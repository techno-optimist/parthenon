"""``LocalZep``: the Zep Cloud client surface, backed by SQLite (spec §2).

Call sites keep using ``client.graph.*``, ``client.batch.*`` and
``client.project.get()`` unchanged. Every method returns the SDK's own
pydantic models and raises the SDK's own exception classes (``NotFoundError``,
``BadRequestError``, ``ConflictError``, or a retryable 503 ``ApiError`` when
the store is busy), so existing error handling keeps working.

Mutations are short SQLite transactions; knowledge extraction happens later
on the :class:`~app.memory.worker.IngestionWorker`, so ``graph.add`` and the
batch calls return in milliseconds and never fail because of the LLM.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Callable, Mapping, Sequence

from zep_cloud.types import (
    BatchItemListResponse,
    BatchListResponse,
    EpisodeMentions,
    EpisodeResponse,
    SuccessResponse,
)

from .activity import ingest_activity_episode, is_activity_metadata
from .errors import bad_request, conflict, not_found, translate_sqlite_errors, unsupported
from .models import (
    LocalHttpResponse,
    NEXT_CURSOR_HEADER,
    batch_item_from_row,
    batch_summary_from_row,
    decode_cursor,
    edge_from_row,
    encode_cursor,
    episode_from_row,
    filters_to_dict,
    graph_from_row,
    json_dumps,
    node_from_row,
    normalize_direction,
    normalize_offset_cursor,
    normalize_page_limit,
    project_info_response,
    string_list,
)
from .ontology import apply_set_ontology
from .search import GraphSearcher
from .settings import LocalMemorySettings
from .store import MemoryStore, new_id
from .textnorm import epoch_to_iso, parse_iso_datetime
from .worker import IngestionWorker

logger = logging.getLogger("mirofish.memory.client")

__all__ = [
    "LocalBatchClient",
    "LocalEdgeClient",
    "LocalEpisodeClient",
    "LocalGraphClient",
    "LocalNodeClient",
    "LocalProjectClient",
    "LocalRawEdgeClient",
    "LocalRawNodeClient",
    "LocalZep",
]

MAX_GRAPH_ID_CHARS = 255
MAX_EPISODE_CHARS = 10_000
MAX_BATCH_ADD_ITEMS = 1000
EPISODE_SOURCES = frozenset({"text", "json", "message"})
GRAPH_EPISODE = "graph_episode"
ORDER_BY_VALUES = frozenset({"created_at", "uuid"})
VACUUM_PAGES_AFTER_DELETE = 2000
_IN_CHUNK = 500

_ACTIVE_ITEM_STATUSES = ("pending", "queued", "processing")
_ACTIVE_ITEMS_SQL = "'pending', 'queued', 'processing'"


def _omitted(value: Any) -> bool:
    """The SDK uses ``...`` as its "not given" default; treat it like ``None``."""

    return value is None or value is Ellipsis


def _value(value: Any) -> Any:
    return None if value is Ellipsis else value


def _marks(count: int) -> str:
    return ",".join("?" * count)


def _field(item: Any, name: str) -> Any:
    """Read ``name`` from a ``BatchAddItem`` model or a plain dict."""

    if isinstance(item, Mapping):
        return _value(item.get(name))
    return _value(getattr(item, name, None))


def _check_graph_id(graph_id: Any) -> str:
    if not isinstance(graph_id, str) or not graph_id or len(graph_id) > MAX_GRAPH_ID_CHARS:
        raise bad_request("graph_id must be a non-empty string of at most 255 characters")
    if any(ch.isspace() for ch in graph_id):
        raise bad_request("graph_id must not contain whitespace")
    return graph_id


def _check_uuid(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise bad_request(f"{what} must be a non-empty string")
    return value.strip()


def _check_data(data: Any) -> str:
    if not isinstance(data, str) or not data.strip():
        raise bad_request("data must be a non-empty string")
    if len(data) > MAX_EPISODE_CHARS:
        raise bad_request(f"data must be at most {MAX_EPISODE_CHARS} characters")
    return data


def _check_source(value: Any, what: str) -> str:
    if value not in EPISODE_SOURCES:
        raise bad_request(f"{what} must be one of text, json or message")
    return value


def _check_created_at(value: Any) -> str | None:
    if _omitted(value):
        return None
    normalized = parse_iso_datetime(value, require_timezone=True)
    if normalized is None:
        raise bad_request("created_at must be an ISO 8601 timestamp with a timezone")
    return normalized


def _check_metadata(value: Any) -> dict[str, Any]:
    if _omitted(value):
        return {}
    if not isinstance(value, Mapping):
        raise bad_request("metadata must be an object")
    cleaned: dict[str, Any] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise bad_request("metadata keys must be strings")
        if item is not None and not isinstance(item, (str, int, float, bool)):
            raise bad_request("metadata values must be strings, numbers, booleans or null")
        cleaned[key] = item
    return cleaned


def _check_optional_text(value: Any, what: str) -> str | None:
    if _omitted(value):
        return None
    if not isinstance(value, str):
        raise bad_request(f"{what} must be a string")
    return value


def _public_item_error(detail: Any) -> Any:
    """Hide the internal ``window_id`` bookkeeping from ``BatchItemDetail.error``."""

    error = getattr(detail, "error", None)
    if isinstance(error, Mapping) and "window_id" in error:
        return detail.model_copy(update={"error": {k: v for k, v in error.items() if k != "window_id"}})
    return detail


class _Unsupported:
    """An SDK namespace the local backend does not implement (``thread``, ``user``, ...).

    Every method call raises a non-retryable ``BadRequestError``.
    """

    def __init__(self, name: str) -> None:
        self._name = name

    def __getattr__(self, attribute: str) -> Any:
        if attribute.startswith("_"):
            raise AttributeError(attribute)
        name = self._name

        def call(*_args: Any, **_kwargs: Any) -> Any:
            raise unsupported(name)

        return call

    def __repr__(self) -> str:
        return f"<unsupported local memory namespace {self._name!r}>"


# ---------------------------------------------------------------------------
# Nodes and edges
# ---------------------------------------------------------------------------


class _Listing:
    """Keyset listing shared by the node and edge clients (spec §2.4)."""

    kind: str = "node"
    table: str = "nodes"

    def __init__(self, zep: "LocalZep") -> None:
        self._zep = zep

    @property
    def _store(self) -> MemoryStore:
        return self._zep.store

    def _filter_sql(self, filters: Mapping[str, Any], params: list[Any]) -> str:
        raise NotImplementedError

    def _convert(self, conn: Any, rows: Sequence[Any]) -> list[Any]:
        raise NotImplementedError

    @translate_sqlite_errors
    def _page(self, graph_id: Any, *, cursor: Any = None, direction: Any = None, filters: Any = None,
              limit: Any = None, order_by: Any = None, uuid_cursor: Any = None) -> LocalHttpResponse:
        graph_id = _check_uuid(_value(graph_id), "graph_id")
        page_limit = normalize_page_limit(_value(limit))
        wanted = None if _omitted(direction) else normalize_direction(direction)
        order = _value(order_by)
        if order is not None and (not isinstance(order, str) or order.strip().lower() not in ORDER_BY_VALUES):
            raise bad_request("order_by must be created_at or uuid")
        spec = filters_to_dict(_value(filters))

        with self._store.read(snapshot=True) as conn:
            if conn.execute("SELECT 1 FROM graphs WHERE graph_id = ?", (graph_id,)).fetchone() is None:
                raise not_found(f"graph not found: {graph_id}")
            after: int | None = None
            direction_used = wanted or "asc"
            if not _omitted(cursor):
                decoded = decode_cursor(cursor, kind=self.kind, graph_id=graph_id)
                if wanted is not None and wanted != decoded.direction:
                    raise bad_request("cursor direction does not match direction")
                after, direction_used = decoded.after, decoded.direction
            elif not _omitted(uuid_cursor):
                row = conn.execute(
                    f"SELECT id FROM {self.table} WHERE uuid = ? AND graph_id = ?", (str(uuid_cursor), graph_id)
                ).fetchone()
                if row is None:
                    raise bad_request("uuid_cursor does not belong to this graph")
                after = int(row["id"])

            params: list[Any] = [graph_id]
            where = "graph_id = ?"
            if after is not None:
                where += " AND id < ?" if direction_used == "desc" else " AND id > ?"
                params.append(after)
            where += self._filter_sql(spec, params)
            sort = "DESC" if direction_used == "desc" else "ASC"
            rows = conn.execute(
                f"SELECT * FROM {self.table} WHERE {where} ORDER BY id {sort} LIMIT ?",
                (*params, page_limit + 1),
            ).fetchall()
            more = len(rows) > page_limit
            rows = rows[:page_limit]
            data = self._convert(conn, rows)
        headers: dict[str, str] = {}
        if more and rows:
            headers[NEXT_CURSOR_HEADER] = encode_cursor(self.kind, graph_id, int(rows[-1]["id"]), direction_used)
        return LocalHttpResponse(data=data, headers=headers)


def _labels_clause(column: str, labels: Sequence[str], params: list[Any]) -> str:
    """SQL that is true when the JSON label array ``column`` holds any of ``labels``."""

    parts = []
    for label in labels:
        parts.append(f"instr({column}, ?) > 0")
        params.append(json_dumps(label))
    return "(" + " OR ".join(parts) + ")"


class LocalNodeClient(_Listing):
    """``client.graph.node`` (spec §2.4)."""

    kind = "node"
    table = "nodes"

    def _filter_sql(self, filters: Mapping[str, Any], params: list[Any]) -> str:
        sql = ""
        include = string_list(filters.get("node_labels"))
        exclude = string_list(filters.get("exclude_node_labels"))
        if include:
            sql += " AND " + _labels_clause("labels_json", include, params)
        if exclude:
            sql += " AND NOT " + _labels_clause("labels_json", exclude, params)
        return sql

    def _convert(self, conn: Any, rows: Sequence[Any]) -> list[Any]:
        return [node_from_row(row) for row in rows]

    @property
    def with_raw_response(self) -> "LocalRawNodeClient":
        return LocalRawNodeClient(self)

    def get_by_graph_id(self, graph_id: str, *, cursor: Any = None, direction: Any = None, filters: Any = None,
                        limit: Any = None, order_by: Any = None, uuid_cursor: Any = None,
                        request_options: Any = None) -> list[Any]:
        return self._page(graph_id, cursor=cursor, direction=direction, filters=filters, limit=limit,
                          order_by=order_by, uuid_cursor=uuid_cursor).data

    def get_by_user_id(self, user_id: str, **_kwargs: Any) -> list[Any]:
        raise unsupported("user graphs")

    @translate_sqlite_errors
    def get(self, uuid_: str, *, request_options: Any = None) -> Any:
        node_uuid = _check_uuid(uuid_, "uuid_")
        with self._store.read() as conn:
            row = conn.execute("SELECT * FROM nodes WHERE uuid = ?", (node_uuid,)).fetchone()
        if row is None:
            raise not_found(f"node not found: {node_uuid}")
        return node_from_row(row)

    @translate_sqlite_errors
    def get_edges(self, node_uuid: str, *, request_options: Any = None) -> list[Any]:
        """Outgoing **and** incoming edges of the node, including invalidated ones.

        Zep Cloud 3.25 returns outgoing edges only; returning both is a
        documented improvement for ``ZepEntityReader.get_node_edges``.
        """

        node_uuid = _check_uuid(node_uuid, "node_uuid")
        with self._store.read(snapshot=True) as conn:
            if conn.execute("SELECT 1 FROM nodes WHERE uuid = ?", (node_uuid,)).fetchone() is None:
                raise not_found(f"node not found: {node_uuid}")
            rows = conn.execute(
                "SELECT * FROM edges WHERE source_node_uuid = ? UNION "
                "SELECT * FROM edges WHERE target_node_uuid = ? ORDER BY created_at, id",
                (node_uuid, node_uuid),
            ).fetchall()
            return _edges_with_episodes(conn, rows)

    @translate_sqlite_errors
    def get_episodes(self, node_uuid: str, *, request_options: Any = None) -> EpisodeResponse:
        node_uuid = _check_uuid(node_uuid, "node_uuid")
        with self._store.read(snapshot=True) as conn:
            if conn.execute("SELECT 1 FROM nodes WHERE uuid = ?", (node_uuid,)).fetchone() is None:
                raise not_found(f"node not found: {node_uuid}")
            rows = conn.execute(
                "SELECT e.* FROM node_episodes ne JOIN episodes e ON e.uuid = ne.episode_uuid "
                "WHERE ne.node_uuid = ? ORDER BY e.created_at, e.id",
                (node_uuid,),
            ).fetchall()
        return EpisodeResponse(episodes=[episode_from_row(row) for row in rows])

    @translate_sqlite_errors
    def delete(self, uuid_: str, *, request_options: Any = None) -> SuccessResponse:
        node_uuid = _check_uuid(uuid_, "uuid_")
        with self._store.write() as conn:
            row = conn.execute("SELECT graph_id FROM nodes WHERE uuid = ?", (node_uuid,)).fetchone()
            if row is None:
                raise not_found(f"node not found: {node_uuid}")
            conn.execute("DELETE FROM nodes WHERE uuid = ?", (node_uuid,))
            conn.execute("UPDATE graphs SET version = version + 1 WHERE graph_id = ?", (row["graph_id"],))
        return SuccessResponse(message="Node deleted")


class LocalEdgeClient(_Listing):
    """``client.graph.edge`` (spec §2.4). Listings include invalidated edges."""

    kind = "edge"
    table = "edges"

    def _filter_sql(self, filters: Mapping[str, Any], params: list[Any]) -> str:
        sql = ""
        include = string_list(filters.get("edge_types"))
        exclude = string_list(filters.get("exclude_edge_types"))
        if include:
            sql += f" AND name IN ({_marks(len(include))})"
            params.extend(include)
        if exclude:
            sql += f" AND name NOT IN ({_marks(len(exclude))})"
            params.extend(exclude)
        return sql

    def _convert(self, conn: Any, rows: Sequence[Any]) -> list[Any]:
        return _edges_with_episodes(conn, rows)

    @property
    def with_raw_response(self) -> "LocalRawEdgeClient":
        return LocalRawEdgeClient(self)

    def get_by_graph_id(self, graph_id: str, *, cursor: Any = None, direction: Any = None, filters: Any = None,
                        limit: Any = None, order_by: Any = None, uuid_cursor: Any = None,
                        request_options: Any = None) -> list[Any]:
        return self._page(graph_id, cursor=cursor, direction=direction, filters=filters, limit=limit,
                          order_by=order_by, uuid_cursor=uuid_cursor).data

    def get_by_user_id(self, user_id: str, **_kwargs: Any) -> list[Any]:
        raise unsupported("user graphs")

    @translate_sqlite_errors
    def get(self, uuid_: str, *, request_options: Any = None) -> Any:
        edge_uuid = _check_uuid(uuid_, "uuid_")
        with self._store.read(snapshot=True) as conn:
            row = conn.execute("SELECT * FROM edges WHERE uuid = ?", (edge_uuid,)).fetchone()
            if row is None:
                raise not_found(f"edge not found: {edge_uuid}")
            return _edges_with_episodes(conn, [row])[0]

    @translate_sqlite_errors
    def delete(self, uuid_: str, *, request_options: Any = None) -> SuccessResponse:
        edge_uuid = _check_uuid(uuid_, "uuid_")
        with self._store.write() as conn:
            row = conn.execute("SELECT graph_id FROM edges WHERE uuid = ?", (edge_uuid,)).fetchone()
            if row is None:
                raise not_found(f"edge not found: {edge_uuid}")
            conn.execute("DELETE FROM edges WHERE uuid = ?", (edge_uuid,))
            conn.execute("UPDATE graphs SET version = version + 1 WHERE graph_id = ?", (row["graph_id"],))
        return SuccessResponse(message="Edge deleted")


class LocalRawNodeClient:
    """``node.with_raw_response``: listings with ``.data`` and ``.headers``."""

    def __init__(self, nodes: LocalNodeClient) -> None:
        self._nodes = nodes

    def get_by_graph_id(self, graph_id: str, *, cursor: Any = None, direction: Any = None, filters: Any = None,
                        limit: Any = None, order_by: Any = None, uuid_cursor: Any = None,
                        request_options: Any = None) -> LocalHttpResponse:
        return self._nodes._page(graph_id, cursor=cursor, direction=direction, filters=filters, limit=limit,
                                 order_by=order_by, uuid_cursor=uuid_cursor)


class LocalRawEdgeClient:
    """``edge.with_raw_response``: listings with ``.data`` and ``.headers``."""

    def __init__(self, edges: LocalEdgeClient) -> None:
        self._edges = edges

    def get_by_graph_id(self, graph_id: str, *, cursor: Any = None, direction: Any = None, filters: Any = None,
                        limit: Any = None, order_by: Any = None, uuid_cursor: Any = None,
                        request_options: Any = None) -> LocalHttpResponse:
        return self._edges._page(graph_id, cursor=cursor, direction=direction, filters=filters, limit=limit,
                                 order_by=order_by, uuid_cursor=uuid_cursor)


def _edges_with_episodes(conn: Any, rows: Sequence[Any]) -> list[Any]:
    """Edge models with their episode uuids (ordered by link time)."""

    uuids = [row["uuid"] for row in rows]
    episodes: dict[str, list[str]] = {uuid_: [] for uuid_ in uuids}
    for start in range(0, len(uuids), _IN_CHUNK):
        part = uuids[start:start + _IN_CHUNK]
        for link in conn.execute(
            f"SELECT edge_uuid, episode_uuid FROM edge_episodes WHERE edge_uuid IN ({_marks(len(part))}) "
            "ORDER BY linked_at, rowid",
            tuple(part),
        ):
            episodes[link["edge_uuid"]].append(link["episode_uuid"])
    return [edge_from_row(row, episodes.get(row["uuid"], [])) for row in rows]


# ---------------------------------------------------------------------------
# Episodes
# ---------------------------------------------------------------------------


class LocalEpisodeClient:
    """``client.graph.episode`` (spec §2.5)."""

    def __init__(self, zep: "LocalZep") -> None:
        self._zep = zep

    @translate_sqlite_errors
    def get(self, uuid_: str, *, request_options: Any = None) -> Any:
        episode_uuid = _check_uuid(uuid_, "uuid_")
        with self._zep.store.read() as conn:
            row = conn.execute("SELECT * FROM episodes WHERE uuid = ?", (episode_uuid,)).fetchone()
        if row is None:
            raise not_found(f"episode not found: {episode_uuid}")
        return episode_from_row(row)

    @translate_sqlite_errors
    def get_by_graph_id(self, graph_id: str, *, lastn: int | None = None,
                        request_options: Any = None) -> EpisodeResponse:
        """The most recent ``lastn`` episodes (all when ``None``), oldest first."""

        graph_id = _check_uuid(graph_id, "graph_id")
        lastn = _value(lastn)
        if lastn is not None and (isinstance(lastn, bool) or not isinstance(lastn, int) or lastn < 1):
            raise bad_request("lastn must be a positive integer")
        with self._zep.store.read(snapshot=True) as conn:
            if conn.execute("SELECT 1 FROM graphs WHERE graph_id = ?", (graph_id,)).fetchone() is None:
                raise not_found(f"graph not found: {graph_id}")
            if lastn is None:
                rows = conn.execute(
                    "SELECT * FROM episodes WHERE graph_id = ? ORDER BY created_at, id", (graph_id,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM episodes WHERE graph_id = ? ORDER BY created_at DESC, id DESC LIMIT ?",
                    (graph_id, lastn),
                ).fetchall()
                rows.reverse()
        return EpisodeResponse(episodes=[episode_from_row(row) for row in rows])

    @translate_sqlite_errors
    def mentions(self, uuid_: str, *, request_options: Any = None) -> EpisodeMentions:
        """Nodes and edges extracted from the episode (``node_episodes`` / ``edge_episodes``)."""

        episode_uuid = _check_uuid(uuid_, "uuid_")
        with self._zep.store.read(snapshot=True) as conn:
            if conn.execute("SELECT 1 FROM episodes WHERE uuid = ?", (episode_uuid,)).fetchone() is None:
                raise not_found(f"episode not found: {episode_uuid}")
            nodes = conn.execute(
                "SELECT n.* FROM node_episodes ne JOIN nodes n ON n.uuid = ne.node_uuid "
                "WHERE ne.episode_uuid = ? ORDER BY n.id",
                (episode_uuid,),
            ).fetchall()
            edges = conn.execute(
                "SELECT e.* FROM edge_episodes ee JOIN edges e ON e.uuid = ee.edge_uuid "
                "WHERE ee.episode_uuid = ? ORDER BY e.id",
                (episode_uuid,),
            ).fetchall()
            edge_models = _edges_with_episodes(conn, edges)
        return EpisodeMentions(nodes=[node_from_row(row) for row in nodes], edges=edge_models)

    # SDK name for the same call.
    get_nodes_and_edges = mentions


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------


class LocalGraphClient:
    """``client.graph`` (spec §2.3)."""

    def __init__(self, zep: "LocalZep") -> None:
        self._zep = zep
        self.node = LocalNodeClient(zep)
        self.edge = LocalEdgeClient(zep)
        self.episode = LocalEpisodeClient(zep)

    @property
    def _store(self) -> MemoryStore:
        return self._zep.store

    @translate_sqlite_errors
    def create(self, *, graph_id: str, name: str | None = None, description: str | None = None,
               time_zone: str | None = None, request_options: Any = None) -> Any:
        graph_id = _check_graph_id(_value(graph_id))
        name = _check_optional_text(name, "name")
        description = _check_optional_text(description, "description")
        time_zone = _check_optional_text(time_zone, "time_zone")
        now = self._zep.now_iso()
        with self._store.write() as conn:
            if conn.execute("SELECT 1 FROM graphs WHERE graph_id = ?", (graph_id,)).fetchone() is not None:
                raise conflict(f"graph already exists: {graph_id}")
            conn.execute(
                "INSERT INTO graphs(graph_id, uuid, name, description, time_zone, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (graph_id, new_id(), name, description, time_zone, now),
            )
            row = conn.execute("SELECT * FROM graphs WHERE graph_id = ?", (graph_id,)).fetchone()
        logger.info("Local graph created: %s", graph_id)
        return graph_from_row(row, self._store.project_uuid)

    @translate_sqlite_errors
    def get(self, graph_id: str, *, request_options: Any = None) -> Any:
        graph_id = _check_uuid(graph_id, "graph_id")
        with self._store.read() as conn:
            row = conn.execute("SELECT * FROM graphs WHERE graph_id = ?", (graph_id,)).fetchone()
        if row is None:
            raise not_found(f"graph not found: {graph_id}")
        return graph_from_row(row, self._store.project_uuid)

    @translate_sqlite_errors
    def delete(self, graph_id: str, *, request_options: Any = None) -> SuccessResponse:
        """Delete a graph with everything in it; its active batch items are canceled."""

        graph_id = _check_uuid(graph_id, "graph_id")
        now = self._zep.now_iso()
        with self._store.write() as conn:
            if conn.execute("SELECT 1 FROM graphs WHERE graph_id = ?", (graph_id,)).fetchone() is None:
                raise not_found(f"graph not found: {graph_id}")
            affected = [
                row["batch_id"] for row in conn.execute(
                    "SELECT DISTINCT batch_id FROM batch_items WHERE graph_id = ?", (graph_id,)
                )
            ]
            canceled = conn.execute(
                "UPDATE batch_items SET status = 'canceled', updated_at = ? "
                f"WHERE graph_id = ? AND status IN ({_ACTIVE_ITEMS_SQL})",
                (now, graph_id),
            ).rowcount
            conn.execute("DELETE FROM graphs WHERE graph_id = ?", (graph_id,))
            for batch_id in affected:
                _recompute_after_graph_delete(conn, batch_id, graph_id, now)
        self._zep.searcher.invalidate(graph_id)
        logger.info("Local graph deleted: %s (%d active batch items canceled)", graph_id, canceled)
        try:
            self._store.incremental_vacuum(VACUUM_PAGES_AFTER_DELETE)
        except Exception as error:  # space reclamation is best effort
            logger.debug("Incremental vacuum after graph delete failed: %s", type(error).__name__)
        return SuccessResponse(message="Graph deleted")

    def set_ontology(self, entities: Any, edges: Any = None, user_ids: Any = None, graph_ids: Any = None,
                     request_options: Any = None) -> SuccessResponse:
        return translate_sqlite_errors(apply_set_ontology)(
            self._store, entities, edges, user_ids=_value(user_ids), graph_ids=_value(graph_ids)
        )

    # SDK alias.
    set_entity_types = set_ontology

    @translate_sqlite_errors
    def add(self, *, data: str, type: str, created_at: str | None = None, graph_id: str | None = None,
            metadata: dict | None = None, source_description: str | None = None,
            strict_ontology: bool | None = None, user_id: str | None = None, request_options: Any = None) -> Any:
        """Store one episode and queue (or apply) its extraction (spec §2.3, §5.1).

        Returns in milliseconds and never raises because of the LLM.
        """

        if not _omitted(user_id):
            raise unsupported("user graphs")
        if _omitted(graph_id):
            raise bad_request("graph_id is required")
        graph_id = _check_uuid(graph_id, "graph_id")
        source = _check_source(type, "type")
        data = _check_data(data)
        reference = _check_created_at(created_at)
        meta = _check_metadata(metadata)
        description = _check_optional_text(source_description, "source_description") or ""
        strict = _value(strict_ontology)
        if strict is not None and not isinstance(strict, bool):
            raise bad_request("strict_ontology must be a boolean")
        kind = "activity" if is_activity_metadata(meta) else "document"
        simulation_id = meta.get("simulation_id")
        now = self._zep.now_iso()
        episode_uuid = new_id()

        with self._store.write() as conn:
            if conn.execute("SELECT 1 FROM graphs WHERE graph_id = ?", (graph_id,)).fetchone() is None:
                raise not_found(f"graph not found: {graph_id}")
            conn.execute(
                "INSERT INTO episodes(uuid, graph_id, kind, content, source, source_description, metadata_json, "
                "simulation_id, strict_ontology, reference_time, reference_time_explicit, created_at, "
                "queued_at, processed, extraction_status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)",
                (
                    episode_uuid, graph_id, kind, data, source, description, json_dumps(meta),
                    None if simulation_id is None else str(simulation_id), 1 if strict else 0,
                    reference or now, 1 if reference else 0, now,
                    now if kind == "document" else None,
                    "queued" if kind == "document" else "pending",
                ),
            )
            if kind == "activity":
                ingest_activity_episode(conn, episode_uuid, mode=self._zep.settings.activity_mode, now=now)
            row = conn.execute("SELECT * FROM episodes WHERE uuid = ?", (episode_uuid,)).fetchone()
        if row["extraction_status"] == "queued":
            self._zep.worker.notify()
        return episode_from_row(row)

    def search(self, **kwargs: Any) -> Any:
        """Lexical hybrid search (spec §6); accepts the SDK's keyword arguments."""

        return self._zep.searcher.search(**kwargs)


