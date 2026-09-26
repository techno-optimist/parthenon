"""Simulation activity episodes (spec §5): the rules parser contract against the
updater's real templates (Chinese and English), rules writes, activity modes
and the LLM-enrichment planning helpers (grouping, signal filter, budget,
deadline, failures)."""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from types import SimpleNamespace
from typing import Any

import pytest
from zep_cloud.core.api_error import ApiError as ZepApiError
from zep_cloud.errors import NotFoundError

from app.memory import activity as activity_module
from app.memory import new_id, utcnow_iso
from app.memory.activity import (
    ACTIVITY_SOURCE,
    MAX_FACT_CHARS,
    ActivityCandidate,
    ActivityLane,
    ActivityPolicy,
    PromptFact,
    activity_fact,
    activity_failure_decision,
    activity_llm_calls_used,
    activity_system_prompt,
    build_activity_messages,
    claim_activity_episodes,
    classify_activity_description,
    decide_activity_group,
    expired_activity_candidates,
    finish_activity_episodes,
    ingest_activity_episode,
    is_activity_metadata,
    load_activity_candidates,
    normalize_activity_mode,
    parse_activity_text,
    plan_activity_groups,
    platform_display_name,
    record_activity_llm_call,
    render_activity_window,
    signal_text,
    simulation_key,
    sweep_expired_activity_episodes,
)
from app.memory.models import edge_from_row, episode_from_row, json_loads
from app.memory.ontology import OntologyView
from app.memory.textnorm import (
    epoch_to_iso,
    iso_to_epoch,
    parse_iso_datetime,
    parse_local_iso_datetime,
)
from app.services.zep_graph_memory_updater import AgentActivity, ZepGraphMemoryUpdater

# Same patterns as the FakeLLM in conftest.py (tests/ is not a package, so they are repeated here).
_TEXT_BLOCK_RE = re.compile(r"<<<\n?(?P<text>.*?)\n?>>>", re.S)
_CHUNK_MARKER_RE = re.compile(r"^\[(?:chunk|episode) (?P<n>\d+)[^\]]*\]\s*$")


def text_block(messages: list[dict[str, str]]) -> str:
    """The ``TEXT: <<< ... >>>`` block of the last user message."""

    for message in reversed(messages):
        if message.get("role") == "user":
            match = _TEXT_BLOCK_RE.search(message.get("content") or "")
            return match.group("text") if match else ""
    return ""


TS = "2026-07-01T09:00:00Z"
TS_UTC = "2026-07-01T09:00:00.000000Z"
T0 = 1_800_000_000.0  # fixed worker clock for scheduling tests


def _activity(action_type: str, args: dict[str, Any] | None = None, *, agent: str = "陈屿",
              platform: str = "twitter", round_num: int = 3, ts: str = TS) -> AgentActivity:
    return AgentActivity(
        platform=platform,
        agent_id=7,
        agent_name=agent,
        action_type=action_type,
        action_args=args or {},
        round_num=round_num,
        timestamp=ts,
    )


def _only_line(activity: AgentActivity, locale: str | None = None):
    parsed = parse_activity_text(activity.to_episode_text(locale))
    assert not parsed.unparsed
    assert len(parsed.lines) == 1
    return parsed.lines[0]


def _fake_updater(locale: str = "zh") -> SimpleNamespace:
    """Enough of an updater for ``ZepGraphMemoryUpdater._build_episode_payloads``."""

    return SimpleNamespace(MAX_EPISODE_CHARS=ZepGraphMemoryUpdater.MAX_EPISODE_CHARS, locale=locale)


# ---------------------------------------------------------------------------
# Contract: every template in zep_graph_memory_updater.AgentActivity, in both
# languages. Chinese and English descriptions of the same action must parse
# into the same edge name, target and signal flag.
# ---------------------------------------------------------------------------

POST = "海城市新总部今天启用，智巡平台商业服务正常运行。"
QUOTE = "作为首席战略顾问，我支持陈屿和新的管理团队。"
COMMENT = "联合部署协议虽已终止，但我们仍是智巡平台客户。"

# (id, action_type, action_args, expected edge name, expected person target, expected signal)
CONTRACT_CASES: list[tuple[str, str, dict[str, Any], str, str | None, bool]] = [
    ("create_post", "CREATE_POST", {"content": POST}, "POSTED", None, True),
    ("create_post_empty", "CREATE_POST", {}, "POSTED", None, False),
    ("like_post_author_content", "LIKE_POST", {"post_author_name": "周岚", "post_content": POST},
     "LIKED_POST_OF", "周岚", False),
    ("like_post_content", "LIKE_POST", {"post_content": POST}, "LIKED_POST", None, False),
    ("like_post_author", "LIKE_POST", {"post_author_name": "周岚"}, "LIKED_POST_OF", "周岚", False),
    ("like_post_bare", "LIKE_POST", {}, "LIKED_POST", None, False),
    ("dislike_post_author_content", "DISLIKE_POST", {"post_author_name": "周岚", "post_content": POST},
     "DISLIKED_POST_OF", "周岚", False),
    ("dislike_post_content", "DISLIKE_POST", {"post_content": POST}, "DISLIKED_POST", None, False),
    ("dislike_post_author", "DISLIKE_POST", {"post_author_name": "周岚"}, "DISLIKED_POST_OF", "周岚", False),
    ("dislike_post_bare", "DISLIKE_POST", {}, "DISLIKED_POST", None, False),
    ("repost_author_content", "REPOST", {"original_author_name": "周岚", "original_content": POST},
     "REPOSTED", "周岚", True),
    ("repost_content", "REPOST", {"original_content": POST}, "REPOSTED", None, True),
    ("repost_author", "REPOST", {"original_author_name": "周岚"}, "REPOSTED", "周岚", False),
    ("repost_bare", "REPOST", {}, "REPOSTED", None, False),
    ("quote_author_content_quote", "QUOTE_POST",
     {"original_author_name": "周岚", "original_content": POST, "quote_content": QUOTE}, "QUOTED", "周岚", True),
    ("quote_author_content", "QUOTE_POST", {"original_author_name": "周岚", "original_content": POST},
     "QUOTED", "周岚", True),
    ("quote_content_quote", "QUOTE_POST", {"original_content": POST, "quote_content": QUOTE},
     "QUOTED", None, True),
    ("quote_content", "QUOTE_POST", {"original_content": POST}, "QUOTED", None, True),
    ("quote_author_quote", "QUOTE_POST", {"original_author_name": "周岚", "quote_content": QUOTE},
     "QUOTED", "周岚", True),
    ("quote_author", "QUOTE_POST", {"original_author_name": "周岚"}, "QUOTED", "周岚", False),
    ("quote_quote_via_content", "QUOTE_POST", {"content": QUOTE}, "QUOTED", None, True),
    ("quote_bare", "QUOTE_POST", {}, "QUOTED", None, False),
    ("follow_user", "FOLLOW", {"target_user_name": "海岳能源"}, "FOLLOWS", "海岳能源", False),
    ("follow_bare", "FOLLOW", {}, "FOLLOWS", None, False),
    ("comment_author_post", "CREATE_COMMENT",
     {"post_author_name": "周岚", "post_content": POST, "content": COMMENT},
     "COMMENTED_ON_POST_OF", "周岚", True),
    ("comment_post", "CREATE_COMMENT", {"post_content": POST, "content": COMMENT}, "COMMENTED", None, True),
    ("comment_author", "CREATE_COMMENT", {"post_author_name": "周岚", "content": COMMENT},
     "COMMENTED_ON_POST_OF", "周岚", True),
    ("comment_only", "CREATE_COMMENT", {"content": COMMENT}, "COMMENTED", None, True),
    ("comment_empty", "CREATE_COMMENT", {"post_author_name": "周岚", "post_content": POST},
     "COMMENTED", None, False),
    ("like_comment_author_content", "LIKE_COMMENT",
     {"comment_author_name": "周岚", "comment_content": COMMENT}, "LIKED_COMMENT_OF", "周岚", False),
    ("like_comment_content", "LIKE_COMMENT", {"comment_content": COMMENT}, "LIKED_COMMENT", None, False),
    ("like_comment_author", "LIKE_COMMENT", {"comment_author_name": "周岚"}, "LIKED_COMMENT_OF", "周岚", False),
    ("like_comment_bare", "LIKE_COMMENT", {}, "LIKED_COMMENT", None, False),
    ("dislike_comment_author_content", "DISLIKE_COMMENT",
     {"comment_author_name": "周岚", "comment_content": COMMENT}, "DISLIKED_COMMENT_OF", "周岚", False),
    ("dislike_comment_content", "DISLIKE_COMMENT", {"comment_content": COMMENT}, "DISLIKED_COMMENT", None, False),
    ("dislike_comment_author", "DISLIKE_COMMENT", {"comment_author_name": "周岚"},
     "DISLIKED_COMMENT_OF", "周岚", False),
    ("dislike_comment_bare", "DISLIKE_COMMENT", {}, "DISLIKED_COMMENT", None, False),
    ("search_query", "SEARCH_POSTS", {"query": "智巡平台"}, "SEARCHED", None, False),
    ("search_keyword", "SEARCH_POSTS", {"keyword": "智巡平台"}, "SEARCHED", None, False),
    ("search_bare", "SEARCH_POSTS", {}, "SEARCHED", None, False),
    ("search_user_query", "SEARCH_USER", {"query": "周岚"}, "SEARCHED_USER", None, False),
    ("search_user_username", "SEARCH_USER", {"username": "周岚"}, "SEARCHED_USER", None, False),
    ("search_user_bare", "SEARCH_USER", {}, "SEARCHED_USER", None, False),
    ("mute_user", "MUTE", {"target_user_name": "海岳能源"}, "MUTED", "海岳能源", False),
    ("mute_bare", "MUTE", {}, "MUTED", None, False),
    ("generic_unfollow", "UNFOLLOW", {"target_user_name": "周岚"}, "PERFORMED_UNFOLLOW", None, False),
    ("generic_join_group", "JOIN_GROUP", {}, "PERFORMED_JOIN_GROUP", None, False),
    ("generic_empty_type", "", {}, "ACTED", None, False),
]

