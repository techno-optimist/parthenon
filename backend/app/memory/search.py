"""Lexical hybrid search for the local memory backend (spec §6).

``GraphSearcher.search`` implements ``client.graph.search`` with the SDK's
signature and returns the SDK's own ``GraphSearchResults``. There are no
embeddings; relevance comes from up to four candidate channels per scope:

* **FTS**: FTS5 BM25 over the scope's index (trigram tokenizer when available);
* **LIKE**: short query terms (2-char words and 2-char CJK names), plus every
  term the FTS index cannot serve in the fallback modes;
* **mention**: nodes whose name or alias key occurs in the query, with the
  edges touching them ("All information ... about Alice Chen");
* **neighborhood**: nodes and edges within two hops of ``center_node_uuid``
  (``node_distance`` reranker only).

Channels are fused with reciprocal rank fusion (RRF, k = 60), invalidated or
expired edges are penalized, and every Zep reranker name is approximated
deterministically (§6.4). Everything runs on one pooled read connection in
one WAL snapshot, so search never waits for extraction writes.
"""

from __future__ import annotations

import json
import logging
import math
import re
import sqlite3
import threading
import time
import unicodedata
from collections import OrderedDict
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Callable, Iterable, Iterator, Mapping, Protocol, Sequence

from zep_cloud.types import EntityEdge, EntityNode, Episode, GraphSearchResults

from .errors import bad_request, is_busy_sqlite_error, not_found, translate_sqlite_errors, unsupported
from .models import edge_from_row, episode_from_row, filters_to_dict, node_from_row, normalize_page_limit
from .settings import LocalMemorySettings
from .store import TOKENIZER_NONE, TOKENIZER_TRIGRAM, TOKENIZER_UNICODE61, MemoryStore
from .textnorm import (
    STOPWORDS_EN,
    TEMPLATE_PHRASES,
    compact_text,
    compact_with_boundaries,
    contains_word,
    is_cjk,
    is_word_char,
    name_key,
    trigrams,
)

logger = logging.getLogger("mirofish.memory.search")

__all__ = [
    "DEFAULT_LIMIT",
    "MAX_LIMIT",
    "RERANKERS",
    "SEARCH_SCOPES",
    "DenseCandidate",
    "DenseRetriever",
    "GraphSearcher",
    "Mention",
    "MentionIndex",
    "QueryAnalysis",
    "QueryTerm",
    "SearchFilterSpec",
    "SearchRequest",
    "TermMatcher",
    "analyze_query",
    "build_context",
    "fts_match_expression",
    "parse_search_filters",
    "parse_search_request",
]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SEARCH_SCOPES = ("edges", "nodes", "episodes", "auto", "observations", "thread_summaries")
EMPTY_SCOPES = frozenset({"observations", "thread_summaries"})
RERANKERS = ("rrf", "cross_encoder", "mmr", "node_distance", "episode_mentions")
DEFAULT_SCOPE = "edges"
DEFAULT_RERANKER = "rrf"

DEFAULT_LIMIT = 10
MAX_LIMIT = 50
MAX_QUERY_CHARS = 2000

MAX_FTS_TERMS = 48
MAX_SHORT_TERMS = 8
MAX_LIKE_TERMS = 32  # the fallback modes route every term through LIKE

RRF_K = 60
POOL_MIN = 50
POOL_MAX = 200
POOL_PER_RESULT = 5
# bfs_origin_node_uuids filters candidates after retrieval, so retrieve more.
FILTERED_POOL = 1000

MAX_MENTIONED_NODES = 64
MIN_MENTION_KEY_CHARS = 2
BFS_MAX_DEPTH = 2
BFS_FRONTIER_CAP = 1000
HOP_PROXIMITY = {0: 1.0, 1: 0.5, 2: 0.25}

DEFAULT_MMR_LAMBDA = 0.5
MMR_POOL_MIN = 40
MMR_POOL_PER_RESULT = 4
MMR_KEY_CHARS = 600
COVERAGE_TEXT_CHARS = 4000

DEFAULT_CONTEXT_CHARS = 5000
MIN_SCORE = 1e-6
SQL_CHUNK = 450  # IN (...) lists stay under SQLite's historical 999-variable limit
MAX_FILTER_VALUES = 500
MENTION_CACHE_SIZE = 32

TERM_HITS_FUNCTION = "memory_term_hits"

# Honoured filters; every other key (date filters, property_filters,
# episode_metadata_filters, ...) is accepted and ignored.
LIST_FILTER_KEYS = ("node_labels", "exclude_node_labels", "edge_types", "exclude_edge_types", "edge_uuids")

CONTEXT_HEADER = "FACTS and ENTITIES represent relevant context to the current conversation."
CONTEXT_FACTS_TITLE = "# These are the most relevant facts and their valid date ranges"
CONTEXT_ENTITIES_TITLE = "# These are the most relevant entities"


def _omitted(value: Any) -> bool:
    """``None`` or the SDK's ``...`` "omit" sentinel."""

    return value is None or value is Ellipsis


# ---------------------------------------------------------------------------
# Query analysis (§6.2)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class QueryTerm:
    """One normalized query term.

    ``whole_word`` terms (2-char words of space-delimited scripts, such as
    "ai") must match at word boundaries; every other term is a substring
    match, like the trigram index.
    """

    text: str
    whole_word: bool = False


@dataclass(frozen=True)
class QueryAnalysis:
    """What each channel searches for.

    ``fts_terms`` go to the FTS index as an ``OR`` of quoted phrases
    (``match``); ``like_terms`` are scanned with LIKE; ``coverage_terms`` are
    every logical term, whatever the tokenizer (used by ``cross_encoder``).
    """

    query: str
    normalized: str
    tokenizer: str
    fts_terms: tuple[str, ...]
    short_terms: tuple[str, ...]
    like_terms: tuple[QueryTerm, ...]
    coverage_terms: tuple[QueryTerm, ...]
    match: str

    @property
    def has_terms(self) -> bool:
        return bool(self.fts_terms or self.like_terms)


# Word tokens: letters and digits of any script, without the underscore.
_WORD_RE = re.compile(r"[^\W_]+")


