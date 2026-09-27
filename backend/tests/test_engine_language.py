"""The engine writes a gathering's record in its record language.

Each gathering has one record language, stored on its project. The engine's
part of the record (the memory's activity facts, the run's notes and errors,
the profiles, the settings, the stance turns) is written in it, whichever
request or thread does the work; nothing falls back to Chinese. No test here
reaches a real model: the translator is a fake, or refuses.
"""

import json
import os
from types import SimpleNamespace

import pytest

from app.memory import MemoryStore, new_id, utcnow_iso
from app.memory.activity import (
    ACTIVITY_SOURCE,
    account_summary,
    activity_system_prompt,
    build_activity_messages,
    episode_accounts,
    hub_summary,
    ingest_activity_episode,
    render_activity_window,
    rerender_description,
    rerender_episode,
    rerender_fact,
    rerender_summary,
)
from app.memory.extraction import _stated_language, document_system_prompt
from app.memory.resolution import create_node
from app.models.project import ProjectManager
from app.services import citizen_portraits as portraits
from app.services import language_guard
from app.services import simulation_manager as simulation_manager_module
from app.services import simulation_runner as runner_module
from app.services.language_guard import HAN_RE
from app.services.oasis_profile_generator import (
    OasisAgentProfile,
    OasisProfileGenerator,
    country_in,
    display_names,
    fallback_persona,
)
from app.services.simulation_config_generator import SimulationConfigGenerator
from app.services.simulation_manager import SimulationManager
from app.services.simulation_runner import RunnerStatus, SimulationRunner, SimulationRunState
from app.services.zep_entity_reader import EntityNode, FilteredEntities
from app.services.zep_graph_memory_updater import AgentActivity, ZepGraphMemoryUpdater
from app.utils.locale import set_locale


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
    """A translate-only model answering from a table (a line it does not know comes back as it was)."""

    def __init__(self, table):
        self.table = table
        self.calls = []

    def chat_json(self, messages, temperature=None, max_tokens=None):
        lines = json.loads(messages[-1]["content"])["lines"]
        self.calls.append(lines)
        return {"lines": [self.table.get(line, line) for line in lines]}


def _translator(monkeypatch, table):
    fake = FakeTranslator(table)
    monkeypatch.setattr(language_guard, "default_translator", lambda: fake)
    return fake


def _han(text):
    return bool(HAN_RE.search(text or ""))


@pytest.fixture()
def gathering(tmp_path, monkeypatch):
    """A project with a stored record language and its simulation's state.json."""

    monkeypatch.setattr(ProjectManager, "PROJECTS_DIR", str(tmp_path / "projects"))

    def make(name, language, requirement="Will Socrates escape?"):
        project = ProjectManager.create_project(name=name, language=language)
        project.simulation_requirement = requirement
        ProjectManager.save_project(project)
        simulation_id = f"sim_{name}"
        folder = os.path.join(SimulationManager.SIMULATION_DATA_DIR, simulation_id)
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "state.json"), "w", encoding="utf-8") as handle:
            json.dump({"simulation_id": simulation_id, "project_id": project.project_id,
                       "graph_id": "graph_1", "status": "created"}, handle)
        return simulation_id

    return make


# ---------------------------------------------------------------- the memory's rules text

@pytest.mark.parametrize("chinese, english", [
    ("Crito在Twitter发布了一条帖子：「I cannot stop weeping」", "On Twitter, Crito posted: “I cannot stop weeping”"),
    ("Priests of Athena在Reddit评论道：「The gods」", "On Reddit, Priests of Athena commented: “The gods”"),
    ("Socrates在Twitter引用了Parents for Pencils的帖子「As the October 22」，并评论道：「Yes」",
     "On Twitter, Socrates quoted Parents for Pencils's post “As the October 22”, adding: “Yes”"),
    ("Ann Lee在Reddit在Bob的帖子「Hi」下评论道：「Nice」", "On Reddit, Ann Lee commented on Bob's post “Hi”: “Nice”"),
    ("Ann在Twitter点赞了Bob的一条帖子", "On Twitter, Ann liked a post by Bob"),
    ("Ann在Twitter关注了用户「Bob Smith」", "On Twitter, Ann followed the user “Bob Smith”"),
    ("Ann在Reddit执行了UNFOLLOW操作", "On Reddit, Ann performed UNFOLLOW"),
    ("Ann在Reddit执行了操作", "On Reddit, Ann performed an action"),
])
def test_a_rules_fact_is_rendered_in_either_language(chinese, english):
    assert rerender_fact(chinese, "en") == english
    assert rerender_fact(english, "zh") == chinese
    assert rerender_fact(english, "en") == english
    assert rerender_fact(chinese, "zh-CN") == chinese


