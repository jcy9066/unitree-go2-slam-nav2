"""Test original DB protection using copied scripts and an inert launch function."""
from pathlib import Path
import os
import shutil
import subprocess

ROOT = Path(__file__).parents[1]


def test_navigation_copies_database_and_defaults_to_no_motion(tmp_path):
    scripts = tmp_path/'scripts'; scripts.mkdir()
    shutil.copyfile(ROOT/'scripts/run_nav.sh', scripts/'run_nav.sh')
    calls = tmp_path/'calls.txt'
    (scripts/'_env.sh').write_text('ros2() { printf "%s\\n" "$@" > "$GO2_TEST_CALLS"; }\n')
    original = tmp_path/'original.db'; original.write_bytes(b'synthetic database bytes')
    original.chmod(0o444)
    before = original.stat()
    env = dict(os.environ, GO2_MAP_DIR=str(tmp_path/'maps'), GO2_TEST_CALLS=str(calls))
    env.pop('GO2_ENABLE_MOTION', None)
    result = subprocess.run(['bash', str(scripts/'run_nav.sh'), str(original)], env=env,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    copies = list((tmp_path/'maps/nav_sessions').glob('*/rtabmap.db'))
    assert len(copies) == 1 and copies[0] != original
    assert copies[0].read_bytes() == original.read_bytes() == b'synthetic database bytes'
    assert original.stat().st_mtime_ns == before.st_mtime_ns
    assert 'enable_motion:=false' in calls.read_text()
    assert 'localize_only:=true' in calls.read_text()
    assert str(copies[0]) in calls.read_text()


def test_mapping_refuses_existing_database_before_startup(tmp_path):
    original = tmp_path/'original.db'; original.write_bytes(b'keep me')
    env = dict(os.environ, GO2_MAP_DIR=str(tmp_path/'maps'))
    result = subprocess.run(['bash', str(ROOT/'scripts/run_mapping.sh'), str(original)],
                            env=env, capture_output=True, text=True)
    assert result.returncode != 0 and 'refusing overwrite' in result.stderr
    assert original.read_bytes() == b'keep me'


def test_navigation_missing_database_fails_before_startup(tmp_path):
    result = subprocess.run(['bash', str(ROOT/'scripts/run_nav.sh'), str(tmp_path/'absent.db')],
                            capture_output=True, text=True)
    assert result.returncode != 0 and 'not found or empty' in result.stderr
