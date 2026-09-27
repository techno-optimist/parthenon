"""The Chronicle and the Scribe speak one language each.

- A Chronicle is written in its gathering's record language, fixed when it is
  begun and stored in meta.json: not the language of whoever pressed Generate.
- Nothing in another script reaches its record: a chapter quoting a citizen
  in Chinese is translated (quotation included) before it is saved or logged,
  and the whole Chronicle is checked again before it is called complete.
- The Scribe answers a visitor in the visitor's language, translating what
  she quotes; a Chinese visitor, or a Chinese Chronicle, keeps its Chinese.
- The Chronicle routes say which language a Chronicle is in, and put it in
  the city's words in that language, never guessed from its quotations.
- The routes of api/parthenon.py that hand model words to a visitor check
  them for the right language too.

No real model is called: the Scribe and the translator are fakes.
"""

import json
import os
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app import create_app
from app.api import parthenon as parthenon_api
from app.api import report as report_api
from app.config import Config
from app.models.project import ProjectManager, ProjectStatus
from app.services import citizen_portraits, language_guard, symposium_memory
from app.services import report_agent as report_agent_module
from app.services.language_guard import HAN_RE
from app.services.report_agent import (
    CHAT_SYSTEM_PROMPT_TEMPLATE,
    Report,
    ReportAgent,
    ReportManager,
    ReportOutline,
    ReportSection,
    ReportStatus,
    chronicle_language,
)
from app.services.simulation_manager import SimulationManager
from app.services.simulation_runner import RunnerStatus
from app.utils.locale import get_locale, language_instruction_for, set_locale

QUESTION = "Should Athens let Socrates walk free before the sacred ship returns?"
QUOTE_ZH = "苏格拉底在对话中坚定论证，逃跑将违背他一生尊崇的城邦法律"
QUOTE_EN = "In the dialogue Socrates argued firmly that escaping would break the laws he had honoured all his life"
TRANSLATIONS = {QUOTE_ZH: QUOTE_EN, "克力同的计划": "Crito's Plan"}
CHAPTER = f'Crito put it to him plainly, and Socrates answered:\n\n> "{QUOTE_ZH}"\n\nThe city did not move.'
SEARCHES = [
    '<tool_call>{"name": "panorama_search", "parameters": {"query": "escape"}}</tool_call>',
    '<tool_call>{"name": "quick_search", "parameters": {"query": "guards"}}</tool_call>',
    '<tool_call>{"name": "insight_forge", "parameters": {"query": "jurors"}}</tool_call>',
]


class FakeTranslator:
    """A translate-only model that knows a few lines by heart."""

    def __init__(self):
        self.calls = []

    def chat_json(self, messages, temperature=None, max_tokens=None):
        lines = json.loads(messages[-1]["content"])["lines"]
        self.calls.append(lines)
        translated = []
        for line in lines:
            for chinese, english in TRANSLATIONS.items():
                line = line.replace(chinese, english)
            translated.append(line)
        return {"lines": translated}


class ScriptedLLM:
    """The Scribe: an outline, then replies from a list; every conversation is kept."""

    def __init__(self, replies=(), outline=None):
        self.replies = list(replies)
        self.outline = outline
        self.seen = []

    def chat(self, messages, **_kwargs):
        self.seen.append([dict(m) for m in messages])
        return self.replies.pop(0)

    def chat_json(self, messages, **_kwargs):
        self.seen.append([dict(m) for m in messages])
        return self.outline


@pytest.fixture(autouse=True)
def translator(monkeypatch):
    """No configured record language, a fresh translation cache and a fake translator."""

    fake = FakeTranslator()
    language_guard.clear_cache()
    monkeypatch.delenv("PARTHENON_RECORD_LANGUAGE", raising=False)
    monkeypatch.setattr(language_guard, "default_translator", lambda: fake)
    yield fake
    language_guard.clear_cache()


@pytest.fixture
def records(tmp_path, monkeypatch):
    """Projects, simulations and Chronicles in a throwaway folder; gathering(language) makes one."""

    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(tmp_path))
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"))
    monkeypatch.setattr(ProjectManager, "PROJECTS_DIR", str(tmp_path / "projects"))

    def gathering(name, language, requirement=QUESTION):
        project = ProjectManager.create_project(name=name, language=language)
        project.simulation_requirement = requirement
        project.graph_id = f"graph_{name}"
        project.status = ProjectStatus.GRAPH_COMPLETED
        ProjectManager.save_project(project)
        simulation_id = f"sim_{name}"
        folder = os.path.join(SimulationManager.SIMULATION_DATA_DIR, simulation_id)
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "state.json"), "w", encoding="utf-8") as handle:
            json.dump({"simulation_id": simulation_id, "project_id": project.project_id}, handle)
        return project, simulation_id

    return gathering