# The describer methods the cases above cover. A new template method in the
# updater must be added to CONTRACT_CASES and to activity.py.
EXPECTED_DESCRIBERS = {
    "_describe_create_post", "_describe_like_post", "_describe_dislike_post", "_describe_repost",
    "_describe_quote_post", "_describe_follow", "_describe_create_comment", "_describe_like_comment",
    "_describe_dislike_comment", "_describe_search", "_describe_search_user", "_describe_mute",
    "_describe_generic",
}
TEMPLATED_ACTION_TYPES = [
    "CREATE_POST", "LIKE_POST", "DISLIKE_POST", "REPOST", "QUOTE_POST", "FOLLOW", "CREATE_COMMENT",
    "LIKE_COMMENT", "DISLIKE_COMMENT", "SEARCH_POSTS", "SEARCH_USER", "MUTE",
]


def test_updater_templates_are_all_covered():
    describers = {name for name in vars(AgentActivity) if name.startswith("_describe_")}
    assert describers == EXPECTED_DESCRIBERS
    covered = {case[1] for case in CONTRACT_CASES}
    assert set(TEMPLATED_ACTION_TYPES) <= covered
    for action_type in TEMPLATED_ACTION_TYPES:
        # A dedicated template, never the generic fallback.
        assert "执行了" not in _activity(action_type).to_episode_text()
        assert "performed" not in _activity(action_type).to_episode_text("en")


@pytest.mark.parametrize("locale", ["zh", "en"])
@pytest.mark.parametrize(
    "action_type,args,expected_action,expected_target,expected_signal",
    [case[1:] for case in CONTRACT_CASES],
    ids=[case[0] for case in CONTRACT_CASES],
)
def test_rules_parser_matches_updater_templates(action_type, args, expected_action, expected_target,
                                                expected_signal, locale):
    activity = _activity(action_type, args, agent="陈屿", platform="reddit", round_num=12)
    line = _only_line(activity, locale)

    assert line.agent == "陈屿"
    assert line.platform == "reddit"
    assert line.platform_name == "Reddit"
    assert line.round == 12
    assert line.timestamp == TS
    assert line.action == expected_action
    assert line.target == expected_target
    assert line.target_kind == ("person" if expected_target else "hub")
    assert line.is_signal is expected_signal
    assert line.language == locale
    assert line.text == activity.to_episode_text(locale)


def test_parser_handles_tricky_names_and_content():
    # Author names containing 的, quoted content containing 的帖子/colons/quotes, newlines.
    tricky = "王五的帖子：「转」\n第二行: still the same post"
    line = _only_line(_activity("LIKE_POST", {"post_author_name": "张三的帖子迷", "post_content": tricky}))
    assert (line.action, line.target) == ("LIKED_POST_OF", "张三的帖子迷")

    line = _only_line(_activity("LIKE_POST", {"post_author_name": "一条鱼"}))
    assert (line.action, line.target) == ("LIKED_POST_OF", "一条鱼")

    line = _only_line(_activity("LIKE_COMMENT", {"comment_author_name": "张三", "comment_content": "李四的帖子不错"}))
    assert (line.action, line.target) == ("LIKED_COMMENT_OF", "张三")

    line = _only_line(_activity("CREATE_COMMENT", {"post_content": "赵六的帖子「嵌套」", "content": "同意"}))
    assert (line.action, line.target) == ("COMMENTED", None)

    line = _only_line(_activity("CREATE_POST", {"content": "第一段\n\n第二段：「引用」"}, agent="Alice Chen"))
    assert line.agent == "Alice Chen"
    assert line.action == "POSTED"
    assert line.description.endswith("第二段：「引用」」")
    assert line.is_signal


def test_multi_line_post_content_stays_in_its_record():
    first = _activity("CREATE_POST", {"content": "line one\nline two\n[not a header] x"})
    second = _activity("FOLLOW", {"target_user_name": "周岚"}, agent="海岳能源", round_num=4)
    parsed = parse_activity_text(first.to_episode_text() + "\n" + second.to_episode_text())

    assert [line.action for line in parsed.lines] == ["POSTED", "FOLLOWS"]
    assert parsed.lines[0].text == first.to_episode_text()
    assert "line two" in parsed.lines[0].description
    assert parsed.lines[1].agent == "海岳能源"
    assert parsed.unparsed == ()


def test_updater_payload_parses_into_one_record_per_activity():
    activities = [
        _activity("CREATE_POST", {"content": POST}, agent="陈屿", round_num=1, ts="2026-07-01T09:00:00Z"),
        _activity("QUOTE_POST", {"original_author_name": "陈屿", "original_content": POST, "quote_content": QUOTE},
                  agent="周岚", round_num=1, ts="2026-07-01T09:05:00Z"),
        _activity("LIKE_POST", {"post_author_name": "陈屿", "post_content": POST},
                  agent="海岳能源", round_num=1, ts="2026-07-01T09:06:00Z"),
        _activity("CREATE_COMMENT", {"post_author_name": "陈屿", "post_content": POST, "content": COMMENT},
                  agent="海岳能源", round_num=2, ts="2026-07-01T09:10:00Z"),
        _activity("FOLLOW", {"target_user_name": "海岳能源"}, agent="陈屿", round_num=2, ts="2026-07-01T09:12:00Z"),
    ]
    payloads = ZepGraphMemoryUpdater._build_episode_payloads(_fake_updater("zh"), activities)
    assert len(payloads) == 1
    parsed = parse_activity_text(payloads[0][1])

    assert [(line.agent, line.action, line.target) for line in parsed.lines] == [
        ("陈屿", "POSTED", None),
        ("周岚", "QUOTED", "陈屿"),
        ("海岳能源", "LIKED_POST_OF", "陈屿"),
        ("海岳能源", "COMMENTED_ON_POST_OF", "陈屿"),
        ("陈屿", "FOLLOWS", "海岳能源"),
    ]
    assert [line.round for line in parsed.lines] == [1, 1, 1, 2, 2]
    assert [line.is_signal for line in parsed.lines] == [True, True, False, True, False]


def test_truncated_long_post_is_still_a_signal_line():
    activity = _activity("CREATE_POST", {"content": "长" * 12_000})
    [(_, text)] = ZepGraphMemoryUpdater._build_episode_payloads(_fake_updater("zh"), [activity])
    assert text.endswith("[truncated by MiroFish]")
    [line] = parse_activity_text(text).lines
    assert line.action == "POSTED"
    assert line.is_signal


def test_unparsed_and_empty_timestamp_lines():
    content = "\n".join([
        "free text before any header",
        _activity("LIKE_POST", ts="").to_episode_text(),
        _activity("CREATE_POST", ts="None").to_episode_text(),
    ])
    parsed = parse_activity_text(content)
    assert parsed.unparsed == ("free text before any header",)
    assert [line.timestamp for line in parsed.lines] == ["", "None"]
    assert parse_activity_text("").lines == ()


def test_classify_and_small_helpers():
    assert classify_activity_description("做了一件奇怪的事") == ("ACTED", None)
    assert classify_activity_description("执行了do_something操作") == ("PERFORMED_DO_SOMETHING", None)
    # A blank person name falls back to the platform hub.
    assert classify_activity_description("关注了用户「 」") == ("FOLLOWS", None)
    assert platform_display_name("twitter") == "Twitter"
    assert platform_display_name("REDDIT") == "Reddit"
    assert platform_display_name("weibo") == "Weibo"
    assert simulation_key(None) == "unknown"
    assert simulation_key("  ") == "unknown"
    assert simulation_key(" sim-1 ") == "sim-1"
    assert is_activity_metadata({"source": ACTIVITY_SOURCE})
    assert not is_activity_metadata({"source": "upload"})
    assert not is_activity_metadata(None)
    assert normalize_activity_mode(" LLM ") == "llm"
    with pytest.raises(ValueError):
        normalize_activity_mode("sometimes")


def test_signal_text_keeps_only_signal_records():
    post = _activity("CREATE_POST", {"content": POST})
    like = _activity("LIKE_POST", {"post_author_name": "周岚", "post_content": POST})
    content = like.to_episode_text() + "\n" + post.to_episode_text()
    assert signal_text(content) == post.to_episode_text()
    assert signal_text(like.to_episode_text()) == ""


# ---------------------------------------------------------------------------
# English templates: exact names, content that repeats templates, mixed lines
# ---------------------------------------------------------------------------

EN_POST = "The new Harbor City HQ opened today and Zhixun services are running normally."
EN_QUOTE = "As chief strategy adviser, I back Alice Chen and the new team."
EN_COMMENT = "The joint deployment deal ended, but we are still a Zhixun customer."

# Author names that trip a naive parser: apostrophes and "'s", the template
# words "post"/"comment"/"by"/"on", names that start like the "by" shapes,
# punctuation, curly quotes, non-Latin text. (A name holding a template
# delimiter followed by an opening quote, such as "Tom's post: “x", is the one
# documented shape the parser cannot read back.)
TRICKY_NAMES = [
    "O'Brien", "Kevin's Bakery", "Chris's post", "Bob's post office", "Ann's comment", "Stand by Me",
    "Hold on Tight", "Dr. J.-P. Smith", "Émilie Dubois", "陈屿", "张伟 (Wei) Zhang", "Li “Lucky” Wei",
    "Bob: “hi”", "Smith, adding", "a post", "a comment", "a", "by", "a post by Carl", "a comment by the lake",
    "a comment by Zed", "Dwayne “The Rock” Johnson",
]
# Content that repeats template phrases of both languages.
TRICKY_CONTENT = [
    "liked Bob's post: “so good”",
    "I agree with Alice's comment: “no”, adding: “yes”",
    "commented on Carol's post “x”: “y”",
    "quoted a post by Dave, adding: “z”",
    "followed the user “Eve”",
    "点赞了张三的帖子：「转」",
    "first line\nsecond line: liked Frank's comment: “w”",
]

# (action type, author key, content key, edge with an author, edge without one)
EN_TARGET_SHAPES = [
    ("LIKE_POST", "post_author_name", "post_content", "LIKED_POST_OF", "LIKED_POST"),
    ("DISLIKE_POST", "post_author_name", "post_content", "DISLIKED_POST_OF", "DISLIKED_POST"),
    ("REPOST", "original_author_name", "original_content", "REPOSTED", "REPOSTED"),
    ("QUOTE_POST", "original_author_name", "original_content", "QUOTED", "QUOTED"),
    ("LIKE_COMMENT", "comment_author_name", "comment_content", "LIKED_COMMENT_OF", "LIKED_COMMENT"),
    ("DISLIKE_COMMENT", "comment_author_name", "comment_content", "DISLIKED_COMMENT_OF", "DISLIKED_COMMENT"),
]


