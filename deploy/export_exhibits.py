#!/usr/bin/env python3
"""
Package finished gatherings as exhibits for the public site.

    python deploy/export_exhibits.py --out DIR [--name exhibits-v1]
        [--uploads backend/uploads] [--memory-db <uploads>/memory/local_memory.sqlite3]
        [--exhibit TITLE=SIMULATION_ID:REPORT_ID ...]

For each exhibit it takes the gathering's project, simulation and report
folders (the scroll, the citizens, the run, the stance ledger, the portraits,
the Chronicle and its film), and ONLY that gathering's graph from the local
memory database, and writes DIR/<name>.tar.gz with a manifest.json inside and
DIR/<name>.tar.gz.sha256 beside it. deploy/seed_exhibits.py installs it.

It never writes to the uploads folder or the live database: the database is
opened read-only (sqlite URI mode=ro), copied with the backup API into a
temporary file, and every other graph is deleted from that copy.

Left out on purpose: the run's own log (simulation.log, which carries the
owner's file paths), the run's IPC folders, and the voices cache.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import io
import json
import os
import re
import sqlite3
import sys
import tarfile
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

FORMAT = 'parthenon-exhibits/1'
REPO = Path(__file__).resolve().parent.parent
DEFAULT_UPLOADS = REPO / 'backend' / 'uploads'
MEMORY_IN_ARCHIVE = 'memory/exhibits.sqlite3'

# The gatherings that ship with the public site (title=simulation:report).
DEFAULT_EXHIBITS = (
    'When Sand Speaks=sim_2c79002f1b0c:report_53d558ea0a3d',
    "Socrates' Apology=sim_909e9d58b157:report_8e64c6bfab2f",
)

ID = re.compile(r'^[A-Za-z0-9_-]{1,80}$')
# Files and folders of a gathering that are not part of the exhibit.
SKIP_NAMES = {'simulation.log', '.DS_Store'}
SKIP_DIRS = {'ipc_commands', 'ipc_responses', '__pycache__'}
# A last look before anything leaves the machine.
SECRET = re.compile(
    rb'(sk-or-v1-[0-9a-f]{20,}|sk-ant-[A-Za-z0-9_-]{20,}|sk-proj-[A-Za-z0-9_-]{20,}|'
    rb'xai-[A-Za-z0-9]{20,}|z_[A-Za-z0-9]{30,}\.[A-Za-z0-9_-]{20,}|Bearer\s+[A-Za-z0-9._-]{30,})'
)
TEXT_SUFFIXES = {'.json', '.jsonl', '.md', '.txt', '.csv', '.vtt', '.log'}


class ExportError(Exception):
    pass


@dataclass
class Exhibit:
    title: str
    project_id: str
    simulation_id: str
    report_id: str
    graph_id: str


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as error:
        raise ExportError(f'cannot read {path}: {error}') from error
    if not isinstance(data, dict):
        raise ExportError(f'{path} is not a JSON object')
    return data


def _id(value: object, what: str) -> str:
    if not isinstance(value, str) or not ID.match(value):
        raise ExportError(f'bad {what}: {value!r}')
    return value


def parse_exhibit(spec: str) -> Tuple[str, str, str]:
    """'Title=sim_x:report_y' -> (title, simulation_id, report_id)."""
    title, sep, ids = spec.rpartition('=')
    simulation_id, colon, report_id = ids.partition(':')
    if not sep or not colon or not title.strip():
        raise ExportError(f'an exhibit is TITLE=SIMULATION_ID:REPORT_ID, not {spec!r}')
    return title.strip(), _id(simulation_id, 'simulation id'), _id(report_id, 'report id')


def resolve_exhibit(uploads: Path, title: str, simulation_id: str, report_id: str) -> Exhibit:
    """Find the project and graph of a finished gathering and check the lineage agrees."""
    state = _read_json(uploads / 'simulations' / simulation_id / 'state.json')
    meta = _read_json(uploads / 'reports' / report_id / 'meta.json')
    project_id = _id(state.get('project_id'), 'project id')
    graph_id = _id(state.get('graph_id'), 'graph id')
    project = _read_json(uploads / 'projects' / project_id / 'project.json')
    if meta.get('simulation_id') != simulation_id:
        raise ExportError(f'{report_id} belongs to {meta.get("simulation_id")}, not {simulation_id}')
    if meta.get('graph_id') not in (None, graph_id) or project.get('graph_id') not in (None, graph_id):
        raise ExportError(f'{title}: the project, simulation and report name different graphs')
    if meta.get('status') != 'completed':
        raise ExportError(f'{report_id} is {meta.get("status")!r}, not completed')
    return Exhibit(title, project_id, simulation_id, report_id, graph_id)


def exhibit_files(uploads: Path, exhibit: Exhibit) -> List[Path]:
    """Every file of the exhibit's three folders, relative to uploads, in a stable order."""
    files: List[Path] = []
    for folder in (
        Path('projects') / exhibit.project_id,
        Path('simulations') / exhibit.simulation_id,
        Path('reports') / exhibit.report_id,
    ):
        root = uploads / folder
        if not root.is_dir():
            raise ExportError(f'missing folder {root}')
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
            for name in sorted(filenames):
                path = Path(dirpath) / name
                if name in SKIP_NAMES or path.is_symlink() or not path.is_file():
                    continue
                files.append(path.relative_to(uploads))
    return files


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _scan_for_secrets(path: Path) -> None:
    if path.suffix.lower() not in TEXT_SUFFIXES and path.suffix.lower() not in {'.db', '.sqlite3'}:
        return
    with open(path, 'rb') as handle:
        data = handle.read()
    if SECRET.search(data):
        raise ExportError(f'{path.name} looks like it holds a key or token; not exporting it')


