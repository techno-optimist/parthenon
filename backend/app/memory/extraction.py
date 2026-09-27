"""Document extraction for the local memory backend (spec §4.2, §4.4, §4.5, §4.8, §4.9).

The pieces the ingestion worker calls:

- :func:`claim_window` / :func:`pack_window`: claim the next window of queued
  document episodes under a lease (one write transaction).
- :func:`process_window`: build the prompt from a read snapshot, make one LLM
  call with no lock held, validate the JSON and commit nodes, edges, links,
  invalidations and episode/item states in one write transaction. Bad output
  splits the window in halves; fatal LLM conditions abort the batch.
- :func:`extract_next_window`: claim plus process (``drain()`` helper).
- :class:`ExtractionLLM`: the throttled, retrying LLM wrapper shared by
  document windows, activity enrichment and the dedup pass.
- :func:`run_dedup_pass`: the post-batch entity merge pass.

Only this module imports ``app.utils.llm_client``, and only lazily, so
search-only use of the backend works without ``LLM_API_KEY``.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .activity import activity_language, written_in
from .models import json_dumps, json_loads
from .ontology import OntologyView, load_ontology
from .resolution import (
    DEDUP_MAX_PAIRS,
    CandidatePair,
    WriteStats,
    find_dedup_candidates,
    group_confirmed_pairs,
    load_dedup_nodes,
    merge_nodes,
    write_extraction,
)
from .settings import LocalMemorySettings
from .store import MemoryStore, new_id
from .textnorm import (
    compact_with_boundaries,
    is_cjk,
    is_word_char,
    parse_iso_datetime,
    to_upper_snake,
    truncate,
    utcnow_iso,
)

logger = logging.getLogger("mirofish.memory.extraction")

__all__ = [
    "DEDUP_SYSTEM_PROMPT",
    "DOCUMENT_SYSTEM_PROMPT",
    "document_system_prompt",
    "FATAL_ERROR_CODES",
    "RETURN_SHAPE",
    "UNKNOWN_REFERENCE_TIME",
    "BadOutputError",
    "CommitOutcome",
    "DedupPassResult",
    "ExistingFact",
    "ExtractedEntity",
    "ExtractedRelation",
    "ExtractionError",
    "ExtractionLLM",
    "ExtractionResult",
    "FatalLLMError",
    "InvalidatedFact",
    "KnownEntity",
    "LLMErrorInfo",
    "PromptContext",
    "Throttle",
    "Window",
    "WindowEpisode",
    "WindowFailedError",
    "WindowResult",
    "abort_batch",
    "build_dedup_messages",
    "build_document_messages",
    "build_document_prompt",
    "cancel_window",
    "claim_window",
    "classify_llm_error",
    "commit_window",
    "default_llm_factory",
    "display_time",
    "extract_next_window",
    "fail_window",
    "find_existing_facts",
    "find_known_entities",
    "gather_prompt_context",
    "is_placeholder_value",
    "pack_window",
    "parse_dedup_decisions",
    "parse_extraction",
    "process_window",
    "record_usage",
    "render_window_text",
    "run_dedup_pass",
    "select_window_rows",
    "strip_overlap",
]

# ---------------------------------------------------------------------------
# Limits (spec §4.5)
# ---------------------------------------------------------------------------

MAX_NAME_CHARS = 200
MAX_FACT_CHARS = 1000
MAX_SUMMARY_CHARS = 600
MAX_ATTRIBUTE_VALUE_CHARS = 300
MAX_ATTRIBUTE_KEY_CHARS = 100
MAX_ALIASES = 5
MAX_TIME_CHARS = 64
# Placeholder attribute values that models write despite "omit unknown values".
# Compared after :func:`_placeholder_key` (casefolded, whitespace collapsed,
# wrapping brackets/quotes and trailing periods removed).
EMPTY_ATTRIBUTE_VALUES = frozenset({
    "unknown", "n/a", "n.a", "none", "null", "nil", "-", "--", "—", "–", "?",
    "not specified", "not mentioned", "unspecified", "not stated", "not given", "not provided",
    "not available", "not applicable", "not known",
    "未知", "未提及", "不详", "无", "暂无", "未说明", "未提供", "不明", "未明确",
})
_PLACEHOLDER_STRIP = " \t\r\n.。()（）[]【】<>\"'“”‘’"
# "Not mentioned in the text", "文中未提及" and similar longer forms.
_PLACEHOLDER_RE = re.compile(
    r"(?:not (?:specified|mentioned|stated|given|provided|available|known|indicated|disclosed)"
    r"|unspecified|unknown)(?: (?:in|by) (?:the )?(?:text|source|document|passage|context))?"
    r"|(?:文中|原文中?)(?:未提及|未说明|未提供|未明确|没有提及|不详)"
)

CANDIDATE_LIMIT = 64
OVERLAP_MIN_CHARS = 20
OVERLAP_MAX_CHARS = 400
PROMPT_FACT_CHARS = 300
DEDUP_PAIRS_PER_CALL = 40
DEDUP_SUMMARY_CHARS = 160
LOG_PREVIEW_CHARS = 500
_IN_CHUNK = 500

# Error codes that stop a batch at once (spec §4.9).
FATAL_ERROR_CODES = frozenset({"llm_quota_exhausted", "llm_auth", "llm_not_configured"})
AUTH_BRIDGE_CODES = frozenset({"grok_not_signed_in", "openrouter_key_missing", "grok_refresh_unavailable"})
DAILY_LIMIT_BRIDGE_CODES = frozenset({"openrouter_daily_limit"})
BAD_REQUEST_STATUSES = frozenset({400, 413, 422})
MAX_RETRY_DELAY_SECONDS = 120.0
TRANSIENT_RETRY_DELAYS = (5.0, 15.0, 45.0)

_ACTIVE_ITEM_STATUSES = ("pending", "queued", "processing")
# Batches a fatal abort may still change; terminal batches are left as they are.
_RUNNING_BATCH_STATUSES = ("queued", "processing")


# ---------------------------------------------------------------------------
# Prompts (spec §4.4)
# ---------------------------------------------------------------------------

DOCUMENT_SYSTEM_PROMPT = """You are a knowledge-graph extraction engine. Read the TEXT and return ONLY one JSON object
describing the entities and relationships it states.

Rules:
1. Extract only entities explicitly mentioned in TEXT. Never invent entities, facts or dates.
2. "type": exactly one name from ENTITY TYPES when the entity clearly fits it, otherwise "Entity".
3. "name": the most complete proper name used in TEXT. If the entity appears in KNOWN ENTITIES,
   use that exact name. Put other spellings, abbreviations and short forms in "aliases".
4. "summary": 1-2 sentences about the entity based only on TEXT, in the language of TEXT.
5. "attributes": only keys listed for that entity type, string values, omit unknown values.
6. Every relation has "source" and "target": the exact "name" of two entities from your
   "entities" list. Use exactly these keys (not subject/object or head/tail).
   "type": a RELATION TYPES name when it fits AND the source->target type pair is allowed;
   otherwise a short English UPPER_SNAKE_CASE verb phrase (e.g. MEMBER_OF, CRITICIZES).
7. "fact": one self-contained sentence stating the relation and naming both entities,
   in the language of TEXT.
8. "valid_at" / "invalid_at": ISO 8601 date or datetime only when TEXT says when the relation
   started / ended; otherwise null. Resolve a relative date ("five years ago") only against an
   absolute date stated in TEXT or a known REFERENCE TIME; if neither exists, use null.
   Use null for BC dates (ISO 8601 cannot express them here).
9. "chunks": the numbers of the [chunk N] or [episode N] markers the relation comes from.
10. "invalidated_facts": ids from EXISTING FACTS that TEXT explicitly contradicts or reports as
    ended or replaced, with "invalid_at" when TEXT says when (same date rules as 8).
    Leave empty when unsure.
