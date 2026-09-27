#!/usr/bin/env python3
"""
Install the exhibits into a data folder on first boot.

    python deploy/seed_exhibits.py [--data-dir /data] [--url URL] [--sha256 HEX]
        [--memory-db PATH]

The archive is the one deploy/export_exhibits.py writes (a tar.gz with a
manifest.json). Defaults come from the environment: PARTHENON_DATA_DIR,
PARTHENON_EXHIBITS_URL (https://, file:// or a local path; a '#sha256=<hex>'
fragment pins the archive), PARTHENON_EXHIBITS_SHA256 and
LOCAL_MEMORY_DB_PATH.

Rules:
- Runs once: <data>/exhibits/manifest.json is the marker. With it present,
  nothing is downloaded.
- Checks the archive's sha256 when one is given, and every file's sha256 and
  size against the manifest; only regular files under manifest.json,
  uploads/ and memory/ are accepted.
- Never overwrites: a file that already exists under <data>/uploads is kept
  as it is. The exhibits' graphs go into the memory database as a new file
  when there is none, else are added to it (graphs it already has are left).
- A failure is reported and leaves no marker, so the next boot tries again;
  it never stops the city from starting (exit status 0 unless --strict).
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import tarfile
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

FORMAT = 'parthenon-exhibits/1'
MARKER = Path('exhibits') / 'manifest.json'
MAX_ARCHIVE_BYTES = 2 * 1024 ** 3
MAX_MEMBERS = 5000
DOWNLOAD_TIMEOUT = 60
HEX64 = re.compile(r'^[0-9a-f]{64}$')
ALLOWED_TOP = ('uploads/', 'memory/')

# Tables copied when the exhibits' graphs join an existing memory database,
# parents first. The integer `id` columns are left for SQLite to assign; the
# rows refer to each other by uuid and graph_id.
MERGE_TABLES: Tuple[Tuple[str, str], ...] = (
    ('graphs', 'graph_id IN ({graphs})'),
    ('episodes', 'graph_id IN ({graphs})'),
    ('nodes', 'graph_id IN ({graphs})'),
    ('node_aliases', 'graph_id IN ({graphs})'),
    ('edges', 'graph_id IN ({graphs})'),
    ('edge_episodes', 'edge_uuid IN (SELECT uuid FROM ex.edges WHERE graph_id IN ({graphs}))'),
    ('node_episodes', 'node_uuid IN (SELECT uuid FROM ex.nodes WHERE graph_id IN ({graphs}))'),
)

Log = Callable[[str], None]


class SeedError(Exception):
    pass


def _log(message: str) -> None:
    print(f'exhibits: {message}', flush=True)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def split_url(url: str, sha256: Optional[str]) -> Tuple[str, Optional[str]]:
    """The URL without a '#sha256=<hex>' fragment, and the expected digest (argument first)."""
    base, _, fragment = url.partition('#')
    expected = (sha256 or '').strip().lower() or None
    if not expected and fragment.startswith('sha256='):
        expected = fragment[len('sha256='):].strip().lower()
    if expected and not HEX64.match(expected):
        raise SeedError('the exhibits sha256 is not 64 hex digits')
    return base.strip(), expected


def public_source(url: str) -> str:
    """The URL as it may be logged and recorded: no query string, no credentials."""
    parts = urllib.parse.urlsplit(url)
    host = parts.hostname or ''
    if parts.port:
        host = f'{host}:{parts.port}'
    return urllib.parse.urlunsplit((parts.scheme, host, parts.path, '', ''))


def download(url: str, target: Path, *, max_bytes: int = MAX_ARCHIVE_BYTES) -> str:
    """Fetch the archive to `target` and return its sha256. https, file:// or a local path."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme in ('', 'file'):
        source = Path(urllib.parse.unquote(parts.path) if parts.scheme == 'file' else url)
        if not source.is_file():
            raise SeedError(f'no archive at {source}')
        if source.stat().st_size > max_bytes:
            raise SeedError('the archive is larger than allowed')
        shutil.copyfile(source, target)
        return _sha256_file(target)
    if parts.scheme != 'https':
        raise SeedError('PARTHENON_EXHIBITS_URL must be https (or a local file)')
    request = urllib.request.Request(url, headers={'User-Agent': 'parthenon-seed/1'})
    digest = hashlib.sha256()
    total = 0
    with urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT) as response, open(target, 'wb') as out:
        if getattr(response, 'status', 200) != 200:
            raise SeedError(f'the archive answered HTTP {response.status}')
        length = response.headers.get('Content-Length')
        if length and length.isdigit() and int(length) > max_bytes:
            raise SeedError('the archive is larger than allowed')
        for chunk in iter(lambda: response.read(1024 * 1024), b''):
            total += len(chunk)
            if total > max_bytes:
                raise SeedError('the archive is larger than allowed')
            digest.update(chunk)
            out.write(chunk)
    return digest.hexdigest()


