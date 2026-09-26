"""Simulation activity episodes: rules extractor and LLM-enrichment planning (spec §5).

``ZepGraphMemoryUpdater`` sends simulation activity as ``graph.add`` episodes
(``metadata.source == "mirofish_simulation"``). Each episode holds a few lines
rendered by ``AgentActivity.to_episode_text()``::

    [{timestamp}] [{platform} round {n}] {agent_name}: {description}

The description is Chinese for a run in the ``zh`` locale (the upstream
MiroFish templates) and English for any other locale. Both template sets
parse into the same edge names and targets. Facts and node summaries written
by the rules follow the language of the line that produced them, so graphs
built before English descriptions existed keep working and a mixed graph is
fine.

Modes (``LOCAL_MEMORY_ACTIVITY_MODE``, §5.1), all applied synchronously inside
the ``graph.add`` write transaction by :func:`ingest_activity_episode`:

- ``off``: the episode is stored and FTS-indexed only; ``processed=1``,
  ``extraction_status='skipped'``.
- ``rules`` (default): the deterministic rules extractor (§5.2) writes agent,
  target and platform-hub nodes plus one event edge per line; ``processed=1``,
  ``succeeded``. No LLM call, ever.
- ``llm``: rules as above, then the episode is ``queued`` for grouped LLM
  enrichment (§5.3). The worker schedules that with the pure helpers below
  (:func:`plan_activity_groups`, :func:`decide_activity_group`,
  :func:`activity_failure_decision`, :class:`ActivityLane`) and the small SQL
  helpers (:func:`load_activity_candidates`, :func:`claim_activity_episodes`,
  :func:`finish_activity_episodes`, :func:`sweep_expired_activity_episodes`,
  usage accounting). An episode without any signal line has nothing to
  enrich, so it finishes ``succeeded`` right away instead of being queued.

Interaction with the updater and runner (§5.4): ``graph.add`` never waits for
or fails because of an LLM. A rules failure is contained in a SAVEPOINT and
downgrades the episode to ``degraded``. In ``rules``/``off`` mode every
episode is ``processed`` when ``graph.add`` returns, so
``ZepGraphMemoryUpdater.stop()`` finds nothing pending on its first poll. In
``llm`` mode the tail wait is bounded by the group wait plus LLM time, and by
the deadline sweep (``LOCAL_MEMORY_ACTIVITY_MAX_PENDING_SECONDS``).

The description patterns are coupled to both template sets in
``app/services/zep_graph_memory_updater.py``; ``tests/local_memory/
test_activity.py`` renders every template in both languages through
``to_episode_text()`` so a template change fails CI instead of silently
degrading extraction.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import threading
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, NamedTuple, Sequence

from .errors import is_busy_sqlite_error, not_found
from .models import EPISODE_TERMINAL_STATUSES, json_dumps, json_loads
from .ontology import GENERIC_ENTITY, OntologyView
from .resolution import (
    EDGE_DEDUP_JACCARD,
    bump_graph_version,
    create_node,
    link_node_episodes,
    resolve_existing,
)
from .store import new_id
from .textnorm import (
    epoch_to_iso,
    iso_to_epoch,
    name_key,
    parse_iso_datetime,
    parse_local_iso_datetime,
    to_upper_snake,
    trigrams,
    truncate,
    utcnow_iso,
)

logger = logging.getLogger("mirofish.memory.activity")

__all__ = [
    "ACTIVITY_MODES",
    "ACTIVITY_SOURCE",
    "ACTIVITY_SYSTEM_PROMPT",
    "ActivityCandidate",
    "ActivityDecision",
    "ActivityGroup",
    "ActivityIngestResult",
    "ActivityLane",
    "ActivityLine",
    "ActivityParse",
    "ActivityPolicy",
    "ActivityWindow",
    "FATAL_LLM_CODES",
    "PromptFact",
    "RulesResult",
    "activity_failure_decision",
    "activity_llm_calls_used",
    "activity_system_prompt",
    "apply_activity_rules",
    "build_activity_messages",
    "claim_activity_episodes",
    "classify_activity_description",
    "decide_activity_group",
    "expired_activity_candidates",
    "finish_activity_episodes",
    "ingest_activity_episode",
    "is_activity_metadata",
    "load_activity_candidates",
    "normalize_activity_mode",
    "parse_activity_text",
    "plan_activity_groups",
    "platform_display_name",
    "record_activity_llm_call",
    "render_activity_window",
    "signal_text",
    "simulation_key",
    "sweep_expired_activity_episodes",
]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ACTIVITY_SOURCE = "mirofish_simulation"  # metadata["source"] that routes graph.add here
UNKNOWN_SIMULATION = "unknown"  # budget key for episodes without a simulation_id

MODE_OFF = "off"
MODE_RULES = "rules"
MODE_LLM = "llm"
ACTIVITY_MODES: tuple[str, ...] = (MODE_RULES, MODE_LLM, MODE_OFF)

RULES_ORIGIN = "rules"
MAX_FACT_CHARS = 1000
MAX_NODE_NAME_CHARS = 200
# Near-duplicate checks look at this many newest active edges of the same
# (source, target, action); exact duplicates are always found. Keeps graph.add
# fast when one account posts hundreds of times.
NEAR_DUPLICATE_SCAN_LIMIT = 200
MAX_ERROR_MESSAGE_CHARS = 300

PLATFORM_DISPLAY_NAMES: Mapping[str, str] = {"twitter": "Twitter", "reddit": "Reddit"}

# Language of an activity line, decided by the rule set that matched it.
LANG_ZH = "zh"
LANG_EN = "en"
# Rules text in the language of the line that produced it.
FACT_TEMPLATES: Mapping[str, str] = {
    LANG_ZH: "{agent}在{platform}{description}",
    LANG_EN: "On {platform}, {agent} {description}",
}
ACCOUNT_SUMMARY_TEMPLATES: Mapping[str, str] = {
    LANG_ZH: "{name}是{platform}上的模拟账号。",
    LANG_EN: "{name} is a simulated account on {platform}.",
}
HUB_SUMMARY_TEMPLATES: Mapping[str, str] = {
    LANG_ZH: "{platform}是模拟中使用的社交媒体平台。",
    LANG_EN: "{platform} is the social media platform used in the simulation.",
}

ACTION_ACTED = "ACTED"
TARGET_HUB = "hub"
TARGET_PERSON = "person"

# Rules whose lines carry the account's own words (or the words it amplifies).
SIGNAL_ACTIONS = frozenset({"POSTED", "QUOTED", "REPOSTED"})
SIGNAL_ACTION_PREFIX = "COMMENTED"

# Extraction codes that stop the LLM for the rest of the process (§4.9, §5.3).
FATAL_LLM_CODES = frozenset({"llm_quota_exhausted", "llm_auth", "llm_not_configured"})

# Error codes this module writes into episodes.extraction_error.
ERROR_RULES = "rules_error"
ERROR_NO_SIGNAL = "no_signal"
ERROR_BUDGET = "budget_exhausted"
ERROR_DEADLINE = "deadline"
ERROR_LANE_DISABLED = "llm_unavailable"

_ERROR_MESSAGES: Mapping[str, str] = {
    ERROR_NO_SIGNAL: "No posts or comments with quoted content to enrich; rules facts only.",
    ERROR_BUDGET: "Activity enrichment LLM budget for this simulation is used up; rules facts only.",
    ERROR_DEADLINE: "Activity enrichment did not start in time; rules facts only.",
    ERROR_LANE_DISABLED: "Activity enrichment is disabled after a fatal LLM error; rules facts only.",
}


def _error(code: str, message: str | None = None) -> dict[str, str]:
    text = message if message is not None else _ERROR_MESSAGES.get(code, code)
    return {"code": code, "message": truncate(text, MAX_ERROR_MESSAGE_CHARS)}


# ---------------------------------------------------------------------------
# Small public helpers
# ---------------------------------------------------------------------------


def is_activity_metadata(metadata: Any) -> bool:
    """True when ``graph.add`` metadata marks a simulation activity episode."""

    return isinstance(metadata, Mapping) and metadata.get("source") == ACTIVITY_SOURCE


def simulation_key(simulation_id: Any) -> str:
    """Budget/usage key for a simulation id (``'unknown'`` when missing)."""

    if simulation_id is None:
        return UNKNOWN_SIMULATION
    text = str(simulation_id).strip()
    return text or UNKNOWN_SIMULATION


def platform_display_name(platform: str) -> str:
    """Hub node name for a platform token (``twitter`` becomes ``Twitter``)."""

    token = (platform or "").strip()
    return PLATFORM_DISPLAY_NAMES.get(token.lower(), token.title())


def normalize_activity_mode(mode: Any) -> str:
    """``rules``, ``llm`` or ``off``; raises ``ValueError`` for anything else."""

    value = str(mode or "").strip().lower()
    if value not in ACTIVITY_MODES:
        raise ValueError(f"activity mode must be one of {', '.join(ACTIVITY_MODES)}")
    return value


# ---------------------------------------------------------------------------
# Rules parser (§5.2)
# ---------------------------------------------------------------------------

# One record starts at a header line. The timestamp may be empty
# (SimulationRunner falls back to "" for some actions), and so may the agent
# name: such a record is kept (it must not swallow the next action or split
# at a ": “" inside its own description) but gets no edge.
ACTIVITY_HEADER_RE = re.compile(
    r"^\[(?P<ts>[^\]\n]*)\] \[(?P<platform>[A-Za-z0-9_]+) round (?P<round>-?\d+)\] "
    r"(?P<agent>[^\n]*?): (?P<desc>[^\n]+)$"
)


@dataclass(frozen=True)
class _Rule:
    pattern: re.Pattern[str]
    # The edge name, or a mapping from the pattern's "k" group to the edge name.
    action: str | Mapping[str, str]
    target: str  # TARGET_HUB or TARGET_PERSON


def _rule(pattern: str, action: str | Mapping[str, str], target: str = TARGET_HUB) -> _Rule:
    return _Rule(re.compile(pattern), action, target)


# Rules are tried in order against the first line of the description; the
# first match wins. A rule's match covers the template (and any person name);
# it stops before the opening quote of the content, so the rest of the
# description (``ActivityLine.detail``) is what the account wrote or searched.

# Chinese templates.
# A person name inside a description. It never crosses into quoted content.
# Unlike the English rules it cannot hold a colon (upstream behaviour, kept).
_T = r"(?P<t>[^「」：:\n]+?)"
# What may follow "帖子"/"评论" in a template: a colon, an opening quote,
# the "，并评论道" suffix, "下评论道", or the end of the description.
_B = r"(?=[：:「，,下]|$)"
# The quote suffix right after "帖子" (no quoted post content) is template too.
_ZH_ADDING = r"(?:，并评论道：(?=「))?"

_ZH_RULES: tuple[_Rule, ...] = (
    _rule(r"发布了一条帖子", "POSTED"),
    _rule(rf"点赞了一条帖子{_B}", "LIKED_POST"),
    _rule(rf"点赞了一条评论{_B}", "LIKED_COMMENT"),
    _rule(rf"点赞了{_T}的(?:一条)?帖子{_B}", "LIKED_POST_OF", TARGET_PERSON),
    _rule(rf"点赞了{_T}的(?:一条)?评论{_B}", "LIKED_COMMENT_OF", TARGET_PERSON),
    _rule(rf"踩了一条帖子{_B}", "DISLIKED_POST"),
    _rule(rf"踩了一条评论{_B}", "DISLIKED_COMMENT"),
    _rule(rf"踩了{_T}的(?:一条)?帖子{_B}", "DISLIKED_POST_OF", TARGET_PERSON),
    _rule(rf"踩了{_T}的(?:一条)?评论{_B}", "DISLIKED_COMMENT_OF", TARGET_PERSON),
    _rule(rf"转发了一条帖子{_B}", "REPOSTED"),
    _rule(rf"转发了{_T}的(?:一条)?帖子{_B}", "REPOSTED", TARGET_PERSON),
    _rule(rf"引用了一条帖子{_ZH_ADDING}{_B}", "QUOTED"),
    _rule(rf"引用了{_T}的(?:一条)?帖子{_ZH_ADDING}{_B}", "QUOTED", TARGET_PERSON),
    _rule(r"关注了用户「(?P<t>[^」\n]+)」", "FOLLOWS", TARGET_PERSON),
    _rule(r"关注了一个用户", "FOLLOWS"),
    _rule(r"屏蔽了用户「(?P<t>[^」\n]+)」", "MUTED", TARGET_PERSON),
    _rule(r"屏蔽了一个用户", "MUTED"),
    _rule(rf"在{_T}的帖子{_B}", "COMMENTED_ON_POST_OF", TARGET_PERSON),
    _rule(r"(?:在帖子(?=「)|评论道|发表了评论)", "COMMENTED"),
    _rule(r"搜索了用户", "SEARCHED_USER"),
    _rule(r"(?:搜索了(?=「)|进行了搜索)", "SEARCHED"),
)
_ZH_GENERIC_RULE = re.compile(r"执行了(?P<a>[A-Za-z0-9_]+)操作")

# English templates. A person name is non-greedy and ends at the first template
# delimiter after it. Every delimiter that can follow a name is either the end
# of the line or ends with the opening quote of the content (“), so the name
# may contain apostrophes, "'s post", "by", "on", colons or even quotes and is
# returned exactly, and quoted content (which may itself contain
# "liked X's post: “") never decides where it ends. The content-only, bare
# and "by" shapes ("liked a post: “...", "liked a post", "liked a post by X")
# are tried before the possessive ones; a "by" name never contains the
# delimiter of the same action's possessive shape, so an author named
# "a post by Carl" or "a comment by Zed" still reads right in "liked a post
# by Carl's post: “...”". A possessive rule that may end in "post" or
# "comment" takes whichever delimiter comes first ("k" group). The one shape
# read wrongly is a name that itself contains a delimiter followed by the
# opening quote, such as "Tom's post: “x" or "Bob, adding: “y".
_EN_T = r"(?P<t>.+?)"
# The opening quote of the content: the template match stops right before it.
_Q = r"(?=“)"


def _en_by(possessive: str, end: str = "$") -> str:
    """``" by {name}"`` up to ``end``; the name never contains ``possessive``.

    A blank name (the line is stripped) still matches and falls back to the
    hub, like the Chinese rules.
    """

    return rf" by(?: (?P<t>(?:(?!{possessive}).)+?))?{end}"


_LIKE_BY = _en_by(r"'s (?:post|comment): “")
_REPOST_BY = _en_by(r"'s post: “")
_QUOTE_BY = _en_by(r"'s post “", end=rf"(?:, adding: {_Q}|$)")

_EN_RULES: tuple[_Rule, ...] = (
    _rule(r"posted(?=: “|$)", "POSTED"),
    _rule(r"liked a post(?=: “|$)", "LIKED_POST"),
    _rule(r"liked a comment(?=: “|$)", "LIKED_COMMENT"),
    _rule(rf"liked a post{_LIKE_BY}", "LIKED_POST_OF", TARGET_PERSON),
    _rule(rf"liked a comment{_LIKE_BY}", "LIKED_COMMENT_OF", TARGET_PERSON),
    _rule(rf"liked {_EN_T}'s (?P<k>post|comment): {_Q}",
          {"post": "LIKED_POST_OF", "comment": "LIKED_COMMENT_OF"}, TARGET_PERSON),
    _rule(r"disliked a post(?=: “|$)", "DISLIKED_POST"),
    _rule(r"disliked a comment(?=: “|$)", "DISLIKED_COMMENT"),
    _rule(rf"disliked a post{_LIKE_BY}", "DISLIKED_POST_OF", TARGET_PERSON),
    _rule(rf"disliked a comment{_LIKE_BY}", "DISLIKED_COMMENT_OF", TARGET_PERSON),
    _rule(rf"disliked {_EN_T}'s (?P<k>post|comment): {_Q}",
          {"post": "DISLIKED_POST_OF", "comment": "DISLIKED_COMMENT_OF"}, TARGET_PERSON),
    _rule(r"reposted a post(?=: “|$)", "REPOSTED"),
    _rule(rf"reposted a post{_REPOST_BY}", "REPOSTED", TARGET_PERSON),
    _rule(rf"reposted {_EN_T}'s post: {_Q}", "REPOSTED", TARGET_PERSON),
    _rule(rf"quoted a post(?:, adding: {_Q}|(?= “)|$)", "QUOTED"),
    _rule(rf"quoted a post{_QUOTE_BY}", "QUOTED", TARGET_PERSON),
    _rule(rf"quoted {_EN_T}'s post {_Q}", "QUOTED", TARGET_PERSON),
    _rule(r"followed the user “(?P<t>.+)”$", "FOLLOWS", TARGET_PERSON),
    _rule(r"followed a user$", "FOLLOWS"),
    _rule(r"muted the user “(?P<t>.+)”$", "MUTED", TARGET_PERSON),
    _rule(r"muted a user$", "MUTED"),
    _rule(rf"commented on a post {_Q}", "COMMENTED"),
    _rule(rf"commented on {_EN_T}'s post:? {_Q}", "COMMENTED_ON_POST_OF", TARGET_PERSON),
    _rule(rf"(?:commented: {_Q}|left a comment$)", "COMMENTED"),
    _rule(rf"(?:searched for the user {_Q}|searched for users$)", "SEARCHED_USER"),
    _rule(rf"(?:searched for {_Q}|ran a search$)", "SEARCHED"),
)
# "performed {ACTION_TYPE}": a PERFORMED_* edge for a plain type name, ACTED
# for anything else, and English either way.
_EN_GENERIC_RULE = re.compile(r"performed (?:(?P<a>[A-Za-z0-9_]+)$)?")

# (language, rules, generic rule). A description is one language or the other:
# every Chinese template starts with a Chinese word and every English one with
# an English word, so no line can match both sets.
_RULE_SETS: tuple[tuple[str, tuple[_Rule, ...], re.Pattern[str]], ...] = (
    (LANG_ZH, _ZH_RULES, _ZH_GENERIC_RULE),
    (LANG_EN, _EN_RULES, _EN_GENERIC_RULE),
)
# A line no rule matched is Chinese when the text before its first opening
# quote has CJK text, else English: quoted content never decides the language.
_CJK_RE = re.compile(r"[\u3000-\u303f\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff00-\uffef]")
_OPENING_QUOTE_RE = re.compile(r"[“「]")
# Quoted content: an opening quote followed by text. The closing quote may be
# cut off by the updater's "[truncated by MiroFish]" marker.
_QUOTED_RES: Mapping[str, re.Pattern[str]] = {
    LANG_ZH: re.compile(r"「\s*[^」\s]"),
    LANG_EN: re.compile(r"“\s*[^”\s]"),
}
_WHITESPACE_RE = re.compile(r"\s+")


def classify_activity_description(description: str) -> tuple[str, str | None]:
    """Map a description to ``(edge name, person target or None for the hub)``."""

    action, target, _language, _template_end = _classify(description)
    return action, target


def _classify(description: str) -> tuple[str, str | None, str, int]:
    """``(edge name, person target or None, language, template end)``.

    Only the first line is matched (content may span lines), always from its
    start, so a template phrase inside quoted content never decides the rule.
    A person name that runs to the end of the first line while the
    description goes on was cut by a line break, so like a blank name it
    falls back to the hub. The template end is where the matched template
    stops (0 when no rule matched); the description must be stripped.
    """

    lines = (description or "").split("\n", 1)
    first_line = lines[0].strip()
    continued = len(lines) > 1 and bool(lines[1].strip())
    for language, rules, generic_rule in _RULE_SETS:
        for rule in rules:
            match = rule.pattern.match(first_line)
            if not match:
                continue
            action = rule.action if isinstance(rule.action, str) else rule.action[match.group("k")]
            if rule.target == TARGET_PERSON:
                target = (match.group("t") or "").strip()
                cut = continued and match.end("t") == len(first_line)
                if target and name_key(target) and not cut:
                    return action, target, language, match.end()
            return action, None, language, match.end()
        match = generic_rule.match(first_line)
        if match:
            action = to_upper_snake(f"PERFORMED_{match.group('a') or ''}")
            return (action if action != "PERFORMED" else ACTION_ACTED), None, language, match.end()
    template = _OPENING_QUOTE_RE.split(first_line, 1)[0]
    return ACTION_ACTED, None, (LANG_ZH if _CJK_RE.search(template) else LANG_EN), 0


@dataclass(frozen=True)
class ActivityLine:
    """One parsed activity record (a header line plus any continuation lines)."""

    index: int
    text: str
    timestamp: str
    platform: str
    round: int
    agent: str
    description: str
    action: str
    target: str | None  # person name; None means the platform hub
    language: str = LANG_ZH  # LANG_ZH or LANG_EN: the template set of the description
    template_end: int = 0  # where the matched template ends in the description

    @property
    def target_kind(self) -> str:
        return TARGET_PERSON if self.target else TARGET_HUB

    @property
    def platform_name(self) -> str:
        return platform_display_name(self.platform)

    @property
    def detail(self) -> str:
        """The description after its template: the quoted content or query.

        The whole description when no rule matched.
        """

        return self.description[self.template_end:]

    @property
    def quoted(self) -> bool:
        """True when the detail carries quoted content (「...」 or “...”).

        A quote inside a person name is part of the template and never counts.
        """

        return _QUOTED_RES[self.language].search(self.detail) is not None

    @property
    def is_signal(self) -> bool:
        """Lines worth an LLM: an account's posts, quotes, reposts and comments with content."""

        return bool(self.agent) and (
            self.action in SIGNAL_ACTIONS or self.action.startswith(SIGNAL_ACTION_PREFIX)
        ) and self.quoted


