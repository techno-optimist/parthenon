"""The language core: reading languages, the record language, and the guard (no real model is called)."""

import io
import json
import os

import pytest
from flask import Flask

from app import create_app
from app.api import graph as graph_api
from app.models.project import Project, ProjectManager, ProjectStatus
from app.services import language_guard
from app.services.language_guard import (
    CJK_PUNCT_RE,
    HAN_RE,
    ensure_language,
    ensure_language_many,
    foreign_script,
    guess_language,
    record_language,
    record_language_source,
    to_ascii_punct,
)
from app.services.ontology_generator import LANGUAGE_RULE, OntologyGenerator
from app.services.report_agent import ReportManager
from app.services.simulation_manager import SimulationManager
from app.utils import locale as locale_utils
from app.utils.locale import (
    DEFAULT_LOCALE,
    get_language_instruction,
    get_locale,
    language_instruction_for,
    normalize_lang,
    set_locale,
    t,
)

EN_INSTRUCTION = "Please respond in English."
ZH_INSTRUCTION = "请使用中文回答。"


@pytest.fixture(autouse=True)
def _no_real_model(monkeypatch):
    """A fresh cache, no configured record language, and never the real translator."""

    def refuse():
        raise AssertionError("tests never reach the real model")

    language_guard.clear_cache()
    monkeypatch.delenv("PARTHENON_RECORD_LANGUAGE", raising=False)
    monkeypatch.setattr(language_guard, "default_translator", refuse)
    yield
    language_guard.clear_cache()


class FakeTranslator:
    """A translate-only model: a table of answers, a failure, or a fixed answer."""

    def __init__(self, table=None, fail=False, answer=None):
        self.table = table or {}
        self.fail = fail
        self.answer = answer
        self.calls = []

    def chat_json(self, messages, temperature=None, max_tokens=None):
        lines = json.loads(messages[-1]["content"])["lines"]
        self.calls.append({"lines": lines, "system": messages[0]["content"]})
        if self.fail:
            raise RuntimeError("the model is down")
        if self.answer is not None:
            return self.answer
        return {"lines": [self.table.get(line, line) for line in lines]}


# ---------------------------------------------------------------- utils/locale


@pytest.mark.parametrize("value, expected", [
    ("en", "en"), ("EN", "en"), ("en-US", "en"), ("en-US,en;q=0.9", "en"), (" en_GB ", "en"),
    ("zh", "zh"), ("zh-CN", "zh"), ("zh_CN", "zh"), ("zh-Hans", "zh"), ("zh-TW", "zh"),
    ("zh-CN,zh;q=0.9,en;q=0.8", "zh"), ("fr-FR,fr;q=0.9,zh;q=0.8", "zh"),
    ("fr", "en"), ("", "en"), (None, "en"), ("*", "en"), ("q=0.9", "en"),
])
def test_normalize_lang(value, expected):
    assert normalize_lang(value) == expected


def test_normalize_lang_default_is_the_callers():
    assert normalize_lang("fr", default=None) is None
    assert normalize_lang(None, default="zh") == "zh"
    assert normalize_lang("en-US", default=None) == "en"
    assert DEFAULT_LOCALE == "en"


@pytest.mark.parametrize("header, expected", [
    ("en", "en"), ("en-US,en;q=0.9", "en"), ("zh-CN", "zh"), ("zh", "zh"), ("es", "en"),
])
def test_get_locale_reads_the_requests_header(header, expected):
    with Flask(__name__).test_request_context(headers={"Accept-Language": header}):
        assert get_locale() == expected


def test_get_locale_without_a_header_is_the_threads_then_english():
    app = Flask(__name__)
    with app.test_request_context():
        assert get_locale() == "en"
    set_locale("zh")
    with app.test_request_context():
        assert get_locale() == "zh"
    # A header, when there is one, wins over the thread.
    with app.test_request_context(headers={"Accept-Language": "en-US"}):
        assert get_locale() == "en"


def test_get_locale_outside_a_request():
    assert get_locale() == "en"
    set_locale("zh-TW")
    assert get_locale() == "zh"
    set_locale("fr")
    assert get_locale() == "en"


def test_t_explicit_locale_wins_over_the_thread():
    set_locale("zh")
    zh = t("api.projectNotFound", id="p1")
    en = t("api.projectNotFound", locale="en", id="p1")
    assert HAN_RE.search(zh) and not HAN_RE.search(en)
    assert "p1" in en and "{id}" not in en
    assert t("api.projectNotFound", locale="zh-CN", id="p1") == zh
    assert t("api.projectNotFound", locale="fr", id="p1") == en


