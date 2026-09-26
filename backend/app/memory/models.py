"""Conversions from local rows to the ``zep_cloud.types`` models, plus paging.

The local backend returns the SDK's own pydantic models so callers see the
exact attribute shapes they get from Zep Cloud (``uuid_``, ``labels``,
``processed``, ``next_cursor``, ...). The models are ``extra='allow'``, so a
few local diagnostic fields (``extraction_status``, ``extraction_error``)
ride along without affecting existing callers.

Rows may be ``sqlite3.Row`` objects or plain mappings.
"""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from zep_cloud.types import (
    BatchItemDetail,
    BatchProgress,
    BatchSummary,
    EntityEdge,
    EntityNode,
    Episode,
    Graph,
    ProjectInfo,
    ProjectInfoResponse,
)

from .errors import bad_request

__all__ = [
    "BATCH_TERMINAL_STATUSES",
    "DEFAULT_PAGE_LIMIT",
    "EPISODE_TERMINAL_STATUSES",
    "MAX_PAGE_LIMIT",
    "NEXT_CURSOR_HEADER",
    "LocalHttpResponse",
    "PageCursor",
    "batch_item_from_row",
    "batch_progress",
    "batch_summary_from_row",
    "decode_cursor",
    "edge_from_row",
    "encode_cursor",
    "episode_from_row",
    "filters_to_dict",
    "graph_from_row",
    "json_dumps",
    "json_loads",
    "node_from_row",
    "normalize_direction",
    "normalize_offset_cursor",
    "normalize_page_limit",
    "project_info_response",
    "string_list",
]

NEXT_CURSOR_HEADER = "zep-next-cursor"  # lowercase, as dict(httpx.Headers) yields it
DEFAULT_PAGE_LIMIT = 100
MAX_PAGE_LIMIT = 1000
CURSOR_VERSION = 1
PAGE_KINDS = frozenset({"node", "edge"})
DIRECTIONS = frozenset({"asc", "desc"})

# Episode extraction states after which ``processed`` is true.
EPISODE_TERMINAL_STATUSES = frozenset({"succeeded", "degraded", "failed", "skipped", "canceled"})
BATCH_TERMINAL_STATUSES = frozenset({"succeeded", "failed", "canceled", "invalid"})
BATCH_ITEM_STATUSES = ("pending", "queued", "processing", "succeeded", "failed", "skipped", "canceled")
PERCENT_CAP_WHILE_RUNNING = 99.0

GRAPH_EPISODE_KIND = "graph_episode"


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------


def json_loads(text: Any, default: Any = None) -> Any:
    """Parse stored JSON, returning ``default`` for NULL or corrupt values."""

    if text is None or text == "":
        return default
    if not isinstance(text, (str, bytes, bytearray)):
        return default
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return default


def json_dumps(value: Any) -> str:
    """Compact, deterministic JSON that keeps non-ASCII text readable."""

    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _get(row: Any, key: str, default: Any = None) -> Any:
    try:
        value = row[key]
    except (KeyError, IndexError):
        return default
    return default if value is None else value


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _labels(row: Any) -> list[str]:
    labels = json_loads(_get(row, "labels_json"), None)
    if isinstance(labels, list) and all(isinstance(label, str) for label in labels) and labels:
        return list(labels)
    entity_type = _get(row, "entity_type")
    return ["Entity", entity_type] if entity_type else ["Entity"]


# ---------------------------------------------------------------------------
# Row converters
# ---------------------------------------------------------------------------


def graph_from_row(row: Any, project_uuid: str | None = None) -> Graph:
    return Graph(
        graph_id=_get(row, "graph_id"),
        name=_get(row, "name"),
        description=_get(row, "description"),
        created_at=_get(row, "created_at"),
        uuid_=_get(row, "uuid"),
        project_uuid=project_uuid,
        time_zone=_get(row, "time_zone"),
    )


def node_from_row(row: Any, *, score: float | None = None) -> EntityNode:
    """``EntityNode`` with labels ``["Entity"]`` or ``["Entity", Type]`` and a str summary."""

    extra: dict[str, Any] = {}
    if score is not None:
        extra["score"] = score
        extra["relevance"] = score
    return EntityNode(
        uuid_=_get(row, "uuid"),
        name=_get(row, "name", ""),
        labels=_labels(row),
        summary=str(_get(row, "summary", "")),
        attributes=_dict(json_loads(_get(row, "attributes_json"), {})),
        created_at=_get(row, "created_at", ""),
        **extra,
    )