@dataclass(frozen=True)
class ActivityParse:
    """Result of :func:`parse_activity_text`."""

    lines: tuple[ActivityLine, ...]
    unparsed: tuple[str, ...]

    @property
    def signal_lines(self) -> tuple[ActivityLine, ...]:
        return tuple(line for line in self.lines if line.is_signal)


def parse_activity_text(content: str) -> ActivityParse:
    """Split an activity episode into records and classify each one.

    A line that matches the header starts a record. Following lines that do
    not match belong to it (post content may contain newlines). Lines before
    the first header are kept only in the episode (``unparsed``).
    """

    records: list[dict[str, Any]] = []
    unparsed: list[str] = []
    for raw_line in (content or "").split("\n"):
        line = raw_line.rstrip("\r")
        match = ACTIVITY_HEADER_RE.match(line)
        if match:
            records.append({"match": match, "text": [line], "desc": [match.group("desc")]})
        elif records:
            records[-1]["text"].append(line)
            records[-1]["desc"].append(line)
        elif line.strip():
            unparsed.append(line)

    lines: list[ActivityLine] = []
    for index, record in enumerate(records):
        match = record["match"]
        description = "\n".join(record["desc"]).strip()
        action, target, language, template_end = _classify(description)
        lines.append(ActivityLine(
            index=index,
            text="\n".join(record["text"]).rstrip(),
            timestamp=match.group("ts").strip(),
            platform=match.group("platform"),
            round=int(match.group("round")),
            agent=match.group("agent").strip(),
            description=description,
            action=action,
            target=target,
            language=language,
            template_end=template_end,
        ))
    return ActivityParse(tuple(lines), tuple(unparsed))