def test_a_fact_cut_short_or_not_written_by_the_rules():
    # A fact cut at 1,000 characters lost its closing quote.
    assert rerender_fact("Crito在Twitter发布了一条帖子：「The gods have been…", "en") == (
        "On Twitter, Crito posted: “The gods have been…”"
    )
    assert rerender_fact("苏格拉底是雅典的哲学家。", "en") is None
    assert rerender_fact("Socrates argued with Crito.", "en") is None
    assert rerender_description("发布了一条帖子：「Hi」", None) == "posted: “Hi”"


def test_an_episode_is_rendered_in_either_language():
    chinese = "\n".join([
        "[2026-09-25T14:04:00] [twitter round 3] Priests of Athena: 发布了一条帖子：「The gods",
        "have been avenged」",
        "[2026-09-25T14:05:00] [reddit round 3] Crito: 点赞了Phaedo的一条帖子",
        "[2026-09-25T14:06:00] [reddit round 4] Crito: 做了一件没有模板的事",
    ])
    english = rerender_episode(chinese, "en")
    assert english.split("\n") == [
        "[2026-09-25T14:04:00] [twitter round 3] Priests of Athena: posted: “The gods",
        "have been avenged”",
        "[2026-09-25T14:05:00] [reddit round 3] Crito: liked a post by Phaedo",
        "[2026-09-25T14:06:00] [reddit round 4] Crito: 做了一件没有模板的事",
    ]
    assert rerender_episode(english, "zh") == chinese
    assert rerender_episode("no records here", "en") == "no records here"


def test_hub_and_account_summaries_in_either_language():
    assert hub_summary("twitter", "en") == "Twitter is the social media platform used in the simulation."
    assert hub_summary("reddit", "zh") == "Reddit是模拟中使用的社交媒体平台。"
    assert account_summary("陈屿", "twitter", None) == "陈屿 is a simulated account on Twitter."
    assert rerender_summary("Twitter是模拟中使用的社交媒体平台。", "en") == hub_summary("twitter", "en")
    assert rerender_summary("陈屿是Twitter上的模拟账号。", "en") == "陈屿 is a simulated account on Twitter."
    assert rerender_summary("A philosopher of Athens.", "en") is None


def _memory(tmp_path):
    store = MemoryStore(str(tmp_path / "memory.sqlite3"), busy_timeout_ms=2000)
    with store.write() as conn:
        conn.execute("INSERT INTO graphs(graph_id, uuid, name, created_at) VALUES (?, ?, ?, ?)",
                     ("g1", new_id(), "g1", utcnow_iso()))
    return store


def _ingest(store, content, language, accounts=None):
    episode_uuid = new_id()
    metadata = {"source": ACTIVITY_SOURCE, "simulation_id": "sim-1"}
    if language:
        metadata["language"] = language
    if accounts:
        metadata["accounts"] = json.dumps(accounts)  # as the updater sends it
    with store.write() as conn:
        conn.execute(
            "INSERT INTO episodes(uuid, graph_id, kind, content, source, source_description, metadata_json, "
            "simulation_id, reference_time, reference_time_explicit, created_at, extraction_status) "
            "VALUES (?, 'g1', 'activity', ?, 'text', 'MiroFish simulation activity batch', ?, 'sim-1', ?, 1, ?, "
            "'pending')",
            (episode_uuid, content, json.dumps(metadata), utcnow_iso(), utcnow_iso()),
        )
        ingest_activity_episode(conn, episode_uuid, mode="rules")
    with store.read() as conn:
        facts = [row["fact"] for row in conn.execute("SELECT fact FROM edges WHERE graph_id = 'g1' ORDER BY id")]
        summaries = {row["name"]: row["summary"]
                     for row in conn.execute("SELECT name, summary FROM nodes WHERE graph_id = 'g1'")}
    return facts, summaries