def _en(action_type: str, args: dict[str, Any] | None = None, **kwargs: Any):
    kwargs.setdefault("agent", "Alice Chen")
    return _only_line(_activity(action_type, args, **kwargs), "en")


@pytest.mark.parametrize("name", TRICKY_NAMES)
def test_english_parser_returns_the_exact_author_name(name):
    for action_type, author_key, content_key, with_author, _ in EN_TARGET_SHAPES:
        for content in ["", *TRICKY_CONTENT]:
            args = {author_key: name, **({content_key: content} if content else {})}
            line = _en(action_type, args)
            assert (line.action, line.target, line.language) == (with_author, name, "en"), (action_type, content)

    for args in (
        {"original_author_name": name, "original_content": EN_POST, "quote_content": EN_QUOTE},
        {"original_author_name": name, "quote_content": "I agree with Bob's post “x”, adding: “y”"},
    ):
        assert (_en("QUOTE_POST", args).action, _en("QUOTE_POST", args).target) == ("QUOTED", name)
    for args in (
        {"post_author_name": name, "post_content": EN_POST, "content": EN_COMMENT},
        {"post_author_name": name, "post_content": "Carol's post “x”", "content": "Dan's post: “y”"},
        {"post_author_name": name, "content": EN_COMMENT},
        {"post_author_name": name, "content": "on Carol's post “x”: “y”"},
    ):
        line = _en("CREATE_COMMENT", args)
        assert (line.action, line.target) == ("COMMENTED_ON_POST_OF", name)
    assert _en("FOLLOW", {"target_user_name": name}).target == name
    assert _en("MUTE", {"target_user_name": name}).target == name


@pytest.mark.parametrize("content", TRICKY_CONTENT)
def test_english_content_never_decides_the_rule(content):
    for action_type, _, content_key, _, without_author in EN_TARGET_SHAPES:
        line = _en(action_type, {content_key: content})
        assert (line.action, line.target) == (without_author, None), action_type
    assert (_en("QUOTE_POST", {"quote_content": content}).action,
            _en("QUOTE_POST", {"quote_content": content}).target) == ("QUOTED", None)
    line = _en("QUOTE_POST", {"original_author_name": "Bob", "quote_content": content})
    assert (line.action, line.target) == ("QUOTED", "Bob")
    for args, expected in (
        ({"post_content": content, "content": content}, ("COMMENTED", None)),
        ({"content": content}, ("COMMENTED", None)),
        ({"post_author_name": "Bob", "content": content}, ("COMMENTED_ON_POST_OF", "Bob")),
        ({"post_author_name": "Bob", "post_content": content, "content": content}, ("COMMENTED_ON_POST_OF", "Bob")),
    ):
        line = _en("CREATE_COMMENT", args)
        assert (line.action, line.target) == expected
    assert _en("CREATE_POST", {"content": content}).action == "POSTED"
    assert _en("SEARCH_POSTS", {"query": content}).action == "SEARCHED"
    assert _en("SEARCH_USER", {"query": content}).action == "SEARCHED_USER"


def test_english_signal_lines_follow_the_quoted_content():
    assert _en("CREATE_POST", {"content": EN_POST}).is_signal
    assert not _en("CREATE_POST", {"content": "   "}).is_signal  # nothing inside the quotes
    assert _en("REPOST", {"original_content": EN_POST}).is_signal
    assert not _en("REPOST", {"original_author_name": "Bob"}).is_signal
    assert _en("QUOTE_POST", {"quote_content": EN_QUOTE}).is_signal
    assert _en("CREATE_COMMENT", {"content": EN_COMMENT}).is_signal
    assert not _en("CREATE_COMMENT", {"post_author_name": "Bob", "post_content": EN_POST}).is_signal
    assert not _en("LIKE_POST", {"post_author_name": "Bob", "post_content": EN_POST}).is_signal
    # A Chinese-style quote inside English content is just content.
    assert not _en("REPOST", {"original_author_name": "「Bob」"}).is_signal
    # Curly quotes inside an author name are not quoted content.
    for name in ("Dwayne “The Rock” Johnson", "Bob: “hi”"):
        for action_type, author_key in (("REPOST", "original_author_name"), ("QUOTE_POST", "original_author_name")):
            line = _en(action_type, {author_key: name})
            assert (line.target, line.detail, line.is_signal) == (name, "", False), (action_type, name)
        line = _en("REPOST", {"original_author_name": name, "original_content": EN_POST})
        assert (line.target, line.detail, line.is_signal) == (name, f"“{EN_POST}”", True)
        line = _en("QUOTE_POST", {"original_author_name": name, "quote_content": EN_QUOTE})
        assert (line.target, line.detail, line.is_signal) == (name, f"“{EN_QUOTE}”", True)


def test_a_name_cut_by_a_line_break_falls_back_to_the_hub():
    # "by {author}" runs to the end of the line; a newline in the name would
    # otherwise leave only its first line ("Bob") as the target.
    for action_type, author_key, expected in (
        ("LIKE_POST", "post_author_name", "LIKED_POST_OF"),
        ("DISLIKE_COMMENT", "comment_author_name", "DISLIKED_COMMENT_OF"),
        ("REPOST", "original_author_name", "REPOSTED"),
        ("QUOTE_POST", "original_author_name", "QUOTED"),
    ):
        line = _en(action_type, {author_key: "Bob\nSmith"})
        assert (line.action, line.target, line.is_signal) == (expected, None, False), action_type
    line = _en("QUOTE_POST", {"original_author_name": "Bob\nSmith", "quote_content": "q"})
    assert (line.action, line.target, line.is_signal) == ("QUOTED", None, True)
    assert activity_fact(line) == "On Twitter, Alice Chen quoted a post by Bob Smith, adding: “q”"
    # A name that ends before the line does is complete, even with more lines after it.
    line = _en("QUOTE_POST", {"original_author_name": "Bob Smith", "quote_content": "one\ntwo"})
    assert (line.action, line.target) == ("QUOTED", "Bob Smith")
    line = _en("LIKE_POST", {"post_author_name": "Bob Smith", "post_content": "one\ntwo"})
    assert (line.action, line.target) == ("LIKED_POST_OF", "Bob Smith")


def test_lines_without_an_agent_name_are_their_own_records():
    for locale in ("en", "zh"):
        content = "\n".join([
            _activity("CREATE_POST", {"content": "first"}, agent="Alice Chen").to_episode_text(locale),
            _activity("CREATE_POST", {"content": "second"}, agent="").to_episode_text(locale),
            _activity("LIKE_POST", {"post_content": "x", "post_author_name": "Bob"}, agent="").to_episode_text(locale),
        ])
        parsed = parse_activity_text(content)
        assert parsed.unparsed == ()
        assert [(line.agent, line.action, line.target) for line in parsed.lines] == [
            ("Alice Chen", "POSTED", None), ("", "POSTED", None), ("", "LIKED_POST_OF", "Bob"),
        ], locale
        assert "second" not in parsed.lines[0].description
        # Nobody to attribute the words to, so nothing for the LLM either.
        assert [line.is_signal for line in parsed.lines] == [True, False, False]


def test_generic_and_unmatched_lines_pick_a_language():
    line = _en("JOIN_GROUP")
    assert (line.action, line.language) == ("PERFORMED_JOIN_GROUP", "en")
    assert activity_fact(line) == "On Twitter, Alice Chen performed JOIN_GROUP"
    line = _en("")
    assert (line.action, line.description, line.language) == ("ACTED", "performed an action", "en")
    assert (_en("JOIN-GROUP").action, _en("JOIN-GROUP").language) == ("ACTED", "en")
    line = _only_line(_activity("JOIN-GROUP"), "zh")
    assert (line.action, line.language) == ("ACTED", "zh")
    assert activity_fact(line) == "陈屿在Twitter执行了JOIN-GROUP操作"

    # Free text no rule knows: Chinese when it has CJK text, English otherwise.
    zh, en = parse_activity_text(
        f"[{TS}] [twitter round 1] 陈屿: 做了一件奇怪的事\n[{TS}] [twitter round 1] Alice Chen: waved at everyone"
    ).lines
    assert (zh.action, zh.language, activity_fact(zh)) == ("ACTED", "zh", "陈屿在Twitter做了一件奇怪的事")
    assert (en.action, en.language, activity_fact(en)) == ("ACTED", "en", "On Twitter, Alice Chen waved at everyone")

    # Only the template part decides: quoted content in another language never does.
    line = _only_line(_activity("CREATE_POST", {"content": "你好，世界"}, agent="Re: Zero"), "en")
    assert (line.agent, line.action, line.language) == ("Re", "ACTED", "en")
    assert activity_fact(line) == "On Twitter, Re Zero: posted: “你好，世界”"
    line = _only_line(_activity("CREATE_POST", {"content": "hello"}, agent="Re: Zero"), "zh")
    assert (line.agent, line.action, line.language) == ("Re", "ACTED", "zh")
    assert activity_fact(line) == "Re在TwitterZero: 发布了一条帖子：「hello」"
    line = _en("发帖")
    assert (line.action, line.language, activity_fact(line)) == ("ACTED", "en", "On Twitter, Alice Chen performed 发帖")

    assert classify_activity_description("performed do_something") == ("PERFORMED_DO_SOMETHING", None)
    # Blank person names fall back to the platform hub, as in Chinese.
    assert classify_activity_description("followed the user “ ”") == ("FOLLOWS", None)
    assert classify_activity_description("liked a post by") == ("LIKED_POST_OF", None)
    assert classify_activity_description("quoted a post by  , adding: “x”") == ("QUOTED", None)


def test_english_facts_are_whitespace_collapsed_and_capped():
    line = _en("CREATE_POST", {"content": "word  " * 400 + "\nlast"}, platform="reddit")
    fact = activity_fact(line)
    assert fact.startswith("On Reddit, Alice Chen posted: “word word ")
    assert len(fact) == MAX_FACT_CHARS
    assert "\n" not in fact and "  " not in fact
    short = _en("FOLLOW", {"target_user_name": "Li “Lucky” Wei"})
    assert activity_fact(short) == "On Twitter, Alice Chen followed the user “Li “Lucky” Wei”"


