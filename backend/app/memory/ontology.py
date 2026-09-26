"""Ontology capture and lookup for the local memory backend (spec §2.3).

``graph.set_ontology`` receives the same dynamic ``EntityModel`` /
``EdgeModel`` subclasses that Zep Cloud receives. They are converted with the
SDK's own ``entity_model_to_api_schema`` / ``edge_model_to_api_schema``, so the
stored JSON is exactly what Cloud would have been sent::

    {"entity_types": [{"name", "description", "properties": [{"name", "type", "description"}]}],
     "edge_types":   [{"name", "description", "properties": [...],
                       "source_targets": [{"source", "target"}]}]}

``OntologyView`` wraps that JSON for extraction: entity/edge type matching,
allowed source/target pairs, attribute names and prompt rendering.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from zep_cloud.external_clients.ontology import (
    EdgeModel,
    EntityModel,
    edge_model_to_api_schema,
    entity_model_to_api_schema,
)
from zep_cloud.types import SuccessResponse

from .errors import bad_request, not_found
from .textnorm import DEFAULT_RELATION_NAME, to_upper_snake, utcnow_iso

logger = logging.getLogger("mirofish.memory.ontology")

__all__ = [
    "GENERIC_ENTITY",
    "EdgeTypeMatch",
    "OntologyView",
    "apply_set_ontology",
    "capture_ontology",
    "load_ontology",
]

GENERIC_ENTITY = "Entity"
PROMPT_MAX_TYPES = 10
_TYPE_KEY_RE = re.compile(r"[\s_\-]+")


# ---------------------------------------------------------------------------
# Capture (set_ontology input -> canonical JSON)
# ---------------------------------------------------------------------------


def _is_model_class(value: Any, base: type) -> bool:
    return isinstance(value, type) and issubclass(value, base)


def _clean_properties(properties: Any) -> list[dict[str, str]]:
    cleaned: list[dict[str, str]] = []
    if not isinstance(properties, list):
        return cleaned
    for prop in properties:
        if not isinstance(prop, Mapping):
            continue
        name = prop.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        cleaned.append({
            "name": name,
            "type": str(prop.get("type") or "Text"),
            "description": str(prop.get("description") or ""),
        })
    return cleaned


def _schema_from_dict(name: str, value: Mapping[str, Any]) -> dict[str, Any]:
    """Lenient path: an already-converted ``{"name","description","properties"}`` dict."""

    schema_name = value.get("name", name)
    if not isinstance(schema_name, str) or not schema_name.strip():
        schema_name = name
    description = value.get("description")
    return {
        "name": schema_name,
        "description": description.strip() if isinstance(description, str) else "",
        "properties": _clean_properties(value.get("properties", [])),
    }


def _source_target_pair(value: Any) -> dict[str, str] | None:
    if isinstance(value, Mapping):
        source, target = value.get("source"), value.get("target")
    elif hasattr(value, "source") or hasattr(value, "target"):
        source, target = getattr(value, "source", None), getattr(value, "target", None)
    else:
        return None
    return {
        "source": source if isinstance(source, str) and source.strip() else GENERIC_ENTITY,
        "target": target if isinstance(target, str) and target.strip() else GENERIC_ENTITY,
    }


def _check_type_name(name: Any, what: str) -> str:
    if not isinstance(name, str) or not name.strip():
        raise bad_request(f"{what} names must be non-empty strings")
    return name


def _convert(converter: Any, model: type, name: str, what: str) -> dict[str, Any]:
    try:
        return converter(model, name)
    except ValueError:
        # e.g. "Unsupported property type" from the SDK converter.
        raise bad_request(f"{what} {name!r} has an unsupported property type") from None


def capture_ontology(entities: Any, edges: Any = None) -> dict[str, Any]:
    """Convert ``set_ontology`` arguments to the canonical stored JSON.

    ``entities`` must be a dict (``{}`` is allowed for an edge-only ontology).
    Each value is an ``EntityModel`` subclass, or a dict already in API form.
    Each ``edges`` value is an ``EdgeModel`` subclass, a
    ``(EdgeModel, [EntityEdgeSourceTarget | dict, ...])`` pair, or a dict in
    API form (optionally with ``source_targets``). A bare model gets
    ``source_targets == []``, meaning any pair. Invalid shapes raise
    ``BadRequestError``.
    """

    if not isinstance(entities, Mapping):
        raise bad_request("entities must be a dict of entity types")
    if edges is not None and not isinstance(edges, Mapping):
        raise bad_request("edges must be a dict of edge types")

    entity_types: list[dict[str, Any]] = []
    for name, value in entities.items():
        name = _check_type_name(name, "entity type")
        if _is_model_class(value, EntityModel):
            schema = _convert(entity_model_to_api_schema, value, name, "entity type")
        elif isinstance(value, Mapping):
            schema = _schema_from_dict(name, value)
        else:
            raise bad_request(f"entity type {name!r} must be an EntityModel subclass")
        entity_types.append(schema)

    edge_types: list[dict[str, Any]] = []
    for name, value in (edges or {}).items():
        name = _check_type_name(name, "edge type")
        pairs_source: Iterable[Any] = ()
        model: Any = value
        if isinstance(value, (tuple, list)):
            if len(value) != 2:
                raise bad_request(f"edge type {name!r} must be (EdgeModel, [source targets])")
            model, pairs_source = value
            if pairs_source is None:
                pairs_source = ()
            if not isinstance(pairs_source, (list, tuple)):
                raise bad_request(f"edge type {name!r} source targets must be a list")
        if _is_model_class(model, EdgeModel):
            schema = _convert(edge_model_to_api_schema, model, name, "edge type")
        elif isinstance(model, Mapping):
            schema = _schema_from_dict(name, model)
            if not pairs_source:
                pairs_source = model.get("source_targets") or ()
        else:
            raise bad_request(f"edge type {name!r} must be an EdgeModel subclass")
        pairs: list[dict[str, str]] = []
        for item in pairs_source:
            pair = _source_target_pair(item)
            if pair is None:
                raise bad_request(f"edge type {name!r} has an invalid source target")
            pairs.append(pair)
        schema["source_targets"] = pairs
        edge_types.append(schema)

    return {"entity_types": entity_types, "edge_types": edge_types}


def apply_set_ontology(
    store: Any,
    entities: Any,
    edges: Any = None,
    user_ids: Sequence[str] | None = None,
    graph_ids: Sequence[str] | None = None,
) -> SuccessResponse:
    """Persist an ontology (``graph.set_ontology`` semantics).

    With ``graph_ids``, every listed graph must exist (else ``NotFoundError``)
    and each one's ontology is replaced. With neither ``graph_ids`` nor
    ``user_ids``, the project default is replaced; it applies to graphs that
    have no ontology of their own. ``user_ids`` are not supported.
    """

    if user_ids:
        raise bad_request("user ontologies are not supported by the local memory backend")
    if graph_ids is not None and (
        isinstance(graph_ids, str) or not isinstance(graph_ids, (list, tuple))
    ):
        raise bad_request("graph_ids must be a list of graph ids")
    canonical = capture_ontology(entities, edges)
    payload = json.dumps(canonical, ensure_ascii=False, separators=(",", ":"))
    now = utcnow_iso()
    targets = list(dict.fromkeys(graph_ids or []))

    with store.write() as conn:
        if targets:
            for graph_id in targets:
                if not isinstance(graph_id, str) or not graph_id:
                    raise bad_request("graph_ids must be non-empty strings")
                exists = conn.execute(
                    "SELECT 1 FROM graphs WHERE graph_id = ?", (graph_id,)
                ).fetchone()
                if exists is None:
                    raise not_found(f"graph not found: {graph_id}")
            conn.executemany(
                "UPDATE graphs SET ontology_json = ?, ontology_updated_at = ? WHERE graph_id = ?",
                [(payload, now, graph_id) for graph_id in targets],
            )
        else:
            conn.execute(
                "INSERT INTO default_ontology(id, ontology_json, updated_at) VALUES (1, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET ontology_json = excluded.ontology_json, "
                "updated_at = excluded.updated_at",
                (payload, now),
            )
    logger.info(
        "Ontology stored for %s: %d entity types, %d edge types",
        ",".join(targets) if targets else "project default",
        len(canonical["entity_types"]),
        len(canonical["edge_types"]),
    )
    return SuccessResponse(message="Ontology set successfully")


def load_ontology(conn: sqlite3.Connection, graph_id: str) -> "OntologyView":
    """The graph's own ontology, else the project default, else an empty view."""

    row = conn.execute("SELECT ontology_json FROM graphs WHERE graph_id = ?", (graph_id,)).fetchone()
    if row is not None and row[0]:
        return OntologyView.from_json(row[0])
    default = conn.execute("SELECT ontology_json FROM default_ontology WHERE id = 1").fetchone()
    if default is not None and default[0]:
        return OntologyView.from_json(default[0])
    return OntologyView(None)


