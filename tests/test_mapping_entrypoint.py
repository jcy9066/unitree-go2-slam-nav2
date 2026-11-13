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
def test_latest_map_only_advances_after_successful_populated_db(runtime_project, kind):
    f = runtime_project
    folder = Path(f.env['GO2_MAP_DIR']); folder.mkdir()
    pointer = folder / '.last_map'; pointer.write_text('previous-map.db\n')
    db = folder / 'new map' / 'rtabmap.db'
    f.env['FIXTURE_DB_KIND'] = kind
    result = subprocess.run(['bash', str(f.root / 'run_mapping.sh'), str(db)],
                            env=f.env, capture_output=True, text=True, timeout=8)
    assert pointer.read_text() == (str(db) + '\n' if kind == 'valid' else 'previous-map.db\n')
    assert db.exists(), 'Partial databases must remain available for diagnosis'
    assert (result.returncode == 0) == (kind == 'valid'), result.stderr
    assert 'UNEXPECTED_SSH' not in f.calls()


def test_plan_does_not_load_environment_connect_or_create_maps(runtime_project):
    f = runtime_project
    result = subprocess.run(['bash', str(f.root / 'run_mapping.sh'), 'plan'],
                            env=f.env, cwd=f.root.parent, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert 'No build, SSH, ROS nodes' in result.stdout
    assert not f.log.exists() and not Path(f.env['GO2_MAP_DIR']).exists()


@pytest.mark.parametrize('mode', ['check', 'start', 'idle-blocked', 'camera-missing'])
def test_startup_uses_manually_started_camera_and_blocks_conflicts(runtime_project, mode):
    f = runtime_project
    if mode == 'idle-blocked': f.env['FIXTURE_IDLE'] = '2'
    if mode == 'camera-missing': f.env['FIXTURE_READY'] = '1'
    result = subprocess.run(['bash', str(f.root / 'run_mapping.sh'),
                             'check' if mode == 'check' else 'start'],
                            env=f.env, capture_output=True, text=True, timeout=5)
    assert 'UNEXPECTED_SSH' not in f.calls()
    assert ('launch_started' in f.calls()) == (mode == 'start')
    assert (result.returncode == 0) == (mode in {'check', 'start'}), result.stderr
    if mode == 'check': assert not Path(f.env['GO2_MAP_DIR']).exists()


def test_ctrl_c_waits_for_db_flush_and_only_stops_owned_launch(runtime_project):
    f = runtime_project
    f.env['FIXTURE_WAIT'] = '1'
    unrelated = subprocess.Popen(['sleep', '30'])
    process = subprocess.Popen(['bash', str(f.root / 'run_mapping.sh')], env=f.env,
                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, start_new_session=True)
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if 'launch_started' in f.calls(): break
            time.sleep(.03)
        else: raise AssertionError('Mapping fixture never started: ' + f.calls())
        process.send_signal(signal.SIGINT)
        _, error = process.communicate(timeout=5)
        assert process.returncode == 130, error
        assert 'launch_closed' in f.calls() and unrelated.poll() is None
        pointer = Path(f.env['GO2_MAP_DIR']) / '.last_map'
        db = Path(pointer.read_text().strip())
        assert preflight.validate_database(db)['nodes'] == 1
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM); process.wait(timeout=5)
        unrelated.terminate(); unrelated.wait(timeout=3)