def make_agent(llm, simulation_id="sim_nowhere", language=None):
    zep = MagicMock()
    zep.get_simulation_context.return_value = {
        "graph_statistics": {"total_nodes": 4, "total_edges": 3, "entity_types": {"Person": 2}},
        "total_entities": 2,
        "related_facts": ["Crito offered to bribe the guards."],
    }
    agent = ReportAgent(
        graph_id="g", simulation_id=simulation_id, simulation_requirement=QUESTION,
        llm_client=llm, zep_tools=zep, language=language,
    )
    agent._execute_tool = MagicMock(return_value=f"Socrates: {QUOTE_ZH}")
    return agent


def write_chronicle(agent, report_id):
    report = agent.generate_report(report_id=report_id)
    folder = ReportManager._get_report_folder(report_id)
    with open(os.path.join(folder, "agent_log.jsonl"), encoding="utf-8") as handle:
        rows = [json.loads(line) for line in handle]
    return report, folder, rows


def scribe(outline_title="The Hemlock Month"):
    return ScriptedLLM(
        [*SEARCHES, f"Final Answer: {CHAPTER}"],
        outline={
            "title": outline_title,
            "summary": "Athens held its verdict.",
            "sections": [{"title": "克力同的计划", "description": "x"}],
        },
    )


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


# ── The Chronicle is written in its record language ──

def test_the_chronicle_takes_its_gatherings_stored_language_not_the_threads(records):
    set_locale("en")  # whoever pressed Generate read in English
    _project, simulation_id = records("zhg", language="zh")

    agent = make_agent(ScriptedLLM(), simulation_id=simulation_id)

    assert agent.language == "zh"


def test_an_english_chronicle_saves_and_logs_no_chinese(records, translator):
    set_locale("zh")  # the thread that runs it may read in Chinese; the record does not
    _project, simulation_id = records("eng", language="en")
    llm = scribe()
    agent = make_agent(llm, simulation_id=simulation_id)

    report, folder, rows = write_chronicle(agent, "report_english00001")

    assert report.status == ReportStatus.COMPLETED and report.language == "en"
    # The prompts asked for English, whatever the thread read in.
    assert llm.seen[0][0]["content"].endswith(language_instruction_for("en"))
    assert llm.seen[1][0]["content"].endswith(language_instruction_for("en"))
    # The quotation was translated, its '>' and its quotation marks kept.
    section = read(os.path.join(folder, "section_01.md"))
    assert f'> "{QUOTE_EN}"' in section
    assert section.startswith("## Crito's Plan\n")
    for name in ("section_01.md", "full_report.md", "meta.json", "outline.json"):
        assert not HAN_RE.search(read(os.path.join(folder, name))), name
    meta = json.loads(read(os.path.join(folder, "meta.json")))
    assert meta["language"] == "en"
    assert f'> "{QUOTE_EN}"' in meta["outline"]["sections"][0]["content"]
    # Every row the pages read the chapter from is English too.
    for action in ("planning_complete", "section_content", "section_complete"):
        found = [row for row in rows if row["action"] == action]
        assert found, action
        assert not HAN_RE.search(json.dumps(found, ensure_ascii=False)), action
    assert [row["action"] for row in rows][-1] == "report_complete"
    # One call for the outline's chapter title and one for the chapter; the rest is clean.
    assert len(translator.calls) == 2


def test_a_chinese_chronicle_keeps_its_chinese(records, translator):
    set_locale("en")
    _project, simulation_id = records("zhc", language="zh")
    llm = scribe()
    agent = make_agent(llm, simulation_id=simulation_id)

    report, folder, rows = write_chronicle(agent, "report_chinese00001")

    assert report.language == "zh"
    assert llm.seen[0][0]["content"].endswith(language_instruction_for("zh"))
    assert QUOTE_ZH in read(os.path.join(folder, "section_01.md"))
    complete = [row for row in rows if row["action"] == "section_complete"][0]
    assert QUOTE_ZH in complete["details"]["content"]
    assert translator.calls == []


def test_the_run_notes_follow_the_record_not_the_thread(records):
    set_locale("zh")
    _project, simulation_id = records("notes", language="en")
    agent = make_agent(scribe(), simulation_id=simulation_id)

    write_chronicle(agent, "report_notes0000001")

    progress = ReportManager.get_progress("report_notes0000001")
    assert progress["status"] == "completed" and not HAN_RE.search(progress["message"])


def test_why_a_chronicle_stopped_is_told_in_its_language(records):
    _project, simulation_id = records("fails", language="en")
    llm = scribe()
    agent = make_agent(llm, simulation_id=simulation_id)
    agent.plan_outline = MagicMock(side_effect=RuntimeError(f"模拟环境未运行: {QUOTE_ZH}"))

    report = agent.generate_report(report_id="report_failed000001")

    assert report.status == ReportStatus.FAILED
    assert not HAN_RE.search(report.error) and QUOTE_EN in report.error
    meta = json.loads(read(os.path.join(ReportManager._get_report_folder("report_failed000001"), "meta.json")))
    assert not HAN_RE.search(meta["error"])