def signal_text(content: str | ActivityParse) -> str:
    """The records of an episode that would go to the LLM, joined by newlines."""

    parsed = content if isinstance(content, ActivityParse) else parse_activity_text(content)
    return "\n".join(line.text for line in parsed.signal_lines)


def activity_fact(line: ActivityLine) -> str:
    """The rules fact of a line, whitespace-collapsed, at most 1,000 chars.

    ``{agent}在{Platform}{description}`` for a Chinese line and
    ``On {Platform}, {agent} {description}`` for an English one.
    """

    return truncate(_format_fact(line, line.description), MAX_FACT_CHARS)


def _fact_head(line: ActivityLine) -> str:
    """The start of the line's fact that its template fixes (all but the detail).

    Always a prefix of the untruncated :func:`activity_fact` text.
    """

    return _format_fact(line, line.description[:line.template_end])


def _format_fact(line: ActivityLine, description: str) -> str:
    description = _WHITESPACE_RE.sub(" ", description).strip()
    return FACT_TEMPLATES[line.language].format(
        agent=line.agent, platform=line.platform_name, description=description,
    )


# ---------------------------------------------------------------------------
# Rules extractor: database writes (§5.2)
# ---------------------------------------------------------------------------


@dataclass
class RulesResult:
    """Counts from one :func:`apply_activity_rules` run."""

    lines: int = 0
    unparsed: int = 0
    skipped_lines: int = 0
    signal_lines: int = 0
    nodes_created: int = 0
    edges_created: int = 0
    edges_merged: int = 0
    self_loops: int = 0
    error: str | None = None  # exception type name when the rules failed

    @property
    def changed(self) -> bool:
        return bool(self.nodes_created or self.edges_created or self.edges_merged)