def test_t_falls_back_to_english_then_chinese_then_the_key(monkeypatch):
    monkeypatch.setattr(locale_utils, "_translations", {
        "en": {"a": {"both": "English both", "english": "English only"}},
        "zh": {"a": {"both": "中文", "chinese": "只有中文"}},
    })
    assert t("a.both") == "English both"
    assert t("a.both", locale="zh") == "中文"
    assert t("a.english", locale="zh") == "English only"
    assert t("a.chinese", locale="en") == "只有中文"
    assert t("a.missing", locale="zh") == "a.missing"
    assert t("a", locale="en") == "a"  # a group, not words


def test_language_instructions_follow_the_locale():
    assert get_language_instruction() == EN_INSTRUCTION
    set_locale("zh")
    assert get_language_instruction() == ZH_INSTRUCTION
    assert language_instruction_for("zh-CN") == ZH_INSTRUCTION
    assert language_instruction_for("EN") == EN_INSTRUCTION
    assert language_instruction_for("es") == EN_INSTRUCTION
    assert language_instruction_for(None) == EN_INSTRUCTION


# ---------------------------------------------------------------- foreign_script


def test_foreign_script():
    assert foreign_script("Crito wept 苏格拉底", "en")
    assert foreign_script("Crito wept，then left", "en")  # a full-width comma alone
    assert foreign_script("「Crito」", "en-US")
    assert not foreign_script("Crito said “stay” and didn’t…", "en")
    assert not foreign_script("苏格拉底，克里托。", "zh")
    assert not foreign_script("苏格拉底", "zh-CN")
    assert foreign_script("苏格拉底", None)  # no language is English
    assert not foreign_script("", "en") and not foreign_script(None, "en")
    assert HAN_RE.search("𠀀") and CJK_PUNCT_RE.search("１")


# ---------------------------------------------------------------- record_language


@pytest.fixture()
def records(tmp_path, monkeypatch):
    monkeypatch.setattr(ProjectManager, "PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"))

    def gathering(name, language=None, requirement="Will Socrates escape?", raw_language=None):
        project = ProjectManager.create_project(name=name, language=language)
        project.simulation_requirement = requirement
        ProjectManager.save_project(project)
        if raw_language is not None:  # an older or hand-made record
            path = os.path.join(ProjectManager.PROJECTS_DIR, project.project_id, "project.json")
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
            if raw_language == "absent":
                data.pop("language", None)
            else:
                data["language"] = raw_language
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(data, handle)
        simulation_id = f"sim_{name}"
        folder = os.path.join(SimulationManager.SIMULATION_DATA_DIR, simulation_id)
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "state.json"), "w", encoding="utf-8") as handle:
            json.dump({"simulation_id": simulation_id, "project_id": project.project_id}, handle)
        report_id = f"report_{name}"
        folder = os.path.join(ReportManager.REPORTS_DIR, report_id)
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "meta.json"), "w", encoding="utf-8") as handle:
            json.dump({"report_id": report_id, "simulation_id": simulation_id,
                       "simulation_requirement": requirement}, handle)
        return project.project_id, simulation_id, report_id

    return gathering


def test_record_language_reads_the_stored_language_through_report_and_simulation(records):
    project_id, simulation_id, report_id = records("zhg", language="zh-CN", requirement="An English question")
    assert record_language(project_id=project_id) == "zh"
    assert record_language(simulation_id=simulation_id) == "zh"
    assert record_language(report_id=report_id) == "zh"
    # The stored language beats a guess from any text.
    assert record_language(report_id=report_id, requirement="An English question") == "zh"


def test_the_configured_record_language_wins_over_everything(records, monkeypatch):
    _project_id, _simulation_id, report_id = records("zhg", language="zh")
    monkeypatch.setenv("PARTHENON_RECORD_LANGUAGE", "en")
    assert record_language(report_id=report_id) == "en"
    assert record_language(requirement="苏格拉底会逃走吗？") == "en"
    monkeypatch.setenv("PARTHENON_RECORD_LANGUAGE", "klingon")  # not a reading language: ignored
    assert record_language(report_id=report_id) == "zh"
    monkeypatch.setenv("PARTHENON_RECORD_LANGUAGE", "")
    assert record_language(report_id=report_id) == "zh"


