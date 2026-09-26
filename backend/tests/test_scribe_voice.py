"""The Scribe of Athens writes in the city's words.

Three things are held here:
- every prompt the Scribe is given (outline, chapter, Symposium) is hers and
  carries none of the machine's words, since a model echoes what it is told;
- scribe_voice(), the backstop on what she hands back, rewrites only the safe
  mechanical cases, never touches a citizen's quoted words except for tags
  and handles, and reports whatever else it finds;
- the chapter, outline and Symposium paths all run through it.
"""

import json
import logging
import os
import re
from unittest.mock import MagicMock

import pytest

from app.config import Config
from app.services import report_agent as ra
from app.services.report_agent import (
    ReportAgent,
    ReportManager,
    ReportOutline,
    ReportSection,
    SCRIBE_BANNED,
    observation_in_city_words,
    scribe_voice,
)
from app.utils.locale import get_language_instruction, set_locale

QUESTION = "Should Athens let Socrates walk free before the sacred ship returns?"
ROSTER = {"crito_719": "Crito", "citizenjury_688": "CitizenJury"}

# The machine's words, as the prompts must never say them. Stricter than
# SCRIBE_BANNED: here even "report" and "round" as bare words are out.
PROMPT_BANNED = [pattern for _term, pattern in SCRIBE_BANNED] + [
    re.compile(r'report', re.I),
    re.compile(r'(?<![a-z])rounds?(?![a-z])', re.I),
    re.compile(r'predict|forecast', re.I),
    re.compile(r'agent', re.I),
    re.compile(r'simulat', re.I),
    re.compile(r'platform', re.I),
    re.compile(r'(?<![a-z])users?(?![a-z])', re.I),
    re.compile(r'posts? on', re.I),
    re.compile(r'oasis|zep|grok|openai', re.I),
    re.compile(r'/api/'),
    re.compile('\\u2014'),  # the em-dash
]


def banned_in(text):
    return sorted({m.group(0) for pattern in PROMPT_BANNED for m in pattern.finditer(text)})


class ScriptedLLM:
    """Replies from a list, recording every conversation it was shown."""

    def __init__(self, replies=(), outline=None):
        self.replies = list(replies)
        self.outline = outline
        self.seen = []

    def chat(self, messages, **_kwargs):
        self.seen.append([dict(m) for m in messages])
        return self.replies.pop(0)

    def chat_json(self, messages, **_kwargs):
        self.seen.append([dict(m) for m in messages])
        if isinstance(self.outline, Exception):
            raise self.outline
        return self.outline


def make_agent(llm, simulation_id="s", question=QUESTION):
    zep = MagicMock()
    zep.get_simulation_context.return_value = {
        "graph_statistics": {"total_nodes": 40, "total_edges": 90, "entity_types": {"Person": 18}},
        "total_entities": 18,
        "related_facts": ["Crito offered to bribe the guards."],
    }
    agent = ReportAgent(
        graph_id="g",
        simulation_id=simulation_id,
        simulation_requirement=question,
        llm_client=llm,
        zep_tools=zep,
    )
    agent.report_logger = None
    agent._execute_tool = MagicMock(return_value="Crito: the guards are paid and the ship is close.")
    return agent


def write_section(agent, title="The Friends Grow Desperate"):
    outline = ReportOutline(title="The Hemlock Month", summary="Athens holds its verdict.",
                            sections=[ReportSection(title=title)])
    return agent._generate_section_react(outline.sections[0], outline, previous_sections=[])


SEARCHES = [
    '<tool_call>{"name": "panorama_search", "parameters": {"query": "escape"}}</tool_call>',
    '<tool_call>{"name": "quick_search", "parameters": {"query": "guards"}}</tool_call>',
    '<tool_call>{"name": "insight_forge", "parameters": {"query": "jurors"}}</tool_call>',
]