def _dedupe(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _script_runs(token: str) -> Iterator[str]:
    """Split a word token into maximal CJK and non-CJK runs."""

    start = 0
    for index in range(1, len(token) + 1):
        if index == len(token) or is_cjk(token[index]) != is_cjk(token[start]):
            yield token[start:index]
            start = index


def fts_match_expression(terms: Sequence[str]) -> str:
    """``"t1" OR "t2" ...``: every term is a quoted FTS5 phrase."""

    return " OR ".join('"' + term.replace('"', '""') + '"' for term in terms)


def analyze_query(query: str, tokenizer: str = TOKENIZER_TRIGRAM) -> QueryAnalysis:
    """Split a query into FTS, LIKE and coverage terms (spec §6.2).

    Template phrases from the profile/report queries are blanked out and
    English stopwords dropped. Words of three or more characters and CJK
    trigrams are "long" terms; 2-character words and 2-character CJK runs are
    "short" terms (1-character runs are dropped). Routing depends on the FTS
    tokenizer: ``trigram`` indexes long terms, ``unicode61`` only non-CJK
    words (CJK trigrams move to LIKE), and without FTS5 every term is a LIKE
    term.
    """

    text = query.strip()[:MAX_QUERY_CHARS] if isinstance(query, str) else ""
    normalized = unicodedata.normalize("NFKC", text).casefold()
    for phrase in TEMPLATE_PHRASES:
        normalized = normalized.replace(phrase, " ")

    latin_long: list[str] = []
    cjk_long: list[str] = []
    long_terms: list[str] = []
    short: list[QueryTerm] = []
    for token in _WORD_RE.findall(normalized):
        for segment in _script_runs(token):
            if is_cjk(segment):
                if len(segment) >= 3:
                    grams = [segment[i:i + 3] for i in range(len(segment) - 2)]
                    cjk_long.extend(grams)
                    long_terms.extend(grams)
                elif len(segment) == 2:
                    short.append(QueryTerm(segment))
                continue
            if segment in STOPWORDS_EN:
                continue
            if len(segment) >= 3:
                latin_long.append(segment)
                long_terms.append(segment)
            elif len(segment) == 2:
                short.append(QueryTerm(segment, whole_word=True))

    long_kept = _dedupe(long_terms)[:MAX_FTS_TERMS]
    kept = set(long_kept)
    short_kept: list[QueryTerm] = []
    seen_short: set[str] = set()
    for term in short:
        if term.text not in seen_short:
            seen_short.add(term.text)
            short_kept.append(term)
    short_kept = short_kept[:MAX_SHORT_TERMS]

    long_as_terms = [QueryTerm(term) for term in long_kept]
    if tokenizer == TOKENIZER_NONE:
        fts_terms: list[str] = []
        like_terms = short_kept + long_as_terms
    elif tokenizer == TOKENIZER_UNICODE61:
        # unicode61 indexes a CJK run as one token, so CJK needs LIKE.
        latin_kept = set(latin_long)
        fts_terms = [term for term in long_kept if term in latin_kept]
        cjk_kept = [QueryTerm(term) for term in _dedupe(cjk_long) if term in kept]
        like_terms = short_kept + cjk_kept
    else:
        fts_terms = list(long_kept)
        like_terms = list(short_kept)

    return QueryAnalysis(
        query=text,
        normalized=normalized,
        tokenizer=tokenizer,
        fts_terms=tuple(fts_terms),
        short_terms=tuple(term.text for term in short_kept),
        like_terms=tuple(like_terms[:MAX_LIKE_TERMS]),
        coverage_terms=tuple(short_kept + long_as_terms),
        match=fts_match_expression(fts_terms),
    )


class TermMatcher:
    """Counts which query terms occur in a piece of text."""

    def __init__(self, terms: Sequence[QueryTerm]) -> None:
        self.terms = tuple(terms)

    @staticmethod
    def normalize(text: str) -> str:
        return unicodedata.normalize("NFKC", text).casefold()

    def count(self, text: str | None) -> int:
        if not text or not self.terms:
            return 0
        value = self.normalize(text)
        hits = 0
        for term in self.terms:
            if term.whole_word:
                if contains_word(value, term.text):
                    hits += 1
            elif term.text in value:
                hits += 1
        return hits

    def coverage(self, text: str | None) -> float:
        """Share of the terms found in ``text`` (0.0 when there are no terms)."""

        if not self.terms:
            return 0.0
        return self.count(text) / len(self.terms)


def _terms_payload(terms: Sequence[QueryTerm]) -> str:
    return json.dumps([[t.text, 1 if t.whole_word else 0] for t in terms], ensure_ascii=False,
                      separators=(",", ":"))


@lru_cache(maxsize=128)
def _matcher_for_payload(payload: str) -> TermMatcher:
    return TermMatcher([QueryTerm(str(text), bool(whole)) for text, whole in json.loads(payload)])


def _sql_term_hits(text: Any, payload: Any) -> int:
    """SQL function ``memory_term_hits(text, terms_json)``: matched term count.

    A pure function of its arguments, so it is registered once per
    connection and never replaced while a statement runs.
    """

    if not isinstance(text, str) or not isinstance(payload, str):
        return 0
    try:
        return _matcher_for_payload(payload).count(text)
    except Exception:  # a UDF error would abort the whole query
        return 0


# ---------------------------------------------------------------------------
# Request validation (§6.1) and filters (§6.6)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SearchFilterSpec:
    """The honoured part of ``search_filters``; empty tuples mean "no filter"."""

    node_labels: tuple[str, ...] = ()
    exclude_node_labels: tuple[str, ...] = ()
    edge_types: tuple[str, ...] = ()
    exclude_edge_types: tuple[str, ...] = ()
    edge_uuids: tuple[str, ...] = ()
    ignored: tuple[str, ...] = ()


def _filter_values(key: str, value: Any) -> tuple[str, ...]:
    if _omitted(value):
        return ()
    if isinstance(value, str):
        items: list[Any] = [value]
    elif isinstance(value, (list, tuple, set, frozenset)):
        items = list(value)
    else:
        raise bad_request(f"search_filters.{key} must be a list of strings")
    if any(not isinstance(item, str) for item in items):
        raise bad_request(f"search_filters.{key} must be a list of strings")
    values = tuple(_dedupe(item for item in items if item.strip()))
    if len(values) > MAX_FILTER_VALUES:
        raise bad_request(f"search_filters.{key} accepts at most {MAX_FILTER_VALUES} values")
    return values


def parse_search_filters(search_filters: Any) -> SearchFilterSpec:
    """Normalize a ``SearchFilters`` model or dict.

    Label, edge-type and edge-uuid filters are honoured. Date filters,
    ``property_filters``, ``episode_metadata_filters`` and unknown keys are
    accepted and ignored (logged at debug level).
    """

    if _omitted(search_filters):
        return SearchFilterSpec()
    data = filters_to_dict(search_filters)
    values: dict[str, tuple[str, ...]] = {}
    ignored: list[str] = []
    for key in sorted(data):
        if key in LIST_FILTER_KEYS:
            values[key] = _filter_values(key, data[key])
        elif not _omitted(data[key]):
            ignored.append(key)
    if ignored:
        logger.debug("Local memory search ignores filters: %s", ", ".join(ignored))
    return SearchFilterSpec(ignored=tuple(ignored), **values)


@dataclass(frozen=True)
class SearchRequest:
    """Validated ``graph.search`` arguments."""

    query: str
    graph_id: str
    limit: int = DEFAULT_LIMIT
    scope: str = DEFAULT_SCOPE
    reranker: str = DEFAULT_RERANKER
    filters: SearchFilterSpec = field(default_factory=SearchFilterSpec)
    center_node_uuid: str | None = None
    bfs_origin_node_uuids: tuple[str, ...] = ()
    mmr_lambda: float = DEFAULT_MMR_LAMBDA
    max_characters: int | None = None


def _choice(name: str, value: Any, choices: Sequence[str], default: str) -> str:
    if _omitted(value):
        return default
    if not isinstance(value, str) or value.strip().lower() not in choices:
        raise bad_request(f"{name} must be one of: {', '.join(choices)}")
    return value.strip().lower()


def _optional_id(name: str, value: Any) -> str | None:
    if _omitted(value):
        return None
    if not isinstance(value, str) or not value.strip():
        raise bad_request(f"{name} must be a non-empty string")
    return value.strip()


def parse_search_request(
    *,
    query: Any,
    graph_id: Any = None,
    user_id: Any = None,
    limit: Any = None,
    scope: Any = None,
    reranker: Any = None,
    search_filters: Any = None,
    center_node_uuid: Any = None,
    bfs_origin_node_uuids: Any = None,
    mmr_lambda: Any = None,
    max_characters: Any = None,
) -> SearchRequest:
    """Validate ``graph.search`` arguments; every problem is a ``BadRequestError``."""

    if not _omitted(user_id):
        raise unsupported("graph.search with user_id")
    if _omitted(graph_id) or not isinstance(graph_id, str) or not graph_id.strip():
        raise bad_request("graph_id is required")
    if not isinstance(query, str) or not query.strip():
        raise bad_request("query must be a non-empty string")
    text = query.strip()[:MAX_QUERY_CHARS]

    limit_value = normalize_page_limit(None if _omitted(limit) else limit, default=DEFAULT_LIMIT,
                                       maximum=MAX_LIMIT)
    scope_value = _choice("scope", scope, SEARCH_SCOPES, DEFAULT_SCOPE)
    reranker_value = _choice("reranker", reranker, RERANKERS, DEFAULT_RERANKER)

    center = _optional_id("center_node_uuid", center_node_uuid)
    if reranker_value == "node_distance" and center is None:
        raise bad_request("the node_distance reranker requires center_node_uuid")

    if _omitted(mmr_lambda):
        lam = DEFAULT_MMR_LAMBDA
    else:
        if isinstance(mmr_lambda, bool) or not isinstance(mmr_lambda, (int, float)):
            raise bad_request("mmr_lambda must be a number between 0 and 1")
        lam = float(mmr_lambda)
        if not 0.0 <= lam <= 1.0:
            raise bad_request("mmr_lambda must be a number between 0 and 1")

    if _omitted(max_characters):
        max_chars: int | None = None
    else:
        if isinstance(max_characters, bool) or not isinstance(max_characters, int) or max_characters < 1:
            raise bad_request("max_characters must be a positive integer")
        max_chars = max_characters

    if _omitted(bfs_origin_node_uuids):
        origins: tuple[str, ...] = ()
    elif isinstance(bfs_origin_node_uuids, (list, tuple)) and all(
        isinstance(item, str) for item in bfs_origin_node_uuids
    ):
        origins = tuple(_dedupe(item.strip() for item in bfs_origin_node_uuids if item.strip()))
        if len(origins) > MAX_FILTER_VALUES:
            raise bad_request(f"bfs_origin_node_uuids accepts at most {MAX_FILTER_VALUES} values")
    else:
        raise bad_request("bfs_origin_node_uuids must be a list of node uuids")

    return SearchRequest(
        query=text,
        graph_id=graph_id,
        limit=limit_value,
        scope=scope_value,
        reranker=reranker_value,
        filters=parse_search_filters(search_filters),
        center_node_uuid=center,
        bfs_origin_node_uuids=origins,
        mmr_lambda=lam,
        max_characters=max_chars,
    )


# ---------------------------------------------------------------------------
# Entity mentions (§6.3, channel 3)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Mention:
    """A node whose name or alias key occurs in the query at ``[start, end)``."""

    node_uuid: str
    key: str
    start: int
    end: int
    by_name: bool
    mention_count: int


def _mentionable_key(key: str) -> bool:
    if not isinstance(key, str) or len(key) < MIN_MENTION_KEY_CHARS:
        return False
    # "us", "all", "background": a stopword alone is not a mention.
    if key in STOPWORDS_EN and all(is_word_char(ch) for ch in key):
        return False
    return True


def _template_mask(compact: str) -> list[bool] | None:
    """Positions covered by template phrases (``关于``, ``的所有信息``, ...)."""

    mask: list[bool] | None = None
    for phrase in TEMPLATE_PHRASES:
        start = compact.find(phrase)
        while start != -1:
            if mask is None:
                mask = [False] * len(compact)
            for index in range(start, start + len(phrase)):
                mask[index] = True
            start = compact.find(phrase, start + 1)
    return mask


class MentionIndex:
    """Name/alias keys of one graph, bucketed by their first two characters.

    ``find`` scans the compacted query once. A key whose first or last
    character is a word character (Latin, digits, ...) must sit on a word
    boundary, so ``ai`` does not match ``said``; CJK keys match as substrings.
    A key found only inside a template phrase is ignored, and a match strictly
    inside a longer match is dropped ("Chen" inside "Alice Chen").
    """

    def __init__(self, entries: Iterable[tuple[str, str, bool, int]] = ()) -> None:
        by_key: dict[str, dict[str, tuple[bool, int]]] = {}
        for key, node_uuid, by_name, mention_count in entries:
            if not node_uuid or not _mentionable_key(key):
                continue
            nodes = by_key.setdefault(key, {})
            previous = nodes.get(node_uuid)
            nodes[node_uuid] = (bool(by_name) or bool(previous and previous[0]), int(mention_count or 0))
        self._nodes: dict[str, tuple[tuple[str, bool, int], ...]] = {
            key: tuple(sorted(((uid, flag, count) for uid, (flag, count) in nodes.items()),
                              key=lambda item: (not item[1], -item[2], item[0])))
            for key, nodes in by_key.items()
        }
        buckets: dict[str, list[str]] = {}
        for key in self._nodes:
            buckets.setdefault(key[:2], []).append(key)
        self._buckets = {prefix: sorted(keys, key=lambda k: (-len(k), k)) for prefix, keys in buckets.items()}

    @classmethod
    def from_rows(cls, rows: Iterable[Any]) -> "MentionIndex":
        return cls((row["key"], row["node_uuid"], bool(row["by_name"]), row["mention_count"]) for row in rows)

    def __len__(self) -> int:
        return len(self._nodes)

    def find(self, text: str, limit: int = MAX_MENTIONED_NODES) -> list[Mention]:
        if not self._nodes or not text:
            return []
        compact, boundaries = compact_with_boundaries(text)
        if len(compact) < MIN_MENTION_KEY_CHARS:
            return []
        mask = _template_mask(compact)
        spans: list[tuple[int, int, str]] = []
        for start in range(len(compact) - 1):
            bucket = self._buckets.get(compact[start:start + 2])
            if not bucket:
                continue
            for key in bucket:
                end = start + len(key)
                if end > len(compact) or not compact.startswith(key, start):
                    continue
                if is_word_char(key[0]) and not boundaries[start]:
                    continue
                if is_word_char(key[-1]) and not boundaries[end]:
                    continue
                if mask is not None and all(mask[start:end]):
                    continue
                spans.append((start, end, key))

        spans.sort(key=lambda span: (-(span[1] - span[0]), span[0]))
        kept: list[tuple[int, int, str]] = []
        for span in spans:
            length = span[1] - span[0]
            if any(k[0] <= span[0] and span[1] <= k[1] and k[1] - k[0] > length for k in kept):
                continue
            kept.append(span)

        mentions: list[Mention] = []
        seen: set[str] = set()
        for start, end, key in kept:
            for node_uuid, by_name, mention_count in self._nodes[key]:
                if node_uuid in seen:
                    continue
                seen.add(node_uuid)
                mentions.append(Mention(node_uuid, key, start, end, by_name, mention_count))
                if len(mentions) >= limit:
                    return mentions
        return mentions


# ---------------------------------------------------------------------------
# Dense retrieval hook (§6.9, not implemented in v1)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DenseCandidate:
    """A retrieved item offered to a dense retriever: ``kind`` is edge, node or episode."""

    uuid: str
    kind: str
    text: str


class DenseRetriever(Protocol):
    """Optional embedding ranker; its order becomes one more RRF channel."""

    def rank(self, graph_id: str, query: str,
             candidates: Sequence[DenseCandidate]) -> Sequence[tuple[str, float]]: ...


# ---------------------------------------------------------------------------
# Context string (§6.7)
# ---------------------------------------------------------------------------


def _one_line(value: Any) -> str:
    return " ".join(str(value or "").split())


def _truncate_lines(text: str, limit: int) -> str:
    kept: list[str] = []
    used = 0
    for line in text.split("\n"):
        cost = len(line) + (1 if kept else 0)
        if used + cost > limit:
            break
        kept.append(line)
        used += cost
    if not kept:
        return text[:limit]
    return "\n".join(kept)


def build_context(edges: Sequence[EntityEdge], nodes: Sequence[EntityNode],
                  max_characters: int | None = None) -> str:
    """Zep-style context block of facts (with date ranges) and entities.

    Truncated to ``max_characters`` (default 5000) on line boundaries: the
    section frame is kept and fact lines, then entity lines, are added while
    they fit.
    """

    limit = max_characters or DEFAULT_CONTEXT_CHARS
    fact_lines = [
        f"  - {_one_line(edge.fact)} (Date range: {edge.valid_at or 'unknown'} - "
        f"{edge.invalid_at or edge.expired_at or 'present'})"
        for edge in edges
    ]
    entity_lines = [f"  - {_one_line(node.name)}: {_one_line(node.summary)}" for node in nodes]

    def assemble(facts: Sequence[str], entities: Sequence[str]) -> str:
        return "\n".join([
            CONTEXT_HEADER,
            CONTEXT_FACTS_TITLE,
            "<FACTS>",
            *facts,
            "</FACTS>",
            CONTEXT_ENTITIES_TITLE,
            "<ENTITIES>",
            *entities,
            "</ENTITIES>",
        ])

    full = assemble(fact_lines, entity_lines)
    if len(full) <= limit:
        return full
    skeleton = assemble([], [])
    if len(skeleton) > limit:
        return _truncate_lines(full, limit)
    budget = limit - len(skeleton)
    kept: dict[str, list[str]] = {"facts": [], "entities": []}
    for name, lines in (("facts", fact_lines), ("entities", entity_lines)):
        for line in lines:
            cost = len(line) + 1
            if cost > budget:
                break
            kept[name].append(line)
            budget -= cost
    return assemble(kept["facts"], kept["entities"])


# ---------------------------------------------------------------------------
# SQL helpers
# ---------------------------------------------------------------------------


class _Params(dict):
    """Named SQL parameters with generated, collision-free names."""

    def add(self, value: Any) -> str:
        name = f"p{len(self)}"
        while name in self:
            name += "_"
        self[name] = value
        return ":" + name

    def many(self, values: Iterable[Any]) -> str:
        return ", ".join(self.add(value) for value in values)


def _chunks(items: Sequence[Any], size: int = SQL_CHUNK) -> Iterator[Sequence[Any]]:
    for start in range(0, len(items), size):
        yield items[start:start + size]


def _label_token(label: str) -> str:
    # labels_json is a JSON array; a quoted element is an exact label match.
    return json.dumps(label, ensure_ascii=False)


def _labels_any(alias: str, names: Sequence[str]) -> str:
    return "(" + " OR ".join(f"instr({alias}.labels_json, {name}) > 0" for name in names) + ")"


def _edge_filter_sql(spec: SearchFilterSpec, params: _Params) -> str:
    parts: list[str] = []
    if spec.edge_types:
        parts.append(f"e.name IN ({params.many(spec.edge_types)})")
    if spec.exclude_edge_types:
        parts.append(f"e.name NOT IN ({params.many(spec.exclude_edge_types)})")
    if spec.edge_uuids:
        parts.append(f"e.uuid IN ({params.many(spec.edge_uuids)})")
    if spec.node_labels:
        names = [params.add(_label_token(label)) for label in spec.node_labels]
        parts.append("EXISTS (SELECT 1 FROM nodes fs WHERE fs.uuid = e.source_node_uuid AND "
                     f"{_labels_any('fs', names)})")
        parts.append("EXISTS (SELECT 1 FROM nodes ft WHERE ft.uuid = e.target_node_uuid AND "
                     f"{_labels_any('ft', names)})")
    if spec.exclude_node_labels:
        names = [params.add(_label_token(label)) for label in spec.exclude_node_labels]
        parts.append("NOT EXISTS (SELECT 1 FROM nodes fx WHERE fx.uuid IN "
                     f"(e.source_node_uuid, e.target_node_uuid) AND {_labels_any('fx', names)})")
    return "".join(f" AND {part}" for part in parts)


def _node_filter_sql(spec: SearchFilterSpec, params: _Params) -> str:
    parts: list[str] = []
    if spec.node_labels:
        names = [params.add(_label_token(label)) for label in spec.node_labels]
        parts.append(_labels_any("n", names))
    if spec.exclude_node_labels:
        names = [params.add(_label_token(label)) for label in spec.exclude_node_labels]
        parts.append(f"NOT {_labels_any('n', names)}")
    return "".join(f" AND {part}" for part in parts)


def _like_pattern(term: str) -> str:
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _like_any(columns: Sequence[str], name: str) -> str:
    return "(" + " OR ".join(f"{col} LIKE {name} ESCAPE '\\'" for col in columns) + ")"


def _like_sql(columns: Sequence[str], terms: Sequence[QueryTerm], params: _Params) -> tuple[str, str]:
    """``(prefilter, hits)`` SQL for the LIKE channel.

    ``prefilter`` keeps rows containing any term; ``hits`` counts the terms a
    row contains. Substring terms are counted with LIKE in SQL; whole-word
    terms (such as "ai") go through ``memory_term_hits`` so "said" does not
    count.
    """

    names = [params.add(_like_pattern(term.text)) for term in terms]
    prefilter = "(" + " OR ".join(_like_any(columns, name) for name in names) + ")"
    parts = [_like_any(columns, name) for term, name in zip(terms, names) if not term.whole_word]
    whole = [term for term in terms if term.whole_word]
    if whole:
        text = " || ' ' || ".join(columns)
        parts.append(f"{TERM_HITS_FUNCTION}({text}, {params.add(_terms_payload(whole))})")
    return prefilter, " + ".join(parts)


def _is_missing_function(error: sqlite3.OperationalError) -> bool:
    return "no such function" in str(error).lower()


def _execute_with_udf(conn: sqlite3.Connection, sql: str, params: Mapping[str, Any]) -> list[sqlite3.Row]:
    """Run ``sql``, registering ``memory_term_hits`` on first use per connection."""

    try:
        return conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError as error:
        if not _is_missing_function(error):
            raise
    conn.create_function(TERM_HITS_FUNCTION, 2, _sql_term_hits, deterministic=True)
    return conn.execute(sql, params).fetchall()


def _sort_rows_newest(rows: list[Any], *, active_first: bool = False) -> list[Any]:
    """Stable multi-key sort: [active,] newer created_at, then higher id."""

    rows = sorted(rows, key=lambda r: r["id"], reverse=True)
    rows.sort(key=lambda r: r["created_at"] or "", reverse=True)
    if active_first:
        rows.sort(key=lambda r: r["invalid_at"] is not None or r["expired_at"] is not None)
    return rows


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return len(a & b) / len(a | b)


# ---------------------------------------------------------------------------
# Fusion and reranking (§6.4)
# ---------------------------------------------------------------------------


@dataclass
class _Candidate:
    uuid: str
    row: Any
    invalid: bool = False
    recency: str = ""
    rrf: float = 0.0
    base: float = 0.0
    final: float = 0.0
    score: float = 0.0


def _rrf_scores(channels: Sequence[Sequence[str]]) -> dict[str, float]:
    scores: dict[str, float] = {}
    for ranking in channels:
        for rank, uuid in enumerate(ranking, 1):
            scores[uuid] = scores.get(uuid, 0.0) + 1.0 / (RRF_K + rank)
    return scores


def _assign_scores(selected: Sequence[_Candidate]) -> None:
    top = max((c.final for c in selected), default=0.0)
    for candidate in selected:
        if top <= 0:
            candidate.score = 1.0
        else:
            candidate.score = min(1.0, max(MIN_SCORE, round(candidate.final / top, 6)))


@dataclass
class _Features:
    """Per-candidate signals for the rerankers (only the needed ones are set)."""

    coverage: Callable[[_Candidate], float] | None = None
    mention: Callable[[_Candidate], bool] | None = None
    episode_count: Callable[[_Candidate], int] | None = None
    hop: Callable[[_Candidate], int | None] | None = None
    sim_key: Callable[[_Candidate], str] | None = None


def _rerank(candidates: list[_Candidate], reranker: str, limit: int, features: _Features,
            mmr_lambda: float) -> list[_Candidate]:
    """Order candidates by the reranker's final score and keep ``limit``.

    Ties go to active items, then newer ones, then the smaller uuid.
    """

    ordered = sorted(candidates, key=lambda c: c.uuid)
    ordered.sort(key=lambda c: c.recency, reverse=True)
    ordered.sort(key=lambda c: c.invalid)
    if reranker == "mmr":
        return _mmr(ordered, limit, features, mmr_lambda)
    for c in ordered:
        if reranker == "cross_encoder":
            coverage = features.coverage(c) if features.coverage else 0.0
            mentioned = 1.0 if features.mention and features.mention(c) else 0.0
            c.final = 0.5 * c.base + 0.4 * coverage + 0.1 * mentioned
        elif reranker == "episode_mentions":
            count = features.episode_count(c) if features.episode_count else 0
            c.final = c.base * (1.0 + math.log1p(max(0, count)))
        elif reranker == "node_distance":
            hop = features.hop(c) if features.hop else None
            proximity = HOP_PROXIMITY.get(hop, 0.0) if hop is not None else 0.0
            c.final = 0.5 * c.base + 0.5 * proximity
        else:
            c.final = c.base
    ordered.sort(key=lambda c: c.final, reverse=True)  # stable: ties keep the tie-break order
    selected = ordered[:limit]
    _assign_scores(selected)
    return selected


def _mmr(ordered: list[_Candidate], limit: int, features: _Features, lam: float) -> list[_Candidate]:
    """Greedy maximal marginal relevance over the best candidates by base score.

    gain = λ·base − (1 − λ)·max_sim(selected); the reported final score is
    ``gain + (1 − λ)``, which is never negative and never increases.
    """

    by_base = sorted(ordered, key=lambda c: c.base, reverse=True)
    pool = by_base[:max(MMR_POOL_MIN, MMR_POOL_PER_RESULT * limit)]
    key_of = features.sim_key or (lambda c: c.uuid)
    grams = [trigrams(key_of(c)[:MMR_KEY_CHARS]) for c in pool]
    max_sim = [0.0] * len(pool)
    remaining = list(range(len(pool)))
    selected: list[_Candidate] = []
    while remaining and len(selected) < limit:
        best = max(remaining, key=lambda i: (lam * pool[i].base - (1.0 - lam) * max_sim[i], -i))
        gain = lam * pool[best].base - (1.0 - lam) * max_sim[best]
        pool[best].final = gain + (1.0 - lam)
        selected.append(pool[best])
        remaining.remove(best)
        for i in remaining:
            similarity = _jaccard(grams[i], grams[best])
            if similarity > max_sim[i]:
                max_sim[i] = similarity
    _assign_scores(selected)
    return selected


# ---------------------------------------------------------------------------
# Searcher
# ---------------------------------------------------------------------------

_FINGERPRINT_SQL = """
SELECT g.version AS version,
       (SELECT count(*) FROM node_aliases a WHERE a.graph_id = g.graph_id) AS alias_count,
       (SELECT max(a.rowid) FROM node_aliases a WHERE a.graph_id = g.graph_id) AS alias_max,
       (SELECT count(*) FROM nodes n WHERE n.graph_id = g.graph_id) AS node_count,
       (SELECT max(n.id) FROM nodes n WHERE n.graph_id = g.graph_id) AS node_max
FROM graphs g WHERE g.graph_id = :g
"""

_MENTION_ROWS_SQL = """
SELECT a.alias_key AS key, a.node_uuid AS node_uuid, (a.alias_key = n.name_key) AS by_name,
       n.mention_count AS mention_count
FROM node_aliases a JOIN nodes n ON n.uuid = a.node_uuid WHERE a.graph_id = :g
UNION ALL
SELECT n.name_key, n.uuid, 1, n.mention_count FROM nodes n WHERE n.graph_id = :g
"""


class GraphSearcher:
    """``graph.search`` over one ``MemoryStore``; safe to share between threads.

    Holds only a small LRU cache of per-graph mention indexes, keyed by
    ``graphs.version`` plus node and alias counters, so a writer that forgets
    to bump ``version`` still invalidates it.
    """

    def __init__(self, store: MemoryStore, settings: LocalMemorySettings | None = None, *,
                 dense_retriever: DenseRetriever | None = None,
                 cache_size: int = MENTION_CACHE_SIZE) -> None:
        self.store = store
        self.settings = settings or LocalMemorySettings()
        self.dense_retriever = dense_retriever
        self._cache: "OrderedDict[str, tuple[tuple[Any, ...], MentionIndex]]" = OrderedDict()
        self._cache_lock = threading.Lock()
        self._cache_size = max(1, int(cache_size))

    def invalidate(self, graph_id: str | None = None) -> None:
        """Drop cached mention indexes (one graph, or all when ``None``)."""

        with self._cache_lock:
            if graph_id is None:
                self._cache.clear()
            else:
                self._cache.pop(graph_id, None)

    def mention_index(self, conn: sqlite3.Connection, graph_id: str) -> MentionIndex:
        """The graph's mention index; ``NotFoundError`` when the graph is missing."""

        row = conn.execute(_FINGERPRINT_SQL, {"g": graph_id}).fetchone()
        if row is None:
            raise not_found(f"graph not found: {graph_id}")
        fingerprint = tuple(row)
        with self._cache_lock:
            cached = self._cache.get(graph_id)
            if cached is not None and cached[0] == fingerprint:
                self._cache.move_to_end(graph_id)
                return cached[1]
        index = MentionIndex.from_rows(conn.execute(_MENTION_ROWS_SQL, {"g": graph_id}))
        with self._cache_lock:
            self._cache[graph_id] = (fingerprint, index)
            self._cache.move_to_end(graph_id)
            while len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)
        return index

    def search(
        self,
        *,
        query: Any = None,
        graph_id: Any = None,
        user_id: Any = None,
        limit: Any = None,
        scope: Any = None,
        reranker: Any = None,
        search_filters: Any = None,
        center_node_uuid: Any = None,
        bfs_origin_node_uuids: Any = None,
        mmr_lambda: Any = None,
        max_characters: Any = None,
        return_raw_results: Any = None,
        request_options: Any = None,
    ) -> GraphSearchResults:
        """``client.graph.search`` (spec §6). ``return_raw_results`` is ignored."""

        request = parse_search_request(
            query=query,
            graph_id=graph_id,
            user_id=user_id,
            limit=limit,
            scope=scope,
            reranker=reranker,
            search_filters=search_filters,
            center_node_uuid=center_node_uuid,
            bfs_origin_node_uuids=bfs_origin_node_uuids,
            mmr_lambda=mmr_lambda,
            max_characters=max_characters,
        )
        return self.run(request)

    @translate_sqlite_errors
    def run(self, request: SearchRequest) -> GraphSearchResults:
        """Execute an already validated request (busy SQLite errors become the SDK's 503)."""

        started = time.perf_counter()
        analysis = analyze_query(request.query, self.store.caps.tokenizer)
        with self.store.read(snapshot=True) as conn:
            index = self.mention_index(conn, request.graph_id)
            edges, nodes, episodes = _SearchRun(self, conn, request, analysis, index).execute()
        logger.debug(
            "Local memory search graph=%s scope=%s reranker=%s -> %d edges, %d nodes, %d episodes (%.1f ms)",
            request.graph_id, request.scope, request.reranker, len(edges), len(nodes), len(episodes),
            (time.perf_counter() - started) * 1000,
        )
        context = None
        if request.scope == "auto" or request.max_characters is not None:
            context = build_context(edges, nodes, request.max_characters)
        return GraphSearchResults(
            edges=edges,
            nodes=nodes,
            episodes=episodes,
            observations=[],
            thread_summaries=[],
            context=context,
        )


