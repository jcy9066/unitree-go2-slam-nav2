#!/usr/bin/env python3
"""Local map archives. Git transfer and robot operation belong to the operator."""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
BLOCK = 4 * 1024 * 1024
LFS_POINTER = b'version https://git-lfs.github.com/spec/v1'


class MapError(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise MapError(message)


def checksum(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(BLOCK), b''):
            digest.update(chunk)
    return digest.hexdigest()


def regular_file(path):
    require(not path.is_symlink() and path.is_file(),
            '일반 파일이 필요합니다(심볼릭 링크 제외): ' + str(path))


@contextmanager
def database_snapshot(path):
    """Hold a SQLite read transaction; never recover or checkpoint a source DB."""
    regular_file(path)
    for suffix in ('-journal', '-wal', '-shm'):
        sidecar = Path(str(path) + suffix)
        require(not sidecar.exists() and not sidecar.is_symlink(),
                'DB 부수 파일이 있습니다. Mapping을 정상 종료하고 저장 상태를 확인하세요: ' + str(sidecar))
    before = path.stat()
    with path.open('rb') as stream:
        header = stream.read(100)
    require(header.startswith(b'SQLite format 3\x00'), 'SQLite DB가 아닙니다: ' + str(path))
    require(header[18:20] != b'\x02\x02',
            'WAL 모드 DB는 완성된 독립 백업본을 준비한 뒤 사용하세요: ' + str(path))
    with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=2,
                         isolation_level=None) as db:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        try:
            result = db.execute('PRAGMA quick_check').fetchall()
            require(result == [('ok',)], 'DB 무결성 검사 실패: ' + str(path))
            nodes = db.execute('SELECT COUNT(*) FROM Node').fetchone()[0]
            require(nodes > 0, '저장된 관측 지점이 없습니다: ' + str(path))
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            version = db.execute('SELECT version FROM Admin LIMIT 1').fetchone() if 'Admin' in tables else None
            yield {'size': before.st_size, 'nodes': nodes,
                   'version': version[0] if version else None}
            after = path.stat()
            require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) ==
                    (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns),
                    '처리 중 DB가 바뀌었습니다. 결과를 사용하지 않습니다: ' + str(path))
        finally:
            db.execute('ROLLBACK')


@contextmanager
def temporary_output(directory):
    descriptor, name = tempfile.mkstemp(prefix='.setup_maps-', suffix='.tmp', dir=directory)
    os.close(descriptor)
    path = Path(name)
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)


@contextmanager
def map_lock(path):
    key = hashlib.sha256(str(path).encode()).hexdigest()
    lock = Path(tempfile.gettempdir()) / ('go2-map-' + str(os.getuid()) + '-' + key + '.lock')
    descriptor = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise MapError('같은 지도를 처리하는 setup_maps가 실행 중입니다: ' + str(path)) from error
        yield
    finally:
        os.close(descriptor)


@contextmanager
def codec_process(command, **kwargs):
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(command, stderr=errors, **kwargs)
        try:
            yield process
            code = process.wait()
            if code:
                errors.seek(0)
                detail = errors.read(8192).decode(errors='replace').strip()
                raise MapError('zstd 실패: ' + detail)
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            if process.stdin:
                process.stdin.close()
            if process.stdout:
                process.stdout.close()