def without_data(text, *data):
    """The instructions alone: drop the question, the notes and the language line."""
    for piece in (get_language_instruction(), *data):
        if piece:
            text = text.replace(piece, "")
    return text


# ── The prompts are the Scribe's ──

def _instruction_constants():
    placeholder = re.compile(r'\{[a-z_]+\}')
    names = [
        "SCRIBE_WORDS", "PLAN_SYSTEM_PROMPT", "PLAN_USER_PROMPT_TEMPLATE",
        "SECTION_SYSTEM_PROMPT_TEMPLATE", "SECTION_USER_PROMPT_TEMPLATE", "FIRST_CHAPTER_NOTE",
        "REACT_OBSERVATION_TEMPLATE", "REACT_INSUFFICIENT_TOOLS_MSG", "REACT_INSUFFICIENT_TOOLS_MSG_ALT",
        "REACT_UNSEARCHED_HINT", "REACT_CONFLICT_MSG", "REACT_EMPTY_REPLY", "REACT_GO_ON_MSG",
        "REACT_TOOL_CALL_EXAMPLE", "REACT_WRITE_NOW_MSG", "REACT_TOOL_LIMIT_MSG",
        "REACT_UNUSED_TOOLS_HINT", "REACT_FORCE_FINAL_MSG",
        "CHAT_SYSTEM_PROMPT_TEMPLATE", "CHAT_NO_CHRONICLE", "CHAT_CHRONICLE_CUT",
        "CHAT_OBSERVATION_TEMPLATE", "CHAT_OBSERVATION_SUFFIX",
        "TOOL_DESC_INSIGHT_FORGE", "TOOL_DESC_PANORAMA_SEARCH", "TOOL_DESC_QUICK_SEARCH",
        "TOOL_DESC_INTERVIEW_AGENTS",
    ]
    return [(name, placeholder.sub("", getattr(ra, name))) for name in names]


@pytest.mark.parametrize(("name", "text"), _instruction_constants())
def test_no_instruction_carries_the_machines_words(name, text):
    assert banned_in(text) == [], name
    # The instructions are English now; the language line decides the Chronicle's.
    assert not re.search(r'[\u3400-\u9fff]', text), name


@pytest.mark.parametrize(("locale", "glossary"), [("zh", True), ("en", False)])
def test_a_chinese_chronicle_is_given_the_citys_chinese_names(locale, glossary):
    set_locale(locale)
    llm = ScriptedLLM(outline={"title": "T", "summary": "S", "sections": []})
    make_agent(llm).plan_outline()

    system = llm.seen[0][0]["content"]
    assert (ra.SCRIBE_WORDS_ZH in system) is glossary
    assert system.endswith(get_language_instruction())
    assert banned_in(ra.SCRIBE_WORDS_ZH) == []


def test_the_search_descriptions_carry_none_either():
    agent = make_agent(ScriptedLLM())
    described = agent._get_tools_description()

    assert banned_in(described) == []
    assert "interview_citizens" in described
    for name in ("insight_forge", "panorama_search", "quick_search"):
        assert name in described


def test_the_outline_prompt_is_the_scribes():
    llm = ScriptedLLM(outline={
        "title": "The Hemlock Month",
        "summary": "Athens held its verdict.",
        "sections": [{"title": "The Verdict Holds", "description": "x"}],
    })
    make_agent(llm).plan_outline()

    system, user = llm.seen[0][0]["content"], llm.seen[0][1]["content"]
    assert system.startswith("You are the Scribe of Athens.")
    assert ra.SCRIBE_WORDS in system
    assert system.endswith(get_language_instruction())
    facts = json.dumps(["Crito offered to bribe the guards."], ensure_ascii=False, indent=2)
    assert banned_in(without_data(system)) == []
    assert banned_in(without_data(user, QUESTION, facts, "['Person']")) == []