11. At most {max_entities} entities and {max_relations} relations; keep the most important.
12. Output JSON only. No markdown, no commentary."""

# A concrete one-item example: models that only see "[...]" invent their own
# keys (subject/object, head/tail) for relation endpoints. The fact id is a
# placeholder that never parses, so a copied example invalidates nothing.
RETURN_SHAPE = (
    'Return: {"entities":[{"name":"...","type":"...","aliases":[],"summary":"...","attributes":{}}],'
    '"relations":[{"source":"<entity name>","target":"<entity name>","type":"UPPER_SNAKE","fact":"...",'
    '"valid_at":null,"invalid_at":null,"chunks":[0]}],'
    '"invalidated_facts":[{"id":"F<n>","invalid_at":null}]}'
)

UNKNOWN_REFERENCE_TIME = "unknown (the text may describe another era)"

DEDUP_SYSTEM_PROMPT = (
    "Decide whether each pair names the same real-world entity. Return JSON "
    '{"decisions":[{"pair":"P1","same_entity":true}]}. Say false when unsure.'
)


def display_time(value: Any) -> str:
    """Stored timestamp as ``YYYY-MM-DDTHH:MM:SSZ`` for prompts ('' if unparsable)."""

    normalized = parse_iso_datetime(value)
    if not normalized:
        return ""
    return normalized[:19] + "Z"


def _display_date(value: Any) -> str:
    """Like :func:`display_time`, but a midnight instant shows as a plain date."""

    shown = display_time(value)
    return shown[:10] if shown.endswith("T00:00:00Z") else shown


def _llm_response_error() -> type[Exception]:
    from ..utils.llm_client import LLMResponseError  # lazy: keeps LLM imports optional

    return LLMResponseError


# ---------------------------------------------------------------------------
# Output validation (spec §4.5)
# ---------------------------------------------------------------------------


def _text(value: Any) -> str | None:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return None


def _first_present(data: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = data.get(key)
        if value is not None and value != "":
            return value
    return None


def _placeholder_key(text: str) -> str:
    return " ".join(text.casefold().split()).strip(_PLACEHOLDER_STRIP)


def is_placeholder_value(value: Any) -> bool:
    """True for an empty or placeholder value ("Not specified", "null", "未提及", ...).

    Such values carry no information; kept, a later window's placeholder
    would overwrite a real value from an earlier window (attributes merge
    with recency winning).
    """

    if value is None:
        return True
    if not isinstance(value, str):
        return False
    key = _placeholder_key(value)
    return not key or key in EMPTY_ATTRIBUTE_VALUES or _PLACEHOLDER_RE.fullmatch(key) is not None


def _attribute_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        text = "true" if value else "false"
    elif isinstance(value, (int, float)):
        text = str(value)
    elif isinstance(value, str):
        text = value.strip()
    elif isinstance(value, (list, tuple)):
        items = (str(item).strip() for item in value if item is not None)
        text = ", ".join(item for item in items if not is_placeholder_value(item))
    elif isinstance(value, Mapping):
        text = json_dumps(value)
    else:
        text = str(value).strip()
    if is_placeholder_value(text):
        return None
    return text[:MAX_ATTRIBUTE_VALUE_CHARS]


def _attributes(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, str] = {}
    for key, raw in value.items():
        if not isinstance(key, str) or not key.strip():
            continue
        text = _attribute_value(raw)
        if text is not None:
            result[key.strip()[:MAX_ATTRIBUTE_KEY_CHARS]] = text
    return result


# ISO 8601 writes a year before 1000 zero-padded ("0399"), and models write BC
# years that way too, which would store a wrong AD date on an ancient event.
# Such dates, and anything marked BC/BCE, are dropped as ambiguous.
_AMBIGUOUS_YEAR_RE = re.compile(r"^[+-]?0\d{3}(?!\d)|\bb\.?\s?c\.?(?:\s?e\.?)?(?![a-z])|公元前", re.IGNORECASE)


def _time_text(value: Any) -> str | None:
    text = _text(value)
    if not text or _AMBIGUOUS_YEAR_RE.search(text):
        return None
    return text[:MAX_TIME_CHARS]


_CHUNK_NUMBER_RE = re.compile(r"-?\d+")


def _chunk_numbers(value: Any) -> list[int]:
    items = value if isinstance(value, (list, tuple)) else [value]
    numbers: list[int] = []
    for item in items:
        if isinstance(item, bool):
            continue
        if isinstance(item, int):
            number = item
        elif isinstance(item, float) and item.is_integer():
            number = int(item)
        elif isinstance(item, str):
            match = _CHUNK_NUMBER_RE.search(item)
            if not match:
                continue
            number = int(match.group(0))
        else:
            continue
        if number not in numbers:
            numbers.append(number)
    return numbers


class ExtractedEntity(BaseModel):
    """One entity from the LLM. Invalid entries are dropped individually."""

    model_config = ConfigDict(extra="ignore")

    name: str = Field(min_length=1)
    type: Optional[str] = None
    aliases: list[str] = Field(default_factory=list)
    summary: str = ""
    attributes: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = {"name": value}
        if not isinstance(value, Mapping):
            raise ValueError("entity must be an object")
        name = truncate(_text(value.get("name")) or "", MAX_NAME_CHARS)
        entity_type = _text(_first_present(value, "type", "entity_type"))
        raw_aliases = value.get("aliases")
        if isinstance(raw_aliases, str):
            raw_aliases = [raw_aliases]
        aliases: list[str] = []
        for alias in raw_aliases if isinstance(raw_aliases, (list, tuple)) else []:
            text = truncate(_text(alias) or "", MAX_NAME_CHARS)
            if text and text != name and text not in aliases:
                aliases.append(text)
            if len(aliases) >= MAX_ALIASES:
                break
        return {
            "name": name,
            "type": entity_type or None,
            "aliases": aliases,
            "summary": truncate(_text(value.get("summary")) or "", MAX_SUMMARY_CHARS),
            "attributes": _attributes(value.get("attributes")),
        }


# Keys models use for relation endpoints, in order of preference.
SOURCE_KEYS = ("source", "from", "subject", "head", "source_entity", "source_name", "source_node")
TARGET_KEYS = ("target", "to", "object", "tail", "target_entity", "target_name", "target_node")
RELATION_TYPE_KEYS = ("type", "relation", "relation_type", "label", "predicate", "relationship")
FACT_KEYS = ("fact", "description", "statement", "sentence")


def _endpoint(value: Any) -> str:
    """An endpoint name: a string, or an object carrying ``name``."""

    if isinstance(value, Mapping):
        value = value.get("name")
    return truncate(_text(value) or "", MAX_NAME_CHARS)


def _synthesized_fact(source: str, relation_type: str, target: str) -> str:
    """``"Alice works for Acme."`` for a typed relation the model gave without a fact."""

    if re.search(r"[A-Za-z]", relation_type):
        phrase = to_upper_snake(relation_type).replace("_", " ").lower()
    elif is_cjk(relation_type):
        phrase = relation_type
    else:
        phrase = "relates to"
    return f"{source} {phrase} {target}."


class ExtractedRelation(BaseModel):
    """One relation from the LLM, with key synonyms accepted.

    Endpoints may come as ``source``/``target`` or a common synonym pair
    (``from``/``to``, ``subject``/``object``, ``head``/``tail``, ...). A
    relation with both endpoints and a type but no fact gets a plain
    synthesized fact instead of being dropped; one with neither a type nor
    a fact states nothing and is dropped.
    """

    model_config = ConfigDict(extra="ignore")

    source: str = Field(min_length=1)
    target: str = Field(min_length=1)
    type: str = ""
    fact: str = Field(min_length=1)
    valid_at: Optional[str] = None
    invalid_at: Optional[str] = None
    chunks: list[int] = Field(default_factory=list)
    attributes: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, value: Any) -> Any:
        if not isinstance(value, Mapping):
            raise ValueError("relation must be an object")
        relation_type = _text(_first_present(value, *RELATION_TYPE_KEYS))
        if not relation_type and isinstance(value.get("name"), str):
            relation_type = value["name"].strip()
        relation_type = truncate(relation_type or "", MAX_NAME_CHARS)
        source = _endpoint(_first_present(value, *SOURCE_KEYS))
        target = _endpoint(_first_present(value, *TARGET_KEYS))
        fact = _text(_first_present(value, *FACT_KEYS)) or ""
        if not fact and source and target and relation_type:
            fact = _synthesized_fact(source, relation_type, target)
        return {
            "source": source,
            "target": target,
            "type": relation_type,
            "fact": truncate(fact, MAX_FACT_CHARS),
            "valid_at": _time_text(value.get("valid_at")),
            "invalid_at": _time_text(value.get("invalid_at")),
            "chunks": _chunk_numbers(value.get("chunks") if value.get("chunks") is not None else []),
            "attributes": _attributes(value.get("attributes")),
        }


_FACT_ID_RE = re.compile(r"^\s*f?\s*(\d+)\s*$", re.IGNORECASE)


def _fact_id(value: Any) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return f"F{value}"
    if isinstance(value, str):
        match = _FACT_ID_RE.match(value)
        return f"F{int(match.group(1))}" if match else None
    return None


class InvalidatedFact(BaseModel):
    """An ``EXISTING FACTS`` id the text contradicts, normalized to ``F<n>``."""

    model_config = ConfigDict(extra="ignore")

    id: str
    invalid_at: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, value: Any) -> Any:
        if isinstance(value, Mapping):
            fact_id = _fact_id(_first_present(value, "id", "fact_id", "fact"))
            invalid_at = _time_text(value.get("invalid_at"))
        else:
            fact_id, invalid_at = _fact_id(value), None
        if fact_id is None:
            raise ValueError("invalidated fact needs an id like F1")
        return {"id": fact_id, "invalid_at": invalid_at}


class ExtractionResult(BaseModel):
    """Validated extraction output for one window."""

    model_config = ConfigDict(extra="ignore")

    entities: list[ExtractedEntity] = Field(default_factory=list)
    relations: list[ExtractedRelation] = Field(default_factory=list)
    invalidated_facts: list[InvalidatedFact] = Field(default_factory=list)
    dropped: int = 0  # entries discarded as invalid or over the caps


def _list_under(data: Mapping[str, Any], *keys: str) -> list[Any] | None:
    for key in keys:
        value = data.get(key)
        if isinstance(value, list):
            return value
    return None


def _validated(model: type[BaseModel], items: Iterable[Any]) -> tuple[list[Any], int]:
    kept: list[Any] = []
    dropped = 0
    for item in items:
        try:
            kept.append(model.model_validate(item))
        except ValidationError:
            dropped += 1
    return kept, dropped


_LOGGABLE_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,39}$")


def _relation_keys_hint(items: Sequence[Any]) -> str:
    """The keys the dropped relations used (identifier-like keys only, no values)."""

    keys = sorted({key for item in items if isinstance(item, Mapping)
                   for key in item if isinstance(key, str) and _LOGGABLE_KEY_RE.match(key)})
    return ", ".join(keys[:12]) or "none"


def parse_extraction(raw: Any, *, max_entities: int = 30, max_relations: int = 50,
                     label: str = "Extraction response") -> ExtractionResult:
    """Validate the LLM's JSON leniently (spec §4.5).

    Accepts ``nodes`` for ``entities`` and ``edges`` / ``relationships`` for
    ``relations``, and the endpoint synonyms of :class:`ExtractedRelation`.
    Bad entries are dropped one by one; the lists are cut to the caps. When
    the response has relations but every one of them is invalid, a WARNING
    names the keys they used (``label`` identifies the call in that log).
    Raises ``LLMResponseError`` when neither list is present, which the
    caller treats as bad output (split or fail).
    """

    error_class = _llm_response_error()
    if not isinstance(raw, Mapping):
        raise error_class("extraction JSON must be an object")
    entities_raw = _list_under(raw, "entities", "nodes")
    relations_raw = _list_under(raw, "relations", "edges", "relationships")
    if entities_raw is None and relations_raw is None:
        raise error_class("extraction JSON missing entities/relations")
    invalidated_raw = raw.get("invalidated_facts")
    if not isinstance(invalidated_raw, list):
        invalidated_raw = []

    entities, dropped_entities = _validated(ExtractedEntity, entities_raw or [])
    relations, dropped_relations = _validated(ExtractedRelation, relations_raw or [])
    if relations_raw and not relations:
        logger.warning(
            "%s: all %d relations were invalid and dropped (relation keys used: %s)",
            label, len(relations_raw), _relation_keys_hint(relations_raw),
        )
    invalidated, _ = _validated(InvalidatedFact, invalidated_raw)
    dropped = dropped_entities + dropped_relations
    dropped += max(0, len(entities) - max_entities) + max(0, len(relations) - max_relations)
    unique_invalidated = list({item.id: item for item in invalidated}.values())
    return ExtractionResult(
        entities=entities[:max_entities],
        relations=relations[:max_relations],
        invalidated_facts=unique_invalidated,
        dropped=dropped,
    )


# ---------------------------------------------------------------------------
# Windows (spec §4.2)
# ---------------------------------------------------------------------------


def _stated_language(metadata_json: Any) -> str | None:
    """The record language an episode's metadata states ("language"), or None."""

    metadata = json_loads(metadata_json, {})
    return activity_language(metadata.get("language")) if isinstance(metadata, dict) else None