def test_english_updater_payload_parses_into_one_record_per_activity():
    activities = [
        _activity("CREATE_POST", {"content": EN_POST}, agent="Alice Chen", round_num=1),
        _activity("QUOTE_POST", {"original_author_name": "Alice Chen", "original_content": EN_POST,
                                 "quote_content": EN_QUOTE}, agent="Bruno O'Neil", round_num=1),
        _activity("LIKE_POST", {"post_author_name": "Alice Chen", "post_content": EN_POST},
                  agent="Chandra", round_num=1),
        _activity("CREATE_COMMENT", {"post_author_name": "Bruno O'Neil", "post_content": EN_QUOTE,
                                     "content": EN_COMMENT}, agent="Chandra", round_num=2),
        _activity("FOLLOW", {"target_user_name": "Chandra"}, agent="Alice Chen", round_num=2),
    ]
    [(_, text)] = ZepGraphMemoryUpdater._build_episode_payloads(_fake_updater("en"), activities)
    parsed = parse_activity_text(text)

    assert [(line.agent, line.action, line.target) for line in parsed.lines] == [
        ("Alice Chen", "POSTED", None),
        ("Bruno O'Neil", "QUOTED", "Alice Chen"),
        ("Chandra", "LIKED_POST_OF", "Alice Chen"),
        ("Chandra", "COMMENTED_ON_POST_OF", "Bruno O'Neil"),
        ("Alice Chen", "FOLLOWS", "Chandra"),
    ]
    assert {line.language for line in parsed.lines} == {"en"}
    assert [line.is_signal for line in parsed.lines] == [True, True, False, True, False]

    [(_, long_text)] = ZepGraphMemoryUpdater._build_episode_payloads(
        _fake_updater("en"), [_activity("CREATE_POST", {"content": "long " * 3_000}, agent="Alice Chen")])
    assert long_text.endswith("[truncated by MiroFish]")
    [line] = parse_activity_text(long_text).lines
    assert (line.action, line.language, line.is_signal) == ("POSTED", "en", True)


def test_mixed_language_lines_are_classified_one_by_one():
    content = "\n".join([
        _activity("CREATE_POST", {"content": POST}).to_episode_text("zh"),
        _activity("LIKE_POST", {"post_author_name": "陈屿", "post_content": POST}, agent="Alice Chen")
        .to_episode_text("en"),
        _activity("LIKE_POST", {"post_author_name": "Alice Chen", "post_content": EN_POST}).to_episode_text("zh"),
        _activity("CREATE_POST", {"content": EN_POST}, agent="Alice Chen").to_episode_text("en"),
    ])
    parsed = parse_activity_text(content)
    assert [(line.action, line.target, line.language) for line in parsed.lines] == [
        ("POSTED", None, "zh"),
        ("LIKED_POST_OF", "陈屿", "en"),
        ("LIKED_POST_OF", "Alice Chen", "zh"),
        ("POSTED", None, "en"),
    ]
    assert signal_text(parsed) == "\n".join([parsed.lines[0].text, parsed.lines[3].text])


# ---------------------------------------------------------------------------
# Timestamp helpers (textnorm additions)
# ---------------------------------------------------------------------------


def test_line_timestamps_follow_the_updater_semantics():
    assert parse_local_iso_datetime("2026-07-01T09:00:00Z") == TS_UTC
    assert parse_local_iso_datetime("2026-07-01T17:00:00+08:00") == TS_UTC
    naive = "2026-07-01T09:00:00.123456"
    assert parse_local_iso_datetime(naive) == parse_iso_datetime(ZepGraphMemoryUpdater._to_rfc3339(naive))
    assert parse_local_iso_datetime("not a time") is None
    assert parse_local_iso_datetime("") is None
    assert parse_local_iso_datetime(None) is None
    assert iso_to_epoch(epoch_to_iso(T0)) == T0
    assert epoch_to_iso(0) == "1970-01-01T00:00:00.000000Z"
    assert iso_to_epoch("garbage") is None


# ---------------------------------------------------------------------------
# Rules extractor: database writes
# ---------------------------------------------------------------------------

REFERENCE = "2026-07-01T10:00:00.000000Z"


def _insert_episode(store, graph_id: str, content: str, *, kind: str = "activity",
                    reference_time: str = REFERENCE, simulation_id: str | None = "sim-1",
                    created_at: str | None = None, queued_at: str | None = None,
                    status: str = "pending") -> str:
    episode_uuid = new_id()
    metadata = {"source": ACTIVITY_SOURCE, "simulation_id": simulation_id} if kind == "activity" else {}
    with store.write() as conn:
        conn.execute(
            "INSERT INTO episodes(uuid, graph_id, kind, content, source, source_description, metadata_json, "
            "simulation_id, reference_time, reference_time_explicit, created_at, queued_at, extraction_status) "
            "VALUES (?, ?, ?, ?, 'text', 'MiroFish simulation activity batch', ?, ?, ?, 1, ?, ?, ?)",
            (episode_uuid, graph_id, kind, content, json.dumps(metadata), simulation_id, reference_time,
             created_at or utcnow_iso(), queued_at, status),
        )
    return episode_uuid


def _add(store, graph_id: str, activities: list[AgentActivity], *, mode: str = "rules",
         now: str | None = None, simulation_id: str | None = "sim-1", created_at: str | None = None,
         locale: str | None = None):
    content = "\n".join(activity.to_episode_text(locale) for activity in activities)
    reference = parse_iso_datetime(ZepGraphMemoryUpdater._to_rfc3339(activities[-1].timestamp))
    episode_uuid = _insert_episode(store, graph_id, content, reference_time=reference,
                                   simulation_id=simulation_id, created_at=created_at)
    with store.write() as conn:
        result = ingest_activity_episode(conn, episode_uuid, mode=mode, now=now)
    return episode_uuid, result


def _episode_row(store, episode_uuid: str):
    with store.read() as conn:
        return conn.execute("SELECT * FROM episodes WHERE uuid = ?", (episode_uuid,)).fetchone()


def _nodes(store, graph_id: str = "g1") -> dict[str, Any]:
    with store.read() as conn:
        rows = conn.execute("SELECT * FROM nodes WHERE graph_id = ? ORDER BY id", (graph_id,)).fetchall()
    return {row["name"]: row for row in rows}


def _edges(store, graph_id: str = "g1") -> list[dict[str, Any]]:
    with store.read() as conn:
        rows = conn.execute(
            "SELECT e.*, s.name AS source_name, t.name AS target_name FROM edges e "
            "JOIN nodes s ON s.uuid = e.source_node_uuid JOIN nodes t ON t.uuid = e.target_node_uuid "
            "WHERE e.graph_id = ? ORDER BY e.id",
            (graph_id,),
        ).fetchall()
        result = []
        for row in rows:
            episodes = [r[0] for r in conn.execute(
                "SELECT episode_uuid FROM edge_episodes WHERE edge_uuid = ? ORDER BY linked_at, rowid",
                (row["uuid"],),
            )]
            result.append({**dict(row), "episodes": episodes})
    return result


def _version(store, graph_id: str = "g1") -> int:
    with store.read() as conn:
        return conn.execute("SELECT version FROM graphs WHERE graph_id = ?", (graph_id,)).fetchone()[0]


def _node_episode_links(store, node_uuid: str) -> list[str]:
    with store.read() as conn:
        return [r[0] for r in conn.execute("SELECT episode_uuid FROM node_episodes WHERE node_uuid = ?", (node_uuid,))]


def test_rules_create_generic_account_hub_and_event_edge(local, seed):
    seed.graph("g1")
    episode_uuid, result = _add(local.store, "g1", [_activity("CREATE_POST", {"content": POST}, round_num=3)])

    assert result.extraction_status == "succeeded"
    assert (result.rules.lines, result.rules.nodes_created, result.rules.edges_created) == (1, 2, 1)
    nodes = _nodes(local.store)
    account, hub = nodes["陈屿"], nodes["Twitter"]
    for node in (account, hub):
        assert json.loads(node["labels_json"]) == ["Entity"]
        assert node["entity_type"] is None
        assert node["origin"] == "rules"
        assert _node_episode_links(local.store, node["uuid"]) == [episode_uuid]
    assert account["summary"] == "陈屿是Twitter上的模拟账号。"
    assert "Twitter" in hub["summary"]

    [edge] = _edges(local.store)
    assert edge["name"] == "POSTED"
    assert (edge["source_name"], edge["target_name"]) == ("陈屿", "Twitter")
    assert edge["fact"] == f"陈屿在Twitter发布了一条帖子：「{POST}」"
    assert edge["origin"] == "rules"
    assert edge["valid_at"] == TS_UTC
    assert edge["invalid_at"] is None and edge["expired_at"] is None
    assert json.loads(edge["attributes_json"]) == {
        "platform": "twitter", "round": "3", "simulation_id": "sim-1", "action": "POSTED",
    }
    assert edge["episodes"] == [episode_uuid]
    assert _version(local.store) == 1

    sdk_edge = edge_from_row(edge, edge["episodes"])
    assert sdk_edge.name == "POSTED"
    assert sdk_edge.episodes == [episode_uuid]


def test_rules_for_english_lines_write_english_facts_and_summaries(local, seed):
    seed.graph("g1")
    episode_uuid, result = _add(local.store, "g1", [
        _activity("CREATE_POST", {"content": EN_POST}, agent="Alice Chen", round_num=3),
        _activity("LIKE_COMMENT", {"comment_author_name": "Kevin's Bakery", "comment_content": EN_COMMENT},
                  agent="Alice Chen", round_num=3),
    ], locale="en")

    assert result.extraction_status == "succeeded"
    assert (result.rules.lines, result.rules.nodes_created, result.rules.edges_created) == (2, 3, 2)
    summaries = {name: node["summary"] for name, node in _nodes(local.store).items()}
    assert summaries == {
        "Alice Chen": "Alice Chen is a simulated account on Twitter.",
        "Twitter": "Twitter is the social media platform used in the simulation.",
        "Kevin's Bakery": "Kevin's Bakery is a simulated account on Twitter.",
    }
    posted, liked = _edges(local.store)
    assert (posted["name"], posted["source_name"], posted["target_name"]) == ("POSTED", "Alice Chen", "Twitter")
    assert posted["fact"] == f"On Twitter, Alice Chen posted: “{EN_POST}”"
    assert posted["valid_at"] == TS_UTC
    assert json.loads(posted["attributes_json"]) == {
        "platform": "twitter", "round": "3", "simulation_id": "sim-1", "action": "POSTED",
    }
    assert (liked["name"], liked["target_name"]) == ("LIKED_COMMENT_OF", "Kevin's Bakery")
    assert liked["fact"] == f"On Twitter, Alice Chen liked Kevin's Bakery's comment: “{EN_COMMENT}”"
    assert posted["episodes"] == liked["episodes"] == [episode_uuid]