def _recompute_after_graph_delete(conn: Any, batch_id: str, graph_id: str, now: str) -> None:
    """Cancel a running batch once nothing of it can still complete (spec §2.3 delete)."""

    batch = conn.execute("SELECT status FROM batches WHERE batch_id = ?", (batch_id,)).fetchone()
    if batch is None or batch["status"] not in ("draft", "queued", "processing"):
        return
    counts = {
        row["status"]: int(row["n"])
        for row in conn.execute(
            "SELECT status, count(*) AS n FROM batch_items WHERE batch_id = ? GROUP BY status", (batch_id,)
        )
    }
    if any(counts.get(status, 0) for status in _ACTIVE_ITEM_STATUSES):
        return
    elsewhere = conn.execute(
        "SELECT 1 FROM batch_items WHERE batch_id = ? AND graph_id != ? AND status != 'canceled' LIMIT 1",
        (batch_id, graph_id),
    ).fetchone()
    if elsewhere is not None:
        return  # items of another graph remain: the finalizer decides
    conn.execute(
        "UPDATE batches SET status = 'canceled', completed_at = ?, updated_at = ?, finalize_owner = NULL, "
        "finalize_until = NULL WHERE batch_id = ?",
        (now, now, batch_id),
    )


# ---------------------------------------------------------------------------
# Batches
# ---------------------------------------------------------------------------