def _safe_name(name: str) -> bool:
    if not name or name.startswith('/') or '\\' in name or '\x00' in name:
        return False
    parts = name.split('/')
    return all(part not in ('', '.', '..') for part in parts)


def extract(archive: Path, into: Path) -> dict:
    """Unpack only manifest.json and regular files under uploads/ and memory/; return the manifest."""
    into.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, 'r:gz') as tar:
        members = []
        total = 0
        for count, member in enumerate(tar, start=1):
            if count > MAX_MEMBERS:
                raise SeedError('the archive has too many entries')
            name = member.name[2:] if member.name.startswith('./') else member.name
            if member.isdir():
                continue
            if not member.isreg():
                raise SeedError(f'the archive holds a link or device: {member.name!r}')
            if not _safe_name(name) or not (name == 'manifest.json' or name.startswith(ALLOWED_TOP)):
                raise SeedError(f'unexpected path in the archive: {member.name!r}')
            total += member.size
            if total > MAX_ARCHIVE_BYTES * 2:
                raise SeedError('the archive unpacks larger than allowed')
            member.name = name
            members.append(member)
        tar.extractall(into, members=members, filter='data')
    manifest_path = into / 'manifest.json'
    if not manifest_path.is_file():
        raise SeedError('the archive has no manifest.json')
    try:
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    except ValueError as error:
        raise SeedError(f'the manifest is not JSON: {error}') from error
    if not isinstance(manifest, dict) or manifest.get('format') != FORMAT:
        raise SeedError(f'the manifest is not {FORMAT}')
    return manifest


def verify(manifest: dict, root: Path) -> Tuple[List[str], Optional[str]]:
    """Check each listed file's size and sha256; return the uploads files and the memory file."""
    uploads: List[str] = []
    listed = list(manifest.get('files') or [])
    memory = manifest.get('memory') or None
    if memory:
        listed.append(memory)
    for entry in listed:
        path = entry.get('path') if isinstance(entry, dict) else None
        if not isinstance(path, str) or not _safe_name(path) or not path.startswith(ALLOWED_TOP):
            raise SeedError(f'bad manifest entry {entry!r}')
        local = root / path
        if not local.is_file():
            raise SeedError(f'{path} is in the manifest but not in the archive')
        if local.stat().st_size != entry.get('size') or _sha256_file(local) != entry.get('sha256'):
            raise SeedError(f'{path} does not match the manifest')
        if path.startswith('uploads/'):
            uploads.append(path)
    memory_path = memory.get('path') if memory else None
    return uploads, memory_path


def install_files(root: Path, paths: List[str], data_dir: Path) -> Tuple[int, int]:
    """Move each uploads file into place unless one is already there. Returns (installed, kept)."""
    installed = kept = 0
    for path in paths:
        source = root / path
        target = data_dir / path
        if os.path.lexists(target):
            kept += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(source, target)
        installed += 1
    return installed, kept


def _columns(conn: sqlite3.Connection, schema: str, table: str) -> List[str]:
    return [row[1] for row in conn.execute(f'PRAGMA {schema}.table_info({table})')]


def merge_memory(target: Path, source: Path, graph_ids: List[str]) -> List[str]:
    """Add the exhibits' graphs that `target` lacks, from `source`. Returns the graphs added."""
    # Opened as a URI so the ATTACH below may name the exhibits copy read-only.
    conn = sqlite3.connect(target.resolve().as_uri(), uri=True, isolation_level=None)
    try:
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute('PRAGMA busy_timeout=10000')
        conn.execute('ATTACH DATABASE ? AS ex', (f'{source.resolve().as_uri()}?mode=ro',))
        marks = ','.join('?' for _ in graph_ids)
        present = {
            row[0] for row in conn.execute(f'SELECT graph_id FROM main.graphs WHERE graph_id IN ({marks})', graph_ids)
        }
        todo = [g for g in graph_ids if g not in present]
        if not todo:
            return []
        todo_marks = ','.join('?' for _ in todo)
        conn.execute('BEGIN IMMEDIATE')
        try:
            for table, where in MERGE_TABLES:
                main_cols = _columns(conn, 'main', table)
                ex_cols = set(_columns(conn, 'ex', table))
                cols = [c for c in main_cols if c in ex_cols and c != 'id']
                if not cols:
                    raise SeedError(f'the memory table {table} does not line up')
                names = ', '.join(cols)
                params = todo * where.count('{graphs}')
                conn.execute(
                    f'INSERT INTO main.{table} ({names}) SELECT {names} FROM ex.{table} '
                    f'WHERE {where.format(graphs=todo_marks)}',
                    params,
                )
            problems = conn.execute('PRAGMA main.foreign_key_check').fetchall()
            if problems:
                raise SeedError(f'the merged memory has dangling rows: {problems[:3]}')
            conn.execute('COMMIT')
        except BaseException:
            conn.execute('ROLLBACK')
            raise
        return todo
    except sqlite3.Error as error:
        raise SeedError(f'could not add the exhibits to the memory database: {error}') from error
    finally:
        conn.close()


