#!/usr/bin/env python3
"""Standalone loopback-only map manager; no Go2/ROS/Nav2 operations."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

from scripts.map_catalog import MapCatalogError, _safe_directory, list_maps, map_root, rename

ROOT = Path(__file__).resolve().parent


def public_row(row):
    return {'id': row['id'], 'name': row['name'],
            'date': row['created_at'], 'preview': row['has_preview']}


class Handler(BaseHTTPRequestHandler):
    server_version = 'Go2MapManager/1.0'

    def _headers(self, status, content_type, length):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(length))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Content-Security-Policy',
                         "default-src 'none'; style-src 'self' 'unsafe-inline'; "
                         "script-src 'self' 'unsafe-inline'; img-src 'self'; connect-src 'self'; "
                         "base-uri 'none'; form-action 'none'")
        self.end_headers()

    def _send(self, status, payload, content_type='application/json; charset=utf-8'):
        body = (json.dumps(payload, ensure_ascii=False).encode('utf-8')
                if content_type.startswith('application/json') else payload)
        self._headers(status, content_type, len(body))
        self.wfile.write(body)

    def _origin_ok(self):
        origin = self.headers.get('Origin')
        host = self.headers.get('Host', '')
        valid_hosts = {f'127.0.0.1:{self.server.server_port}',
                       f'localhost:{self.server.server_port}'}
        return (host in valid_hosts and
                (not origin or origin in {'http://' + h for h in valid_hosts}) and
                self.headers.get('Sec-Fetch-Site', '') != 'cross-site')

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == '/':
            self._send(200, (ROOT / 'map_manager.html').read_bytes(), 'text/html; charset=utf-8')
            return
        if path == '/api/maps':
            rows = [public_row(r) for r in list_maps()]
            self._send(200, {'maps': rows})
            return
        match = re.fullmatch(r'/api/maps/([^/]+)/preview', path)
        if match:
            try:
                identifier = unquote(match.group(1))
                directory, _ = _safe_directory(map_root(), identifier)
                preview = directory / 'preview.png'
                if preview.is_symlink() or not preview.is_file() or preview.stat().st_size > 8_000_000:
                    raise MapCatalogError('미리보기가 없습니다')
                data = preview.read_bytes()
                if not data.startswith(b'\x89PNG\r\n\x1a\n'):
                    raise MapCatalogError('PNG 미리보기 형식이 아닙니다')
                self._send(200, data, 'image/png')
            except (MapCatalogError, OSError):
                self._send(404, {'error': '미리보기 없음'})
            return
        self._send(404, {'error': '페이지를 찾을 수 없습니다'})

    def do_POST(self):
        match = re.fullmatch(r'/api/maps/([^/]+)/rename', urlsplit(self.path).path)
        if not match:
            self._send(404, {'error': '허용되지 않은 요청'})
            return
        if not self._origin_ok() or self.headers.get_content_type() != 'application/json':
            self._send(403, {'error': '로컬 동일 출처 JSON 요청만 허용합니다'})
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if length < 1 or length > 8192:
                raise MapCatalogError('요청 크기가 잘못되었습니다')
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict) or 'name' not in body:
                raise MapCatalogError('name 필드가 필요합니다')
            updated = rename(unquote(match.group(1)), body['name'])
            self._send(200, {'map': public_row(updated)})
        except (MapCatalogError, OSError, ValueError, TypeError) as error:
            self._send(400, {'error': str(error)})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error('port must be 1024..65535')
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    print(f'[map] 관리자 페이지: http://127.0.0.1:{args.port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