# --------------------------------------------------------------------------- memory


def copy_memory(live_db: Path, graph_ids: Sequence[str], out_path: Path) -> Dict[str, Dict[str, int]]:
    """Copy the live memory database read-only, keep only `graph_ids`, and compact the copy."""
    if not live_db.is_file():
        raise ExportError(f'no memory database at {live_db}')
    uri = f'{live_db.resolve().as_uri()}?mode=ro'
    if not any(Path(f'{live_db}{suffix}').exists() for suffix in ('-wal', '-shm')):
        # Nothing has it open: a read-only connection to a WAL database would
        # still create -wal and -shm files beside it, so read it as immutable.
        uri += '&immutable=1'
    source = sqlite3.connect(uri, uri=True)
    try:
        target = sqlite3.connect(str(out_path))
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()

    conn = sqlite3.connect(str(out_path), isolation_level=None)
    try:
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute('PRAGMA journal_mode=DELETE')
        keep = list(graph_ids)
        marks = ','.join('?' for _ in keep)
        found = {row[0] for row in conn.execute(f'SELECT graph_id FROM graphs WHERE graph_id IN ({marks})', keep)}
        missing = [g for g in keep if g not in found]
        if missing:
            raise ExportError(f'the memory database has no graph {", ".join(missing)}')
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        conn.execute('BEGIN')
        # The foreign keys cascade from graphs to episodes, nodes, aliases,
        # edges and their episode links; the FTS triggers follow the deletes.
        conn.execute(f'DELETE FROM graphs WHERE graph_id NOT IN ({marks})', keep)
        if 'batch_items' in tables:
            conn.execute(f'DELETE FROM batch_items WHERE graph_id NOT IN ({marks})', keep)
        if 'batches' in tables and 'batch_items' in tables:
            conn.execute('DELETE FROM batches WHERE batch_id NOT IN (SELECT batch_id FROM batch_items)')
        if 'usage' in tables:
            conn.execute(
                f"DELETE FROM usage WHERE NOT (scope_kind = 'graph' AND scope_id IN ({marks}))", keep
            )
        conn.execute('COMMIT')
        problems = conn.execute('PRAGMA foreign_key_check').fetchall()
        if problems:
            raise ExportError(f'the exhibits memory copy has dangling rows: {problems[:5]}')
        for (fts,) in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%\\_fts' ESCAPE '\\'"
        ).fetchall():
            conn.execute(f"INSERT INTO {fts}({fts}) VALUES ('rebuild')")
        if conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ExportError('the exhibits memory copy failed its integrity check')
        conn.execute('VACUUM')
        counts: Dict[str, Dict[str, int]] = {}
        for graph_id in keep:
            counts[graph_id] = {
                table: conn.execute(f'SELECT COUNT(*) FROM {table} WHERE graph_id = ?', (graph_id,)).fetchone()[0]
                for table in ('nodes', 'edges', 'episodes')
            }
            pending = conn.execute(
                "SELECT COUNT(*) FROM episodes WHERE graph_id = ? AND extraction_status IN ('pending', 'queued', 'processing')",
                (graph_id,),
            ).fetchone()[0]
            if pending:
                raise ExportError(f'{graph_id} still has {pending} episode(s) waiting for extraction')
        others = conn.execute(f'SELECT COUNT(*) FROM graphs WHERE graph_id NOT IN ({marks})', keep).fetchone()[0]
        if others:
            raise ExportError('other graphs survived in the exhibits memory copy')
        return counts
    finally:
        conn.close()


# --------------------------------------------------------------------------- archive