@dataclass(frozen=True)
class WindowEpisode:
    """A claimed document episode as the extraction step sees it."""

    id: int
    uuid: str
    graph_id: str
    batch_id: str | None
    sequence_index: int | None
    content: str
    reference_time: str
    reference_time_explicit: bool
    strict_ontology: bool
    chunk: int
    # The gathering's record language, when the sender stated it in the
    # episode's metadata ("language": "en" or "zh").
    language: str | None = None

    @property
    def marker_kind(self) -> str:
        return "chunk" if self.batch_id is not None else "episode"


@dataclass(frozen=True)
class Window:
    """Consecutive episodes of one graph and batch, extracted with one LLM call."""

    window_id: str
    graph_id: str
    batch_id: str | None
    episodes: tuple[WindowEpisode, ...]
    owner: str | None = None
    lease_until: float | None = None

    @property
    def episode_uuids(self) -> list[str]:
        return [episode.uuid for episode in self.episodes]

    @property
    def strict(self) -> bool:
        return any(episode.strict_ontology for episode in self.episodes)

    @property
    def explicit_reference_time(self) -> str | None:
        times = [e.reference_time for e in self.episodes if e.reference_time_explicit and e.reference_time]
        return max(times) if times else None

    @property
    def language(self) -> str | None:
        """The record language its episodes state, when they state one and agree on it."""

        stated = {episode.language for episode in self.episodes if episode.language}
        return stated.pop() if len(stated) == 1 else None

    @property
    def reference_time(self) -> str:
        explicit = self.explicit_reference_time
        if explicit:
            return explicit
        times = [e.reference_time for e in self.episodes if e.reference_time]
        return max(times) if times else utcnow_iso()

    @property
    def text(self) -> str:
        return render_window_text(self.episodes)

    @property
    def chunk_map(self) -> dict[int, str]:
        return {episode.chunk: episode.uuid for episode in self.episodes}

    @property
    def chars(self) -> int:
        return sum(len(episode.content) for episode in self.episodes)

    def split(self) -> tuple["Window", "Window"]:
        """Two halves with fresh window ids (used after bad LLM output)."""

        if len(self.episodes) < 2:
            raise ValueError("a single-episode window cannot be split")
        middle = (len(self.episodes) + 1) // 2
        return (
            Window(new_id(), self.graph_id, self.batch_id, self.episodes[:middle], self.owner, self.lease_until),
            Window(new_id(), self.graph_id, self.batch_id, self.episodes[middle:], self.owner, self.lease_until),
        )


def strip_overlap(previous: str, current: str, *, min_chars: int = OVERLAP_MIN_CHARS,
                  max_chars: int = OVERLAP_MAX_CHARS) -> str:
    """Drop the chunker's overlap from the start of ``current``.

    Finds the largest ``k`` in ``[min_chars, min(max_chars, len(previous),
    len(current))]`` with ``previous.endswith(current[:k])``.
    """

    upper = min(max_chars, len(previous), len(current))
    for k in range(upper, min_chars - 1, -1):
        if previous.endswith(current[:k]):
            return current[k:].lstrip()
    return current


def render_window_text(episodes: Sequence[WindowEpisode]) -> str:
    """``[chunk N]`` / ``[episode N | time ...]`` markers followed by the text.

    Consecutive chunks of one batch have their overlap stripped. The time is
    shown only for episodes whose reference time was given explicitly.
    """

    parts: list[str] = []
    previous: WindowEpisode | None = None
    for episode in episodes:
        content = (episode.content or "").strip()
        text = content
        if (
            previous is not None
            and episode.batch_id is not None
            and episode.batch_id == previous.batch_id
            and previous.sequence_index is not None
            and episode.sequence_index == previous.sequence_index + 1
        ):
            text = strip_overlap((previous.content or "").strip(), content)
        marker = f"[{episode.marker_kind} {episode.chunk}"
        if episode.reference_time_explicit:
            shown = display_time(episode.reference_time)
            if shown:
                marker += f" | time {shown}"
        parts.append(marker + "]")
        if text:
            parts.append(text)
        previous = episode
    return "\n".join(parts)


def select_window_rows(candidates: Sequence[Mapping[str, Any]], window_chars: int) -> list[Mapping[str, Any]]:
    """Pick the rows of the next window from ordered candidates (spec §4.2 steps 2-3).

    The first row fixes ``(graph_id, batch_id)``. Batch rows must continue
    with consecutive ``sequence_index`` values; standalone rows follow in
    candidate order. Rows are added while the character total stays within
    ``window_chars``; the first row is always taken.
    """

    if not candidates:
        return []
    first = candidates[0]
    key = (first["graph_id"], first["batch_id"])
    picked = [first]
    total = int(first["n"] or 0)
    previous = first
    for row in candidates[1:]:
        if (row["graph_id"], row["batch_id"]) != key:
            if key[1] is None:
                continue
            break
        if key[1] is not None:
            if previous["sequence_index"] is None or row["sequence_index"] != previous["sequence_index"] + 1:
                break
        size = int(row["n"] or 0)
        if total + size > window_chars:
            break
        picked.append(row)
        total += size
        previous = row
    return picked


_CANDIDATE_SQL = (
    "SELECT id, uuid, graph_id, batch_id, sequence_index, length(content) AS n "
    "FROM episodes WHERE kind = 'document' AND extraction_status = 'queued' "
    "ORDER BY queued_at, batch_id, sequence_index, id LIMIT ?"
)


def _placeholders(count: int) -> str:
    return ",".join("?" * count)


def pack_window(
    conn: Any,
    *,
    window_chars: int,
    owner: str,
    lease_until: float,
    candidate_limit: int = CANDIDATE_LIMIT,
    now_iso: str | None = None,
) -> Window | None:
    """Claim the next window on ``conn``, which must be inside ``store.write()``.

    Claimed episodes become ``processing`` under ``owner``'s lease with
    ``attempts += 1``; their batch items become ``processing``, and a
    ``queued`` batch becomes ``processing``. Returns ``None`` when nothing is
    queued.
    """

    now_iso = now_iso or utcnow_iso()
    candidates = conn.execute(_CANDIDATE_SQL, (candidate_limit,)).fetchall()
    rows = select_window_rows(candidates, window_chars)
    if not rows:
        return None
    uuids = [row["uuid"] for row in rows]
    marks = _placeholders(len(uuids))
    conn.execute(
        "UPDATE episodes SET extraction_status = 'processing', lease_owner = ?, lease_until = ?, "
        f"attempts = attempts + 1 WHERE uuid IN ({marks}) AND extraction_status = 'queued'",
        (owner, lease_until, *uuids),
    )
    conn.execute(
        f"UPDATE batch_items SET status = 'processing', updated_at = ? WHERE episode_uuid IN ({marks}) "
        "AND status IN ('pending', 'queued')",
        (now_iso, *uuids),
    )
    batch_id = rows[0]["batch_id"]
    if batch_id is not None:
        conn.execute(
            "UPDATE batches SET status = 'processing', updated_at = ? WHERE batch_id = ? AND status = 'queued'",
            (now_iso, batch_id),
        )
    full = {
        row["uuid"]: row
        for row in conn.execute(
            "SELECT id, uuid, graph_id, batch_id, sequence_index, content, reference_time, "
            f"reference_time_explicit, strict_ontology, metadata_json FROM episodes WHERE uuid IN ({marks})",
            tuple(uuids),
        )
    }
    episodes = []
    for position, uuid in enumerate(uuids, start=1):
        row = full[uuid]
        episodes.append(WindowEpisode(
            id=row["id"],
            uuid=row["uuid"],
            graph_id=row["graph_id"],
            batch_id=row["batch_id"],
            sequence_index=row["sequence_index"],
            content=row["content"],
            reference_time=row["reference_time"],
            reference_time_explicit=bool(row["reference_time_explicit"]),
            strict_ontology=bool(row["strict_ontology"]),
            chunk=row["sequence_index"] if row["batch_id"] is not None and row["sequence_index"] is not None
            else position,
            language=_stated_language(row["metadata_json"]),
        ))
    return Window(new_id(), rows[0]["graph_id"], batch_id, tuple(episodes), owner, lease_until)