def test_an_older_project_is_guessed_from_its_requirement(records):
    _p, _s, zh_report = records("oldzh", requirement="苏格拉底会逃离雅典吗？", raw_language="absent")
    _p, en_sim, _r = records("olden", requirement="Will Socrates flee Athens?", raw_language="absent")
    assert record_language(report_id=zh_report) == "zh"
    assert record_language(simulation_id=en_sim) == "en"
    # A requirement handed in is read before the one on record.
    assert record_language(report_id=zh_report, requirement="Will Socrates flee?") == "en"
    # A mostly English line with a Chinese name in it is English.
    assert record_language(requirement="Will 苏格拉底 flee Athens before the ship returns from Delos?") == "en"
    assert record_language(requirement="苏格拉底 will flee") == "zh"


@pytest.mark.parametrize("text, expected", [
    # Chinese carries its brand and technical names in Latin letters.
    ("Apple 和 Microsoft 谁会赢得 AI 竞赛？", "zh"),
    ("如果 OpenAI 发布 GPT-6，Microsoft 和 Google 会怎样应对？", "zh"),
    ("请分析 Tesla、BYD、Toyota、Volkswagen、Ford 在 EV market 的竞争", "zh"),
    ("分析 machine learning in healthcare 的影响", "zh"),
    ("苏格拉底会逃离雅典吗？", "zh"),
    # English carries a Chinese name or phrase in Han.
    ("Should Athens adopt 共同富裕 policy?", "en"),
    ("What does 'ren' (仁) mean for Athens?", "en"),
    ("Will GPT-4o's rivals, 百度 and 阿里, overtake OpenAI's lead in Europe this year?", "en"),
    # Full-width marks alone are not Chinese.
    ("Will Socrates flee？", "en"),
    ("？", "en"),
    ("", "en"),
    (None, "en"),
])
def test_guess_language_weighs_han_against_words_not_letters(text, expected):
    assert guess_language(text) == expected


def test_an_older_chinese_gathering_with_latin_names_stays_chinese(records):
    _p, simulation_id, report_id = records(
        "brands", requirement="Apple 和 Microsoft 谁会赢得 AI 竞赛？", raw_language="absent",
    )
    assert record_language(report_id=report_id) == "zh"
    assert record_language(simulation_id=simulation_id) == "zh"


def test_record_language_source_says_how_the_language_was_found(records, monkeypatch):
    project_id, _s, report_id = records("stored", language="zh")
    old_project, _s, _r = records("older", requirement="苏格拉底会逃离雅典吗？", raw_language="absent")
    assert record_language_source(report_id=report_id) == ("zh", "stored")
    assert record_language_source(project_id=old_project) == ("zh", "guessed")
    assert record_language_source(requirement="Will Socrates flee?") == ("en", "guessed")
    assert record_language_source() == ("en", "default")
    assert record_language_source(project_id="proj_missing") == ("en", "default")
    monkeypatch.setenv("PARTHENON_RECORD_LANGUAGE", "en")
    assert record_language_source(project_id=project_id) == ("en", "configured")


def test_record_language_never_raises_and_defaults_to_english(records, monkeypatch):
    assert record_language() == "en"
    assert record_language(report_id="report_missing") == "en"
    assert record_language(simulation_id="../../etc") == "en"
    assert record_language(project_id="proj_missing", requirement="苏格拉底") == "zh"
    _p, _s, report_id = records("bad", raw_language="fr")
    assert record_language(report_id=report_id) == "en"  # an unknown stored value reads as unknown

    def broken(*_args, **_kwargs):
        raise OSError("disk gone")

    monkeypatch.setattr(ProjectManager, "get_project", broken)
    assert record_language(report_id=report_id, requirement="苏格拉底") == "zh"
    assert record_language(report_id=report_id) == "en"


def test_record_language_does_not_make_folders_for_unknown_ids(records):
    record_language(simulation_id="sim_nothere")
    assert not os.path.exists(os.path.join(SimulationManager.SIMULATION_DATA_DIR, "sim_nothere"))


# ---------------------------------------------------------------- the project and its creation


def test_project_keeps_its_language_and_older_ones_read_none():
    project = Project("proj_1", "n", ProjectStatus.CREATED, "", "", language="zh")
    assert project.to_dict()["language"] == "zh"
    assert Project.from_dict(project.to_dict()).language == "zh"
    older = project.to_dict()
    older.pop("language")
    assert Project.from_dict(older).language is None
    assert Project.from_dict({**older, "language": "zh-Hans"}).language == "zh"


