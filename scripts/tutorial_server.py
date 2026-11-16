#!/usr/bin/env python3
"""Read-only, loopback-only tutorial page and offline occupancy-map viewer API.

The viewer never modifies a map, selection pointer, metadata, or robot state.
It is independent of map_manager.py and uses only Python standard library.
"""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
from urllib.parse import quote, unquote, urlsplit

from map_catalog import _safe_directory, list_maps, map_root, MapCatalogError

REPO = Path(__file__).resolve().parents[1]
STATIC_FILES = {
    '/': REPO / 'slam_nav2_tutorial.html',
    '/slam_nav2_tutorial.html': REPO / 'slam_nav2_tutorial.html',
    '/docs/images/go2-edu-hero.png': REPO / 'docs/images/go2-edu-hero.png',
    '/docs/KakaoTalk_20261112_203846672_web.mp4': REPO / 'docs/KakaoTalk_20261112_203846672_web.mp4',
}
MAX_IMAGE_BYTES = 96_000_000
MAX_MAPS = 2000


def map_locations():
    """Separate runtime maps from restored shared maps; do not expose DB paths."""
    runtime = map_root()
    shared = (REPO / 'maps').resolve()
    roots = [('local', runtime)]
    if shared != runtime:
        roots.append(('shared', shared))
    return roots


def _image_for(folder):
    # Full-resolution image is preferred. Older sessions may only have a thumbnail.
    for name, quality in (('map.png', 'full'), ('preview.png', 'preview')):
        image = folder / name
        if image.is_file() and not image.is_symlink() and 0 < image.stat().st_size <= MAX_IMAGE_BYTES:
            with image.open('rb') as stream:
                if stream.read(8) == b'\x89PNG\r\n\x1a\n':
                    return image, quality
    return None, None


def public_maps():
    entries = []
    for source, root in map_locations():
        for item in list_maps(root):
            identifier = item['id']
            try:
                folder, _ = _safe_directory(root, identifier)
                image, quality = _image_for(folder)
            except (OSError, MapCatalogError):
                image, quality = None, None
            token = f'{source}:{identifier}'
            entries.append({
                'id': token, 'name': item['name'],
                'created_at': item['created_at'],
                'image_available': image is not None,
                'image_quality': quality,
                'image_url': '/api/tutorial/maps/' + quote(token, safe='') + '/image' if image else None,
            })
    entries.sort(key=lambda row: row['created_at'], reverse=True)
    return entries[:MAX_MAPS]


def resolve_image(token):
    if ':' not in token:
        raise MapCatalogError('잘못된 지도 식별자')
    source, identifier = token.split(':', 1)
    roots = dict(map_locations())
    if source not in roots:
        raise MapCatalogError('알 수 없는 지도 저장 위치')
    folder, _ = _safe_directory(roots[source], identifier)
    image, quality = _image_for(folder)
    if image is None:
        raise MapCatalogError('지도 이미지가 없습니다')
    return image, quality


class Handler(BaseHTTPRequestHandler):
    server_version = 'Go2Tutorial/1.0'

    def _respond(self, status, mime, body, extra=None):
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Content-Security-Policy',
                         "default-src 'self'; style-src 'self' 'unsafe-inline'; "
                         "script-src 'self' 'unsafe-inline'; img-src 'self' blob:; "
                         "media-src 'self'; connect-src 'self'; object-src 'none'")
        for key, value in (extra or {}).items():
            self.send_header(key, str(value))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status, result):
        self._respond(status, 'application/json; charset=utf-8',
                      json.dumps(result, ensure_ascii=False).encode('utf-8'))

    def _file(self, path, content_type, *, range_allowed=False):
        if not path.is_file() or path.is_symlink():
            self._json(404, {'error': '파일이 없습니다'})
            return
        size = path.stat().st_size
        start, end, status = 0, size - 1, 200
        header = self.headers.get('Range') if range_allowed else None
        if header:
            match = re.fullmatch(r'bytes=(\d*)-(\d*)', header)
            if not match or (not match[1] and not match[2]):
                self._json(416, {'error': '지원하지 않는 Range'})
                return
            if not match[1]:
                count = int(match[2])
                if count < 1:
                    self._json(416, {'error': '잘못된 Range'})
                    return
                start = max(size - count, 0)
            else:
                start = int(match[1])
            if match[1] and match[2]:
                end = min(int(match[2]), size - 1)
            if start >= size or end < start:
                self._json(416, {'error': '파일 범위를 벗어났습니다'})
                return
            status = 206
        count = end - start + 1
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(count))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Accept-Ranges', 'bytes' if range_allowed else 'none')
        if status == 206:
            self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        self.end_headers()
        with path.open('rb') as stream:
            stream.seek(start)
            remaining = count
            while remaining:
                chunk = stream.read(min(131_072, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def do_GET(self):
        valid_hosts = {f'127.0.0.1:{self.server.server_port}',
                       f'localhost:{self.server.server_port}'}
        if self.headers.get('Host') not in valid_hosts:
            self._json(403, {'error': '로컬 접근만 허용합니다'})
            return
        path = urlsplit(self.path).path
        if path == '/api/tutorial/health':
            self._json(200, {'service': 'go2-tutorial', 'ok': True})
        elif path == '/api/tutorial/maps':
            self._json(200, {'maps': public_maps()})
        elif re.fullmatch(r'/api/tutorial/maps/[^/]+/image', path):
            encoded = path[len('/api/tutorial/maps/'):-len('/image')]
            try:
                image, _ = resolve_image(unquote(encoded))
                self._file(image, 'image/png')
            except (MapCatalogError, OSError):
                self._json(404, {'error': '지도 이미지를 찾을 수 없습니다'})
        elif path in STATIC_FILES:
            file = STATIC_FILES[path]
            mime = 'video/mp4' if file.suffix == '.mp4' else (
                'image/png' if file.suffix == '.png' else 'text/html; charset=utf-8')
            self._file(file, mime, range_allowed=file.suffix == '.mp4')
        else:
            self._json(404, {'error': '페이지를 찾을 수 없습니다'})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8766)
    parser.add_argument('--background', action='store_true',
                        help='Start read-only viewer without occupying the PC terminal')
    args = parser.parse_args()
    if args.port < 1024 or args.port > 65535:
        parser.error('--port must be in 1024..65535')
    address = f'http://127.0.0.1:{args.port}'
    if args.background:
        with socket.socket() as client:
            client.settimeout(0.5)
            if client.connect_ex(('127.0.0.1', args.port)) == 0:
                print('[map] 포트가 이미 사용 중입니다: ' + address)
                return
        subprocess.Popen([sys.executable, str(Path(__file__).resolve()),
                          '--port', str(args.port)],
                         cwd=REPO, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
        print('[map] 튜토리얼: ' + address)
        return
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    print('[map] 튜토리얼: ' + address, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