def test_a_mixed_language_episode_writes_each_line_in_its_own_language(local, seed):
    seed.graph("g1")
    lines = [
        (_activity("CREATE_POST", {"content": EN_POST}, agent="Alice Chen", round_num=1), "en"),
        (_activity("CREATE_POST", {"content": POST}, agent="陈屿", round_num=1), "zh"),
        (_activity("FOLLOW", {"target_user_name": "陈屿"}, agent="Alice Chen", round_num=2), "en"),
        (_activity("LIKE_POST", {"post_author_name": "Bob Stone", "post_content": EN_POST}, agent="陈屿",
                   round_num=2), "zh"),
        (_activity("CREATE_POST", {"content": POST}, agent="周岚", platform="reddit", round_num=2), "zh"),
        (_activity("LIKE_COMMENT", {"comment_author_name": "Dr. J.-P. O'Brien", "comment_content": EN_COMMENT},
                   agent="周岚", platform="reddit", round_num=3), "en"),
    ]
    content = "\n".join(activity.to_episode_text(locale) for activity, locale in lines)
    episode_uuid = _insert_episode(local.store, "g1", content)
    with local.store.write() as conn:
        result = ingest_activity_episode(conn, episode_uuid, mode="rules")

    assert (result.extraction_status, result.rules.lines, result.rules.edges_created) == ("succeeded", 6, 6)
    assert [(e["name"], e["source_name"], e["target_name"], e["fact"]) for e in _edges(local.store)] == [
        ("POSTED", "Alice Chen", "Twitter", f"On Twitter, Alice Chen posted: “{EN_POST}”"),
        ("POSTED", "陈屿", "Twitter", f"陈屿在Twitter发布了一条帖子：「{POST}」"),
        ("FOLLOWS", "Alice Chen", "陈屿", "On Twitter, Alice Chen followed the user “陈屿”"),
        ("LIKED_POST_OF", "陈屿", "Bob Stone", f"陈屿在Twitter点赞了Bob Stone的帖子：「{EN_POST}」"),
        ("POSTED", "周岚", "Reddit", f"周岚在Reddit发布了一条帖子：「{POST}」"),
        ("LIKED_COMMENT_OF", "周岚", "Dr. J.-P. O'Brien",
         f"On Reddit, 周岚 liked Dr. J.-P. O'Brien's comment: “{EN_COMMENT}”"),
    ]
    # A node's summary is in the language of the line that created it.
    summaries = {name: node["summary"] for name, node in _nodes(local.store).items()}
    assert summaries == {
        "Alice Chen": "Alice Chen is a simulated account on Twitter.",
        "Twitter": "Twitter is the social media platform used in the simulation.",
        "陈屿": "陈屿是Twitter上的模拟账号。",
        "Bob Stone": "Bob Stone是Twitter上的模拟账号。",
        "周岚": "周岚是Reddit上的模拟账号。",
        "Reddit": "Reddit是模拟中使用的社交媒体平台。",
        "Dr. J.-P. O'Brien": "Dr. J.-P. O'Brien is a simulated account on Reddit.",
    }


def test_the_same_action_in_both_languages_shares_edge_names_and_nodes(local, seed):
    seed.graph("g1")
    follow = _activity("FOLLOW", {"target_user_name": "周岚"}, agent="Alice Chen")
    _add(local.store, "g1", [follow], locale="zh")
    _add(local.store, "g1", [follow], locale="en")
    edges = _edges(local.store)
    # Different fact text, so two edges, but between the same two nodes.
    assert [(e["name"], e["source_name"], e["target_name"]) for e in edges] == [
        ("FOLLOWS", "Alice Chen", "周岚"), ("FOLLOWS", "Alice Chen", "周岚"),
    ]
    assert [e["fact"] for e in edges] == ["Alice Chen在Twitter关注了用户「周岚」",
                                         "On Twitter, Alice Chen followed the user “周岚”"]
    assert set(_nodes(local.store)) == {"Alice Chen", "周岚"}


def test_rules_edges_are_searchable_through_fts(local, seed):
    if not local.store.caps.fts5:
        pytest.skip("FTS5 not available")
    seed.graph("g1")
    _add(local.store, "g1", [_activity("CREATE_POST", {"content": "智巡平台今天上线"})])
    query = '"智巡平台"' if local.store.caps.trigram else '"twitter"'
    with local.store.read() as conn:
        hits = conn.execute("SELECT rowid FROM edges_fts WHERE edges_fts MATCH ?", (query,)).fetchall()
    assert len(hits) == 1


def test_agent_and_target_resolve_to_existing_typed_nodes(local, seed):
    seed.graph("g1")
    chen = seed.node("g1", "陈屿", "Person", summary="陈屿是智巡平台的CEO。")
    zhou = seed.node("g1", "周岚", "Person")
    alice = seed.node("g1", "Alice Chen", "Person")
    with local.store.write() as conn:
        conn.execute("UPDATE nodes SET mention_count = 4 WHERE uuid = ?", (chen,))

    _, result = _add(local.store, "g1", [
        _activity("LIKE_POST", {"post_author_name": "陈屿", "post_content": POST}, agent="周岚"),
        _activity("FOLLOW", {"target_user_name": "陈屿"}, agent="Dr. Alice Chen"),
    ])

    assert result.rules.nodes_created == 0
    edges = _edges(local.store)
    assert [(e["name"], e["source_node_uuid"], e["target_node_uuid"]) for e in edges] == [
        ("LIKED_POST_OF", zhou, chen),
        ("FOLLOWS", alice, chen),
    ]
    node = _nodes(local.store)["陈屿"]
    assert json.loads(node["labels_json"]) == ["Entity", "Person"]
    assert node["summary"] == "陈屿是智巡平台的CEO。"
    assert node["mention_count"] == 4  # rules never inflate mention counts


def test_resolution_prefers_the_most_mentioned_candidate(local, seed):
    seed.graph("g1")
    seed.node("g1", "李明", "Person")
    popular = seed.node("g1", "李明", "Organization")
    with local.store.write() as conn:
        conn.execute("UPDATE nodes SET mention_count = 7 WHERE uuid = ?", (popular,))
    _add(local.store, "g1", [_activity("CREATE_POST", {"content": POST}, agent="李明")])
    [edge] = _edges(local.store)
    assert edge["source_node_uuid"] == popular


def test_platform_hub_reuses_an_existing_node_and_is_created_once(local, seed):
    seed.graph("g1")
    twitter = seed.node("g1", "Twitter", "Organization")
    _add(local.store, "g1", [_activity("CREATE_POST", {"content": POST})])
    assert _edges(local.store)[0]["target_node_uuid"] == twitter

    for round_num in (1, 2):
        _add(local.store, "g1", [_activity("CREATE_POST", {"content": f"{POST}{round_num}"}, platform="reddit",
                                           round_num=round_num, agent=f"用户{round_num}")])
    reddit_nodes = [node for node in _nodes(local.store).values() if node["name"] == "Reddit"]
    assert len(reddit_nodes) == 1


def test_repeated_identical_actions_link_episodes_instead_of_new_edges(local, seed):
    seed.graph("g1")
    first, result_1 = _add(local.store, "g1", [_activity("LIKE_POST", round_num=1, ts="2026-07-01T09:00:00Z")])
    second, result_2 = _add(local.store, "g1", [
        _activity("LIKE_POST", round_num=2, ts="2026-07-01T09:30:00Z"),
        _activity("LIKE_POST", round_num=2, ts="2026-07-01T09:31:00Z"),
    ])

    assert result_1.rules.edges_created == 1
    assert (result_2.rules.edges_created, result_2.rules.edges_merged) == (0, 2)
    [edge] = _edges(local.store)
    assert edge["name"] == "LIKED_POST"
    assert edge["episodes"] == [first, second]
    assert edge["valid_at"] == TS_UTC  # the first occurrence
    assert json.loads(edge["attributes_json"])["round"] == "2"  # newer values win


def test_near_duplicate_facts_merge_but_distinct_posts_do_not(local, seed):
    seed.graph("g1")
    base = "智巡平台今天在海城市正式上线，首批覆盖二十个社区，市民反响热烈，运营团队表示会持续优化服务体验"
    _add(local.store, "g1", [_activity("CREATE_POST", {"content": base + "。"})])
    _add(local.store, "g1", [_activity("CREATE_POST", {"content": base + "！"})])
    assert len(_edges(local.store)) == 1
    _add(local.store, "g1", [_activity("CREATE_POST", {"content": "完全不同的另一条帖子内容。"})])
    assert len(_edges(local.store)) == 2

    base = "Zhixun launched in Harbor City today, covering twenty {} at first, and residents love it"
    _add(local.store, "g1", [_activity("CREATE_POST", {"content": base.format("neighbourhoods")},
                                       agent="Alice Chen")], locale="en")
    _, result = _add(local.store, "g1", [_activity("CREATE_POST", {"content": base.format("neighborhoods")},
                                                   agent="Alice Chen")], locale="en")
    assert (result.rules.edges_created, result.rules.edges_merged) == (0, 1)
    assert len(_edges(local.store)) == 3


@pytest.mark.parametrize("locale", ["zh", "en"])
def test_distinct_short_actions_are_not_merged_as_near_duplicates(local, seed, locale):
    # The fixed template words ("On Twitter, Alice Chen searched for the user")
    # must not make two different short queries, quotes or comments look alike.
    seed.graph("g1")
    pairs = [
        ("SEARCH_POSTS", {"query": "no"}, {"query": "yes"}),
        ("SEARCH_USER", {"query": "NASA"}, {"query": "WHO"}),
        ("QUOTE_POST", {"original_author_name": "Bob", "quote_content": "true"},
         {"original_author_name": "Bob", "quote_content": "false"}),
        ("CREATE_COMMENT", {"content": "ok"}, {"content": "no"}),
        ("CREATE_COMMENT", {"post_author_name": "Bob", "content": "fine"}, {"post_author_name": "Bob", "content": "nope"}),
        ("LIKE_POST", {"post_author_name": "Bob", "post_content": "hi"}, {"post_author_name": "Bob", "post_content": "yo"}),
        ("CREATE_POST", {"content": "a"}, {"content": "b"}),
    ]
    for action_type, first, second in pairs:
        _add(local.store, "g1", [_activity(action_type, first, agent="Alice Chen")], locale=locale)
        _, result = _add(local.store, "g1", [_activity(action_type, second, agent="Alice Chen")], locale=locale)
        assert (result.rules.edges_created, result.rules.edges_merged) == (1, 0), (action_type, second)
    assert len(_edges(local.store)) == 2 * len(pairs)
    # An identical action still merges.
    _, result = _add(local.store, "g1", [_activity("SEARCH_POSTS", {"query": "no"}, agent="Alice Chen")], locale=locale)
    assert (result.rules.edges_created, result.rules.edges_merged) == (0, 1)