def test_an_older_chronicle_reads_in_its_gatherings_record_language(records, monkeypatch):
    older = Report(
        report_id="report_older0000001", simulation_id="sim_gone", graph_id="g",
        simulation_requirement="苏格拉底应当逃走吗？城邦会怎样看他？", status=ReportStatus.COMPLETED,
    )
    assert older.language is None
    assert chronicle_language(older) == "zh"  # guessed from its question, as its gathering is
    monkeypatch.setenv("PARTHENON_RECORD_LANGUAGE", "en")
    assert chronicle_language(older) == "en"  # the public steps write English
    older.language = "zh"
    assert chronicle_language(older) == "zh"  # what is stored with it stands


def test_the_searches_answer_in_the_language_she_writes_in():
    agent = make_agent(ScriptedLLM(), language="zh")
    del agent._execute_tool  # the real one, over a fake memory
    zep = agent.zep_tools

    agent._execute_tool("interview_citizens", {"interview_topic": "the verdict"})
    agent._execute_tool("search_graph", {"query": "the ship"})  # an older name, redirected
    agent._execute_tool("panorama_search", {"query": "the ship"}, lang="en")  # an answer to a visitor

    assert zep.interview_agents.call_args.kwargs["language"] == "zh"
    assert zep.quick_search.call_args.kwargs["language"] == "zh"
    assert zep.panorama_search.call_args.kwargs["language"] == "en"


# ── A line that does not come back whole is asked for once more ──

class FlakyTranslator(FakeTranslator):
    """Out the first time it is shown each batch of lines, then as FakeTranslator; or out for good."""

    def __init__(self, always=False):
        super().__init__()
        self.always = always
        self.shown = set()

    def chat_json(self, messages, temperature=None, max_tokens=None):
        lines = json.loads(messages[-1]["content"])["lines"]
        if self.always or tuple(lines) not in self.shown:
            self.shown.add(tuple(lines))
            self.calls.append(lines)
            raise RuntimeError("the translator is out")
        return super().chat_json(messages, temperature, max_tokens)


def assert_no_chinese_on_record(folder, rows):
    """Nothing the pages read (the files, the ledger, the log rows they show) holds Chinese."""
    for name in ("section_01.md", "full_report.md", "meta.json", "outline.json", "console_log.txt"):
        assert not HAN_RE.search(read(os.path.join(folder, name))), name
    for action in ("planning_complete", "section_content", "section_complete"):
        found = [row for row in rows if row["action"] == action]
        assert found, action
        assert not HAN_RE.search(json.dumps(found, ensure_ascii=False)), action


def test_a_chronicle_the_translator_fails_once_is_whole_on_the_second_asking(records, monkeypatch):
    flaky = FlakyTranslator()
    monkeypatch.setattr(language_guard, "default_translator", lambda: flaky)
    _project, simulation_id = records("flaky", language="en")

    report, folder, rows = write_chronicle(make_agent(scribe(), simulation_id=simulation_id), "report_flaky000001")

    assert report.status == ReportStatus.COMPLETED
    section = read(os.path.join(folder, "section_01.md"))
    assert section.startswith("## Crito's Plan\n")
    assert f'> "{QUOTE_EN}"' in section
    assert f'> "{QUOTE_EN}"' in read(os.path.join(folder, "full_report.md"))
    complete = [row for row in rows if row["action"] == "section_complete"][0]
    assert f'> "{QUOTE_EN}"' in complete["details"]["content"]
    assert_no_chinese_on_record(folder, rows)
    # The chapter title and the chapter were each asked for twice, the second time
    # with the very lines that failed (none was kept from the failed call).
    assert flaky.calls == [["克力同的计划"], ["克力同的计划"], [f'"{QUOTE_ZH}"'], [f'"{QUOTE_ZH}"']]
    ledger = read(os.path.join(folder, "console_log.txt"))
    assert "asking once more (the outline)" in ledger and "asking once more (chapter 1)" in ledger
    assert "WARNING" not in ledger  # put right on the second asking: nothing for the visitor to hear


