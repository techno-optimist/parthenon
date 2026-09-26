"""Text normalization helpers shared by the local memory backend.

Everything here is pure (no I/O, no database access) and deterministic:
name keys used for entity resolution, relation-name normalization, trigram
similarity, timestamp parsing, sentence splitting and query vocabulary.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from typing import Iterable

# ---------------------------------------------------------------------------
# Timestamps
# ---------------------------------------------------------------------------

# One fixed format for every stored timestamp, so ISO strings compare
# lexicographically in the same order as the instants they describe.
ISO_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"

_YEAR_RE = re.compile(r"^(\d{4})$")
_YEAR_MONTH_RE = re.compile(r"^(\d{4})-(\d{1,2})$")


def format_utc(value: datetime) -> str:
    """Format a datetime as UTC ISO 8601 with microseconds and a ``Z`` suffix.

    Naive datetimes are treated as UTC.
    """

    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    try:
        value = value.astimezone(timezone.utc)
    except OverflowError:  # e.g. year 1 with a positive offset
        value = value.replace(tzinfo=timezone.utc)
    # Built by hand: strftime("%Y") does not zero-pad years < 1000 on every platform.
    return (
        f"{value.year:04d}-{value.month:02d}-{value.day:02d}T"
        f"{value.hour:02d}:{value.minute:02d}:{value.second:02d}.{value.microsecond:06d}Z"
    )


def utcnow_iso() -> str:
    """Current time as ``YYYY-MM-DDTHH:MM:SS.ffffffZ``."""

    return format_utc(datetime.now(timezone.utc))


def parse_iso_datetime(value: object, *, require_timezone: bool = False) -> str | None:
    """Parse a full ISO 8601 date or datetime and normalize it to UTC.

    Accepts a ``Z`` suffix or a numeric offset. Naive values are treated as
    UTC unless ``require_timezone`` is true, in which case they are rejected.
    Returns ``None`` for anything that does not parse.
    """

    if isinstance(value, datetime):
        if value.tzinfo is None and require_timezone:
            return None
        return format_utc(value)
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    candidate = text[:-1] + "+00:00" if text[-1:] in ("Z", "z") else text
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None and require_timezone:
        return None
    return format_utc(parsed)


def parse_iso_date(value: object) -> str | None:
    """Parse ``YYYY``, ``YYYY-MM``, ``YYYY-MM-DD`` or a full ISO datetime.

    The result is normalized to UTC (``...Z``); anything else gives ``None``.
    Partial dates resolve to the first instant of the period.
    """

    if isinstance(value, datetime):
        return format_utc(value)
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    match = _YEAR_RE.match(text)
    if match:
        year = int(match.group(1))
        if year < 1:
            return None
        return format_utc(datetime(year, 1, 1, tzinfo=timezone.utc))
    match = _YEAR_MONTH_RE.match(text)
    if match:
        year, month = int(match.group(1)), int(match.group(2))
        if year < 1 or not 1 <= month <= 12:
            return None
        return format_utc(datetime(year, month, 1, tzinfo=timezone.utc))
    return parse_iso_datetime(text)


def parse_local_iso_datetime(value: object) -> str | None:
    """Parse an ISO 8601 datetime, treating a naive value as local time.

    This mirrors ``ZepGraphMemoryUpdater._to_rfc3339``, which sends naive
    simulation timestamps (``datetime.now().isoformat()``) as local time, so
    a line timestamp and the episode's ``created_at`` agree. The result is
    normalized to UTC (``...Z``); anything that does not parse gives ``None``.
    """

    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        candidate = text[:-1] + "+00:00" if text[-1:] in ("Z", "z") else text
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        try:
            parsed = parsed.astimezone()  # interpret as local time
        except (OverflowError, OSError, ValueError):
            parsed = parsed.replace(tzinfo=timezone.utc)
    return format_utc(parsed)


def iso_to_epoch(value: object) -> float | None:
    """Seconds since the epoch for an ISO timestamp (naive values are UTC)."""

    normalized = parse_iso_datetime(value)
    if normalized is None:
        return None
    parsed = datetime.fromisoformat(normalized[:-1] + "+00:00")
    try:
        return parsed.timestamp()
    except (OverflowError, OSError, ValueError):
        return None


def epoch_to_iso(seconds: float) -> str:
    """Format epoch seconds in the stored timestamp format (UTC, ``...Z``)."""

    return format_utc(datetime.fromtimestamp(float(seconds), tz=timezone.utc))


# ---------------------------------------------------------------------------
# Script detection
# ---------------------------------------------------------------------------

# Hiragana/katakana, CJK ideographs (ext. A + unified), Hangul, compatibility ideographs.
CJK_CHAR_CLASS = "぀-ヿ㐀-鿿가-힯豈-﫿"
_CJK_RE = re.compile(f"[{CJK_CHAR_CLASS}]")
_LATIN_WORD_RE = re.compile(r"^[0-9a-zÀ-ɏ]+$", re.IGNORECASE)


def is_cjk(text: str) -> bool:
    """True when ``text`` contains at least one CJK/kana/Hangul character."""

    return bool(text) and _CJK_RE.search(text) is not None


def is_latin(text: str) -> bool:
    """True when ``text`` is made only of Latin letters and digits."""

    return bool(text) and _LATIN_WORD_RE.match(text) is not None


# ---------------------------------------------------------------------------
# Names and keys
# ---------------------------------------------------------------------------

_EDGE_QUOTES = " \t\r\n\"'“”‘’「」『』《》()（）[]【】"
_TRAILING_PUNCT_RE = re.compile(r"[\s.,;:!?，。；：！？、]+$")
_LEADING_ARTICLE_RE = re.compile(r"^(the|a|an) ")
_KEY_SEPARATORS_RE = re.compile(r"[\s\-_·•'’.]+")
_WHITESPACE_RE = re.compile(r"\s+")

HONORIFICS = r"^(mr|mrs|ms|miss|dr|prof|professor|sir|madam)\.?\s+"
_HONORIFICS_RE = re.compile(HONORIFICS)
CJK_HONORIFIC_SUFFIXES = r"(先生|女士|教授|博士|老师)$"  # 先生|女士|教授|博士|老师
_CJK_HONORIFIC_RE = re.compile(CJK_HONORIFIC_SUFFIXES)

# Keys produced only by stripping an honorific must still be this long, so
# "王先生" and "王女士" do not both collapse onto the single-character key "王".
MIN_STRIPPED_KEY_CHARS = 2


def normalize_text(text: str) -> str:
    """NFKC, casefold and collapse whitespace. Keeps punctuation."""

    if not text:
        return ""
    return _WHITESPACE_RE.sub(" ", unicodedata.normalize("NFKC", text)).strip().casefold()


def normalize_name(name: str) -> str:
    """Display-insensitive basis for name keys (see spec §4.6)."""

    if not name:
        return ""
    value = unicodedata.normalize("NFKC", name).strip()
    value = value.strip(_EDGE_QUOTES)
    value = _WHITESPACE_RE.sub(" ", value).casefold()
    value = _LEADING_ARTICLE_RE.sub("", value)
    value = _TRAILING_PUNCT_RE.sub("", value)
    return value


def name_key(name: str) -> str:
    """Compact key stored in ``nodes.name_key`` and ``node_aliases.alias_key``."""

    return _KEY_SEPARATORS_RE.sub("", normalize_name(name))


def compact_text(text: str) -> str:
    """Normalize free text the same way keys are built, for substring tests.

    ``name_key(x) in compact_text(text)`` answers "is x mentioned in text".
    """

    return _KEY_SEPARATORS_RE.sub("", normalize_text(text))


def is_word_char(ch: str) -> bool:
    """True for a letter or digit of a space-delimited script (Latin, Cyrillic, ...).

    CJK characters are not word characters here: those scripts have no word
    boundaries, so matches inside CJK text are plain substring matches.
    """

    return bool(ch) and ch.isalnum() and _CJK_RE.match(ch) is None


def contains_word(text: str, term: str) -> bool:
    """True when ``term`` occurs in ``text`` with no word character on either side.

    ``contains_word("said", "ai")`` is false; ``contains_word("ai policy", "ai")``
    and ``contains_word("ai小组", "ai")`` are true. Both strings should already
    be normalized the same way (for example with :func:`normalize_text`).
    """

    if not term:
        return False
    start = text.find(term)
    while start != -1:
        end = start + len(term)
        if (start == 0 or not is_word_char(text[start - 1])) and (
            end == len(text) or not is_word_char(text[end])
        ):
            return True
        start = text.find(term, start + 1)
    return False


def compact_with_boundaries(text: str) -> tuple[str, list[bool]]:
    """:func:`compact_text` plus the word boundaries the compaction removed.

    Returns ``(compact, boundaries)`` where ``boundaries`` has
    ``len(compact) + 1`` entries: ``boundaries[i]`` is true when a word
    boundary lies just before ``compact[i]`` (``boundaries[-1]`` is the end of
    the text). A boundary exists at either end, where a separator such as a
    space was dropped, and next to any non-word character. This lets a key
    such as ``"ai"`` match ``"AI policy"`` but not ``"said"``.
    """

    compact: list[str] = []
    boundaries: list[bool] = []
    separated = True
    previous_word = False
    for ch in normalize_text(text):
        if _KEY_SEPARATORS_RE.match(ch):
            separated = True
            continue
        word = is_word_char(ch)
        boundaries.append(separated or not (word and previous_word))
        compact.append(ch)
        previous_word = word
        separated = False
    boundaries.append(True)
    return "".join(compact), boundaries


def strip_honorifics(name: str) -> str:
    """``normalize_name(name)`` without a leading Latin or trailing CJK honorific.

    ``"Dr. Alice Chen"`` gives ``"alice chen"`` and ``"王伟先生"`` gives ``"王伟"``.
    """

    normalized = normalize_name(name)
    stripped = _HONORIFICS_RE.sub("", normalized)
    return _CJK_HONORIFIC_RE.sub("", stripped)


def alias_keys(name: str, aliases: Iterable[str] = ()) -> set[str]:
    """All keys registered for a node: its name, aliases and honorific-free forms."""

    names = [n for n in [name, *aliases] if isinstance(n, str) and n.strip()]
    keys = {name_key(n) for n in names}
    for raw in names:
        normalized = normalize_name(raw)
        for stripped in (
            _HONORIFICS_RE.sub("", normalized),
            _CJK_HONORIFIC_RE.sub("", normalized),
        ):
            if stripped == normalized:
                continue
            key = name_key(stripped)
            if len(key) >= MIN_STRIPPED_KEY_CHARS:
                keys.add(key)
    return {key for key in keys if key}


# ---------------------------------------------------------------------------
# Relation names
# ---------------------------------------------------------------------------

DEFAULT_RELATION_NAME = "RELATES_TO"
MAX_RELATION_NAME_CHARS = 60
_CAMEL_BOUNDARY_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_NON_ALNUM_RE = re.compile(r"[^A-Za-z0-9]+")


def to_upper_snake(raw: object) -> str:
    """Normalize a relation name to UPPER_SNAKE_CASE (at most 60 chars).

    ``"works for"``, ``"works-for"`` and ``"worksFor"`` all become
    ``WORKS_FOR``. A result without any A-Z letter becomes ``RELATES_TO``.
    """

    if not isinstance(raw, str):
        return DEFAULT_RELATION_NAME
    value = unicodedata.normalize("NFKC", raw)
    value = _CAMEL_BOUNDARY_RE.sub("_", value)
    value = _NON_ALNUM_RE.sub("_", value).strip("_").upper()
    value = value[:MAX_RELATION_NAME_CHARS].strip("_")
    if not re.search(r"[A-Z]", value):
        return DEFAULT_RELATION_NAME
    return value


# ---------------------------------------------------------------------------
# Similarity
# ---------------------------------------------------------------------------


def trigrams(key: str) -> set[str]:
    """3-character shingles of ``key``; the key itself when shorter than 3."""

    if not key:
        return set()
    if len(key) < 3:
        return {key}
    return {key[i:i + 3] for i in range(len(key) - 2)}


def trigram_jaccard(a: str, b: str) -> float:
    """Jaccard similarity of the trigram sets of two keys (0.0 to 1.0)."""

    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    set_a, set_b = trigrams(a), trigrams(b)
    union = set_a | set_b
    if not union:
        return 0.0
    return len(set_a & set_b) / len(union)


# ---------------------------------------------------------------------------
# Sentences and truncation
# ---------------------------------------------------------------------------

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?。！？])\s*")


def split_sentences(text: str) -> list[str]:
    """Split on sentence-final punctuation (Latin and CJK), dropping empties."""

    if not text:
        return []
    return [part.strip() for part in _SENTENCE_SPLIT_RE.split(text) if part.strip()]


def truncate(text: object, limit: int) -> str:
    """Return ``str(text)`` stripped and cut to ``limit`` characters."""

    if text is None:
        return ""
    value = str(text).strip()
    return value[:limit] if limit >= 0 else value


# ---------------------------------------------------------------------------
# Query vocabulary (used by search)
# ---------------------------------------------------------------------------

STOPWORDS_EN: frozenset[str] = frozenset(
    """
    a about above after again against all also am an and any are as at be because been before
    being below between both but by can could did do does doing down during each few for from
    further had has have having he her here hers herself him himself his how i if in into is it
    its itself just me more most my myself no nor not now of off on once only or other our ours
    ourselves out over own same she should so some such than that the their theirs them
    themselves then there these they this those through to too under until up very was we were
    what when where which while who whom why will with would you your yours yourself yourselves
    get got let may might must shall us via per within without upon among across
    information activities activity events event relationships relationship background
    """.split()
)

# Profile and report query templates (progress.zepSearchQuery translations).
TEMPLATE_PHRASES: tuple[str, ...] = (
    "的所有信息",  # 的所有信息
    "所有信息",  # 所有信息
    "关于",  # 关于
    "活动",  # 活动
    "事件",  # 事件
    "关系",  # 关系
    "背景",  # 背景
)