def install_memory(root: Path, memory_path: Optional[str], graph_ids: List[str], db_path: Path) -> str:
    if not memory_path:
        return 'none'
    source = root / memory_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(db_path.parent, 0o700)
    except OSError:
        pass
    leftovers = [Path(f'{db_path}{suffix}') for suffix in ('-wal', '-shm', '-journal')]
    if not db_path.exists() and not any(p.exists() for p in leftovers):
        os.replace(source, db_path)
        os.chmod(db_path, 0o600)
        return 'installed'
    if not db_path.exists():
        raise SeedError(f'{db_path.name} is missing but its journal files are there; not touching it')
    added = merge_memory(db_path, source, graph_ids)
    return f'merged {len(added)}' if added else 'present'


def seed(
    data_dir: Path,
    url: Optional[str],
    sha256: Optional[str] = None,
    *,
    memory_db: Optional[Path] = None,
    log: Log = _log,
) -> str:
    """Install the exhibits once. Returns 'present', 'no-url' or 'installed'; raises SeedError."""
    data_dir = Path(data_dir)
    marker = data_dir / MARKER
    if marker.exists():
        return 'present'
    if not url or not url.strip():
        return 'no-url'
    url, expected = split_url(url, sha256)
    memory_db = Path(memory_db) if memory_db else data_dir / 'uploads' / 'memory' / 'local_memory.sqlite3'
    exhibits_dir = marker.parent
    exhibits_dir.mkdir(parents=True, exist_ok=True)
    staging = exhibits_dir / f'.staging-{os.getpid()}'
    shutil.rmtree(staging, ignore_errors=True)
    for old in exhibits_dir.glob('.staging-*'):
        shutil.rmtree(old, ignore_errors=True)
    staging.mkdir()
    try:
        archive = staging / 'exhibits.tar.gz'
        log(f'fetching {public_source(url)}')
        digest = download(url, archive)
        if expected and digest != expected:
            raise SeedError('the archive does not match its sha256')
        if not expected:
            log('no sha256 given; checking the files against the manifest only')
        root = staging / 'unpacked'
        manifest = extract(archive, root)
        archive.unlink()
        upload_paths, memory_path = verify(manifest, root)
        graph_ids = [e['graph_id'] for e in manifest.get('exhibits') or [] if isinstance(e, dict) and e.get('graph_id')]
        installed, kept = install_files(root, upload_paths, data_dir)
        memory_state = install_memory(root, memory_path, graph_ids, memory_db)
        record = {
            key: manifest.get(key) for key in ('format', 'name', 'created_at', 'exhibits')
        }
        record.update({
            'installed_at': dt.datetime.now(dt.timezone.utc).isoformat().replace('+00:00', 'Z'),
            'source': public_source(url),
            'archive_sha256': digest,
            'files_installed': installed,
            'files_kept': kept,
            'memory': memory_state,
        })
        partial = exhibits_dir / '.manifest.json.partial'
        partial.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(partial, marker)
        titles = ', '.join(e.get('title', '?') for e in manifest.get('exhibits') or [])
        log(f'installed {titles}: {installed} files new, {kept} kept, memory {memory_state}')
        return 'installed'
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description='Install the exhibits into a data folder once.')
    parser.add_argument('--data-dir', type=Path, default=Path(os.environ.get('PARTHENON_DATA_DIR') or '/data'))
    parser.add_argument('--url', default=os.environ.get('PARTHENON_EXHIBITS_URL'))
    parser.add_argument('--sha256', default=os.environ.get('PARTHENON_EXHIBITS_SHA256'))
    parser.add_argument('--memory-db', type=Path, default=os.environ.get('LOCAL_MEMORY_DB_PATH') or None)
    parser.add_argument('--strict', action='store_true', help='exit 1 when the exhibits could not be installed')
    args = parser.parse_args(argv)
    try:
        result = seed(args.data_dir, args.url, args.sha256, memory_db=args.memory_db)
    except (SeedError, OSError, tarfile.TarError, sqlite3.Error) as error:
        _log(f'not installed this time: {error}')
        return 1 if args.strict else 0
    if result == 'present':
        _log('already installed')
    elif result == 'no-url':
        _log('PARTHENON_EXHIBITS_URL is not set; the shelf starts empty')
    return 0


if __name__ == '__main__':
    sys.exit(main())