def test_every_message_in_a_chapter_is_the_scribes():
    llm = ScriptedLLM([
        "I'll look at the escape plan first.",  # a stall, answered with a ready block
        *SEARCHES,
        "Final Answer: Crito's plan found listeners, not helpers.",
    ])
    agent = make_agent(llm)

    write_section(agent)

    system = llm.seen[0][0]["content"]
    assert system.startswith("You are the Scribe of Athens, writing one chapter of the Chronicle.")
    assert ra.SCRIBE_WORDS in system
    assert system.endswith(get_language_instruction())
    notes = "Crito: the guards are paid and the ship is close."
    ours = [m["content"] for m in llm.seen[-1] if m["role"] in ("system", "user")]
    assert len(ours) >= 5
    for content in ours:
        assert banned_in(without_data(content, QUESTION, notes, "The Hemlock Month", "Athens holds its verdict.")) == []


def test_the_symposium_prompt_is_the_scribes(monkeypatch):
    monkeypatch.setattr(ReportManager, "get_report_by_simulation", classmethod(lambda _cls, _sid: None))
    llm = ScriptedLLM(["The city kept its verdict."])

    make_agent(llm).chat("Did Athens change its mind?")

    system = llm.seen[0][0]["content"]
    assert system.startswith("You are the Scribe of Athens, seated at the head of the Symposium.")
    assert ra.SCRIBE_WORDS in system
    assert ra.CHAT_NO_CHRONICLE in system
    assert banned_in(without_data(system, QUESTION)) == []


# ── The backstop: the safe rewrites ──

@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Interviews with simulated agents confirm it.", "Interviews with citizens confirm it."),
        ("The simulated agents largely agree.", "The citizens largely agree."),
        ("A simulated user spoke.", "A citizen spoke."),
        ("Twitter lit up at dusk.", "The Agora lit up at dusk."),
        ("The quarrel moved to Twitter.", "The quarrel moved to the Agora."),
        ("Anytus spoke on Twitter and in Reddit.", "Anytus spoke in the Agora and in the Stoa."),
        ("Reddit's regulars were unmoved.", "The Stoa's regulars were unmoved."),
        ("Twitter users split.", "Citizens in the Agora split."),
        ("The Twitter crowd jeered.", "The Agora crowd jeered."),
        ("Both camps met on both platforms.", "Both camps met in the Agora and the Stoa."),
        ("It spread on the simulated platforms.", "It spread in the Agora and the Stoa."),
        ("Anger grew on social media.", "Anger grew in the Agora and the Stoa."),
        ("The simulated Athens fractures.", "Athens fractures."),
        ("In the simulated month, Crito moved.", "In the month, Crito moved."),
        ("Overall, the simulation shows a hardening.", "Overall, the argument shows a hardening."),
        ("In this report, the city holds.", "In this Chronicle, the city holds."),
        ("Multiple interviewed agents agree.", "Multiple interviewed citizens agree."),
        ("Agents across roles describe caution.", "Citizens across roles describe caution."),
        ("A simulated uprising fails.", "An uprising fails."),
    ],
)
def test_the_safe_mechanical_cases_are_rewritten(text, expected):
    assert scribe_voice(text)[0] == expected


def test_numbered_rounds_become_hours_only_where_the_unit_is_hours():
    text = "By round 12 the square was full, and after 17 rounds it emptied."

    assert scribe_voice(text, time_unit="hour")[0] == "By hour 12 the square was full, and after 17 hours it emptied."
    assert scribe_voice(text, time_unit="day")[0] == "By day 12 the square was full, and after 17 days it emptied."

    unchanged, notes = scribe_voice(text)  # a length the city does not name: left, and logged
    assert unchanged == text
    assert [n["term"] for n in notes if n["kind"] == "left"] == ["round", "round"]


def test_a_round_that_belongs_to_the_story_stays():
    text = "Round 2 of the talks failed at hour 3."
    assert scribe_voice(text, time_unit="hour")[0] == text


