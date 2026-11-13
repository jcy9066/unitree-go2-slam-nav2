"""Exercise map transfer with synthetic SQLite data; never open operator maps."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('map_archives', ROOT / 'scripts/map_archives.py')
maps = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(maps)
pytestmark = pytest.mark.skipif(shutil.which('zstd') is None, reason='zstd is required')


def project(root):
    root.mkdir()
    config = json.loads((ROOT / 'environment.json').read_text())
    (root / 'environment.json').write_text(json.dumps(config))
    folder = root / 'maps' / '창학관 3층'
    folder.mkdir(parents=True)
    return maps.MapArchives(root), folder / 'rtabmap.db'


def create_database(path, text='synthetic map'):
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE Node(id INTEGER PRIMARY KEY, data BLOB)')
        db.execute('INSERT INTO Node VALUES(1, ?)', ((text * 500).encode(),))
        db.execute('CREATE TABLE Admin(version TEXT)')
        db.execute("INSERT INTO Admin VALUES('test-only')")


@pytest.fixture
def producer(tmp_path):
    app, db = project(tmp_path / 'producer')
    create_database(db)
    return app, db


def transfer(app, db, root):
    consumer, target = project(root)
    for source, dest in zip(app.paths(db), consumer.paths(target)):
        shutil.copyfile(source, dest)
    return consumer, target


def state(folder):
    return {p.name: (maps.checksum(p), p.stat().st_mtime_ns)
            for p in folder.iterdir() if p.is_file()}


def test_roundtrip_between_computers_and_idempotence(producer, tmp_path):
    app, db = producer
    db.chmod(0o444)
    original = state(db.parent)
    app.run('setup')
    assert state(db.parent)[db.name] == original[db.name]
    packed = state(db.parent)
    app.pack(db)
    assert state(db.parent) == packed
    consumer, target = transfer(app, db, tmp_path / 'consumer')
    consumer.run('setup')
    assert target.read_bytes() == db.read_bytes()
    restored = state(target.parent)
    consumer.restore(target)
    consumer.verify(target)
    assert state(target.parent) == restored
    metadata = json.loads(app.paths(db)[1].read_text())
    assert metadata['database']['nodes'] == 1
    assert metadata['database']['version'] == 'test-only'
    assert str(app.root) not in json.dumps(metadata)
    assert metadata['database']['file'] == 'rtabmap.db'


def test_plan_and_standalone_verify_are_read_only(producer):
    app, db = producer
    before = state(db.parent)
    app.run('plan')
    app.verify(db)
    assert state(db.parent) == before


def test_existing_different_database_is_preserved(producer, tmp_path):
    app, db = producer
    app.pack(db)
    consumer, target = transfer(app, db, tmp_path / 'consumer')
    create_database(target, 'different map')
    before = state(target.parent)
    with pytest.raises(maps.MapError, match='덮어쓰지'):
        consumer.restore(target)
    assert state(target.parent) == before


@pytest.mark.parametrize('suffix', ['-journal', '-shm', '-wal'])
def test_sidecars_refuse_compression(producer, suffix):
    app, db = producer
    Path(str(db) + suffix).write_bytes(b'keep sidecar')
    before = state(db.parent)
    with pytest.raises(maps.MapError, match='부수 파일'):
        app.pack(db)
    assert state(db.parent) == before


def test_wal_header_refused_without_creating_sidecars(producer):
    app, db = producer
    with sqlite3.connect(db) as connection:
        connection.execute('PRAGMA journal_mode=WAL')
    assert not Path(str(db) + '-wal').exists()
    before = state(db.parent)
    with pytest.raises(maps.MapError, match='WAL 모드'):
        app.pack(db)
    assert state(db.parent) == before


@pytest.mark.parametrize('damage', ['archive', 'raw_hash', 'raw_size', 'nodes', 'metadata'])
def test_corruption_never_publishes_database(producer, tmp_path, damage):
    app, db = producer
    app.pack(db)
    consumer, target = transfer(app, db, tmp_path / 'consumer')
    archive, metadata = consumer.paths(target)
    value = json.loads(metadata.read_text())
    if damage == 'archive':
        with archive.open('ab') as stream:
            stream.write(b'corrupt')
    elif damage == 'metadata':
        metadata.write_text('{}')
    else:
        if damage == 'raw_hash':
            value['database']['sha256'] = '0' * 64
        elif damage == 'raw_size':
            value['database']['size'] = 1
        else:
            value['database']['nodes'] = 2
        metadata.write_text(json.dumps(value))
    with pytest.raises((maps.MapError, KeyError)):
        consumer.restore(target)
    assert not target.exists()
    assert not list(target.parent.glob('.setup_maps-*'))


def test_lfs_pointer_requires_manual_download(producer):
    app, db = producer
    archive, _ = app.paths(db)
    archive.write_text('version https://git-lfs.github.com/spec/v1\noid sha256:' + '0' * 64 + '\nsize 99\n')
    with pytest.raises(maps.MapError, match='git lfs pull'):
        app.restore(db)


@pytest.mark.parametrize('name', ['..', '../other', '/tmp', 'map/name'])
def test_names_cannot_escape_maps(producer, name):
    app, _ = producer
    with pytest.raises(maps.MapError):
        app.discover(name)


def test_database_symlink_is_refused(producer):
    app, db = producer
    link = db.parent / 'alias.db'
    link.symlink_to(db.name)
    with pytest.raises(maps.MapError, match='심볼릭 링크'):
        app.pack(link)


def test_archive_replacement_is_explicit_and_preserves_source(producer):
    app, db = producer
    app.pack(db)
    archive, metadata = app.paths(db)
    original_archive = archive.read_bytes()
    with sqlite3.connect(db) as connection:
        connection.execute('INSERT INTO Node VALUES(2, ?)', (b'new observation',))
    source = db.read_bytes()
    with pytest.raises(maps.MapError, match='replace-archive'):
        app.pack(db)
    assert archive.read_bytes() == original_archive
    app.pack(db, replace_archive=True)
    assert db.read_bytes() == source
    assert json.loads(metadata.read_text())['database']['nodes'] == 2
    app.verify(db)


def test_source_mutation_aborts_before_publication(producer, monkeypatch):
    app, db = producer
    decode = app.decode

    def mutate(*args, **kwargs):
        result = decode(*args, **kwargs)
        with db.open('ab') as stream:
            stream.write(b'external source change')
        return result

    monkeypatch.setattr(app, 'decode', mutate)
    with pytest.raises(maps.MapError, match='처리 중 DB'):
        app.pack(db)
    assert not any(p.exists() for p in app.paths(db))
    assert not list(db.parent.glob('.setup_maps-*'))


def test_compressor_failure_cleans_temporary_outputs(producer, monkeypatch):
    app, db = producer
    monkeypatch.setattr(app, 'zstd', lambda: '/bin/false')
    before = state(db.parent)
    with pytest.raises((maps.MapError, BrokenPipeError)):
        app.pack(db)
    assert state(db.parent) == before


def test_wrapper_works_outside_repository(producer, tmp_path):
    app, db = producer
    scripts = app.root / 'scripts'
    scripts.mkdir()
    shutil.copyfile(ROOT / 'setup_maps.sh', app.root / 'setup_maps.sh')
    shutil.copyfile(ROOT / 'scripts/map_archives.py', scripts / 'map_archives.py')
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
    result = subprocess.run(['bash', str(app.root / 'setup_maps.sh'), 'pack', '창학관 3층'],
                            cwd=tmp_path, env=env, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert 'PACK OK' in result.stdout
    assert app.paths(db)[0].is_file()


@pytest.mark.skipif(shutil.which('git-lfs') is None, reason='git-lfs is required')
def test_lfs_stages_archive_pointer_but_plain_metadata(producer):
    app, db = producer
    app.pack(db)

    def git(*args):
        return subprocess.check_output(['git', *args], cwd=app.root, text=True,
                                       stderr=subprocess.STDOUT)

    git('init', '-b', 'synthetic-map-test')
    git('lfs', 'install', '--local')
    (app.root / '.gitattributes').write_text((ROOT / '.gitattributes').read_text())
    archive, metadata = app.paths(db)
    git('add', '.gitattributes', str(archive.relative_to(app.root)), str(metadata.relative_to(app.root)))
    pointer = git('show', ':' + archive.relative_to(app.root).as_posix())
    assert pointer.startswith(maps.LFS_POINTER.decode())
    assert json.loads(git('show', ':' + metadata.relative_to(app.root).as_posix()))['codec'] == 'zstd'