class _NodeResolver:
    """Resolve account and hub names to node uuids within one graph and episode."""

    def __init__(self, conn: sqlite3.Connection, graph_id: str, episode_uuid: str, now: str,
                 result: RulesResult) -> None:
        self.conn = conn
        self.graph_id = graph_id
        self.episode_uuid = episode_uuid
        self.now = now
        self.result = result
        self._cache: dict[str, str] = {}

    # A new node's summary is in the language of the line that created it.
    def account(self, name: str, platform: str, language: str = LANG_ZH) -> str | None:
        return self._resolve(name, ACCOUNT_SUMMARY_TEMPLATES[language].format(name=name, platform=platform))

    def hub(self, platform: str, language: str = LANG_ZH) -> str | None:
        return self._resolve(platform, HUB_SUMMARY_TEMPLATES[language].format(platform=platform))

    def _resolve(self, raw_name: str, summary: str) -> str | None:
        name = truncate(raw_name, MAX_NODE_NAME_CHARS)
        key = name_key(name)
        if not key:
            return None
        cached = self._cache.get(key)
        if cached:
            return cached
        row = resolve_existing(self.conn, self.graph_id, name)
        if row is not None:
            node_uuid = row["uuid"]
        else:
            node_uuid = create_node(self.conn, self.graph_id, name=name, summary=summary,
                                    origin=RULES_ORIGIN, now=self.now).uuid
            self.result.nodes_created += 1
        link_node_episodes(self.conn, node_uuid, [self.episode_uuid])
        self._cache[key] = node_uuid
        return node_uuid


def _near_duplicate(key: str, candidates: Iterable[tuple[Any, str]]) -> Any:
    """The row whose key has the highest trigram Jaccard >= 0.8 with ``key``, if any.

    ``candidates`` are ``(row, key)`` pairs. Same measure as
    ``textnorm.trigram_jaccard``; the new key's trigram set is built once,
    and a candidate too short to reach the threshold is skipped before its
    set is built (J <= |B| / |A| <= (len(B) - 2) / |A|).
    """

    new_set = trigrams(key)
    if not new_set:
        return None
    best, best_score = None, 0.0
    for row, other in candidates:
        if len(other) >= 3 and len(other) - 2 < EDGE_DEDUP_JACCARD * len(new_set):
            continue
        other_set = trigrams(other)
        common = len(new_set & other_set)
        union = len(new_set) + len(other_set) - common
        score = common / union if union else 0.0
        if score >= EDGE_DEDUP_JACCARD and score > best_score:
            best, best_score = row, score
    return best