def test_a_chronicle_the_translator_never_answers_keeps_no_chinese_and_says_so(records, monkeypatch):
    dead = FlakyTranslator(always=True)
    monkeypatch.setattr(language_guard, "default_translator", lambda: dead)
    _project, simulation_id = records("dead", language="en")
    llm = scribe()
    llm.outline["sections"].append({"title": "The City Waits", "description": "y"})

    report, folder, rows = write_chronicle(make_agent(llm, simulation_id=simulation_id), "report_dead0000001")

    # The Chronicle is still written: what could not be put in English is left out,
    # the chapter whose title could not be read with it.
    assert report.status == ReportStatus.COMPLETED
    assert [section.title for section in report.outline.sections] == ["The City Waits"]
    section = read(os.path.join(folder, "section_01.md"))
    assert section.startswith("## The City Waits\n")
    assert "Crito put it to him plainly, and Socrates answered:" in section
    assert "The city did not move." in section
    assert QUOTE_EN not in section
    assert_no_chinese_on_record(folder, rows)
    complete = [row for row in rows if row["action"] == "section_complete"][0]
    assert "The city did not move." in complete["details"]["content"]
    # Asked twice at each point, never a third time.
    assert dead.calls == [["克力同的计划"], ["克力同的计划"], [f'"{QUOTE_ZH}"'], [f'"{QUOTE_ZH}"']]
    # The owner is told, in the ledger, in English.
    ledger = read(os.path.join(folder, "console_log.txt"))
    assert "WARNING: 1 line(s) could not be put in English after a second try" in ledger
    assert "(the outline)" in ledger and "(chapter 1)" in ledger


def test_an_outline_with_nothing_left_of_its_titles_is_the_plain_one(monkeypatch):
    dead = FlakyTranslator(always=True)
    monkeypatch.setattr(language_guard, "default_translator", lambda: dead)
    agent = make_agent(scribe(outline_title="毒芹之月"), language="en")

    outline = agent.plan_outline()

    assert outline.title == "The Chronicle"
    assert outline.summary == "Athens held its verdict."
    assert [section.title for section in outline.sections] == [
        "The Question and What the City Found", "How the Citizens Moved", "What Is Still Unsettled",
    ]
    assert len(dead.calls) == 2  # asked once more, never a third time


def test_only_the_lines_that_did_not_come_back_whole_are_asked_for_again(monkeypatch):
    class HalfTranslator(FakeTranslator):
        """Leaves the quotation in Chinese the first time it is shown it."""

        def __init__(self):
            super().__init__()
            self.balked = False

        def chat_json(self, messages, temperature=None, max_tokens=None):
            lines = json.loads(messages[-1]["content"])["lines"]
            if self.balked or f'"{QUOTE_ZH}"' not in lines:
                return super().chat_json(messages, temperature, max_tokens)
            self.balked = True
            self.calls.append(lines)
            return {"lines": [line if QUOTE_ZH in line else TRANSLATIONS.get(line, line) for line in lines]}

    half = HalfTranslator()
    monkeypatch.setattr(language_guard, "default_translator", lambda: half)
    agent = make_agent(ScriptedLLM(), language="en")
    chapter = f'## 克力同的计划\n\nCrito asked, and Socrates said:\n\n> "{QUOTE_ZH}"\n\nThe city did not move.'

    checked = agent._in_record_language([chapter, "Athens held.", None], "chapter 1")

    assert checked == [
        f"## Crito's Plan\n\nCrito asked, and Socrates said:\n\n> \"{QUOTE_EN}\"\n\nThe city did not move.",
        "Athens held.",
        None,
    ]
    # The title came back whole the first time: only the quotation was asked for again.
    assert half.calls == [["克力同的计划", f'"{QUOTE_ZH}"'], [f'"{QUOTE_ZH}"']]


def test_a_chinese_chronicle_is_never_asked_for_again(monkeypatch):
    dead = FlakyTranslator(always=True)
    monkeypatch.setattr(language_guard, "default_translator", lambda: dead)
    agent = make_agent(ScriptedLLM(), language="zh")

    assert agent._in_record_language([CHAPTER], "chapter 1") == [CHAPTER]
    assert dead.calls == []


# ── A citizen is named in the language of the text that names them ──

HOST_ZH, HOST_EN = "克法洛斯", "Cephalus"


def enroll(simulation_id, citizens):
    """The gathering's roll: [(handle, name)], as the profile files hold it."""
    folder = os.path.join(SimulationManager.SIMULATION_DATA_DIR, simulation_id)
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "reddit_profiles.json"), "w", encoding="utf-8") as handle:
        json.dump([{"username": u, "name": n} for u, n in citizens], handle, ensure_ascii=False)


def test_an_english_chronicle_names_a_citizen_on_a_chinese_roll_in_english(records, translator, monkeypatch):
    monkeypatch.setitem(TRANSLATIONS, HOST_ZH, HOST_EN)
    _project, simulation_id = records("roll", language="en")
    enroll(simulation_id, [("old_host_7", HOST_ZH)])
    first = "@old_host_7 argued that the ship should wait, and the city listened to him for a long while."
    second = "As old_host_7 had said at the start, the city waited for the ship, and nobody left the agora."
    llm = ScriptedLLM(
        [*SEARCHES, f"Final Answer: {first}", *SEARCHES, f"Final Answer: {second}"],
        outline={
            "title": "What @old_host_7 told Athens",
            "summary": "Athens heard @old_host_7 out.",
            "sections": [
                {"title": "The words of @old_host_7", "description": "x"},
                {"title": "The City Waits", "description": "y"},
            ],
        },
    )

    report, folder, rows = write_chronicle(make_agent(llm, simulation_id=simulation_id), "report_roll0000001")

    assert report.status == ReportStatus.COMPLETED
    outline = json.loads(read(os.path.join(folder, "outline.json")))
    assert outline["title"] == "What Cephalus told Athens"
    assert outline["summary"] == "Athens heard Cephalus out."
    assert [section["title"] for section in outline["sections"]] == ["The words of Cephalus", "The City Waits"]
    assert read(os.path.join(folder, "section_01.md")).startswith("## The words of Cephalus\n")
    planned = [row for row in rows if row["action"] == "planning_complete"]
    assert "What Cephalus told Athens" in json.dumps(planned)
    content = [row["details"]["content"] for row in rows if row["action"] == "section_content"]
    assert content[0].startswith("Cephalus argued that the ship should wait")
    assert content[1].startswith("As Cephalus had said at the start")
    assert_no_chinese_on_record(folder, rows)
    # The roll was put in English once, for the outline and both chapters; nothing else was asked.
    assert translator.calls == [[HOST_ZH]]