def test_hashtags_become_plain_words_everywhere():
    text = 'Meletus wrote:\n\n> "Let the ship come home. #ImpietyPunished"\n\nThe cry #CleanseTheCity spread.'
    voiced, _ = scribe_voice(text)

    assert voiced == (
        'Meletus wrote:\n\n> "Let the ship come home. Impiety Punished"\n\n'
        'The cry Cleanse The City spread.'
    )


def test_handles_become_names_everywhere():
    text = 'Plato answered @crito_719 and "@citizenjury_688 is wrong," said @anytus_779.'
    voiced, _ = scribe_voice(text, roster=ROSTER)

    assert voiced == 'Plato answered Crito and "CitizenJury is wrong," said Anytus.'


def test_a_bare_username_is_a_handle_too():
    assert scribe_voice("As crito_719 put it, the guards are paid.", roster=ROSTER)[0] == (
        "As Crito put it, the guards are paid."
    )


def test_what_is_not_a_tag_or_handle_stays():
    text = "Write to x@y.com, see https://x.com/#tag or twitter.com/athens, the #1 worry, and C# code."
    assert scribe_voice(text)[0] == text


@pytest.mark.parametrize(
    "quoted",
    [
        '> "The simulated agents on Twitter lied, and round 4 proved it."',
        'Crito said "the simulation is rigged on Twitter" and left.',
        'Xanthippe wrote “the simulated agents on Reddit laugh” at dawn.',
        # Single quotes, curly and straight (apostrophes inside do not close them).
        "Xanthippe said ‘the agents of Anytus lie, and the simulation of justice is over’ at dawn.",
        "Plato wrote 'the simulated city won't hold, and round 4 proved it' at dusk.",
        "他说‘模拟Agent在Twitter上’，然后离开。",
        # Italics led in by a verb of speech or a colon, or followed by who said them.
        "Crito answered: *the agents of the city are simulated men*",
        "**Crito:** *the simulated agents on Twitter are paid*",
        "*The simulation is rigged on Twitter*, said Crito.",
        "Plato said _the simulated agents lie on Reddit_ and left.",
    ],
)
def test_a_citizens_quoted_words_are_never_rewritten(quoted):
    voiced, notes = scribe_voice(quoted, time_unit="hour")

    assert voiced == quoted
    left = [n for n in notes if n["kind"] == "left"]
    assert left and all(n["quoted"] for n in left)


def test_around_single_quotes_and_spoken_italics_the_scribes_words_still_change():
    text = (
        "Plato wrote 'the simulated city is a lie #Rigged' on Twitter, and Xanthippe said "
        "‘the simulation is over’ on Reddit. Crito answered: *the simulated agents are paid*. "
        "The simulated agents on Twitter left."
    )
    voiced, _ = scribe_voice(text, time_unit="hour")

    assert voiced == (
        "Plato wrote 'the simulated city is a lie Rigged' in the Agora, and Xanthippe said "
        "‘the simulation is over’ in the Stoa. Crito answered: *the simulated agents are paid*. "
        "The citizens in the Agora left."
    )


@pytest.mark.parametrize("opener", ["‘", "“", "'", '"', "said *", ": _"])
def test_an_unclosed_quote_cannot_stall_the_scribe(opener):
    # One paragraph of openers that never close: each must end at the next,
    # not scan to the end of the paragraph (that took twelve seconds).
    import time

    text = (f" {opener}the simulated agents on Twitter" * 1500).strip()
    started = time.monotonic()
    voiced, _ = scribe_voice(text, time_unit="hour")
    assert time.monotonic() - started < 5
    assert voiced


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # Apostrophes are not quotes.
        (
            "Crito's friends and the jurors' anger grew on Twitter; the simulated agents cheered.",
            "Crito's friends and the jurors' anger grew in the Agora; the citizens cheered.",
        ),
        (
            "In the '90s the simulated agents said 'Athens’s ship won't wait for Twitter' at dawn.",
            "In the '90s the citizens said 'Athens’s ship won't wait for Twitter' at dawn.",
        ),
        (
            "'Tis the hour: the simulated agents on Twitter left.",
            "'Tis the hour: the citizens in the Agora left.",
        ),
        # An inch mark does not open a quote, so the real one is still found.
        (
            'The board is 12" wide, and Crito said "the simulated agents lie" on Twitter.',
            'The board is 12" wide, and Crito said "the simulated agents lie" in the Agora.',
        ),
        # The Scribe's own emphasis is not a citizen's words.
        (
            "Twitter went *very* quiet, and the simulated agents slept.",
            "The Agora went *very* quiet, and the citizens slept.",
        ),
    ],
)
def test_what_only_looks_like_a_quote_is_the_scribes_to_rewrite(text, expected):
    assert scribe_voice(text, time_unit="hour")[0] == expected


