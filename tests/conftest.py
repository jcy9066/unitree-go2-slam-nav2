"""Copied entry points with synthetic ROS boundaries; no robot or external overlay."""
import json
import os
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest


@pytest.fixture
def runtime_project(tmp_path):
    source = Path(__file__).resolve().parents[1]
    root = tmp_path / 'repo'
    scripts = root / 'scripts'
    scripts.mkdir(parents=True)
    for name in ('run_mapping.sh', 'run_nav.sh'):
        shutil.copyfile(source / name, root / name)
    shutil.copyfile(source / 'environment.json', root / 'environment.json')
    helpers = (source / 'scripts/_env.sh').read_text()
    helpers += '''
go2_load_environment() {
    echo environment >> "$COMMAND_LOG"
    GO2_PYTHON=/usr/bin/python3
}
go2_require_network() {
    [[ "${FIXTURE_OFFLINE:-0}" != 1 ]] || { echo 'Offline interface' >&2; return 1; }
}
'''
    (scripts / '_env.sh').write_text(helpers)
    preflight = (source / 'scripts/mapping_preflight.py').read_text()
    preflight = preflight.replace("if __name__ == '__main__':", '''
def sensor_check(mode, timeout):
    import os
    with open(os.environ['COMMAND_LOG'], 'a') as stream:
        stream.write(mode + '\\n')
    return int(os.environ.get('FIXTURE_' + mode.upper(), '0'))

if __name__ == '__main__':
''')
    (scripts / 'mapping_preflight.py').write_text(preflight)
    (scripts / 'nav_health.py').write_text(
        "import os,sys\nwith open(os.environ['COMMAND_LOG'],'a') as f:f.write('health '+repr(sys.argv[1:])+'\\n')\n")
    binaries = tmp_path / 'bin'
    binaries.mkdir()
    ros = binaries / 'ros2'
    ros.write_text('''#!/usr/bin/python3
import json,os,signal,sqlite3,sys,time
from pathlib import Path
args=sys.argv[1:]
def record(value):
    with open(os.environ['COMMAND_LOG'],'a') as stream: stream.write(value+'\n')
record(json.dumps(args))
if args[:2]==['node','list']:
    if os.environ.get('FIXTURE_EXISTING_BRIDGE')=='1': print('/sport_ctrl')
    raise SystemExit(0)
if args[:2]==['run','go2_cmd_processor']: raise SystemExit(0)
path=Path(next(a.split(':=',1)[1] for a in args if a.startswith('database_path:=')))
mapping='mapping.launch.py' in args
kind=os.environ.get('FIXTURE_DB_KIND','valid')
def save():
    if not mapping:return
    if kind=='corrupt':path.write_bytes(b'corrupt');return
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE Node(id INTEGER)')
        if kind!='empty':db.execute('INSERT INTO Node VALUES(1)')
def stop(*_):
    save();record('launch_closed');raise SystemExit(0)
signal.signal(signal.SIGINT,stop)
record('launch_started')
if os.environ.get('FIXTURE_WAIT')=='1':
    while True:time.sleep(.03)
save()
raise SystemExit(2 if kind=='launchfail' else 0)
'''.replace("value+'\n'", "value+'\\n'"))
    ros.chmod(0o755)
    ssh = binaries / 'ssh'
    ssh.write_text('#!/bin/bash\necho UNEXPECTED_SSH >> "$COMMAND_LOG"\nexit 99\n')
    ssh.chmod(0o755)
    log = tmp_path / 'calls'
    env = dict(os.environ, PATH=str(binaries) + ':' + os.environ['PATH'],
               COMMAND_LOG=str(log), GO2_MAP_DIR=str(tmp_path / 'maps'), DISPLAY=':fixture')
    env.pop('GO2_ENABLE_MOTION', None)
    env.pop('GO2_LOCALIZATION_PROFILE', None)
    return SimpleNamespace(root=root, scripts=scripts, log=log, env=env,
                           calls=lambda: log.read_text() if log.exists() else '')