def _line(locale, **args):
    activity = AgentActivity(platform="twitter", agent_id=1, agent_name="Crito", action_type="QUOTE_POST",
                             action_args=args, round_num=2, timestamp="2026-09-25T14:00:00")
    return activity.to_episode_text(locale)


def test_an_english_gathering_never_gets_chinese_rules_facts(tmp_path):
    store = _memory(tmp_path)
    try:
        # A line written with the Chinese templates, in an English gathering.
        line = _line("zh", original_author_name="Phaedo", original_content="He drank", quote_content="Calmly")
        facts, summaries = _ingest(store, line, "en")
    finally:
        store.close()
    assert facts == ["On Twitter, Crito quoted Phaedo's post “He drank”, adding: “Calmly”"]
    assert summaries == {"Crito": "Crito is a simulated account on Twitter.",
                         "Phaedo": "Phaedo is a simulated account on Twitter."}


def test_a_chinese_gathering_keeps_its_chinese_rules_facts(tmp_path):
    store = _memory(tmp_path)
    try:
        facts, summaries = _ingest(store, _line("en", original_content="He drank"), "zh")
    finally:
        store.close()
    assert facts == ["Crito在Twitter引用了一条帖子「He drank」"]
    assert summaries["Twitter"] == "Twitter是模拟中使用的社交媒体平台。"


def test_without_a_stated_language_the_facts_follow_the_line(tmp_path):
    store = _memory(tmp_path)
    try:
        facts, _summaries = _ingest(store, _line("zh", original_content="He drank"), None)
    finally:
        store.close()
    assert facts == ["Crito在Twitter引用了一条帖子「He drank」"]


def test_an_account_stays_on_the_graph_node_it_was_built_from(tmp_path):
    """An English record names 苏格拉底 "Socrates": his activity still joins the scroll's node."""

    store = _memory(tmp_path)
    try:
        with store.write() as conn:
            socrates = create_node(conn, "g1", name="苏格拉底", entity_type="Person", origin="llm").uuid
        lines = "\n".join([
            AgentActivity(platform="twitter", agent_id=0, agent_name="Socrates", action_type="CREATE_POST",
                          action_args={"content": "Know yourself"}, round_num=1,
                          timestamp="2026-09-25T14:00:00").to_episode_text("en"),
            AgentActivity(platform="twitter", agent_id=1, agent_name="Crito", action_type="FOLLOW",
                          action_args={"target_user_name": "Socrates"}, round_num=1,
                          timestamp="2026-09-25T14:01:00").to_episode_text("en"),
        ])
        # Crito's node was merged away: his name finds (here: makes) his node instead.
        facts, summaries = _ingest(store, lines, "en", accounts={"Socrates": socrates, "Crito": "gone"})
        with store.read() as conn:
            ends = [(row["source_node_uuid"], row["target_node_uuid"])
                    for row in conn.execute("SELECT * FROM edges WHERE graph_id = 'g1' ORDER BY id")]
    finally:
        store.close()
    assert facts == ["On Twitter, Socrates posted: “Know yourself”", "On Twitter, Crito followed the user “Socrates”"]
    assert set(summaries) == {"苏格拉底", "Twitter", "Crito"}  # no second node for Socrates
    assert ends[0][0] == socrates and ends[1][1] == socrates


def test_the_accounts_an_episode_names():
    assert episode_accounts({"accounts": json.dumps({"Socrates": "n1"})}) == {"Socrates": "n1"}
    assert episode_accounts({"accounts": {"Socrates": "n1", "Crito": 3}}) == {"Socrates": "n1"}
    assert episode_accounts({"accounts": "{broken"}) == {}
    assert episode_accounts({}) == {} and episode_accounts(None) == {}