def edge_from_row(
    row: Any,
    episodes: Sequence[str] | None = None,
    *,
    score: float | None = None,
) -> EntityEdge:
    """``EntityEdge`` with temporal fields and the linked episode uuids."""

    extra: dict[str, Any] = {}
    if score is not None:
        extra["score"] = score
        extra["relevance"] = score
    return EntityEdge(
        uuid_=_get(row, "uuid"),
        name=_get(row, "name", ""),
        fact=_get(row, "fact", ""),
        source_node_uuid=_get(row, "source_node_uuid", ""),
        target_node_uuid=_get(row, "target_node_uuid", ""),
        attributes=_dict(json_loads(_get(row, "attributes_json"), {})),
        created_at=_get(row, "created_at", ""),
        valid_at=_get(row, "valid_at"),
        invalid_at=_get(row, "invalid_at"),
        expired_at=_get(row, "expired_at"),
        episodes=list(episodes or []),
        **extra,
    )


def episode_from_row(row: Any, *, score: float | None = None) -> Episode:
    """``Episode`` whose ``created_at`` is the reference time (Zep semantics).

    ``processed`` is true once extraction reached a terminal state.
    """

    status = _get(row, "extraction_status", "pending")
    processed = bool(_get(row, "processed", 0)) or status in EPISODE_TERMINAL_STATUSES
    extra: dict[str, Any] = {
        "extraction_status": status,
        "extraction_error": json_loads(_get(row, "extraction_error"), None),
    }
    if score is not None:
        extra["score"] = score
        extra["relevance"] = score
    return Episode(
        uuid_=_get(row, "uuid"),
        content=_get(row, "content", ""),
        created_at=_get(row, "reference_time") or _get(row, "created_at", ""),
        processed=processed,
        metadata=_dict(json_loads(_get(row, "metadata_json"), {})),
        source=_get(row, "source"),
        source_description=_get(row, "source_description", ""),
        **extra,
    )


def batch_progress(counts: Mapping[str, int], status: str | None, total: int | None = None) -> BatchProgress:
    """Progress block for ``batch.get``.

    ``percent_complete`` counts finished items (succeeded, failed, skipped,
    canceled) and stays at 99 or below until the batch reaches a terminal
    status, because post passes may still run after the last item.
    """

    count = {name: int(counts.get(name, 0) or 0) for name in BATCH_ITEM_STATUSES}
    total_items = int(total) if total is not None else sum(count.values())
    finished = count["succeeded"] + count["failed"] + count["skipped"] + count["canceled"]
    percent = 100.0 * finished / total_items if total_items > 0 else 0.0
    if status not in BATCH_TERMINAL_STATUSES:
        percent = min(percent, PERCENT_CAP_WHILE_RUNNING)
    return BatchProgress(
        total_items=total_items,
        queued_items=count["pending"] + count["queued"],
        processing_items=count["processing"],
        succeeded_items=count["succeeded"],
        failed_items=count["failed"],
        skipped_items=count["skipped"],
        canceled_items=count["canceled"],
        percent_complete=round(percent, 2),
    )


def batch_summary_from_row(row: Any, counts: Mapping[str, int] | None = None) -> BatchSummary:
    status = _get(row, "status")
    item_count = int(_get(row, "item_count", 0) or 0)
    extra: dict[str, Any] = {}
    error = json_loads(_get(row, "error_json"), None)
    if error is not None:
        extra["error"] = error
    return BatchSummary(
        batch_id=_get(row, "batch_id"),
        status=status,
        item_count=item_count,
        metadata=_dict(json_loads(_get(row, "metadata_json"), {})),
        ignore_roles=json_loads(_get(row, "ignore_roles_json"), None),
        created_at=_get(row, "created_at"),
        updated_at=_get(row, "updated_at"),
        processed_at=_get(row, "processed_at"),
        completed_at=_get(row, "completed_at"),
        progress=batch_progress(counts or {}, status, item_count),
        **extra,
    )


def batch_item_from_row(row: Any) -> BatchItemDetail:
    episode_uuid = _get(row, "episode_uuid")
    return BatchItemDetail(
        item_id=_get(row, "item_id"),
        sequence_index=_get(row, "sequence_index"),
        status=_get(row, "status"),
        episode_uuid=episode_uuid,
        source_uuid=episode_uuid,
        graph_id=_get(row, "graph_id"),
        kind=GRAPH_EPISODE_KIND,
        error=json_loads(_get(row, "error_json"), None),
        created_at=_get(row, "created_at"),
        updated_at=_get(row, "updated_at"),
    )