def test_only_the_tags_change_inside_a_quote():
    text = '> "The simulated agents on Twitter lied. #Truth @crito_719"\n\nThe simulated agents on Twitter lied.'
    voiced, _ = scribe_voice(text, roster=ROSTER)

    assert voiced == '> "The simulated agents on Twitter lied. Truth Crito"\n\nThe citizens in the Agora lied.'


def test_an_agent_in_the_story_is_left_and_logged():
    text = "At dusk, agents of the company left, and the travel agents with them."
    voiced, notes = scribe_voice(text)

    assert voiced == text
    assert [n["term"] for n in notes if n["kind"] == "left"] == ["agent", "agent"]


def test_when_the_city_argues_about_agents_the_word_is_its_own():
    text = "The agents spoke. Many agents want a vote."
    assert scribe_voice(text, question="Should Athens let AI agents vote?")[0] == text


def test_the_rest_is_reported_not_rewritten():
    text = "The platform held. What the freeze predicts is unclear."
    voiced, notes = scribe_voice(text)

    assert voiced == text
    assert sorted(n["term"] for n in notes if n["kind"] == "left") == ["platform", "prediction"]


def test_a_chinese_chronicle_gets_its_own_words():
    voiced, _ = scribe_voice("在Twitter上，模拟Agent们争论到第12轮。各类Agent都发言了。#雅典#", time_unit="hour")
    assert voiced == "在广场上，公民们争论到第12小时。各类公民都发言了。雅典"


def test_prose_without_the_machines_words_is_untouched():
    text = (
        "Mayor Despina Nomikou holds the casting vote and refuses to spend it early.\n\n"
        "> \"The council meets Wednesday, October 14. I have not chosen.\"\n\n"
        "**Three asks, and none of them is a signature**\n\n- the roof\n- the tankers"
    )
    voiced, notes = scribe_voice(text, roster=ROSTER, time_unit="hour")
    assert voiced == text
    assert notes == []


def test_the_scribe_reads_her_notes_relabelled():
    raw = (
        "**采访人数:** 3 / 18 位模拟Agent\n【Twitter平台回答】\nThe ship is late.\n\n"
        "【Reddit平台回答】\n（该平台未获得回复）\nThey met on Twitter."
    )
    seen = observation_in_city_words(raw)

    assert "Twitter" not in seen and "Reddit" not in seen and "Agent" not in seen
    assert "【In the Agora】" in seen and "【In the Stoa】" in seen
    assert "They met in the Agora." in seen


# ── Every path runs through it ──

def test_a_chapter_is_handed_back_in_the_citys_words():
    llm = ScriptedLLM([*SEARCHES, "Final Answer: On Twitter the simulated agents cheered #Hemlock."])
    agent = make_agent(llm)
    agent.report_logger = MagicMock()

    assert write_section(agent) == "In the Agora the citizens cheered Hemlock."
    logged = agent.report_logger.log_section_content.call_args.kwargs["content"]
    assert logged == "In the Agora the citizens cheered Hemlock."


