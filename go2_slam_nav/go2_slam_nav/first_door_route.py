"""Validate the saved-map identity before applying a map-specific route mask."""
import hashlib
import json
from pathlib import Path
import sqlite3
import struct
import zlib


def validate_route_database(database_path, manifest_path):
    """Read only. Reject unsupported maps instead of placing a mask arbitrarily."""
    path = Path(database_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f'Route mode requires an existing database: {path}')
    manifest = json.loads(Path(manifest_path).read_text())
    with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as database:
        row = database.execute(
            'SELECT opt_map,opt_map_x_min,opt_map_y_min,opt_map_resolution FROM Admin').fetchone()
    if row is None or row[0] is None:
        raise ValueError('Route mode requires a saved optimized occupancy map')
    blob, x, y, resolution = row
    height, width, cvtype = struct.unpack('<iii', blob[-12:])
    metadata_ok = (cvtype == 1 and width == manifest['width'] and
                   height == manifest['height'] and
                   abs(resolution - manifest['resolution']) < 1e-8 and
                   abs(x - manifest['origin'][0]) < 1e-6 and
                   abs(y - manifest['origin'][1]) < 1e-6)
    if not metadata_ok or hashlib.sha256(zlib.decompress(blob)).hexdigest() != manifest['map_sha256']:
        raise ValueError('This map does not match the first-door route mask; no nodes were started')
    image = Path(manifest_path).parent / 'first_door_keepout.png'
    if hashlib.sha256(image.read_bytes()).hexdigest() != manifest['mask_png_sha256']:
        raise ValueError('First-door route mask checksum mismatch')
    return manifest
