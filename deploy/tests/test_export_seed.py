"""deploy/export_exhibits.py and deploy/seed_exhibits.py, end to end on a made-up city."""

from __future__ import annotations

import hashlib
import io
import json
import os
import sqlite3
import tarfile
from pathlib import Path

import pytest

import export_exhibits
import seed_exhibits
from conftest import count, fts_problems, graph_ids, make_memory

from export_exhibits import ExportError, export
from seed_exhibits import SeedError, seed


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree(root: Path) -> dict:
    return {
        str(p.relative_to(root)): (p.stat().st_size, p.stat().st_mtime_ns)
        for p in sorted(root.rglob('*')) if p.is_file()
    }


def _export(city, out: Path, name: str = 'exhibits-test') -> dict:
    return export(city['uploads'], city['memory'], out, name, city['specs'])


# --------------------------------------------------------------------------- export


def test_export_packs_the_exhibits_and_only_their_graphs(city, tmp_path):
    before = _tree(city['uploads'])
    result = _export(city, tmp_path / 'out')
    assert _tree(city['uploads']) == before  # nothing written into uploads, not even -wal/-shm

    archive = Path(result['archive'])
    assert archive.name == 'exhibits-test.tar.gz'
    sidecar = (tmp_path / 'out' / 'exhibits-test.tar.gz.sha256').read_text()
    assert sidecar.split()[0] == result['sha256'] == _sha(archive)

    with tarfile.open(archive) as tar:
        names = tar.getnames()
        manifest = json.loads(tar.extractfile('manifest.json').read())
        tar.extractall(tmp_path / 'x', filter='data')
    assert names[0] == 'manifest.json'
    assert manifest['format'] == 'parthenon-exhibits/1'
    assert [e['title'] for e in manifest['exhibits']] == ['Exhibit 1', 'Exhibit 2']
    (p1, s1, r1), (p2, s2, r2), (p3, s3, r3) = city['ids']
    assert manifest['exhibits'][0] == {
        'title': 'Exhibit 1', 'project_id': p1, 'simulation_id': s1, 'report_id': r1,
        'graph_id': 'mirofish_graph1',
    }
    listed = {f['path'] for f in manifest['files']}
    assert f'uploads/simulations/{s1}/portraits/0.jpg' in listed
    assert f'uploads/reports/{r2}/film/film.mp4' in listed
    assert f'uploads/projects/{p1}/files/scroll.md' in listed
    assert not any(p3 in p or s3 in p or r3 in p for p in listed)  # the third gathering stays home
    assert not any(p.endswith('simulation.log') or '/ipc_' in p for p in listed)
    assert set(names) == listed | {'manifest.json', 'memory/exhibits.sqlite3'}

    copy = tmp_path / 'x' / 'memory' / 'exhibits.sqlite3'
    assert graph_ids(copy) == ['mirofish_graph1', 'mirofish_graph2']
    assert count(copy, 'nodes', 'mirofish_graph1') == 3
    assert count(copy, 'edges', 'mirofish_graph2') == 1
    conn = sqlite3.connect(copy)
    assert conn.execute('SELECT COUNT(*) FROM batch_items').fetchone()[0] == 2
    assert conn.execute('SELECT COUNT(*) FROM batches').fetchone()[0] == 2
    assert sorted(r[0] for r in conn.execute('SELECT scope_id FROM usage')) == ['mirofish_graph1', 'mirofish_graph2']
    assert conn.execute("SELECT COUNT(*) FROM nodes_fts WHERE nodes_fts MATCH 'graph3'").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM nodes_fts WHERE nodes_fts MATCH 'graph1'").fetchone()[0] == 3
    conn.close()
    assert fts_problems(copy) == []
    assert manifest['memory']['graphs']['mirofish_graph1'] == {'nodes': 3, 'edges': 2, 'episodes': 1}
    # The live database still has every graph.
    assert graph_ids(city['memory']) == ['mirofish_graph1', 'mirofish_graph2', 'mirofish_graph3', 'mirofish_other']


def test_export_reads_an_open_wal_database_read_only(city, tmp_path):
    holder = sqlite3.connect(city['memory'])  # the running backend keeps it open in WAL mode
    holder.execute('PRAGMA journal_mode=WAL')
    holder.execute('SELECT COUNT(*) FROM graphs').fetchone()
    try:
        digest = _sha(city['memory'])
        result = _export(city, tmp_path / 'out')
        assert _sha(city['memory']) == digest
        assert set(result['graphs']) == {'mirofish_graph1', 'mirofish_graph2'}
    finally:
        holder.close()


def test_export_refuses_to_write_inside_uploads(city):
    with pytest.raises(ExportError, match='inside the uploads'):
        _export(city, city['uploads'] / 'exports')


