"""SQLite storage for the local memory backend.

One database file holds every graph (spec §3). ``MemoryStore`` owns a small
connection pool, applies the pragmas on every connection, serializes writes
with a process-wide lock plus ``BEGIN IMMEDIATE``, detects FTS5/trigram
support and runs schema migrations at open.

Usage::

    store = MemoryStore("/path/local_memory.sqlite3")
    with store.write() as conn:          # one IMMEDIATE transaction
        conn.execute("INSERT ...")
    with store.read() as conn:           # pooled connection, WAL snapshot per statement
        rows = conn.execute("SELECT ...").fetchall()
    with store.read(snapshot=True) as conn:  # several statements, one snapshot
        ...

Never make an LLM call (or any other slow I/O) while holding ``write()``.
"""

from __future__ import annotations

import logging
import os
import queue
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable, Iterator, Mapping, Sequence, Union

from .errors import is_busy_sqlite_error, map_sqlite_error, store_busy
from .textnorm import utcnow_iso

logger = logging.getLogger("mirofish.memory.store")

__all__ = [
    "FTS_TABLES",
    "MIGRATIONS",
    "SCHEMA_V1",
    "SCHEMA_VERSION",
    "ConnectionPool",
    "MemoryStore",
    "StoreCaps",
    "TOKENIZER_NONE",
    "TOKENIZER_TRIGRAM",
    "TOKENIZER_UNICODE61",
    "detect_caps",
    "drop_fts_statements",
    "fts_statements",
    "new_id",
    "utcnow_iso",
]

DEFAULT_POOL_SIZE = 8
DEFAULT_BUSY_TIMEOUT_MS = 10000
CONNECT_TIMEOUT_SECONDS = 30.0
POOL_ACQUIRE_TIMEOUT_SECONDS = 30.0
DIRECTORY_MODE = 0o700
FILE_MODE = 0o600

TOKENIZER_TRIGRAM = "trigram"
TOKENIZER_UNICODE61 = "unicode61 remove_diacritics 2"
TOKENIZER_NONE = "none"


def new_id() -> str:
    """Random UUID4 string used for nodes, edges, episodes, batches and items."""

    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

SCHEMA_VERSION = 1

