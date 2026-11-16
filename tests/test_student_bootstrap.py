"""No apt/SSH/ROS startup: validate novice command boundaries with fake executables."""
import os
import json
from pathlib import Path
import subprocess

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'


def run(script, *args, env=None):
    return subprocess.run(['bash', str(SCRIPTS / script), *args],
                          env=env, text=True, capture_output=True, timeout=12)


def test_plan_survives_conda_and_makes_no_files(tmp_path):
    env = dict(os.environ, CONDA_PREFIX='/nonexistent/conda',
               PYTHONHOME='/nonexistent/python', PYTHONPATH='/nonexistent/site')
    before = set(tmp_path.iterdir())
    result = run('install_student.sh', 'plan', env=env)
    assert result.returncode == 0, result.stderr
    manifest = json.loads((SCRIPTS.parent / 'environment.json').read_text())
    assert 'Python ' + manifest['conda']['python'] in result.stdout
    assert 'Conda default envs directory' in result.stdout
    assert 'No apt, clone, build' in result.stdout
    assert set(tmp_path.iterdir()) == before


def test_unsafe_paths_and_invalid_options_rejected():
    for args in [('install', '--prefix', '/'), ('plan', '--prefix', str(Path.home())),
                 ('install', '--interface', 'eth0;touch x'), ('install', '--ref', '--force'),
                 ('delete',), ('install', '--prefix')]:
        assert run('install_student.sh', *args).returncode != 0


def test_inactive_environment_stops_before_ros(tmp_path):
    env = {key: value for key, value in os.environ.items() if key not in {'CONDA_PREFIX', 'CONDA_DEFAULT_ENV'}}
    result = run('student_session.sh', 'view', '/tmp/not-a-map.db', env=env)
    assert result.returncode != 0
    assert 'conda activate go2_nav2' in result.stderr


def session_fixture(tmp_path, iface='lo', existing=False):
    bindir = tmp_path / 'bin'
    bindir.mkdir()
    logfile = tmp_path / 'commands.txt'
    ros = bindir / 'ros2'
    ros.write_text('#!/bin/bash\nprintf "%s\\n" "$*" >> "$COMMAND_LOG"\n'
                   + ('if [[ "$1 $2" == "node list" ]]; then echo /sport_ctrl; fi\n' if existing else ''))
    ros.chmod(0o755)
    prefix = tmp_path / 'go2_nav2'
    (prefix / 'bin').mkdir(parents=True)
    python = prefix / 'bin' / 'python'
    python.write_text('#!/bin/bash\n'
                      'if [[ "$1" == */environment.py && "$2" == verify ]]; then exit 0; fi\n'
                      'exec /usr/bin/python3 "$@"\n')
    python.chmod(0o755)
    (bindir / 'python3').symlink_to(python)
    return dict(os.environ, CONDA_PREFIX=str(prefix), CONDA_DEFAULT_ENV='go2_nav2',
                GO2_NET_IFACE=iface, PATH=str(bindir) + ':' + os.environ['PATH'],
                COMMAND_LOG=str(logfile)), logfile


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


def test_conda_loader_does_not_require_system_workspace(tmp_path):
    env, log = session_fixture(tmp_path)
    env['GO2_WS_ROOT'] = '/nonexistent/system-workspace'
    result = subprocess.run(['bash', '-c', 'source "$1"; printf "%s" "$GO2_WS_ROOT"',
                             'test', str(SCRIPTS / '_env.sh')], env=env,
                            text=True, capture_output=True, timeout=12)
    assert result.returncode == 0, result.stderr
    assert result.stdout == env['CONDA_PREFIX']
    assert not log.exists()


def test_other_conda_environment_is_rejected_before_ros(tmp_path):
    env, log = session_fixture(tmp_path)
    env['CONDA_PREFIX'] = str(tmp_path / 'other-environment')
    result = subprocess.run(['bash', '-c', 'source "$1"', 'test', str(SCRIPTS / '_env.sh')],
                            env=env, text=True, capture_output=True, timeout=12)
    assert result.returncode != 0
    assert 'conda activate go2_nav2' in result.stderr
    assert not log.exists()