def _merge_attributes(old: Mapping[str, Any], new: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(old)
    for key, value in new.items():
        if value is not None and value != "":
            merged[key] = value
    return merged


def _write_event_edge(conn: sqlite3.Connection, *, graph_id: str, name: str, source: str,
                      target: str, fact: str, fact_head: str, valid_at: str | None,
                      attributes: Mapping[str, str], episode_uuid: str, now: str) -> bool:
    """Insert a rules edge, or link the episode to an equivalent active edge.

    Returns True when a new edge was created. Dedup follows §4.7 (equal fact
    key, or trigram Jaccard >= 0.8) but only in the same direction: actions
    are directed, and "A followed B" must not absorb "B followed A". The
    Jaccard compares only what follows ``fact_head`` (the part the template
    fixes, :func:`_fact_head`) in facts that start with it, so two distinct
    short searches or comments are not merged just because they share the
    template words. Near duplicates are searched among the newest
    ``NEAR_DUPLICATE_SCAN_LIMIT`` candidate edges.
    """

    fact_key = name_key(fact)
    active = (
        "SELECT uuid, fact_key, valid_at, attributes_json FROM edges "
        "WHERE graph_id = ? AND source_node_uuid = ? AND target_node_uuid = ? AND name = ? "
        "AND invalid_at IS NULL AND expired_at IS NULL"
    )
    duplicate = conn.execute(
        active + " AND fact_key = ? ORDER BY id LIMIT 1", (graph_id, source, target, name, fact_key),
    ).fetchone()
    head_key = name_key(fact_head)
    if duplicate is None and fact_key.startswith(head_key):
        rows = conn.execute(active + " ORDER BY id DESC LIMIT ?",
                            (graph_id, source, target, name, NEAR_DUPLICATE_SCAN_LIMIT)).fetchall()
        duplicate = _near_duplicate(fact_key[len(head_key):], [
            (row, row["fact_key"][len(head_key):])
            for row in rows if (row["fact_key"] or "").startswith(head_key)
        ])

    if duplicate is not None:
        edge_uuid = duplicate["uuid"]
        old_attributes = json_loads(duplicate["attributes_json"], {})
        old_attributes = old_attributes if isinstance(old_attributes, dict) else {}
        merged = _merge_attributes(old_attributes, attributes)
        if merged != old_attributes or (duplicate["valid_at"] is None and valid_at):
            conn.execute(
                "UPDATE edges SET attributes_json = ?, valid_at = COALESCE(valid_at, ?) WHERE uuid = ?",
                (json_dumps(merged), valid_at, edge_uuid),
            )
        created = False
    else:
        edge_uuid = new_id()
        conn.execute(
            "INSERT INTO edges(uuid, graph_id, name, fact, fact_key, source_node_uuid, "
            "target_node_uuid, attributes_json, origin, created_at, valid_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (edge_uuid, graph_id, name, fact, fact_key, source, target, json_dumps(dict(attributes)),
             RULES_ORIGIN, now, valid_at),
        )
        created = True
    conn.execute(
        "INSERT OR IGNORE INTO edge_episodes(edge_uuid, episode_uuid, linked_at) VALUES (?, ?, ?)",
        (edge_uuid, episode_uuid, now),
    )
    return created


def apply_activity_rules(conn: sqlite3.Connection, *, graph_id: str, episode_uuid: str,
                         content: str, reference_time: str | None,
                         simulation_id: str | None = None, now: str | None = None,
                         parsed: ActivityParse | None = None) -> RulesResult:
    """Write the rules nodes and edges for one activity episode (§5.2).

    Must run inside a write transaction (``store.write()``), after the episode
    row exists. Per parsed line:

    - the agent resolves by alias keys (``resolution.resolve_existing``: an
      exact name first, else the highest ``mention_count``), which is a typed
      entity when the account came from the graph; otherwise a generic
      ``["Entity"]`` node with ``origin='rules'`` is created;
    - the target is a person (resolved the same way) or the platform hub
      (``Twitter``/``Reddit``, reusing an existing node of that name);
    - one directed event edge ``agent -ACTION-> target`` with the
      :func:`activity_fact` of the line (``{agent}在{Platform}{desc}`` or
      ``On {Platform}, {agent} {desc}``), ``valid_at`` from the line
      timestamp (else the episode reference time), string attributes
      ``platform``/``round``/``simulation_id``/``action`` and an episode link.
      A repeated identical action, or the same template with near-identical
      content, links the episode to the existing edge.

    A line without an agent name is skipped (``skipped_lines``).

    A node created here gets a summary in the language of the line that
    created it (Chinese or English).

    Existing nodes are only linked to the episode; their ``mention_count``
    is left alone so simulated chatter does not outrank document entities.
    Bumps ``graphs.version`` when anything was written.
    """

    now = now or utcnow_iso()
    parsed = parsed if parsed is not None else parse_activity_text(content)
    result = RulesResult(lines=len(parsed.lines), unparsed=len(parsed.unparsed),
                         signal_lines=len(parsed.signal_lines))
    if not parsed.lines:
        return result

    sim_key = simulation_key(simulation_id)
    resolver = _NodeResolver(conn, graph_id, episode_uuid, now, result)
    for line in parsed.lines:
        agent_uuid = resolver.account(line.agent, line.platform_name, line.language)
        if not agent_uuid:  # a blank agent name: nothing to attribute, not even a target node
            result.skipped_lines += 1
            continue
        if line.target:
            target_uuid = resolver.account(line.target, line.platform_name, line.language)
        else:
            target_uuid = resolver.hub(line.platform_name, line.language)
        if not target_uuid:
            result.skipped_lines += 1
            continue
        if agent_uuid == target_uuid:
            result.self_loops += 1
            continue
        valid_at = parse_local_iso_datetime(line.timestamp) or parse_iso_datetime(reference_time)
        attributes = {
            "platform": line.platform,
            "round": str(line.round),
            "simulation_id": sim_key,
            "action": line.action,
        }
        created = _write_event_edge(
            conn, graph_id=graph_id, name=line.action, source=agent_uuid, target=target_uuid,
            fact=activity_fact(line), fact_head=_fact_head(line), valid_at=valid_at, attributes=attributes,
            episode_uuid=episode_uuid, now=now,
        )
        if created:
            result.edges_created += 1
        else:
            result.edges_merged += 1

    if result.changed:
        bump_graph_version(conn, graph_id)
    return result


_RULES_SAVEPOINT = "memory_activity_rules"


def _apply_rules_contained(conn: sqlite3.Connection, **kwargs: Any) -> RulesResult:
    """Run the rules in a SAVEPOINT; a non-busy failure is logged and undone."""

    conn.execute(f"SAVEPOINT {_RULES_SAVEPOINT}")
    try:
        result = apply_activity_rules(conn, **kwargs)
    except Exception as error:  # rules are best effort: graph.add must not fail
        try:
            conn.execute(f"ROLLBACK TO {_RULES_SAVEPOINT}")
            conn.execute(f"RELEASE {_RULES_SAVEPOINT}")
        except sqlite3.Error:
            pass
        if isinstance(error, sqlite3.OperationalError) and is_busy_sqlite_error(error):
            raise
        logger.warning(
            "Activity rules extraction failed for episode %s (%s); keeping the episode only",
            kwargs.get("episode_uuid"), type(error).__name__,
        )
        logger.debug("Activity rules failure detail", exc_info=True)
        return RulesResult(error=type(error).__name__)
    conn.execute(f"RELEASE {_RULES_SAVEPOINT}")
    return result


# ---------------------------------------------------------------------------
# Ingestion entry point for graph.add (§5.1)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ActivityIngestResult:
    """Final episode state chosen by :func:`ingest_activity_episode`."""

    mode: str
    extraction_status: str
    processed: bool
    queued: bool
    rules: RulesResult | None = None
    error: Mapping[str, str] | None = None