class _SearchRun:
    """One search: channels, fusion and reranking inside one read snapshot."""

    def __init__(self, searcher: GraphSearcher, conn: sqlite3.Connection, request: SearchRequest,
                 analysis: QueryAnalysis, index: MentionIndex) -> None:
        self.searcher = searcher
        self.conn = conn
        self.request = request
        self.analysis = analysis
        self.index = index
        self.graph_id = request.graph_id
        self.filters = request.filters
        self.fts = searcher.store.caps.fts5 and bool(analysis.match)
        self.penalty = float(searcher.settings.search_invalid_penalty)
        self.coverage = TermMatcher(analysis.coverage_terms)
        self.mentions: list[Mention] = []
        self.mentioned: dict[str, int] = {}
        self.center_distances: dict[str, int] | None = None
        self.region: dict[str, int] | None = None

    # -- orchestration ---------------------------------------------------------

    def execute(self) -> tuple[list[EntityEdge], list[EntityNode], list[Episode]]:
        request = self.request
        if request.reranker == "node_distance":
            found = self.conn.execute(
                "SELECT 1 FROM nodes WHERE uuid = :u AND graph_id = :g",
                {"u": request.center_node_uuid, "g": self.graph_id},
            ).fetchone()
            if found is None:
                raise not_found("center node not found")
        if request.scope in EMPTY_SCOPES:
            return [], [], []
        self.mentions = self.index.find(request.query)
        self.mentioned = {m.node_uuid: rank for rank, m in enumerate(self.mentions)}
        if not self.analysis.has_terms and not self.mentions:
            return [], [], []
        if request.reranker == "node_distance":
            self.center_distances = self._bfs([request.center_node_uuid or ""])
        if request.bfs_origin_node_uuids:
            self.region = self._bfs(request.bfs_origin_node_uuids)

        edges: list[EntityEdge] = []
        nodes: list[EntityNode] = []
        episodes: list[Episode] = []
        limit = request.limit
        if request.scope in ("edges", "auto"):
            edges = self.search_edges(limit)
        if request.scope in ("nodes", "auto"):
            nodes = self.search_nodes(limit if request.scope == "nodes" else max(3, limit // 2))
        if request.scope in ("episodes", "auto"):
            episodes = self.search_episodes(limit if request.scope == "episodes" else max(3, limit // 3))
        return edges, nodes, episodes

    def _pool(self, limit: int) -> int:
        if self.region is not None:
            return FILTERED_POOL
        return min(POOL_MAX, max(POOL_MIN, POOL_PER_RESULT * limit))

    # -- shared steps ------------------------------------------------------------

    def _query(self, sql: str, params: Mapping[str, Any]) -> list[sqlite3.Row]:
        return self.conn.execute(sql, params).fetchall()

    def _fts_query(self, sql: str, params: Mapping[str, Any]) -> list[sqlite3.Row]:
        """FTS channel; a broken index degrades to the other channels."""

        try:
            return self._query(sql, params)
        except sqlite3.OperationalError as error:
            if is_busy_sqlite_error(error):
                raise
            logger.warning("Local memory FTS query failed; using the other channels: %s", error)
            return []

    @staticmethod
    def _collect(found: Iterable[Any], rows: dict[str, Any]) -> list[str]:
        ranking: list[str] = []
        seen: set[str] = set()
        for row in found:
            uuid = row["uuid"]
            if uuid in seen:
                continue
            seen.add(uuid)
            ranking.append(uuid)
            rows.setdefault(uuid, row)
        return ranking

    def _bfs(self, origins: Sequence[str]) -> dict[str, int]:
        """Node uuid -> hop distance (0..2) from ``origins`` over all edges."""

        distances: dict[str, int] = {}
        frontier: list[str] = []
        for chunk in _chunks(list(origins)):
            params = _Params(g=self.graph_id)
            found = self._query(
                f"SELECT uuid FROM nodes WHERE graph_id = :g AND uuid IN ({params.many(chunk)})", params
            )
            frontier.extend(row["uuid"] for row in found)
        frontier = sorted(set(frontier))
        for uuid in frontier:
            distances[uuid] = 0
        for depth in range(1, BFS_MAX_DEPTH + 1):
            if not frontier:
                break
            neighbors: set[str] = set()
            for chunk in _chunks(frontier):
                params = _Params(g=self.graph_id)
                names = params.many(chunk)
                # The unary "+" stops SQLite (which has no ANALYZE statistics
                # here) from preferring the graph_id-only index and scanning
                # the whole graph; the node-uuid indexes are far narrower.
                found = self._query(
                    f"SELECT target_node_uuid AS n FROM edges WHERE +graph_id = :g AND source_node_uuid IN ({names}) "
                    f"UNION SELECT source_node_uuid FROM edges WHERE +graph_id = :g AND target_node_uuid IN ({names})",
                    params,
                )
                neighbors.update(row["n"] for row in found)
            frontier = sorted(uuid for uuid in neighbors if uuid not in distances)[:BFS_FRONTIER_CAP]
            for uuid in frontier:
                distances[uuid] = depth
        return distances

    @staticmethod
    def _levels(distances: Mapping[str, int]) -> list[list[str]]:
        levels: dict[int, list[str]] = {}
        for uuid, depth in distances.items():
            levels.setdefault(depth, []).append(uuid)
        return [sorted(levels[depth]) for depth in sorted(levels)]

    def _dense_channel(self, kind: str, rows: Mapping[str, Any],
                       text_of: Callable[[Any], str]) -> list[str]:
        retriever = self.searcher.dense_retriever
        if retriever is None or not rows:
            return []
        candidates = [DenseCandidate(uuid, kind, text_of(row)) for uuid, row in rows.items()]
        try:
            ranked = retriever.rank(self.graph_id, self.request.query, candidates)
            scored = [(uuid, float(score)) for uuid, score in ranked if uuid in rows]
        except Exception as error:  # an optional hook must never break search
            logger.warning("Dense retriever failed (%s); ignoring it", type(error).__name__)
            return []
        scored.sort(key=lambda item: item[1], reverse=True)
        return _dedupe(uuid for uuid, _ in scored)

    def _fuse(self, channels: list[list[str]], rows: Mapping[str, Any],
              invalid_of: Callable[[Any], bool], recency_of: Callable[[Any], str]) -> list[_Candidate]:
        scores = _rrf_scores(channels)
        if not scores:
            return []
        top = max(scores.values())
        candidates: list[_Candidate] = []
        for uuid, value in scores.items():
            row = rows[uuid]
            invalid = invalid_of(row)
            base = value / top
            if invalid:
                base *= self.penalty
            candidates.append(_Candidate(uuid=uuid, row=row, invalid=invalid,
                                         recency=recency_of(row) or "", rrf=value, base=base))
        return candidates

    def _counts(self, sql_template: str, uuids: Sequence[str]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for chunk in _chunks(list(uuids)):
            params = _Params()
            for row in self._query(sql_template.format(ids=params.many(chunk)), params):
                counts[row[0]] = int(row[1])
        return counts

    def _episode_nodes(self, episode_uuids: Sequence[str]) -> dict[str, list[str]]:
        links: dict[str, list[str]] = {}
        for chunk in _chunks(list(episode_uuids)):
            params = _Params()
            found = self._query(
                f"SELECT episode_uuid, node_uuid FROM node_episodes WHERE episode_uuid IN ({params.many(chunk)})",
                params,
            )
            for row in found:
                links.setdefault(row["episode_uuid"], []).append(row["node_uuid"])
        return links

    # -- edges -----------------------------------------------------------------

    def search_edges(self, limit: int) -> list[EntityEdge]:
        pool = self._pool(limit)
        rows: dict[str, Any] = {}
        channels: list[list[str]] = []
        if self.fts:
            params = _Params(g=self.graph_id, match=self.analysis.match, pool=pool)
            sql = ("SELECT e.*, bm25(edges_fts, 1.0, 2.0) AS _rank FROM edges_fts "
                   "JOIN edges e ON e.id = edges_fts.rowid "
                   "WHERE edges_fts MATCH :match AND e.graph_id = :g"
                   f"{_edge_filter_sql(self.filters, params)} ORDER BY _rank, e.id LIMIT :pool")
            channels.append(self._collect(self._fts_query(sql, params), rows))
        if self.analysis.like_terms:
            params = _Params(g=self.graph_id, pool=pool)
            prefilter, hits = _like_sql(("e.fact", "e.name"), self.analysis.like_terms, params)
            sql = (f"SELECT e.*, {hits} AS _hits FROM edges e "
                   f"WHERE e.graph_id = :g AND {prefilter}{_edge_filter_sql(self.filters, params)} "
                   "ORDER BY _hits DESC, e.id DESC LIMIT :pool")
            found = _execute_with_udf(self.conn, sql, params)
            channels.append(self._collect((row for row in found if row["_hits"] > 0), rows))
        if self.mentioned:
            params = _Params(g=self.graph_id, pool=pool)
            names = params.many(self.mentioned)
            sql = (f"SELECT e.*, ((e.source_node_uuid IN ({names})) + (e.target_node_uuid IN ({names}))) "
                   "AS _mentioned FROM edges e WHERE +e.graph_id = :g AND "
                   f"(e.source_node_uuid IN ({names}) OR e.target_node_uuid IN ({names}))"
                   f"{_edge_filter_sql(self.filters, params)} ORDER BY _mentioned DESC, "
                   "(e.invalid_at IS NULL AND e.expired_at IS NULL) DESC, e.created_at DESC, e.id DESC "
                   "LIMIT :pool")
            channels.append(self._collect(self._query(sql, params), rows))
        if self.center_distances is not None:
            channels.append(self._edge_neighborhood(self.center_distances, pool, rows))

        if self.region is not None:
            region = self.region
            channels = [[u for u in channel if rows[u]["source_node_uuid"] in region
                         or rows[u]["target_node_uuid"] in region] for channel in channels]
        channels = [channel for channel in channels if channel]
        if not channels:
            return []
        rows = {uuid: rows[uuid] for channel in channels for uuid in channel}
        dense = self._dense_channel("edge", rows, lambda r: f"{r['name']}: {r['fact']}")
        if dense:
            channels.append(dense)

        candidates = self._fuse(
            channels, rows,
            invalid_of=lambda r: r["invalid_at"] is not None or r["expired_at"] is not None,
            recency_of=lambda r: r["created_at"],
        )
        features = _Features()
        reranker = self.request.reranker
        if reranker == "cross_encoder":
            features.coverage = lambda c: self.coverage.coverage(
                f"{c.row['fact'] or ''} {c.row['name'] or ''}"[:COVERAGE_TEXT_CHARS])
            features.mention = lambda c: (c.row["source_node_uuid"] in self.mentioned
                                          or c.row["target_node_uuid"] in self.mentioned)
        elif reranker == "episode_mentions":
            counts = self._counts(
                "SELECT edge_uuid, count(*) FROM edge_episodes WHERE edge_uuid IN ({ids}) GROUP BY edge_uuid",
                [c.uuid for c in candidates],
            )
            features.episode_count = lambda c: counts.get(c.uuid, 0)
        elif reranker == "node_distance":
            distances = self.center_distances or {}
            features.hop = lambda c: _edge_hop(c.row, distances)
        elif reranker == "mmr":
            features.sim_key = lambda c: c.row["fact_key"] or name_key(c.row["fact"] or "")

        selected = _rerank(candidates, reranker, limit, features, self.request.mmr_lambda)
        episodes = self._edge_episodes([c.uuid for c in selected])
        return [edge_from_row(c.row, episodes.get(c.uuid, []), score=c.score) for c in selected]

    def _edge_neighborhood(self, distances: Mapping[str, int], pool: int, rows: dict[str, Any]) -> list[str]:
        """Edges touching nodes at hop 0, then 1, then 2 from the center."""

        ranking: list[str] = []
        seen: set[str] = set()
        for level in self._levels(distances):
            if len(ranking) >= pool:
                break
            found: list[Any] = []
            for chunk in _chunks(level):
                params = _Params(g=self.graph_id, pool=pool)
                names = params.many(chunk)
                sql = ("SELECT e.* FROM edges e WHERE +e.graph_id = :g AND "
                       f"(e.source_node_uuid IN ({names}) OR e.target_node_uuid IN ({names}))"
                       f"{_edge_filter_sql(self.filters, params)} ORDER BY "
                       "(e.invalid_at IS NULL AND e.expired_at IS NULL) DESC, e.created_at DESC, e.id DESC "
                       "LIMIT :pool")
                found.extend(row for row in self._query(sql, params) if row["uuid"] not in seen)
            unique = {row["uuid"]: row for row in found}
            for row in _sort_rows_newest(list(unique.values()), active_first=True):
                if len(ranking) >= pool:
                    break
                seen.add(row["uuid"])
                ranking.append(row["uuid"])
                rows.setdefault(row["uuid"], row)
        return ranking

    def _edge_episodes(self, edge_uuids: Sequence[str]) -> dict[str, list[str]]:
        links: dict[str, list[str]] = {}
        for chunk in _chunks(list(edge_uuids)):
            params = _Params()
            found = self._query(
                "SELECT edge_uuid, episode_uuid FROM edge_episodes "
                f"WHERE edge_uuid IN ({params.many(chunk)}) ORDER BY linked_at, rowid",
                params,
            )
            for row in found:
                links.setdefault(row["edge_uuid"], []).append(row["episode_uuid"])
        return links

    # -- nodes -----------------------------------------------------------------

    def search_nodes(self, limit: int) -> list[EntityNode]:
        pool = self._pool(limit)
        rows: dict[str, Any] = {}
        channels: list[list[str]] = []
        if self.fts:
            params = _Params(g=self.graph_id, match=self.analysis.match, pool=pool)
            sql = ("SELECT n.*, bm25(nodes_fts, 3.0, 2.0, 1.0, 0.5) AS _rank FROM nodes_fts "
                   "JOIN nodes n ON n.id = nodes_fts.rowid "
                   "WHERE nodes_fts MATCH :match AND n.graph_id = :g"
                   f"{_node_filter_sql(self.filters, params)} ORDER BY _rank, n.id LIMIT :pool")
            channels.append(self._collect(self._fts_query(sql, params), rows))
        if self.analysis.like_terms:
            params = _Params(g=self.graph_id, pool=pool)
            prefilter, hits = _like_sql(("n.name", "n.aliases_text", "n.summary"), self.analysis.like_terms, params)
            sql = (f"SELECT n.*, {hits} AS _hits FROM nodes n "
                   f"WHERE n.graph_id = :g AND {prefilter}{_node_filter_sql(self.filters, params)} "
                   "ORDER BY _hits DESC, n.id DESC LIMIT :pool")
            found = _execute_with_udf(self.conn, sql, params)
            channels.append(self._collect((row for row in found if row["_hits"] > 0), rows))
        if self.mentioned:
            found = self._nodes_by_uuid(list(self.mentioned))
            found.sort(key=lambda row: self.mentioned[row["uuid"]])
            channels.append(self._collect(found[:pool], rows))
        if self.center_distances is not None:
            distances = self.center_distances
            found = self._nodes_by_uuid(list(distances))
            found.sort(key=lambda row: row["id"])
            found.sort(key=lambda row: -int(row["mention_count"] or 0))
            found.sort(key=lambda row: distances[row["uuid"]])
            channels.append(self._collect(found[:pool], rows))

        if self.region is not None:
            channels = [[u for u in channel if u in self.region] for channel in channels]
        channels = [channel for channel in channels if channel]
        if not channels:
            return []
        rows = {uuid: rows[uuid] for channel in channels for uuid in channel}
        dense = self._dense_channel("node", rows, lambda r: f"{r['name']}: {r['summary']}")
        if dense:
            channels.append(dense)

        candidates = self._fuse(channels, rows, invalid_of=lambda r: False, recency_of=lambda r: r["created_at"])
        features = _Features()
        reranker = self.request.reranker
        if reranker == "cross_encoder":
            features.coverage = lambda c: self.coverage.coverage(
                " ".join(str(c.row[col] or "") for col in ("name", "aliases_text", "summary", "attributes_text"))
                [:COVERAGE_TEXT_CHARS])
            features.mention = lambda c: c.uuid in self.mentioned
        elif reranker == "episode_mentions":
            counts = self._counts(
                "SELECT node_uuid, count(*) FROM node_episodes WHERE node_uuid IN ({ids}) GROUP BY node_uuid",
                [c.uuid for c in candidates],
            )
            features.episode_count = lambda c: counts.get(c.uuid, 0)
        elif reranker == "node_distance":
            distances = self.center_distances or {}
            features.hop = lambda c: distances.get(c.uuid)
        elif reranker == "mmr":
            features.sim_key = lambda c: c.row["name_key"] or name_key(c.row["name"] or "")

        selected = _rerank(candidates, reranker, limit, features, self.request.mmr_lambda)
        return [node_from_row(c.row, score=c.score) for c in selected]

    def _nodes_by_uuid(self, uuids: Sequence[str]) -> list[Any]:
        found: list[Any] = []
        for chunk in _chunks(list(uuids)):
            params = _Params(g=self.graph_id)
            sql = (f"SELECT n.* FROM nodes n WHERE n.graph_id = :g AND n.uuid IN ({params.many(chunk)})"
                   f"{_node_filter_sql(self.filters, params)}")
            found.extend(self._query(sql, params))
        return found

    # -- episodes ------------------------------------------------------------------

    def search_episodes(self, limit: int) -> list[Episode]:
        pool = self._pool(limit)
        rows: dict[str, Any] = {}
        channels: list[list[str]] = []
        if self.fts:
            params = _Params(g=self.graph_id, match=self.analysis.match, pool=pool)
            sql = ("SELECT ep.*, bm25(episodes_fts, 1.0, 0.3) AS _rank FROM episodes_fts "
                   "JOIN episodes ep ON ep.id = episodes_fts.rowid "
                   "WHERE episodes_fts MATCH :match AND ep.graph_id = :g ORDER BY _rank, ep.id DESC LIMIT :pool")
            channels.append(self._collect(self._fts_query(sql, params), rows))
        if self.analysis.like_terms:
            params = _Params(g=self.graph_id, pool=pool)
            prefilter, hits = _like_sql(("ep.content", "ep.source_description"), self.analysis.like_terms, params)
            sql = (f"SELECT ep.*, {hits} AS _hits FROM episodes ep WHERE ep.graph_id = :g AND {prefilter} "
                   "ORDER BY _hits DESC, ep.id DESC LIMIT :pool")
            found = _execute_with_udf(self.conn, sql, params)
            channels.append(self._collect((row for row in found if row["_hits"] > 0), rows))

        channels = [channel for channel in channels if channel]
        links: dict[str, list[str]] | None = None
        if channels and (self.region is not None or self.request.reranker == "node_distance"):
            links = self._episode_nodes(_dedupe(uuid for channel in channels for uuid in channel))
        if self.region is not None and links is not None:
            region = self.region
            channels = [[u for u in channel if any(n in region for n in links.get(u, ()))]
                        for channel in channels]
            channels = [channel for channel in channels if channel]
        if not channels:
            return []
        rows = {uuid: rows[uuid] for channel in channels for uuid in channel}
        dense = self._dense_channel("episode", rows, lambda r: r["content"])
        if dense:
            channels.append(dense)

        candidates = self._fuse(channels, rows, invalid_of=lambda r: False,
                                recency_of=lambda r: r["reference_time"] or r["created_at"])
        features = _Features()
        reranker = self.request.reranker
        if reranker == "cross_encoder":
            keys = _dedupe(m.key for m in self.mentions)
            features.coverage = lambda c: self.coverage.coverage(
                f"{(c.row['content'] or '')[:COVERAGE_TEXT_CHARS]} {c.row['source_description'] or ''}")
            features.mention = lambda c: _mentions_any(c.row["content"], keys)
        elif reranker == "node_distance":
            distances = self.center_distances or {}
            episode_links = links or {}
            features.hop = lambda c: min(
                (distances[n] for n in episode_links.get(c.uuid, ()) if n in distances), default=None)
        elif reranker == "mmr":
            features.sim_key = lambda c: compact_text((c.row["content"] or "")[:MMR_KEY_CHARS])

        selected = _rerank(candidates, reranker, limit, features, self.request.mmr_lambda)
        return [episode_from_row(c.row, score=c.score) for c in selected]


def _edge_hop(row: Any, distances: Mapping[str, int]) -> int | None:
    hops = [distances[uuid] for uuid in (row["source_node_uuid"], row["target_node_uuid"]) if uuid in distances]
    return min(hops) if hops else None


def _mentions_any(content: Any, keys: Sequence[str]) -> bool:
    """True when any mention key occurs in the (compacted) start of ``content``."""

    if not keys or not content:
        return False
    compact = compact_text(str(content)[:COVERAGE_TEXT_CHARS])
    return any(key in compact for key in keys)
