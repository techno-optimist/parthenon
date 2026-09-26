"""Entity resolution and graph writes for the local memory backend (spec §4.6-§4.8).

Everything here runs on a connection the caller already holds inside
``store.write()`` (one transaction per extraction window, or per merge
batch). Nothing here calls an LLM: the dedup pass's LLM step lives in
``extraction.run_dedup_pass`` and hands its confirmed pairs back to
:func:`group_confirmed_pairs` / :func:`merge_nodes`.

Inputs from the LLM are duck-typed so this module does not depend on
``extraction`` (see the dependency order in spec §9):

- entities: ``name``, ``type``, ``aliases``, ``summary``, ``attributes``
- relations: ``source``, ``target``, ``type``, ``fact``, ``valid_at``,
  ``invalid_at``, ``chunks``, ``attributes``
- invalidated facts: ``id``, ``invalid_at``
- episodes: ``uuid``, ``content``, ``reference_time``,
  ``reference_time_explicit``, ``chunk``

The helpers :func:`resolve_existing`, :func:`create_node`,
:func:`link_node_episodes`, :func:`upsert_edge` and
:func:`bump_graph_version` are also meant for the activity rules extractor.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Protocol, Sequence

from .models import json_dumps, json_loads
from .ontology import OntologyView
from .store import new_id
from .textnorm import (
    alias_keys,
    compact_text,
    is_cjk,
    name_key,
    normalize_name,
    parse_iso_date,
    split_sentences,
    strip_honorifics,
    trigram_jaccard,
    trigrams,
    utcnow_iso,
)

logger = logging.getLogger("mirofish.memory.resolution")

__all__ = [
    "DEDUP_CANDIDATE_JACCARD",
    "DEDUP_MAX_PAIRS",
    "EDGE_DEDUP_JACCARD",
    "FALLBACK_ENTITY_TYPES",
    "SYMMETRIC_RELATIONS",
    "CandidatePair",
    "DedupNode",
    "EpisodeRef",
    "MergedEntity",
    "PreparedEntities",
    "ResolvedNode",
    "WriteStats",
    "bump_graph_version",
    "choose_candidate",
    "create_node",
    "dedupe_node_edges",
    "episodes_mentioning",
    "filter_attributes",
    "find_candidates",
    "find_dedup_candidates",
    "find_duplicate_edge",
    "group_confirmed_pairs",
    "invalidate_edge",
    "link_node_episodes",
    "load_dedup_nodes",
    "merge_nodes",
    "merge_summary",
    "prepare_entities",
    "resolve_existing",
    "resolve_or_create",
    "upsert_edge",
    "write_extraction",
]

# Two facts on the same endpoints and relation are the same fact at or above this.
EDGE_DEDUP_JACCARD = 0.8
# A summary sentence this similar to an existing one adds nothing.
SUMMARY_DEDUP_JACCARD = 0.8
# Dedup-pass candidate threshold on name keys (spec §4.8).
DEDUP_CANDIDATE_JACCARD = 0.6
DEDUP_MAX_PAIRS = 120
# Display aliases kept per node (aliases_text); alias keys are not capped.
MAX_DISPLAY_ALIASES = 20
# SQLite host-parameter budget per IN (...) list.
_IN_CHUNK = 500

_ALIAS_SEPARATOR = " | "
_ATTRIBUTE_KEY_RE = re.compile(r"[\s\-]+")
_TOKEN_SPLIT_RE = re.compile(r"[\s\-_.·•'’/]+")
_ACRONYM_RE = re.compile(r"^[A-Z]{2,6}$")
_ACRONYM_SKIP_WORDS = frozenset({"of", "and", "the", "for", "&", "de", "du", "la", "le"})
_ACTIVE_EDGE = "invalid_at IS NULL AND expired_at IS NULL"

# Catch-all entity types the ontology generator always adds (ontology_generator.py),
# mapped to their family. A node typed with a fallback and one typed with a more
# specific type of the same family, under the same name, are one entity whose type
# drifted between extraction windows ("Socrates" [Person] vs "Socrates" [Philosopher]).
FALLBACK_ENTITY_TYPES: Mapping[str, str] = {
    "person": "person",
    "organization": "organization",
    "organisation": "organization",
}
# Head nouns (last word of a PascalCase type name) that make a type organization-like
# or not an actor at all; any other type is person-like. Only used to decide whether a
# specific type belongs to a fallback's family.
_ORGANIZATION_TYPE_WORDS = frozenset("""
    academy administration agency alliance army assembly association authority bank board brand
    bureau business cabinet channel charity church clinic club coalition college commission
    committee company congress consortium cooperative corporation council court department
    enterprise faction federation firm force foundation fund government group guild hospital
    institute institution journal lab laboratory league legislature magazine media military
    ministry movement network newspaper ngo nonprofit office organisation organization outlet
    parliament party platform police publication publisher regime regulator school senate
    service society startup station studio syndicate team tribunal union university website
""".split())
_NON_ACTOR_TYPE_WORDS = frozenset("""
    animal app area article artifact artwork asset bill book building campaign case city concept
    continent country currency date device disease document drug era event facility film food
    hashtag idea incident issue item land landmark law location meeting movie object period place
    plant policy post product program programme project province region regulation resource site
    software song species state technology text time title tool topic town treaty trial vehicle
    venue village weapon work
""".split())
_TYPE_KEY_RE = re.compile(r"[\s_\-]+")
_CAMEL_SPLIT_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")

# Relation names whose facts read the same in both directions: only for these may a
# reversed edge with a merely similar fact be folded into an existing one.
SYMMETRIC_RELATIONS = frozenset({
    "ACQUAINTED_WITH", "ALLIED_WITH", "ALLY_OF", "ASSOCIATED_WITH", "CLASSMATE_OF",
    "COLLABORATED_WITH", "COLLABORATES_WITH", "COLLEAGUE_OF", "COLLEAGUES_WITH", "COMPETES_WITH",
    "COMPETITOR_OF", "CONNECTED_TO", "CORRESPONDS_WITH", "DEBATED", "DEBATES_WITH", "FRIENDS_WITH",
    "FRIEND_OF", "KNOWS", "MARRIED_TO", "MEETS", "MET", "MET_WITH", "NEIGHBOR_OF", "PARTNERS_WITH",
    "PARTNER_OF", "RELATED_TO", "RIVAL_OF", "SIBLING_OF", "SIMILAR_TO", "SPOKE_WITH", "SPOUSE_OF",
    "TALKS_WITH", "WORKS_WITH",
})

# Renaming a node (spec §4.6: "Alice" -> "Alice Chen") accepts only proper-name growth.
# These characters mark an apposition or description ("Crito, Socrates' oldest friend").
_RENAME_BLOCKING_CHARS = frozenset(",;:()[]{}<>|/\"“”«»「」『』《》（），：；【】")
_NAME_TOKEN_SPLIT_RE = re.compile(r"[\s\-‐‑‒–—]+")
MAX_RENAME_ADDED_TOKENS = 3
# Lowercase name particles ("Leonardo da Vinci", "Ludwig van Beethoven").
_NAME_PARTICLES = frozenset({
    "af", "al", "av", "bin", "bint", "binti", "da", "das", "de", "del", "della", "der", "des", "di",
    "do", "dos", "du", "el", "ibn", "la", "le", "lo", "ten", "ter", "van", "von", "y", "zu",
})
# Titles and roles: capitalized, but not part of a proper name ("Board President Diane Kerrigan").
_TITLE_WORDS = frozenset("""
    admiral agent ambassador archbishop archon aunt bishop board brother captain cardinal ceo cfo
    chair chairman chairperson chairwoman chancellor chief citizen coach colonel commander
    commissioner comrade congressman congresswoman coo councillor councilor councilman
    councilwoman count countess cto dame dean deputy detective director doctor dr duchess duke
    emir emperor empress executive father founder general governor head inspector judge justice
    king lady lieutenant lord madam madame manager master mayor member minister miss mister mr
    mrs ms officer pastor pharaoh pope premier president priest prime prince princess principal
    prof professor provost queen rabbi rector rep representative rev reverend saint secretary
    senator sergeant sheikh sir sister speaker spokesman spokesperson spokeswoman sultan
    superintendent treasurer trustee uncle vice