def project_info_response(project_uuid: str, created_at: str | None, db_basename: str) -> ProjectInfoResponse:
    return ProjectInfoResponse(
        project=ProjectInfo(
            uuid_=project_uuid,
            name="Parthenon local memory",
            description=f"SQLite memory backend at {db_basename}",
            created_at=created_at,
        )
    )


# ---------------------------------------------------------------------------
# Paging
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LocalHttpResponse:
    """Stand-in for the SDK's ``HttpResponse`` from ``with_raw_response`` calls.

    ``headers`` holds ``{"zep-next-cursor": "<opaque>"}`` only when more rows
    exist, else it is empty.
    """

    data: list
    headers: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class PageCursor:
    """Decoded keyset cursor: continue after row id ``after``."""

    kind: str
    graph_id: str
    after: int
    direction: str = "asc"


def normalize_direction(direction: Any) -> str:
    if direction is None:
        return "asc"
    value = str(direction).strip().lower()
    if value not in DIRECTIONS:
        raise bad_request("direction must be 'asc' or 'desc'")
    return value


def encode_cursor(kind: str, graph_id: str, after: int, direction: str | None = "asc") -> str:
    """Opaque URL-safe cursor for node/edge keyset paging."""

    if kind not in PAGE_KINDS:
        raise ValueError(f"unknown cursor kind: {kind}")
    payload = {
        "v": CURSOR_VERSION,
        "k": kind,
        "g": graph_id,
        "after": int(after),
        "d": normalize_direction(direction),
    }
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(cursor: Any, *, kind: str, graph_id: str) -> PageCursor:
    """Decode and check a cursor; anything unusable is a ``BadRequestError``."""

    if not isinstance(cursor, str) or not cursor.strip():
        raise bad_request("invalid cursor")
    text = cursor.strip()
    try:
        raw = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
        payload = json.loads(raw.decode("utf-8"))
    except (binascii.Error, ValueError, UnicodeDecodeError):
        raise bad_request("invalid cursor") from None
    if not isinstance(payload, dict) or payload.get("v") != CURSOR_VERSION:
        raise bad_request("invalid cursor")
    if payload.get("k") != kind or payload.get("g") != graph_id:
        raise bad_request("cursor does not belong to this listing")
    after = payload.get("after")
    if isinstance(after, bool) or not isinstance(after, int) or after < 0:
        raise bad_request("invalid cursor")
    direction = payload.get("d", "asc")
    if direction not in DIRECTIONS:
        raise bad_request("invalid cursor")
    return PageCursor(kind=kind, graph_id=graph_id, after=after, direction=direction)


def normalize_page_limit(limit: Any, *, default: int = DEFAULT_PAGE_LIMIT,
                         maximum: int = MAX_PAGE_LIMIT) -> int:
    """``None`` gives ``default``; ``< 1`` is a 400; values above ``maximum`` are clamped."""

    if limit is None:
        return default
    if isinstance(limit, bool):
        raise bad_request("limit must be an integer")
    try:
        value = int(limit)
    except (TypeError, ValueError):
        raise bad_request("limit must be an integer") from None
    if value < 1:
        raise bad_request("limit must be at least 1")
    return min(value, maximum)


def normalize_offset_cursor(cursor: Any) -> int:
    """Integer offset cursors for ``batch.list`` / ``list_items``; ``None`` and 0 start."""

    if cursor is None:
        return 0
    if isinstance(cursor, bool):
        raise bad_request("cursor must be a non-negative integer")
    try:
        value = int(cursor)
    except (TypeError, ValueError):
        raise bad_request("cursor must be a non-negative integer") from None
    if value < 0:
        raise bad_request("cursor must be a non-negative integer")
    return value


def filters_to_dict(filters: Any) -> dict[str, Any]:
    """Normalize ``SearchFilters`` (or a dict) to a plain dict without ``None`` values."""

    if filters is None:
        return {}
    if isinstance(filters, Mapping):
        data = dict(filters)
    elif hasattr(filters, "model_dump"):
        data = filters.model_dump(exclude_none=True)
    elif hasattr(filters, "dict"):
        data = filters.dict(exclude_none=True)
    else:
        raise bad_request("search_filters must be a SearchFilters object or a dict")
    return {key: value for key, value in data.items() if value is not None}


def string_list(value: Any) -> list[str]:
    """A filter value as a list of non-empty strings (a lone string is wrapped)."""

    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, Iterable):
        return [item for item in value if isinstance(item, str) and item]
    return []