def test_the_enrichment_and_extraction_prompts_follow_a_stated_language():
    row = {"uuid": "e1", "content": _line("en", original_content="He drank"),
           "reference_time": "2026-09-25T14:00:00Z", "metadata_json": json.dumps({"language": "en"})}
    window = render_activity_window([row])
    assert window.language == "en"
    system = build_activity_messages(window)[0]["content"]
    assert "in the language of TEXT" not in system and system.count("in English") == 2
    assert render_activity_window([{**row, "metadata_json": None}]).language is None
    assert "in the language of TEXT" in activity_system_prompt()

    assert _stated_language(json.dumps({"language": "zh-CN"})) == "zh"
    assert _stated_language(None) is None and _stated_language("{broken") is None
    english = document_system_prompt(12, 34, "en")
    assert "in the language of TEXT" not in english and "in English" in english
    assert "in the language of TEXT" in document_system_prompt(12, 34)


def test_an_english_record_names_its_entities_in_english():
    english = document_system_prompt(12, 34, "en")
    assert 'Write "name" in English' in english and "keep names as written" not in english
    assert english.count('name each entity by its "name"') == 2  # summary and fact
    chinese = document_system_prompt(12, 34, "zh")
    assert 'Write "name" in English' not in chinese and chinese.count("keep names as written") == 2
    unknown = document_system_prompt(12, 34)
    assert 'Write "name" in English' not in unknown and "keep names as written" not in unknown
    # An account's name is how the rules find its node: activity keeps names as written.
    assert "keep names as written" in activity_system_prompt(language="en")


# ---------------------------------------------------------------- the memory updater

def _updater(monkeypatch, simulation_id):
    client = SimpleNamespace(graph=SimpleNamespace(add=lambda **kwargs: None))
    monkeypatch.setattr("app.services.zep_graph_memory_updater.get_zep_client", lambda _key: client)
    return ZepGraphMemoryUpdater("graph-1", api_key="test-key", simulation_id=simulation_id)


def test_the_updater_reads_the_stored_record_language(gathering, monkeypatch):
    set_locale("zh")
    assert _updater(monkeypatch, gathering("athens", "en")).locale == "en"
    set_locale("en")
    assert _updater(monkeypatch, gathering("xian", "zh")).locale == "zh"
    monkeypatch.setenv("PARTHENON_RECORD_LANGUAGE", "en")  # the public steps
    assert _updater(monkeypatch, "sim_xian").locale == "en"


# ---------------------------------------------------------------- the run's notes and errors

def _stale_run(simulation_id):
    state = SimulationRunState(simulation_id=simulation_id, runner_status=RunnerStatus.STOPPING,
                               current_round=136, total_rounds=336, process_pid=4242)
    SimulationRunner._save_run_state(state)
    SimulationRunner._run_states.pop(simulation_id, None)


@pytest.mark.parametrize("language, words", [("en", "marked as stopped"), ("zh", "已标记为停止")])
def test_the_startup_note_is_written_in_the_record_language(gathering, monkeypatch, language, words):
    monkeypatch.setattr(runner_module, "_surviving_simulator_pid", lambda *_args: None)
    simulation_id = gathering(f"reconciled{language}", language)
    _stale_run(simulation_id)
    # The reader of this thread (a startup has none) never decides.
    set_locale("zh" if language == "en" else "en")
    try:
        state = SimulationRunner.reconcile_orphaned_run(simulation_id)
    finally:
        SimulationRunner._run_states.pop(simulation_id, None)
    assert state is not None and words in state.error
    assert _han(state.error) is (language == "zh")
    assert SimulationManager().get_simulation(simulation_id).error == state.error


def test_a_failed_runs_note_keeps_only_the_log_lines_its_reader_can_read():
    log = "OASIS 双平台并行模拟\n\nTraceback (most recent call last):\nValueError: the model is down\n已发布 3 条初始帖子"
    assert runner_module._log_tail(log, "en") == "Traceback (most recent call last):\nValueError: the model is down"
    assert "已发布" in runner_module._log_tail(log, "zh")


