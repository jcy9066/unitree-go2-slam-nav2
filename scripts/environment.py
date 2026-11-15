#!/usr/bin/env python3
"""Conda setup driven by environment.json. Does not start ROS nodes or motion."""
import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
OVERLAY_VARS = ('PYTHONHOME', 'PYTHONPATH', 'AMENT_PREFIX_PATH', 'COLCON_PREFIX_PATH',
                'CMAKE_PREFIX_PATH', 'LD_LIBRARY_PATH', 'LD_PRELOAD', 'ROS_DISTRO',
                'ROS_VERSION', 'CONDA_PREFIX', 'CONDA_DEFAULT_ENV', 'CONDA_SHLVL', 'BASH_ENV', 'ENV')


class SetupError(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise SetupError(message)


def package_name(spec):
    match = re.match(r'^[A-Za-z0-9_.-]+', spec)
    require(match is not None and not spec.startswith('-') and '\n' not in spec,
            'Invalid package specification')
    return match.group()


def relative_path(value):
    path = Path(value)
    require(value and not path.is_absolute() and '..' not in path.parts,
            'Manifest paths must be relative and cannot contain ..')
    return path


def audit_metadata(config, root, required=False):
    available = {package_name(x) for x in config['conda']['packages']}
    source_packages = set(config['project']['packages'])
    for source in config['sources']:
        source_packages.update(source['packages'])
    overrides = config.get('rosdep_conda_overrides', {})
    missing = []
    for package in config['project']['packages']:
        path = root / package / 'package.xml'
        if not path.is_file():
            require(not required, 'Missing ROS package metadata: ' + str(path))
            continue
        for node in ET.parse(path).getroot():
            if node.tag not in {'depend', 'exec_depend', 'build_depend', 'buildtool_depend', 'test_depend'}:
                continue
            key = node.text.strip()
            if key in source_packages:
                continue
            provider = overrides.get(key, 'ros-humble-' + key.replace('_', '-'))
            if provider not in available:
                missing.append(key + ' -> ' + provider)
    require(not missing, 'environment.json is missing providers: ' + ', '.join(sorted(set(missing))))


def load_config(path, root=None):
    config = json.loads(Path(path).read_text())
    require(config.get('schema_version') == 1, 'Unsupported environment schema')
    conda = config['conda']
    require(conda['name'] == 'go2_nav2', 'The project environment must be go2_nav2')
    require(re.fullmatch(r'3\.\d+\.\d+', conda['python']), 'Pin an exact Python version')
    require(conda['channel_priority'] == 'strict', 'Strict channel priority is required')
    require(conda['solver'] in {'libmamba', 'classic'}, 'Unknown Conda solver')
    require(conda['channels'] and all(re.fullmatch(r'[A-Za-z0-9_-]+', c) for c in conda['channels']),
            'Use named public Conda channels')
    require(conda['packages'], 'Conda package list is empty')
    for spec in conda['packages'] + conda['pip']:
        package_name(spec)
    require('python' not in {package_name(s) for s in conda['packages']},
            'Declare Python only in conda.python')
    require(config['build']['jobs'] > 0, 'Build jobs must be positive')
    for value in config.get('paths', {}).values():
        relative_path(value)
    names = set()
    for source in config['sources']:
        require(re.fullmatch(r'[a-z][a-z0-9_]*', source['name']), 'Invalid source name')
        require(source['name'] not in names, 'Duplicate source name')
        names.add(source['name'])
        require(re.fullmatch(r'[0-9a-f]{40}', source['ref']), 'Pin external sources to a commit SHA')
        for key in ('source_subpath',):
            relative_path(source[key])
    for source in [config['project'], *config['sources']]:
        require(re.fullmatch(r'https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?', source['url']),
                'Source URLs must be public HTTPS GitHub URLs')
        require(re.fullmatch(r'[A-Za-z0-9_./-]+', source['ref']) and not source['ref'].startswith('-'),
                'Invalid source ref')
        require(source['packages'] and all(re.fullmatch(r'[a-z][a-z0-9_]*', p) for p in source['packages']),
                'Invalid build package name')
    environment = config['activation']['environment']
    for key, value in environment.items():
        require(re.fullmatch(r'[A-Z][A-Z0-9_]*', key) and key not in {'HOME', 'PATH', 'PYTHONHOME', 'PYTHONPATH'},
                'Invalid deployment environment key')
        require(isinstance(value, str) and '\x00' not in value, 'Environment values must be text')
    require(not any(key.startswith('GO2_') or 'SSH' in key for key in environment), 'Robot settings do not belong in setup')
    require(config['completion_message'] == '[env] 환경 신규 구축 및 검증 완료', 'Invalid completion message')
    audit_metadata(config, root or Path(path).resolve().parent)
    return config


def clean_environment():
    env = dict(os.environ)
    for key in OVERLAY_VARS:
        env.pop(key, None)
    env['PATH'] = '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
    env['PYTHONNOUSERSITE'] = '1'
    return env


def conda_executable(explicit=None):
    candidate = explicit or os.environ.get('GO2_CONDA_EXE') or os.environ.get('CONDA_EXE') or shutil.which('conda')
    if not candidate:
        for folder in ('miniconda3', 'miniforge3', 'anaconda3'):
            path = Path.home() / folder / 'bin' / 'conda'
            if path.is_file():
                candidate = str(path)
                break
    require(candidate is not None and Path(candidate).is_file(),
            'Conda was not found. Install Conda or set GO2_CONDA_EXE to its executable.')
    return str(Path(candidate).resolve())


class Installer:
    """Only the named Conda environment is persistent; builds use temporary files."""

    def __init__(self, config, conda, source_root=ROOT):
        self.config, self.conda, self.source_root = config, conda, Path(source_root)
        self.env_prefix = None
        self.env = clean_environment()
        jobs = str(config['build']['jobs'])
        self.env.update(MAKEFLAGS='-j' + jobs, CMAKE_BUILD_PARALLEL_LEVEL=jobs,
                        OPENBLAS_NUM_THREADS=jobs, OMP_NUM_THREADS=jobs)

    @property
    def record_dir(self):
        require(self.env_prefix is not None, 'Conda environment is not selected')
        return self.env_prefix / '.go2_nav2_setup'

    def run(self, command, cwd=None, capture=False):
        if not capture:
            print('[go2 setup] ' + shlex.join([str(x) for x in command]), flush=True)
        result = subprocess.run([str(x) for x in command], cwd=cwd, env=self.env,
                                check=True, text=True, stdout=subprocess.PIPE if capture else None)
        return result.stdout.strip() if capture else None

    def in_conda(self, command, cwd=None, capture=False):
        return self.run([self.conda, 'run', '--no-capture-output',
                         '--prefix', str(self.env_prefix), *command], cwd, capture)

    def find_env(self):
        data = json.loads(self.run([self.conda, 'env', 'list', '--json'], capture=True))
        matches = [Path(p).resolve() for p in data['envs'] if Path(p).name == self.config['conda']['name']]
        require(len(matches) <= 1, 'Multiple go2_nav2 environments found; resolve the name ambiguity first')
        return matches[0] if matches else None


    @staticmethod
    def _version_tuple(value):
        """Numeric version comparison for the simple Conda constraints in environment.json."""
        parts = [int(part) for part in re.findall(r'\d+', str(value).split('+')[0])]
        return tuple((parts + [0] * 6)[:6])

    def configuration_problems(self):
        """Read-only audit of installed packages, declared versions and ROS runtime."""
        problems = []
        record = self.record_dir / 'installation.json'
        if not record.is_file():
            problems.append('설치 완료 기록이 없습니다')
        else:
            try:
                state = json.loads(record.read_text())
                expected = hashlib.sha256(json.dumps(self.config, sort_keys=True).encode()).hexdigest()
                if state.get('project') != 'unitree-go2-slam-nav2' or not state.get('complete'):
                    problems.append('프로젝트 설치 완료 기록이 유효하지 않습니다')
                if state.get('manifest_sha256') != expected:
                    problems.append('환경 설정(environment.json)이 설치 당시와 다릅니다')
                for source in self.config['sources']:
                    if state.get('source_commits', {}).get(source['name']) != source['ref']:
                        problems.append('외부 소스 버전이 다릅니다: ' + source['name'])
            except (OSError, ValueError, TypeError, KeyError) as error:
                problems.append('설치 기록을 읽을 수 없습니다: ' + str(error))
        installed = json.loads(self.run(
            [self.conda, 'list', '--prefix', str(self.env_prefix), '--json'], capture=True))
        versions = {p['name'].lower(): str(p['version']) for p in installed}
        specs = ['python=' + self.config['conda']['python'], *self.config['conda']['packages']]
        for spec in specs:
            name = package_name(spec)
            actual = versions.get(name.lower())
            if actual is None:
                problems.append('필수 패키지 누락: ' + name)
                continue
            constraints = spec[len(name):]
            for condition in filter(None, constraints.split(',')):
                match = re.fullmatch(r'(>=|<=|==|=|>|<)([A-Za-z0-9_.+-]+)', condition)
                require(match is not None, 'Invalid Conda version constraint: ' + spec)
                operator, wanted = match.groups()
                left, right = self._version_tuple(actual), self._version_tuple(wanted)
                accepted = {'=': left == right, '==': left == right,
                            '>=': left >= right, '<=': left <= right,
                            '>': left > right, '<': left < right}[operator]
                if not accepted:
                    problems.append('버전 불일치: ' + name + ' (' + actual + ' / ' + condition + ')')
        try:
            variables = json.loads(self.run(
                [self.conda, 'env', 'config', 'vars', 'list',
                 '--name', self.config['conda']['name'], '--json'], capture=True))
            for key, wanted in self.config['activation']['environment'].items():
                if variables.get(key) != wanted:
                    problems.append('Conda 환경 변수 불일치: ' + key)
        except (ValueError, subprocess.CalledProcessError) as error:
            problems.append('Conda 환경 변수를 검증할 수 없습니다: ' + str(error))
        if self.config['conda']['pip']:
            try:
                listed = json.loads(self.in_conda(['python', '-m', 'pip', 'list', '--format=json'], capture=True))
                pip_versions = {p['name'].lower().replace('_', '-'): p['version'] for p in listed}
                for spec in self.config['conda']['pip']:
                    if package_name(spec).lower().replace('_', '-') not in pip_versions:
                        problems.append('pip 패키지 누락: ' + package_name(spec))
            except (ValueError, subprocess.CalledProcessError) as error:
                problems.append('pip 패키지 검증 실패: ' + str(error))
        if not problems:
            try:
                self.verify()
            except subprocess.CalledProcessError:
                problems.append('ROS 2 모듈·메시지·플러그인 실행 검증 실패')
        return problems

    def create_environment(self):
        existing = self.find_env()
        # The caller explicitly requests consent before modifying an existing environment.
        if existing:
            self.env_prefix = existing
            self.save_state(complete=False)
        conda = self.config['conda']
        command = [self.conda, 'install' if existing else 'create', '--yes', '--name', conda['name'],
                   '--override-channels', '--strict-channel-priority', '--solver', conda['solver']]
        for channel in conda['channels']:
            command += ['--channel', channel]
        command += ['python=' + conda['python'], *conda['packages']]
        self.run(command)
        self.env_prefix = self.find_env()
        require(self.env_prefix is not None, 'Conda did not create the requested environment')
        self.record_dir.mkdir(exist_ok=True)
        self.save_state(complete=False)
        variables = [key + '=' + value for key, value in self.config['activation']['environment'].items()]
        if variables:
            self.run([self.conda, 'env', 'config', 'vars', 'set', '--name', conda['name'], *variables])
        if conda['pip']:
            self.in_conda(['python', '-m', 'pip', 'install', *conda['pip']])

    def save_state(self, complete, revisions=None):
        state = {'project': 'unitree-go2-slam-nav2', 'complete': complete,
                 'environment_name': self.config['conda']['name'],
                 'manifest_sha256': hashlib.sha256(json.dumps(self.config, sort_keys=True).encode()).hexdigest(),
                 'source_commits': revisions or {}}
        (self.record_dir / 'installation.json').write_text(json.dumps(state, indent=2) + '\n')

    def clone(self, source, target):
        self.in_conda(['git', 'clone', '--no-checkout', source['url'], str(target)])
        self.in_conda(['git', 'fetch', 'origin', source['ref']], cwd=target)
        revision = self.in_conda(['git', 'rev-parse', 'FETCH_HEAD'], cwd=target, capture=True)
        require(revision == source['ref'], 'External source commit does not match the manifest')
        self.in_conda(['git', 'checkout', '--detach', revision], cwd=target)
        return revision

    def build(self, workspace, base_path, packages, label):
        workspace.mkdir(parents=True, exist_ok=True)
        python = str(self.env_prefix / 'bin' / 'python')
        command = ['colcon', '--log-base', str(self.record_dir / 'build-logs' / label),
                   'build', '--base-paths', str(base_path), '--packages-select', *packages,
                   '--executor', 'sequential', '--merge-install', '--install-base', str(self.env_prefix),
                   '--cmake-args', *self.config['build']['cmake_args'],
                   '-DPython_EXECUTABLE=' + python, '-DPython3_EXECUTABLE=' + python]
        # Install copies rather than symlinks so temporary build sources can be removed.
        self.in_conda(command, cwd=workspace)

    def verify(self):
        code = '''import importlib, json, sys
from pathlib import Path
from ament_index_python.packages import get_package_prefix, get_package_share_directory
d=json.loads(sys.argv[1])
assert str(Path(sys.prefix).resolve()) == d['prefix'], 'Wrong Conda interpreter'
assert '.'.join(map(str,sys.version_info[:3])) == d['python'], 'Wrong Python version'
for module in d['checks']['python_modules']: importlib.import_module(module)
for module, names in d['checks']['python_symbols'].items():
    for name in names: getattr(importlib.import_module(module), name)
assert Path(importlib.import_module('rclpy').__file__).resolve().is_relative_to(Path(sys.prefix)), 'System rclpy leaked in'
for package in d['checks']['ros_packages']:
    assert Path(get_package_prefix(package)).resolve().is_relative_to(Path(sys.prefix)), 'System ROS overlay leaked in: '+package
for plugin in d['checks']['plugins']:
    root=Path(get_package_share_directory(plugin['package']))
    assert any(plugin['class'] in p.read_text() for p in root.rglob('*.xml')), 'Missing plugin '+plugin['class']
pass  # Validation is silent when all checks succeed; sensor and physical tests remain separate.
'''
        payload = {'prefix': str(self.env_prefix), 'python': self.config['conda']['python'],
                   'checks': self.config['verification']}
        self.in_conda(['python', '-c', code, json.dumps(payload)], capture=True)

    def install(self):
        require(os.geteuid() != 0, 'Run setup as your normal user, not root')
        require(sys.platform == self.config['host']['os'] and platform.machine() in self.config['host']['architectures'],
                'Unsupported host platform')
        release = dict(line.strip().split('=', 1) for line in Path('/etc/os-release').read_text().splitlines() if '=' in line)
        require(release.get('ID', '').strip('"') == 'ubuntu' and release.get('VERSION_ID', '').strip('"') == self.config['host']['ubuntu'],
                'This environment targets the recorded Ubuntu version')
        audit_metadata(self.config, self.source_root, required=True)
        existing = self.find_env()
        if existing:
            self.env_prefix = existing
            problems = self.configuration_problems()
            if not problems:
                print('[env] 기존 환경 검증 완료')
                return
            print('[env] 기존 환경의 설정 차이가 발견되었습니다:')
            for problem in problems:
                print(' - ' + problem)
            if not sys.stdin.isatty():
                raise SetupError('대화형 터미널에서 수정 여부를 y/n으로 선택해야 합니다. 환경은 변경하지 않았습니다.')
            answer = input('[env] 기존 환경을 수정하시겠습니까? (y/n): ').strip().lower()
            if answer != 'y':
                raise SetupError('수정하지 않고 종료했습니다. 기존 환경은 변경되지 않았습니다.')
        self.create_environment()
        revisions = {}
        with tempfile.TemporaryDirectory(prefix='go2-nav2-build-') as temporary:
            scratch = Path(temporary)
            for source in self.config['sources']:
                target = scratch / source['name']
                revisions[source['name']] = self.clone(source, target)
                self.build(scratch / (source['name'] + '-build'),
                           target / source['source_subpath'], source['packages'], source['name'])
            self.build(scratch / 'project-build', self.source_root,
                       self.config['project']['packages'], 'project')
        if (self.source_root / '.git').exists():
            revisions['project'] = self.in_conda(['git', 'rev-parse', 'HEAD'], cwd=self.source_root, capture=True)
        self.verify()
        resolved = self.run([self.conda, 'list', '--prefix', str(self.env_prefix), '--explicit'], capture=True)
        (self.record_dir / 'conda-resolved.txt').write_text(resolved + '\n')
        (self.record_dir / 'environment-installed.json').write_text(json.dumps(self.config, indent=2) + '\n')
        self.save_state(complete=True, revisions=revisions)
        if existing:
            print('[env] 기존 환경 수정 및 검증 완료')
        else:
            print(self.config['completion_message'])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', nargs='?', default='install', choices=['install', 'plan', 'verify', 'validate', 'vcs'])
    parser.add_argument('--manifest', type=Path, default=ROOT / 'environment.json')
    parser.add_argument('--conda-exe')
    args = parser.parse_args(argv)
    config = load_config(args.manifest)
    if args.mode == 'validate':
        print('environment.json and ROS metadata: PASS')
        return
    if args.mode == 'vcs':
        print('# Generated from environment.json by scripts/environment.py vcs.\nrepositories:')
        for source in config['sources']:
            print('  ' + source['name'] + ':\n    type: git\n    url: ' + source['url'] + '\n    version: ' + source['ref'])
        return
    if args.mode == 'plan':
        print('Environment: ' + config['conda']['name'] + ' / Python ' + config['conda']['python'])
        print('Location: Conda default envs directory (--name); no repository environment or separate install prefix.')
        print('Conda packages: ' + ', '.join(['python=' + config['conda']['python'], *config['conda']['packages']]))
        print('Build: ' + ', '.join(p for s in config['sources'] for p in s['packages']) + ', ' + ', '.join(config['project']['packages']))
        print('Temporary source builds install into the Conda environment.')
        print('No apt, clone, build, Conda creation, SSH, network change, ROS startup or motion executed.')
        return
    installer = Installer(config, conda_executable(args.conda_exe))
    if args.mode == 'install':
        installer.install()
    else:
        installer.env_prefix = installer.find_env()
        require(installer.env_prefix is not None, 'go2_nav2 is missing')
        problems = installer.configuration_problems()
        require(not problems, 'Conda 환경 검증 실패: ' + '; '.join(problems))


if __name__ == '__main__':
    try:
        main()
    except (SetupError, OSError, ValueError, TypeError, KeyError, ET.ParseError, subprocess.CalledProcessError) as error:
        print('ERROR: ' + str(error), file=sys.stderr)
        raise SystemExit(1)