def _add_file(tar: tarfile.TarFile, arcname: str, path: Path, mtime: int) -> None:
    info = tarfile.TarInfo(arcname)
    info.size = path.stat().st_size
    info.mtime = mtime
    info.mode = 0o644
    info.uid = info.gid = 0
    info.uname = info.gname = ''
    with open(path, 'rb') as handle:
        tar.addfile(info, handle)


def _add_bytes(tar: tarfile.TarFile, arcname: str, data: bytes, mtime: int) -> None:
    info = tarfile.TarInfo(arcname)
    info.size = len(data)
    info.mtime = mtime
    info.mode = 0o644
    info.uid = info.gid = 0
    info.uname = info.gname = ''
    tar.addfile(info, io.BytesIO(data))


def export(
    uploads: Path,
    memory_db: Path,
    out_dir: Path,
    name: str,
    specs: Iterable[str] = DEFAULT_EXHIBITS,
    *,
    now: Optional[dt.datetime] = None,
) -> Dict[str, object]:
    uploads = uploads.resolve()
    out_dir = out_dir.resolve()
    if out_dir == uploads or uploads in out_dir.parents:
        raise ExportError('the archive must not be written inside the uploads folder')
    if not re.match(r'^[A-Za-z0-9._-]{1,64}$', name):
        raise ExportError(f'bad archive name {name!r}')
    exhibits = [resolve_exhibit(uploads, *parse_exhibit(spec)) for spec in specs]
    if not exhibits:
        raise ExportError('no exhibits')
    now = now or dt.datetime.now(dt.timezone.utc)
    mtime = int(now.timestamp())

    entries: List[Tuple[str, Path]] = []
    for exhibit in exhibits:
        for relative in exhibit_files(uploads, exhibit):
            path = uploads / relative
            _scan_for_secrets(path)
            entries.append((f'uploads/{relative.as_posix()}', path))

    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=out_dir, prefix='.export-') as scratch:
        memory_copy = Path(scratch) / 'exhibits.sqlite3'
        graph_counts = copy_memory(memory_db, [e.graph_id for e in exhibits], memory_copy)
        _scan_for_secrets(memory_copy)

        files = [
            {'path': arcname, 'size': path.stat().st_size, 'sha256': _sha256_file(path)}
            for arcname, path in entries
        ]
        memory_entry = {
            'path': MEMORY_IN_ARCHIVE,
            'size': memory_copy.stat().st_size,
            'sha256': _sha256_file(memory_copy),
            'graphs': graph_counts,
        }
        manifest = {
            'format': FORMAT,
            'name': name,
            'created_at': now.isoformat().replace('+00:00', 'Z'),
            'exhibits': [asdict(e) for e in exhibits],
            'memory': memory_entry,
            'files': files,
            'total_bytes': sum(f['size'] for f in files) + memory_entry['size'],
        }
        manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode('utf-8')

        archive = out_dir / f'{name}.tar.gz'
        partial = out_dir / f'.{name}.tar.gz.partial'
        with tarfile.open(partial, 'w:gz', format=tarfile.PAX_FORMAT, compresslevel=6) as tar:
            _add_bytes(tar, 'manifest.json', manifest_bytes, mtime)
            _add_file(tar, MEMORY_IN_ARCHIVE, memory_copy, mtime)
            for arcname, path in entries:
                _add_file(tar, arcname, path, mtime)
        os.replace(partial, archive)

    digest = _sha256_file(archive)
    (out_dir / f'{name}.tar.gz.sha256').write_text(f'{digest}  {archive.name}\n', encoding='utf-8')
    return {
        'archive': str(archive),
        'sha256': digest,
        'size': archive.stat().st_size,
        'files': len(files) + 1,
        'exhibits': [asdict(e) for e in exhibits],
        'graphs': graph_counts,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description='Package finished gatherings as exhibits for the public site.')
    parser.add_argument('--out', required=True, type=Path, help='folder for <name>.tar.gz and its .sha256')
    parser.add_argument('--name', default='exhibits-v1')
    parser.add_argument('--uploads', type=Path, default=DEFAULT_UPLOADS)
    parser.add_argument('--memory-db', type=Path, default=None,
                        help='default <uploads>/memory/local_memory.sqlite3')
    parser.add_argument('--exhibit', action='append', default=None, metavar='TITLE=SIMULATION_ID:REPORT_ID')
    args = parser.parse_args(argv)
    memory_db = args.memory_db or args.uploads / 'memory' / 'local_memory.sqlite3'
    try:
        result = export(args.uploads, memory_db, args.out, args.name, args.exhibit or DEFAULT_EXHIBITS)
    except ExportError as error:
        print(f'export_exhibits: {error}', file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