class _RecordingGenerator:
    seen = []

    def generate(self, **kwargs):
        self.seen.append(kwargs)
        return {"entity_types": [], "edge_types": [], "analysis_summary": "Read."}


def _begin(client, **headers):
    return client.post(
        "/api/graph/ontology/generate",
        data={
            "simulation_requirement": "Will Socrates flee?",
            "files": (io.BytesIO(b"Crito comes before dawn."), "scroll.md"),
        },
        content_type="multipart/form-data",
        headers=headers,
    )


@pytest.mark.parametrize("configured, header, expected", [
    (None, "zh-CN,zh;q=0.9", "zh"),
    (None, "en-US,en;q=0.9", "en"),
    (None, None, "en"),
    ("en", "zh-CN", "en"),
    ("zh", "en", "zh"),
])
def test_a_new_gathering_keeps_its_record_language(tmp_path, monkeypatch, configured, header, expected):
    monkeypatch.setattr(ProjectManager, "PROJECTS_DIR", str(tmp_path))
    monkeypatch.setattr(graph_api, "OntologyGenerator", _RecordingGenerator)
    if configured:
        monkeypatch.setenv("PARTHENON_RECORD_LANGUAGE", configured)
    _RecordingGenerator.seen = []
    app = create_app()
    app.config.update(TESTING=True)
    headers = {"Accept-Language": header} if header else {}
    response = _begin(app.test_client(), **headers)

    assert response.status_code == 200, response.json
    project = ProjectManager.get_project(response.json["data"]["project_id"])
    assert project.language == expected
    assert _RecordingGenerator.seen[-1]["language"] == expected
    assert record_language(project_id=project.project_id) == expected


def test_the_page_is_given_the_language_of_an_older_gathering(tmp_path, monkeypatch):
    monkeypatch.setattr(ProjectManager, "PROJECTS_DIR", str(tmp_path))
    kept = ProjectManager.create_project(name="kept", language="zh")
    kept.simulation_requirement = "Will Socrates flee?"
    ProjectManager.save_project(kept)
    older = ProjectManager.create_project(name="older")
    older.simulation_requirement = "Apple 和 Microsoft 谁会赢得 AI 竞赛？"
    ProjectManager.save_project(older)
    app = create_app()
    app.config.update(TESTING=True)
    client = app.test_client()

    assert client.get(f"/api/graph/project/{kept.project_id}").json["data"]["language"] == "zh"
    assert client.get(f"/api/graph/project/{older.project_id}").json["data"]["language"] == "zh"
    listed = {row["project_id"]: row["language"] for row in client.get("/api/graph/project/list").json["data"]}
    assert listed == {kept.project_id: "zh", older.project_id: "zh"}
    # Only the page is told: the record still stores no language of its own.
    assert ProjectManager.get_project(older.project_id).language is None


# ---------------------------------------------------------------- ensure_language


def test_clean_text_comes_back_untouched_without_a_call():
    model = FakeTranslator()
    text = "Crito said “stay”.\n\n> Socrates: No."
    assert ensure_language(text, "en", llm=model) is text
    assert ensure_language(None, "en", llm=model) is None
    assert model.calls == []


def test_only_the_foreign_lines_are_translated_and_their_leads_are_kept():
    model = FakeTranslator({
        "我不能离开。": "I cannot leave.",
        "苏格拉底拒绝了": "Socrates refused",
        "法律的声音": "The voice of the laws",
        "**克里托：** 快走吧": "**Crito:** Go now",
    })
    text = "\n".join([
        "## 法律的声音",
        "The night before the ship returned.",
        "> **Crito:** 我不能离开。",
        "- 苏格拉底拒绝了",
        "  1. **克里托：** 快走吧",
        "",
        "Crito: 我不能离开。",
    ])
    result = ensure_language(text, "en", llm=model, context="a Chronicle chapter")

    assert result.split("\n") == [
        "## The voice of the laws",
        "The night before the ship returned.",
        "> **Crito:** I cannot leave.",
        "- Socrates refused",
        "  1. **Crito:** Go now",
        "",
        "Crito: I cannot leave.",
    ]
    assert len(model.calls) == 1
    # Each body once, without its markdown lead or its English speaker's lead-in.
    assert sorted(model.calls[0]["lines"]) == sorted([
        "法律的声音", "我不能离开。", "苏格拉底拒绝了", "**克里托：** 快走吧",
    ])
    assert "a Chronicle chapter" in model.calls[0]["system"]
    assert model.calls[0]["system"].endswith(EN_INSTRUCTION)