def test_a_chapter_keeps_a_citizens_single_quoted_words():
    llm = ScriptedLLM([*SEARCHES, "Final Answer: On Twitter, Crito said ‘the simulated agents lie’."])

    assert write_section(make_agent(llm)) == "In the Agora, Crito said ‘the simulated agents lie’."


def test_an_unmarked_chapter_is_voiced_too():
    body = "The simulated agents on Twitter cheered for hours and would not stop. " * 12
    llm = ScriptedLLM([*SEARCHES, body])

    section = write_section(make_agent(llm))

    assert "simulated" not in section and "Twitter" not in section
    assert section.startswith("The citizens in the Agora cheered for hours")


def test_a_chapter_forced_to_finish_is_voiced_too():
    llm = ScriptedLLM([
        *SEARCHES,
        '<tool_call>{"name": "quick_search", "parameters": {"query": "ship"}}</tool_call>',
        '<tool_call>{"name": "quick_search", "parameters": {"query": "ship"}}</tool_call>',
        "Final Answer: Reddit never forgave the simulation.",
    ])

    assert write_section(make_agent(llm)) == "The Stoa never forgave the argument."


def test_the_scribe_is_shown_interview_citizens_and_the_engine_runs_interview_agents():
    llm = ScriptedLLM([
        '<tool_call>{"name": "interview_citizens", "parameters": {"interview_topic": "the verdict", "max_citizens": 3}}</tool_call>',
        *SEARCHES[:2],
        "Final Answer: Done.",
    ])
    agent = make_agent(llm)
    agent._execute_tool = MagicMock(return_value="【Twitter平台回答】\nThe city voted.")

    write_section(agent)

    assert agent._execute_tool.call_args_list[0].args[0] == "interview_agents"
    observation = llm.seen[1][-1]["content"]
    assert "interview_citizens answered" in observation
    assert "【In the Agora】" in observation
    assert banned_in(without_data(observation, "The city voted.")) == []


def test_a_bare_json_call_by_the_citizens_name_is_accepted():
    agent = make_agent(ScriptedLLM())
    calls = agent._parse_tool_calls('{"name": "interview_citizens", "parameters": {"interview_topic": "x"}}')
    assert calls == [{"name": "interview_agents", "parameters": {"interview_topic": "x"}}]


def test_the_outline_is_set_down_in_the_citys_words():
    llm = ScriptedLLM(outline={
        "title": "The Simulated Athens on Twitter",
        "summary": "In the simulated month, the agents held firm.",
        "sections": [{"title": "Reddit Turns", "description": "x"}, {"title": "Round 3", "description": "y"}],
    })

    outline = make_agent(llm).plan_outline()

    assert outline.title == "Athens in the Agora"
    assert outline.summary == "In the month, the citizens held firm."
    assert outline.sections[0].title == "The Stoa Turns"
    # No length of step is known for this gathering, so the number stays (and is logged).
    assert outline.sections[1].title == "Round 3"


def test_a_failed_outline_falls_back_to_the_scribes_words():
    set_locale("en")
    outline = make_agent(ScriptedLLM(outline=RuntimeError("no outline"))).plan_outline()

    assert outline.title == "What Athens Came to Believe"
    assert [s.title for s in outline.sections] == [
        "The Question and What the City Found", "How the Citizens Moved", "What Is Still Unsettled",
    ]
    for text in (outline.title, outline.summary, *(s.title for s in outline.sections)):
        assert banned_in(text) == []


@pytest.fixture
def gathering():
    """A gathering folder with one-hour steps and a roster of handles."""
    sim_id = "sim_scribe_voice"
    sim_dir = os.path.join(Config.OASIS_SIMULATION_DATA_DIR, sim_id)
    os.makedirs(sim_dir, exist_ok=True)
    with open(os.path.join(sim_dir, "simulation_config.json"), "w", encoding="utf-8") as f:
        json.dump({"time_config": {"minutes_per_round": 60}}, f)
    with open(os.path.join(sim_dir, "reddit_profiles.json"), "w", encoding="utf-8") as f:
        json.dump([{"username": "crito_719", "name": "Crito"}, {"username": "plato_218", "name": "Plato"}], f)
    with open(os.path.join(sim_dir, "twitter_profiles.csv"), "w", encoding="utf-8") as f:
        f.write("user_id,username,name\n2,xanthippe_183,Xanthippe\n")
    return sim_id