def test_no_default_is_chinese_in_the_runner():
    assert SimulationRunner._monitor_simulation.__func__.__defaults__ == (None,)


# ---------------------------------------------------------------- the preparation

class _EmptyReader:
    def filter_defined_entities(self, **_kwargs):
        return FilteredEntities(entities=[], entity_types=set(), total_count=3, filtered_count=0)


@pytest.mark.parametrize("language", ["en", "zh"])
def test_a_failed_preparation_is_noted_in_the_record_language(gathering, monkeypatch, language):
    monkeypatch.setattr(simulation_manager_module, "ZepEntityReader", _EmptyReader)
    simulation_id = gathering(f"empty{language}", language)
    set_locale("zh" if language == "en" else "en")
    with pytest.raises(ValueError):
        SimulationManager().prepare_simulation(simulation_id, "Will Socrates escape?", "text")
    with open(os.path.join(SimulationManager.SIMULATION_DATA_DIR, simulation_id, "state.json"),
              encoding="utf-8") as handle:
        error = json.load(handle)["error"]
    assert _han(error) is (language == "zh")


def test_the_profiles_and_settings_are_asked_for_in_the_record_language(gathering, monkeypatch):
    asked = {}

    class Reader:
        def filter_defined_entities(self, **_kwargs):
            entity = EntityNode(uuid="u1", name="Crito", labels=["Entity", "Person"], summary="A friend.",
                                attributes={})
            return FilteredEntities(entities=[entity], entity_types={"Person"}, total_count=1, filtered_count=1)

    class Profiles:
        def __init__(self, **kwargs):
            asked["profiles"] = kwargs.get("language")

        def generate_profiles_from_entities(self, **_kwargs):
            return [OasisAgentProfile(user_id=0, user_name="crito_101", name="Crito", bio="b", persona="p")]

        def save_profiles(self, **_kwargs):
            pass

    class Settings:
        def generate_config(self, **kwargs):
            asked["settings"] = kwargs.get("language")
            asked["names"] = kwargs.get("agent_names")
            return SimpleNamespace(to_json=lambda: "{}", generation_reasoning="")

    monkeypatch.setattr(simulation_manager_module, "ZepEntityReader", Reader)
    monkeypatch.setattr(simulation_manager_module, "OasisProfileGenerator", Profiles)
    monkeypatch.setattr(simulation_manager_module, "SimulationConfigGenerator", Settings)
    simulation_id = gathering("xianprep", "zh")
    set_locale("en")  # an English visitor pressed prepare
    SimulationManager().prepare_simulation(simulation_id, "Will Socrates escape?", "text")
    # The settings name each citizen as its profile does.
    assert asked == {"profiles": "zh", "settings": "zh", "names": {0: "Crito"}}


# ---------------------------------------------------------------- the profiles

def _profile_generator(language):
    generator = OasisProfileGenerator.__new__(OasisProfileGenerator)
    generator.language = language
    return generator


def test_the_persona_prompts_are_english_and_name_the_record_language():
    set_locale("zh")
    english = _profile_generator("en")
    for build in (english._build_individual_persona_prompt, english._build_group_persona_prompt):
        prompt = build("Phaedra", "WaterCarrier", "carries water", {}, "Athens, 410 BC")
        assert not _han(prompt)
        assert '"Greece"' in prompt and prompt.rstrip().endswith("Please respond in English.")
    assert not _han(english._get_system_prompt(True))
    chinese = _profile_generator("zh")
    prompt = chinese._build_individual_persona_prompt("Phaedra", "WaterCarrier", "carries water", {}, "")
    assert '"希腊"' in prompt and "请使用中文回答" in prompt
    assert "中国" not in prompt


def test_a_country_is_written_as_the_record_writes_it():
    assert country_in("希腊", "en") == "Greece"
    assert country_in("「普萨莫斯」", "en") == "Psammos"
    assert country_in("Greece", "en") == "Greece"
    assert country_in("某个城邦", "en") is None
    assert country_in("希腊", "zh") == "希腊"
    assert country_in("", "en") is None
    assert fallback_persona("Crito", "Person", "en") == "Crito is a Person."
    assert fallback_persona("Crito", "Person", "zh") == "Crito是一个Person。"