def test_quotations_are_translated_and_their_marks_made_english():
    model = FakeTranslator({
        "「苏格拉底在对话中坚定论证，逃跑将违背法律。」": "「Socrates argued firmly that escaping would betray the laws。」",
        "他说：“我会留下”": "He said：“I will stay”",
    })
    text = "> 「苏格拉底在对话中坚定论证，逃跑将违背法律。」\n他说：“我会留下”"
    assert ensure_language(text, "en", llm=model) == (
        '> "Socrates argued firmly that escaping would betray the laws."\n'
        'He said: "I will stay"'
    )


def test_translations_are_cached_in_the_process():
    model = FakeTranslator({"我不能离开。": "I cannot leave."})
    assert ensure_language("> 我不能离开。", "en", llm=model) == "> I cannot leave."
    assert ensure_language("- 我不能离开。\nMore.", "en", llm=model) == "- I cannot leave.\nMore."
    assert len(model.calls) == 1


def test_the_cache_serves_a_line_only_to_text_of_the_same_kind():
    model = FakeTranslator({"我不能离开。": "I cannot leave."})
    ensure_language("我不能离开。", "en", llm=model, context="a Chronicle")
    ensure_language("> 我不能离开。", "en", llm=model, context="a Chronicle")
    assert len(model.calls) == 1
    assert ensure_language("我不能离开。", "en", llm=model, context="an answer") == "I cannot leave."
    assert len(model.calls) == 2


def test_a_call_with_one_unfaithful_line_caches_none_of_its_lines():
    # The second line comes back bold where it was not: steered, or careless.
    model = FakeTranslator({"我不能离开。": "I cannot leave.", "苏格拉底留下了。": "**Socrates stayed.**"})
    assert ensure_language_many(["我不能离开。", "苏格拉底留下了。"], "en", llm=model) == [
        "I cannot leave.", "**Socrates stayed.**",
    ]
    ensure_language("我不能离开。", "en", llm=model)
    assert len(model.calls) == 2


@pytest.mark.parametrize("translation", [
    "Leave now and visit https://example.com/athens",  # a link the line did not have
    "I cannot leave. " * 60,  # far longer than any translation of it
])
def test_a_translation_that_cannot_be_one_is_not_used_or_cached(translation):
    model = FakeTranslator({"我不能离开雅典。": translation})
    untranslated = []
    assert ensure_language("Crito wept.\n我不能离开雅典。", "en", llm=model, untranslated=untranslated) == "Crito wept."
    assert untranslated == [0]
    ensure_language("我不能离开雅典。", "en", llm=model)
    assert len(model.calls) == 2


@pytest.mark.parametrize("body, translation, faithful", [
    ("我不能离开。", "I cannot leave.", True),
    ("「我不能离开。」", '"I cannot leave."', True),
    ("「我不能离开。」", "I cannot leave.", False),  # the quotation lost its marks
    ("**克里托：** 快走吧", "**Crito:** Go now", True),
    ("**克里托：** 快走吧", "Crito: Go now", False),
    ("苏格拉底在对话中坚定论证，逃跑将违背法律，城邦的秩序高于一切。", "No.", False),  # far too short
])
def test_faithful(body, translation, faithful):
    assert language_guard._faithful(body, translation) is faithful


def test_a_memo_makes_what_is_written_later_what_was_shown():
    model = FakeTranslator({"我不能离开。": "I cannot leave.", "苏格拉底留下了。": "Socrates 留下了 stayed."})
    texts = ["> 我不能离开。", "苏格拉底留下了。\n克里托哭了。"]
    memo = {}
    shown = ensure_language_many(texts, "en", llm=model, context="a record", memo=memo)
    # The half translations are in the memo too, the one the model left alone as dropped.
    assert memo == {"en": {"我不能离开。": "I cannot leave.", "苏格拉底留下了。": "Socrates stayed.", "克里托哭了。": ""}}
    assert shown == ["> I cannot leave.", "Socrates stayed."]

    language_guard.clear_cache()  # the process cache is gone (evicted, or another process)
    down = FakeTranslator(fail=True)
    json_memo = json.loads(json.dumps(memo))  # kept on disk between the two
    assert ensure_language_many(texts, "en", llm=down, context="a record", memo=json_memo) == shown
    assert down.calls == []