def claim_window(
    store: MemoryStore,
    settings: LocalMemorySettings,
    *,
    owner: str,
    clock: Callable[[], float] = time.time,
    candidate_limit: int = CANDIDATE_LIMIT,
) -> Window | None:
    """Claim the next document window in its own write transaction."""

    lease_until = clock() + settings.lease_seconds
    with store.write() as conn:
        window = pack_window(conn, window_chars=settings.window_chars, owner=owner,
                             lease_until=lease_until, candidate_limit=candidate_limit)
    if window is not None:
        logger.info(
            "Claimed window %s: graph=%s batch=%s episodes=%d chars=%d",
            window.window_id, window.graph_id, window.batch_id, len(window.episodes), window.chars,
        )
    return window


# ---------------------------------------------------------------------------
# Prompt context (spec §4.4)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class KnownEntity:
    uuid: str
    name: str
    entity_type: str | None
    mention_count: int = 0
    mentioned: bool = False  # its name or an alias occurs in the window text


@dataclass(frozen=True)
class ExistingFact:
    fid: str
    uuid: str
    name: str
    fact: str
    source_name: str
    target_name: str
    valid_at: str | None = None


@dataclass
class PromptContext:
    ontology: OntologyView
    known: list[KnownEntity]
    facts: list[ExistingFact]
    # The window's explicit reference time; None when no episode gave one
    # (the ingestion clock says nothing about when the text takes place).
    reference_time: str | None
    # The record language the summaries and facts are written in; None: the
    # language of the text itself.
    language: str | None = None

    @property
    def fact_map(self) -> dict[str, str]:
        return {fact.fid: fact.uuid for fact in self.facts}


def _key_occurs(key: str, compact: str, boundaries: Sequence[bool]) -> bool:
    """True when ``key`` occurs in ``compact`` on word boundaries.

    ``compact``/``boundaries`` come from :func:`compact_with_boundaries`. An
    end of the key that is a word character (Latin, digits, ...) must sit on
    a word boundary, so ``anna`` does not match ``joanna`` and ``ai`` does not
    match ``said``; CJK ends match as plain substrings.
    """

    check_start = is_word_char(key[0])
    check_end = is_word_char(key[-1])
    start = compact.find(key)
    while start != -1:
        end = start + len(key)
        if (not check_start or boundaries[start]) and (not check_end or boundaries[end]):
            return True
        start = compact.find(key, start + 1)
    return False


def find_known_entities(conn: Any, graph_id: str, text: str, *, limit: int) -> tuple[list[KnownEntity], list[str]]:
    """KNOWN ENTITIES for the prompt, plus the uuids of every node mentioned in ``text``.

    Mentioned nodes (a name or alias key of 2+ chars occurs in the compact
    window text, on word boundaries as search's ``MentionIndex`` requires)
    come first, then the most mentioned nodes of the graph.
    """

    rows = conn.execute(
        "SELECT a.alias_key AS key, n.uuid, n.name, n.entity_type, n.mention_count, n.id "
        "FROM node_aliases a JOIN nodes n ON n.uuid = a.node_uuid WHERE a.graph_id = ? "
        "UNION ALL "
        "SELECT n.name_key, n.uuid, n.name, n.entity_type, n.mention_count, n.id "
        "FROM nodes n WHERE n.graph_id = ?",
        (graph_id, graph_id),
    ).fetchall()
    compact, boundaries = compact_with_boundaries(text)
    matched: dict[str, Any] = {}
    for row in rows:
        key = row["key"] or ""
        if row["uuid"] in matched or len(key) < 2 or key not in compact:
            continue
        if not _key_occurs(key, compact, boundaries):
            continue
        matched[row["uuid"]] = row
    ordered = sorted(matched.values(), key=lambda r: (-int(r["mention_count"] or 0), r["id"]))
    known = [
        KnownEntity(r["uuid"], r["name"], r["entity_type"], int(r["mention_count"] or 0), True)
        for r in ordered[:max(0, limit)]
    ]
    if len(known) < limit:
        taken = {entity.uuid for entity in known}
        for row in conn.execute(
            "SELECT uuid, name, entity_type, mention_count FROM nodes WHERE graph_id = ? "
            "ORDER BY mention_count DESC, id ASC LIMIT ?",
            (graph_id, limit + len(taken)),
        ):
            if row["uuid"] in taken:
                continue
            known.append(KnownEntity(row["uuid"], row["name"], row["entity_type"],
                                     int(row["mention_count"] or 0), False))
            if len(known) >= limit:
                break
    return known, [row["uuid"] for row in ordered]


def find_existing_facts(conn: Any, graph_id: str, node_uuids: Sequence[str], *, limit: int) -> list[ExistingFact]:
    """Active edges touching ``node_uuids``, newest first, numbered ``F1..Fn``."""

    if limit <= 0 or not node_uuids:
        return []
    nodes = list(dict.fromkeys(node_uuids))[:_IN_CHUNK]
    marks = _placeholders(len(nodes))
    rows = conn.execute(
        "SELECT e.uuid, e.name, e.fact, e.valid_at, s.name AS source_name, t.name AS target_name "
        "FROM edges e JOIN nodes s ON s.uuid = e.source_node_uuid "
        "JOIN nodes t ON t.uuid = e.target_node_uuid "
        "WHERE e.graph_id = ? AND e.invalid_at IS NULL AND e.expired_at IS NULL "
        f"AND (e.source_node_uuid IN ({marks}) OR e.target_node_uuid IN ({marks})) "
        "ORDER BY e.created_at DESC, e.id DESC LIMIT ?",
        (graph_id, *nodes, *nodes, limit),
    ).fetchall()
    return [
        ExistingFact(f"F{index}", row["uuid"], row["name"], row["fact"], row["source_name"],
                     row["target_name"], row["valid_at"])
        for index, row in enumerate(rows, start=1)
    ]


def gather_prompt_context(conn: Any, window: Window, settings: LocalMemorySettings) -> PromptContext:
    """Ontology, known entities and existing facts for ``window`` (read snapshot).

    The reference time is the window's *explicit* one only. Documents sent
    without ``created_at`` fall back to the ingestion time, which must not be
    offered for resolving "five years ago" in a text set in 399 BC.
    """

    ontology = load_ontology(conn, window.graph_id)
    known, mentioned = find_known_entities(conn, window.graph_id, window.text,
                                           limit=settings.prompt_known_entities)
    facts = find_existing_facts(conn, window.graph_id, mentioned, limit=settings.prompt_existing_facts)
    return PromptContext(ontology=ontology, known=known, facts=facts,
                         reference_time=window.explicit_reference_time, language=window.language)


def build_document_prompt(
    window_text: str,
    ontology: OntologyView,
    known: Sequence[KnownEntity],
    facts: Sequence[ExistingFact],
    reference_time: str | None,
) -> str:
    """The user message of a document extraction call (spec §4.4).

    ``reference_time`` is ``None`` when no episode of the window has an
    explicit time; the prompt then says the reference time is unknown.
    """

    shown = (display_time(reference_time) or reference_time) if reference_time else UNKNOWN_REFERENCE_TIME
    lines = [f"REFERENCE TIME: {shown}"]
    lines.append(ontology.render_entity_types())
    lines.append(ontology.render_relation_types())
    names = "; ".join(f"{entity.name} [{entity.entity_type or 'Entity'}]" for entity in known)
    lines.append(f"KNOWN ENTITIES (reuse these exact names): {names or '(none)'}")
    lines.append("EXISTING FACTS:")
    if facts:
        for fact in facts:
            line = (f"{fact.fid}: {fact.source_name} -{fact.name}-> {fact.target_name}: "
                    f"{json.dumps(truncate(fact.fact, PROMPT_FACT_CHARS), ensure_ascii=False)}")
            if fact.valid_at:
                line += f" (valid_at {_display_date(fact.valid_at)})"
            lines.append(line)
    else:
        lines.append("(none)")
    lines.extend(["TEXT:", "<<<", window_text, ">>>", RETURN_SHAPE])
    return "\n".join(lines)


# Rule 3's last sentence, and what an English record adds to it: the node's
# name is the one its readers know, the scroll's own form an alias.
_NAME_RULE_END = 'Put other spellings, abbreviations and short forms in "aliases".'
_ENGLISH_NAMES = (
    '\n   Write "name" in English: a name TEXT gives in Chinese in its usual English form,'
    '\n   with TEXT\'s own form in "aliases".'
)