def test_a_citizen_the_translator_cannot_name_is_called_by_their_handle(translator):
    agent = make_agent(ScriptedLLM(), language="en")
    agent._city = {"roster": {"li_wei_12": "李伟", "li_wei": "李伟"}, "time_unit": None}

    first = agent._in_record(["@li_wei_12 argued that the ship should wait; li_wei_12 was heard."], "chapter 1")
    second = agent._in_record(["The city listened to @li_wei."], "chapter 2")

    # The subject is kept, never stripped with the name that could not be read.
    assert first == ["Li Wei argued that the ship should wait; Li Wei was heard."]
    assert second == ["The city listened to Li Wei."]
    assert translator.calls == [["李伟"]]  # asked once for the Chronicle, not again in each chapter


def test_an_answer_names_the_citizen_in_the_visitors_language(translator, monkeypatch):
    monkeypatch.setitem(TRANSLATIONS, HOST_ZH, HOST_EN)
    agent = make_agent(ScriptedLLM(), language="zh")
    agent._city = {"roster": {"old_host_7": HOST_ZH}, "time_unit": None}

    english = agent._checked_answer(
        "Final Answer: @old_host_7 said the ship should wait, and many agreed with him.", [], lang="en",
    )
    chinese = agent._checked_answer("Final Answer: @old_host_7 说船应该等一等，很多人同意他的看法。", [], lang="zh")

    assert english == "Cephalus said the ship should wait, and many agreed with him."
    assert chinese == f"{HOST_ZH} 说船应该等一等，很多人同意他的看法。"
    assert translator.calls == [[HOST_ZH]]


def test_the_symposium_reads_and_answers_with_the_chronicles_names(translator, monkeypatch):
    monkeypatch.setitem(TRANSLATIONS, HOST_ZH, HOST_EN)
    report = Report(
        report_id="report_rollchat0001", simulation_id="sim_nowhere", graph_id="g",
        simulation_requirement=QUESTION, status=ReportStatus.COMPLETED,
        markdown_content="# The Hemlock Month\n\n@old_host_7 asked the city to wait.", language="en",
    )
    monkeypatch.setattr(ReportManager, "get_report_by_simulation", classmethod(lambda _cls, _sid: report))
    llm = ScriptedLLM(["@old_host_7 asked the city to wait for the ship, and the city did wait."])
    agent = make_agent(llm)
    agent._city = {"roster": {"old_host_7": HOST_ZH}, "time_unit": None}

    result = agent.chat("Who asked the city to wait?", lang="en")

    assert "Cephalus asked the city to wait." in llm.seen[0][0]["content"]
    assert result["response"] == "Cephalus asked the city to wait for the ship, and the city did wait."
    assert translator.calls == [[HOST_ZH]]


def test_a_chinese_chronicle_keeps_its_citizens_chinese_names(translator):
    agent = make_agent(ScriptedLLM(), language="zh")
    agent._city = {"roster": {"old_host_7": HOST_ZH}, "time_unit": None}

    assert agent._in_record(["@old_host_7 认为船应该等一等。"], "chapter 1") == [f"{HOST_ZH} 认为船应该等一等。"]
    assert translator.calls == []


def test_whatever_the_voice_brings_in_another_script_is_checked_once_more(translator, monkeypatch):
    # A roll the Scribe could not put in English (here, not put in it at all): the check
    # still has the last word on what goes on record and what the visitor reads.
    monkeypatch.setitem(TRANSLATIONS, HOST_ZH, HOST_EN)
    monkeypatch.setattr(report_agent_module, "roster_in", lambda roster, _lang: dict(roster or {}))
    agent = make_agent(ScriptedLLM(), language="en")
    agent._city = {"roster": {"old_host_7": HOST_ZH}, "time_unit": None}

    assert agent._in_record(["@old_host_7 argued that the ship should wait."], "chapter 1") == [
        "Cephalus argued that the ship should wait."
    ]
    assert agent._in_answer("@old_host_7 said the ship should wait.", "en") == "Cephalus said the ship should wait."