def test_a_chinese_profile_is_put_into_english_for_an_english_record(monkeypatch):
    fake = _translator(monkeypatch, {
        "克里托是苏格拉底的老朋友。": "Crito is an old friend of Socrates.",
        "富有的雅典人": "A wealthy Athenian",
        "政治": "Politics",
    })
    data = {"bio": "富有的雅典人", "persona": "克里托是苏格拉底的老朋友。", "country": "希腊",
            "profession": "Landowner", "interested_topics": ["政治", "Friendship"], "age": 60}
    fixed = _profile_generator("en")._in_record_language(data, "Crito")
    assert fixed == {"bio": "A wealthy Athenian", "persona": "Crito is an old friend of Socrates.",
                     "country": "Greece", "profession": "Landowner",
                     "interested_topics": ["Politics", "Friendship"], "age": 60}
    assert len(fake.calls) == 1  # every field in one call; the country needed none
    # A Chinese record is left as written, with no call.
    assert _profile_generator("zh")._in_record_language(data, "Crito") == data
    assert len(fake.calls) == 1


def test_a_chinese_name_is_shown_in_english_for_an_english_record(monkeypatch):
    fake = _translator(monkeypatch, {"苏格拉底": "Socrates", "雅典公民大会": "The Athenian Assembly"})
    generator = _profile_generator("en")
    generator._learn_names(["苏格拉底", "Crito", "雅典公民大会", "无名氏", "苏格拉底"])
    assert len(fake.calls) == 1 and sorted(fake.calls[0]) == ["无名氏", "苏格拉底", "雅典公民大会"]
    assert generator.shown_name("苏格拉底", 0) == "Socrates"
    assert generator.shown_name("雅典公民大会", 1) == "The Athenian Assembly"
    assert generator.shown_name("Crito", 2) == "Crito"
    # A name the model gave back untranslated gets a stand-in, never Chinese.
    assert generator.shown_name("无名氏", 3) == "Citizen 3"
    assert len(fake.calls) == 1  # every name was asked for once
    # A Chinese record shows the names as the graph has them.
    assert _profile_generator("zh").shown_name("苏格拉底", 0) == "苏格拉底"
    assert display_names(["苏格拉底"], "zh") == {} and len(fake.calls) == 1


def test_a_profile_from_a_chinese_entity_shows_its_english_name(monkeypatch):
    _translator(monkeypatch, {"苏格拉底": "Socrates", "雅典的哲学家。": "A philosopher of Athens."})
    generator = _profile_generator("en")
    monkeypatch.setattr(generator, "_build_entity_context", lambda _entity: "")
    entity = EntityNode(uuid="node-socrates", name="苏格拉底", labels=["Entity", "Person"],
                        summary="雅典的哲学家。", attributes={})
    profile = generator.generate_profile_from_entity(entity, user_id=0, use_llm=False)
    assert profile.name == "Socrates" and profile.user_name.startswith("socrates_")
    assert profile.source_entity_uuid == "node-socrates"  # the graph keeps its own name
    assert not _han(json.dumps(profile.to_reddit_format(), ensure_ascii=False))
    stand_in = generator._stand_in_profile(4, entity, "Person")
    assert stand_in.name == "Socrates" and not _han(json.dumps(stand_in.to_dict(), ensure_ascii=False))


def test_the_persona_prompt_knows_the_sources_name_for_the_shown_one():
    english = _profile_generator("en")._build_individual_persona_prompt(
        "Socrates", "Person", "A philosopher.", {}, "苏格拉底 drank the hemlock.", source_name="苏格拉底")
    assert "Entity name: Socrates\nThe context writes this name as: 苏格拉底" in english
    assert "in its usual English form" in english and "keeping names as they are" not in english
    same = _profile_generator("en")._build_group_persona_prompt("Crito", "Person", "", {}, "", source_name="Crito")
    assert "The context writes this name as" not in same
    chinese = _profile_generator("zh")._build_individual_persona_prompt("苏格拉底", "Person", "", {}, "")
    assert "keeping names as they are" in chinese