def document_system_prompt(max_entities: int, max_relations: int, language: str | None = None) -> str:
    """:data:`DOCUMENT_SYSTEM_PROMPT` with its limits filled in.

    With a known record language, "summary" and "fact" are written in it
    rather than in the language of TEXT (an English gathering built from a
    Chinese scroll still gets an English memory). An English record also
    names its entities in English (苏格拉底 is Socrates, with 苏格拉底 as an
    alias), so the Web, the citizens' cards and the Chronicle show one name.
    A Chinese record keeps names as TEXT writes them.
    """

    system = DOCUMENT_SYSTEM_PROMPT.format(max_entities=max_entities, max_relations=max_relations)
    english = activity_language(language) == "en"
    system = system.replace("in the language of TEXT", written_in(language, names_in_language=english))
    return system.replace(_NAME_RULE_END, _NAME_RULE_END + _ENGLISH_NAMES) if english else system


def build_document_messages(window: Window, context: PromptContext,
                            settings: LocalMemorySettings) -> list[dict[str, str]]:
    system = document_system_prompt(
        settings.max_entities_per_window, settings.max_relations_per_window, context.language,
    )
    user = build_document_prompt(window.text, context.ontology, context.known, context.facts,
                                 context.reference_time)
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


# ---------------------------------------------------------------------------
# LLM call policy (spec §4.9)
# ---------------------------------------------------------------------------


