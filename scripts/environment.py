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
    for value in config['paths'].values():
        relative_path(value)
    names = set()
    for source in config['sources']:
        require(re.fullmatch(r'[a-z][a-z0-9_]*', source['name']), 'Invalid source name')
        require(source['name'] not in names, 'Duplicate source name')
        names.add(source['name'])
        require(re.fullmatch(r'[0-9a-f]{40}', source['ref']), 'Pin external sources to a commit SHA')
        for key in ('workspace', 'source_subpath'):
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
    require(config['completion_message'] == 'go2_nav2 환경 설정이 완료되었습니다.', 'Invalid completion message')
    audit_metadata(config, root or Path(path).resolve().parent)
    return config


def resolve_paths(config, prefix=None, home=None):
    home = (home or Path.home()).resolve()
    path = Path(prefix).expanduser().resolve() if prefix else (home / config['paths']['prefix']).resolve()
    require(path != home and home in path.parents, 'Choose a dedicated path inside your home')
    return {'prefix': path, 'logs': path / 'logs'}


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
    def __init__(self, config, paths, conda, project_ref=None):
        self.config, self.paths, self.conda = config, paths, conda
        self.prefix, self.logs = paths['prefix'], paths['logs']
        self.project_ref = project_ref or config['project']['ref']
        self.env_prefix = None
        self.overlays = []
        self.env = clean_environment()
        jobs = str(config['build']['jobs'])
        self.env.update(MAKEFLAGS='-j' + jobs, CMAKE_BUILD_PARALLEL_LEVEL=jobs,
                        OPENBLAS_NUM_THREADS=jobs, OMP_NUM_THREADS=jobs)

    def run(self, command, cwd=None, capture=False):
        if not capture:
            print('[go2 setup] ' + shlex.join([str(x) for x in command]), flush=True)
        result = subprocess.run([str(x) for x in command], cwd=cwd, env=self.env,
                                check=True, text=True, stdout=subprocess.PIPE if capture else None)
        return result.stdout.strip() if capture else None

    def in_conda(self, command, cwd=None, overlays=False, capture=False):
        prefix = [self.conda, 'run', '--no-capture-output', '--prefix', str(self.env_prefix)]
        if overlays:
            script = 'set -e; set +u; ' + ''.join('source ' + shlex.quote(str(p)) + '; ' for p in self.overlays)
            command = ['bash', '--noprofile', '--norc', '-c', script + 'exec "$@"', 'go2-setup', *command]
        return self.run(prefix + command, cwd, capture)

    def find_env(self):
        data = json.loads(self.run([self.conda, 'env', 'list', '--json'], capture=True))
        matches = [Path(p).resolve() for p in data['envs'] if Path(p).name == self.config['conda']['name']]
        require(len(matches) <= 1, 'Multiple go2_nav2 environments found; resolve the name ambiguity first')
        return matches[0] if matches else None

    def create_environment(self):
        existing = self.find_env()
        owner = '.go2_nav2-managed.json'
        if existing:
            marker = existing / owner
            require(marker.is_file() and json.loads(marker.read_text()).get('project') == 'unitree-go2-slam-nav2',
                    'An unmanaged go2_nav2 environment already exists; it was not modified.')
        conda = self.config['conda']
        command = [self.conda, 'install' if existing else 'create', '--yes', '--name', conda['name'],
                   '--override-channels', '--strict-channel-priority', '--solver', conda['solver']]
        for channel in conda['channels']:
            command += ['--channel', channel]
        command += ['python=' + conda['python'], *conda['packages']]
        self.run(command)
        self.env_prefix = self.find_env()
        require(self.env_prefix is not None, 'Conda did not create the requested environment')
        (self.env_prefix / owner).write_text(json.dumps({'project': 'unitree-go2-slam-nav2'}))
        if conda['pip']:
            self.in_conda(['python', '-m', 'pip', 'install', *conda['pip']])

    def clone(self, source, target, ref=None):
        ref = ref or source['ref']
        fresh = not target.exists()
        if not fresh:
            require((target / '.git').exists(), 'Existing source directory is not a Git checkout: ' + str(target))
            require(not self.in_conda(['git', 'status', '--porcelain'], cwd=target, capture=True),
                    'Existing source checkout is modified: ' + str(target))
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            self.in_conda(['git', 'clone', '--no-checkout', source['url'], str(target)])
        self.in_conda(['git', 'fetch', 'origin', ref], cwd=target)
        expected = self.in_conda(['git', 'rev-parse', 'FETCH_HEAD'], cwd=target, capture=True)
        head = self.in_conda(['git', 'rev-parse', 'HEAD'], cwd=target, capture=True)
        # A fresh --no-checkout clone has no source files yet.
        require(fresh or head == expected, 'Source revision changed; choose a new installation prefix.')
        if fresh:
            self.in_conda(['git', 'checkout', '--detach', expected], cwd=target)
        return expected

    def build(self, workspace, base_path, packages):
        workspace.mkdir(parents=True, exist_ok=True)
        python = str(self.env_prefix / 'bin' / 'python')
        command = ['colcon', 'build', '--base-paths', str(base_path), '--packages-select', *packages,
                   '--executor', 'sequential', '--cmake-args', *self.config['build']['cmake_args'],
                   '-DPython_EXECUTABLE=' + python, '-DPython3_EXECUTABLE=' + python]
        self.in_conda(command, cwd=workspace, overlays=True)
        setup = workspace / 'install' / 'local_setup.bash'
        require(setup.is_file(), 'Build did not produce ' + str(setup))
        self.overlays.append(setup)

    def verify(self):
        settings = self.config['verification']
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
    prefix=Path(get_package_prefix(package)).resolve()
    assert any(prefix.is_relative_to(Path(root)) for root in [d['prefix'],d['workspace_root']]), 'System ROS overlay leaked in: '+package