# Statements are kept as a list (not one script) because executescript()
# commits implicitly, which would break the migration transaction.
SCHEMA_V1: tuple[str, ...] = (
    "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    """
    CREATE TABLE IF NOT EXISTS graphs (
      graph_id            TEXT PRIMARY KEY,
      uuid                TEXT NOT NULL UNIQUE,
      name                TEXT,
      description         TEXT,
      time_zone           TEXT,
      created_at          TEXT NOT NULL,
      ontology_json       TEXT,
      ontology_updated_at TEXT,
      version             INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS default_ontology (
      id            INTEGER PRIMARY KEY CHECK (id = 1),
      ontology_json TEXT NOT NULL,
      updated_at    TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS episodes (
      id                      INTEGER PRIMARY KEY,
      uuid                    TEXT NOT NULL UNIQUE,
      graph_id                TEXT NOT NULL REFERENCES graphs(graph_id) ON DELETE CASCADE,
      kind                    TEXT NOT NULL CHECK (kind IN ('document','activity')),
      content                 TEXT NOT NULL,
      source                  TEXT NOT NULL,
      source_description      TEXT NOT NULL DEFAULT '',
      metadata_json           TEXT NOT NULL DEFAULT '{}',
      simulation_id           TEXT,
      strict_ontology         INTEGER NOT NULL DEFAULT 0,
      reference_time          TEXT NOT NULL,
      reference_time_explicit INTEGER NOT NULL DEFAULT 0,
      created_at              TEXT NOT NULL,
      queued_at               TEXT,
      processed               INTEGER NOT NULL DEFAULT 0,
      extraction_status       TEXT NOT NULL DEFAULT 'pending',
      extraction_error        TEXT,
      attempts                INTEGER NOT NULL DEFAULT 0,
      lease_owner             TEXT,
      lease_until             REAL,
      batch_id                TEXT,
      sequence_index          INTEGER
    )
    """,
    "CREATE INDEX IF NOT EXISTS episodes_graph_created ON episodes(graph_id, created_at)",
    "CREATE INDEX IF NOT EXISTS episodes_work ON episodes(kind, extraction_status, queued_at)",
    "CREATE INDEX IF NOT EXISTS episodes_batch ON episodes(batch_id, sequence_index)",
    """
    CREATE TABLE IF NOT EXISTS nodes (
      id              INTEGER PRIMARY KEY,
      uuid            TEXT NOT NULL UNIQUE,
      graph_id        TEXT NOT NULL REFERENCES graphs(graph_id) ON DELETE CASCADE,
      name            TEXT NOT NULL,
      name_key        TEXT NOT NULL,
      entity_type     TEXT,
      labels_json     TEXT NOT NULL,
      summary         TEXT NOT NULL DEFAULT '',
      attributes_json TEXT NOT NULL DEFAULT '{}',
      aliases_text    TEXT NOT NULL DEFAULT '',
      attributes_text TEXT NOT NULL DEFAULT '',
      origin          TEXT NOT NULL DEFAULT 'llm',
      mention_count   INTEGER NOT NULL DEFAULT 1,
      created_at      TEXT NOT NULL,
      updated_at      TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS nodes_graph_key ON nodes(graph_id, name_key)",
    """
    CREATE TABLE IF NOT EXISTS node_aliases (
      graph_id  TEXT NOT NULL REFERENCES graphs(graph_id) ON DELETE CASCADE,
      alias_key TEXT NOT NULL,
      node_uuid TEXT NOT NULL REFERENCES nodes(uuid) ON DELETE CASCADE,
      PRIMARY KEY (graph_id, alias_key, node_uuid)
    )
    """,
    # Child-key index so node deletes do not scan every alias.
    "CREATE INDEX IF NOT EXISTS node_aliases_node ON node_aliases(node_uuid)",
    """
    CREATE TABLE IF NOT EXISTS edges (
      id               INTEGER PRIMARY KEY,
      uuid             TEXT NOT NULL UNIQUE,
      graph_id         TEXT NOT NULL REFERENCES graphs(graph_id) ON DELETE CASCADE,
      name             TEXT NOT NULL,
      fact             TEXT NOT NULL,
      fact_key         TEXT NOT NULL,
      source_node_uuid TEXT NOT NULL REFERENCES nodes(uuid) ON DELETE CASCADE,
      target_node_uuid TEXT NOT NULL REFERENCES nodes(uuid) ON DELETE CASCADE,
      attributes_json  TEXT NOT NULL DEFAULT '{}',
      origin           TEXT NOT NULL DEFAULT 'llm',
      created_at       TEXT NOT NULL,
      valid_at         TEXT,
      invalid_at       TEXT,
      expired_at       TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS edges_src ON edges(graph_id, source_node_uuid)",
    "CREATE INDEX IF NOT EXISTS edges_tgt ON edges(graph_id, target_node_uuid)",
    "CREATE INDEX IF NOT EXISTS edges_name ON edges(graph_id, name)",
    # Child-key indexes: FK cascades from nodes and the global node.get_edges
    # lookup search by node uuid alone.
    "CREATE INDEX IF NOT EXISTS edges_src_node ON edges(source_node_uuid)",
    "CREATE INDEX IF NOT EXISTS edges_tgt_node ON edges(target_node_uuid)",
    """
    CREATE TABLE IF NOT EXISTS edge_episodes (
      edge_uuid    TEXT NOT NULL REFERENCES edges(uuid) ON DELETE CASCADE,
      episode_uuid TEXT NOT NULL REFERENCES episodes(uuid) ON DELETE CASCADE,
      linked_at    TEXT NOT NULL,
      PRIMARY KEY (edge_uuid, episode_uuid)
    )
    """,
    "CREATE INDEX IF NOT EXISTS edge_episodes_episode ON edge_episodes(episode_uuid)",
    """
    CREATE TABLE IF NOT EXISTS node_episodes (
      node_uuid    TEXT NOT NULL REFERENCES nodes(uuid) ON DELETE CASCADE,
      episode_uuid TEXT NOT NULL REFERENCES episodes(uuid) ON DELETE CASCADE,
      PRIMARY KEY (node_uuid, episode_uuid)
    )
    """,
    "CREATE INDEX IF NOT EXISTS node_episodes_episode ON node_episodes(episode_uuid)",
    """
    CREATE TABLE IF NOT EXISTS batches (
      id                INTEGER PRIMARY KEY,
      batch_id          TEXT NOT NULL UNIQUE,
      status            TEXT NOT NULL,
      metadata_json     TEXT NOT NULL DEFAULT '{}',
      ignore_roles_json TEXT,
      item_count        INTEGER NOT NULL DEFAULT 0,
      error_json        TEXT,
      post_pass_done    INTEGER NOT NULL DEFAULT 0,
      finalize_owner    TEXT,
      finalize_until    REAL,
      created_at        TEXT NOT NULL,
      updated_at        TEXT NOT NULL,
      processed_at      TEXT,
      completed_at      TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS batch_items (
      id             INTEGER PRIMARY KEY,
      item_id        TEXT NOT NULL UNIQUE,
      batch_id       TEXT NOT NULL REFERENCES batches(batch_id) ON DELETE CASCADE,
      sequence_index INTEGER NOT NULL,
      graph_id       TEXT NOT NULL,
      episode_uuid   TEXT NOT NULL,
      status         TEXT NOT NULL,
      error_json     TEXT,
      created_at     TEXT NOT NULL,
      updated_at     TEXT NOT NULL,
      UNIQUE (batch_id, sequence_index)
    )
    """,
    # graph.delete cancels a graph's active items; commits update items by episode.
    "CREATE INDEX IF NOT EXISTS batch_items_graph ON batch_items(graph_id, status)",
    "CREATE INDEX IF NOT EXISTS batch_items_episode ON batch_items(episode_uuid)",
    """
    CREATE TABLE IF NOT EXISTS usage (
      scope_kind   TEXT NOT NULL,
      scope_id     TEXT NOT NULL,
      llm_calls    INTEGER NOT NULL DEFAULT 0,
      llm_failures INTEGER NOT NULL DEFAULT 0,
      prompt_chars INTEGER NOT NULL DEFAULT 0,
      output_chars INTEGER NOT NULL DEFAULT 0,
      updated_at   TEXT NOT NULL,
      PRIMARY KEY (scope_kind, scope_id)
    )
    """,
)


@dataclass(frozen=True)
class FtsTable:
    """An external-content FTS5 index over one base table."""

    table: str
    fts: str
    columns: tuple[str, ...]
    # Columns whose UPDATE re-indexes the row (content is immutable for episodes).
    update_columns: tuple[str, ...]


FTS_TABLES: tuple[FtsTable, ...] = (
    FtsTable("edges", "edges_fts", ("name", "fact"), ("name", "fact")),
    FtsTable(
        "nodes",
        "nodes_fts",
        ("name", "aliases_text", "summary", "attributes_text"),
        ("name", "aliases_text", "summary", "attributes_text"),
    ),
    FtsTable("episodes", "episodes_fts", ("content", "source_description"), ("source_description",)),
)


def fts_statements(tokenizer: str) -> list[str]:
    """DDL for the FTS5 tables and their sync triggers (idempotent)."""

    if tokenizer == TOKENIZER_NONE:
        return []
    statements: list[str] = []
    for spec in FTS_TABLES:
        cols = ", ".join(spec.columns)
        new_vals = ", ".join(f"new.{c}" for c in spec.columns)
        old_vals = ", ".join(f"old.{c}" for c in spec.columns)
        statements.append(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS {spec.fts} USING fts5("
            f"{cols}, content='{spec.table}', content_rowid='id', tokenize='{tokenizer}')"
        )
        statements.append(
            f"CREATE TRIGGER IF NOT EXISTS {spec.table}_ai AFTER INSERT ON {spec.table} BEGIN "
            f"INSERT INTO {spec.fts}(rowid, {cols}) VALUES (new.id, {new_vals}); END"
        )
        statements.append(
            f"CREATE TRIGGER IF NOT EXISTS {spec.table}_ad AFTER DELETE ON {spec.table} BEGIN "
            f"INSERT INTO {spec.fts}({spec.fts}, rowid, {cols}) VALUES ('delete', old.id, {old_vals}); END"
        )
        statements.append(
            f"CREATE TRIGGER IF NOT EXISTS {spec.table}_au AFTER UPDATE OF "
            f"{', '.join(spec.update_columns)} ON {spec.table} BEGIN "
            f"INSERT INTO {spec.fts}({spec.fts}, rowid, {cols}) VALUES ('delete', old.id, {old_vals}); "
            f"INSERT INTO {spec.fts}(rowid, {cols}) VALUES (new.id, {new_vals}); END"
        )
    return statements


def drop_fts_statements() -> list[str]:
    """DDL that removes the FTS triggers first, then the FTS tables."""

    statements: list[str] = []
    for spec in FTS_TABLES:
        for suffix in ("ai", "ad", "au"):
            statements.append(f"DROP TRIGGER IF EXISTS {spec.table}_{suffix}")
    for spec in FTS_TABLES:
        statements.append(f"DROP TABLE IF EXISTS {spec.fts}")
    return statements


# ---------------------------------------------------------------------------
# Capabilities
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StoreCaps:
    """What the linked SQLite supports. Search and schema adapt to this."""

    fts5: bool
    trigram: bool

    @property
    def tokenizer(self) -> str:
        if not self.fts5:
            return TOKENIZER_NONE
        return TOKENIZER_TRIGRAM if self.trigram else TOKENIZER_UNICODE61


def _probe(conn: sqlite3.Connection, name: str, module_args: str) -> bool:
    """Try to create (then drop) a temp FTS5 table; True when it works."""

    try:
        conn.execute(f"CREATE VIRTUAL TABLE temp.{name} USING fts5({module_args})")
    except sqlite3.Error:
        return False
    try:
        conn.execute(f"DROP TABLE IF EXISTS temp.{name}")
    except sqlite3.Error:
        pass
    return True


def detect_caps(conn: sqlite3.Connection) -> StoreCaps:
    """Probe FTS5 and the trigram tokenizer on ``conn`` (uses temp tables)."""

    fts5 = _probe(conn, "__memory_caps_fts5", "a")
    trigram = (
        fts5
        and sqlite3.sqlite_version_info >= (3, 34, 0)
        and _probe(conn, "__memory_caps_trigram", "a, tokenize='trigram'")
    )
    return StoreCaps(fts5=fts5, trigram=bool(trigram))


# ---------------------------------------------------------------------------
# Migrations
# ---------------------------------------------------------------------------

Migration = Union[Sequence[str], Callable[[sqlite3.Connection, StoreCaps], None]]


def _migrate_v1(conn: sqlite3.Connection, caps: StoreCaps) -> None:
    for statement in SCHEMA_V1:
        conn.execute(statement)
    for statement in fts_statements(caps.tokenizer):
        conn.execute(statement)
    _meta_set(conn, "fts_tokenizer", caps.tokenizer)


# Version -> step. Steps must be idempotent. A future schema change adds MIGRATIONS[2].
MIGRATIONS: dict[int, Migration] = {1: _migrate_v1}


def _meta_get(conn: sqlite3.Connection, key: str) -> str | None:
    try:
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    except sqlite3.OperationalError as error:
        if "no such table" in str(error).lower():
            return None
        raise
    return None if row is None else row[0]


def _meta_set(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


# ---------------------------------------------------------------------------
# Connection pool
# ---------------------------------------------------------------------------


class ConnectionPool:
    """Hands out at most ``size`` connections, one thread at a time each."""

    def __init__(self, factory: Callable[[], sqlite3.Connection], size: int = DEFAULT_POOL_SIZE,
                 acquire_timeout: float = POOL_ACQUIRE_TIMEOUT_SECONDS) -> None:
        if size < 1:
            raise ValueError("pool size must be at least 1")
        self._factory = factory
        self._size = size
        self._acquire_timeout = acquire_timeout
        self._idle: "queue.LifoQueue[sqlite3.Connection]" = queue.LifoQueue()
        self._created = 0
        self._lock = threading.Lock()
        self._closed = False

    @property
    def size(self) -> int:
        return self._size

    @property
    def closed(self) -> bool:
        return self._closed

    def acquire(self) -> sqlite3.Connection:
        if self._closed:
            raise RuntimeError("local memory store is closed")
        try:
            return self._idle.get_nowait()
        except queue.Empty:
            pass
        create = False
        with self._lock:
            if self._created < self._size:
                self._created += 1
                create = True
        if create:
            try:
                return self._factory()
            except BaseException:
                with self._lock:
                    self._created -= 1
                raise
        try:
            return self._idle.get(timeout=self._acquire_timeout)
        except queue.Empty:
            logger.warning("Local memory connection pool exhausted after %.0fs", self._acquire_timeout)
            raise store_busy() from None

    def release(self, conn: sqlite3.Connection) -> None:
        if self._closed:
            _close_quietly(conn)
            with self._lock:
                self._created -= 1
            return
        self._idle.put(conn)

    def close(self) -> None:
        """Close idle connections now; checked-out ones close on release."""

        self._closed = True
        while True:
            try:
                conn = self._idle.get_nowait()
            except queue.Empty:
                break
            _close_quietly(conn)
            with self._lock:
                self._created -= 1


def _close_quietly(conn: sqlite3.Connection) -> None:
    try:
        conn.close()
    except sqlite3.Error:
        pass


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

_WRITE_LOCKS: dict[str, "threading.RLock"] = {}
_WRITE_LOCKS_GUARD = threading.Lock()


def _write_lock_for(path: str) -> "threading.RLock":
    """Process-wide write lock, one per database file.

    Every ``MemoryStore`` on the same file in this process shares it, so
    in-process writers queue on the lock instead of spinning on SQLite's busy
    handler. Other processes are serialized by ``BEGIN IMMEDIATE``.
    """

    key = os.path.normcase(os.path.realpath(path))
    with _WRITE_LOCKS_GUARD:
        lock = _WRITE_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _WRITE_LOCKS[key] = lock
        return lock


class MemoryStore:
    """Pooled, migrated SQLite database for the local memory backend."""

    def __init__(
        self,
        path: Union[str, "os.PathLike[str]"],
        *,
        pool_size: int = DEFAULT_POOL_SIZE,
        busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS,
        caps: StoreCaps | None = None,
        acquire_timeout: float = POOL_ACQUIRE_TIMEOUT_SECONDS,
    ) -> None:
        raw_path = os.fspath(path)
        if not raw_path or raw_path == ":memory:" or raw_path.startswith("file:"):
            raise ValueError("MemoryStore needs a file path (in-memory databases are not pooled)")
        self.path = os.path.abspath(raw_path)
        self.busy_timeout_ms = int(busy_timeout_ms)
        self._local = threading.local()
        self._closed = False
        self._prepare_files()
        self._write_lock = _write_lock_for(self.path)
        self._pool = ConnectionPool(self._open_connection, pool_size, acquire_timeout)
        self.caps: StoreCaps = caps or StoreCaps(fts5=False, trigram=False)
        self.project_uuid: str = ""
        self.created_at: str = ""
        try:
            self._bootstrap()
            if caps is None:
                with self.read() as conn:
                    self.caps = detect_caps(conn)
            self.migrate()
        except BaseException:
            self.close()
            raise

    # -- files and connections ------------------------------------------------

    def _prepare_files(self) -> None:
        directory = os.path.dirname(self.path)
        if directory and not os.path.isdir(directory):
            os.makedirs(directory, mode=DIRECTORY_MODE, exist_ok=True)
            try:
                os.chmod(directory, DIRECTORY_MODE)
            except OSError:
                logger.debug("Could not set permissions on %s", directory)
        if not os.path.exists(self.path):
            fd = os.open(self.path, os.O_CREAT | os.O_RDWR, FILE_MODE)
            os.close(fd)
            try:
                os.chmod(self.path, FILE_MODE)
            except OSError:
                logger.debug("Could not set permissions on %s", self.path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            self.path,
            timeout=CONNECT_TIMEOUT_SECONDS,
            isolation_level=None,
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        return conn

    def _open_connection(self) -> sqlite3.Connection:
        conn = self._connect()
        try:
            conn.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA temp_store=MEMORY")
        except sqlite3.OperationalError as error:
            _close_quietly(conn)
            mapped = map_sqlite_error(error)
            if mapped is error:
                raise
            raise mapped from error
        except BaseException:
            _close_quietly(conn)
            raise
        return conn

    def _bootstrap(self) -> None:
        """Enable incremental auto-vacuum on a brand-new file, then switch to WAL."""

        conn = self._connect()
        try:
            conn.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")
            empty = conn.execute("SELECT count(*) FROM sqlite_master").fetchone()[0] == 0
            if empty:
                # Must happen before the first table exists.
                conn.execute("PRAGMA auto_vacuum=INCREMENTAL")
            conn.execute("PRAGMA journal_mode=WAL")
        except sqlite3.OperationalError as error:
            mapped = map_sqlite_error(error)
            if mapped is error:
                raise
            raise mapped from error
        finally:
            _close_quietly(conn)

    def _acquire(self) -> sqlite3.Connection:
        if self._closed:
            raise RuntimeError("local memory store is closed")
        return self._pool.acquire()

    def _release(self, conn: sqlite3.Connection) -> None:
        if conn.in_transaction:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
        self._pool.release(conn)

    # -- transactions -----------------------------------------------------------

    @property
    def in_write(self) -> bool:
        """True while the calling thread is inside ``write()``."""

        return getattr(self._local, "write_depth", 0) > 0

    @contextmanager
    def write(self) -> Iterator[sqlite3.Connection]:
        """One ``BEGIN IMMEDIATE`` transaction under the process-wide write lock.

        Commits on success and rolls back on any exception. A nested
        ``write()`` in the same thread joins the outer transaction through a
        SAVEPOINT, so ``BEGIN`` is never issued twice and a failing inner
        block undoes only its own changes. Busy/locked/I-O SQLite errors are
        raised as the SDK's retryable 503 ``ApiError``.
        """

        depth = getattr(self._local, "write_depth", 0)
        if depth:
            conn: sqlite3.Connection = self._local.write_conn
            savepoint = f"memory_sp_{depth}"
            conn.execute(f"SAVEPOINT {savepoint}")
            self._local.write_depth = depth + 1
            try:
                yield conn
            except BaseException as error:
                try:
                    conn.execute(f"ROLLBACK TO {savepoint}")
                    conn.execute(f"RELEASE {savepoint}")
                except sqlite3.Error:
                    pass
                self._raise_mapped(error)
            else:
                conn.execute(f"RELEASE {savepoint}")
            finally:
                self._local.write_depth = depth
            return

        with self._write_lock:
            conn = self._acquire()
            try:
                try:
                    conn.execute("BEGIN IMMEDIATE")
                except sqlite3.OperationalError as error:
                    self._raise_mapped(error)
                self._local.write_conn = conn
                self._local.write_depth = 1
                try:
                    yield conn
                except BaseException as error:
                    try:
                        conn.execute("ROLLBACK")
                    except sqlite3.Error:
                        pass
                    self._raise_mapped(error)
                else:
                    if not conn.in_transaction:
                        # SQLite rolled the whole transaction back on its own
                        # (or the body ended it); later statements ran in
                        # autocommit mode, so do not report success.
                        raise sqlite3.OperationalError("write transaction ended before commit")
                    try:
                        conn.execute("COMMIT")
                    except sqlite3.OperationalError as error:
                        try:
                            conn.execute("ROLLBACK")
                        except sqlite3.Error:
                            pass
                        self._raise_mapped(error)
                finally:
                    self._local.write_depth = 0
                    self._local.write_conn = None
            finally:
                self._release(conn)

    @contextmanager
    def read(self, *, snapshot: bool = False) -> Iterator[sqlite3.Connection]:
        """A pooled connection for reads.

        Under WAL every statement sees a consistent snapshot. Pass
        ``snapshot=True`` to wrap several statements in one read transaction.
        Inside ``write()`` (same thread) this yields the write connection, so
        uncommitted changes are visible. A nested ``read()`` reuses the
        thread's current read connection.
        """

        if getattr(self._local, "write_depth", 0):
            yield self._local.write_conn
            return
        depth = getattr(self._local, "read_depth", 0)
        if depth:
            self._local.read_depth = depth + 1
            try:
                yield self._local.read_conn
            finally:
                self._local.read_depth = depth
            return

        conn = self._acquire()
        self._local.read_conn = conn
        self._local.read_depth = 1
        try:
            if snapshot:
                conn.execute("BEGIN")
            try:
                yield conn
            except BaseException as error:
                self._raise_mapped(error)
            else:
                if conn.in_transaction:
                    conn.execute("COMMIT")
        finally:
            self._local.read_depth = 0
            self._local.read_conn = None
            self._release(conn)

    @staticmethod
    def _raise_mapped(error: BaseException) -> None:
        if isinstance(error, sqlite3.OperationalError) and is_busy_sqlite_error(error):
            logger.warning("Local memory store busy: %s", type(error).__name__)
            raise store_busy() from error
        raise error

    # -- migrations ---------------------------------------------------------------

    def schema_version(self) -> int:
        with self.read() as conn:
            value = _meta_get(conn, "schema_version")
        return int(value) if value else 0

    def migrate(self) -> None:
        """Apply pending migrations and sync the FTS tokenizer, under the write lock."""

        with self.write() as conn:
            current = int(_meta_get(conn, "schema_version") or 0)
            for version in sorted(MIGRATIONS):
                if version <= current:
                    continue
                step = MIGRATIONS[version]
                if callable(step):
                    step(conn, self.caps)
                else:
                    for statement in step:
                        conn.execute(statement)
                _meta_set(conn, "schema_version", str(version))
                logger.info("Local memory schema migrated to version %s", version)
                current = version
            conn.execute(
                "INSERT OR IGNORE INTO meta(key, value) VALUES ('project_uuid', ?)", (new_id(),)
            )
            conn.execute(
                "INSERT OR IGNORE INTO meta(key, value) VALUES ('created_at', ?)", (utcnow_iso(),)
            )
            self._sync_fts(conn)
            self.project_uuid = _meta_get(conn, "project_uuid") or ""
            self.created_at = _meta_get(conn, "created_at") or ""

    def _sync_fts(self, conn: sqlite3.Connection) -> None:
        wanted = self.caps.tokenizer
        stored = _meta_get(conn, "fts_tokenizer")
        if stored == wanted:
            for statement in fts_statements(wanted):
                conn.execute(statement)
            return
        logger.info("Rebuilding local memory FTS indexes (%s -> %s)", stored, wanted)
        for statement in drop_fts_statements():
            try:
                conn.execute(statement)
            except sqlite3.OperationalError as error:
                # Dropping an fts5 table needs the fts5 module. Without it the
                # triggers are already gone, so base-table writes still work.
                logger.warning("Could not drop an FTS table: %s", error)
        for statement in fts_statements(wanted):
            conn.execute(statement)
        if wanted != TOKENIZER_NONE:
            for spec in FTS_TABLES:
                conn.execute(f"INSERT INTO {spec.fts}({spec.fts}) VALUES ('rebuild')")
        _meta_set(conn, "fts_tokenizer", wanted)

    # -- meta and maintenance ------------------------------------------------------

    def meta_get(self, key: str) -> str | None:
        with self.read() as conn:
            return _meta_get(conn, key)

    def meta_set(self, key: str, value: str) -> None:
        with self.write() as conn:
            _meta_set(conn, key, value)

    def meta(self) -> Mapping[str, str]:
        with self.read() as conn:
            return {row["key"]: row["value"] for row in conn.execute("SELECT key, value FROM meta")}

    def optimize_fts(self, tables: Sequence[str] = ("edges", "nodes")) -> None:
        """Merge FTS b-tree segments (cheap at this scale; run after a batch finalizes)."""

        if not self.caps.fts5:
            return
        with self.write() as conn:
            for spec in FTS_TABLES:
                if spec.table in tables:
                    conn.execute(f"INSERT INTO {spec.fts}({spec.fts}) VALUES ('optimize')")

    def incremental_vacuum(self, pages: int = 2000) -> None:
        """Return up to ``pages`` free pages to the file system (after graph delete).

        Runs in its own autocommit statement under the write lock, so it must
        not be called from inside ``write()``. ``executescript`` is used
        because ``execute`` steps this pragma only once (one page).
        """

        if self.in_write:
            raise RuntimeError("incremental_vacuum must run outside write()")
        with self._write_lock:
            conn = self._acquire()
            try:
                conn.executescript(f"PRAGMA incremental_vacuum({int(pages)})")
            except sqlite3.OperationalError as error:
                self._raise_mapped(error)
            finally:
                self._release(conn)

    def fts_integrity_check(self) -> list[str]:
        """Run FTS5 ``integrity-check`` on every index; return the failures."""

        if not self.caps.fts5:
            return []
        problems: list[str] = []
        # The check is issued as an INSERT command, which needs a write transaction.
        with self.write() as conn:
            for spec in FTS_TABLES:
                try:
                    conn.execute(
                        f"INSERT INTO {spec.fts}({spec.fts}, rank) VALUES ('integrity-check', 1)"
                    )
                except sqlite3.DatabaseError as error:
                    problems.append(f"{spec.fts}: {error}")
        return problems

    # -- lifecycle ---------------------------------------------------------------

    @property
    def closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        """Close pooled connections. Idempotent."""

        if self._closed:
            return
        self._closed = True
        self._pool.close()

    def __enter__(self) -> "MemoryStore":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"MemoryStore({os.path.basename(self.path)!r}, tokenizer={self.caps.tokenizer!r})"