# ── The Scribe answers the visitor in the visitor's language ──

def test_the_chat_prompt_asks_for_quotations_in_the_visitors_language():
    assert "translate what you quote into that language" in CHAT_SYSTEM_PROMPT_TEMPLATE


@pytest.fixture
def chinese_chronicle(monkeypatch):
    report = Report(
        report_id="report_zhchronicle1", simulation_id="sim_nowhere", graph_id="g",
        simulation_requirement=QUESTION, status=ReportStatus.COMPLETED,
        markdown_content=f"# 毒芹之月\n\n> {QUOTE_ZH}", language="zh",
    )
    monkeypatch.setattr(ReportManager, "get_report_by_simulation", classmethod(lambda _cls, _sid: report))
    return report


def test_an_english_visitor_gets_an_english_answer(chinese_chronicle, translator):
    set_locale("zh")
    llm = ScriptedLLM([f'Socrates would not go. He said:\n\n> "{QUOTE_ZH}"'])

    result = make_agent(llm).chat("Why did Socrates stay?", lang="en")

    assert result["response"] == f'Socrates would not go. He said:\n\n> "{QUOTE_EN}"'
    system = llm.seen[0][0]["content"]
    assert QUOTE_ZH in system  # she reads the Chronicle as it is written
    assert system.endswith(language_instruction_for("en"))
    assert len(translator.calls) == 1


def test_a_chinese_visitor_keeps_the_chinese(chinese_chronicle, translator):
    llm = ScriptedLLM([f"苏格拉底没有走。\n\n> {QUOTE_ZH}"])

    result = make_agent(llm).chat("苏格拉底为什么留下？", lang="zh")

    assert QUOTE_ZH in result["response"]
    assert llm.seen[0][0]["content"].endswith(language_instruction_for("zh"))
    assert translator.calls == []


def test_the_visitors_language_defaults_to_their_request(chinese_chronicle):
    set_locale("zh")
    llm = ScriptedLLM(["He stayed."])
    app = create_app()
    with app.test_request_context(headers={"Accept-Language": "en-US,en;q=0.9"}):
        assert get_locale() == "en"
        make_agent(llm).chat("Why?")
    assert llm.seen[0][0]["content"].endswith(language_instruction_for("en"))


def test_an_answer_the_scribe_cannot_give_is_said_in_the_visitors_language(chinese_chronicle):
    set_locale("zh")
    llm = ScriptedLLM(["", ""])

    answer = make_agent(llm).chat("Why?", lang="en")["response"]

    assert answer and not HAN_RE.search(answer)


# ── The report routes ──

@pytest.fixture
def client(records):
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def _save(report_id, markdown, language=None, simulation_id="sim_nowhere", question=QUESTION):
    report = Report(
        report_id=report_id, simulation_id=simulation_id, graph_id="g",
        simulation_requirement=question, status=ReportStatus.COMPLETED,
        outline=ReportOutline(title="The Hemlock Month", summary="Athens held.",
                              sections=[ReportSection(title="The Plan", content=markdown)]),
        markdown_content=markdown, created_at="2026-09-27T10:00:00", language=language,
    )
    ReportManager.save_report(report)
    ReportManager.save_section(report_id, 1, report.outline.sections[0])
    return report


def test_the_report_routes_say_which_language_the_chronicle_is_in(client):
    _save("report_withlang0001", "Athens held.", language="zh")
    _save("report_nolang000001", "Athens held.")  # begun before languages were stored

    assert client.get("/api/report/report_withlang0001").get_json()["data"]["language"] == "zh"
    assert client.get("/api/report/report_nolang000001").get_json()["data"]["language"] == "en"
    listed = {r["report_id"]: r["language"] for r in client.get("/api/report/list").get_json()["data"]}
    assert listed == {"report_withlang0001": "zh", "report_nolang000001": "en"}
    sections = client.get("/api/report/report_withlang0001/sections").get_json()["data"]
    assert sections["language"] == "zh"


def test_an_english_chronicle_quoting_chinese_is_served_in_english_city_words(client):
    # Mostly Chinese by its letters, but the Chinese is all quotation: the prose is English.
    markdown = f"On Twitter, the simulated agents argued.\n\n> {QUOTE_ZH}{QUOTE_ZH}{QUOTE_ZH}"
    _save("report_quoting00001", markdown, language="en")

    data = client.get("/api/report/report_quoting00001").get_json()["data"]
    assert data["markdown_content"].startswith("In the Agora, the citizens argued.")
    section = client.get("/api/report/report_quoting00001/section/1").get_json()["data"]["content"]
    assert "In the Agora, the citizens argued." in section and "广场" not in section
    # Even without a stored language the quotations do not decide it.
    _save("report_quotingold01", markdown)
    assert client.get("/api/report/report_quotingold01").get_json()["data"]["markdown_content"].startswith(
        "In the Agora, the citizens argued."
    )


