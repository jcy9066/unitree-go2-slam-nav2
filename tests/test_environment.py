"""Offline setup regression checks: no package installation, ROS nodes or motion."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('go2_environment', ROOT / 'scripts/environment.py')
environment = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(environment)


@pytest.fixture
def config():
    return environment.load_config(ROOT / 'environment.json')


class FakeInstaller(environment.Installer):
    """Fake only the external command boundary, keeping install orchestration real."""

    def __init__(self, config, tmp_path, failure=None):
        super().__init__(config, '/fake/conda', source_root=ROOT)
        self.target = tmp_path / 'conda-default/envs/go2_nav2'
        self.failure = failure
        self.commands = []
        self.build_directories = []

    def run(self, command, cwd=None, capture=False):
        command = [str(x) for x in command]
        self.commands.append(command)
        if command[1:4] == ['env', 'list', '--json']:
            return json.dumps({'envs': [str(self.target)] if self.target.exists() else []})
        if command[1] in {'create', 'install'}:
            assert command[command.index('--name') + 1] == 'go2_nav2'
            assert '--prefix' not in command
            if self.failure == 'create':
                raise subprocess.CalledProcessError(1, command)
            self.target.mkdir(parents=True, exist_ok=True)
        elif command[1:5] == ['env', 'config', 'vars', 'set']:
            assert all('SSH' not in x and 'NET_IFACE' not in x for x in command)
        elif command[1] == 'list':
            if self.failure == 'record':
                raise subprocess.CalledProcessError(1, command)
            return '@EXPLICIT\nhttps://example.invalid/test-package.conda'
        elif command[1] == 'run':
            assert command[command.index('--prefix') + 1] == str(self.target)
            args = command[command.index('--prefix') + 2:]
            if args[:2] == ['git', 'clone']:
                if self.failure == 'clone':
                    raise subprocess.CalledProcessError(1, command)
                Path(args[-1]).mkdir()
            elif args[:3] == ['git', 'rev-parse', 'FETCH_HEAD']:
                return next(s['ref'] for s in self.config['sources'] if s['name'] == Path(cwd).name)
            elif args[:3] == ['git', 'rev-parse', 'HEAD']:
                return 'a' * 40
            elif args[0] == 'colcon':
                self.build_directories.append(Path(cwd))
                assert args[args.index('--install-base') + 1] == str(self.target)
                assert '--merge-install' in args and '--symlink-install' not in args
                if self.failure == 'build':
                    raise subprocess.CalledProcessError(1, command)
            elif args[:2] == ['python', '-c']:
                payload = json.loads(args[-1])
                assert payload['prefix'] == str(self.target)
                assert payload['python'] == self.config['conda']['python']
                if self.failure == 'verify':
                    raise subprocess.CalledProcessError(1, command)
        return '' if capture else None


def test_manifest_matches_ros_metadata_and_has_no_device_settings(config):
    environment.audit_metadata(config, ROOT, required=True)
    assert config['conda']['name'] == 'go2_nav2'
    assert 'paths' not in config and 'runtime' not in config
    assert not any(key.startswith('GO2_') for key in config['activation']['environment'])
    assert any('rtabmap_viz' in source['packages'] for source in config['sources'])


def test_missing_dependency_provider_is_rejected(config):
    bad = copy.deepcopy(config)
    bad['conda']['packages'].remove('ros-humble-rclpy')
    with pytest.raises(environment.SetupError, match='rclpy'):
        environment.audit_metadata(bad, ROOT, required=True)


def test_device_settings_are_rejected(config, tmp_path):
    bad = copy.deepcopy(config)
    bad['activation']['environment']['GO2_SSH_TARGET'] = 'operator@device'
    path = tmp_path / 'environment.json'
    path.write_text(json.dumps(bad))
    with pytest.raises(environment.SetupError, match='Robot settings'):
        environment.load_config(path)


def test_plan_makes_no_external_calls_or_files(monkeypatch, capsys, tmp_path):
    def reject(*args, **kwargs):
        raise AssertionError('plan must not call external commands')
    monkeypatch.setattr(environment.subprocess, 'run', reject)
    before = set(tmp_path.iterdir())
    environment.main(['plan'])
    text = capsys.readouterr().out
    assert 'Conda default envs directory (--name)' in text
    assert 'go2_nav2 환경 설정이 완료되었습니다.' not in text
    assert set(tmp_path.iterdir()) == before


def test_no_arguments_selects_install(monkeypatch):
    calls = []
    class StubInstaller:
        def __init__(self, config, conda):
            assert config['conda']['name'] == 'go2_nav2'
        def install(self):
            calls.append('install')
    monkeypatch.setattr(environment, 'Installer', StubInstaller)
    monkeypatch.setattr(environment, 'conda_executable', lambda value: '/fake/conda')
    environment.main([])
    assert calls == ['install']


def test_success_is_printed_only_after_all_builds_and_verification(config, tmp_path, capsys):
    foreign = tmp_path / 'conda-default/envs/unrelated/keep.txt'
    foreign.parent.mkdir(parents=True)
    foreign.write_text('preserve')
    installer = FakeInstaller(config, tmp_path)
    installer.install()
    output = capsys.readouterr().out
    assert output.splitlines()[-1] == config['completion_message']
    assert output.count(config['completion_message']) == 1
    assert json.loads((installer.record_dir / 'installation.json').read_text())['complete'] is True
    assert len(installer.build_directories) == len(config['sources']) + 1
    assert all(not path.exists() for path in installer.build_directories)
    assert foreign.read_text() == 'preserve'
    assert not any('ssh' == arg or arg in {'send_goal', 'pub', 'launch'} for command in installer.commands for arg in command)


@pytest.mark.parametrize('failure', ['create', 'clone', 'build', 'verify', 'record'])
def test_failures_never_print_success_or_leave_completed_state(config, tmp_path, capsys, failure):
    installer = FakeInstaller(config, tmp_path, failure)
    with pytest.raises(subprocess.CalledProcessError):
        installer.install()
    assert config['completion_message'] not in capsys.readouterr().out
    marker = installer.target / '.go2_nav2_setup/installation.json'
    assert not marker.exists() or json.loads(marker.read_text())['complete'] is False
    assert all(not path.exists() for path in installer.build_directories)


def test_unmanaged_existing_environment_is_untouched(config, tmp_path):
    installer = FakeInstaller(config, tmp_path)
    installer.target.mkdir(parents=True)
    sentinel = installer.target / 'keep.txt'
    sentinel.write_text('existing environment')
    with pytest.raises(environment.SetupError, match='unmanaged'):
        installer.install()
    assert sentinel.read_text() == 'existing environment'
    assert not any(command[1] in {'install', 'create'} for command in installer.commands)


def test_failed_managed_update_invalidates_old_completion(config, tmp_path):
    installer = FakeInstaller(config, tmp_path, 'create')
    installer.env_prefix = installer.target
    installer.record_dir.mkdir(parents=True)
    installer.save_state(complete=True)
    with pytest.raises(subprocess.CalledProcessError):
        installer.install()
    assert json.loads((installer.record_dir / 'installation.json').read_text())['complete'] is False