def test_saved_profiles_give_every_citizen_a_country_in_the_record_language(tmp_path):
    def profile(name, country=None):
        return OasisAgentProfile(user_id=0, user_name=name.lower(), name=name, bio="b", persona="p", country=country)

    profiles = [profile("Lysias", "希腊"), profile("Kleon", "某个城邦"), profile("Aristo", "Greece"), profile("Phaedra")]
    path = tmp_path / "reddit_profiles.json"
    _profile_generator("en")._save_reddit_json(profiles, str(path))
    assert [item["country"] for item in json.loads(path.read_text(encoding="utf-8"))] == ["Greece"] * 4
    _profile_generator("zh")._save_reddit_json([profile("Lysias")], str(path))
    assert json.loads(path.read_text(encoding="utf-8"))[0]["country"] == "希腊"


# ---------------------------------------------------------------- the settings

def _settings_generator(monkeypatch, answer=None):
    generator = SimulationConfigGenerator.__new__(SimulationConfigGenerator)
    generator.model_name, generator.base_url = "test-model", "http://127.0.0.1:9/v1"
    prompts = []

    def call(prompt, system_prompt):
        prompts.append((prompt, system_prompt))
        if answer is None:
            raise RuntimeError("the model is down")
        return answer(prompt)

    monkeypatch.setattr(generator, "_call_llm_with_retry", call)
    return generator, prompts


def _entity(name="Crito"):
    return EntityNode(uuid=f"u-{name}", name=name, labels=["Entity", "Person"], summary="A friend.", attributes={})


@pytest.mark.parametrize("language", ["en", "zh"])
def test_the_default_settings_reason_in_the_record_language(monkeypatch, language):
    set_locale("zh" if language == "en" else "en")
    generator, prompts = _settings_generator(monkeypatch)
    params = generator.generate_config("sim_1", "proj_1", "graph_1", "Will Socrates escape?", "text",
                                       [_entity()], language=language)
    assert params.language == language and params.to_dict()["language"] == language
    assert _han(params.generation_reasoning) is (language == "zh")
    assert "Chinese" not in params.generation_reasoning and "中国" not in params.generation_reasoning
    # The prompts themselves are English; the record language is their last word.
    instruction = "Please respond in English." if language == "en" else "请使用中文回答。"
    for prompt, system in prompts:
        assert not _han(prompt.replace("Will Socrates escape?", ""))
        assert instruction in system


def test_the_settings_name_each_citizen_as_its_profile_does(monkeypatch):
    generator, _prompts = _settings_generator(monkeypatch)
    params = generator.generate_config("sim_1", "proj_1", "graph_1", "Will Socrates escape?", "text",
                                       [_entity("苏格拉底"), _entity("Crito")], language="en",
                                       agent_names={0: "Socrates"})
    agents = params.to_dict()["agent_configs"]
    assert [(a["entity_name"], a["entity_uuid"]) for a in agents] == [("Socrates", "u-苏格拉底"), ("Crito", "u-Crito")]


def test_the_settings_guard_puts_chinese_into_english(monkeypatch):
    _translator(monkeypatch, {"苏格拉底会逃走吗？": "Will Socrates escape?", "越狱": "Escape",
                              "监狱里的讨论": "Talk in the prison"})
    time_result = {"reasoning": "Evenings are busy."}
    event_result = {"hot_topics": ["越狱", "Hemlock"], "narrative_direction": "监狱里的讨论",
                    "initial_posts": [{"content": "苏格拉底会逃走吗？", "poster_type": "Person"}],
                    "reasoning": "Plain."}
    SimulationConfigGenerator._in_record_language(time_result, event_result, "en")
    assert event_result == {"hot_topics": ["Escape", "Hemlock"], "narrative_direction": "Talk in the prison",
                            "initial_posts": [{"content": "Will Socrates escape?", "poster_type": "Person"}],
                            "reasoning": "Plain."}
    untouched = {"hot_topics": ["越狱"]}
    SimulationConfigGenerator._in_record_language({}, untouched, "zh")
    assert untouched == {"hot_topics": ["越狱"]}


