"""Offline tutorial launcher tests. No HTTP, ROS, or robot access."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import map_preview_capture
import open_tutorial


def make_saved_map(base, ident, image=True):
    folder = base / ident
    folder.mkdir(parents=True)
    db = folder / 'rtabmap.db'
    db.write_bytes(b'synthetic original RTAB-Map DB sentinel')
    (folder / 'metadata.json').write_text(
        json.dumps({'name': f'지도 {ident}', 'created_at': '2026-11-16T13:00:00+09:00'}),
        encoding='utf-8'
    )
    if image:
        png = map_preview_capture.occupancy_png(2, 2, [0, 100, 0, -1])
        (folder / 'preview.png').write_bytes(png)
    return folder, db.read_bytes()


def test_all_maps_indexed_with_metadata_and_optional_image(tmp_path, monkeypatch):
    first, first_db = make_saved_map(tmp_path, 'a', True)
    second, second_db = make_saved_map(tmp_path, 'b', False)
    rows = [
        {'database': str(first / 'rtabmap.db'), 'name': '복도 지도', 'created_at': '2026-11-16T13:00:00+09:00'},
        {'database': str(second / 'rtabmap.db'), 'name': '계단 지도', 'created_at': '2026-11-16T12:00:00+09:00'},
    ]
    monkeypatch.setattr(open_tutorial, 'list_available_maps', lambda: rows)
    output = tmp_path / 'out'
    output.mkdir()
    maps = open_tutorial.export_maps(output)
    assert len(maps) == 2
    assert [r['name'] for r in maps] == ['복도 지도', '계단 지도']
    assert maps[0]['image_available'] is True and maps[0]['image_quality'] == 'preview'
    assert maps[1]['image_available'] is False and maps[1]['image_url'] is None
    assert (output / maps[0]['image_url']).read_bytes() == (first / 'preview.png').read_bytes()
    text = (output / 'maps_manifest.js').read_text('utf-8')
    assert text.startswith('window.GO2_OFFLINE_MAPS = ')
    assert '복도 지도' not in text and 'rtabmap.db' in text  # escaped JSON and local-only map ID
    data = json.loads(text.partition('= ')[2].rstrip(';\n'))
    assert len(data) == 2
    assert (first / 'rtabmap.db').read_bytes() == first_db
    assert (second / 'rtabmap.db').read_bytes() == second_db


def test_full_resolution_preferred_and_refresh_on_change(tmp_path, monkeypatch):
    folder, db_bytes = make_saved_map(tmp_path, 'c', True)
    full = map_preview_capture.occupancy_png(4, 4, [0]*16, max_side=4)
    (folder / 'map.png').write_bytes(full)
    monkeypatch.setattr(open_tutorial, 'list_available_maps',
                        lambda: [{'database': str(folder / 'rtabmap.db'), 'name': 'C', 'created_at': '2026-11-16'}])
    target = tmp_path / 'output'
    target.mkdir()
    result = open_tutorial.export_maps(target)[0]
    assert result['image_quality'] == 'full'
    assert (target / result['image_url']).read_bytes() == full
    changed = map_preview_capture.occupancy_png(5, 5, [100]*25, max_side=5)
    (folder / 'map.png').write_bytes(changed)
    open_tutorial.export_maps(target)
    assert (target / result['image_url']).read_bytes() == changed
    assert (folder / 'rtabmap.db').read_bytes() == db_bytes


def test_launcher_only_opens_file_url_and_returns(monkeypatch, tmp_path, capsys):
    html = tmp_path / 'slam_nav2_tutorial.html'
    html.write_text('<!doctype html><title>Go2</title>', encoding='utf-8')
    monkeypatch.setattr(open_tutorial, 'ROOT', tmp_path)
    monkeypatch.setattr(open_tutorial, 'export_maps',
                        lambda: [{'image_available': False, 'name': 'A'}])
    opened = []
    monkeypatch.setattr(open_tutorial.webbrowser, 'open', lambda url: opened.append(url))
    open_tutorial.main()
    assert opened == [html.resolve().as_uri()]
    assert '서버 없이' in capsys.readouterr().out


def test_manifest_is_not_an_http_url(tmp_path, monkeypatch):
    folder, _ = make_saved_map(tmp_path, 'd', True)
    monkeypatch.setattr(open_tutorial, 'list_available_maps',
                        lambda: [{'database': str(folder/'rtabmap.db'), 'name': 'D', 'created_at': '2026-11-16'}])
    out = tmp_path / 'output'
    out.mkdir()
    row = open_tutorial.export_maps(out)[0]
    assert row['image_url'].startswith('viewer_maps/')
    assert '://' not in row['image_url']
