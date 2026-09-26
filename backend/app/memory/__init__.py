"""Local, Zep-compatible memory backend (SQLite + FTS5).

``LocalZep`` implements the subset of ``zep_cloud.client.Zep`` that
MiroFish/Parthenon uses (graph, node, edge, episode, batch and project
clients) on one SQLite database, with LLM extraction through the existing
OpenAI-compatible ``LLMClient``. ``app.utils.zep.get_zep_client`` returns the
process-wide instance from :func:`get_local_memory_client` when the resolved
memory backend is ``local``.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Union

from .client import LocalZep
from .errors import (
    bad_request,
    conflict,
    is_busy_sqlite_error,
    map_sqlite_error,
    not_found,
    store_busy,
    translate_sqlite_errors,
    unsupported,
)
from .models import (
    LocalHttpResponse,
    PageCursor,
    decode_cursor,
    encode_cursor,
)
from .ontology import EdgeTypeMatch, OntologyView, apply_set_ontology, capture_ontology, load_ontology
from .settings import LocalMemorySettings
from .store import MemoryStore, StoreCaps, new_id, utcnow_iso
from .worker import IngestionWorker

logger = logging.getLogger("mirofish.memory")

__all__ = [
    "EdgeTypeMatch",
    "IngestionWorker",
    "LocalHttpResponse",
    "LocalMemorySettings",
    "LocalZep",
    "MemoryStore",
    "OntologyView",
    "PageCursor",
    "StoreCaps",
    "apply_set_ontology",
    "bad_request",
    "capture_ontology",
    "clear_local_memory_clients",
    "conflict",
    "decode_cursor",
    "encode_cursor",
    "get_local_memory_client",
    "is_busy_sqlite_error",
    "load_ontology",
    "map_sqlite_error",
    "new_id",
    "not_found",
    "register_local_memory_client",
    "start_local_memory_in_background",
    "store_busy",
    "translate_sqlite_errors",
    "unsupported",
    "utcnow_iso",
]

PathLike = Union[str, "os.PathLike[str]"]

_clients: dict[str, LocalZep] = {}
_clients_lock = threading.Lock()


def _normalized_path(db_path: PathLike | None) -> str:
    if db_path is None:
        from ..config import Config

        db_path = Config.LOCAL_MEMORY_DB_PATH
    return os.path.abspath(os.fspath(db_path))


def get_local_memory_client(db_path: PathLike | None = None) -> LocalZep:
    """The process-wide ``LocalZep`` for ``db_path`` (default ``Config.LOCAL_MEMORY_DB_PATH``).

    Created on first use with settings from ``Config`` and its worker
    started, which also resumes work left queued or leased by an earlier
    process. A closed instance is replaced.
    """

    path = _normalized_path(db_path)
    with _clients_lock:
        client = _clients.get(path)
        if client is None or client.closed:
            client = LocalZep(db_path=path)
            _clients[path] = client
        return client


def register_local_memory_client(client: LocalZep) -> LocalZep:
    """Make ``client`` the shared instance for its database path (tests, CLI tools)."""

    with _clients_lock:
        previous = _clients.get(client.db_path)
        _clients[client.db_path] = client
    if previous is not None and previous is not client:
        previous.close()
    return client


def clear_local_memory_clients() -> None:
    """Close every shared ``LocalZep`` (stops workers, closes pools) and forget them."""

    with _clients_lock:
        clients = list(_clients.values())
        _clients.clear()
    for client in clients:
        try:
            client.close()
        except Exception as error:  # closing is best effort
            logger.warning("Closing the local memory client failed: %s", type(error).__name__)


def start_local_memory_in_background(db_path: PathLike | None = None) -> threading.Thread:
    """Open the shared client on a daemon thread so interrupted work resumes at startup.

    The path is resolved now, in the calling thread, so a later change of
    ``Config.LOCAL_MEMORY_DB_PATH`` cannot redirect the thread.
    """

    path = _normalized_path(db_path)

    def run() -> None:
        try:
            get_local_memory_client(path)
        except Exception as error:  # the next request retries
            logger.warning("Local memory startup resume failed: %s", type(error).__name__)

    thread = threading.Thread(target=run, name="memory-startup", daemon=True)
    thread.start()
    return thread