# ---------------------------------------------------------------- the stance turns

def _stance_gathering(gathering, name, language, requirement):
    simulation_id = gathering(name, language, requirement=requirement)
    folder = os.path.join(SimulationManager.SIMULATION_DATA_DIR, simulation_id)
    with open(os.path.join(folder, "simulation_config.json"), "w", encoding="utf-8") as handle:
        json.dump({"simulation_id": simulation_id, "simulation_requirement": requirement,
                   "agent_configs": [{"agent_id": 1, "entity_name": "Crito", "entity_type": "Person",
                                      "stance": "neutral"}]}, handle)
    os.makedirs(os.path.join(folder, "twitter"), exist_ok=True)
    with open(os.path.join(folder, "twitter", "actions.jsonl"), "w", encoding="utf-8") as handle:
        for round_number, words in ((0, "I have not chosen."), (1, "He must escape.")):
            handle.write(json.dumps({"round": round_number, "timestamp": f"2026-09-25T19:00:0{round_number}",
                                     "agent_id": 1, "agent_name": "Crito", "action_type": "CREATE_POST",
                                     "action_args": {"content": words}}) + "\n")
    return simulation_id


class _Reader:
    def __init__(self, turn):
        self.turn = turn
        self.calls = []

    def chat_json(self, messages, **_kwargs):
        self.calls.append(messages)
        return {"citizens": [{"id": 1, "turn": self.turn, "periods": [{"period": 2, "stance": "supportive"}]}]}


def test_the_gathering_language_is_the_stored_record_language(gathering):
    simulation_id = gathering("xianlang", "zh", requirement="Will Socrates escape?")
    assert portraits.gathering_language_of(simulation_id) == "zh"
    assert portraits.gathering_language("Will Socrates escape?", simulation_id=simulation_id) == "zh"
    assert portraits.gathering_language("苏格拉底会逃走吗？") == "zh"
    assert portraits.gathering_language("", ["The agora waits."]) == "en"


def test_one_chinese_character_hides_a_turn_from_an_english_reader():
    citizens = [{"turn": "Welcomed the Nerve 条款."}, {"turn": "Welcomed the Nerve clause."},
                {"turn": "欢迎Nerve条款使其转为支持。"}]
    assert [c["turn"] for c in portraits.hide_foreign_turns(citizens, "en")] == [
        "", "Welcomed the Nerve clause.", ""]
    assert [c["turn"] for c in portraits.hide_foreign_turns(citizens, "zh")] == [
        "", "", "欢迎Nerve条款使其转为支持。"]


def test_stance_turns_are_written_and_guarded_in_the_record_language(gathering, monkeypatch):
    fake = _translator(monkeypatch, {"克里托被说服了。": "Crito was persuaded."})
    simulation_id = _stance_gathering(gathering, "athensturns", "en", "苏格拉底会逃走吗？")
    set_locale("zh")  # a Chinese visitor asked for the reading
    reader = portraits.StanceReader(simulation_id, llm=_Reader("克里托被说服了。"))
    assert reader.locale == "en"  # the stored language beats the Chinese question
    reader.finish(reader.read())
    assert "Please respond in English." in reader.llm.calls[0][0]["content"]
    saved = portraits.read_stances(simulation_id)
    assert saved["lang"] == "en"
    assert [c["turn"] for c in saved["citizens"]] == ["Crito was persuaded."]
    assert fake.calls == [["克里托被说服了。"]]


def test_a_chinese_gatherings_turns_stay_chinese(gathering):
    simulation_id = _stance_gathering(gathering, "xianturns", "zh", "Will Socrates escape?")
    set_locale("en")
    reader = portraits.StanceReader(simulation_id, llm=_Reader("克里托被说服了。"))
    assert reader.locale == "zh"
    reader.finish(reader.read())
    assert [c["turn"] for c in portraits.read_stances(simulation_id)["citizens"]] == ["克里托被说服了。"]
    assert portraits.get_stances(simulation_id)["lang"] == "zh"
