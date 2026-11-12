"""Exercise startup/cleanup with fake SSH and sensors; never contact hardware."""
import importlib.util
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import time

import pytest

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location('mapping_preflight', ROOT/'scripts/mapping_preflight.py')
preflight = importlib.util.module_from_spec(spec); spec.loader.exec_module(preflight)


@pytest.mark.parametrize('nodes', [0, 2])
def test_database_is_read_only_and_requires_nodes(tmp_path, nodes):
    db = tmp_path/'map.db'
    with sqlite3.connect(db) as conn:
        conn.execute('CREATE TABLE Node(id INTEGER)')
        conn.executemany('INSERT INTO Node VALUES (?)', [(n,) for n in range(nodes)])
    before = db.read_bytes(); stamp = db.stat().st_mtime_ns
    if nodes:
        assert preflight.validate_database(db)['nodes'] == nodes
    else:
        with pytest.raises(ValueError, match='no RTAB-Map nodes'):
            preflight.validate_database(db)
    assert db.read_bytes() == before and db.stat().st_mtime_ns == stamp


def test_corrupt_db_is_not_a_saved_map(tmp_path):
    db = tmp_path/'map.db'; db.write_bytes(b'not SQLite')
    with pytest.raises(sqlite3.Error):
        preflight.validate_database(db)


@pytest.mark.parametrize('kind', ['valid', 'empty', 'corrupt', 'launchfail'])
def test_latest_map_only_advances_after_successful_populated_db(tmp_path, kind):
    scripts = tmp_path/'scripts'; scripts.mkdir()
    for name in ['run_mapping.sh', 'mapping_preflight.py']:
        (scripts/name).write_bytes((ROOT/'scripts'/name).read_bytes())
    (scripts/'_env.sh').write_text('''ros2() {
python3 - "$DB" "$GO2_FIXTURE_KIND" <<'PY'
import sqlite3,sys,pathlib
p,k=sys.argv[1:]
if k=='corrupt':pathlib.Path(p).write_bytes(b'corrupt')
else:
 with sqlite3.connect(p) as c:
  c.execute('CREATE TABLE Node(id INTEGER)')
  if k!='empty':c.execute('INSERT INTO Node VALUES (1)')
PY
[[ "$GO2_FIXTURE_KIND" != launchfail ]]
}
''')
    maps=tmp_path/'maps'; maps.mkdir(); pointer=maps/'.last_map'; pointer.write_text('previous-map.db\n')
    db=maps/'new.db'
    env=dict(os.environ,GO2_MAP_DIR=str(maps),GO2_FIXTURE_KIND=kind)
    result=subprocess.run(['bash',str(scripts/'run_mapping.sh'),str(db)],env=env,capture_output=True,text=True,timeout=8)
    assert pointer.read_text() == (str(db)+'\n' if kind=='valid' else 'previous-map.db\n')
    assert db.exists(), 'Failed partial DB must remain available for diagnosis'
    if kind!='valid':assert result.returncode != 0


def fixture(tmp_path):
    scripts=tmp_path/'repo/scripts';scripts.mkdir(parents=True)
    carrier=tmp_path/'carrier';carrier.write_text('1')
    source=(ROOT/'scripts/laptop_slam.sh').read_text().replace('/sys/class/net/eno1/carrier',str(carrier))
    (scripts/'laptop_slam.sh').write_text(source)
    (scripts/'_env.sh').write_text('echo env >> "$GO2_FIXTURE_LOG"\n')
    (scripts/'go2_camera_session.sh').write_text('# synthetic camera fixture\n')
    (scripts/'mapping_preflight.py').write_text('''import os,sys
with open(os.environ['GO2_FIXTURE_LOG'],'a') as f:f.write(sys.argv[1]+'\\n')
raise SystemExit(int(os.environ.get('FIXTURE_'+sys.argv[1].upper(),'0')))
''')
    (scripts/'mapping.py').write_text('''import os,signal,time
def record(s):
 with open(os.environ['GO2_FIXTURE_LOG'],'a') as f:f.write(s+'\\n')
def stop(*_):record('mapping_closed');raise SystemExit(0)
signal.signal(signal.SIGINT,stop)
record('mapping_started')
if os.environ.get('FIXTURE_WAIT')=='1':
 while True:time.sleep(.05)
''')
    (scripts/'run_mapping.sh').write_text('exec python3 "$(dirname "$0")/mapping.py"\n')
    binaries=tmp_path/'bin';binaries.mkdir()
    ssh=binaries/'ssh';ssh.write_text('''#!/usr/bin/env python3
import os,signal,time,pathlib
log=pathlib.Path(os.environ['GO2_FIXTURE_LOG'])
def record(s):
 with log.open('a') as f:f.write(s+'\\n')
def stop(*_):record('ssh_closed');raise SystemExit(0)
signal.signal(signal.SIGTERM,stop)
record('ssh_started')
while True:time.sleep(.03)
''');ssh.chmod(0o755)
    log=tmp_path/'calls'
    env=dict(os.environ,PATH=str(binaries)+':'+os.environ['PATH'],GO2_MAP_DIR=str(tmp_path/'maps'),
             GO2_FIXTURE_LOG=str(log),FIXTURE_CAMERA='1',ROS_DOMAIN_ID='81')
    return scripts,log,env