def ingest_activity_episode(conn: sqlite3.Connection, episode_uuid: str, *, mode: str,
                            now: str | None = None) -> ActivityIngestResult:
    """Apply the activity mode to a freshly inserted activity episode.

    Call inside the ``graph.add`` write transaction, right after inserting the
    episode row (``kind='activity'``; its initial status does not matter).
    Sets ``processed``, ``extraction_status``, ``extraction_error`` and
    ``queued_at`` on the row and returns the chosen state. Never calls an
    LLM and never raises for a rules failure (only for a busy store or a
    missing episode). ``now`` is the ISO time used for ``queued_at`` and the
    rows written (defaults to the current time).
    """

    mode = normalize_activity_mode(mode)
    now = now or utcnow_iso()
    row = conn.execute(
        "SELECT graph_id, content, reference_time, simulation_id, metadata_json "
        "FROM episodes WHERE uuid = ?",
        (episode_uuid,),
    ).fetchone()
    if row is None:
        raise not_found("episode not found")

    if mode == MODE_OFF:
        _set_episode_state(conn, episode_uuid, status="skipped", processed=True)
        return ActivityIngestResult(mode, "skipped", True, False)

    sim_id = row["simulation_id"]
    if not sim_id:
        metadata = json_loads(row["metadata_json"], {})
        sim_id = metadata.get("simulation_id") if isinstance(metadata, dict) else None
    rules = _apply_rules_contained(
        conn, graph_id=row["graph_id"], episode_uuid=episode_uuid, content=row["content"],
        reference_time=row["reference_time"], simulation_id=sim_id, now=now,
    )
    rules_error = _error(ERROR_RULES, f"Rules extraction failed ({rules.error}).") if rules.error else None

    if mode == MODE_LLM and (rules.error or rules.signal_lines):
        _set_episode_state(conn, episode_uuid, status="queued", processed=False, queued_at=now)
        return ActivityIngestResult(mode, "queued", False, True, rules)

    # rules mode, or llm mode with nothing worth an LLM call.
    status = "degraded" if rules_error else "succeeded"
    _set_episode_state(conn, episode_uuid, status=status, processed=True, error=rules_error)
    return ActivityIngestResult(mode, status, True, False, rules, rules_error)


def _set_episode_state(conn: sqlite3.Connection, episode_uuid: str, *, status: str, processed: bool,
                       queued_at: str | None = None, error: Mapping[str, str] | None = None) -> None:
    conn.execute(
        "UPDATE episodes SET processed = ?, extraction_status = ?, extraction_error = ?, "
        "queued_at = ?, lease_owner = NULL, lease_until = NULL WHERE uuid = ?",
        (1 if processed else 0, status, json_dumps(dict(error)) if error else None, queued_at,
         episode_uuid),
    )


# ---------------------------------------------------------------------------
# LLM enrichment planning (§5.3): pure functions the worker schedules
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ActivityPolicy:
    """The §1.1 activity knobs the scheduler needs."""

    group_size: int = 8
    group_chars: int = 12000
    group_wait_seconds: float = 15.0
    max_pending_seconds: float = 300.0
    max_llm_calls: int = 60

    @classmethod
    def from_settings(cls, settings: Any) -> "ActivityPolicy":
        return cls(
            group_size=max(1, int(settings.activity_group_size)),
            group_chars=max(1, int(settings.activity_group_chars)),
            group_wait_seconds=float(settings.activity_group_wait_seconds),
            max_pending_seconds=float(settings.activity_max_pending_seconds),
            max_llm_calls=int(settings.activity_max_llm_calls),
        )


def _row_value(row: Any, key: str, default: Any = None) -> Any:
    try:
        value = row[key]
    except (KeyError, IndexError, TypeError):
        return getattr(row, key, default)
    return default if value is None else value


@dataclass(frozen=True)
class ActivityCandidate:
    """A queued activity episode as the scheduler sees it."""

    uuid: str
    graph_id: str
    simulation_key: str
    created_at: str  # ingestion time (ISO); orders episodes within a graph
    queued_at: float | None  # epoch seconds
    chars: int  # prompt characters this episode contributes (its signal records)
    reference_time: str = ""
    row_id: int = 0

    @classmethod
    def from_row(cls, row: Any) -> "ActivityCandidate":
        """Build from an ``episodes`` row (needs uuid, graph_id, created_at, content)."""

        sim_id = _row_value(row, "simulation_id")
        if not sim_id:
            metadata = json_loads(_row_value(row, "metadata_json"), {})
            sim_id = metadata.get("simulation_id") if isinstance(metadata, dict) else None
        created_at = str(_row_value(row, "created_at", ""))
        queued = _row_value(row, "queued_at")
        return cls(
            uuid=str(_row_value(row, "uuid")),
            graph_id=str(_row_value(row, "graph_id")),
            simulation_key=simulation_key(sim_id),
            created_at=created_at,
            queued_at=iso_to_epoch(queued) if queued else iso_to_epoch(created_at),
            chars=len(signal_text(str(_row_value(row, "content", "")))),
            reference_time=str(_row_value(row, "reference_time", "")),
            row_id=int(_row_value(row, "id", 0) or 0),
        )

    def waited(self, now: float) -> float:
        """Seconds since the episode was queued (infinite when unknown)."""

        if self.queued_at is None:
            return float("inf")
        return max(0.0, now - self.queued_at)


@dataclass(frozen=True)
class ActivityGroup:
    """Episodes of one graph and simulation enriched by a single LLM call."""

    graph_id: str
    simulation_key: str
    episodes: tuple[ActivityCandidate, ...]
    reason: str  # "size" | "chars" | "wait" | "force"

    @property
    def uuids(self) -> tuple[str, ...]:
        return tuple(candidate.uuid for candidate in self.episodes)

    @property
    def chars(self) -> int:
        return sum(candidate.chars for candidate in self.episodes)

    @property
    def has_signal(self) -> bool:
        return self.chars > 0


def expired_activity_candidates(candidates: Iterable[ActivityCandidate], policy: ActivityPolicy,
                                now: float) -> list[ActivityCandidate]:
    """Queued episodes that waited longer than ``max_pending_seconds``."""

    return [c for c in candidates if c.waited(now) > policy.max_pending_seconds]


def plan_activity_groups(candidates: Iterable[ActivityCandidate], policy: ActivityPolicy, *,
                         now: float, force: bool = False) -> list[ActivityGroup]:
    """Split queued episodes into ready enrichment groups (§5.3).

    Episodes are partitioned by ``(graph_id, simulation_key)`` (the budget is
    per simulation), ordered by ``created_at``, and packed greedily into
    groups of at most ``group_size`` episodes and ``group_chars`` signal
    characters. An episode larger than the cap forms its own group. A closed
    group is always ready. The last, partial group of a partition is ready
    only when it is full, reached the character cap, its oldest episode has
    waited ``group_wait_seconds``, or ``force`` is true (``drain()``).

    The result is in lane order: ``graph_id``, then simulation, then time.
    Groups of one graph must run sequentially in that order.
    """

    partitions: dict[tuple[str, str], list[ActivityCandidate]] = {}
    for candidate in candidates:
        partitions.setdefault((candidate.graph_id, candidate.simulation_key), []).append(candidate)

    groups: list[ActivityGroup] = []
    for (graph_id, sim_key) in sorted(partitions):
        items = sorted(partitions[(graph_id, sim_key)], key=lambda c: (c.created_at, c.row_id, c.uuid))
        current: list[ActivityCandidate] = []
        chars = 0
        for candidate in items:
            if current and (len(current) >= policy.group_size or chars + candidate.chars > policy.group_chars):
                reason = "size" if len(current) >= policy.group_size else "chars"
                groups.append(ActivityGroup(graph_id, sim_key, tuple(current), reason))
                current, chars = [], 0
            current.append(candidate)
            chars += candidate.chars
        if not current:
            continue
        tail_reason: str | None = None
        if len(current) >= policy.group_size:
            tail_reason = "size"
        elif chars >= policy.group_chars:
            tail_reason = "chars"
        elif max(c.waited(now) for c in current) >= policy.group_wait_seconds:
            tail_reason = "wait"
        elif force:
            tail_reason = "force"
        if tail_reason:
            groups.append(ActivityGroup(graph_id, sim_key, tuple(current), tail_reason))
    return groups


