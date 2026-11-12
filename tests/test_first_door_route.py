"""Map identity and virtual door routing; no robot node is started."""
import hashlib
import json
from pathlib import Path
import sqlite3
import struct
import zlib

import numpy as np
from PIL import Image
import pytest
import yaml

from go2_slam_nav.first_door_route import validate_route_database

ROOT = Path(__file__).parents[1]
CONFIG = ROOT / 'go2_slam_nav/config'


def test_route_policy_changes_only_keepout_and_waypoint_failure_handling():
    baseline = yaml.safe_load((CONFIG / 'nav2_params.yaml').read_text())
    trial = yaml.safe_load((CONFIG / 'nav2_first_door_only.yaml').read_text())
    assert trial['waypoint_follower']['ros__parameters']['stop_on_failure'] is True
    trial['waypoint_follower']['ros__parameters']['stop_on_failure'] = False
    for name in ['global_costmap', 'local_costmap']:
        p = trial[name][name]['ros__parameters']
        assert p.pop('filters') == ['first_door_keepout']
        assert p.pop('first_door_keepout')['plugin'] == 'nav2_costmap_2d::KeepoutFilter'
    assert trial == baseline


def test_keepout_excludes_door2_but_preserves_first_door_and_professor_reference():
    manifest = json.loads((CONFIG / 'first_door_route.json').read_text())
    mask = np.flipud(np.asarray(Image.open(CONFIG / 'first_door_keepout.png')))
    assert mask.shape == (manifest['height'], manifest['width'])
    def blocked(p):
        x, y = [(p[i] - manifest['origin'][i]) / manifest['resolution'] for i in range(2)]
        return mask[int(y), int(x)] == 0
    assert blocked(manifest['second_door_reference_point'])
    assert not blocked(manifest['first_door_reference_point'])
    assert not blocked(manifest['professor_reference_point'])


def fixture(tmp_path):
    data = bytes([0, 0, 100, 0]); image = tmp_path / 'first_door_keepout.png'
    image.write_bytes(b'checksum fixture')
    manifest = {'width': 2, 'height': 2, 'resolution': .05, 'origin': [0., 0.],
                'map_sha256': hashlib.sha256(data).hexdigest(),
                'mask_png_sha256': hashlib.sha256(image.read_bytes()).hexdigest()}
    path = tmp_path / 'route.json'; path.write_text(json.dumps(manifest))
    db = tmp_path / 'fixture.db'
    with sqlite3.connect(db) as connection:
        connection.execute('CREATE TABLE Admin(opt_map BLOB,opt_map_x_min REAL,opt_map_y_min REAL,opt_map_resolution REAL)')
        connection.execute('INSERT INTO Admin VALUES(?,?,?,?)',
                           (zlib.compress(data) + struct.pack('<iii', 2, 2, 1), 0., 0., .05))
    return db, path


def test_map_validation_is_read_only_and_rejects_another_map(tmp_path):
    db, manifest = fixture(tmp_path); original = db.read_bytes()
    validate_route_database(db, manifest)
    assert db.read_bytes() == original
    m = json.loads(manifest.read_text()); m['map_sha256'] = 'unsupported'
    manifest.write_text(json.dumps(m))
    with pytest.raises(ValueError, match='does not match'):
        validate_route_database(db, manifest)
    assert db.read_bytes() == original


def test_missing_database_is_never_created(tmp_path):
    _, manifest = fixture(tmp_path); missing = tmp_path / 'absent.db'
    with pytest.raises(FileNotFoundError):
        validate_route_database(missing, manifest)
    assert not missing.exists()


def test_modified_mask_is_rejected(tmp_path):
    db, manifest = fixture(tmp_path)
    (tmp_path / 'first_door_keepout.png').write_bytes(b'different mask')
    with pytest.raises(ValueError, match='checksum'):
        validate_route_database(db, manifest)