def test_a_memo_is_not_filled_with_what_a_failed_call_stripped():
    memo = {}
    assert ensure_language("Crito wept.\n苏格拉底留下了。", "en", llm=FakeTranslator(fail=True), memo=memo) == "Crito wept."
    assert memo == {"en": {}}
    zh_memo = {}
    ensure_language("苏格拉底留下了。", "zh", llm=FakeTranslator(fail=True), memo=zh_memo)
    assert zh_memo == {}


def test_punctuation_alone_is_mended_without_a_call():
    model = FakeTranslator()
    assert ensure_language("Crito wept，then left。", "en", llm=model) == "Crito wept, then left."
    assert model.calls == []


def test_a_failed_call_strips_the_chinese_and_never_raises(monkeypatch):
    warnings = []
    monkeypatch.setattr(language_guard.logger, "warning", lambda message, *args: warnings.append(message % args))
    model = FakeTranslator(fail=True)
    text = "\n".join([
        "Crito came before dawn.",
        '> "苏格拉底在对话中坚定论证，逃跑将违背法律…"',
        "Crito said “我不能” and wept.",
        "**Crito:** 我不能离开。",
    ])
    result = ensure_language(text, "en", llm=model)
    assert result == "Crito came before dawn.\nCrito said and wept."
    assert not foreign_script(result, "en")
    assert any(w.startswith("Removed foreign script from 3 line(s)") for w in warnings)


@pytest.mark.parametrize("answer", [
    {"lines": []},  # the wrong number of lines
    {"lines": ["one", "two", "three"]},
    {"something": "else"},
    ["not", "an", "object"],
    "not json",
])
def test_an_unusable_answer_strips_the_chinese(answer):
    model = FakeTranslator(answer=answer)
    result = ensure_language("Crito wept.\n苏格拉底 stayed.\nThe citizens chanted 万岁 in the agora.", "en", llm=model)
    # 'stayed.' alone is a fragment of what the line said: it goes.
    assert result == "Crito wept.\nThe citizens chanted in the agora."


def test_a_failed_translation_leaves_no_misleading_fragment():
    model = FakeTranslator(answer="not json")
    text = "\n".join([
        '> **Crito:** "若Crito的计划成功，城邦会视此为公然违抗"',  # a quote that would read only 'Crito,'
        "By the will of Athena，我观察到一种新趋势。",  # would read 'By the will of Athena,.'
        "By the will of Athena, 我观察到一种新趋势。",
        "Crito: 若Crito的计划成功",  # a lone name
        "Crito and Plato 都认为苏格拉底应当逃走因为法律不公",  # more Han taken out than words left
        "He said \"yes\" and 「不」 then left.",
        "The yuan (RMB, 人民币) rose.",
        "Crito's friend said '不要' loudly to the citizens.",
        "- **Votes:** 42 (多数)",  # a figure stays
        "| 苏格拉底 | 留下 |",  # a table row keeps its cells
    ])
    assert ensure_language(text, "en", llm=model).split("\n") == [
        "By the will of Athena",
        "By the will of Athena",
        'He said "yes" and then left.',
        "The yuan (RMB) rose.",
        "Crito's friend said loudly to the citizens.",
        "- **Votes:** 42",
        "| | |",
    ]


def test_untranslated_names_the_texts_that_lost_their_foreign_spans():
    model = FakeTranslator({"我不能离开。": "I cannot leave.", "苏格拉底留下了。": "Socrates 留下了 stayed."})
    untranslated = []
    result = ensure_language_many(
        ["> 我不能离开。", "Clean.", "苏格拉底留下了。", "Crito 说他明天会离开雅典"], "en",
        llm=model, untranslated=untranslated,
    )
    # The model hands the last line back untouched: all that is left of it is a lone name.
    assert result == ["> I cannot leave.", "Clean.", "Socrates stayed.", ""]
    assert untranslated == [2, 3]
    untranslated = []
    ensure_language("> 我不能离开。", "en", llm=model, untranslated=untranslated)
    assert untranslated == []