def _counts_by_batch(conn: Any, batch_ids: Sequence[str]) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {batch_id: {} for batch_id in batch_ids}
    for start in range(0, len(batch_ids), _IN_CHUNK):
        part = batch_ids[start:start + _IN_CHUNK]
        for row in conn.execute(
            f"SELECT batch_id, status, count(*) AS n FROM batch_items WHERE batch_id IN ({_marks(len(part))}) "
            "GROUP BY batch_id, status",
            tuple(part),
        ):
            counts[row["batch_id"]][row["status"]] = int(row["n"])
    return counts


class LocalBatchClient:
    """``client.batch`` (spec §2.6).

    State machine: ``draft -> queued -> processing -> succeeded | failed |
    canceled``, plus ``draft -> invalid`` for an empty batch.
    """

    def __init__(self, zep: "LocalZep") -> None:
        self._zep = zep

    @property
    def _store(self) -> MemoryStore:
        return self._zep.store

    def _summary(self, conn: Any, batch_id: str) -> Any:
        row = conn.execute("SELECT * FROM batches WHERE batch_id = ?", (batch_id,)).fetchone()
        if row is None:
            raise not_found(f"batch not found: {batch_id}")
        return batch_summary_from_row(row, _counts_by_batch(conn, [batch_id])[batch_id])

    @translate_sqlite_errors
    def create(self, *, ignore_roles: Any = None, metadata: Any = None, request_options: Any = None) -> Any:
        meta = _value(metadata)
        if meta is None:
            meta = {}
        if not isinstance(meta, Mapping):
            raise bad_request("metadata must be an object")
        roles = _value(ignore_roles)
        if roles is not None and (isinstance(roles, str) or not isinstance(roles, Sequence)):
            raise bad_request("ignore_roles must be a list")
        batch_id = new_id()
        now = self._zep.now_iso()
        with self._store.write() as conn:
            conn.execute(
                "INSERT INTO batches(batch_id, status, metadata_json, ignore_roles_json, created_at, updated_at) "
                "VALUES (?, 'draft', ?, ?, ?, ?)",
                (batch_id, json_dumps(dict(meta)), None if roles is None else json_dumps(list(roles)), now, now),
            )
            return self._summary(conn, batch_id)

    @translate_sqlite_errors
    def add(self, batch_id: str, *, items: Sequence[Any], request_options: Any = None) -> list[Any]:
        """Append items to a draft batch in one transaction (all or nothing)."""

        batch_id = _check_uuid(batch_id, "batch_id")
        if isinstance(items, (str, bytes, Mapping)) or not isinstance(items, Sequence):
            raise bad_request("items must be a list")
        if not 1 <= len(items) <= MAX_BATCH_ADD_ITEMS:
            raise bad_request(f"items must contain between 1 and {MAX_BATCH_ADD_ITEMS} entries")
        prepared = []
        for item in items:
            if _field(item, "type") != GRAPH_EPISODE:
                raise unsupported("batch items other than graph_episode")
            if not _omitted(_field(item, "user_id")) or not _omitted(_field(item, "thread_id")):
                raise unsupported("user and thread batch items")
            graph_id = _check_uuid(_field(item, "graph_id"), "graph_id")
            data_type = _field(item, "data_type") or "text"
            prepared.append({
                "graph_id": graph_id,
                "data": _check_data(_field(item, "data")),
                "source": _check_source(data_type, "data_type"),
                "created_at": _check_created_at(_field(item, "created_at")),
                "metadata": _check_metadata(_field(item, "metadata")),
                "source_description": _check_optional_text(_field(item, "source_description"),
                                                           "source_description") or "",
            })

        now = self._zep.now_iso()
        with self._store.write() as conn:
            batch = conn.execute(
                "SELECT status, item_count FROM batches WHERE batch_id = ?", (batch_id,)
            ).fetchone()
            if batch is None:
                raise not_found(f"batch not found: {batch_id}")
            if batch["status"] != "draft":
                raise conflict(f"batch {batch_id} is {batch['status']}; items can only be added to a draft batch")
            for graph_id in sorted({item["graph_id"] for item in prepared}):
                if conn.execute("SELECT 1 FROM graphs WHERE graph_id = ?", (graph_id,)).fetchone() is None:
                    raise not_found(f"graph not found: {graph_id}")
            start = int(batch["item_count"] or 0)
            item_ids = []
            for offset, item in enumerate(prepared):
                episode_uuid = new_id()
                item_id = new_id()
                sequence = start + offset
                conn.execute(
                    "INSERT INTO episodes(uuid, graph_id, kind, content, source, source_description, metadata_json, "
                    "reference_time, reference_time_explicit, created_at, processed, extraction_status, batch_id, "
                    "sequence_index) VALUES (?, ?, 'document', ?, ?, ?, ?, ?, ?, ?, 0, 'pending', ?, ?)",
                    (
                        episode_uuid, item["graph_id"], item["data"], item["source"], item["source_description"],
                        json_dumps(item["metadata"]), item["created_at"] or now, 1 if item["created_at"] else 0,
                        now, batch_id, sequence,
                    ),
                )
                conn.execute(
                    "INSERT INTO batch_items(item_id, batch_id, sequence_index, graph_id, episode_uuid, status, "
                    "created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)",
                    (item_id, batch_id, sequence, item["graph_id"], episode_uuid, now, now),
                )
                item_ids.append(item_id)
            conn.execute(
                "UPDATE batches SET item_count = item_count + ?, updated_at = ? WHERE batch_id = ?",
                (len(prepared), now, batch_id),
            )
            rows = {
                row["item_id"]: row for row in conn.execute(
                    "SELECT * FROM batch_items WHERE batch_id = ? AND sequence_index >= ?", (batch_id, start)
                )
            }
        return [batch_item_from_row(rows[item_id]) for item_id in item_ids]

    @translate_sqlite_errors
    def process(self, batch_id: str, *, request_options: Any = None) -> Any:
        """Start processing a draft batch; idempotent once it is queued or later."""

        batch_id = _check_uuid(batch_id, "batch_id")
        now = self._zep.now_iso()
        queued = False
        with self._store.write() as conn:
            batch = conn.execute(
                "SELECT status, item_count FROM batches WHERE batch_id = ?", (batch_id,)
            ).fetchone()
            if batch is None:
                raise not_found(f"batch not found: {batch_id}")
            status = batch["status"]
            if status in ("invalid", "canceled"):
                raise conflict(f"batch {batch_id} is {status} and cannot be processed")
            if status == "draft":
                if int(batch["item_count"] or 0) == 0:
                    conn.execute(
                        "UPDATE batches SET status = 'invalid', updated_at = ?, completed_at = ? WHERE batch_id = ?",
                        (now, now, batch_id),
                    )
                else:
                    conn.execute(
                        "UPDATE batches SET status = 'queued', processed_at = ?, updated_at = ? WHERE batch_id = ?",
                        (now, now, batch_id),
                    )
                    conn.execute(
                        "UPDATE episodes SET extraction_status = 'queued', queued_at = ? "
                        "WHERE batch_id = ? AND extraction_status = 'pending'",
                        (now, batch_id),
                    )
                    conn.execute(
                        "UPDATE batch_items SET status = 'queued', updated_at = ? "
                        "WHERE batch_id = ? AND status = 'pending'",
                        (now, batch_id),
                    )
                    queued = True
            summary = self._summary(conn, batch_id)
        if queued:
            logger.info("Local batch %s queued (%d items)", batch_id, summary.item_count or 0)
            self._zep.worker.notify()
        return summary

    @translate_sqlite_errors
    def get(self, batch_id: str, *, request_options: Any = None) -> Any:
        batch_id = _check_uuid(batch_id, "batch_id")
        with self._store.read(snapshot=True) as conn:
            return self._summary(conn, batch_id)

    @translate_sqlite_errors
    def list(self, *, limit: int | None = None, cursor: int | None = None, status: str | None = None,
             request_options: Any = None) -> BatchListResponse:
        """Newest first; ``cursor`` is an integer offset (``None``/0 start)."""

        page_limit = normalize_page_limit(_value(limit))
        offset = normalize_offset_cursor(_value(cursor))
        status = _check_optional_text(status, "status")
        params: list[Any] = []
        where = ""
        if status:
            where = "WHERE status = ?"
            params.append(status)
        with self._store.read(snapshot=True) as conn:
            rows = conn.execute(
                f"SELECT * FROM batches {where} ORDER BY id DESC LIMIT ? OFFSET ?",
                (*params, page_limit + 1, offset),
            ).fetchall()
            more = len(rows) > page_limit
            rows = rows[:page_limit]
            counts = _counts_by_batch(conn, [row["batch_id"] for row in rows])
        return BatchListResponse(
            batches=[batch_summary_from_row(row, counts[row["batch_id"]]) for row in rows],
            next_cursor=offset + len(rows) if more else None,
        )

    @translate_sqlite_errors
    def list_items(self, batch_id: str, *, limit: int | None = None, cursor: int | None = None,
                   status: str | None = None, request_options: Any = None) -> BatchItemListResponse:
        """Items in ``sequence_index`` order; ``cursor`` is an integer offset."""

        batch_id = _check_uuid(batch_id, "batch_id")
        page_limit = normalize_page_limit(_value(limit))
        offset = normalize_offset_cursor(_value(cursor))
        status = _check_optional_text(status, "status")
        params: list[Any] = [batch_id]
        where = "batch_id = ?"
        if status:
            where += " AND status = ?"
            params.append(status)
        with self._store.read(snapshot=True) as conn:
            if conn.execute("SELECT 1 FROM batches WHERE batch_id = ?", (batch_id,)).fetchone() is None:
                raise not_found(f"batch not found: {batch_id}")
            rows = conn.execute(
                f"SELECT * FROM batch_items WHERE {where} ORDER BY sequence_index LIMIT ? OFFSET ?",
                (*params, page_limit + 1, offset),
            ).fetchall()
        more = len(rows) > page_limit
        rows = rows[:page_limit]
        return BatchItemListResponse(
            items=[_public_item_error(batch_item_from_row(row)) for row in rows],
            next_cursor=offset + len(rows) if more else None,
        )

    @translate_sqlite_errors
    def delete(self, batch_id: str, *, request_options: Any = None) -> SuccessResponse:
        """Delete a draft batch with its items and their episodes."""

        batch_id = _check_uuid(batch_id, "batch_id")
        with self._store.write() as conn:
            batch = conn.execute("SELECT status FROM batches WHERE batch_id = ?", (batch_id,)).fetchone()
            if batch is None:
                raise not_found(f"batch not found: {batch_id}")
            if batch["status"] != "draft":
                raise conflict(f"batch {batch_id} is {batch['status']}; only draft batches can be deleted")
            conn.execute(
                "DELETE FROM episodes WHERE uuid IN (SELECT episode_uuid FROM batch_items WHERE batch_id = ?)",
                (batch_id,),
            )
            conn.execute("DELETE FROM batches WHERE batch_id = ?", (batch_id,))
        return SuccessResponse(message="Batch deleted")


