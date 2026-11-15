#!/usr/bin/env python3
"""Shared local map catalog. No robot access, SSH, network, or DB modification."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import tempfile

SCHEMA = 1


class MapCatalogError(ValueError):
    pass


def map_root():
    return Path(os.environ.get('GO2_MAP_DIR', str(Path.home() / 'maps'))).expanduser().resolve()


def _safe_directory(root, identifier):
    if not re.fullmatch(r'[^\x00-\x1f/\\]{1,120}', identifier) or identifier in {'.', '..'}:
        raise MapCatalogError('잘못된 지도 ID')
    folder = root / identifier
    if folder.is_symlink() or not folder.is_dir() or folder.resolve().parent != root.resolve():
        raise MapCatalogError('지도 디렉터리를 찾을 수 없습니다')
    db = folder / 'rtabmap.db'
    if db.is_symlink() or not db.is_file() or not db.stat().st_size:
        raise MapCatalogError('유효한 지도 DB 파일이 없습니다')
    return folder, db


def _atomic_json(path, payload):
    if path.is_symlink():
        raise MapCatalogError('메타데이터 심볼릭 링크는 사용할 수 없습니다')
    descriptor, temporary = tempfile.mkstemp(prefix='.metadata-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _valid_name(name):
    if not isinstance(name, str):
        raise MapCatalogError('지도 이름은 문자열이어야 합니다')
    name = name.strip()
    if not name or len(name) > 80 or any(ord(char) < 32 for char in name):
        raise MapCatalogError('지도 이름은 1~80자이며 제어 문자를 포함할 수 없습니다')
    return name


def info(root, identifier):
    folder, db = _safe_directory(root, identifier)
    file = folder / 'metadata.json'
    metadata = {}
    if file.is_file() and not file.is_symlink():
        try:
            metadata = json.loads(file.read_text(encoding='utf-8'))
        except (ValueError, OSError):
            metadata = {}
    created = metadata.get('created_at')
    if not isinstance(created, str) or not created:
        created = datetime.fromtimestamp(db.stat().st_mtime, timezone.utc).astimezone().isoformat(timespec='seconds')
    name = metadata.get('name')
    if not isinstance(name, str) or not name.strip():
        name = identifier
    preview = folder / 'preview.png'
    return {'id': identifier, 'name': name, 'created_at': created,
            'has_preview': preview.is_file() and not preview.is_symlink(),
            'database': str(db)}


def list_maps(root=None):
    root = Path(root or map_root()).expanduser().resolve()
    if not root.is_dir():
        return []
    rows = []
    for folder in root.iterdir():
        if folder.is_symlink() or not folder.is_dir() or folder.name in {'mapping_sessions', 'nav_sessions'}:
            continue
        try:
            rows.append(info(root, folder.name))
        except (MapCatalogError, OSError):
            continue
    return sorted(rows, key=lambda row: row['created_at'], reverse=True)


def list_available_maps(root=None):
    """CLI may also select an already restored repository map; admin UI stays ~/maps-only."""
    runtime = Path(root or map_root()).expanduser().resolve()
    repository_maps = Path(__file__).resolve().parents[1] / 'maps'
    rows = list_maps(runtime)
    if repository_maps.is_dir() and repository_maps.resolve() != runtime:
        rows.extend(list_maps(repository_maps))
    return sorted(rows, key=lambda row: row['created_at'], reverse=True)


def register(database, root=None):
    root = Path(root or map_root()).expanduser().resolve()
    database = Path(database).expanduser().resolve()
    if database.name != 'rtabmap.db' or database.parent.parent != root:
        raise MapCatalogError('새 지도는 ~/maps/<지도 ID>/rtabmap.db 위치에 저장해야 합니다')
    folder, _ = _safe_directory(root, database.parent.name)
    path = folder / 'metadata.json'
    if path.exists() or path.is_symlink():
        return info(root, folder.name)
    created = datetime.now().astimezone().isoformat(timespec='seconds')
    _atomic_json(path, {'schema_version': SCHEMA, 'name': '이름 미지정',
                        'created_at': created})
    return info(root, folder.name)


def rename(identifier, name, root=None):
    root = Path(root or map_root()).expanduser().resolve()
    folder, _ = _safe_directory(root, identifier)
    row = info(root, identifier)
    _atomic_json(folder / 'metadata.json',
                 {'schema_version': SCHEMA, 'name': _valid_name(name),
                  'created_at': row['created_at']})
    return info(root, identifier)


def selected_path(root=None):
    root = Path(root or map_root()).expanduser().resolve()
    for pointer in ('.selected_map', '.last_map'):
        path = root / pointer
        if not path.is_file() or path.is_symlink():
            continue
        selected = Path(path.read_text(encoding='utf-8').strip()).expanduser().resolve()
        repository_maps = (Path(__file__).resolve().parents[1] / 'maps').resolve()
        for trusted_root in (root, repository_maps):
            if selected.parent.parent != trusted_root:
                continue
            try:
                _, db = _safe_directory(trusted_root, selected.parent.name)
                if db == selected:
                    return str(db)
            except MapCatalogError:
                continue
    return None


def choose(root=None):
    root = Path(root or map_root()).expanduser().resolve()
    rows = list_available_maps(root)
    if not rows:
        raise MapCatalogError('선택 가능한 지도가 없습니다. 신규 Mapping을 진행하세요')
    if not sys.stdin.isatty():
        raise MapCatalogError('지도 선택은 대화형 터미널에서 진행해야 합니다')
    print('\n저장된 지도', file=sys.stderr)
    for i, row in enumerate(rows, 1):
        print(f" {i}. {row['name']} | {row['created_at']}", file=sys.stderr)
    answer = input('지도 번호를 선택하세요: ').strip()
    if not answer.isdecimal() or not (1 <= int(answer) <= len(rows)):
        raise MapCatalogError('잘못된 지도 번호')
    selected = rows[int(answer) - 1]['database']
    root.mkdir(parents=True, exist_ok=True)
    pointer = root / '.selected_map'
    if pointer.is_symlink():
        raise MapCatalogError('지도 선택 포인터가 심볼릭 링크입니다')
    descriptor, temporary = tempfile.mkstemp(prefix='.selected-', dir=root)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            stream.write(selected + '\n')
        os.replace(temporary, pointer)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return selected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['list', 'register', 'rename', 'choose', 'selected'])
    parser.add_argument('arguments', nargs='*')
    options = parser.parse_args()
    try:
        if options.action == 'list':
            print(json.dumps(list_maps(), ensure_ascii=False))
        elif options.action == 'register' and len(options.arguments) == 1:
            print(json.dumps(register(options.arguments[0]), ensure_ascii=False))
        elif options.action == 'rename' and len(options.arguments) == 2:
            print(json.dumps(rename(*options.arguments), ensure_ascii=False))
        elif options.action == 'choose' and not options.arguments:
            print(choose())
        elif options.action == 'selected' and not options.arguments:
            path = selected_path()
            if not path:
                raise MapCatalogError('선택된 지도 없음')
            print(path)
        else:
            parser.error('잘못된 인자')
    except (MapCatalogError, OSError, ValueError) as error:
        parser.exit(1, '[map] ' + str(error) + '\n')


if __name__ == '__main__':
    main()