def test_a_half_translated_line_keeps_what_the_reader_can_read_and_is_not_cached():
    model = FakeTranslator({"苏格拉底留下了。": "Socrates 留下了 stayed."})
    assert ensure_language("苏格拉底留下了。", "en", llm=model) == "Socrates stayed."
    ensure_language("苏格拉底留下了。", "en", llm=model)
    assert len(model.calls) == 2


def test_no_model_at_all_still_returns_no_chinese():
    # The autouse fixture makes the default translator fail.
    assert ensure_language("Crito wept.\n苏格拉底", "en") == "Crito wept."
    assert ensure_language_many(["苏格拉底", "Crito"], "en") == ["", "Crito"]


def test_a_chinese_target_is_never_touched():
    model = FakeTranslator(fail=True)
    text = "> 「苏格拉底在对话中坚定论证。」\nCrito wept，"
    assert ensure_language(text, "zh", llm=model) is text
    assert ensure_language(text, "zh-CN", llm=model) is text
    assert ensure_language_many([text, "English"], "zh", llm=model) == [text, "English"]
    assert model.calls == []


def test_ensure_language_many_uses_one_call_for_every_text():
    model = FakeTranslator({"我不能离开。": "I cannot leave.", "苏格拉底": "Socrates"})
    texts = ["> 我不能离开。", None, "Clean.", "苏格拉底\n- 我不能离开。", 7]
    assert ensure_language_many(texts, "en", llm=model) == [
        "> I cannot leave.", None, "Clean.", "Socrates\n- I cannot leave.", 7,
    ]
    assert len(model.calls) == 1
    assert sorted(model.calls[0]["lines"]) == ["我不能离开。", "苏格拉底"]  # each body once
    assert ensure_language_many([], "en", llm=model) == []


def test_a_very_long_batch_goes_in_parts(monkeypatch):
    monkeypatch.setattr(language_guard, "MAX_LINES_PER_CALL", 2)
    table = {f"第{i}行": f"Line {i}" for i in range(5)}
    model = FakeTranslator(table)
    assert ensure_language("\n".join(table), "en", llm=model) == "\n".join(table.values())
    assert [len(call["lines"]) for call in model.calls] == [2, 2, 1]


def test_the_guard_survives_its_own_failure(monkeypatch):
    def broken(*_args, **_kwargs):
        raise RuntimeError("a bug")

    monkeypatch.setattr(language_guard, "_ensure_many", broken)
    assert ensure_language("Crito wept.\n> 苏格拉底 stayed", "en") == "Crito wept."
    assert ensure_language("Crito wept.\n> The citizens chanted 万岁 at dawn", "en") == (
        "Crito wept.\n> The citizens chanted at dawn"
    )
    untranslated = []
    assert ensure_language_many(["Clean.", "苏格拉底"], "en", untranslated=untranslated) == ["Clean.", ""]
    assert untranslated == [1]


# ---------------------------------------------------------------- to_ascii_punct


@pytest.mark.parametrize("text, expected", [
    ("Socrates，the teacher。He said：“I stay。”", 'Socrates, the teacher. He said: "I stay."'),
    ("「hello」he said", '"hello" he said'),
    ("『inner』", "'inner'"),
    ("word（note）next", "word (note) next"),
    ("【Act I】The Pnyx", "[Act I] The Pnyx"),
    ("《Crito》is a dialogue", '"Crito" is a dialogue'),
    ("2，000 drachmas at 10：30", "2,000 drachmas at 10:30"),
    ("A——B", "A, B"),
    ("wait……", "wait..."),
    ("Why？Because！", "Why? Because!"),
    ("x ； y", "x; y"),
    ("one、two", "one, two"),
    ("don’t", "don't"),
    ("ｆｕｌｌ１２３", "full123"),
    ("a　b", "a b"),
    ("  ，indented", "  , indented"),
    ("end。\nnext", "end.\nnext"),
    ("plain text", "plain text"),
    ("", ""),
])
def test_to_ascii_punct(text, expected):
    assert to_ascii_punct(text) == expected
    assert not CJK_PUNCT_RE.search(to_ascii_punct(text))


# ---------------------------------------------------------------- the ontology


class _OntologyModel:
    def __init__(self, answer):
        self.answer = answer
        self.calls = []

    def chat_json(self, **kwargs):
        self.calls.append(kwargs)
        return json.loads(json.dumps(self.answer))


