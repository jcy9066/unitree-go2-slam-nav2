#!/usr/bin/env python3
"""One-shot offline tutorial launcher. No HTTP server or background process."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import webbrowser

from map_catalog import list_available_maps

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'maps_manifest.js'
CACHE = ROOT / 'viewer_maps'
MAX_IMAGE_BYTES = 96_000_000


def export_maps(root=ROOT):
    """Index every valid saved DB and stage its existing display PNG, if any."""
    entries = []
    cache = root / 'viewer_maps'
    cache.mkdir(parents=True, exist_ok=True)

    for row in list_available_maps():
        database = Path(row['database'])
        folder = database.parent
        key = hashlib.sha256(str(database.resolve()).encode('utf-8')).hexdigest()[:20]
        image_name = None
        quality = None
        for candidate, kind in (('map.png', 'full'), ('preview.png', 'preview')):
            source = folder / candidate
            if source.is_symlink() or not source.is_file():
                continue
            stat = source.stat()
            if not 0 < stat.st_size <= MAX_IMAGE_BYTES:
                continue
            with source.open('rb') as stream:
                if stream.read(8) != b'\x89PNG\r\n\x1a\n':
                    continue
            image_name = key + '.png'
            target = cache / image_name
            if (not target.is_file() or target.is_symlink()
                    or target.stat().st_size != stat.st_size
                    or target.stat().st_mtime_ns != stat.st_mtime_ns):
                if target.is_symlink():
                    raise ValueError('생성된 뷰어 이미지 경로가 심볼릭 링크입니다: ' + str(target))
                shutil.copy2(source, target)
            quality = kind
            break

        entries.append({
            'id': str(database.resolve()),
            'name': row['name'],
            'created_at': row['created_at'],
            'image_available': image_name is not None,
            'image_quality': quality,
            'image_url': 'viewer_maps/' + image_name if image_name else None,
        })

    # External script executes from file:// without fetch(), CORS, or a server.
    payload = 'window.GO2_OFFLINE_MAPS = ' + json.dumps(entries, ensure_ascii=True) + ';\n'
    manifest = root / 'maps_manifest.js'
    descriptor, temporary = tempfile.mkstemp(prefix='.maps-manifest-', suffix='.tmp', dir=root)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, manifest)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)

    return entries


def main():
    entries = export_maps()
    visible = sum(row['image_available'] for row in entries)
    print(f'[map] 지도 {len(entries)}개 확인 · 이미지 표시 가능 {visible}개')
    print('[map] 서버 없이 HTML을 엽니다. 실행기는 바로 종료됩니다.')
    page = ROOT / 'slam_nav2_tutorial.html'
    webbrowser.open(page.resolve().as_uri())


if __name__ == '__main__':
    main()
