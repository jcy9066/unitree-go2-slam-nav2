"""Offline map catalog, thumbnail and administrator HTTP tests; never use ROS or motion."""
import importlib.util
import io
import json
from pathlib import Path
import sqlite3
import struct
import threading
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


catalog = load('map_catalog', 'scripts/map_catalog.py')
preview = load('map_preview_capture', 'scripts/map_preview_capture.py')
manager = load('map_manager', 'map_manager.py')


def make_map(folder):
    folder.mkdir(parents=True)
    db = folder / 'rtabmap.db'
    with sqlite3.connect(db) as connection:
        connection.execute('CREATE TABLE Node (id INTEGER)')
        connection.execute('INSERT INTO Node VALUES(1)')
    return db


def test_metadata_name_changes_never_touch_db(tmp_path, monkeypatch):
    root = tmp_path / 'maps'
    db = make_map(root / 'map_20261116_121200')
    monkeypatch.setenv('GO2_MAP_DIR', str(root))
    data, stamp = db.read_bytes(), db.stat().st_mtime_ns
    first = catalog.register(db)
    assert first['name'] == '이름 미지정'
    updated = catalog.rename(db.parent.name, '창학관 3층')
    assert updated['name'] == '창학관 3층'
    assert updated['created_at'] == first['created_at']
    assert db.read_bytes() == data and db.stat().st_mtime_ns == stamp
    assert catalog.list_maps()[0]['name'] == '창학관 3층'
    with pytest.raises(catalog.MapCatalogError):
        catalog.rename(db.parent.name, '   ')


def test_refuse_paths_outside_map_root_and_symlinks(tmp_path, monkeypatch):
    root = tmp_path / 'maps'
    root.mkdir()
    external = make_map(tmp_path / 'external')
    (root / 'linked').symlink_to(external.parent, target_is_directory=True)
    monkeypatch.setenv('GO2_MAP_DIR', str(root))
    assert catalog.list_maps() == []
    with pytest.raises(catalog.MapCatalogError):
        catalog.register(external)
    with pytest.raises(catalog.MapCatalogError):
        catalog.rename('linked', 'unsafe')


def test_occupancy_preview_is_real_png_with_correct_dimensions():
    result = preview.occupancy_png(3, 2, [0, 100, -1, -1, 0, 100])
    assert result[:8] == b'\x89PNG\r\n\x1a\n'
    assert struct.unpack('!II', result[16:24]) == (3, 2)
    assert b'IDAT' in result


class TTY(io.StringIO):
    def isatty(self):
        return True


def test_terminal_selection_updates_only_pointer(tmp_path, monkeypatch, capsys):
    root = tmp_path / 'maps'
    db = make_map(root / 'map_20261116_130000')
    monkeypatch.setenv('GO2_MAP_DIR', str(root))
    catalog.register(db)
    monkeypatch.setattr(catalog.sys, 'stdin', TTY('1\n'))
    assert catalog.choose() == str(db.resolve())
    streams = capsys.readouterr()
    assert streams.out == '', 'CLI prompts must not corrupt captured DB path'
    assert '지도 번호' in streams.err
    assert catalog.selected_path() == str(db.resolve())
    assert db.is_file()


def test_loopback_http_lists_and_renames_no_database_write(tmp_path, monkeypatch):
    root = tmp_path / 'maps'
    db = make_map(root / 'map_20261116_140000')
    catalog.register(db, root)
    monkeypatch.setenv('GO2_MAP_DIR', str(root))
    server = ThreadingHTTPServer(('127.0.0.1', 0), manager.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f'http://127.0.0.1:{server.server_port}'
    try:
        with urlopen(url + '/api/maps', timeout=3) as response:
            row = json.load(response)['maps'][0]
        assert set(row) == {'id', 'name', 'date', 'preview'}
        body = json.dumps({'name': '실습 복도'}).encode('utf-8')
        request = Request(url + '/api/maps/' + row['id'] + '/rename',
                          body, {'Content-Type': 'application/json', 'Origin': url}, method='POST')
        with urlopen(request, timeout=3) as response:
            assert json.load(response)['map']['name'] == '실습 복도'
        forbidden = Request(url + '/api/maps/' + row['id'] + '/rename',
                            body, {'Content-Type': 'application/json',
                                   'Origin': 'https://example.com'}, method='POST')
        with pytest.raises(HTTPError) as error:
            urlopen(forbidden, timeout=3)
        assert error.value.code == 403
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