def test_export_refuses_what_looks_like_a_key(city, tmp_path):
    _, sim, _ = city['ids'][0]
    key = 'sk-or-v1-' + 'ab' * 32
    (city['uploads'] / 'simulations' / sim / 'stances.json').write_text(json.dumps({'note': key}))
    with pytest.raises(ExportError, match='key or token'):
        _export(city, tmp_path / 'out')
    assert not (tmp_path / 'out' / 'exhibits-test.tar.gz').exists()


def test_export_checks_the_lineage(city, tmp_path):
    _, sim1, _ = city['ids'][0]
    _, _, report2 = city['ids'][1]
    with pytest.raises(ExportError, match='belongs to'):
        export(city['uploads'], city['memory'], tmp_path / 'out', 'x', [f'Mixed={sim1}:{report2}'])
    with pytest.raises(ExportError, match='TITLE=SIMULATION_ID:REPORT_ID'):
        export_exhibits.parse_exhibit('no-title')
    with pytest.raises(ExportError, match='bad simulation id'):
        export_exhibits.parse_exhibit('T=../etc:report_1')


def test_export_needs_the_graphs(city, tmp_path):
    conn = sqlite3.connect(city['memory'])
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute("DELETE FROM graphs WHERE graph_id = 'mirofish_graph2'")
    conn.commit()
    conn.close()
    with pytest.raises(ExportError, match='no graph mirofish_graph2'):
        _export(city, tmp_path / 'out')


def test_export_refuses_graphs_still_being_built(city, tmp_path):
    conn = sqlite3.connect(city['memory'])
    conn.execute("UPDATE episodes SET extraction_status = 'queued' WHERE graph_id = 'mirofish_graph1'")
    conn.commit()
    conn.close()
    with pytest.raises(ExportError, match='waiting for extraction'):
        _export(city, tmp_path / 'out')


# --------------------------------------------------------------------------- seed


@pytest.fixture
def archive(city, tmp_path):
    result = _export(city, tmp_path / 'out')
    return Path(result['archive']), result['sha256']


def test_seed_installs_once(city, archive, tmp_path):
    path, digest = archive
    data = tmp_path / 'data'
    logs = []
    assert seed(data, str(path), digest, log=logs.append) == 'installed'
    (p1, s1, r1), _, _ = city['ids']
    assert (data / 'uploads' / 'reports' / r1 / 'film' / 'film.mp4').read_bytes() == (
        city['uploads'] / 'reports' / r1 / 'film' / 'film.mp4'
    ).read_bytes()
    assert (data / 'uploads' / 'projects' / p1 / 'project.json').is_file()
    assert not (data / 'uploads' / 'simulations' / s1 / 'simulation.log').exists()
    db = data / 'uploads' / 'memory' / 'local_memory.sqlite3'
    assert graph_ids(db) == ['mirofish_graph1', 'mirofish_graph2']
    assert oct(db.stat().st_mode & 0o777) == '0o600'
    marker = json.loads((data / 'exhibits' / 'manifest.json').read_text())
    assert marker['memory'] == 'installed' and marker['archive_sha256'] == digest
    assert marker['files_installed'] > 0 and marker['files_kept'] == 0
    assert [e['project_id'] for e in marker['exhibits']] == [p1, city['ids'][1][0]]
    assert not list((data / 'exhibits').glob('.staging-*'))
    assert fts_problems(db) == []
    # The second boot does nothing, even with the archive gone.
    path.unlink()
    assert seed(data, str(path), digest) == 'present'


def test_seed_never_overwrites_and_merges_graphs(city, archive, tmp_path):
    path, digest = archive
    data = tmp_path / 'data'
    (p1, _, _), _, _ = city['ids']
    mine = data / 'uploads' / 'projects' / p1 / 'project.json'
    mine.parent.mkdir(parents=True)
    mine.write_text('{"mine": true}')
    db = data / 'uploads' / 'memory' / 'local_memory.sqlite3'
    db.parent.mkdir(parents=True)
    # A visitor's gathering already lives here, and one exhibit graph too.
    make_memory(db, {'mirofish_visitor': 2, 'mirofish_graph2': 5})
    assert seed(data, path.as_uri(), None) == 'installed'
    assert mine.read_text() == '{"mine": true}'
    assert graph_ids(db) == ['mirofish_graph1', 'mirofish_graph2', 'mirofish_visitor']
    assert count(db, 'nodes', 'mirofish_graph2') == 5  # the graph it had was left alone
    assert count(db, 'nodes', 'mirofish_graph1') == 3
    assert count(db, 'edges', 'mirofish_graph1') == 2
    conn = sqlite3.connect(db)
    assert conn.execute(
        'SELECT COUNT(*) FROM edge_episodes JOIN edges ON edges.uuid = edge_uuid WHERE graph_id = ?',
        ('mirofish_graph1',),
    ).fetchone()[0] == 2
    assert conn.execute('PRAGMA foreign_key_check').fetchall() == []
    conn.close()
    assert fts_problems(db) == []
    marker = json.loads((data / 'exhibits' / 'manifest.json').read_text())
    assert marker['memory'] == 'merged 1' and marker['files_kept'] == 1