# ---------------------------------------------------------------------------
# View
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EdgeTypeMatch:
    """Result of mapping an extracted relation onto the ontology.

    ``definition`` is the ontology edge type (``None`` for free-form names).
    ``swap`` means the relation only fits with source and target reversed.
    """

    name: str
    definition: Mapping[str, Any] | None
    swap: bool = False


def _type_key(name: str) -> str:
    return _TYPE_KEY_RE.sub("", name).casefold()


class OntologyView:
    """Read-only helper over the canonical ontology JSON."""

    def __init__(self, data: Mapping[str, Any] | None) -> None:
        data = data if isinstance(data, Mapping) else {}
        self.entity_types: list[dict[str, Any]] = [
            dict(item) for item in data.get("entity_types", []) or []
            if isinstance(item, Mapping) and isinstance(item.get("name"), str) and item.get("name")
        ]
        self.edge_types: list[dict[str, Any]] = [
            dict(item) for item in data.get("edge_types", []) or []
            if isinstance(item, Mapping) and isinstance(item.get("name"), str) and item.get("name")
        ]
        self._entities_by_key = {}
        for item in self.entity_types:
            self._entities_by_key.setdefault(_type_key(item["name"]), item)
        self._edges_by_name = {}
        for item in self.edge_types:
            self._edges_by_name.setdefault(to_upper_snake(item["name"]), item)

    @classmethod
    def from_json(cls, text: str | None) -> "OntologyView":
        if not text:
            return cls(None)
        try:
            data = json.loads(text)
        except (TypeError, ValueError):
            logger.warning("Ignoring an unreadable stored ontology")
            return cls(None)
        return cls(data if isinstance(data, Mapping) else None)

    def to_dict(self) -> dict[str, Any]:
        return {"entity_types": list(self.entity_types), "edge_types": list(self.edge_types)}

    @property
    def is_empty(self) -> bool:
        return not self.entity_types and not self.edge_types

    @property
    def entity_type_names(self) -> list[str]:
        return [item["name"] for item in self.entity_types]

    @property
    def edge_type_names(self) -> list[str]:
        return [item["name"] for item in self.edge_types]

    # -- entities -----------------------------------------------------------

    def match_entity_type(self, raw: Any) -> str | None:
        """Canonical entity type name, or ``None`` for generic/unknown types.

        Matching ignores case, spaces, ``_`` and ``-``. ``"Entity"`` and empty
        values are generic.
        """

        if not isinstance(raw, str):
            return None
        key = _type_key(raw.strip())
        if not key or key == _type_key(GENERIC_ENTITY):
            return None
        item = self._entities_by_key.get(key)
        return item["name"] if item else None

    def entity_definition(self, entity_type: str | None) -> Mapping[str, Any] | None:
        if not entity_type:
            return None
        return self._entities_by_key.get(_type_key(entity_type))

    def entity_attribute_names(self, entity_type: str | None) -> list[str]:
        definition = self.entity_definition(entity_type)
        return _property_names(definition)

    # -- edges --------------------------------------------------------------

    def edge_definition(self, name: str | None) -> Mapping[str, Any] | None:
        if not name:
            return None
        return self._edges_by_name.get(to_upper_snake(name))

    def edge_attribute_names(self, name: str | None) -> list[str]:
        return _property_names(self.edge_definition(name))

    @staticmethod
    def allowed(definition: Mapping[str, Any], source_type: str | None,
                target_type: str | None) -> bool:
        """Whether an edge type admits ``source_type -> target_type``.

        A pair ``(s, t)`` allows the edge when ``s`` is ``"Entity"`` or the
        source type and ``t`` is ``"Entity"`` or the target type. A generic
        node (type ``None``) matches only ``"Entity"``. An empty list allows
        any pair.
        """

        pairs = definition.get("source_targets") or []
        if not pairs:
            return True
        source_ok = {GENERIC_ENTITY} | ({source_type} if source_type else set())
        target_ok = {GENERIC_ENTITY} | ({target_type} if target_type else set())
        for pair in pairs:
            if not isinstance(pair, Mapping):
                continue
            source = pair.get("source") or GENERIC_ENTITY
            target = pair.get("target") or GENERIC_ENTITY
            if source in source_ok and target in target_ok:
                return True
        return False

    def match_edge_type(self, raw: Any, source_type: str | None, target_type: str | None,
                        *, strict: bool = False) -> EdgeTypeMatch | None:
        """Map an extracted relation name onto the ontology (spec §4.7).

        - An ontology edge type whose pair is allowed keeps its name.
        - If only the reversed pair is allowed, ``swap`` is true.
        - If neither direction is allowed, the relation becomes ``RELATES_TO``.
        - A name outside the ontology stays free-form (as Zep keeps it), or is
          dropped (``None``) when ``strict`` is true.
        """

        name = to_upper_snake(raw)
        definition = self._edges_by_name.get(name)
        if definition is not None:
            canonical = definition["name"]
            if self.allowed(definition, source_type, target_type):
                return EdgeTypeMatch(canonical, definition, False)
            if self.allowed(definition, target_type, source_type):
                return EdgeTypeMatch(canonical, definition, True)
            logger.debug(
                "Relation %s not allowed for %s -> %s; using %s",
                canonical, source_type or GENERIC_ENTITY, target_type or GENERIC_ENTITY,
                DEFAULT_RELATION_NAME,
            )
            if strict:
                return None
            return EdgeTypeMatch(DEFAULT_RELATION_NAME, None, False)
        if strict:
            return None
        return EdgeTypeMatch(name, None, False)

    # -- prompt rendering ---------------------------------------------------------

    def render_entity_types(self, max_types: int = PROMPT_MAX_TYPES) -> str:
        """``ENTITY TYPES:`` block for the extraction prompt (spec §4.4)."""

        if not self.entity_types:
            return 'ENTITY TYPES: (none, use "Entity")'
        lines = ["ENTITY TYPES:"]
        for item in self.entity_types[:max_types]:
            line = f"- {item['name']}: {_one_line(item.get('description'))}"
            attributes = _render_properties(item)
            if attributes:
                line += f" Attributes: {attributes}"
            lines.append(line.rstrip())
        return "\n".join(lines)

    def render_relation_types(self, max_types: int = PROMPT_MAX_TYPES) -> str:
        """``RELATION TYPES:`` block for the extraction prompt (spec §4.4)."""

        if not self.edge_types:
            return "RELATION TYPES: (none, use free-form)"
        lines = ["RELATION TYPES:"]
        for item in self.edge_types[:max_types]:
            line = f"- {item['name']}: {_one_line(item.get('description'))}"
            pairs = [
                f"{pair.get('source') or GENERIC_ENTITY} -> {pair.get('target') or GENERIC_ENTITY}"
                for pair in item.get("source_targets") or []
                if isinstance(pair, Mapping)
            ]
            line += f" Allowed: {', '.join(pairs) if pairs else 'Entity -> Entity'}."
            attributes = _render_properties(item)
            if attributes:
                line += f" Attributes: {attributes}"
            lines.append(line.rstrip())
        return "\n".join(lines)


def _property_names(definition: Mapping[str, Any] | None) -> list[str]:
    if not definition:
        return []
    return [
        prop["name"] for prop in definition.get("properties") or []
        if isinstance(prop, Mapping) and isinstance(prop.get("name"), str) and prop["name"]
    ]


def _one_line(text: Any, limit: int = 200) -> str:
    if not isinstance(text, str):
        return ""
    value = " ".join(text.split())
    return value if len(value) <= limit else value[: limit - 3].rstrip() + "..."


def _render_properties(definition: Mapping[str, Any]) -> str:
    parts = []
    for prop in definition.get("properties") or []:
        if not isinstance(prop, Mapping) or not prop.get("name"):
            continue
        description = _one_line(prop.get("description"), 80)
        parts.append(f"{prop['name']} ({description})" if description else str(prop["name"]))
    return ", ".join(parts)