def test_lines_without_an_agent_name_write_nothing(local, seed):
    seed.graph("g1")
    for locale in ("en", "zh"):
        _, result = _add(local.store, "g1", [
            _activity("CREATE_POST", {"content": "first"}, agent="Alice Chen"),
            _activity("CREATE_POST", {"content": "second"}, agent=""),
            _activity("LIKE_POST", {"post_content": "x", "post_author_name": "Bob"}, agent=""),
            _activity("FOLLOW", {"target_user_name": "Carol"}, agent="  "),
        ], locale=locale)
        assert (result.rules.lines, result.rules.skipped_lines) == (4, 3), locale
    assert set(_nodes(local.store)) == {"Alice Chen", "Twitter"}
    assert [e["fact"] for e in _edges(local.store)] == [
        "On Twitter, Alice Chen posted: “first”", "Alice Chen在Twitter发布了一条帖子：「first」",
    ]


def test_near_duplicate_search_matches_trigram_jaccard():
    import random

    from app.memory.textnorm import trigram_jaccard

    rng = random.Random(7)
    alphabet = "智巡平台海城市新总部今天启用服务正常运行ab"
    for _ in range(300):
        new_key = "".join(rng.choice(alphabet) for _ in range(rng.randint(1, 40)))
        keys = [
            "".join(rng.choice(alphabet) for _ in range(rng.randint(1, 40))) for _ in range(5)
        ] + [new_key[: max(1, len(new_key) - rng.randint(0, 3))] + "平台"]
        candidates = [({"fact_key": key}, key) for key in keys]
        scores = [trigram_jaccard(new_key, key) for key in keys]
        best = max(scores)
        found = activity_module._near_duplicate(new_key, candidates)
        if best >= activity_module.EDGE_DEDUP_JACCARD:
            assert found is not None and trigram_jaccard(new_key, found["fact_key"]) == best
        else:
            assert found is None


def test_exact_duplicates_are_found_beyond_the_near_duplicate_window(local, seed, monkeypatch):
    monkeypatch.setattr(activity_module, "NEAR_DUPLICATE_SCAN_LIMIT", 1)
    seed.graph("g1")
    first = "智巡平台今天在海城市正式上线，首批覆盖二十个社区，市民反响热烈"
    _add(local.store, "g1", [_activity("CREATE_POST", {"content": first})])
    _add(local.store, "g1", [_activity("CREATE_POST", {"content": "完全不同的另一条帖子内容。"})])
    _add(local.store, "g1", [_activity("CREATE_POST", {"content": first})])  # exact: always merged
    assert len(_edges(local.store)) == 2
    # A near duplicate of an edge outside the (1-edge) window becomes a new edge...
    _add(local.store, "g1", [_activity("CREATE_POST", {"content": first + "啊"})])
    assert len(_edges(local.store)) == 3
    # ...and inside the default window it is merged.
    monkeypatch.setattr(activity_module, "NEAR_DUPLICATE_SCAN_LIMIT", 200)
    _add(local.store, "g1", [_activity("CREATE_POST", {"content": first + "呀"})])
    assert len(_edges(local.store)) == 3


def test_reverse_actions_stay_separate_edges(local, seed):
    seed.graph("g1")
    _add(local.store, "g1", [
        _activity("FOLLOW", {"target_user_name": "周岚"}, agent="陈屿"),
        _activity("FOLLOW", {"target_user_name": "陈屿"}, agent="周岚"),
    ])
    edges = _edges(local.store)
    assert [(e["source_name"], e["target_name"]) for e in edges] == [("陈屿", "周岚"), ("周岚", "陈屿")]


def test_self_loops_are_dropped(local, seed):
    seed.graph("g1")
    _, result = _add(local.store, "g1", [
        _activity("CREATE_POST", {"content": POST}, agent="Twitter"),
        _activity("FOLLOW", {"target_user_name": "陈屿"}, agent="陈屿"),
    ])
    assert result.rules.self_loops == 2
    assert _edges(local.store) == []
    assert result.extraction_status == "succeeded"


def test_timestamps_fall_back_to_the_episode_reference_time(local, seed):
    seed.graph("g1")
    content = "\n".join([
        "a line that is not an activity record",
        _activity("LIKE_POST", ts="").to_episode_text(),
        _activity("FOLLOW", {"target_user_name": "周岚"}, ts="not-a-time").to_episode_text(),
        _activity("MUTE", {"target_user_name": "海岳能源"}, ts="2026-07-01T17:00:00+08:00").to_episode_text(),
    ])
    episode_uuid = _insert_episode(local.store, "g1", content, reference_time=REFERENCE)
    with local.store.write() as conn:
        result = ingest_activity_episode(conn, episode_uuid, mode="rules")
    assert (result.rules.lines, result.rules.unparsed) == (3, 1)
    assert [(e["name"], e["valid_at"]) for e in _edges(local.store)] == [
        ("LIKED_POST", REFERENCE),
        ("FOLLOWS", REFERENCE),
        ("MUTED", TS_UTC),
    ]


def test_simulation_id_falls_back_to_metadata_then_unknown(local, seed):
    seed.graph("g1")
    content = _activity("LIKE_POST").to_episode_text()
    from_metadata = _insert_episode(local.store, "g1", content, simulation_id=None)
    with local.store.write() as conn:
        conn.execute("UPDATE episodes SET metadata_json = ? WHERE uuid = ?",
                     (json.dumps({"source": ACTIVITY_SOURCE, "simulation_id": "sim-meta"}), from_metadata))
        ingest_activity_episode(conn, from_metadata, mode="rules")
    _add(local.store, "g1", [_activity("FOLLOW", {"target_user_name": "周岚"})], simulation_id=None)
    sims = [json.loads(e["attributes_json"])["simulation_id"] for e in _edges(local.store)]
    assert sims == ["sim-meta", "unknown"]


# ---------------------------------------------------------------------------
# Modes (§5.1)
# ---------------------------------------------------------------------------


def test_rules_mode_finishes_the_episode_synchronously(local, seed):
    seed.graph("g1")
    episode_uuid, result = _add(local.store, "g1", [_activity("CREATE_POST", {"content": POST})], mode="rules")
    row = _episode_row(local.store, episode_uuid)
    assert (result.processed, result.queued) == (True, False)
    assert (row["processed"], row["extraction_status"], row["queued_at"]) == (1, "succeeded", None)
    assert row["extraction_error"] is None
    episode = episode_from_row(row)
    assert episode.processed is True
    assert episode.extraction_status == "succeeded"


def test_off_mode_stores_the_episode_only(local, seed):
    seed.graph("g1")
    episode_uuid, result = _add(local.store, "g1", [_activity("CREATE_POST", {"content": POST})], mode="off")
    row = _episode_row(local.store, episode_uuid)
    assert (result.extraction_status, result.processed, result.rules) == ("skipped", True, None)
    assert (row["processed"], row["extraction_status"]) == (1, "skipped")
    assert _nodes(local.store) == {} and _edges(local.store) == []
    assert _version(local.store) == 0


def test_llm_mode_applies_rules_and_queues_signal_episodes(local, seed):
    seed.graph("g1")
    now = epoch_to_iso(T0)
    episode_uuid, result = _add(local.store, "g1", [
        _activity("CREATE_POST", {"content": POST}),
        _activity("LIKE_POST", {"post_author_name": "周岚"}),
    ], mode="llm", now=now)
    row = _episode_row(local.store, episode_uuid)
    assert (result.extraction_status, result.processed, result.queued) == ("queued", False, True)
    assert result.rules.signal_lines == 1
    assert (row["processed"], row["extraction_status"], row["queued_at"]) == (0, "queued", now)
    assert episode_from_row(row).processed is False
    assert {e["name"] for e in _edges(local.store)} == {"POSTED", "LIKED_POST_OF"}


def test_llm_mode_without_signal_lines_finishes_immediately(local, seed):
    seed.graph("g1")
    episode_uuid, result = _add(local.store, "g1", [
        _activity("LIKE_POST", {"post_author_name": "周岚", "post_content": POST}),
        _activity("FOLLOW", {"target_user_name": "周岚"}),
    ], mode="llm")
    row = _episode_row(local.store, episode_uuid)
    assert (result.extraction_status, result.processed, result.queued) == ("succeeded", True, False)
    assert (row["processed"], row["queued_at"]) == (1, None)


@pytest.mark.parametrize("mode,expected_status,expected_processed", [
    ("rules", "degraded", 1),
    ("llm", "queued", 0),
])
def test_a_rules_failure_is_contained(local, seed, monkeypatch, mode, expected_status, expected_processed):
    seed.graph("g1")

    def boom(*_args, **_kwargs):
        raise RuntimeError("synthetic failure with source text 「secret」")

    monkeypatch.setattr(activity_module, "_write_event_edge", boom)
    episode_uuid, result = _add(local.store, "g1", [_activity("CREATE_POST", {"content": POST})], mode=mode)

    row = _episode_row(local.store, episode_uuid)
    assert result.rules.error == "RuntimeError"
    assert (row["extraction_status"], row["processed"]) == (expected_status, expected_processed)
    if mode == "rules":
        error = json.loads(row["extraction_error"])
        assert error["code"] == "rules_error"
        assert "secret" not in error["message"]
    # The SAVEPOINT undid the nodes written before the failure.
    assert _nodes(local.store) == {}
    assert _version(local.store) == 0