def test_seed_rejects_a_wrong_sha256_and_leaves_no_marker(archive, tmp_path):
    path, digest = archive
    data = tmp_path / 'data'
    with pytest.raises(SeedError, match='sha256'):
        seed(data, str(path), '0' * 64)
    assert not (data / 'exhibits' / 'manifest.json').exists()
    assert not (data / 'uploads' / 'projects').exists()
    assert not list((data / 'exhibits').glob('.staging-*'))
    # The fragment form pins it too.
    with pytest.raises(SeedError, match='sha256'):
        seed(data, f'{path}#sha256={"1" * 64}')
    assert seed(data, f'{path}#sha256={digest}') == 'installed'


def _tar(path: Path, entries) -> Path:
    with tarfile.open(path, 'w:gz') as tar:
        for name, data, kind in entries:
            info = tarfile.TarInfo(name)
            if kind == 'symlink':
                info.type = tarfile.SYMTYPE
                info.linkname = data
                tar.addfile(info)
            else:
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
    return path


def _manifest(files) -> bytes:
    return json.dumps({
        'format': 'parthenon-exhibits/1', 'exhibits': [], 'files': [
            {'path': name, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()} for name, data in files
        ],
    }).encode()


@pytest.mark.parametrize('entries, message', [
    ([('manifest.json', b'{}', 'file'), ('../evil', b'x', 'file')], 'unexpected path'),
    ([('manifest.json', b'{}', 'file'), ('/etc/evil', b'x', 'file')], 'unexpected path'),
    ([('manifest.json', b'{}', 'file'), ('other/x', b'x', 'file')], 'unexpected path'),
    ([('manifest.json', b'{}', 'file'), ('uploads/link', '/etc/passwd', 'symlink')], 'link or device'),
    ([('uploads/a', b'x', 'file')], 'no manifest'),
    ([('manifest.json', b'{"format": "other"}', 'file')], 'not parthenon-exhibits/1'),
])
def test_seed_refuses_unsafe_archives(tmp_path, entries, message):
    bad = _tar(tmp_path / 'bad.tar.gz', entries)
    with pytest.raises(SeedError, match=message):
        seed(tmp_path / 'data', str(bad))
    assert not (tmp_path / 'data' / 'uploads').exists()
    assert not (tmp_path / 'evil').exists()


def test_seed_checks_every_file_against_the_manifest(tmp_path):
    good = [('uploads/projects/proj_1/project.json', b'{"a": 1}')]
    tampered = _tar(tmp_path / 't.tar.gz', [
        ('manifest.json', _manifest(good), 'file'),
        ('uploads/projects/proj_1/project.json', b'{"a": 2}', 'file'),
    ])
    with pytest.raises(SeedError, match='does not match the manifest'):
        seed(tmp_path / 'data', str(tampered))
    missing = _tar(tmp_path / 'm.tar.gz', [('manifest.json', _manifest(good), 'file')])
    with pytest.raises(SeedError, match='not in the archive'):
        seed(tmp_path / 'data', str(missing))
    assert not (tmp_path / 'data' / 'exhibits' / 'manifest.json').exists()


def test_seed_without_a_url_does_nothing(tmp_path):
    assert seed(tmp_path / 'data', None) == 'no-url'
    assert seed(tmp_path / 'data', '  ') == 'no-url'
    assert not (tmp_path / 'data').exists()


def test_seed_only_fetches_https(tmp_path):
    with pytest.raises(SeedError, match='must be https'):
        seed(tmp_path / 'data', 'http://example.com/exhibits.tar.gz')
    with pytest.raises(SeedError, match='64 hex'):
        seed(tmp_path / 'data', 'https://example.com/x.tar.gz', 'abc')


def test_public_source_drops_credentials_and_query():
    assert seed_exhibits.public_source('https://user:pw@example.com:8443/a/b.tar.gz?token=x#sha256=1') == (
        'https://example.com:8443/a/b.tar.gz'
    )


def test_seed_main_never_fails_the_boot(tmp_path, capsys):
    code = seed_exhibits.main(['--data-dir', str(tmp_path / 'data'), '--url', str(tmp_path / 'missing.tar.gz')])
    assert code == 0
    assert 'not installed this time' in capsys.readouterr().out
    assert seed_exhibits.main([
        '--data-dir', str(tmp_path / 'data'), '--url', str(tmp_path / 'missing.tar.gz'), '--strict',
    ]) == 1


def test_seed_refuses_a_memory_database_missing_but_journaled(city, archive, tmp_path):
    path, digest = archive
    data = tmp_path / 'data'
    db = data / 'uploads' / 'memory' / 'local_memory.sqlite3'
    db.parent.mkdir(parents=True)
    Path(f'{db}-wal').write_bytes(b'')
    with pytest.raises(SeedError, match='journal files'):
        seed(data, str(path), digest)
    assert not db.exists()