def test_the_chat_route_answers_in_the_visitors_language(client, records, monkeypatch):
    _project, simulation_id = records("chat", language="zh")
    seen = {}

    def chat(self, message, chat_history=None, lang=None):
        seen.update(lang=lang, record=self.language)
        return {"response": "ok", "tool_calls": [], "sources": []}

    monkeypatch.setattr(report_api.ReportAgent, "chat", chat)

    body = {"simulation_id": simulation_id, "message": "Why?"}
    assert client.post("/api/report/chat", json=body, headers={"Accept-Language": "en-US"}).status_code == 200
    assert seen == {"lang": "en", "record": "zh"}
    client.post("/api/report/chat", json={**body, "lang": "zh-CN"}, headers={"Accept-Language": "en"})
    assert seen["lang"] == "zh"


def test_generate_writes_in_the_record_language_not_the_requests(client, records, monkeypatch):
    project, simulation_id = records("gen", language="zh")
    monkeypatch.setattr(report_api.SimulationRunner, "get_run_state",
                        staticmethod(lambda _sid: SimpleNamespace(runner_status=RunnerStatus.COMPLETED)))
    monkeypatch.setattr(report_api.ZepGraphMemoryManager, "get_updater", staticmethod(lambda _sid: None))
    monkeypatch.setattr(report_api.ReportManager, "get_report_by_simulation",
                        classmethod(lambda _cls, _sid: None))
    started = threading.Event()
    seen = {}

    class Agent:
        def __init__(self, **kwargs):
            seen["language"] = kwargs.get("language")

        def generate_report(self, progress_callback=None, report_id=None):
            seen["thread_locale"] = get_locale()
            started.set()
            return SimpleNamespace(status=ReportStatus.FAILED, error=None, report_id=report_id)

    monkeypatch.setattr(report_api, "ReportAgent", Agent)
    monkeypatch.setattr(report_api.ReportManager, "save_report", classmethod(lambda _cls, _report: None))

    response = client.post("/api/report/generate", json={"simulation_id": simulation_id},
                           headers={"Accept-Language": "en"})

    assert response.status_code == 200, response.get_json()
    assert started.wait(10)
    assert seen == {"language": "zh", "thread_locale": "zh"}
    task_id = response.get_json()["data"]["task_id"]
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        task = client.post("/api/report/generate/status", json={"task_id": task_id}).get_json()["data"]
        if task["status"] == "failed":
            break
        time.sleep(0.05)
    # The task's own words are for the one watching it, in their language.
    assert task["status"] == "failed" and not HAN_RE.search(task.get("error") or "")


# ── What api/parthenon.py hands a visitor ──

def test_the_status_names_the_configured_record_language(client, monkeypatch):
    monkeypatch.setattr(parthenon_api, "_zep_key_status", lambda: (True, None))
    monkeypatch.setattr(parthenon_api, "_llm_status_and_health", lambda: (True, None, None))
    assert client.get("/api/parthenon/status").get_json()["data"]["recordLanguage"] is None
    monkeypatch.setenv("PARTHENON_RECORD_LANGUAGE", "en")
    assert client.get("/api/parthenon/status").get_json()["data"]["recordLanguage"] == "en"


def test_a_film_is_made_in_the_chronicles_language_whoever_asks(client, monkeypatch):
    _save("report_filmlang0001", "Athens held.", language="en")
    seen = {}
    monkeypatch.setattr(parthenon_api.chronicle_film, "start_film",
                        lambda report, **kwargs: seen.update(kwargs))

    response = client.post("/api/parthenon/chronicle/report_filmlang0001/film", json={},
                           headers={"Accept-Language": "zh-CN"})

    assert response.status_code == 202
    assert seen["locale"] == "en"


DRAFT_ZH = {
    "title": "克力同的计划", "question": f"{QUOTE_ZH}?", "happensNext": None,
    "speakers": [{"name": "Crito", "words": QUOTE_ZH}],
    "audience": [{"name": "Phaedo", "description": "A young friend."}],
    "filled": ["title", "question", "words", "audience"],
}


def test_a_drafted_stage_is_in_the_visitors_language(translator, monkeypatch):
    # The public steps keep English records, but the draft is the visitor's
    # to read and edit: a Chinese visitor keeps the Oracle's Chinese, and no
    # translate call is spent on it.
    monkeypatch.setenv("PARTHENON_RECORD_LANGUAGE", "en")
    app = create_app()
    with app.test_request_context(headers={"Accept-Language": "zh-CN"}):
        assert parthenon_api.draft_in_visitor_language(DRAFT_ZH) == DRAFT_ZH
    assert translator.calls == []

    # An English visitor never reads a slip into Chinese, whatever the record keeps.
    monkeypatch.setenv("PARTHENON_RECORD_LANGUAGE", "zh")
    with app.test_request_context(headers={"Accept-Language": "en-US,en;q=0.9"}):
        drafted = parthenon_api.draft_in_visitor_language(DRAFT_ZH)
    assert drafted["title"] == "Crito's Plan"
    assert drafted["speakers"] == [{"name": "Crito", "words": QUOTE_EN}]
    assert drafted["question"] == f"{QUOTE_EN}?"
    assert drafted["audience"] == DRAFT_ZH["audience"]
    assert DRAFT_ZH["title"] == "克力同的计划"  # the Oracle's own answer is left as it was
    assert len(translator.calls) == 1