class ActivityLane:
    """Process-lifetime state of the single activity-enrichment lane.

    A fatal LLM condition (quota, auth, not configured) switches the lane to
    rules-only until the process restarts. Both that switch and each
    simulation's budget exhaustion are logged once.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._disabled: dict[str, str] | None = None
        self._budget_logged: set[str] = set()

    @property
    def enabled(self) -> bool:
        return self._disabled is None

    @property
    def disabled_error(self) -> dict[str, str] | None:
        return dict(self._disabled) if self._disabled else None

    def disable(self, error: Mapping[str, Any] | None) -> bool:
        """Switch to rules-only. Returns True the first time only."""

        with self._lock:
            if self._disabled is not None:
                return False
            code = str((error or {}).get("code") or "llm_error")
            self._disabled = {"code": code}
        logger.warning(
            "Activity enrichment disabled for this process after a fatal LLM error (%s); "
            "simulation activity keeps rules-only facts", code,
        )
        return True

    def note_budget_exhausted(self, sim_key: str, used: int, limit: int) -> bool:
        """Record an exhausted budget. Returns True (and logs) the first time per simulation."""

        with self._lock:
            if sim_key in self._budget_logged:
                return False
            self._budget_logged.add(sim_key)
        logger.info(
            "Activity enrichment budget used up for simulation %s (%d of %d calls); "
            "further activity keeps rules-only facts", sim_key, used, limit,
        )
        return True


@dataclass(frozen=True)
class ActivityDecision:
    """What to do with a group: call the LLM, or finish its episodes now."""

    call: bool
    status: str | None = None  # terminal episode status when not calling / after a failure
    error: Mapping[str, str] | None = None


CALL_LLM = ActivityDecision(call=True)


def decide_activity_group(group: ActivityGroup, *, lane: ActivityLane, calls_used: int,
                          policy: ActivityPolicy) -> ActivityDecision:
    """Signal filter, lane state and budget check, before any LLM call (§5.3).

    ``calls_used`` is ``usage('simulation', group.simulation_key).llm_calls``.
    """

    if not group.has_signal:
        return ActivityDecision(False, "skipped", _error(ERROR_NO_SIGNAL))
    if not lane.enabled:
        return ActivityDecision(False, "skipped", _error(ERROR_LANE_DISABLED))
    if calls_used >= policy.max_llm_calls:
        lane.note_budget_exhausted(group.simulation_key, calls_used, policy.max_llm_calls)
        return ActivityDecision(False, "skipped", _error(ERROR_BUDGET))
    return CALL_LLM


def activity_failure_decision(error: Mapping[str, Any] | None, *, lane: ActivityLane) -> ActivityDecision:
    """Outcome of an enrichment call that gave up (after its retries).

    The rules edges already exist, so the episodes finish ``degraded`` with
    the extraction error. A fatal code also switches the lane to rules-only.
    """

    error = error or {}
    code = str(error.get("code") or "extraction_error")
    message = error.get("message")
    if code in FATAL_LLM_CODES:
        lane.disable({"code": code})
    return ActivityDecision(False, "degraded", _error(code, str(message) if message else code))


# ---------------------------------------------------------------------------
# Enrichment prompt (§5.3)
# ---------------------------------------------------------------------------

ACTIVITY_SYSTEM_PROMPT = """You are a knowledge-graph extraction engine. The TEXT is a log of social-media actions by \
simulated accounts. Return ONLY one JSON object describing what the accounts said.

Extract:
(a) stances and opinions an account expresses about people, organizations or topics. Use a RELATION TYPES name when \
it fits AND the source->target type pair is allowed; otherwise one of SUPPORTS, OPPOSES, CRITICIZES, PRAISES, \
QUESTIONS, DISCUSSES.
(b) claims made in posts, phrased as attributed facts ("X claimed that ...").
Skip likes, follows, mutes and searches; they are already recorded.