""".split())


# ---------------------------------------------------------------------------
# Input protocols and small value types
# ---------------------------------------------------------------------------


class EntityLike(Protocol):
    name: str
    type: str | None
    aliases: Sequence[str]
    summary: str
    attributes: Mapping[str, str]


class RelationLike(Protocol):
    source: str
    target: str
    type: str
    fact: str
    valid_at: str | None
    invalid_at: str | None
    chunks: Sequence[int]
    attributes: Mapping[str, str]


class InvalidationLike(Protocol):
    id: str
    invalid_at: str | None


class EpisodeLike(Protocol):
    uuid: str
    content: str
    reference_time: str
    reference_time_explicit: bool
    chunk: int | None


@dataclass(frozen=True)
class EpisodeRef:
    """Minimal episode view used for evidence and node links."""

    uuid: str
    content: str
    reference_time: str
    reference_time_explicit: bool = False
    chunk: int | None = None


@dataclass
class MergedEntity:
    """One entity after type mapping, attribute filtering and in-window merging."""

    name: str
    entity_type: str | None
    aliases: list[str] = field(default_factory=list)
    summary: str = ""
    attributes: dict[str, str] = field(default_factory=dict)
    # Every surface form seen in the response (name, aliases, merged names).
    names: list[str] = field(default_factory=list)
    # The ``name`` of every response entity merged into this one (never an alias).
    own_names: list[str] = field(default_factory=list)

    def keys(self) -> set[str]:
        """Every key: names, aliases and their honorific-free forms."""

        return alias_keys(self.name, [*self.aliases, *self.names])

    def name_keys(self) -> set[str]:
        """Keys of the entity's own names only (honorific-free forms included).

        Matches are anchored on these: an alias shared by two entities ("the
        accuser") never makes them one.
        """

        return alias_keys(self.name, self.own_names)


@dataclass(frozen=True)
class ResolvedNode:
    uuid: str
    name: str
    entity_type: str | None
    created: bool = False


@dataclass
class WriteStats:
    """Counters for one ``write_extraction`` call (logged by the caller)."""

    nodes_created: int = 0
    nodes_updated: int = 0
    edges_created: int = 0
    edges_merged: int = 0
    edges_invalidated: int = 0
    entities_dropped: int = 0
    relations_dropped: int = 0
    node_uuids: list[str] = field(default_factory=list)
    edge_uuids: list[str] = field(default_factory=list)

    def add(self, other: "WriteStats") -> None:
        for name in ("nodes_created", "nodes_updated", "edges_created", "edges_merged",
                     "edges_invalidated", "entities_dropped", "relations_dropped"):
            setattr(self, name, getattr(self, name) + getattr(other, name))
        self.node_uuids.extend(u for u in other.node_uuids if u not in self.node_uuids)
        self.edge_uuids.extend(u for u in other.edge_uuids if u not in self.edge_uuids)

    def as_dict(self) -> dict[str, int]:
        return {
            "nodes_created": self.nodes_created,
            "nodes_updated": self.nodes_updated,
            "edges_created": self.edges_created,
            "edges_merged": self.edges_merged,
            "edges_invalidated": self.edges_invalidated,
            "entities_dropped": self.entities_dropped,
            "relations_dropped": self.relations_dropped,
        }


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _chunks(values: Sequence[Any], size: int = _IN_CHUNK) -> Iterable[Sequence[Any]]:
    for start in range(0, len(values), size):
        yield values[start:start + size]


def _placeholders(count: int) -> str:
    return ",".join("?" * count)


def _split_aliases(text: Any) -> list[str]:
    if not isinstance(text, str) or not text:
        return []
    return [part.strip() for part in text.split(_ALIAS_SEPARATOR.strip()) if part.strip()]


def _display_aliases(name: str, candidates: Iterable[str]) -> list[str]:
    """Distinct surface forms other than ``name`` (by name key), capped."""

    own = name_key(name)
    seen = {own} if own else set()
    result: list[str] = []
    for alias in candidates:
        if not isinstance(alias, str):
            continue
        alias = alias.strip()
        key = name_key(alias)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(alias)
        if len(result) >= MAX_DISPLAY_ALIASES:
            break
    return result


def _attributes_text(attributes: Mapping[str, Any]) -> str:
    return "\n".join(f"{key}: {value}" for key, value in attributes.items())


def _labels(entity_type: str | None) -> list[str]:
    return ["Entity", entity_type] if entity_type else ["Entity"]


def _types_compatible(a: str | None, b: str | None) -> bool:
    """Same custom type, or at least one generic."""

    return a is None or b is None or a == b


def _fallback_family(entity_type: str | None) -> str | None:
    """``"person"`` / ``"organization"`` for the catch-all types, else ``None``."""

    if not entity_type:
        return None
    return FALLBACK_ENTITY_TYPES.get(_TYPE_KEY_RE.sub("", entity_type).casefold())


def _singular_forms(word: str) -> list[str]:
    forms = [word]
    if word.endswith("ies") and len(word) > 4:
        forms.append(word[:-3] + "y")
    if word.endswith("es") and len(word) > 3:
        forms.append(word[:-2])
    if word.endswith("s") and len(word) > 2:
        forms.append(word[:-1])
    return forms


def _type_family(entity_type: str) -> str:
    """``"person"``, ``"organization"`` or ``"other"``, from the type's head noun.

    ``"MediaOutlet"`` and ``"GovernmentAgency"`` are organizations,
    ``"Product"`` and ``"City"`` are not actors, and anything else
    (``"Philosopher"``, ``"GovernmentOfficial"``) is a person.
    """

    family = _fallback_family(entity_type)
    if family:
        return family
    words = _CAMEL_SPLIT_RE.sub(" ", re.sub(r"[^0-9A-Za-z]+", " ", entity_type)).split()
    head = words[-1].casefold() if words else ""
    for form in _singular_forms(head):
        if form in _ORGANIZATION_TYPE_WORDS:
            return "organization"
        if form in _NON_ACTOR_TYPE_WORDS:
            return "other"
    return "person"


def _fallback_compatible(a: str | None, b: str | None) -> bool:
    """Two different custom types where one is a fallback of the other's family.

    ``Person``/``Philosopher`` and ``Organization``/``MediaOutlet`` are; the two
    fallbacks together, ``Organization``/``Product`` and two specific types are
    not.
    """

    if not a or not b or a == b:
        return False
    family_a, family_b = _fallback_family(a), _fallback_family(b)
    if family_a and family_b:
        return False
    if family_a:
        return _type_family(b) == family_a
    if family_b:
        return _type_family(a) == family_b
    return False


def _preferred_type(existing: str | None, new: str | None) -> str | None:
    """The type a node keeps when an entity of type ``new`` resolves to it.

    A generic side takes the other side's type, and a fallback type
    (``Person``) gives way to a more specific one (``Philosopher``).
    """

    if existing is None:
        return new
    if new is None or new == existing:
        return existing
    if _fallback_family(existing) and not _fallback_family(new):
        return new
    return existing


def _type_rank(entity_type: str | None) -> int:
    """Survivor preference in a merge: specific type, then fallback type, then generic."""

    if not entity_type:
        return 2
    return 1 if _fallback_family(entity_type) else 0


def _own_name_keys(name: str, stored_key: str | None = None) -> set[str]:
    """Keys of a node's own name (plus its honorific-free forms)."""

    keys = alias_keys(name) if isinstance(name, str) else set()
    if stored_key:
        keys.add(stored_key)
    return keys


def _share_one_name(key_sets: Sequence[Iterable[str]]) -> bool:
    """Whether every set in ``key_sets`` contains one common key."""

    sets = [set(keys) for keys in key_sets]
    if not sets:
        return False
    return bool(set.intersection(*sets))


def _types_mergeable(members: Sequence[tuple[str | None, Iterable[str]]]) -> bool:
    """A merge group holds at most one custom type, or custom types that share one name.

    ``members`` are ``(entity_type, own name keys)``. Different custom types
    under the same name are type drift ("Socrates" [Person] and "Socrates"
    [Philosopher]); under different names they stay separate.
    """

    typed = [(entity_type, keys) for entity_type, keys in members if entity_type]
    if len({entity_type for entity_type, _ in typed}) <= 1:
        return True
    return _share_one_name([keys for _, keys in typed])


def _contains_name(container: str, part: str) -> bool:
    """Whether normalized ``part`` occurs in normalized ``container`` as a whole name."""

    if not container or not part:
        return False
    if is_cjk(part) or is_cjk(container):
        return part in container
    return re.search(rf"(?<![0-9a-z]){re.escape(part)}(?![0-9a-z])", container) is not None


def _is_proper_token(token: str) -> bool:
    """A capitalized name part ("Chen", "O'Brien", "VIII", "11"), not a title or possessive."""

    if token.endswith(("'", "’", "'s", "’s")):
        return False
    core = token.strip(".'’")
    if not core or name_key(core) in _TITLE_WORDS:
        return False
    first = core[0]
    if first.isdigit():
        return True
    if not first.isalpha():
        return False
    return first.isupper() or first.upper() == first.lower()  # caseless scripts


def _adds_only_name_tokens(current: str, candidate: str) -> bool:
    """Whether ``candidate`` is ``current`` plus a few proper-name tokens.

    "Alice" -> "Alice Chen" and "Leonardo" -> "Leonardo da Vinci" are;
    "Socrates of Athens", "Plato the philosopher" and "Board President
    Diane Kerrigan" are not.
    """

    old = [t for t in _NAME_TOKEN_SPLIT_RE.split(current.strip()) if name_key(t)]
    new = [t for t in _NAME_TOKEN_SPLIT_RE.split(candidate.strip()) if name_key(t)]
    old_keys = [name_key(t) for t in old]
    new_keys = [name_key(t) for t in new]
    size = len(old_keys)
    if not size or len(new_keys) <= size:
        return False
    for start in range(len(new_keys) - size + 1):
        if new_keys[start:start + size] != old_keys:
            continue
        added = [i for i in range(len(new)) if not start <= i < start + size]
        if len(added) > MAX_RENAME_ADDED_TOKENS:
            return False
        for i in added:
            token = new[i]
            if _is_proper_token(token):
                continue
            is_particle = token in _NAME_PARTICLES
            if not (is_particle and i + 1 < len(new) and _is_proper_token(new[i + 1])):
                return False
        return True
    return False


def _should_rename(current: str, candidate: str) -> bool:
    """Replace a node name only by a longer proper name that contains it ("Alice" -> "Alice Chen").

    A form that only adds an honorific ("Mr. Wang") stays an alias, and so do
    descriptions and appositions: "Socrates of Athens", "Crito, Socrates'
    oldest friend", "Board President Diane Kerrigan" (see
    :func:`_adds_only_name_tokens`).
    """

    if not candidate or not current or len(candidate.strip()) <= len(current.strip()):
        return False
    if any(ch in _RENAME_BLOCKING_CHARS for ch in candidate):
        return False
    new_norm = normalize_name(candidate)
    if strip_honorifics(candidate) != new_norm:
        return False
    old_norm = normalize_name(current)
    if old_norm == new_norm or not _contains_name(new_norm, old_norm):
        return False
    if is_cjk(candidate) or is_cjk(current):
        return "的" not in candidate  # "雅典的苏格拉底" describes, it does not name
    return _adds_only_name_tokens(current, candidate)


def _clean_value(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _attribute_key(name: str) -> str:
    return _ATTRIBUTE_KEY_RE.sub("_", name.strip()).casefold()


def filter_attributes(attributes: Mapping[str, Any] | None, allowed: Sequence[str]) -> dict[str, str]:
    """Keep only ``allowed`` attribute names (the SAFE names from ``set_ontology``).

    Keys match case-insensitively with spaces and hyphens read as ``_``; the
    result uses the canonical ontology spelling. Empty values are dropped.
    """

    if not attributes or not allowed:
        return {}
    canonical = {_attribute_key(name): name for name in allowed}
    result: dict[str, str] = {}
    for key, value in attributes.items():
        if not isinstance(key, str):
            continue
        name = canonical.get(_attribute_key(key))
        text = _clean_value(value)
        if name and text:
            result[name] = text
    return result


def _merge_attributes(base: Mapping[str, Any], new: Mapping[str, Any], *, new_wins: bool) -> dict[str, Any]:
    merged = dict(base)
    for key, value in new.items():
        if value in (None, ""):
            continue
        if new_wins or merged.get(key) in (None, ""):
            merged[key] = value
    return merged


# ---------------------------------------------------------------------------
# Summaries
# ---------------------------------------------------------------------------


def _needs_space(left: str, right: str) -> bool:
    if not left or not right:
        return False
    return not (is_cjk(left[-1]) or is_cjk(right[0]) or left[-1] in "。！？，；：")


def merge_summary(old: str | None, new: str | None, cap: int = 800) -> str:
    """Accumulate new information without repeating it (spec §4.6).

    Sentences of ``new`` are appended when their key is not already inside
    the summary and they are not a near-duplicate (trigram Jaccard >= 0.8) of
    an existing sentence. Stops before exceeding ``cap`` characters; the
    first summary is kept as is (cut to ``cap`` only if it is longer).
    """

    summary = (old or "").strip()
    if len(summary) > cap:
        summary = summary[:cap].rstrip()
    if not new or not new.strip():
        return summary
    existing = [name_key(sentence) for sentence in split_sentences(summary)]
    for sentence in split_sentences(new):
        key = name_key(sentence)
        if not key:
            continue
        if key in name_key(summary) or any(
            trigram_jaccard(key, other) >= SUMMARY_DEDUP_JACCARD for other in existing
        ):
            continue
        if not summary:
            summary = sentence[:cap].rstrip()
            existing.append(key)
            continue
        separator = " " if _needs_space(summary, sentence) else ""
        if len(summary) + len(separator) + len(sentence) > cap:
            break
        summary = f"{summary}{separator}{sentence}"
        existing.append(key)
    return summary


# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------


def _absorb_entity(target: MergedEntity, item: MergedEntity, summary_cap: int) -> None:
    target.entity_type = _preferred_type(target.entity_type, item.entity_type)
    target.own_names.extend(n for n in item.own_names if n not in target.own_names)
    if _should_rename(target.name, item.name):
        target.aliases.append(target.name)
        target.name = item.name
    else:
        target.aliases.append(item.name)
    target.aliases = _display_aliases(target.name, [*target.aliases, *item.aliases])
    target.attributes = _merge_attributes(target.attributes, item.attributes, new_wins=True)
    target.summary = merge_summary(target.summary, item.summary, summary_cap)
    target.names.extend(n for n in item.names if n not in target.names)


@dataclass
class PreparedEntities:
    """Output of :func:`prepare_entities`."""

    entities: list[MergedEntity]
    # Alias keys of entities dropped by strict mode; relations naming them are dropped.
    dropped_keys: set[str] = field(default_factory=set)
    dropped: int = 0


def prepare_entities(
    entities: Iterable[EntityLike],
    ontology: OntologyView,
    *,
    strict: bool = False,
    summary_cap: int = 800,
) -> PreparedEntities:
    """Map types, filter attributes and merge same-window duplicates.

    Two entities merge only when one's own name key is among the other's
    keys ("IBM" and "International Business Machines" with alias "IBM"); a
    shared alias alone ("the accuser") never merges them. They must also
    carry compatible types: the same custom type or a generic one, or, under
    the same name, a fallback type and a more specific type of its family
    (the specific type wins). Other homonyms stay separate. With ``strict``
    (and an ontology that defines entity types), entities of no ontology type
    are dropped and their keys reported so relations naming them can be
    dropped.
    """

    strict_entities = strict and bool(ontology.entity_types)
    prepared = PreparedEntities(entities=[])
    dropped = prepared.dropped_keys
    merged = prepared.entities
    by_key: dict[str, list[int]] = {}   # any key of a merged entity -> positions
    by_name: dict[str, list[int]] = {}  # own-name key of a merged entity -> positions
    for entity in entities:
        name = _clean_value(getattr(entity, "name", ""))
        if not name:
            continue
        aliases = [a for a in (getattr(entity, "aliases", None) or []) if isinstance(a, str)]
        entity_type = ontology.match_entity_type(getattr(entity, "type", None))
        if strict_entities and entity_type is None:
            dropped |= alias_keys(name, aliases)
            prepared.dropped += 1
            continue
        item = MergedEntity(
            name=name,
            entity_type=entity_type,
            aliases=_display_aliases(name, aliases),
            summary=merge_summary("", getattr(entity, "summary", "") or "", summary_cap),
            attributes=filter_attributes(
                getattr(entity, "attributes", None), ontology.entity_attribute_names(entity_type)
            ),
            names=[name, *[a for a in aliases if a.strip()]],
            own_names=[name],
        )
        item_names = item.name_keys()
        positions: set[int] = set()
        for key in item_names:
            positions.update(by_key.get(key, ()))
        for key in item.keys():
            positions.update(by_name.get(key, ()))
        target: int | None = None
        for position in sorted(positions):
            other = merged[position]
            if _types_compatible(other.entity_type, item.entity_type) or (
                _fallback_compatible(other.entity_type, item.entity_type)
                and other.name_keys() & item_names
            ):
                target = position
                break
        if target is None:
            merged.append(item)
            target = len(merged) - 1
        else:
            _absorb_entity(merged[target], item, summary_cap)
        for index, keys in ((by_key, merged[target].keys()), (by_name, merged[target].name_keys())):
            for key in keys:
                slots = index.setdefault(key, [])
                if target not in slots:
                    slots.append(target)
    return prepared


def _nodes_registered_under(conn: sqlite3.Connection, graph_id: str,
                            keys: Sequence[str]) -> list[sqlite3.Row]:
    """Nodes whose ``name_key`` or any alias key is in ``keys``."""

    rows: list[sqlite3.Row] = []
    for part in _chunks(keys):
        marks = _placeholders(len(part))
        rows.extend(conn.execute(
            f"SELECT * FROM nodes WHERE graph_id = ? AND (name_key IN ({marks}) OR uuid IN ("
            f"SELECT node_uuid FROM node_aliases WHERE graph_id = ? AND alias_key IN ({marks})))",
            (graph_id, *part, graph_id, *part),
        ).fetchall())
    return rows


def find_candidates(conn: sqlite3.Connection, graph_id: str, keys: Iterable[str], *,
                    extra_name_keys: Iterable[str] = ()) -> list[sqlite3.Row]:
    """Nodes of ``graph_id`` that match an entity's names, most mentioned first.

    ``keys`` are the entity's own name keys: they match a node's
    ``name_key`` or any of its alias keys. ``extra_name_keys`` (the entity's
    alias keys) match only a node's own name, so two entities that merely
    share an alias ("the accuser", a shared first name) never resolve to
    each other.
    """

    own = sorted({key for key in keys if key})
    extra = sorted({key for key in extra_name_keys if key} - set(own))
    found: dict[str, sqlite3.Row] = {}
    for row in _nodes_registered_under(conn, graph_id, own):
        found.setdefault(row["uuid"], row)
    if extra:
        wanted = set(extra)
        for row in _nodes_registered_under(conn, graph_id, extra):
            if row["uuid"] not in found and _own_name_keys(row["name"], row["name_key"]) & wanted:
                found[row["uuid"]] = row
    return sorted(found.values(), key=lambda row: (-int(row["mention_count"] or 0), row["id"]))


def choose_candidate(candidates: Sequence[sqlite3.Row], entity_type: str | None, *,
                     name_keys: Iterable[str] = ()) -> sqlite3.Row | None:
    """Pick the node to reuse (spec §4.6 step 2); ``None`` means create a new one.

    Candidates must already be sorted by ``mention_count`` descending. In
    order: a node of the same type, a generic node, then (type drift) a node
    whose own name is one of ``name_keys`` and whose type is a fallback of the
    entity type's family, or the reverse ("Socrates" [Person] for an entity
    "Socrates" [Philosopher]). Only other custom types left: a homonym.
    """

    if not candidates:
        return None
    if entity_type is None:
        return candidates[0]
    for row in candidates:
        if row["entity_type"] == entity_type:
            return row
    for row in candidates:
        if row["entity_type"] is None:
            return row
    wanted = {key for key in name_keys if key}
    if wanted:
        for row in candidates:
            if (_fallback_compatible(row["entity_type"], entity_type)
                    and _own_name_keys(row["name"], row["name_key"]) & wanted):
                return row
    return None  # only other custom types: a homonym


def resolve_existing(conn: sqlite3.Connection, graph_id: str, name: str,
                     aliases: Sequence[str] = ()) -> sqlite3.Row | None:
    """The node registered under ``name`` (or named like one of ``aliases``).

    A node named ``name`` wins (exact key first, then an honorific-free
    form), most mentioned first. A name found only among the aliases of
    several nodes ("the accuser") is ambiguous and resolves to ``None``.
    """

    return _resolve_existing(conn, graph_id, name, aliases)[0]


def _resolve_existing(conn: sqlite3.Connection, graph_id: str, name: str,
                      aliases: Sequence[str] = ()) -> tuple[sqlite3.Row | None, bool]:
    """:func:`resolve_existing` plus whether ``name`` was ambiguous."""

    exact = name_key(name)
    own = alias_keys(name)
    candidates = find_candidates(conn, graph_id, own, extra_name_keys=alias_keys(name, aliases))
    if not candidates:
        return None, False
    for row in candidates:
        if row["name_key"] == exact:
            return row, False
    for row in candidates:
        if _own_name_keys(row["name"], row["name_key"]) & own:
            return row, False
    if len(candidates) == 1:
        return candidates[0], False
    return None, True


def _insert_alias_keys(conn: sqlite3.Connection, graph_id: str, node_uuid: str, keys: Iterable[str]) -> None:
    conn.executemany(
        "INSERT OR IGNORE INTO node_aliases(graph_id, alias_key, node_uuid) VALUES (?, ?, ?)",
        [(graph_id, key, node_uuid) for key in sorted(set(keys)) if key],
    )


def create_node(
    conn: sqlite3.Connection,
    graph_id: str,
    *,
    name: str,
    entity_type: str | None = None,
    summary: str = "",
    attributes: Mapping[str, str] | None = None,
    aliases: Sequence[str] = (),
    origin: str = "llm",
    now: str | None = None,
) -> ResolvedNode:
    """Insert a node plus its alias keys."""

    now = now or utcnow_iso()
    node_uuid = new_id()
    display = _display_aliases(name, aliases)
    attributes = dict(attributes or {})
    conn.execute(
        "INSERT INTO nodes(uuid, graph_id, name, name_key, entity_type, labels_json, summary, "
        "attributes_json, aliases_text, attributes_text, origin, mention_count, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)",
        (node_uuid, graph_id, name, name_key(name), entity_type, json_dumps(_labels(entity_type)),
         summary or "", json_dumps(attributes), _ALIAS_SEPARATOR.join(display),
         _attributes_text(attributes), origin, now, now),
    )
    _insert_alias_keys(conn, graph_id, node_uuid, alias_keys(name, display))
    return ResolvedNode(node_uuid, name, entity_type, created=True)


def _update_node(conn: sqlite3.Connection, row: sqlite3.Row, entity: MergedEntity, *,
                 summary_cap: int, now: str) -> ResolvedNode:
    name = row["name"]
    aliases = _split_aliases(row["aliases_text"])
    if _should_rename(name, entity.name):
        aliases.append(name)
        name = entity.name
    aliases = _display_aliases(name, [*aliases, *entity.names, *entity.aliases])
    entity_type = _preferred_type(row["entity_type"], entity.entity_type)
    attributes = _merge_attributes(json_loads(row["attributes_json"], {}) or {}, entity.attributes,
                                   new_wins=True)
    summary = merge_summary(row["summary"], entity.summary, summary_cap)
    conn.execute(
        "UPDATE nodes SET name = ?, name_key = ?, entity_type = ?, labels_json = ?, summary = ?, "
        "attributes_json = ?, aliases_text = ?, attributes_text = ?, "
        "mention_count = mention_count + 1, updated_at = ? WHERE uuid = ?",
        (name, name_key(name), entity_type, json_dumps(_labels(entity_type)), summary,
         json_dumps(attributes), _ALIAS_SEPARATOR.join(aliases), _attributes_text(attributes),
         now, row["uuid"]),
    )
    _insert_alias_keys(conn, row["graph_id"], row["uuid"], alias_keys(name, aliases) | entity.keys())
    return ResolvedNode(row["uuid"], name, entity_type, created=False)


def resolve_or_create(
    conn: sqlite3.Connection,
    graph_id: str,
    entity: MergedEntity,
    *,
    summary_cap: int = 800,
    now: str | None = None,
    origin: str = "llm",
) -> ResolvedNode:
    """Reuse the matching node (updating it) or create one (spec §4.6).

    Candidates are anchored on a name (:func:`find_candidates`). A typed
    entity reuses a node of the same type, else upgrades a generic one, else
    reuses a node of the same name whose type drifted between a fallback and
    a more specific type (the specific type is kept). A generic entity reuses
    the most mentioned candidate. When only homonyms of a different custom
    type exist, a new node is created.
    """

    now = now or utcnow_iso()
    own = entity.name_keys()
    candidates = find_candidates(conn, graph_id, own, extra_name_keys=entity.keys())
    row = choose_candidate(candidates, entity.entity_type, name_keys=own)
    if row is None:
        return create_node(
            conn, graph_id, name=entity.name, entity_type=entity.entity_type,
            summary=entity.summary, attributes=entity.attributes,
            aliases=[*entity.aliases, *entity.names], origin=origin, now=now,
        )
    return _update_node(conn, row, entity, summary_cap=summary_cap, now=now)


def link_node_episodes(conn: sqlite3.Connection, node_uuid: str, episode_uuids: Iterable[str]) -> None:
    conn.executemany(
        "INSERT OR IGNORE INTO node_episodes(node_uuid, episode_uuid) VALUES (?, ?)",
        [(node_uuid, episode) for episode in dict.fromkeys(episode_uuids) if episode],
    )


def episodes_mentioning(episodes: Sequence[EpisodeLike], names: Iterable[str],
                        *, require_all: Sequence[Iterable[str]] | None = None) -> list[str]:
    """Uuids of episodes whose content (casefolded) contains any of ``names``.

    With ``require_all``, each group of names must be matched (used for "both
    endpoints are mentioned").
    """

    groups = [list(group) for group in require_all] if require_all is not None else [list(names)]
    groups = [[n.casefold() for n in group if isinstance(n, str) and n.strip()] for group in groups]
    if not groups or any(not group for group in groups):
        return []
    result: list[str] = []
    for episode in episodes:
        content = (episode.content or "").casefold()
        compact = compact_text(episode.content or "")
        if all(any(n in content or (name_key(n) and name_key(n) in compact) for n in group)
               for group in groups):
            result.append(episode.uuid)
    return result


# ---------------------------------------------------------------------------
# Edges
# ---------------------------------------------------------------------------


def bump_graph_version(conn: sqlite3.Connection, graph_id: str) -> None:
    """Invalidate per-graph caches (search mention cache) keyed by ``graphs.version``."""

    conn.execute("UPDATE graphs SET version = version + 1 WHERE graph_id = ?", (graph_id,))


def _similar_fact_allowed(name: str, same_direction: bool) -> bool:
    """Whether a near-duplicate (not identical) fact may fold into an edge.

    Only in the same direction, or for a symmetric relation: with long names,
    "A persuaded B to ..." and "B persuaded A to ..." score above the
    threshold but state opposite facts.
    """

    return same_direction or name in SYMMETRIC_RELATIONS


def _is_duplicate_edge(a: Mapping[str, Any], b: Mapping[str, Any]) -> bool:
    """Two edge rows on the same endpoints and relation that state the same fact."""

    key_a, key_b = a["fact_key"], b["fact_key"]
    if not key_a or not key_b:
        return False
    if key_a == key_b:
        return True
    same_direction = a["source_node_uuid"] == b["source_node_uuid"]
    return (_similar_fact_allowed(a["name"], same_direction)
            and trigram_jaccard(key_a, key_b) >= EDGE_DEDUP_JACCARD)


def find_duplicate_edge(conn: sqlite3.Connection, graph_id: str, name: str, source_uuid: str,
                        target_uuid: str, fact_key: str) -> sqlite3.Row | None:
    """An active edge with the same relation, endpoints and fact (spec §4.7).

    An identical fact key matches in either direction (the LLM may swap the
    endpoints of the same sentence); a merely similar fact (trigram Jaccard
    >= 0.8) matches only in the same direction, or in both for a symmetric
    relation.
    """

    rows = conn.execute(
        "SELECT * FROM edges WHERE graph_id = ? AND name = ? AND ("
        "(source_node_uuid = ? AND target_node_uuid = ?) OR "
        "(source_node_uuid = ? AND target_node_uuid = ?)) "
        f"AND {_ACTIVE_EDGE} ORDER BY id",
        (graph_id, name, source_uuid, target_uuid, target_uuid, source_uuid),
    ).fetchall()
    best: sqlite3.Row | None = None
    best_score = 0.0
    for row in rows:
        if row["fact_key"] == fact_key:
            return row
        if not _similar_fact_allowed(name, row["source_node_uuid"] == source_uuid):
            continue
        score = trigram_jaccard(row["fact_key"], fact_key)
        if score >= EDGE_DEDUP_JACCARD and score > best_score:
            best, best_score = row, score
    return best


def _link_edge_episodes(conn: sqlite3.Connection, edge_uuid: str, episode_uuids: Iterable[str],
                        now: str) -> None:
    conn.executemany(
        "INSERT OR IGNORE INTO edge_episodes(edge_uuid, episode_uuid, linked_at) VALUES (?, ?, ?)",
        [(edge_uuid, episode, now) for episode in dict.fromkeys(episode_uuids) if episode],
    )


def upsert_edge(
    conn: sqlite3.Connection,
    graph_id: str,
    *,
    name: str,
    fact: str,
    source_uuid: str,
    target_uuid: str,
    attributes: Mapping[str, str] | None = None,
    valid_at: str | None = None,
    invalid_at: str | None = None,
    episode_uuids: Iterable[str] = (),
    origin: str = "llm",
    now: str | None = None,
) -> tuple[str, bool]:
    """Insert an edge, or fold it into an active duplicate (spec §4.7).

    Returns ``(edge_uuid, created)``. On a duplicate the episode links are
    added, a missing ``valid_at`` / ``invalid_at`` is filled and new
    non-empty attribute values win; no new edge is created.
    """

    now = now or utcnow_iso()
    episodes = list(dict.fromkeys(episode_uuids))
    fact_key = name_key(fact)
    duplicate = find_duplicate_edge(conn, graph_id, name, source_uuid, target_uuid, fact_key)
    if duplicate is not None:
        merged = _merge_attributes(json_loads(duplicate["attributes_json"], {}) or {},
                                   dict(attributes or {}), new_wins=True)
        conn.execute(
            "UPDATE edges SET valid_at = COALESCE(valid_at, ?), invalid_at = COALESCE(invalid_at, ?), "
            "attributes_json = ? WHERE uuid = ?",
            (valid_at, invalid_at, json_dumps(merged), duplicate["uuid"]),
        )
        _link_edge_episodes(conn, duplicate["uuid"], episodes, now)
        return duplicate["uuid"], False
    edge_uuid = new_id()
    conn.execute(
        "INSERT INTO edges(uuid, graph_id, name, fact, fact_key, source_node_uuid, target_node_uuid, "
        "attributes_json, origin, created_at, valid_at, invalid_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (edge_uuid, graph_id, name, fact, fact_key, source_uuid, target_uuid,
         json_dumps(dict(attributes or {})), origin, now, valid_at, invalid_at),
    )
    _link_edge_episodes(conn, edge_uuid, episodes, now)
    return edge_uuid, True


def invalidate_edge(conn: sqlite3.Connection, edge_uuid: str, *, invalid_at: str | None,
                    now: str | None = None) -> bool:
    """Mark an active edge historical: ``invalid_at`` is world time, ``expired_at`` system time."""

    now = now or utcnow_iso()
    cursor = conn.execute(
        "UPDATE edges SET invalid_at = COALESCE(?, invalid_at), expired_at = ? "
        f"WHERE uuid = ? AND {_ACTIVE_EDGE}",
        (invalid_at, now, edge_uuid),
    )
    return cursor.rowcount > 0


# ---------------------------------------------------------------------------
# One extraction window
# ---------------------------------------------------------------------------


def _latest_explicit_time(episodes: Iterable[EpisodeLike]) -> str | None:
    times = [ep.reference_time for ep in episodes if ep.reference_time_explicit and ep.reference_time]
    return max(times) if times else None


# Endpoint words that make a phrase a list of entities ("Alice and Crito").
_LIST_WORDS = frozenset({"and", "or", "nor", "plus", "with", "versus", "vs", "und", "et", "&"})
# Words that open a description after a name ("Socrates of Athens", "Plato the philosopher").
_APPOSITION_WORDS = frozenset({"of", "from", "the", "in", "at", "who", "called", "aka", "known"})
_POSSESSIVE_SUFFIXES = ("'", "’", "'s", "’s")


def _endpoint_tokens(text: str) -> list[tuple[str, str]]:
    """``(surface token, key)`` pairs of a non-CJK name split on whitespace (``[]`` for CJK)."""

    text = unicodedata.normalize("NFKC", text or "").strip()
    if not text or is_cjk(text):
        return []
    return [(token, name_key(token)) for token in text.split()]


def _is_capitalized(token: str) -> bool:
    core = token.lstrip("\"'“‘([")
    return bool(core) and (core[0].isdigit() or (core[0].isalpha() and (
        core[0].isupper() or core[0].upper() == core[0].lower())))


def _affix_names_entity(raw: list[tuple[str, str]], entity: Sequence[str]) -> bool:
    """Whether endpoint tokens ``raw`` name the entity with keys ``entity`` plus a description.

    Prefix: an apposition after the name ("Socrates of Athens", "Crito,
    Socrates' oldest friend"), never a possessive ("Socrates' trial") or a
    compound ("Athens University"). Suffix: only capitalized titles or name
    parts before it ("Board President Diane Kerrigan"), never "Mother of
    Socrates".
    """

    keyed = [(index, key) for index, (_, key) in enumerate(raw) if key]
    keys = [key for _, key in keyed]
    size = len(entity)
    if not size or size >= len(keys) or len("".join(entity)) < 2:
        return False
    if keys[:size] == list(entity):
        last, following = keyed[size - 1][0], keyed[size][0]
        last_token = raw[last][0]
        if last_token.endswith(_POSSESSIVE_SUFFIXES):
            return False
        apposition = (
            last_token.endswith((",", ":"))
            or following > last + 1  # a dash or other punctuation-only token in between
            or raw[following][0].startswith(("(", "["))
        )
        if apposition:
            # "Alice, Bob" is a list; a description has a lowercase word.
            return not all(_is_capitalized(raw[index][0]) for index, _ in keyed[size:])
        return keys[size] in _APPOSITION_WORDS
    if keys[-size:] == list(entity):
        leading = raw[:keyed[-size][0]]
        return all(
            key and _is_capitalized(token) and not token.endswith((",", ":", *_POSSESSIVE_SUFFIXES))
            for token, key in leading
        )
    return False


class _WindowIndex:
    """Where a window's relation endpoints resolve (spec §4.6 "Relation endpoints").

    Own names (an entity's names, or an endpoint name already resolved) win
    over aliases, and an alias shared by two nodes of the window is
    ambiguous: it resolves to no node.
    """

    def __init__(self) -> None:
        self.names: dict[str, ResolvedNode] = {}
        self.aliases: dict[str, dict[str, ResolvedNode]] = {}
        self.entity_tokens: list[tuple[tuple[str, ...], ResolvedNode]] = []

    def add_entity(self, entity: MergedEntity, node: ResolvedNode) -> None:
        for key in sorted(entity.name_keys() | alias_keys(node.name)):
            self.names.setdefault(key, node)
        for key in sorted(entity.keys()):
            self.aliases.setdefault(key, {})[node.uuid] = node
        for name in dict.fromkeys((entity.name, node.name)):
            tokens = tuple(key for _, key in _endpoint_tokens(name) if key)
            if tokens:
                self.entity_tokens.append((tokens, node))

    def add_name(self, raw: str, node: ResolvedNode) -> None:
        for key in sorted(alias_keys(raw)):
            self.names.setdefault(key, node)

    def _keys(self, raw: str) -> list[str]:
        exact = name_key(raw)
        return [exact, *sorted(alias_keys(raw) - {exact})]

    def lookup(self, raw: str) -> ResolvedNode | None:
        keys = self._keys(raw)
        for key in keys:
            if key in self.names:
                return self.names[key]
        for key in keys:
            nodes = self.aliases.get(key)
            if nodes and len(nodes) == 1:
                return next(iter(nodes.values()))
        return None

    def is_ambiguous(self, raw: str) -> bool:
        """``raw`` is only an alias, shared by several of the window's nodes."""

        keys = self._keys(raw)
        if any(key in self.names for key in keys):
            return False
        return any(len(self.aliases.get(key, ())) > 1 for key in keys)

    def affix_match(self, raw: str) -> ResolvedNode | None:
        """The one window entity that ``raw`` names with a description attached.

        "Socrates of Athens" resolves to the entity "Socrates" (see
        :func:`_affix_names_entity`); lists ("Alice and Crito") and phrases
        matching several entities resolve to none.
        """

        tokens = _endpoint_tokens(raw)
        if len(tokens) < 2 or any(key in _LIST_WORDS or token == "&" for token, key in tokens):
            return None
        found: dict[str, ResolvedNode] = {}
        for entity_tokens, node in self.entity_tokens:
            if _affix_names_entity(tokens, entity_tokens):
                found[node.uuid] = node
        return next(iter(found.values())) if len(found) == 1 else None


def write_extraction(
    conn: sqlite3.Connection,
    graph_id: str,
    *,
    entities: Iterable[EntityLike],
    relations: Iterable[RelationLike],
    invalidated_facts: Iterable[InvalidationLike] = (),
    episodes: Sequence[EpisodeLike],
    ontology: OntologyView,
    fact_map: Mapping[str, str] | None = None,
    strict: bool = False,
    summary_cap: int = 800,
    now: str | None = None,
    origin: str = "llm",
) -> WriteStats:
    """Apply one validated extraction to the graph (spec §4.6-§4.7).

    Runs inside the caller's write transaction. ``episodes`` are the
    window's episodes (evidence and node links); ``fact_map`` maps the
    prompt's short fact ids (``F1``...) to the edge uuids offered to the LLM.
    """

    now = now or utcnow_iso()
    stats = WriteStats()
    episode_list = list(episodes)
    all_episode_uuids = [ep.uuid for ep in episode_list]
    chunk_map = {ep.chunk: ep.uuid for ep in episode_list if ep.chunk is not None}
    window_time = _latest_explicit_time(episode_list)
    reference_by_uuid = {ep.uuid: ep for ep in episode_list}

    prepared = prepare_entities(entities, ontology, strict=strict, summary_cap=summary_cap)
    dropped_keys = prepared.dropped_keys
    stats.entities_dropped = prepared.dropped
    window = _WindowIndex()
    names_by_node: dict[str, list[str]] = {}
    for entity in prepared.entities:
        node = resolve_or_create(conn, graph_id, entity, summary_cap=summary_cap, now=now, origin=origin)
        if node.created:
            stats.nodes_created += 1
        else:
            stats.nodes_updated += 1
        if node.uuid not in stats.node_uuids:
            stats.node_uuids.append(node.uuid)
        window.add_entity(entity, node)
        surface = [*entity.names, node.name]
        names_by_node.setdefault(node.uuid, []).extend(surface)
        linked = episodes_mentioning(episode_list, surface) or all_episode_uuids
        link_node_episodes(conn, node.uuid, linked)

    strict_edges = strict and bool(ontology.edge_types)
    strict_entities = strict and bool(ontology.entity_types)
    reasserted: set[str] = set()
    for relation in relations:
        endpoints: list[ResolvedNode] = []
        for raw in (relation.source, relation.target):
            node = window.lookup(raw)
            if node is None and alias_keys(raw) & dropped_keys:
                break  # names an entity strict mode dropped
            if node is None:
                row, ambiguous = _resolve_existing(conn, graph_id, raw)
                ambiguous = ambiguous or window.is_ambiguous(raw)
                if row is not None:
                    node = ResolvedNode(row["uuid"], row["name"], row["entity_type"])
                elif not ambiguous:
                    # "Socrates of Athens" for the window's entity "Socrates".
                    node = window.affix_match(raw)
                if node is None:
                    if ambiguous:
                        break  # an alias of several entities ("the accuser"): do not guess
                    if strict_entities:
                        break  # would create a generic node, which strict mode forbids
                    node = create_node(conn, graph_id, name=raw.strip(), now=now, origin=origin)
                    stats.nodes_created += 1
                    stats.node_uuids.append(node.uuid)
                window.add_name(raw, node)
                names_by_node.setdefault(node.uuid, []).extend([raw, node.name])
            endpoints.append(node)
        if len(endpoints) != 2:
            stats.relations_dropped += 1
            continue
        source, target = endpoints
        if source.uuid == target.uuid:
            stats.relations_dropped += 1
            continue
        match = ontology.match_edge_type(relation.type, source.entity_type, target.entity_type,
                                         strict=strict_edges)
        if match is None:
            stats.relations_dropped += 1
            continue
        if match.swap:
            source, target = target, source
        edge_attributes = filter_attributes(
            getattr(relation, "attributes", None),
            ontology.edge_attribute_names(match.name) if match.definition is not None else [],
        )

        evidence = [chunk_map[c] for c in dict.fromkeys(relation.chunks or []) if c in chunk_map]
        if not evidence:
            evidence = episodes_mentioning(
                episode_list, (),
                require_all=[names_by_node.get(source.uuid, [source.name]),
                             names_by_node.get(target.uuid, [target.name])],
            )
        if not evidence:
            evidence = list(all_episode_uuids)

        valid_at = parse_iso_date(relation.valid_at)
        if valid_at is None:
            valid_at = _latest_explicit_time(
                reference_by_uuid[uuid] for uuid in evidence if uuid in reference_by_uuid
            )
        invalid_at = parse_iso_date(relation.invalid_at)

        edge_uuid, created = upsert_edge(
            conn, graph_id, name=match.name, fact=relation.fact, source_uuid=source.uuid,
            target_uuid=target.uuid, attributes=edge_attributes, valid_at=valid_at,
            invalid_at=invalid_at, episode_uuids=evidence, origin=origin, now=now,
        )
        if created:
            stats.edges_created += 1
        else:
            stats.edges_merged += 1
            reasserted.add(edge_uuid)
        if edge_uuid not in stats.edge_uuids:
            stats.edge_uuids.append(edge_uuid)
        link_node_episodes(conn, source.uuid, evidence)
        link_node_episodes(conn, target.uuid, evidence)

    offered = dict(fact_map or {})
    for item in invalidated_facts:
        edge_uuid = offered.get(getattr(item, "id", None) or "")
        if edge_uuid is None:
            continue  # not offered in this prompt: a hallucinated id
        if edge_uuid in reasserted:
            continue  # the same response restated the fact; keep it active
        invalid_at = parse_iso_date(getattr(item, "invalid_at", None)) or window_time
        if invalidate_edge(conn, edge_uuid, invalid_at=invalid_at, now=now):
            stats.edges_invalidated += 1

    bump_graph_version(conn, graph_id)
    return stats


# ---------------------------------------------------------------------------
# Post-batch entity dedup pass (spec §4.8): candidates and merges
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DedupNode:
    """Precomputed features of one node for candidate generation."""

    uuid: str
    graph_id: str
    name: str
    key: str
    entity_type: str | None
    summary: str
    mention_count: int
    id: int
    tokens: tuple[str, ...]
    grams: frozenset[str]
    latin: bool
    initials: frozenset[str]
    # Keys of the node's own name (``key`` plus honorific-free forms).
    name_keys: frozenset[str] = frozenset()

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "DedupNode":
        name = row["name"] or ""
        key = row["name_key"] or name_key(name)
        tokens = tuple(t for t in _TOKEN_SPLIT_RE.split(normalize_name(name)) if t)
        raw_tokens = [t for t in re.split(r"[\s\-]+", name.strip()) if t]
        initials = set()
        if len(raw_tokens) >= 2:
            letters = [t[0] for t in raw_tokens if t[0].isalpha()]
            initials.add("".join(letters).upper())
            skipped = [t[0] for t in raw_tokens if t[0].isalpha() and t.casefold() not in _ACRONYM_SKIP_WORDS]
            initials.add("".join(skipped).upper())
        return cls(
            uuid=row["uuid"],
            graph_id=row["graph_id"],
            name=name,
            key=key,
            entity_type=row["entity_type"],
            summary=row["summary"] or "",
            mention_count=int(row["mention_count"] or 0),
            id=int(row["id"]),
            tokens=tokens,
            grams=frozenset(trigrams(key)),
            latin=not is_cjk(name),
            initials=frozenset(i for i in initials if len(i) >= 2),
            name_keys=frozenset(_own_name_keys(name, key)),
        )

    def same_name(self, other: "DedupNode") -> bool:
        """Whether both nodes carry the same name (up to an honorific)."""

        return self.key == other.key or bool(self.name_keys & other.name_keys)

    @property
    def acronym(self) -> str | None:
        text = self.name.strip()
        return text if _ACRONYM_RE.match(text) else None


@dataclass(frozen=True)
class CandidatePair:
    a: DedupNode
    b: DedupNode
    similarity: float

    @property
    def uuids(self) -> frozenset[str]:
        return frozenset((self.a.uuid, self.b.uuid))


def load_dedup_nodes(conn: sqlite3.Connection, graph_id: str) -> list[DedupNode]:
    rows = conn.execute(
        "SELECT uuid, graph_id, name, name_key, entity_type, summary, mention_count, id "
        "FROM nodes WHERE graph_id = ? ORDER BY id",
        (graph_id,),
    ).fetchall()
    return [DedupNode.from_row(row) for row in rows]


def _pair_similarity(a: DedupNode, b: DedupNode) -> float | None:
    """Similarity when the pair is a dedup candidate (spec §4.8 rules), else ``None``."""

    if not a.key or not b.key:
        return None
    if a.key == b.key:
        return 1.0
    union = len(a.grams | b.grams)
    jaccard = len(a.grams & b.grams) / union if union else 0.0
    score = jaccard if jaccard >= DEDUP_CANDIDATE_JACCARD else 0.0

    short, long_ = (a, b) if len(a.key) <= len(b.key) else (b, a)
    if len(short.key) >= 2:
        affix = False
        if short.latin and long_.latin and short.tokens and len(short.tokens) < len(long_.tokens):
            n = len(short.tokens)
            affix = long_.tokens[:n] == short.tokens or long_.tokens[-n:] == short.tokens
        elif not (short.latin and long_.latin):
            affix = long_.key.startswith(short.key) or long_.key.endswith(short.key)
        if affix:
            score = max(score, 0.5 + 0.5 * len(short.key) / len(long_.key))

    acronym = short.acronym if short.acronym and not long_.acronym else None
    if acronym is None and long_.acronym and not short.acronym:
        acronym, short, long_ = long_.acronym, long_, short
    if acronym and acronym in long_.initials:
        score = max(score, 0.75)
    return score if score > 0 else None


def _candidate_index(nodes: Sequence[DedupNode]) -> dict[str, dict[str, list[int]]]:
    """Inverted indexes that cover every rule of :func:`_pair_similarity`.

    - ``gram``: trigram -> nodes (any Jaccard > 0 and any affix whose shorter key has 3+ chars);
    - ``key``: exact key -> nodes, ``edge2``: first/last two key chars -> nodes (2-char affixes);
    - ``first`` / ``last``: first/last Latin token -> nodes (whole-token affixes);
    - ``initials`` / ``acronym``: initials of multi-token names and 2-6 letter acronyms.
    """

    index: dict[str, dict[str, list[int]]] = {
        name: {} for name in ("gram", "key", "edge2", "first", "last", "initials", "acronym")
    }

    def add(kind: str, value: str, position: int) -> None:
        index[kind].setdefault(value, []).append(position)

    for position, node in enumerate(nodes):
        for gram in node.grams:
            add("gram", gram, position)
        if node.key:
            add("key", node.key, position)
            add("edge2", node.key[:2], position)
            if node.key[-2:] != node.key[:2]:
                add("edge2", node.key[-2:], position)
        if node.latin and node.tokens:
            add("first", node.tokens[0], position)
            add("last", node.tokens[-1], position)
        for initials in node.initials:
            add("initials", initials, position)
        if node.acronym:
            add("acronym", node.acronym, position)
    return index


def _candidate_positions(node: DedupNode, index: Mapping[str, Mapping[str, list[int]]]) -> set[int]:
    found: set[int] = set()
    for gram in node.grams:
        found.update(index["gram"].get(gram, ()))
    if len(node.key) == 2:
        found.update(index["edge2"].get(node.key, ()))
    for edge in (node.key[:2], node.key[-2:]):
        found.update(index["key"].get(edge, ()))
    if node.latin and node.tokens:
        found.update(index["first"].get(node.tokens[0], ()))
        found.update(index["last"].get(node.tokens[-1], ()))
    if node.acronym:
        found.update(index["initials"].get(node.acronym, ()))
    for initials in node.initials:
        found.update(index["acronym"].get(initials, ()))
    return found


def find_dedup_candidates(
    nodes: Sequence[DedupNode],
    focus_uuids: Iterable[str],
    *,
    max_pairs: int = DEDUP_MAX_PAIRS,
) -> list[CandidatePair]:
    """Candidate pairs between ``focus_uuids`` (the batch's nodes) and every node.

    Types must be compatible (same custom type, or one generic), except that
    two different custom types under the same name are always a candidate:
    type drift between windows ("Socrates" [Person] / "Socrates"
    [Philosopher]) is left to the LLM. Sorted by similarity and capped at
    ``max_pairs``. Inverted indexes limit the pairs scored to those that can
    satisfy a rule.
    """

    focus = set(focus_uuids)
    index = _candidate_index(nodes)
    seen: set[frozenset[str]] = set()
    pairs: list[CandidatePair] = []
    for a in nodes:
        if a.uuid not in focus:
            continue
        for position in sorted(_candidate_positions(a, index)):
            b = nodes[position]
            if b.uuid == a.uuid:
                continue
            key = frozenset((a.uuid, b.uuid))
            if key in seen:
                continue
            seen.add(key)
            if not _types_compatible(a.entity_type, b.entity_type) and not a.same_name(b):
                continue
            similarity = _pair_similarity(a, b)
            if similarity is None:
                continue
            first, second = (a, b) if a.id <= b.id else (b, a)
            pairs.append(CandidatePair(first, second, round(similarity, 6)))
    pairs.sort(key=lambda p: (-p.similarity, p.a.id, p.b.id))
    return pairs[:max(0, max_pairs)]


def group_confirmed_pairs(pairs: Sequence[CandidatePair]) -> list[list[str]]:
    """Union-find over confirmed pairs, guarded against over-merging.

    Two groups join only if they hold at most one custom type (or several
    custom types whose nodes all carry the same name, see
    :func:`_types_mergeable`) and every cross pair is either confirmed or
    name-contained (one key inside the other). So "Alice" = "Alice Chen" and
    "Alice" = "Alice Smith" do not merge Alice Chen with Alice Smith.
    """

    confirmed = {pair.uuids for pair in pairs}
    parent: dict[str, str] = {}
    members: dict[str, list[DedupNode]] = {}

    def find(uuid: str) -> str:
        while parent[uuid] != uuid:
            parent[uuid] = parent[parent[uuid]]
            uuid = parent[uuid]
        return uuid

    for pair in pairs:
        for node in (pair.a, pair.b):
            if node.uuid not in parent:
                parent[node.uuid] = node.uuid
                members[node.uuid] = [node]
    for pair in sorted(pairs, key=lambda p: (-p.similarity, p.a.id, p.b.id)):
        root_a, root_b = find(pair.a.uuid), find(pair.b.uuid)
        if root_a == root_b:
            continue
        group = members[root_a] + members[root_b]
        if not _types_mergeable([(node.entity_type, node.name_keys or {node.key}) for node in group]):
            continue
        if not all(
            frozenset((x.uuid, y.uuid)) in confirmed or x.key in y.key or y.key in x.key
            for x in members[root_a] for y in members[root_b]
        ):
            continue
        parent[root_b] = root_a
        members[root_a] = group
        del members[root_b]
    groups = [[node.uuid for node in sorted(group, key=lambda n: n.id)]
              for group in members.values() if len(group) > 1]
    return sorted(groups, key=lambda g: g[0])


def _absorb_edge(conn: sqlite3.Connection, keep: sqlite3.Row, drop: sqlite3.Row) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO edge_episodes(edge_uuid, episode_uuid, linked_at) "
        "SELECT ?, episode_uuid, linked_at FROM edge_episodes WHERE edge_uuid = ?",
        (keep["uuid"], drop["uuid"]),
    )
    attributes = _merge_attributes(json_loads(keep["attributes_json"], {}) or {},
                                   json_loads(drop["attributes_json"], {}) or {}, new_wins=False)
    conn.execute(
        "UPDATE edges SET valid_at = COALESCE(valid_at, ?), attributes_json = ? WHERE uuid = ?",
        (drop["valid_at"], json_dumps(attributes), keep["uuid"]),
    )
    conn.execute("DELETE FROM edges WHERE uuid = ?", (drop["uuid"],))