def test_the_draft_route_answers_a_chinese_visitor_in_chinese(client, translator, monkeypatch):
    monkeypatch.setenv("PARTHENON_RECORD_LANGUAGE", "en")
    oracle = MagicMock()
    oracle.draft.return_value = DRAFT_ZH
    monkeypatch.setattr(parthenon_api, "StageOracle", lambda: oracle)

    answered = client.post("/api/parthenon/stage/draft", json={"stage": {}},
                           headers={"Accept-Language": "zh-CN"})

    assert answered.status_code == 200
    assert answered.get_json()["data"] == DRAFT_ZH
    assert translator.calls == []


def test_a_turn_quoting_chinese_is_read_in_the_gatherings_language(translator):
    citizens = [
        {"agent_id": 1, "turn": f'He turned when Socrates said "{QUOTE_ZH}".'},
        {"agent_id": 2, "turn": "He held."},
        "not a citizen",
    ]
    checked = parthenon_api.turns_in_language(citizens, "en")
    assert checked[0]["turn"] == f'He turned when Socrates said "{QUOTE_EN}".'
    assert checked[1] is citizens[1] and checked[2] == "not a citizen"
    assert parthenon_api.turns_in_language(citizens, "zh") is citizens


def test_the_one_who_had_the_floor_answers_in_the_visitors_language(client, monkeypatch):
    answer = {"answer": f'I said it then:\n\n> "{QUOTE_ZH}"', "lang": "en", "speaker": {"name": "Socrates"}}
    monkeypatch.setattr(symposium_memory, "answer_as_speaker", lambda *args, **kwargs: dict(answer))

    data = client.post("/api/parthenon/gathering/sim_x/speaker", json={"question": "Why?", "lang": "en"}).get_json()

    assert data["data"]["answer"] == f'I said it then:\n\n> "{QUOTE_EN}"'


def test_the_voice_speaks_in_the_language_the_visitor_reads(client, monkeypatch):
    spoken = []

    def speak(text, **kwargs):
        spoken.append((text, kwargs.get("lang")))
        return {"file": "a.mp3", "voice": "scribe", "voice_id": "eve", "language": kwargs.get("lang"),
                "part": 0, "parts": 1, "cached": True, "truncated": False}

    monkeypatch.setattr(citizen_portraits, "speak", speak)

    client.post("/api/parthenon/voice", json={"text": f"He said: {QUOTE_ZH}", "lang": "en"})
    client.post("/api/parthenon/voice", json={"text": f"他说：{QUOTE_ZH}", "lang": "zh"})

    assert spoken == [(f"He said: {QUOTE_EN}", "en"), (f"他说：{QUOTE_ZH}", "zh")]


def test_an_answer_that_only_promises_a_search_is_asked_for_again(monkeypatch):
    """Seen live: 'The Chronicle records the plan ... I will ask the city.' and no search made."""

    report = Report(
        report_id="report_promise0001", simulation_id="sim_nowhere", graph_id="g",
        simulation_requirement=QUESTION, status=ReportStatus.COMPLETED,
        markdown_content="# The Hemlock Month\n\nCrito offered to bribe the guards.", language="en",
    )
    monkeypatch.setattr(ReportManager, "get_report_by_simulation", classmethod(lambda _cls, _sid: report))
    llm = ScriptedLLM([
        "The Chronicle records the plan and its rejection, but not two citizens by name. I will ask the city.",
        "Crito offered to bribe the guards, and Socrates refused: he would not break the laws that raised him.",
    ])
    agent = make_agent(llm)

    result = agent.chat("What did the citizens say about Crito's plan?", lang="en")

    assert result["response"] == (
        "Crito offered to bribe the guards, and Socrates refused: he would not break the laws that raised him."
    )
    assert len(llm.seen) == 2


@pytest.mark.parametrize("answer, promise", [
    ("The Chronicle is thin here. I will ask the city.", True),
    ("Let me search the record for Crito's words", True),
    ("I'll look into what the potters said.", True),
    ("Crito wept, and said he would ask the guards again.", False),
    ("I will ask the city, I said to Crito, and then Socrates laughed at me for it, as he always did.", False),
])
def test_what_counts_as_a_promised_search(answer, promise):
    # Refused either as a promise or, when it opens with one, as planning.
    assert (report_agent_module._answer_problem(answer) is not None) is promise