class ExtractionError(Exception):
    """An extraction failure with a stored, user-safe ``{"code", "message"}``."""

    def __init__(self, code: str, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status

    @property
    def error(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


class FatalLLMError(ExtractionError):
    """Auth failure, exhausted daily quota or no LLM configured: stop the batch."""


class BadOutputError(ExtractionError):
    """Unusable output or a rejected request: split the window, or fail one episode."""


class WindowFailedError(ExtractionError):
    """Retries exhausted, or an unexpected error: the window fails."""


@dataclass(frozen=True)
class LLMErrorInfo:
    """How the call policy treats one exception.

    ``kind`` is ``fatal``, ``rate_limited``, ``transient``, ``bad_output`` or
    ``other``.
    """

    kind: str
    code: str
    message: str
    status: int | None = None
    retry_after: float | None = None


def _status_of(error: BaseException) -> int | None:
    status = getattr(error, "status_code", None)
    if isinstance(status, int) and not isinstance(status, bool):
        return status
    response = getattr(error, "response", None)
    status = getattr(response, "status_code", None)
    return status if isinstance(status, int) and not isinstance(status, bool) else None


def _bridge_code(error: BaseException) -> str | None:
    body = getattr(error, "body", None)
    if isinstance(body, Mapping):
        details = body.get("error", body)
        if isinstance(details, Mapping):
            code = details.get("code")
            if isinstance(code, str) and code:
                return code
    code = getattr(error, "code", None)
    return code if isinstance(code, str) and code else None


def _retry_after(error: BaseException) -> float | None:
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    try:
        value = headers.get("retry-after")
    except Exception:  # pragma: no cover - exotic header containers
        return None
    if value is None:
        return None
    try:
        seconds = float(str(value).strip())
    except ValueError:
        return None
    if seconds != seconds or seconds < 0:
        return None
    return seconds


def _transport_error_types() -> tuple[type[BaseException], ...]:
    types: list[type[BaseException]] = [TimeoutError, ConnectionError]
    try:
        import openai

        types += [openai.APIConnectionError, openai.APITimeoutError]
    except ImportError:  # pragma: no cover - openai is a dependency
        pass
    try:
        import httpx

        types.append(httpx.TransportError)
    except ImportError:  # pragma: no cover - httpx ships with openai
        pass
    return tuple(types)


def _is_rate_limit_class(error: BaseException) -> bool:
    try:
        import openai
    except ImportError:  # pragma: no cover
        return False
    return isinstance(error, openai.RateLimitError)


def classify_llm_error(error: BaseException) -> LLMErrorInfo:
    """Map an exception from ``chat_json`` (or the factory) to the §4.9 table."""

    if isinstance(error, _llm_response_error()):
        return LLMErrorInfo("bad_output", "llm_bad_output", str(error) or "LLM returned unusable JSON")
    status = _status_of(error)
    code = _bridge_code(error)
    if code in AUTH_BRIDGE_CODES or status in (401, 403):
        shown = f" (HTTP {status})" if status else ""
        return LLMErrorInfo("fatal", "llm_auth", f"The LLM provider rejected the request{shown}.", status)
    if status == 429 or _is_rate_limit_class(error):
        if code in DAILY_LIMIT_BRIDGE_CODES:
            return LLMErrorInfo(
                "fatal", "llm_quota_exhausted",
                "The LLM's daily free quota is used up (resets 00:00 UTC).", status or 429,
            )
        return LLMErrorInfo("rate_limited", "llm_rate_limited", "The LLM rate limit was exceeded.",
                            status or 429, _retry_after(error))
    if status in BAD_REQUEST_STATUSES:
        return LLMErrorInfo("bad_output", "llm_bad_output",
                            f"The LLM rejected the request (HTTP {status}).", status)
    if isinstance(status, int) and status >= 500:
        return LLMErrorInfo("transient", "llm_unavailable", f"The LLM provider failed (HTTP {status}).", status)
    if isinstance(error, _transport_error_types()):
        return LLMErrorInfo("transient", "llm_unavailable", "The LLM provider could not be reached.")
    if isinstance(error, ValueError) and "LLM_API_KEY" in str(error):
        return LLMErrorInfo("fatal", "llm_not_configured", "LLM_API_KEY is not configured.")
    return LLMErrorInfo("other", "extraction_error", type(error).__name__, status)


class Throttle:
    """Global spacing between LLM call starts (``LOCAL_MEMORY_LLM_MIN_INTERVAL_SECONDS``)."""

    def __init__(self, min_interval: float = 0.0, *, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.min_interval = max(0.0, float(min_interval or 0.0))
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._last_start: float | None = None

    def acquire(self) -> float:
        """Wait until ``last_start + min_interval``; returns the seconds waited."""

        if self.min_interval <= 0:
            return 0.0
        with self._lock:
            now = self._clock()
            wait = 0.0
            if self._last_start is not None:
                wait = self._last_start + self.min_interval - now
            if wait > 0:
                self._sleep(wait)
                now = max(self._clock(), now + wait)
            self._last_start = now
            return max(wait, 0.0)


def record_usage(conn: Any, scope_kind: str, scope_id: str, *, calls: int = 0, failures: int = 0,
                 prompt_chars: int = 0, output_chars: int = 0, now: str | None = None) -> None:
    """Add to the ``usage`` counters of ``(scope_kind, scope_id)`` (inside ``write()``)."""

    conn.execute(
        "INSERT INTO usage(scope_kind, scope_id, llm_calls, llm_failures, prompt_chars, output_chars, "
        "updated_at) VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(scope_kind, scope_id) DO UPDATE SET "
        "llm_calls = llm_calls + excluded.llm_calls, llm_failures = llm_failures + excluded.llm_failures, "
        "prompt_chars = prompt_chars + excluded.prompt_chars, "
        "output_chars = output_chars + excluded.output_chars, updated_at = excluded.updated_at",
        (scope_kind, scope_id or "unknown", calls, failures, prompt_chars, output_chars, now or utcnow_iso()),
    )


def default_llm_factory(settings: LocalMemorySettings | None = None) -> Callable[[], Any]:
    """``LLMClient`` factory honoring ``LOCAL_MEMORY_LLM_MODEL`` (imported lazily)."""

    model = (settings.llm_model if settings else "") or None

    def factory() -> Any:
        from ..utils.llm_client import LLMClient

        return LLMClient(model=model)

    return factory


_UNSET: Any = object()


class ExtractionLLM:
    """Throttled, retrying ``chat_json`` wrapper implementing the §4.9 policy.

    - 429 retries after ``Retry-After`` (else ``10 * 2**(n-1)`` s), capped at 120 s.
    - 5xx and transport errors retry after 5 / 15 / 45 s.
    - Up to ``settings.llm_max_attempts`` SDK calls per request; exhausting
      them raises :class:`WindowFailedError` (``llm_rate_limited`` or
      ``llm_unavailable``).
    - Auth failures, the daily quota and a missing key raise
      :class:`FatalLLMError`; bad JSON and 400/413/422 raise
      :class:`BadOutputError` without retrying; anything else raises
      :class:`WindowFailedError` (``extraction_error``).

    The client comes from ``llm_factory`` on first use, so constructing this
    never needs ``LLM_API_KEY``. With a ``store``, every SDK call updates the
    ``usage`` row of the request's ``scope``.
    """

    def __init__(
        self,
        llm_factory: Callable[[], Any],
        settings: LocalMemorySettings | None = None,
        *,
        throttle: Throttle | None = None,
        sleep: Callable[[float], None] = time.sleep,
        store: MemoryStore | None = None,
    ) -> None:
        self.settings = settings or LocalMemorySettings()
        self._factory = llm_factory
        self.sleep = sleep
        self.throttle = throttle or Throttle(self.settings.llm_min_interval_seconds, sleep=sleep)
        self.store = store
        self._client: Any = None
        self._lock = threading.Lock()
        self._counter_lock = threading.Lock()
        self.calls = 0
        self.failures = 0

    def client(self) -> Any:
        """The underlying LLM client, created on first use."""

        with self._lock:
            if self._client is None:
                try:
                    self._client = self._factory()
                except Exception as error:
                    info = classify_llm_error(error)
                    if info.kind == "fatal" or _is_client_setup_error(error):
                        raise FatalLLMError("llm_not_configured", "LLM_API_KEY is not configured.") from None
                    raise WindowFailedError("extraction_error", type(error).__name__) from None
            return self._client

    def retry_delay(self, info: LLMErrorInfo, attempt: int) -> float:
        if info.kind == "rate_limited":
            delay = info.retry_after if info.retry_after is not None else 10.0 * 2 ** (attempt - 1)
            return min(float(delay), MAX_RETRY_DELAY_SECONDS)
        return TRANSIENT_RETRY_DELAYS[min(attempt - 1, len(TRANSIENT_RETRY_DELAYS) - 1)]

    def chat_json(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.1,
        max_tokens: int | None = _UNSET,
        max_attempts: int = 2,
        scope: tuple[str, str] | None = None,
    ) -> dict[str, Any]:
        """One logical request; ``max_attempts`` is passed to ``LLMClient.chat_json``."""

        if max_tokens is _UNSET:
            max_tokens = self.settings.llm_max_tokens
        client = self.client()
        attempts = max(1, int(self.settings.llm_max_attempts))
        prompt_chars = sum(len(message.get("content") or "") for message in messages)
        for attempt in range(1, attempts + 1):
            self.throttle.acquire()
            try:
                result = client.chat_json(messages, temperature=temperature, max_tokens=max_tokens,
                                          max_attempts=max_attempts)
            except Exception as error:
                info = classify_llm_error(error)
                self._count(scope, failed=True, prompt_chars=prompt_chars, output_chars=0)
                logger.warning(
                    "Extraction LLM call failed (attempt %d/%d, %s, %s, HTTP %s)",
                    attempt, attempts, info.kind, type(error).__name__, info.status,
                )
                if info.kind == "fatal":
                    raise FatalLLMError(info.code, info.message, status=info.status) from None
                if info.kind == "bad_output":
                    raise BadOutputError(info.code, info.message, status=info.status) from None
                if info.kind == "other":
                    raise WindowFailedError(info.code, info.message, status=info.status) from None
                if attempt >= attempts:
                    raise WindowFailedError(info.code, _exhausted_message(info, attempts),
                                            status=info.status) from None
                self.sleep(self.retry_delay(info, attempt))
                continue
            output = json_dumps(result) if isinstance(result, (dict, list)) else str(result)
            self._count(scope, failed=False, prompt_chars=prompt_chars, output_chars=len(output))
            logger.debug("Extraction LLM output: %s", output[:LOG_PREVIEW_CHARS])
            if not isinstance(result, dict):
                raise BadOutputError("llm_bad_output", "LLM JSON response must be a top-level JSON object")
            return result
        raise WindowFailedError("extraction_error", "no LLM attempt was made")  # pragma: no cover

    def _count(self, scope: tuple[str, str] | None, *, failed: bool, prompt_chars: int,
               output_chars: int) -> None:
        with self._counter_lock:
            self.calls += 1
            self.failures += int(failed)
        if self.store is None or not scope:
            return
        try:
            with self.store.write() as conn:
                record_usage(conn, scope[0], scope[1], calls=1, failures=int(failed),
                             prompt_chars=prompt_chars, output_chars=output_chars)
        except Exception as error:  # usage accounting must never break extraction
            logger.debug("Could not record LLM usage: %s", type(error).__name__)


def _is_client_setup_error(error: BaseException) -> bool:
    if isinstance(error, ValueError):
        return True
    try:
        import openai
    except ImportError:  # pragma: no cover
        return False
    return isinstance(error, openai.OpenAIError)


def _exhausted_message(info: LLMErrorInfo, attempts: int) -> str:
    if info.kind == "rate_limited":
        return f"The LLM rate limit was still exceeded after {attempts} attempts."
    detail = f"HTTP {info.status}" if info.status else "connection error"
    return f"The LLM provider was unavailable after {attempts} attempts ({detail})."


# ---------------------------------------------------------------------------
# Window outcomes (spec §4.3 commit and failure rules)
# ---------------------------------------------------------------------------


@dataclass
class CommitOutcome:
    status: str  # succeeded | failed (batch aborted) | canceled | discarded
    episodes: list[str] = field(default_factory=list)
    stats: WriteStats = field(default_factory=WriteStats)
    error: dict[str, Any] | None = None


@dataclass
class WindowResult:
    """What happened to a claimed window (including any split halves)."""

    window_id: str
    graph_id: str
    batch_id: str | None
    succeeded: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    canceled: list[str] = field(default_factory=list)
    discarded: list[str] = field(default_factory=list)  # lease lost: someone else owns them now
    errors: list[dict[str, Any]] = field(default_factory=list)
    fatal_error: dict[str, Any] | None = None
    splits: int = 0
    stats: WriteStats = field(default_factory=WriteStats)

    @property
    def fatal(self) -> bool:
        return self.fatal_error is not None

    @property
    def status(self) -> str:
        """``succeeded``, ``partial``, ``failed``, ``canceled``, ``discarded`` or ``empty``."""

        if self.succeeded and self.failed:
            return "partial"
        if self.succeeded:
            return "succeeded"
        if self.failed:
            return "failed"
        if self.canceled:
            return "canceled"
        if self.discarded:
            return "discarded"
        return "empty"


def _graph_exists(conn: Any, graph_id: str) -> bool:
    return conn.execute("SELECT 1 FROM graphs WHERE graph_id = ?", (graph_id,)).fetchone() is not None


def _owned(conn: Any, window: Window, owner: str | None) -> list[str]:
    """Window episodes still ``processing`` under ``owner`` (any owner when ``None``)."""

    uuids = window.episode_uuids
    marks = _placeholders(len(uuids))
    sql = f"SELECT uuid FROM episodes WHERE uuid IN ({marks}) AND extraction_status = 'processing'"
    params: list[Any] = list(uuids)
    if owner is not None:
        sql += " AND lease_owner = ?"
        params.append(owner)
    found = {row["uuid"] for row in conn.execute(sql, params)}
    return [uuid for uuid in uuids if uuid in found]


def _batch_fatal_error(conn: Any, batch_id: str | None) -> dict[str, Any] | None:
    if batch_id is None:
        return None
    row = conn.execute("SELECT error_json FROM batches WHERE batch_id = ?", (batch_id,)).fetchone()
    error = json_loads(row["error_json"], None) if row is not None else None
    if isinstance(error, Mapping) and error.get("code") in FATAL_ERROR_CODES:
        return dict(error)
    return None


def _cancel_items(conn: Any, uuids: Sequence[str], now_iso: str) -> None:
    if not uuids:
        return
    conn.execute(
        f"UPDATE batch_items SET status = 'canceled', updated_at = ? WHERE episode_uuid IN "
        f"({_placeholders(len(uuids))}) AND status IN ('pending', 'queued', 'processing')",
        (now_iso, *uuids),
    )


def cancel_window(store: MemoryStore, window: Window) -> list[str]:
    """The graph is gone: cancel the window's items (the episodes were cascade-deleted)."""

    now_iso = utcnow_iso()
    with store.write() as conn:
        _cancel_items(conn, window.episode_uuids, now_iso)
        remaining = _owned(conn, window, None)
        if remaining:
            conn.execute(
                "UPDATE episodes SET processed = 1, extraction_status = 'canceled', lease_owner = NULL, "
                f"lease_until = NULL WHERE uuid IN ({_placeholders(len(remaining))})",
                tuple(remaining),
            )
    return window.episode_uuids


def _window_error(window: Window, error: Mapping[str, Any]) -> dict[str, str]:
    return {"code": str(error.get("code") or "extraction_error"),
            "message": str(error.get("message") or ""),
            "window_id": window.window_id}


def _mark_failed(conn: Any, uuids: Sequence[str], payload: Mapping[str, Any], now_iso: str) -> None:
    text = json_dumps(dict(payload))
    marks = _placeholders(len(uuids))
    conn.execute(
        "UPDATE episodes SET processed = 1, extraction_status = 'failed', extraction_error = ?, "
        f"lease_owner = NULL, lease_until = NULL WHERE uuid IN ({marks})",
        (text, *uuids),
    )
    conn.execute(
        f"UPDATE batch_items SET status = 'failed', error_json = ?, updated_at = ? "
        f"WHERE episode_uuid IN ({marks}) AND status IN ('pending', 'queued', 'processing')",
        (text, now_iso, *uuids),
    )


def _abort_batch_rows(conn: Any, batch_id: str, error: Mapping[str, Any], now_iso: str) -> int | None:
    """Fatal abort (spec §4.9) inside the caller's write transaction.

    Records the error in ``batches.error_json`` (unless a fatal error is
    already recorded) and fails every ``pending``/``queued`` item of the
    batch and its episode with the same error. Items that are
    ``processing`` belong to in-flight windows, which fail when they return.
    A missing or already terminal batch is left untouched and gives ``None``;
    otherwise returns the number of items failed here.
    """

    row = conn.execute("SELECT status FROM batches WHERE batch_id = ?", (batch_id,)).fetchone()
    if row is None or row["status"] not in _RUNNING_BATCH_STATUSES:
        return None
    payload = {"code": str(error.get("code") or "extraction_error"), "message": str(error.get("message") or "")}
    text = json_dumps(payload)
    if _batch_fatal_error(conn, batch_id) is None:
        conn.execute("UPDATE batches SET error_json = ?, updated_at = ? WHERE batch_id = ?",
                     (text, now_iso, batch_id))
    conn.execute(
        "UPDATE episodes SET processed = 1, extraction_status = 'failed', extraction_error = ?, "
        "lease_owner = NULL, lease_until = NULL WHERE uuid IN (SELECT episode_uuid FROM batch_items "
        "WHERE batch_id = ? AND status IN ('pending', 'queued')) "
        "AND extraction_status IN ('pending', 'queued')",
        (text, batch_id),
    )
    cursor = conn.execute(
        "UPDATE batch_items SET status = 'failed', error_json = ?, updated_at = ? "
        "WHERE batch_id = ? AND status IN ('pending', 'queued')",
        (text, now_iso, batch_id),
    )
    return cursor.rowcount


def _log_abort(batch_id: str, error: Mapping[str, Any], failed: int) -> None:
    logger.error("Batch %s aborted (%s); %d waiting items failed",
                 batch_id, str(error.get("code") or "extraction_error"), failed)


def fail_window(store: MemoryStore, window: Window, error: Mapping[str, Any], *,
                owner: str | None = None, fatal: bool = False) -> list[str]:
    """Failure rule: episodes ``failed`` (processed), items ``failed`` with ``error_json``.

    The stored error carries ``window_id`` so the finalizer can count windows.
    Only episodes still leased by ``owner`` are touched; returns their uuids.

    With ``fatal=True`` the window's batch is aborted (spec §4.9) in the
    **same** write transaction. The finalizer only claims a batch once none
    of its items is active, so it must never see the window's items failed
    without the batch's fatal ``error_json``: it would then finish the batch
    ``succeeded`` (degraded) instead of ``failed``. The dispatcher likewise
    cannot claim another window of the aborted batch in between.
    """

    payload = _window_error(window, error)
    now_iso = utcnow_iso()
    aborted: int | None = None
    with store.write() as conn:
        owned = _owned(conn, window, owner)
        if owned:
            _mark_failed(conn, owned, payload, now_iso)
        if fatal and window.batch_id is not None:
            aborted = _abort_batch_rows(conn, window.batch_id, error, now_iso)
    if owned:
        logger.warning("Window %s failed (%s) for %d episodes", window.window_id, payload["code"], len(owned))
    if aborted is not None:
        _log_abort(window.batch_id or "", error, aborted)
    return owned


def abort_batch(store: MemoryStore, batch_id: str, error: Mapping[str, Any]) -> int:
    """Fatal abort (spec §4.9) in its own write transaction.

    Every ``pending``/``queued`` item of the batch and its episode become
    ``failed`` with the same error. In-flight windows finish on their own.
    Returns the number of items failed here (0 for a missing or terminal
    batch). A window that hits the fatal error itself uses
    ``fail_window(..., fatal=True)`` instead, so the window failure and the
    abort commit together.
    """

    with store.write() as conn:
        failed = _abort_batch_rows(conn, batch_id, error, utcnow_iso())
    if failed is None:
        return 0
    _log_abort(batch_id, error, failed)
    return failed


def commit_window(
    store: MemoryStore,
    window: Window,
    extraction: ExtractionResult,
    context: PromptContext,
    settings: LocalMemorySettings,
    *,
    owner: str | None = None,
) -> CommitOutcome:
    """Commit rule (spec §4.3): one write transaction per window.

    A deleted graph cancels the items. Episodes whose lease was lost are
    left alone. If the batch was fatally aborted meanwhile, the window fails
    with the batch's error (spec §4.9). Otherwise the extraction is written,
    episodes become ``succeeded`` (processed) and their items ``succeeded``.
    """

    now_iso = utcnow_iso()
    with store.write() as conn:
        if not _graph_exists(conn, window.graph_id):
            _cancel_items(conn, window.episode_uuids, now_iso)
            return CommitOutcome("canceled", window.episode_uuids)
        owned = set(_owned(conn, window, owner))
        if not owned:
            return CommitOutcome("discarded", [])
        batch_error = _batch_fatal_error(conn, window.batch_id)
        if batch_error is not None:
            payload = _window_error(window, batch_error)
            failed = [uuid for uuid in window.episode_uuids if uuid in owned]
            _mark_failed(conn, failed, payload, now_iso)
            return CommitOutcome("failed", failed, error=payload)
        episodes = [episode for episode in window.episodes if episode.uuid in owned]
        stats = write_extraction(
            conn, window.graph_id,
            entities=extraction.entities,
            relations=extraction.relations,
            invalidated_facts=extraction.invalidated_facts,
            episodes=episodes,
            ontology=context.ontology,
            fact_map=context.fact_map,
            strict=window.strict,
            summary_cap=settings.summary_max_chars,
            now=now_iso,
        )
        uuids = [episode.uuid for episode in episodes]
        marks = _placeholders(len(uuids))
        conn.execute(
            "UPDATE episodes SET processed = 1, extraction_status = 'succeeded', extraction_error = NULL, "
            f"lease_owner = NULL, lease_until = NULL WHERE uuid IN ({marks})",
            tuple(uuids),
        )
        conn.execute(
            f"UPDATE batch_items SET status = 'succeeded', error_json = NULL, updated_at = ? "
            f"WHERE episode_uuid IN ({marks}) AND status IN ('pending', 'queued', 'processing')",
            (now_iso, *uuids),
        )
    return CommitOutcome("succeeded", uuids, stats)


def _fail(store: MemoryStore, window: Window, error: Mapping[str, Any], owner: str | None,
          result: WindowResult, *, fatal: bool = False) -> None:
    failed = fail_window(store, window, error, owner=owner, fatal=fatal)
    result.failed.extend(failed)
    result.errors.append({**dict(error), "window_id": window.window_id})
    lost = [uuid for uuid in window.episode_uuids if uuid not in failed]
    result.discarded.extend(lost)


COMMIT_BUSY_ATTEMPTS = 3
COMMIT_BUSY_DELAY_SECONDS = 1.0


def _is_store_busy(error: BaseException) -> bool:
    return getattr(error, "status_code", None) == 503 and type(error).__module__.startswith("zep_cloud")


def _commit_with_retry(store: MemoryStore, window: Window, extraction: ExtractionResult, context: PromptContext,
                       settings: LocalMemorySettings, owner: str | None,
                       sleep: Callable[[float], None]) -> CommitOutcome:
    """``commit_window``, retried briefly while the store reports busy (503)."""

    for attempt in range(1, COMMIT_BUSY_ATTEMPTS + 1):
        try:
            return commit_window(store, window, extraction, context, settings, owner=owner)
        except Exception as error:
            if not _is_store_busy(error) or attempt >= COMMIT_BUSY_ATTEMPTS:
                raise
            logger.warning("Window %s commit found the store busy; retrying", window.window_id)
            sleep(COMMIT_BUSY_DELAY_SECONDS)
    raise AssertionError("unreachable")  # pragma: no cover


def _process_part(store: MemoryStore, window: Window, llm: ExtractionLLM, settings: LocalMemorySettings,
                  owner: str | None, result: WindowResult) -> None:
    if result.fatal_error is not None:
        _fail(store, window, result.fatal_error, owner, result)
        return

    with store.read(snapshot=True) as conn:
        exists = _graph_exists(conn, window.graph_id)
        batch_error = _batch_fatal_error(conn, window.batch_id) if exists else None
        context = gather_prompt_context(conn, window, settings) if exists and batch_error is None else None
    if not exists:
        result.canceled.extend(cancel_window(store, window))
        logger.info("Window %s discarded: graph %s was deleted", window.window_id, window.graph_id)
        return
    if batch_error is not None or context is None:
        _fail(store, window, batch_error or {"code": "extraction_error", "message": "no prompt context"},
              owner, result)
        return

    messages = build_document_messages(window, context, settings)
    logger.debug("Extraction prompt for window %s: %s", window.window_id,
                 messages[-1]["content"][:LOG_PREVIEW_CHARS])
    try:
        raw = llm.chat_json(messages, temperature=0.1, max_tokens=settings.llm_max_tokens, max_attempts=2,
                            scope=("graph", window.graph_id))
        try:
            extraction = parse_extraction(raw, max_entities=settings.max_entities_per_window,
                                          max_relations=settings.max_relations_per_window,
                                          label=f"Window {window.window_id}")
        except ValueError as error:  # LLMResponseError
            raise BadOutputError("llm_bad_output", str(error) or "LLM returned unusable JSON") from None
    except FatalLLMError as error:
        result.fatal_error = error.error
        # Fail the window and abort its batch in one transaction (spec §4.9).
        _fail(store, window, error.error, owner, result, fatal=True)
        return
    except BadOutputError as error:
        if len(window.episodes) > 1:
            result.splits += 1
            first, second = window.split()
            logger.info("Window %s gave bad output (%s); splitting %d episodes into %d + %d",
                        window.window_id, error.code, len(window.episodes),
                        len(first.episodes), len(second.episodes))
            _process_part(store, first, llm, settings, owner, result)
            _process_part(store, second, llm, settings, owner, result)
            return
        _fail(store, window, {"code": "llm_bad_output", "message": error.message}, owner, result)
        return
    except ExtractionError as error:
        _fail(store, window, error.error, owner, result)
        return
    except Exception as error:
        logger.warning("Window %s extraction error: %s", window.window_id, type(error).__name__)
        _fail(store, window, {"code": "extraction_error", "message": type(error).__name__}, owner, result)
        return

    try:
        outcome = _commit_with_retry(store, window, extraction, context, settings, owner, llm.sleep)
    except Exception as error:
        if _is_store_busy(error):
            raise  # transient: lease recovery requeues the window
        logger.warning("Window %s commit failed: %s", window.window_id, type(error).__name__,
                       exc_info=logger.isEnabledFor(logging.DEBUG))
        _fail(store, window, {"code": "extraction_error", "message": type(error).__name__}, owner, result)
        return
    if outcome.status == "failed":
        result.failed.extend(outcome.episodes)
        result.errors.append(dict(outcome.error or {}))
        result.discarded.extend(uuid for uuid in window.episode_uuids if uuid not in outcome.episodes)
        logger.warning("Window %s failed: its batch was aborted (%s)", window.window_id,
                       (outcome.error or {}).get("code"))
        return
    if outcome.status == "canceled":
        result.canceled.extend(outcome.episodes)
        return
    if outcome.status == "discarded":
        result.discarded.extend(window.episode_uuids)
        logger.info("Window %s result discarded: lease lost", window.window_id)
        return
    result.succeeded.extend(outcome.episodes)
    result.discarded.extend(uuid for uuid in window.episode_uuids if uuid not in outcome.episodes)
    result.stats.add(outcome.stats)
    if extraction.dropped:
        logger.info("Window %s: %d invalid or excess extraction entries dropped",
                    window.window_id, extraction.dropped)


def process_window(
    store: MemoryStore,
    window: Window,
    llm: ExtractionLLM,
    settings: LocalMemorySettings,
    *,
    owner: str | None = _UNSET,
) -> WindowResult:
    """Extract and commit a claimed window (spec §4.3, §4.9).

    Never raises for LLM problems: those end as failed episodes and items,
    and a fatal condition also aborts the window's batch (``fatal_error`` is
    set on the result so the caller can stop claiming work). Bad output
    splits the window in halves recursively. A commit that finds the store
    busy is retried briefly; if it stays busy the 503 ``ApiError`` propagates
    and the leased episodes are recovered by lease expiry.

    ``owner`` defaults to ``window.owner``; ``None`` skips the lease check.
    """

    owner = window.owner if owner is _UNSET else owner
    result = WindowResult(window.window_id, window.graph_id, window.batch_id)
    _process_part(store, window, llm, settings, owner, result)
    stats = result.stats
    logger.info(
        "Window %s %s: %d ok, %d failed, %d canceled; nodes +%d/~%d, edges +%d/~%d, invalidated %d",
        window.window_id, result.status, len(result.succeeded), len(result.failed), len(result.canceled),
        stats.nodes_created, stats.nodes_updated, stats.edges_created, stats.edges_merged,
        stats.edges_invalidated,
    )
    return result


def extract_next_window(
    store: MemoryStore,
    llm: ExtractionLLM,
    settings: LocalMemorySettings,
    *,
    owner: str,
    clock: Callable[[], float] = time.time,
) -> WindowResult | None:
    """Claim the next window and process it; ``None`` when nothing is queued."""

    window = claim_window(store, settings, owner=owner, clock=clock)
    if window is None:
        return None
    return process_window(store, window, llm, settings, owner=owner)


# ---------------------------------------------------------------------------
# Post-batch entity dedup pass (spec §4.8)
# ---------------------------------------------------------------------------


def build_dedup_messages(pairs: Sequence[CandidatePair]) -> list[dict[str, str]]:
    lines = ["PAIRS:"]
    for index, pair in enumerate(pairs, start=1):
        a, b = pair.a, pair.b
        lines.append(
            f"P{index}: {json.dumps(a.name, ensure_ascii=False)} [{a.entity_type or 'Entity'}]: "
            f"{truncate(' '.join(a.summary.split()), DEDUP_SUMMARY_CHARS)} || "
            f"{json.dumps(b.name, ensure_ascii=False)} [{b.entity_type or 'Entity'}]: "
            f"{truncate(' '.join(b.summary.split()), DEDUP_SUMMARY_CHARS)}"
        )
    lines.append('Return: {"decisions":[{"pair":"P1","same_entity":true}]}')
    return [{"role": "system", "content": DEDUP_SYSTEM_PROMPT}, {"role": "user", "content": "\n".join(lines)}]


_PAIR_ID_RE = re.compile(r"^\s*p?\s*(\d+)\s*$", re.IGNORECASE)


def _truthy(value: Any) -> bool:
    if value is True:
        return True
    return isinstance(value, str) and value.strip().casefold() in {"true", "yes"}


def parse_dedup_decisions(raw: Any, count: int) -> set[int]:
    """0-based indices of pairs the LLM confirmed as the same entity (only explicit true)."""

    confirmed: set[int] = set()
    if not isinstance(raw, Mapping):
        return confirmed
    decisions = raw.get("decisions")
    items: list[tuple[Any, Any]] = []
    if isinstance(decisions, list):
        for item in decisions:
            if isinstance(item, Mapping):
                items.append((_first_present(item, "pair", "id"), item.get("same_entity", item.get("same"))))
    else:
        items = [(key, value) for key, value in raw.items() if isinstance(key, str) and key[:1] in "Pp"]
    for pair_id, same in items:
        if isinstance(pair_id, bool):
            continue
        if isinstance(pair_id, int):
            number = pair_id
        else:
            match = _PAIR_ID_RE.match(str(pair_id or ""))
            if not match:
                continue
            number = int(match.group(1))
        if 1 <= number <= count and _truthy(same):
            confirmed.add(number - 1)
    return confirmed


@dataclass
class DedupPassResult:
    skipped: bool = False
    graphs: int = 0
    candidates: int = 0
    llm_calls: int = 0
    confirmed: int = 0
    merged_nodes: int = 0  # nodes removed by merging
    errors: int = 0


def _batch_focus(conn: Any, batch_id: str) -> dict[str, list[str]]:
    rows = conn.execute(
        "SELECT DISTINCT n.graph_id, n.uuid FROM node_episodes ne "
        "JOIN episodes e ON e.uuid = ne.episode_uuid JOIN nodes n ON n.uuid = ne.node_uuid "
        "WHERE e.batch_id = ? ORDER BY n.graph_id, n.id",
        (batch_id,),
    ).fetchall()
    focus: dict[str, list[str]] = {}
    for row in rows:
        focus.setdefault(row["graph_id"], []).append(row["uuid"])
    return focus


def run_dedup_pass(
    store: MemoryStore,
    batch_id: str,
    llm: ExtractionLLM,
    settings: LocalMemorySettings,
    *,
    max_pairs: int = DEDUP_MAX_PAIRS,
    pairs_per_call: int = DEDUP_PAIRS_PER_CALL,
) -> DedupPassResult:
    """Entity dedup pass for one batch (spec §4.8).

    Candidate pairs come from a read snapshot; the LLM confirms them in
    chunks of ``pairs_per_call`` with no lock held; confirmed groups are
    merged in one write transaction per graph. LLM failures are logged and
    ignored (a fatal one stops further calls). Returns counters.
    """

    result = DedupPassResult()
    if settings.dedup_pass != "llm":
        result.skipped = True
        return result
    with store.read(snapshot=True) as conn:
        focus = _batch_focus(conn, batch_id)
        work: list[tuple[str, list[CandidatePair]]] = []
        budget = max_pairs
        for graph_id, uuids in focus.items():
            if budget <= 0:
                break
            pairs = find_dedup_candidates(load_dedup_nodes(conn, graph_id), uuids, max_pairs=budget)
            if pairs:
                work.append((graph_id, pairs))
                budget -= len(pairs)
    result.graphs = len(focus)
    result.candidates = sum(len(pairs) for _, pairs in work)
    if not work:
        return result

    stop = False
    for graph_id, pairs in work:
        confirmed: list[CandidatePair] = []
        for start in range(0, len(pairs), max(1, pairs_per_call)):
            if stop:
                break
            chunk = pairs[start:start + max(1, pairs_per_call)]
            try:
                result.llm_calls += 1
                raw = llm.chat_json(build_dedup_messages(chunk), temperature=0.0,
                                    max_tokens=settings.llm_max_tokens, max_attempts=2,
                                    scope=("graph", graph_id))
            except FatalLLMError as error:
                result.errors += 1
                stop = True
                logger.warning("Dedup pass for batch %s stopped: %s", batch_id, error.code)
                break
            except Exception as error:  # pass failures never fail the batch
                result.errors += 1
                logger.warning("Dedup pass call failed for batch %s: %s", batch_id,
                               getattr(error, "code", type(error).__name__))
                continue
            confirmed.extend(chunk[index] for index in sorted(parse_dedup_decisions(raw, len(chunk))))
        result.confirmed += len(confirmed)
        groups = group_confirmed_pairs(confirmed)
        if not groups:
            continue
        now_iso = utcnow_iso()
        with store.write() as conn:
            if not _graph_exists(conn, graph_id):
                continue
            for group in groups:
                if merge_nodes(conn, graph_id, group, summary_cap=settings.summary_max_chars, now=now_iso):
                    result.merged_nodes += len(group) - 1
    logger.info(
        "Dedup pass for batch %s: %d candidates, %d confirmed, %d nodes merged, %d LLM calls, %d errors",
        batch_id, result.candidates, result.confirmed, result.merged_nodes, result.llm_calls, result.errors,
    )
    return result
