"""Read-only interactive tutorial map API tests: no ROS or physical robot required."""
import json
import sqlite3
import struct
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import map_catalog
import map_preview_capture
import tutorial_server


@pytest.fixture
def sample_maps(tmp_path, monkeypatch):
    root = tmp_path / 'maps'
    folder = root / 'map_20261116_100000'
    folder.mkdir(parents=True)
    db = folder / 'rtabmap.db'
    with sqlite3.connect(db) as conn:
        conn.execute('CREATE TABLE Node(id INTEGER)')
        conn.execute('INSERT INTO Node VALUES (1)')
    original_db = db.read_bytes()
    map_catalog.register(db, root)
    map_catalog.rename(folder.name, '창학관 3층', root)
    # A full-size occupancy image and a smaller preview come from the same cells.
    values = [0, 100, -1, 0] * 6
    full = map_preview_capture.occupancy_png(8, 3, values, max_side=8)
    thumb = map_preview_capture.occupancy_png(8, 3, values, max_side=4)
    (folder / 'map.png').write_bytes(full)
    (folder / 'preview.png').write_bytes(thumb)
    monkeypatch.setenv('GO2_MAP_DIR', str(root))
    monkeypatch.setattr(tutorial_server, 'REPO', tmp_path)
    return folder, original_db, full, thumb


@pytest.fixture
def live_http():
    server = ThreadingHTTPServer(('127.0.0.1', 0), tutorial_server.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f'http://127.0.0.1:{server.server_port}'
    server.shutdown()
    server.server_close()
    thread.join(timeout=3)


def test_public_map_list_only_name_date_image_no_db_paths(sample_maps):
    folder, original, full, thumb = sample_maps
    entries = tutorial_server.public_maps()
    assert len(entries) == 1
    entry = entries[0]
    assert entry['id'] == 'local:' + folder.name
    assert entry['name'] == '창학관 3층'
    assert entry['created_at']
    assert entry['image_available'] and entry['image_quality'] == 'full'
    assert entry['image_url'].startswith('/api/tutorial/maps/')
    assert 'database' not in entry and str(folder) not in json.dumps(entry)
    assert (folder / 'rtabmap.db').read_bytes() == original


def test_http_list_and_full_resolution_png_are_read_only(sample_maps, live_http):
    folder, original, full, _ = sample_maps
    with urlopen(live_http + '/api/tutorial/maps', timeout=3) as response:
        payload = json.load(response)
    row = payload['maps'][0]
    with urlopen(live_http + row['image_url'], timeout=3) as response:
        data = response.read()
        assert response.headers.get('Content-Type') == 'image/png'
    assert data == full
    assert struct.unpack('!II', data[16:24]) == (8, 3)
    assert (folder / 'rtabmap.db').read_bytes() == original
    assert not (folder.parent / '.selected_map').exists()


def test_thumbnail_fallback_and_missing_png(sample_maps):
    folder, _, full, thumb = sample_maps
    (folder / 'map.png').unlink()
    first = tutorial_server.public_maps()[0]
    assert first['image_quality'] == 'preview'
    image, quality = tutorial_server.resolve_image(first['id'])
    assert image.read_bytes() == thumb
    (folder / 'preview.png').unlink()
    last = tutorial_server.public_maps()[0]
    assert not last['image_available'] and last['image_url'] is None


def test_path_traversal_and_db_access_blocked(sample_maps, live_http):
    bad = ['local:../other', 'local:../../etc/passwd', 'invalid:map_20261116_100000']
    for token in bad:
        with pytest.raises(map_catalog.MapCatalogError):
            tutorial_server.resolve_image(token)
    with pytest.raises(HTTPError) as error:
        urlopen(live_http + '/api/tutorial/maps/local%3A..%2Fother/image', timeout=3)
    assert error.value.code == 404
    with pytest.raises(HTTPError) as error:
        urlopen(live_http + '/rtabmap.db', timeout=3)
    assert error.value.code == 404


def test_video_range_is_supported(tmp_path, monkeypatch, live_http):
    media = tmp_path / 'movie.mp4'
    media.write_bytes(b'0123456789ABCDEFGH')
    monkeypatch.setitem(tutorial_server.STATIC_FILES, '/docs/KakaoTalk_20261112_203846672_web.mp4', media)
    request = Request(live_http + '/docs/KakaoTalk_20261112_203846672_web.mp4',
                      headers={'Range': 'bytes=3-8'})
    with urlopen(request, timeout=3) as response:
        assert response.status == 206
        assert response.read() == b'345678'
        assert response.headers['Content-Range'] == 'bytes 3-8/18'


def test_host_header_is_local_only(sample_maps, live_http):
    request = Request(live_http + '/api/tutorial/maps', headers={'Host': 'example.com'})
    with pytest.raises(HTTPError) as error:
        urlopen(request, timeout=3)
    assert error.value.code == 403