def dedupe_node_edges(conn: sqlite3.Connection, graph_id: str, node_uuid: str) -> int:
    """Re-run the §4.7 dedup rule among a node's active edges; returns edges removed."""

    rows = conn.execute(
        "SELECT * FROM edges WHERE graph_id = ? AND (source_node_uuid = ? OR target_node_uuid = ?) "
        f"AND {_ACTIVE_EDGE} ORDER BY id",
        (graph_id, node_uuid, node_uuid),
    ).fetchall()
    groups: dict[tuple[str, frozenset[str]], list[sqlite3.Row]] = {}
    for row in rows:
        key = (row["name"], frozenset((row["source_node_uuid"], row["target_node_uuid"])))
        groups.setdefault(key, []).append(row)
    removed = 0
    for group in groups.values():
        kept: list[sqlite3.Row] = []
        for row in group:
            target = next((k for k in kept if _is_duplicate_edge(k, row)), None)
            if target is None:
                kept.append(row)
                continue
            _absorb_edge(conn, target, row)
            removed += 1
    return removed


def merge_nodes(
    conn: sqlite3.Connection,
    graph_id: str,
    uuids: Sequence[str],
    *,
    summary_cap: int = 800,
    now: str | None = None,
) -> str | None:
    """Merge nodes into one survivor (spec §4.8 step 3); returns its uuid.

    The survivor is a node of a specific type, else of a fallback type
    (``Person``/``Organization``), else a generic one; then the most
    mentioned, then the oldest. So type drift ends with the specific type.
    Edges are re-pointed, self-loops deleted and duplicate facts folded;
    aliases, episode links and attributes are unioned (the survivor's values
    win), summaries merged and mention counts summed. A typed survivor never
    takes the name of a bare generic node (one created for a relation
    endpoint, with no summary); that name stays an alias. Returns ``None``
    (and changes nothing) when fewer than two nodes remain or the group
    mixes custom types under different names.
    """

    now = now or utcnow_iso()
    wanted = list(dict.fromkeys(uuids))
    if len(wanted) < 2:
        return None
    rows = conn.execute(
        f"SELECT * FROM nodes WHERE graph_id = ? AND uuid IN ({_placeholders(len(wanted))})",
        (graph_id, *wanted),
    ).fetchall()
    if len(rows) < 2:
        return None
    if not _types_mergeable([(row["entity_type"], _own_name_keys(row["name"], row["name_key"]))
                             for row in rows]):
        logger.warning("Refusing to merge nodes of different custom types in graph %s", graph_id)
        return None
    ordered = sorted(rows, key=lambda r: (_type_rank(r["entity_type"]), -int(r["mention_count"] or 0), r["id"]))
    survivor, losers = ordered[0], ordered[1:]
    loser_uuids = [row["uuid"] for row in losers]
    marks = _placeholders(len(loser_uuids))

    name = survivor["name"]
    aliases = _split_aliases(survivor["aliases_text"])
    survivor_typed = survivor["entity_type"] is not None
    for row in losers:
        bare_endpoint = row["entity_type"] is None and not (row["summary"] or "").strip()
        if not (survivor_typed and bare_endpoint) and _should_rename(name, row["name"]):
            aliases.append(name)
            name = row["name"]
        else:
            aliases.append(row["name"])
        aliases.extend(_split_aliases(row["aliases_text"]))
    aliases = _display_aliases(name, aliases)
    attributes: dict[str, Any] = {}
    for row in reversed(losers):
        attributes = _merge_attributes(attributes, json_loads(row["attributes_json"], {}) or {},
                                       new_wins=True)
    attributes = _merge_attributes(attributes, json_loads(survivor["attributes_json"], {}) or {},
                                   new_wins=True)
    summary = survivor["summary"] or ""
    for row in losers:
        summary = merge_summary(summary, row["summary"], summary_cap)
    mentions = sum(int(row["mention_count"] or 0) for row in rows)
    entity_type = survivor["entity_type"]
    target = survivor["uuid"]

    conn.execute(f"UPDATE edges SET source_node_uuid = ? WHERE source_node_uuid IN ({marks})",
                 (target, *loser_uuids))
    conn.execute(f"UPDATE edges SET target_node_uuid = ? WHERE target_node_uuid IN ({marks})",
                 (target, *loser_uuids))
    conn.execute("DELETE FROM edges WHERE source_node_uuid = ? AND target_node_uuid = ?", (target, target))
    conn.execute(
        "INSERT OR IGNORE INTO node_aliases(graph_id, alias_key, node_uuid) "
        f"SELECT graph_id, alias_key, ? FROM node_aliases WHERE node_uuid IN ({marks})",
        (target, *loser_uuids),
    )
    conn.execute(
        "INSERT OR IGNORE INTO node_episodes(node_uuid, episode_uuid) "
        f"SELECT ?, episode_uuid FROM node_episodes WHERE node_uuid IN ({marks})",
        (target, *loser_uuids),
    )
    conn.execute(f"DELETE FROM nodes WHERE uuid IN ({marks})", tuple(loser_uuids))
    conn.execute(
        "UPDATE nodes SET name = ?, name_key = ?, entity_type = ?, labels_json = ?, summary = ?, "
        "attributes_json = ?, aliases_text = ?, attributes_text = ?, mention_count = ?, updated_at = ? "
        "WHERE uuid = ?",
        (name, name_key(name), entity_type, json_dumps(_labels(entity_type)), summary,
         json_dumps(attributes), _ALIAS_SEPARATOR.join(aliases), _attributes_text(attributes),
         mentions, now, target),
    )
    _insert_alias_keys(conn, graph_id, target, alias_keys(name, aliases))
    dedupe_node_edges(conn, graph_id, target)
    bump_graph_version(conn, graph_id)
    return target