Rules:
1. Accounts are listed in KNOWN ENTITIES. Reference an account by that exact name. Never invent entities, facts or \
dates.
2. People, organizations and topics discussed in posts are entities too. "type": exactly one name from ENTITY TYPES \
when the entity clearly fits it, otherwise "Entity".
3. "summary": 1-2 sentences about the entity based only on TEXT, in the language of TEXT.
4. "attributes": only keys listed for that entity type, string values, omit unknown values.
5. Every relation connects two entities from your "entities" list (include the accounts you use), referenced by \
exact "name".
6. "fact": one self-contained sentence stating the relation and naming both entities, in the language of TEXT.
7. "valid_at" / "invalid_at": ISO 8601 date or datetime only when TEXT says when the stance or claim started / \
ended; otherwise null. Each line starts with the time of the action.
8. "chunks": the [episode N] numbers the relation comes from.
9. "invalidated_facts": ids from EXISTING FACTS that an account explicitly retracts or reverses (for example a \
changed opinion), with "invalid_at" when TEXT says when. Leave empty when unsure.
10. At most {max_entities} entities and {max_relations} relations; keep the most important.
11. Output JSON only. No markdown, no commentary."""

RETURN_SHAPE = 'Return: {"entities":[...],"relations":[...],"invalidated_facts":[...]}'


def activity_system_prompt(max_entities: int = 30, max_relations: int = 50) -> str:
    """:data:`ACTIVITY_SYSTEM_PROMPT` with the per-call limits filled in."""

    return ACTIVITY_SYSTEM_PROMPT.replace("{max_entities}", str(int(max_entities))).replace(
        "{max_relations}", str(int(max_relations))
    )


class PromptFact(NamedTuple):
    """One EXISTING FACTS line; ``short_id`` (F1..Fn) maps to an edge uuid per call."""

    short_id: str
    source: str
    name: str
    target: str
    fact: str
    valid_at: str | None = None


@dataclass(frozen=True)
class ActivityWindow:
    """The TEXT block of one enrichment call and its episode markers."""

    text: str
    markers: Mapping[int, str]  # [episode N] -> episode uuid
    episode_uuids: tuple[str, ...]  # every episode of the group, with or without signal
    accounts: tuple[str, ...]  # agents and person targets of the signal lines, first-seen order
    reference_time: str | None

    @property
    def has_signal(self) -> bool:
        return bool(self.markers)


def render_activity_window(episodes: Sequence[Any]) -> ActivityWindow:
    """Render the signal records of a group's episodes, in the given order.

    ``episodes`` are rows or mappings with ``uuid``, ``content`` and
    ``reference_time``. Each episode that has signal records gets a
    ``[episode N | time T]`` marker (T is its reference time); episodes
    without signal are left out of the text but stay in ``episode_uuids``.
    """

    blocks: list[str] = []
    markers: dict[int, str] = {}
    accounts: dict[str, None] = {}
    uuids: list[str] = []
    latest: str | None = None
    for row in episodes:
        episode_uuid = str(_row_value(row, "uuid"))
        uuids.append(episode_uuid)
        reference = parse_iso_datetime(_row_value(row, "reference_time"))
        lines = parse_activity_text(str(_row_value(row, "content", ""))).signal_lines
        if not lines:
            continue
        number = len(markers) + 1
        markers[number] = episode_uuid
        header = f"[episode {number} | time {reference}]" if reference else f"[episode {number}]"
        blocks.append("\n".join([header, *(line.text for line in lines)]))
        for line in lines:
            accounts.setdefault(line.agent, None)
            if line.target:
                accounts.setdefault(line.target, None)
        if reference and (latest is None or reference > latest):
            latest = reference
    return ActivityWindow("\n".join(blocks), markers, tuple(uuids), tuple(accounts), latest)


def _render_known(known_entities: Iterable[tuple[str, str | None]]) -> str:
    parts = [f"{name} [{entity_type or GENERIC_ENTITY}]" for name, entity_type in known_entities if name]
    return "KNOWN ENTITIES (reuse these exact names): " + ("; ".join(parts) if parts else "(none)")


def _render_facts(facts: Iterable[PromptFact]) -> str:
    lines = []
    for fact in facts:
        line = f'{fact.short_id}: {fact.source} -{fact.name}-> {fact.target}: "{fact.fact}"'
        if fact.valid_at:
            line += f" (valid_at {fact.valid_at})"
        lines.append(line)
    return "EXISTING FACTS:\n" + "\n".join(lines) if lines else "EXISTING FACTS: (none)"


def build_activity_messages(window: ActivityWindow, *, ontology: OntologyView | None = None,
                            known_entities: Iterable[tuple[str, str | None]] = (),
                            existing_facts: Iterable[PromptFact] = (), max_entities: int = 30,
                            max_relations: int = 50) -> list[dict[str, str]]:
    """``[system, user]`` messages for one enrichment call (§4.4 layout).

    ``known_entities`` are ``(name, type)`` pairs, normally the resolved
    account nodes first; ``existing_facts`` are the accounts' active facts,
    offered for invalidation.
    """

    view = ontology or OntologyView(None)
    user = "\n".join([
        f"REFERENCE TIME: {window.reference_time or utcnow_iso()}",
        view.render_entity_types(),
        view.render_relation_types(),
        _render_known(known_entities),
        _render_facts(existing_facts),
        "TEXT:",
        "<<<",
        window.text,
        ">>>",
        RETURN_SHAPE,
    ])
    return [
        {"role": "system", "content": activity_system_prompt(max_entities, max_relations)},
        {"role": "user", "content": user},
    ]


# ---------------------------------------------------------------------------
# SQL helpers for the scheduler (run inside store.read()/store.write())
# ---------------------------------------------------------------------------


def load_activity_candidates(conn: sqlite3.Connection, *, limit: int = 1000) -> list[ActivityCandidate]:
    """Queued activity episodes, oldest first per graph."""

    rows = conn.execute(
        "SELECT id, uuid, graph_id, content, simulation_id, metadata_json, created_at, queued_at, "
        "reference_time FROM episodes WHERE kind = 'activity' AND extraction_status = 'queued' "
        "ORDER BY graph_id, created_at, id LIMIT ?",
        (max(1, int(limit)),),
    ).fetchall()
    return [ActivityCandidate.from_row(row) for row in rows]


def _in_clause(values: Sequence[str]) -> str:
    return ",".join("?" for _ in values)


def claim_activity_episodes(conn: sqlite3.Connection, uuids: Sequence[str], *, owner: str,
                            lease_until: float) -> list[str]:
    """Lease the still-queued episodes of a group; returns the uuids claimed."""

    uuids = list(dict.fromkeys(uuids))
    if not uuids:
        return []
    claimed = [
        row[0] for row in conn.execute(
            f"SELECT uuid FROM episodes WHERE uuid IN ({_in_clause(uuids)}) "
            "AND kind = 'activity' AND extraction_status = 'queued'",
            uuids,
        )
    ]
    if claimed:
        conn.execute(
            "UPDATE episodes SET extraction_status = 'processing', lease_owner = ?, lease_until = ?, "
            f"attempts = attempts + 1 WHERE uuid IN ({_in_clause(claimed)})",
            (owner, float(lease_until), *claimed),
        )
    return claimed


def finish_activity_episodes(conn: sqlite3.Connection, uuids: Sequence[str], *, status: str,
                             error: Mapping[str, Any] | None = None) -> int:
    """Set ``processed=1`` and a terminal status on queued/processing activity episodes.

    Episodes already in a terminal state are left alone. Returns the number
    of rows changed.
    """

    if status not in EPISODE_TERMINAL_STATUSES:
        raise ValueError(f"not a terminal episode status: {status}")
    uuids = list(dict.fromkeys(uuids))
    if not uuids:
        return 0
    cursor = conn.execute(
        "UPDATE episodes SET processed = 1, extraction_status = ?, extraction_error = ?, "
        "lease_owner = NULL, lease_until = NULL "
        f"WHERE uuid IN ({_in_clause(uuids)}) AND kind = 'activity' "
        "AND extraction_status IN ('pending', 'queued', 'processing')",
        (status, json_dumps(dict(error)) if error else None, *uuids),
    )
    return cursor.rowcount


def sweep_expired_activity_episodes(conn: sqlite3.Connection, *, now: float,
                                    max_pending_seconds: float) -> list[str]:
    """Deadline sweep: queued episodes older than the limit become ``skipped``.

    ``now`` is epoch seconds (the worker's clock). ``queued_at`` (falling back
    to ``created_at``) must be in the stored timestamp format, which sorts
    chronologically. Returns the swept uuids.
    """

    cutoff = epoch_to_iso(now - float(max_pending_seconds))
    uuids = [
        row[0] for row in conn.execute(
            "SELECT uuid FROM episodes WHERE kind = 'activity' AND extraction_status = 'queued' "
            "AND COALESCE(queued_at, created_at) < ? ORDER BY id",
            (cutoff,),
        )
    ]
    if uuids:
        finish_activity_episodes(conn, uuids, status="skipped", error=_error(ERROR_DEADLINE))
        logger.info("Activity enrichment deadline passed for %d queued episode(s)", len(uuids))
    return uuids


def activity_llm_calls_used(conn: sqlite3.Connection, sim_key: str) -> int:
    """``usage('simulation', sim_key).llm_calls`` (0 when there is no row)."""

    row = conn.execute(
        "SELECT llm_calls FROM usage WHERE scope_kind = 'simulation' AND scope_id = ?",
        (sim_key,),
    ).fetchone()
    return int(row[0]) if row else 0


def record_activity_llm_call(conn: sqlite3.Connection, *, sim_key: str, graph_id: str,
                             prompt_chars: int = 0, output_chars: int = 0, failed: bool = False,
                             now: str | None = None) -> None:
    """Count one enrichment call against the simulation budget and the graph usage."""

    now = now or utcnow_iso()
    for scope_kind, scope_id in (("simulation", sim_key), ("graph", graph_id)):
        conn.execute(
            "INSERT INTO usage(scope_kind, scope_id, llm_calls, llm_failures, prompt_chars, "
            "output_chars, updated_at) VALUES (?, ?, 1, ?, ?, ?, ?) "
            "ON CONFLICT(scope_kind, scope_id) DO UPDATE SET "
            "llm_calls = llm_calls + 1, llm_failures = llm_failures + excluded.llm_failures, "
            "prompt_chars = prompt_chars + excluded.prompt_chars, "
            "output_chars = output_chars + excluded.output_chars, updated_at = excluded.updated_at",
            (scope_kind, scope_id, 1 if failed else 0, max(0, int(prompt_chars)),
             max(0, int(output_chars)), now),
        )