def test_the_symposium_answer_is_in_the_citys_words(monkeypatch, gathering):
    monkeypatch.setattr(ReportManager, "get_report_by_simulation", classmethod(lambda _cls, _sid: None))
    llm = ScriptedLLM(['By round 3 the simulated agents on Twitter sided with @crito_719. #Escape\n\n> "#Escape now," wrote @xanthippe_183.'])

    result = make_agent(llm, simulation_id=gathering).chat("Who sided with Crito?")

    assert result["response"] == (
        'By hour 3 the citizens in the Agora sided with Crito. Escape\n\n> "Escape now," wrote Xanthippe.'
    )
    assert result["tool_calls"] == []


def test_the_symposium_answer_after_a_search_is_voiced_too(monkeypatch, gathering):
    monkeypatch.setattr(ReportManager, "get_report_by_simulation", classmethod(lambda _cls, _sid: None))
    llm = ScriptedLLM([
        '<tool_call>{"name": "quick_search", "parameters": {"query": "Crito"}}</tool_call>',
        '<tool_call>{"name": "interview_citizens", "parameters": {"interview_topic": "Crito"}}</tool_call>',
        "Reddit sided with plato_218 by round 2.",
    ])
    agent = make_agent(llm, simulation_id=gathering)
    agent._execute_tool = MagicMock(return_value="【Reddit平台回答】\nPlato: stay.")

    result = agent.chat("Where did the Stoa stand?")

    assert result["response"] == "The Stoa sided with Plato by hour 2."
    # The tool calls go back under the names the Symposium already knows.
    assert [c["name"] for c in result["tool_calls"]] == ["quick_search", "interview_agents"]
    observation = llm.seen[1][-1]["content"]
    assert observation.startswith("[quick_search answered]\n【In the Stoa】")


def test_the_symposium_reads_an_older_chronicle_in_the_citys_words(monkeypatch):
    chronicle = "# The Hemlock Month\n\nThe simulated agents on Twitter held firm."
    report = MagicMock(markdown_content=chronicle)
    monkeypatch.setattr(ReportManager, "get_report_by_simulation", classmethod(lambda _cls, _sid: report))
    llm = ScriptedLLM(["They held."])

    make_agent(llm).chat("Did they hold?")

    assert "The citizens in the Agora held firm." in llm.seen[0][0]["content"]


class _Records(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.records = []

    def emit(self, record):
        self.records.append(record)


def test_what_is_left_is_logged_for_the_owner_not_shown_as_trouble():
    # The mirofish loggers do not propagate, so listen on the Scribe's own.
    scribe_log = logging.getLogger("mirofish.report_agent")
    listener, level = _Records(), scribe_log.level
    scribe_log.addHandler(listener)
    scribe_log.setLevel(logging.DEBUG)
    try:
        voiced = make_agent(ScriptedLLM())._in_scribe_voice("The platform held; Twitter cheered.", "chapter 1")
    finally:
        scribe_log.removeHandler(listener)
        scribe_log.setLevel(level)

    assert voiced == "The platform held; the Agora cheered."
    records = [r for r in listener.records if "Scribe's words (chapter 1)" in r.getMessage()]
    assert records
    # The Chronicle's ledger shows warnings to the visitor; this is for the owner only.
    assert all(r.levelno < logging.WARNING for r in records)
    summary = [r.getMessage() for r in records if r.levelno == logging.INFO][0]
    assert "1 put in the city's words" in summary and "platform x1" in summary
