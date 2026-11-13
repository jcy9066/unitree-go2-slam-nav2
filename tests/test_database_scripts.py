"""Root Nav2 behavior with copied scripts, fake ROS and synthetic map bytes."""
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).parents[1]


def test_navigation_copies_database_and_defaults_to_no_motion(runtime_project):
    f = runtime_project
    original = f.root / 'original map.db'; original.write_bytes(b'synthetic database bytes')
    original.chmod(0o444)
    before = original.stat()
    f.env['GO2_ENABLE_MOTION'] = 'true'  # View must override stale motion settings.
    result = subprocess.run(['bash', str(f.root / 'run_nav.sh'), str(original)], env=f.env,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    copies = list(Path(f.env['GO2_MAP_DIR']).glob('nav_sessions/*/rtabmap.db'))
    assert len(copies) == 1 and copies[0] != original
    assert copies[0].read_bytes() == original.read_bytes() == b'synthetic database bytes'
    assert original.stat().st_mtime_ns == before.st_mtime_ns
    calls = f.calls()
    assert 'enable_motion:=false' in calls and 'localize_only:=true' in calls
    assert 'restart_map:=false' in calls and str(copies[0]) in calls
    assert 'UNEXPECTED_SSH' not in calls


def test_mapping_refuses_existing_database_before_startup(tmp_path):
    original = tmp_path / 'original.db'; original.write_bytes(b'keep me')
    result = subprocess.run(['bash', str(ROOT / 'run_mapping.sh'), str(original)],
                            capture_output=True, text=True)
    assert result.returncode != 0 and 'refusing overwrite' in result.stderr
    assert original.read_bytes() == b'keep me'


def test_navigation_missing_database_fails_before_startup(tmp_path):
    result = subprocess.run(['bash', str(ROOT / 'run_nav.sh'), str(tmp_path / 'absent.db')],
                            capture_output=True, text=True)
    assert result.returncode != 0 and 'not found or empty' in result.stderr


@pytest.mark.parametrize('mode,profile', [('aligned','aligned_visual'), ('reference','reference_visual')])
def test_comparison_preserves_profile_and_source(runtime_project, mode, profile):
    f = runtime_project
    original = f.root / 'comparison.db'; original.write_bytes(b'comparison fixture')
    f.env['GO2_FIRST_DOOR_ONLY'] = 'true'
    result = subprocess.run(['bash', str(f.root / 'run_nav.sh'), mode, str(original)],
                            env=f.env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert 'localization_profile:=' + profile in f.calls()
    assert 'enable_motion:=false' in f.calls()
    if mode == 'reference': assert 'first_door_only:=false' in f.calls()
    assert original.read_bytes() == b'comparison fixture'


@pytest.mark.parametrize('mode', ['aligned', 'reference'])
def test_comparison_never_uses_an_implicit_foreign_map(runtime_project, mode):
    f = runtime_project
    result = subprocess.run(['bash', str(f.root / 'run_nav.sh'), mode], env=f.env,
                            capture_output=True, text=True)
    assert result.returncode != 0 and 'explicit DB path' in result.stderr
    assert not f.log.exists()


def test_drive_requires_explicit_operator_mode_and_accepts_profile(runtime_project):
    f = runtime_project
    original = f.root / 'test.db'; original.write_bytes(b'inert map')
    result = subprocess.run(['bash', str(f.root / 'run_nav.sh'), 'drive', str(original),
                             '--profile', 'aligned_visual'], env=f.env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert 'enable_motion:=true' in f.calls()
    assert 'localization_profile:=aligned_visual' in f.calls()


def test_health_is_forwarded_without_starting_navigation(runtime_project):
    f = runtime_project
    result = subprocess.run(['bash', str(f.root / 'run_nav.sh'), 'health', '--seconds', '7'],
                            env=f.env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "health ['--seconds', '7']" in f.calls()
    assert 'launch_started' not in f.calls()
    assert not Path(f.env['GO2_MAP_DIR']).exists()


def test_missing_camera_blocks_nav_before_db_copy(runtime_project):
    f = runtime_project
    original = f.root / 'test.db'; original.write_bytes(b'inert map')
    f.env['FIXTURE_READY'] = '1'
    result = subprocess.run(['bash', str(f.root / 'run_nav.sh'), str(original)], env=f.env,
                            capture_output=True, text=True)
    assert result.returncode != 0 and 'launch_started' not in f.calls()
    assert not Path(f.env['GO2_MAP_DIR']).exists()
    assert original.read_bytes() == b'inert map'


def test_nav_plan_is_read_only_from_another_directory(runtime_project):
    f = runtime_project
    original = f.root / 'test.db'; original.write_bytes(b'inert map')
    result = subprocess.run(['bash', str(f.root / 'run_nav.sh'), 'plan', str(original)],
                            cwd=f.root.parent, env=f.env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert not f.log.exists() and not Path(f.env['GO2_MAP_DIR']).exists()