def test_a_busy_store_during_rules_still_raises(local, seed, monkeypatch):
    seed.graph("g1")

    def locked(*_args, **_kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(activity_module, "_write_event_edge", locked)
    with pytest.raises(ZepApiError) as excinfo:
        _add(local.store, "g1", [_activity("CREATE_POST", {"content": POST})])
    assert excinfo.value.status_code == 503


def test_ingest_rejects_unknown_modes_and_missing_episodes(local, seed):
    seed.graph("g1")
    episode_uuid = _insert_episode(local.store, "g1", _activity("LIKE_POST").to_episode_text())
    with local.store.write() as conn:
        with pytest.raises(ValueError):
            ingest_activity_episode(conn, episode_uuid, mode="maybe")
    with pytest.raises(NotFoundError):
        with local.store.write() as conn:
            ingest_activity_episode(conn, "missing", mode="rules")


def test_ingest_is_idempotent_for_the_same_episode(local, seed):
    seed.graph("g1")
    episode_uuid, _ = _add(local.store, "g1", [_activity("CREATE_POST", {"content": POST})])
    with local.store.write() as conn:
        again = ingest_activity_episode(conn, episode_uuid, mode="rules")
    assert (again.rules.nodes_created, again.rules.edges_created, again.rules.edges_merged) == (0, 0, 1)
    [edge] = _edges(local.store)
    assert edge["episodes"] == [episode_uuid]


# ---------------------------------------------------------------------------
# Enrichment planning (§5.3): grouping
# ---------------------------------------------------------------------------


def _cand(uuid: str, *, graph: str = "g1", sim: str = "s1", offset: int = 0, queued_at: float | None = T0,
          chars: int = 100) -> ActivityCandidate:
    return ActivityCandidate(
        uuid=uuid, graph_id=graph, simulation_key=sim, created_at=epoch_to_iso(T0 + offset),
        queued_at=queued_at, chars=chars, row_id=offset,
    )


POLICY = ActivityPolicy(group_size=4, group_chars=12_000, group_wait_seconds=15.0,
                        max_pending_seconds=300.0, max_llm_calls=60)


def test_groups_close_by_size_and_the_tail_waits():
    candidates = [_cand(f"e{i}", offset=i) for i in range(10)]
    groups = plan_activity_groups(candidates, POLICY, now=T0 + 1)
    assert [(g.uuids, g.reason) for g in groups] == [
        (("e0", "e1", "e2", "e3"), "size"),
        (("e4", "e5", "e6", "e7"), "size"),
    ]
    forced = plan_activity_groups(candidates, POLICY, now=T0 + 1, force=True)
    assert [(len(g.episodes), g.reason) for g in forced] == [(4, "size"), (4, "size"), (2, "force")]


def test_groups_close_by_characters_and_an_oversized_episode_goes_alone():
    candidates = [_cand("a", offset=0, chars=5_000), _cand("b", offset=1, chars=5_000),
                  _cand("c", offset=2, chars=20_000), _cand("d", offset=3, chars=5_000)]
    groups = plan_activity_groups(candidates, POLICY, now=T0 + 1)
    assert [(g.uuids, g.reason, g.chars) for g in groups] == [
        (("a", "b"), "chars", 10_000),
        (("c",), "chars", 20_000),
    ]
    # "d" waits for more company until the group wait elapses.
    groups = plan_activity_groups(candidates, POLICY, now=T0 + 15)
    assert groups[-1].uuids == ("d",) and groups[-1].reason == "wait"


def test_a_partial_group_is_dispatched_once_its_oldest_episode_waited():
    candidates = [_cand("old", offset=0, queued_at=T0), _cand("new", offset=1, queued_at=T0 + 10)]
    assert plan_activity_groups(candidates, POLICY, now=T0 + 14.9) == []
    [group] = plan_activity_groups(candidates, POLICY, now=T0 + 15)
    assert (group.uuids, group.reason) == (("old", "new"), "wait")
    # Unknown queue time counts as waited.
    [group] = plan_activity_groups([_cand("x", queued_at=None)], POLICY, now=T0)
    assert group.reason == "wait"


def test_groups_follow_lane_order_and_split_by_graph_and_simulation():
    candidates = [
        _cand("g2-a", graph="g2", offset=5), _cand("g1-s2", graph="g1", sim="s2", offset=0),
        _cand("g1-s1-late", graph="g1", offset=9), _cand("g1-s1-early", graph="g1", offset=1),
    ]
    groups = plan_activity_groups(candidates, POLICY, now=T0, force=True)
    assert [(g.graph_id, g.simulation_key, g.uuids) for g in groups] == [
        ("g1", "s1", ("g1-s1-early", "g1-s1-late")),
        ("g1", "s2", ("g1-s2",)),
        ("g2", "s1", ("g2-a",)),
    ]


def test_expired_candidates_and_policy_from_settings(memory_settings):
    candidates = [_cand("fresh", queued_at=T0 - 10), _cand("stale", queued_at=T0 - 301), _cand("x", queued_at=None)]
    assert [c.uuid for c in expired_activity_candidates(candidates, POLICY, T0)] == ["stale", "x"]
    policy = ActivityPolicy.from_settings(memory_settings)
    assert policy.group_size == memory_settings.activity_group_size
    assert policy.group_chars == memory_settings.activity_group_chars
    assert policy.group_wait_seconds == memory_settings.activity_group_wait_seconds
    assert policy.max_pending_seconds == memory_settings.activity_max_pending_seconds
    assert policy.max_llm_calls == memory_settings.activity_max_llm_calls


# ---------------------------------------------------------------------------
# Enrichment planning: signal filter, budget, failures, lane
# ---------------------------------------------------------------------------


def _group(chars: int = 100, sim: str = "s1"):
    [group] = plan_activity_groups([_cand("e1", sim=sim, chars=chars)], POLICY, now=T0, force=True)
    return group


class _ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


@pytest.fixture
def activity_logs():
    """Messages logged to ``mirofish.memory.activity`` (the app's "mirofish" logger may not propagate)."""

    logger = logging.getLogger("mirofish.memory.activity")
    handler = _ListHandler()
    previous = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    try:
        yield handler.messages
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous)


def test_decisions_before_the_call(activity_logs):
    lane = ActivityLane()
    assert decide_activity_group(_group(), lane=lane, calls_used=0, policy=POLICY).call is True

    no_signal = decide_activity_group(_group(chars=0), lane=lane, calls_used=0, policy=POLICY)
    assert (no_signal.call, no_signal.status, no_signal.error["code"]) == (False, "skipped", "no_signal")

    for _ in range(3):
        over = decide_activity_group(_group(), lane=lane, calls_used=60, policy=POLICY)
        assert (over.call, over.status, over.error["code"]) == (False, "skipped", "budget_exhausted")
    budget_logs = [m for m in activity_logs if "budget" in m]
    assert len(budget_logs) == 1  # logged once per simulation
    zero_budget = ActivityPolicy(max_llm_calls=0)
    assert decide_activity_group(_group(sim="s9"), lane=lane, calls_used=0, policy=zero_budget).call is False
    # Another simulation still has budget.
    assert decide_activity_group(_group(sim="s2"), lane=lane, calls_used=3, policy=POLICY).call is True


def test_failures_degrade_and_fatal_codes_switch_the_lane_off(activity_logs):
    lane = ActivityLane()

    soft = activity_failure_decision({"code": "llm_bad_output", "message": "invalid JSON"}, lane=lane)
    assert (soft.call, soft.status, dict(soft.error)) == (
        False, "degraded", {"code": "llm_bad_output", "message": "invalid JSON"})
    assert lane.enabled
    assert activity_failure_decision(None, lane=lane).error["code"] == "extraction_error"

    for _ in range(2):
        fatal = activity_failure_decision({"code": "llm_quota_exhausted", "message": "quota"}, lane=lane)
        assert fatal.status == "degraded"
    assert not lane.enabled
    assert lane.disabled_error == {"code": "llm_quota_exhausted"}
    assert len([m for m in activity_logs if "disabled" in m]) == 1

    after = decide_activity_group(_group(), lane=lane, calls_used=0, policy=POLICY)
    assert (after.call, after.status, after.error["code"]) == (False, "skipped", "llm_unavailable")


# ---------------------------------------------------------------------------
# Scheduler SQL helpers
# ---------------------------------------------------------------------------


def test_load_claim_and_finish_queued_activity(local, seed):
    seed.graph("g1")
    now = epoch_to_iso(T0)
    signal_activity = _activity("CREATE_POST", {"content": POST})
    queued, _ = _add(local.store, "g1", [signal_activity], mode="llm", now=now,
                     created_at=epoch_to_iso(T0 - 5))
    _add(local.store, "g1", [_activity("CREATE_POST", {"content": POST})], mode="rules")  # finished
    _insert_episode(local.store, "g1", "document text", kind="document", status="queued", queued_at=now)

    with local.store.read() as conn:
        [candidate] = load_activity_candidates(conn)
    assert candidate.uuid == queued
    assert (candidate.graph_id, candidate.simulation_key) == ("g1", "sim-1")
    assert candidate.chars == len(signal_activity.to_episode_text())
    assert candidate.queued_at == T0

    with local.store.write() as conn:
        assert claim_activity_episodes(conn, [queued, "missing"], owner="host:1:0", lease_until=T0 + 180) == [queued]
        assert claim_activity_episodes(conn, [queued], owner="other", lease_until=T0 + 180) == []
    row = _episode_row(local.store, queued)
    assert (row["extraction_status"], row["lease_owner"], row["lease_until"], row["attempts"]) == (
        "processing", "host:1:0", T0 + 180, 1)

    with local.store.write() as conn:
        assert finish_activity_episodes(conn, [queued], status="succeeded") == 1
        # Terminal episodes are never overwritten.
        assert finish_activity_episodes(conn, [queued], status="skipped", error={"code": "deadline"}) == 0
        with pytest.raises(ValueError):
            finish_activity_episodes(conn, [queued], status="processing")
    row = _episode_row(local.store, queued)
    assert (row["processed"], row["extraction_status"], row["lease_owner"]) == (1, "succeeded", None)
    assert episode_from_row(row).processed is True


def test_deadline_sweep_skips_only_stale_queued_episodes(local, seed):
    seed.graph("g1")
    post = [_activity("CREATE_POST", {"content": POST})]
    stale, _ = _add(local.store, "g1", post, mode="llm", now=epoch_to_iso(T0 - 301))
    fresh, _ = _add(local.store, "g1", post, mode="llm", now=epoch_to_iso(T0 - 10))

    with local.store.write() as conn:
        swept = sweep_expired_activity_episodes(conn, now=T0, max_pending_seconds=300)
    assert swept == [stale]
    stale_row, fresh_row = _episode_row(local.store, stale), _episode_row(local.store, fresh)
    assert (stale_row["processed"], stale_row["extraction_status"]) == (1, "skipped")
    assert json_loads(stale_row["extraction_error"])["code"] == "deadline"
    assert (fresh_row["processed"], fresh_row["extraction_status"]) == (0, "queued")