class MapArchives:
    def __init__(self, root=ROOT):
        self.root = Path(root).resolve()
        self.config = json.loads((self.root / 'environment.json').read_text())['maps']
        relative = Path(self.config['root'])
        require(not relative.is_absolute() and '..' not in relative.parts,
                'maps.root는 저장소 내부 상대 경로여야 합니다.')
        self.directory = self.root / relative
        require(not self.directory.is_symlink(), 'maps 폴더에 심볼릭 링크를 사용할 수 없습니다.')
        require(self.config['archive_suffix'] == '.zst' and self.config['metadata_suffix'] == '.json',
                '지원하는 지도 형식은 .db.zst와 생성된 .json 메타데이터입니다.')
        require(type(self.config['compression_level']) is int and
                1 <= self.config['compression_level'] <= 19, '압축 수준은 1~19여야 합니다.')
        require(type(self.config['compression_threads']) is int and
                1 <= self.config['compression_threads'] <= 32, '잘못된 압축 스레드 수입니다.')

    def discover(self, name=None):
        require(self.directory.is_dir(), '지도 폴더가 없습니다: ' + str(self.directory))
        if name:
            require(name not in ('.', '..') and '/' not in name and '\\' not in name and
                    not any(ord(char) < 32 for char in name), '지도 폴더 이름만 입력하세요.')
            directories = [self.directory / name]
        else:
            directories = sorted(p for p in self.directory.iterdir()
                                 if p.is_dir() and not p.name.startswith('.'))
        databases = []
        for directory in directories:
            require(directory.is_dir() and not directory.is_symlink(),
                    '지도 폴더가 없거나 심볼릭 링크입니다: ' + str(directory))
            names = {p.name for p in directory.glob('*.db')}
            names.update(p.name[:-4] for p in directory.glob('*.db.zst'))
            databases.extend(directory / filename for filename in sorted(names))
        require(databases, '처리할 .db 또는 .db.zst가 없습니다.')
        return databases

    def paths(self, database):
        archive = Path(str(database) + self.config['archive_suffix'])
        return archive, Path(str(archive) + self.config['metadata_suffix'])

    def zstd(self):
        command = shutil.which('zstd')
        require(command is not None, 'zstd가 없습니다. environment.json의 프로젝트 환경을 준비하세요.')
        return command

    def read_metadata(self, database):
        archive, metadata = self.paths(database)
        regular_file(archive)
        with archive.open('rb') as stream:
            require(not stream.read(128).startswith(LFS_POINTER),
                    '지도 대신 Git LFS 포인터가 있습니다. 사용자가 git lfs pull을 실행하세요: ' + str(archive))
        regular_file(metadata)
        value = json.loads(metadata.read_text())
        require(value.get('schema_version') == 1 and value.get('codec') == 'zstd', '지원하지 않는 지도 메타데이터입니다.')
        for key, path in [('database', database), ('archive', archive)]:
            entry = value[key]
            require(entry['file'] == path.name, '지도 메타데이터 파일명이 다릅니다: ' + str(metadata))
            require(type(entry['size']) is int and entry['size'] > 0, '잘못된 지도 파일 크기입니다.')
            digest = entry['sha256']
            require(isinstance(digest, str) and len(digest) == 64 and
                    all(char in '0123456789abcdef' for char in digest), '잘못된 지도 SHA256입니다.')
        require(type(value['database']['nodes']) is int and value['database']['nodes'] > 0,
                '잘못된 지도 관측 지점 수입니다.')
        require(archive.stat().st_size == value['archive']['size'] and
                checksum(archive) == value['archive']['sha256'], '압축본 크기/SHA256 불일치: ' + str(archive))
        return value

    def decode(self, archive, expected_size=None, output=None):
        digest = hashlib.sha256()
        size = 0
        with codec_process([self.zstd(), '-d', '-c', '--no-progress', str(archive)],
                           stdout=subprocess.PIPE) as process:
            for chunk in iter(lambda: process.stdout.read(BLOCK), b''):
                size += len(chunk)
                require(expected_size is None or size <= expected_size, '압축 해제 크기가 메타데이터를 초과했습니다.')
                digest.update(chunk)
                if output is not None:
                    output.write(chunk)
        return size, digest.hexdigest()

    def pack(self, database, replace_archive=False):
        archive, metadata = self.paths(database)
        require(not archive.is_symlink() and not metadata.is_symlink(), '압축본 경로에 심볼릭 링크가 있습니다.')
        with map_lock(database), database_snapshot(database) as info:
            if archive.exists() or metadata.exists():
                try:
                    existing = self.read_metadata(database)
                    if info['size'] == existing['database']['size'] and checksum(database) == existing['database']['sha256']:
                        print('REUSE 압축본: ' + str(archive))
                        return
                except (MapError, OSError, ValueError, KeyError, TypeError):
                    if not replace_archive:
                        raise
                require(replace_archive,
                        '다른 내용의 압축본을 보존합니다. 갱신하려면 pack --replace-archive를 명시하세요: ' + str(archive))
            print('PACK ' + str(database), flush=True)
            with temporary_output(database.parent) as temporary, temporary_output(database.parent) as temporary_meta:
                digest = hashlib.sha256()
                size = 0
                with temporary.open('wb') as output, database.open('rb') as source:
                    command = [self.zstd(), '-c', '-' + str(self.config['compression_level']),
                               '-T' + str(self.config['compression_threads']), '--no-progress']
                    with codec_process(command, stdin=subprocess.PIPE, stdout=output) as process:
                        for chunk in iter(lambda: source.read(BLOCK), b''):
                            digest.update(chunk)
                            size += len(chunk)
                            process.stdin.write(chunk)
                        process.stdin.close()
                    output.flush()
                    os.fsync(output.fileno())
                require(size == info['size'], '처리 중 원본 DB 크기가 바뀌었습니다.')
                raw_hash = digest.hexdigest()
                require(self.decode(temporary, size) == (size, raw_hash), '압축 왕복 검증 실패')
                value = {'schema_version': 1, 'codec': 'zstd',
                         'database': {'file': database.name, 'size': size, 'sha256': raw_hash,
                                      'nodes': info['nodes'], 'version': info['version']},
                         'archive': {'file': archive.name, 'size': temporary.stat().st_size,
                                     'sha256': checksum(temporary)},
                         'compression': {'level': self.config['compression_level'],
                                         'threads': self.config['compression_threads']}}
                temporary_meta.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n')
                if replace_archive:
                    os.replace(temporary, archive)
                    os.replace(temporary_meta, metadata)
                else:
                    os.link(temporary, archive)
                    try:
                        os.link(temporary_meta, metadata)
                    except BaseException:
                        archive.unlink()
                        raise
            print('PACK OK ' + str(archive) + ' + ' + metadata.name)

    def restore(self, database):
        archive, _ = self.paths(database)
        with map_lock(database):
            value = self.read_metadata(database)
            expected = value['database']
            if database.exists() or database.is_symlink():
                with database_snapshot(database) as info:
                    require(info['size'] == expected['size'] and checksum(database) == expected['sha256'],
                            '기존 DB가 압축본과 다릅니다. 기존 파일은 덮어쓰지 않습니다: ' + str(database))
                print('REUSE DB: ' + str(database))
                return
            require(shutil.disk_usage(database.parent).free >= expected['size'],
                    'DB 복원에 필요한 여유 공간이 없습니다: ' + str(database.parent))
            print('RESTORE ' + str(database), flush=True)
            with temporary_output(database.parent) as temporary:
                with temporary.open('wb') as output:
                    result = self.decode(archive, expected['size'], output)
                    output.flush()
                    os.fsync(output.fileno())
                require(result == (expected['size'], expected['sha256']), '복원 DB 크기/SHA256 불일치')
                with database_snapshot(temporary) as info:
                    require(info['nodes'] == expected['nodes'], '복원 DB 관측 지점 수 불일치')
                # Exclusive publication prevents overwriting a DB created concurrently.
                os.link(temporary, database)
            print('RESTORE OK ' + str(database))

    def verify(self, database):
        archive, _ = self.paths(database)
        if archive.exists():
            value = self.read_metadata(database)
            expected = value['database']
            require(self.decode(archive, expected['size']) == (expected['size'], expected['sha256']),
                    '압축본 왕복 검증 실패')
            if database.exists() or database.is_symlink():
                with database_snapshot(database) as info:
                    require(info['size'] == expected['size'] and checksum(database) == expected['sha256'],
                            '기존 DB가 압축본과 다릅니다: ' + str(database))
        else:
            with database_snapshot(database):
                checksum(database)
        print('VERIFY OK ' + str(database))

    def run(self, mode, name=None, replace_archive=False):
        require(not replace_archive or mode == 'pack', '--replace-archive는 pack에서만 사용할 수 있습니다.')
        for database in self.discover(name):
            archive, metadata = self.paths(database)
            if mode == 'plan':
                action = 'RESTORE/VERIFY' if archive.exists() else 'PACK'
                print(action + ' ' + str(database) + ' <-> ' + archive.name + ' + ' + metadata.name)
                continue
            action = ('restore' if archive.exists() else 'pack') if mode == 'setup' else mode
            if action == 'pack':
                self.pack(database, replace_archive)
            elif action == 'restore':
                self.restore(database)
            else:
                self.verify(database)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', nargs='?', default='setup',
                        choices=['setup', 'pack', 'restore', 'verify', 'plan'])
    parser.add_argument('map_name', nargs='?', help='maps/ 아래 지도 폴더 이름; 생략하면 전체')
    parser.add_argument('--replace-archive', action='store_true',
                        help='pack에서 기존 압축본·생성 메타데이터만 갱신; 원본 DB는 보존')
    args = parser.parse_args(argv)
    try:
        MapArchives().run(args.mode, args.map_name, args.replace_archive)
    except (MapError, OSError, sqlite3.Error, ValueError, KeyError, TypeError) as error:
        parser.exit(1, 'ERROR: ' + str(error) + '\n')
    except KeyboardInterrupt:
        parser.exit(130, '중단했습니다. 원본 DB는 보존했습니다.\n')


if __name__ == '__main__':
    main()