def test_plan_does_not_build_connect_or_create_maps(tmp_path):
    scripts,log,env=fixture(tmp_path)
    r=subprocess.run(['bash',str(scripts/'laptop_slam.sh'),'plan'],env=env,capture_output=True,text=True,timeout=3)
    assert r.returncode==0 and 'No build, SSH, ROS nodes' in r.stdout
    assert not log.exists() and not (tmp_path/'maps').exists()


@pytest.mark.parametrize('mode', ['check','existing-camera','blocked','missing-camera','stale-camera'])
def test_startup_reuses_camera_and_blocks_conflicts(tmp_path,mode):
    scripts,log,env=fixture(tmp_path)
    if mode=='existing-camera':env['FIXTURE_CAMERA']='0'
    if mode=='blocked':env['FIXTURE_IDLE']='2'
    if mode=='missing-camera':env['GO2_CAMERA_MODE']='existing'
    if mode=='stale-camera':env['FIXTURE_CAMERA']='3'
    r=subprocess.run(['bash',str(scripts/'laptop_slam.sh'),'check' if mode=='check' else 'start'],env=env,capture_output=True,text=True,timeout=5)
    calls=log.read_text()
    assert 'ssh_started' not in calls
    assert ('mapping_started' in calls)==(mode=='existing-camera')
    assert (r.returncode==0)==(mode in {'check','existing-camera'})


def test_ctrl_c_cleanup_only_stops_owned_mapping_and_ssh(tmp_path):
    scripts,log,env=fixture(tmp_path);env['FIXTURE_WAIT']='1'
    unrelated=subprocess.Popen(['sleep','30'])
    process=subprocess.Popen(['bash',str(scripts/'laptop_slam.sh'),'start'],env=env,
                             stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,start_new_session=True)
    try:
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            text=log.read_text() if log.exists() else ''
            if 'mapping_started' in text and 'ssh_started' in text:break
            time.sleep(.03)
        else:raise AssertionError('Fixture never reached Mapping: '+text)
        process.send_signal(signal.SIGINT);process.communicate(timeout=5)
        text=log.read_text();assert 'mapping_closed' in text and 'ssh_closed' in text
        assert unrelated.poll() is None
    finally:
        if process.poll() is None:os.killpg(process.pid,signal.SIGTERM);process.wait(timeout=5)
        unrelated.terminate();unrelated.wait(timeout=3)


def test_remote_pty_hangup_stops_only_owned_camera(tmp_path):
    scripts,log,env=fixture(tmp_path)
    # Use a synthetic activation file and ros2 executable, without changing HOME.
    activate=tmp_path/'activate.bash';activate.write_text('export ROS_DISTRO=foxy\n')
    ros2=tmp_path/'bin/ros2'
    ros2.write_text((scripts/'mapping.py').read_text().replace('mapping_', 'camera_'))
    ros2.write_text('#!/usr/bin/env python3\n'+ros2.read_text());ros2.chmod(0o755)
    payload=tmp_path/'camera.sh';payload.write_text((ROOT/'scripts/go2_camera_session.sh').read_text().replace('$HOME/ros2_realsense_456_ws/activate.bash',str(activate)))
    env['FIXTURE_WAIT']='1'
    process=subprocess.Popen(['bash',str(payload),'81'],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,start_new_session=True)
    try:
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            if log.exists() and 'camera_started' in log.read_text():break
            time.sleep(.03)
        else:raise AssertionError('Camera fixture never started')
        # Check the actual child environment, not just the shell's source text.
        children=(Path(f'/proc/{process.pid}/task/{process.pid}/children').read_text().split())
        assert children
        child_env=Path(f'/proc/{children[0]}/environ').read_bytes().split(b'\0')
        assert b'RMW_IMPLEMENTATION=rmw_cyclonedds_cpp' in child_env
        process.send_signal(signal.SIGHUP);process.communicate(timeout=5)
        assert 'camera_closed' in log.read_text()
    finally:
        if process.poll() is None:os.killpg(process.pid,signal.SIGTERM);process.wait(timeout=5)
