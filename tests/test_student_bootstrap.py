"""No apt/SSH/ROS startup: validate novice command boundaries with fake executables."""
import os
from pathlib import Path
import subprocess

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'


def run(script, *args, env=None):
    return subprocess.run(['bash', str(SCRIPTS / script), *args],
                          env=env, text=True, capture_output=True, timeout=12)


def test_plan_survives_conda_and_makes_no_files(tmp_path):
    env = dict(os.environ, CONDA_PREFIX='/nonexistent/conda',
               PYTHONHOME='/nonexistent/python', PYTHONPATH='/nonexistent/site')
    prefix = Path.home() / 'ctrlcv' / ('go2_test_' + tmp_path.name)
    assert not prefix.exists()
    result = run('install_student.sh', 'plan', '--prefix', str(prefix), env=env)
    assert result.returncode == 0, result.stderr
    assert 'Python 3.10.' in result.stdout
    assert 'No apt, clone, build' in result.stdout
    assert not prefix.exists()


def test_unsafe_paths_and_invalid_options_rejected():
    for args in [('install', '--prefix', '/'), ('plan', '--prefix', str(Path.home())),
                 ('install', '--interface', 'eth0;touch x'), ('install', '--ref', '--force'),
                 ('delete',), ('install', '--prefix')]:
        assert run('install_student.sh', *args).returncode != 0


def test_missing_installation_stops_before_ros(tmp_path):
    env = dict(os.environ, GO2_STUDENT_ENV=str(tmp_path / 'missing'))
    result = run('student_session.sh', 'view', '/tmp/not-a-map.db', env=env)
    assert result.returncode != 0
    assert 'Missing' in result.stderr


def session_fixture(tmp_path, iface='lo', existing=False):
    bindir = tmp_path / 'bin'
    bindir.mkdir()
    logfile = tmp_path / 'commands.txt'
    ros = bindir / 'ros2'
    ros.write_text('#!/bin/bash\nprintf "%s\\n" "$*" >> "$COMMAND_LOG"\n'
                   + ('if [[ "$1 $2" == "node list" ]]; then echo /sport_ctrl; fi\n' if existing else ''))
    ros.chmod(0o755)
    envfile = tmp_path / 'env.bash'
    envfile.write_text(f'export GO2_REPO_ROOT="{SCRIPTS.parent}"\n'
                       f'export GO2_NET_IFACE="{iface}"\n')
    return dict(os.environ, GO2_SESSION_CLEAN='1', GO2_STUDENT_ENV=str(envfile),
                PATH=str(bindir) + ':' + os.environ['PATH'], COMMAND_LOG=str(logfile)), logfile


def test_offline_interface_blocks_all_live_modes(tmp_path):
    env, log = session_fixture(tmp_path)
    for mode in ('camera', 'sensors', 'map', 'view', 'bridge', 'health'):
        result = run('student_session.sh', mode, env=env)
        assert result.returncode != 0
        assert 'Offline interface' in result.stderr
    assert not log.exists()


def test_bridge_starts_disabled_and_remapped(tmp_path):
    iface = next(p.name for p in Path('/sys/class/net').iterdir() if p.name != 'lo')
    env, log = session_fixture(tmp_path, iface)
    result = run('student_session.sh', 'bridge', env=env)
    assert result.returncode == 0, result.stderr
    text = log.read_text()
    assert 'enabled:=false' in text
    assert 'cmd_vel:=/go2_nav/cmd_vel' in text
    assert 'enabled:=true' not in text
    assert 'send_goal' not in text and 'topic pub' not in text


def test_duplicate_bridge_rejected(tmp_path):
    iface = next(p.name for p in Path('/sys/class/net').iterdir() if p.name != 'lo')
    env, log = session_fixture(tmp_path, iface, existing=True)
    result = run('student_session.sh', 'bridge', env=env)
    assert result.returncode != 0
    assert 'already exists' in result.stderr
    assert 'run go2_cmd_processor' not in log.read_text()