for plugin in d['checks']['plugins']:
    root=Path(get_package_share_directory(plugin['package']))
    assert any(plugin['class'] in p.read_text() for p in root.rglob('*.xml')), 'Missing plugin '+plugin['class']
print('INSTALL CHECK PASS: Conda Python, ROS packages, messages and plugins. Live sensors/TF/motion NOT TESTED.')
'''
        payload = {'prefix': str(self.env_prefix), 'workspace_root': str(self.prefix), 'python': self.config['conda']['python'], 'checks': settings}
        self.in_conda(['python', '-c', code, json.dumps(payload)], overlays=True)

    def activation(self, repo):
        base = self.run([self.conda, 'info', '--base'], capture=True)
        complete = self.prefix / '.go2-setup-complete'
        lines = ['# Generated from environment.json; rerun the installer to refresh.',
                 'if [[ ! -f ' + shlex.quote(str(complete)) + ' ]]; then',
                 "  echo 'ERROR: setup is incomplete; rerun install_student.sh.' >&2",
                 '  return 1 2>/dev/null || exit 1', 'fi',
                 'unset ' + ' '.join(x for x in OVERLAY_VARS if not x.startswith('CONDA_')),
                 'source ' + shlex.quote(str(Path(base) / 'etc/profile.d/conda.sh')),
                 'conda activate ' + shlex.quote(str(self.env_prefix)) + ' || return 1']
        values = dict(self.config['activation']['environment'])
        values.update(GO2_ENV_MANAGER='conda', GO2_CONDA_ENV=self.config['conda']['name'],
                      GO2_CONDA_PREFIX=str(self.env_prefix), GO2_PYTHON=str(self.env_prefix / 'bin/python'),
                      GO2_PREFIX=str(self.prefix), GO2_WS_ROOT=str(self.prefix / 'ws'),
                      GO2_REPO_ROOT=str(repo), GO2_UNITREE_SETUP=str(self.overlays[0]),
                      GO2_STUDENT_ENV=str(self.prefix / 'env.bash'))
        for key, value in values.items():
            lines.append('export ' + key + '=' + shlex.quote(value))
        lines += ['set +u'] + ['source ' + shlex.quote(str(p)) + ' || return 1' for p in self.overlays]
        lines.append('set -u')
        (self.prefix / 'env.bash').write_text('\n'.join(lines) + '\n')

    def install(self):
        require(os.geteuid() != 0, 'Run setup as your normal user, not root')
        require(sys.platform == self.config['host']['os'] and platform.machine() in self.config['host']['architectures'],
                'Unsupported host platform')
        release = dict(line.strip().split('=', 1) for line in Path('/etc/os-release').read_text().splitlines() if '=' in line)
        require(release.get('ID', '').strip('"') == 'ubuntu' and release.get('VERSION_ID', '').strip('"') == self.config['host']['ubuntu'],
                'This environment targets the recorded Ubuntu version')
        marker = self.prefix / '.go2-student-install'
        if self.prefix.exists() and any(self.prefix.iterdir()):
            require(marker.is_file() and marker.read_text().strip() == 'conda:go2_nav2',
                    'Existing prefix belongs to another setup; choose a new dedicated prefix.')
        self.prefix.mkdir(parents=True, exist_ok=True)
        marker.write_text('conda:go2_nav2\n')
        complete = self.prefix / '.go2-setup-complete'
        complete.unlink(missing_ok=True)
        self.logs.mkdir(parents=True, exist_ok=True)
        self.create_environment()
        revisions = {}
        for source in self.config['sources']:
            target = self.prefix / 'vendor' / source['name']
            revisions[source['name']] = self.clone(source, target)
            self.build(self.prefix / source['workspace'], target / source['source_subpath'], source['packages'])
        repo = self.prefix / 'ws/src/unitree-go2-slam-nav2'
        revisions['project'] = self.clone(self.config['project'], repo, self.project_ref)
        audit_metadata(self.config, repo, required=True)
        self.build(self.prefix / 'ws', repo, self.config['project']['packages'])
        self.activation(repo)
        self.verify()
        resolved = self.run([self.conda, 'list', '--prefix', str(self.env_prefix), '--explicit'], capture=True)
        snapshot = self.logs
        (snapshot / 'conda-resolved.txt').write_text(resolved + '\n')
        (snapshot / 'environment-installed.json').write_text(json.dumps(self.config, indent=2) + '\n')
        (snapshot / 'source-commits.json').write_text(json.dumps(revisions, indent=2) + '\n')
        complete.write_text(hashlib.sha256(json.dumps(self.config, sort_keys=True).encode()).hexdigest() + '\n')
        print('Activate: source ' + shlex.quote(str(self.prefix / 'env.bash')))
        print(self.config['completion_message'])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', nargs='?', default='install', choices=['install', 'plan', 'verify', 'validate', 'env-file', 'vcs'])
    parser.add_argument('--manifest', type=Path, default=ROOT / 'environment.json')
    parser.add_argument('--prefix')
    parser.add_argument('--ref')
    parser.add_argument('--conda-exe')
    args = parser.parse_args(argv)
    config = load_config(args.manifest)
    paths = resolve_paths(config, args.prefix)
    if args.ref:
        require(re.fullmatch(r'[A-Za-z0-9_./-]+', args.ref) and not args.ref.startswith('-'), 'Invalid project ref')
    if args.mode == 'env-file':
        print(paths['prefix'] / 'env.bash')
        return
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
        print('Prefix: ' + str(paths['prefix']) + '\nSetup logs: ' + str(paths['logs']))
        print('Conda packages: ' + ', '.join(['python=' + config['conda']['python'], *config['conda']['packages']]))
        print('Build: ' + ', '.join(p for s in config['sources'] for p in s['packages']) + ', ' + ', '.join(config['project']['packages']))
        print('No apt, clone, build, Conda creation, SSH, network change, ROS startup or motion executed.')
        return
    installer = Installer(config, paths, conda_executable(args.conda_exe), args.ref)
    if args.mode == 'install':
        installer.install()
    else:
        require((paths['prefix'] / '.go2-setup-complete').is_file(), 'Missing completed installation; run install first.')
        installer.env_prefix = installer.find_env()
        require(installer.env_prefix is not None, 'go2_nav2 is missing')
        installer.overlays = [paths['prefix'] / s['workspace'] / 'install/local_setup.bash' for s in config['sources']]
        installer.overlays.append(paths['prefix'] / 'ws/install/local_setup.bash')
        installer.verify()


if __name__ == '__main__':
    try:
        main()
    except (SetupError, OSError, ValueError, KeyError, ET.ParseError, subprocess.CalledProcessError) as error:
        print('ERROR: ' + str(error), file=sys.stderr)
        raise SystemExit(1)
