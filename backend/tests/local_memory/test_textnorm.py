"""Pure text helpers: name keys, relation names, similarity, timestamps."""

from __future__ import annotations

import re
from datetime import datetime, timezone

import pytest

from app.memory.textnorm import (
    STOPWORDS_EN,
    TEMPLATE_PHRASES,
    alias_keys,
    compact_text,
    format_utc,
    is_cjk,
    is_latin,
    name_key,
    normalize_name,
    parse_iso_date,
    parse_iso_datetime,
    split_sentences,
    to_upper_snake,
    trigram_jaccard,
    trigrams,
    truncate,
    utcnow_iso,
)

ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$")


@pytest.mark.parametrize("raw, expected", [
    ("  The Acme Corp. ", "acme corp"),
    ("“Alice   Chen”", "alice chen"),
    ("「北京大学」", "北京大学"),
    ("ＡＢＣ", "abc"),  # NFKC folds full-width letters
    ("An Apple!", "apple"),
    ("Theodore", "theodore"),
    ("", ""),
])
def test_normalize_name(raw, expected):
    assert normalize_name(raw) == expected


@pytest.mark.parametrize("a, b", [
    ("Alice Chen", "alice-chen"),
    ("Alice Chen", "ALICE_CHEN."),
    ("O'Neil", "ONeil"),
    ("Jean·Luc", "jean luc"),
])
def test_name_key_ignores_separators_and_case(a, b):
    assert name_key(a) == name_key(b)


def test_alias_keys_include_aliases_and_honorific_free_forms():
    keys = alias_keys("Dr. Alice Chen", ["Alice", "Prof Chen"])
    assert keys == {"dralicechen", "alicechen", "alice", "profchen", "chen"}

    cjk = alias_keys("王建国先生", [])
    assert cjk == {"王建国先生", "王建国"}
    # A single character left after stripping is too ambiguous to register.
    assert alias_keys("王先生", []) == {"王先生"}
    assert alias_keys("", ["", "  "]) == set()


def test_compact_text_supports_mention_checks():
    text = compact_text("Yesterday, Alice-Chen met the ACME corp team.")
    assert name_key("Alice Chen") in text
    assert name_key("Acme Corp") in text


@pytest.mark.parametrize("raw, expected", [
    ("works for", "WORKS_FOR"),
    ("works-for", "WORKS_FOR"),
    ("worksFor", "WORKS_FOR"),
    ("WORKS_FOR", "WORKS_FOR"),
    ("  member of  ", "MEMBER_OF"),
    ("CREATE_POST", "CREATE_POST"),
    ("关注", "RELATES_TO"),
    ("123", "RELATES_TO"),
    ("", "RELATES_TO"),
    (None, "RELATES_TO"),
])
def test_to_upper_snake(raw, expected):
    assert to_upper_snake(raw) == expected


def test_to_upper_snake_caps_length_without_trailing_underscore():
    value = to_upper_snake("a" * 59 + " b" * 10)
    assert len(value) <= 60
    assert not value.endswith("_")


def test_trigram_similarity():
    assert trigrams("ab") == {"ab"}
    assert trigrams("abcd") == {"abc", "bcd"}
    assert trigram_jaccard("alicechen", "alicechen") == 1.0
    assert trigram_jaccard("", "x") == 0.0
    assert trigram_jaccard("alicechenworksforacme", "alicechenworksforacmecorp") >= 0.8
    assert trigram_jaccard("alice", "globex") == 0.0


@pytest.mark.parametrize("raw, expected", [
    ("2021", "2021-01-01T00:00:00.000000Z"),
    ("2021-05", "2021-05-01T00:00:00.000000Z"),
    ("2021-05-10", "2021-05-10T00:00:00.000000Z"),
    ("2026-05-10T09:00:00Z", "2026-05-10T09:00:00.000000Z"),
    ("2026-05-10T17:00:00+08:00", "2026-05-10T09:00:00.000000Z"),
    ("2026-05-10T09:00:00.123456", "2026-05-10T09:00:00.123456Z"),
    ("2021-13", None),
    ("last spring", None),
    ("", None),
    (None, None),
    (2021, None),
])
def test_parse_iso_date(raw, expected):
    assert parse_iso_date(raw) == expected


def test_parse_iso_datetime_timezone_policy():
    assert parse_iso_datetime("2026-05-10T09:00:00") == "2026-05-10T09:00:00.000000Z"
    assert parse_iso_datetime("2026-05-10T09:00:00", require_timezone=True) is None
    assert parse_iso_datetime("2026-05-10T09:00:00z", require_timezone=True) == "2026-05-10T09:00:00.000000Z"
    assert parse_iso_datetime("2026", require_timezone=True) is None
    aware = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    assert parse_iso_datetime(aware) == "2026-01-02T03:04:05.000000Z"


def test_timestamps_have_one_sortable_format():
    now = utcnow_iso()
    assert ISO_RE.match(now)
    assert ISO_RE.match(format_utc(datetime(5, 1, 1)))
    assert format_utc(datetime(5, 1, 1)) == "0005-01-01T00:00:00.000000Z"
    earlier = parse_iso_date("2021-05-10T23:59:59+00:00")
    later = parse_iso_date("2021-05-11T00:00:00+08:00")  # 2021-05-10T16:00Z
    assert earlier > later


def test_script_detection():
    assert is_cjk("北京")
    assert is_cjk("mixed 文本")
    assert is_cjk("カタカナ")
    assert not is_cjk("plain")
    assert is_latin("café")
    assert not is_latin("two words")


def test_sentences_and_truncation():
    assert split_sentences("Alice leads. Bob follows!  张伟毕业了。然后呢？") == [
        "Alice leads.", "Bob follows!", "张伟毕业了。", "然后呢？",
    ]
    assert split_sentences("") == []
    assert truncate("  abcdef ", 3) == "abc"
    assert truncate(None, 3) == ""


def test_query_vocabulary():
    assert {"the", "about", "information", "relationships", "all"} <= STOPWORDS_EN
    assert "alice" not in STOPWORDS_EN
    assert TEMPLATE_PHRASES.index("的所有信息") < TEMPLATE_PHRASES.index("所有信息")
