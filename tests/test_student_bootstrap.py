"""No apt/SSH/ROS startup: validate novice command boundaries with fake executables."""
import os
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'scripts'


def run(script, *args, env=None):
    root = Path((env or {}).get('FIXTURE_REPO_ROOT', ROOT))
    return subprocess.run(['bash', str(root / script), *args],
                          env=env, text=True, capture_output=True, timeout=12)


def test_plan_survives_conda_and_makes_no_files(tmp_path):
    env = dict(os.environ, CONDA_PREFIX='/nonexistent/conda',
               PYTHONHOME='/nonexistent/python', PYTHONPATH='/nonexistent/site')
    before = set(tmp_path.iterdir())
    result = run('install_student.sh', 'plan', env=env)
    assert result.returncode == 0, result.stderr
    manifest = json.loads((ROOT / 'environment.json').read_text())
    assert 'Python ' + manifest['conda']['python'] in result.stdout
    assert 'Conda default envs directory' in result.stdout
    assert 'No apt, clone, build' in result.stdout
    assert set(tmp_path.iterdir()) == before


def test_unsafe_paths_and_invalid_options_rejected():
    for args in [('install', '--prefix', '/'), ('plan', '--prefix', str(Path.home())),
                 ('install', '--interface', 'eth0;touch x'), ('install', '--ref', '--force'),
                 ('delete',), ('install', '--prefix')]:
        assert run('install_student.sh', *args).returncode != 0


def test_wrong_environment_stops_before_ros(tmp_path):
    env = dict(os.environ, CONDA_PREFIX=str(tmp_path / 'other-environment'))
    result = run('run_nav.sh', 'check', env=env)
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
    root = tmp_path / 'repo'
    (root / 'scripts').mkdir(parents=True)
    for name in ['run_nav.sh', 'run_mapping.sh']:
        (root / name).write_bytes((ROOT / name).read_bytes())
    (root / 'environment.json').write_bytes((ROOT / 'environment.json').read_bytes())
    network = tmp_path / 'net'
    (network / 'fixture0').mkdir(parents=True)
    (network / 'fixture0/carrier').write_text('1')
    (root / 'scripts/_env.sh').write_text((SCRIPTS / '_env.sh').read_text().replace('/sys/class/net', str(network)))
    return dict(os.environ, FIXTURE_REPO_ROOT=str(root), CONDA_PREFIX=str(prefix), CONDA_DEFAULT_ENV='go2_nav2',
                GO2_NET_IFACE=iface, PATH=str(bindir) + ':' + os.environ['PATH'],
                COMMAND_LOG=str(logfile)), logfile


def test_offline_interface_blocks_all_live_modes(tmp_path):
    env, log = session_fixture(tmp_path)
    original = tmp_path / 'inert.db'; original.write_bytes(b'inert map')
    for script, args in [('run_mapping.sh', ['sensors']), ('run_mapping.sh', ['start']),
                         ('run_nav.sh', ['view', str(original)]), ('run_nav.sh', ['bridge']),
                         ('run_nav.sh', ['health'])]:
        result = run(script, *args, env=env)
        assert result.returncode != 0
        assert 'Offline interface' in result.stderr
    assert not log.exists()


def test_bridge_starts_disabled_and_remapped(tmp_path):
    iface = 'fixture0'
    env, log = session_fixture(tmp_path, iface)
    result = run('run_nav.sh', 'bridge', env=env)
    assert result.returncode == 0, result.stderr
    text = log.read_text()
    assert 'enabled:=false' in text
    assert 'cmd_vel:=/go2_nav/cmd_vel' in text
    assert 'enabled:=true' not in text
    assert 'send_goal' not in text and 'topic pub' not in text


def test_duplicate_bridge_rejected(tmp_path):
    iface = 'fixture0'
    env, log = session_fixture(tmp_path, iface, existing=True)
    result = run('run_nav.sh', 'bridge', env=env)
    assert result.returncode != 0
    assert 'already exists' in result.stderr
    assert 'run go2_cmd_processor' not in log.read_text()


def test_conda_loader_does_not_require_system_workspace(tmp_path):
    env, log = session_fixture(tmp_path)
    env['GO2_WS_ROOT'] = '/nonexistent/system-workspace'
    result = subprocess.run(['bash', '-c', 'source "$1"; go2_load_environment; printf "%s" "$GO2_WS_ROOT"',
                             'test', str(SCRIPTS / '_env.sh')], env=env,
                            text=True, capture_output=True, timeout=12)
    assert result.returncode == 0, result.stderr
    assert result.stdout == env['CONDA_PREFIX']
    assert not log.exists()


def test_other_conda_environment_is_rejected_before_ros(tmp_path):
    env, log = session_fixture(tmp_path)
    env['CONDA_PREFIX'] = str(tmp_path / 'other-environment')
    result = subprocess.run(['bash', '-c', 'source "$1"; go2_load_environment', 'test', str(SCRIPTS / '_env.sh')],
                            env=env, text=True, capture_output=True, timeout=12)
    assert result.returncode != 0
    assert 'conda activate go2_nav2' in result.stderr
    assert not log.exists()


def test_shell_layout_is_four_root_entrypoints_and_one_internal_helper():
    assert {p.name for p in ROOT.glob('*.sh')} == {
        'install_student.sh', 'setup_maps.sh', 'run_mapping.sh', 'run_nav.sh'}
    assert {p.name for p in SCRIPTS.glob('*.sh')} == {'_env.sh'}