class LocalProjectClient:
    """``client.project`` (spec §2.7). Never raises."""

    def __init__(self, zep: "LocalZep") -> None:
        self._zep = zep

    def get(self, *, request_options: Any = None) -> Any:
        store = self._zep.store
        return project_info_response(store.project_uuid, store.created_at or None,
                                     os.path.basename(store.path))


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class LocalZep:
    """In-process, SQLite-backed stand-in for ``zep_cloud.client.Zep`` (spec §2.2).

    One instance is shared by every request thread, the build thread, the
    simulation updater and the profile-generation pools. All state lives in
    SQLite; the only in-memory state is caches. ``llm_client_factory`` is
    called lazily on the first extraction, so search-only use works without
    ``LLM_API_KEY``.
    """

    backend = "local"

    def __init__(
        self,
        *,
        db_path: str | os.PathLike,
        settings: LocalMemorySettings | None = None,
        llm_client_factory: Callable[[], Any] | None = None,
        autostart_worker: bool = True,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.settings = settings or LocalMemorySettings.from_config()
        self.db_path = os.path.abspath(os.fspath(db_path))
        self.clock = clock
        self._closed = False
        self._close_lock = threading.Lock()
        self.store = MemoryStore(
            self.db_path,
            pool_size=self.settings.pool_size,
            busy_timeout_ms=self.settings.busy_timeout_ms,
        )
        try:
            self.searcher = GraphSearcher(self.store, self.settings)
            self.worker = IngestionWorker(self.store, self.settings, llm_client_factory, clock=clock, sleep=sleep)
        except BaseException:
            self.store.close()
            raise
        self.graph = LocalGraphClient(self)
        self.batch = LocalBatchClient(self)
        self.project = LocalProjectClient(self)
        self.thread = _Unsupported("thread")
        self.user = _Unsupported("user")
        self.context = _Unsupported("context")
        self.task = _Unsupported("task")
        self.ingestion_wait_timeout_seconds: float = float(self.settings.ingestion_timeout_seconds)
        if autostart_worker:
            self.worker.start()
        logger.info("Local memory backend ready at %s (FTS tokenizer: %s)",
                    os.path.basename(self.db_path), self.store.caps.tokenizer)

    def now_iso(self) -> str:
        """The client clock as a stored timestamp (UTC, microseconds, ``Z``)."""

        return epoch_to_iso(self.clock())

    @property
    def closed(self) -> bool:
        return self._closed

    def close(self, timeout: float = 10.0) -> None:
        """Stop the worker and close the connection pool (idempotent)."""

        with self._close_lock:
            if self._closed:
                return
            self._closed = True
        try:
            self.worker.stop(timeout=timeout)
        finally:
            self.store.close()

    def __enter__(self) -> "LocalZep":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"LocalZep({os.path.basename(self.db_path)!r})"