def test_usage_accounting_feeds_the_budget(local, seed):
    seed.graph("g1")
    with local.store.write() as conn:
        assert activity_llm_calls_used(conn, "sim-1") == 0
        record_activity_llm_call(conn, sim_key="sim-1", graph_id="g1", prompt_chars=100, output_chars=40)
        record_activity_llm_call(conn, sim_key="sim-1", graph_id="g1", prompt_chars=50, failed=True)
    with local.store.read() as conn:
        assert activity_llm_calls_used(conn, "sim-1") == 2
        rows = {row["scope_kind"]: dict(row) for row in conn.execute("SELECT * FROM usage")}
    for scope in ("simulation", "graph"):
        assert (rows[scope]["llm_calls"], rows[scope]["llm_failures"]) == (2, 1)
        assert (rows[scope]["prompt_chars"], rows[scope]["output_chars"]) == (150, 40)
    assert rows["graph"]["scope_id"] == "g1"


# ---------------------------------------------------------------------------
# Enrichment prompt
# ---------------------------------------------------------------------------


def test_window_renders_signal_records_with_episode_markers():
    post = _activity("CREATE_POST", {"content": POST}, agent="陈屿")
    like = _activity("LIKE_POST", {"post_author_name": "陈屿"}, agent="周岚")
    comment = _activity("CREATE_COMMENT", {"post_author_name": "陈屿", "content": COMMENT}, agent="海岳能源")
    episodes = [
        {"uuid": "e1", "content": post.to_episode_text() + "\n" + like.to_episode_text(),
         "reference_time": "2026-07-01T09:00:00Z"},
        {"uuid": "e2", "content": like.to_episode_text(), "reference_time": "2026-07-01T09:30:00Z"},
        {"uuid": "e3", "content": comment.to_episode_text(), "reference_time": "2026-07-01T09:10:00Z"},
    ]
    window = render_activity_window(episodes)

    assert window.markers == {1: "e1", 2: "e3"}
    assert window.episode_uuids == ("e1", "e2", "e3")
    assert window.accounts == ("陈屿", "海岳能源")
    assert window.reference_time == "2026-07-01T09:10:00.000000Z"
    assert window.text == "\n".join([
        "[episode 1 | time 2026-07-01T09:00:00.000000Z]",
        post.to_episode_text(),
        "[episode 2 | time 2026-07-01T09:10:00.000000Z]",
        comment.to_episode_text(),
    ])
    assert "点赞" not in window.text
    assert render_activity_window([episodes[1]]).has_signal is False


def test_window_renders_english_signal_records():
    post = _activity("CREATE_POST", {"content": EN_POST}, agent="Alice Chen")
    like = _activity("LIKE_POST", {"post_author_name": "Alice Chen", "post_content": EN_POST}, agent="Bruno")
    quote = _activity("QUOTE_POST", {"original_author_name": "Alice Chen", "quote_content": EN_QUOTE},
                      agent="Chandra")
    content = "\n".join(activity.to_episode_text("en") for activity in (post, like, quote))
    window = render_activity_window([{"uuid": "e1", "content": content, "reference_time": "2026-07-01T09:00:00Z"}])

    assert window.markers == {1: "e1"}
    assert window.accounts == ("Alice Chen", "Chandra")
    assert window.text == "\n".join([
        "[episode 1 | time 2026-07-01T09:00:00.000000Z]",
        post.to_episode_text("en"),
        quote.to_episode_text("en"),
    ])
    assert "liked" not in window.text


def test_activity_messages_follow_the_extraction_prompt_layout():
    window = render_activity_window([{
        "uuid": "e1", "content": _activity("CREATE_POST", {"content": POST}).to_episode_text(),
        "reference_time": "2026-07-01T09:00:00Z",
    }])
    ontology = OntologyView({
        "entity_types": [{"name": "Person", "description": "A person.", "properties": []}],
        "edge_types": [{"name": "SUPPORTS", "description": "Supports.", "properties": [],
                        "source_targets": [{"source": "Person", "target": "Entity"}]}],
    })
    messages = build_activity_messages(
        window, ontology=ontology, known_entities=[("陈屿", "Person"), ("Twitter", None)],
        existing_facts=[PromptFact("F1", "陈屿", "SUPPORTS", "智巡平台", "陈屿支持智巡平台。", "2026-06-01")],
        max_entities=12, max_relations=34,
    )

    system, user = messages[0]["content"], messages[1]["content"]
    assert [m["role"] for m in messages] == ["system", "user"]
    assert system == activity_system_prompt(12, 34)
    assert "At most 12 entities and 34 relations" in system
    assert "Skip likes, follows, mutes and searches" in system
    assert "{max_" not in system
    assert user.startswith("REFERENCE TIME: 2026-07-01T09:00:00.000000Z\nENTITY TYPES:\n- Person: A person.")
    assert "- SUPPORTS: Supports. Allowed: Person -> Entity." in user
    assert "KNOWN ENTITIES (reuse these exact names): 陈屿 [Person]; Twitter [Entity]" in user
    assert 'F1: 陈屿 -SUPPORTS-> 智巡平台: "陈屿支持智巡平台。" (valid_at 2026-06-01)' in user
    assert user.endswith('Return: {"entities":[...],"relations":[...],"invalidated_facts":[...]}')
    # The fake LLM (and a real one) can find the TEXT block and the markers.
    assert text_block(messages) == window.text
    assert _CHUNK_MARKER_RE.match(window.text.splitlines()[0]).group("n") == "1"

    bare = build_activity_messages(window)[1]["content"]
    assert 'ENTITY TYPES: (none, use "Entity")' in bare
    assert "KNOWN ENTITIES (reuse these exact names): (none)" in bare
    assert "EXISTING FACTS: (none)" in bare


# ---------------------------------------------------------------------------
# The pieces together: one activity lane as the worker will run it
# ---------------------------------------------------------------------------


def _run_lane_once(store, llm, lane: ActivityLane, policy: ActivityPolicy, now: float, *,
                   force: bool = False) -> list[tuple[tuple[str, ...], str]]:
    """Minimal stand-in for the worker's activity lane (no result writes)."""

    outcomes = []
    with store.write() as conn:
        sweep_expired_activity_episodes(conn, now=now, max_pending_seconds=policy.max_pending_seconds)
    with store.read() as conn:
        candidates = load_activity_candidates(conn)
    for group in plan_activity_groups(candidates, policy, now=now, force=force):
        with store.read() as conn:
            used = activity_llm_calls_used(conn, group.simulation_key)
        decision = decide_activity_group(group, lane=lane, calls_used=used, policy=policy)
        if decision.call:
            with store.write() as conn:
                claimed = claim_activity_episodes(conn, group.uuids, owner="test", lease_until=now + 60)
                rows = conn.execute(
                    f"SELECT uuid, content, reference_time FROM episodes WHERE uuid IN "
                    f"({','.join('?' for _ in claimed)}) ORDER BY created_at, id", claimed,
                ).fetchall()
            messages = build_activity_messages(render_activity_window(rows))
            status, error, failed = "succeeded", None, False
            try:
                llm.chat_json(messages)
            except RuntimeError:
                # The worker classifies errors (§4.9); here every failure is a spent quota.
                failure = activity_failure_decision({"code": "llm_quota_exhausted", "message": "quota"},
                                                    lane=lane)
                status, error, failed = failure.status, failure.error, True
            with store.write() as conn:
                record_activity_llm_call(conn, sim_key=group.simulation_key, graph_id=group.graph_id,
                                         failed=failed)
                finish_activity_episodes(conn, claimed, status=status, error=error)
        else:
            status = decision.status
            with store.write() as conn:
                finish_activity_episodes(conn, group.uuids, status=status, error=decision.error)
        outcomes.append((group.uuids, status))
    return outcomes


def test_activity_lane_end_to_end_with_budget_and_fatal_switch(local, seed, fake_llm):
    seed.graph("g1")
    policy = ActivityPolicy(group_size=2, group_chars=12_000, group_wait_seconds=15.0,
                            max_pending_seconds=300.0, max_llm_calls=1)
    contents = ["智巡平台今天在海城市上线。", "海岳能源宣布终止联合部署协议。", "新的管理团队首次公开亮相。"]
    posts = [_activity("CREATE_POST", {"content": text}, round_num=i) for i, text in enumerate(contents)]
    uuids = [
        _add(local.store, "g1", [post], mode="llm", now=epoch_to_iso(T0), created_at=epoch_to_iso(T0 + i))[0]
        for i, post in enumerate(posts)
    ]
    fake_llm.script = [{"entities": [], "relations": []}]
    lane = ActivityLane()

    # First tick: one full group (size 2) is called; the tail waits.
    assert _run_lane_once(local.store, fake_llm, lane, policy, T0 + 1) == [((uuids[0], uuids[1]), "succeeded")]
    assert fake_llm.call_count == 1
    assert "[episode 1 | time" in text_block(fake_llm.calls[0]["messages"])
    # Second tick after the wait: the budget (1 call) is used up.
    assert _run_lane_once(local.store, fake_llm, lane, policy, T0 + 20) == [((uuids[2],), "skipped")]
    assert fake_llm.call_count == 1
    assert json_loads(_episode_row(local.store, uuids[2])["extraction_error"])["code"] == "budget_exhausted"
    assert all(_episode_row(local.store, u)["processed"] == 1 for u in uuids)

    # A fatal LLM failure degrades that group and turns the lane off for later groups.
    more = [
        _add(local.store, "g1", [post], mode="llm", now=epoch_to_iso(T0 + 30), simulation_id="sim-2",
             created_at=epoch_to_iso(T0 + 30 + i))[0]
        for i, post in enumerate(posts)
    ]
    fake_llm.script = [RuntimeError("quota")]
    outcomes = _run_lane_once(local.store, fake_llm, lane, policy, T0 + 31, force=True)
    assert outcomes == [((more[0], more[1]), "degraded"), ((more[2],), "skipped")]
    assert not lane.enabled
    assert json_loads(_episode_row(local.store, more[2])["extraction_error"])["code"] == "llm_unavailable"
    # Rules facts exist for every activity regardless of enrichment.
    assert len([e for e in _edges(local.store) if e["name"] == "POSTED"]) == 3