_CHINESE_ONTOLOGY = {
    "entity_types": [{
        "name": "Philosopher",
        "description": "雅典的哲学家",
        "attributes": [{"name": "school", "type": "text", "description": "学派"}],
        "examples": ["苏格拉底", "Crito"],
    }],
    "edge_types": [{
        "name": "TEACHES",
        "description": "教导",
        "source_targets": [{"source": "Philosopher", "target": "Person"}],
    }],
    "analysis_summary": "这是关于苏格拉底的审判。",
}


def test_the_ontology_prompt_is_english_and_asks_for_the_record_language():
    model = _OntologyModel({"entity_types": [], "edge_types": [], "analysis_summary": "Read."})
    OntologyGenerator(llm_client=model).generate(["A scroll."], "Will Socrates flee?", language="en")
    system = model.calls[0]["messages"][0]["content"]
    user = model.calls[0]["messages"][1]["content"]
    assert not HAN_RE.search(system) and not HAN_RE.search(user)
    assert system.endswith(f"{EN_INSTRUCTION}\n{LANGUAGE_RULE}")

    model.calls.clear()
    OntologyGenerator(llm_client=model).generate(["A scroll."], "苏格拉底会逃走吗？", language="zh-CN")
    assert model.calls[0]["messages"][0]["content"].endswith(f"{ZH_INSTRUCTION}\n{LANGUAGE_RULE}")


def test_the_ontology_language_defaults_to_the_threads_locale():
    model = _OntologyModel({"entity_types": [], "edge_types": [], "analysis_summary": ""})
    OntologyGenerator(llm_client=model).generate(["A scroll."], "Q")
    assert model.calls[0]["messages"][0]["content"].endswith(f"{EN_INSTRUCTION}\n{LANGUAGE_RULE}")
    set_locale("zh")
    OntologyGenerator(llm_client=model).generate(["A scroll."], "Q")
    assert model.calls[1]["messages"][0]["content"].endswith(f"{ZH_INSTRUCTION}\n{LANGUAGE_RULE}")


def test_an_english_ontology_has_no_chinese_left_for_the_hearing():
    translator = FakeTranslator({
        "雅典的哲学家": "A philosopher of Athens",
        "学派": "School",
        "苏格拉底": "Socrates",
        "教导": "Teaches",
        "这是关于苏格拉底的审判。": "This is about the trial of Socrates.",
    })
    ontology = OntologyGenerator(llm_client=_OntologyModel(_CHINESE_ONTOLOGY), translator=translator).generate(
        ["A scroll."], "Will Socrates flee?", language="en"
    )
    assert len(translator.calls) == 1
    philosopher = ontology["entity_types"][0]
    assert philosopher["description"] == "A philosopher of Athens"
    assert philosopher["examples"] == ["Socrates", "Crito"]
    assert philosopher["attributes"][0]["description"] == "School"
    assert ontology["edge_types"][0]["description"] == "Teaches"
    assert ontology["analysis_summary"] == "This is about the trial of Socrates."
    assert not HAN_RE.search(json.dumps(ontology, ensure_ascii=False))


def test_a_translated_description_keeps_the_hundred_character_cap():
    translator = FakeTranslator({"雅典的哲学家": "A philosopher of Athens " * 10})
    ontology = OntologyGenerator(llm_client=_OntologyModel(_CHINESE_ONTOLOGY), translator=translator).generate(
        ["A scroll."], "Will Socrates flee?", language="en"
    )
    description = ontology["entity_types"][0]["description"]
    assert len(description) == 100 and description.endswith("...")


def test_an_english_ontology_without_a_translator_drops_what_it_cannot_translate():
    ontology = OntologyGenerator(llm_client=_OntologyModel(_CHINESE_ONTOLOGY)).generate(
        ["A scroll."], "Will Socrates flee?", language="en"
    )
    assert ontology["entity_types"][0]["examples"] == ["Crito"]
    assert not HAN_RE.search(json.dumps(ontology, ensure_ascii=False))


def test_a_chinese_ontology_stays_chinese():
    translator = FakeTranslator(fail=True)
    ontology = OntologyGenerator(llm_client=_OntologyModel(_CHINESE_ONTOLOGY), translator=translator).generate(
        ["A scroll."], "苏格拉底会逃走吗？", language="zh"
    )
    assert ontology["analysis_summary"] == "这是关于苏格拉底的审判。"
    assert ontology["entity_types"][0]["examples"] == ["苏格拉底", "Crito"]
    assert translator.calls == []
