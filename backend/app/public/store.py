"""
The public steps' counters and featured list, in a small SQLite file.

It lives under PARTHENON_DATA_DIR (parthenon_public.sqlite3), so a restart
or a deploy does not hand every visitor a fresh day. Visitors are kept only
as salted hashes (see guard.visitor_key); the salt is made once and kept
here.

Counters are fixed windows: a UTC day ('2026-09-27') or a UTC hour
('2026-09-27T14'). take() checks every bucket it is given and counts them all
at once, or none.
"""

import os
import secrets
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


# (scope, key, window, limit)
Bucket = Tuple[str, str, str, int]

PRUNE_EVERY = 500  # takes between two prunes of old windows
KEEP_DAYS = 3


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def day_window(now: Optional[datetime] = None) -> str:
    return (now or utc_now()).strftime('%Y-%m-%d')


def hour_window(now: Optional[datetime] = None) -> str:
    return (now or utc_now()).strftime('%Y-%m-%dT%H')


def seconds_to_next_day(now: Optional[datetime] = None) -> int:
    now = now or utc_now()
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(1, int((tomorrow - now).total_seconds()))


def seconds_to_next_hour(now: Optional[datetime] = None) -> int:
    now = now or utc_now()
    next_hour = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    return max(1, int((next_hour - now).total_seconds()))


class PublicStore:
    """Thread-safe counters and featured overrides. One process (waitress threads)."""

    def __init__(self, path: str):
        self.path = path
        self._lock = threading.RLock()
        self._takes = 0
        folder = os.path.dirname(os.path.abspath(path))
        os.makedirs(folder, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS counters (
                    scope TEXT NOT NULL,
                    key TEXT NOT NULL,
                    win TEXT NOT NULL,
                    count INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (scope, key, win)
                );
                CREATE TABLE IF NOT EXISTS featured (
                    id TEXT PRIMARY KEY,
                    featured INTEGER NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
        self._salt = self._load_salt()

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        try:
            conn.execute('PRAGMA busy_timeout = 10000')
            yield conn
        finally:
            conn.close()

    def _load_salt(self) -> str:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT value FROM meta WHERE key = 'salt'").fetchone()
            if row:
                return row[0]
            salt = secrets.token_hex(32)
            conn.execute("INSERT OR IGNORE INTO meta (key, value) VALUES ('salt', ?)", (salt,))
            row = conn.execute("SELECT value FROM meta WHERE key = 'salt'").fetchone()
            return row[0]

    @property
    def salt(self) -> str:
        return self._salt

    # ---------------------------------------------------------------- counters

    def count(self, scope: str, key: str, window: str) -> int:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                'SELECT count FROM counters WHERE scope = ? AND key = ? AND win = ?',
                (scope, key, window),
            ).fetchone()
        return int(row[0]) if row else 0

    def take(self, buckets: Sequence[Bucket]) -> Tuple[bool, Optional[int]]:
        """Count one in every bucket, or in none.

        Returns (True, None) when every bucket had room, else (False, index of
        the first full bucket). A limit below one means the bucket is closed.
        """

        with self._lock, self._connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            try:
                for index, (scope, key, window, limit) in enumerate(buckets):
                    row = conn.execute(
                        'SELECT count FROM counters WHERE scope = ? AND key = ? AND win = ?',
                        (scope, key, window),
                    ).fetchone()
                    if (int(row[0]) if row else 0) >= limit:
                        conn.execute('ROLLBACK')
                        return False, index
                for scope, key, window, _limit in buckets:
                    conn.execute(
                        'INSERT INTO counters (scope, key, win, count) VALUES (?, ?, ?, 1) '
                        'ON CONFLICT (scope, key, win) DO UPDATE SET count = count + 1',
                        (scope, key, window),
                    )
                conn.execute('COMMIT')
            except BaseException:
                conn.execute('ROLLBACK')
                raise
            self._takes += 1
            if self._takes % PRUNE_EVERY == 0:
                self._prune(conn)
        return True, None

    def give_back(self, buckets: Iterable[Bucket]) -> None:
        """Undo a take() (the request it paid for came to nothing)."""

        with self._lock, self._connect() as conn:
            for scope, key, window, _limit in buckets:
                conn.execute(
                    'UPDATE counters SET count = MAX(count - 1, 0) '
                    'WHERE scope = ? AND key = ? AND win = ?',
                    (scope, key, window),
                )

    def _prune(self, conn) -> None:
        cutoff = (utc_now() - timedelta(days=KEEP_DAYS)).strftime('%Y-%m-%d')
        conn.execute('DELETE FROM counters WHERE win < ?', (cutoff,))

    # ---------------------------------------------------------------- featured

    def featured_overrides(self) -> Dict[str, bool]:
        with self._lock, self._connect() as conn:
            rows = conn.execute('SELECT id, featured FROM featured').fetchall()
        return {row[0]: bool(row[1]) for row in rows}

    def set_featured(self, gathering_id: str, featured: bool) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                'INSERT INTO featured (id, featured, updated_at) VALUES (?, ?, ?) '
                'ON CONFLICT (id) DO UPDATE SET featured = excluded.featured, '
                'updated_at = excluded.updated_at',
                (gathering_id, 1 if featured else 0, utc_now().isoformat()),
            )

    def featured_ids(self, defaults: Iterable[str]) -> List[str]:
        """The featured ids: the defaults, then those featured later; minus those unfeatured."""

        overrides = self.featured_overrides()
        ordered = list(dict.fromkeys(list(defaults) + [k for k, v in overrides.items() if v]))
        return [item for item in ordered if overrides.get(item, True)]
