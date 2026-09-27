"""The record language reaches the places round one left unwired.

1. graph_builder: every document chunk states its gathering's record language
   in its episode metadata, and the local extraction writes the memory in it
   (an English gathering built from a Chinese scroll names Socrates in
   English, with the scroll's form as an alias).
2. api/simulation.py generate-profiles: the profiles are written in the record
   language of the gathering, never in the thread's or the visitor's.
3. GET /api/simulation/<id>, /list and /history: each row carries 'language',
   so the shelf no longer guesses it.

No test reaches a real model: the extraction talks to a fake, and the profile
generator and entity reader are stand-ins.
"""

from __future__ import annotations

import json
import os
from dataclasses import replace
from types import SimpleNamespace

import pytest
from flask import Flask

from app.api import simulation as simulation_api
from app.api import simulation_bp
from app.config import Config
from app.memory import LocalZep, clear_local_memory_clients, register_local_memory_client
from app.memory.settings import LocalMemorySettings
from app.models.project import ProjectManager
from app.services import graph_builder as graph_builder_module
from app.services.graph_builder import GraphBuilderService, graph_record_language
from app.services.language_guard import RECORD_LANGUAGE_ENV
from app.services.report_agent import ReportManager
from app.services.simulation_manager import SimulationManager, SimulationState, SimulationStatus
from app.services.simulation_runner import SimulationRunner
from app.utils.locale import set_locale

CHINESE_QUESTION = "苏格拉底会逃离雅典吗？"
ENGLISH_QUESTION = "Will Socrates flee Athens?"
SCROLL = ["苏格拉底在雅典的监狱里等待审判。", "克里托劝他在夜里逃走。"]


@pytest.fixture(autouse=True)
def _no_configured_language(monkeypatch):
    """The owner's machine: no PARTHENON_RECORD_LANGUAGE unless a test sets it."""

    monkeypatch.delenv(RECORD_LANGUAGE_ENV, raising=False)


@pytest.fixture
def projects(tmp_path, monkeypatch):
    """Projects (and reports) in a temp folder; simulations already are (conftest)."""

    folder = tmp_path / "projects"
    folder.mkdir()
    monkeypatch.setattr(ProjectManager, "PROJECTS_DIR", str(folder))
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"))
    return folder


def _project(language=None, *, graph_id=None, requirement=ENGLISH_QUESTION, name="The Hemlock"):
    project = ProjectManager.create_project(name=name, language=language)
    project.graph_id = graph_id
    project.simulation_requirement = requirement
    ProjectManager.save_project(project)
    return project


# ---------------------------------------------------------------- 1. the graph's record language


class _Batches:
    """The Batch API calls add_text_batches makes, remembered."""

    def __init__(self):
        self.items = []

    def create(self, metadata=None):
        return SimpleNamespace(batch_id="batch-1", metadata=metadata)

    def add(self, batch_id, items):
        self.items.extend(items)
        start = len(self.items) - len(items)
        return [
            SimpleNamespace(episode_uuid=f"episode-{start + offset}", sequence_index=start + offset)
            for offset in range(len(items))
        ]

    def process(self, batch_id):
        return None


def _builder():
    builder = object.__new__(GraphBuilderService)
    builder.client = SimpleNamespace(batch=_Batches())
    return builder


def _sent_languages(builder):
    return [item.metadata.get("language", "<none>") for item in builder.client.batch.items]


@pytest.mark.parametrize("language", ["en", "zh"])
def test_each_chunk_states_the_language_of_the_project_that_owns_the_graph(projects, language):
    _project(language, graph_id="mirofish_hemlock")
    builder = _builder()

    builder.add_text_batches("mirofish_hemlock", SCROLL, batch_size=1)

    assert _sent_languages(builder) == [language, language]
    # The rest of each chunk's metadata is as it was.
    first = builder.client.batch.items[0].metadata
    assert first["chunk_index"] == 0 and first["chunk_sha256"] and first["mirofish_operation_id"]


def test_an_english_gathering_from_a_chinese_scroll_is_remembered_in_english(projects):
    # The scroll is Chinese, the visitor reads Chinese, the gathering is English.
    _project("en", graph_id="mirofish_hemlock", requirement=CHINESE_QUESTION)
    set_locale("zh")
    builder = _builder()

    builder.add_text_batches("mirofish_hemlock", SCROLL)

    assert _sent_languages(builder) == ["en", "en"]


def test_an_older_project_is_remembered_in_the_language_of_its_question(projects):
    _project(None, graph_id="mirofish_old", requirement=CHINESE_QUESTION)
    builder = _builder()

    builder.add_text_batches("mirofish_old", SCROLL)

    assert _sent_languages(builder) == ["zh", "zh"]


def test_the_language_given_or_the_project_named_wins_over_the_lookup(projects):
    english = _project("en", graph_id="mirofish_shared")
    chinese = _project("zh")

    given = _builder()
    given.add_text_batches("mirofish_shared", SCROLL, language="zh-CN")
    named = _builder()
    named.add_text_batches("mirofish_shared", SCROLL, project_id=chinese.project_id)

    assert _sent_languages(given) == ["zh", "zh"]
    assert _sent_languages(named) == ["zh", "zh"]
    assert graph_record_language("mirofish_shared") == english.language == "en"


def test_the_public_steps_remember_everything_in_english(projects, monkeypatch):
    monkeypatch.setenv(RECORD_LANGUAGE_ENV, "en")
    _project("zh", graph_id="mirofish_hemlock", requirement=CHINESE_QUESTION)
    builder = _builder()

    builder.add_text_batches("mirofish_hemlock", SCROLL)

    assert _sent_languages(builder) == ["en", "en"]
    assert graph_record_language("mirofish_nobody_owns") == "en"


def test_a_graph_nobody_claims_leaves_the_language_to_the_text(projects):
    _project("en", graph_id="mirofish_someone_else")
    builder = _builder()

    builder.add_text_batches("mirofish_unclaimed", SCROLL)

    assert _sent_languages(builder) == ["<none>", "<none>"]
    assert graph_record_language(None) is None


def test_projects_that_share_a_graph_and_disagree_leave_it_to_the_text(projects):
    _project("en", graph_id="mirofish_fork")
    _project("zh", graph_id="mirofish_fork")

    assert graph_record_language("mirofish_fork") is None


def test_a_missing_projects_folder_is_not_made_by_the_lookup(tmp_path, monkeypatch):
    missing = tmp_path / "no-projects-here"
    monkeypatch.setattr(ProjectManager, "PROJECTS_DIR", str(missing))

    assert graph_record_language("mirofish_hemlock") is None
    assert not missing.exists()


def test_the_legacy_build_worker_passes_the_language_on(projects, monkeypatch):
    seen = {}
    builder = object.__new__(GraphBuilderService)
    builder.task_manager = SimpleNamespace(
        update_task=lambda *a, **k: None,
        complete_task=lambda *a, **k: seen.setdefault("done", True),
        fail_task=lambda task_id, error: seen.setdefault("error", error),
    )
    monkeypatch.setattr(builder, "create_graph", lambda name: "mirofish_legacy", raising=False)
    monkeypatch.setattr(builder, "set_ontology", lambda graph_id, ontology: None, raising=False)

    def add_text_batches(graph_id, chunks, batch_size, progress_callback, **kwargs):
        seen["kwargs"] = kwargs
        return graph_builder_module.BatchSubmission("batch-1", "op", [], len(chunks))

    monkeypatch.setattr(builder, "add_text_batches", add_text_batches, raising=False)
    monkeypatch.setattr(builder, "_wait_for_batch", lambda *a, **k: [], raising=False)
    monkeypatch.setattr(
        builder, "_get_graph_info",
        lambda graph_id: graph_builder_module.GraphInfo(graph_id, 0, 0, []), raising=False,
    )

    builder._build_graph_worker(
        "task-1", "Socrates waits.", {}, "Hemlock", 500, 50, 350, project_id="proj_x", language="zh",
    )

    assert "error" not in seen, seen.get("error")
    assert seen["kwargs"] == {"language": "zh", "project_id": "proj_x"}


def test_a_missing_zep_key_is_said_in_the_readers_language(monkeypatch):
    monkeypatch.setattr(Config, "MEMORY_BACKEND", "zep")
    monkeypatch.setattr(Config, "ZEP_API_KEY", None)

    with pytest.raises(ValueError) as english:
        GraphBuilderService()
    set_locale("zh")
    with pytest.raises(ValueError) as chinese:
        GraphBuilderService()

    assert "ZEP_API_KEY" in str(english.value)
    assert not any("一" <= ch <= "鿿" for ch in str(english.value))
    assert "未配置" in str(chinese.value)


class _ExtractionModel:
    """Answers every extraction call with Socrates, remembering what it was told."""

    def __init__(self):
        self.calls = []

    def chat_json(self, messages, temperature=0.3, max_tokens=4096, max_attempts=1):
        self.calls.append(messages)
        return {
            "entities": [{
                "name": "Socrates", "type": "Entity", "aliases": ["苏格拉底"],
                "summary": "Socrates waits in the prison of Athens.", "attributes": {},
            }],
            "relations": [],
            "invalidated_facts": [],
        }


@pytest.fixture
def local_memory(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "MEMORY_BACKEND", "local", raising=False)
    monkeypatch.setattr(Config, "ZEP_API_KEY", None)
    monkeypatch.setattr(Config, "LOCAL_MEMORY_DB_PATH", str(tmp_path / "mem.sqlite3"), raising=False)
    model = _ExtractionModel()
    settings = replace(
        LocalMemorySettings(),
        llm_concurrency=1, llm_max_attempts=1, window_chars=4000, lease_seconds=60.0,
        ingestion_timeout_seconds=30.0, activity_group_wait_seconds=0.0, busy_timeout_ms=2000,
        heartbeat_seconds=0.05, dedup_pass="off",
    )
    client = LocalZep(
        db_path=tmp_path / "mem.sqlite3",
        settings=settings,
        llm_client_factory=lambda: model,
        autostart_worker=False,
        sleep=lambda _seconds: None,
    )
    register_local_memory_client(client)
    yield client, model
    clear_local_memory_clients()
    client.close()


def _extract(local_memory, graph_id):
    client, model = local_memory
    builder = GraphBuilderService()
    assert builder.client is client
    builder.create_graph("Hemlock", graph_id=graph_id)
    builder.add_text_batches(graph_id, SCROLL)
    client.worker.drain(max_seconds=20)
    assert model.calls, "the extraction never asked the model"
    system = model.calls[0][0]["content"]
    with client.store.read() as conn:
        rows = conn.execute(
            "SELECT metadata_json FROM episodes WHERE graph_id = ?", (graph_id,)
        ).fetchall()
    stored = {json.loads(row["metadata_json"]).get("language") for row in rows}
    return system, stored


def test_the_local_memory_writes_an_english_gathering_in_english(projects, local_memory):
    _project("en", graph_id="mirofish_local_en", requirement=CHINESE_QUESTION)

    system, stored = _extract(local_memory, "mirofish_local_en")

    assert stored == {"en"}
    assert "in the language of TEXT" not in system
    assert "in English" in system
    assert 'Write "name" in English' in system


def test_the_local_memory_keeps_a_chinese_gathering_in_chinese(projects, local_memory):
    _project("zh", graph_id="mirofish_local_zh", requirement=CHINESE_QUESTION)

    system, stored = _extract(local_memory, "mirofish_local_zh")

    assert stored == {"zh"}
    assert "in Simplified Chinese" in system
    assert 'Write "name" in English' not in system


def test_the_local_memory_of_an_unclaimed_graph_follows_its_text(projects, local_memory):
    system, stored = _extract(local_memory, "mirofish_local_nobody")

    assert stored == {None}
    assert "in the language of TEXT" in system


# ---------------------------------------------------------------- the routes


@pytest.fixture
def client(projects, monkeypatch):
    # The shelf's newest-Chronicle lookup reads the live uploads folder by a path of its own.
    monkeypatch.setattr(simulation_api, "_get_report_id_for_simulation", lambda simulation_id: None)
    app = Flask(__name__)
    app.config.update(TESTING=True)
    app.register_blueprint(simulation_bp, url_prefix="/api/simulation")
    return app.test_client()


# ---------------------------------------------------------------- 2. generate-profiles


class _Reader:
    def filter_defined_entities(self, graph_id, defined_entity_types=None, enrich_with_edges=True):
        return SimpleNamespace(
            filtered_count=1,
            entities=[SimpleNamespace(name="Socrates")],
            entity_types={"Person"},
        )


@pytest.fixture
def generators(monkeypatch):
    made = []

    class Generator:
        def __init__(self, **kwargs):
            made.append(kwargs)

        def generate_profiles_from_entities(self, entities, use_llm=True):
            return [SimpleNamespace(to_reddit_format=lambda: {"name": "Socrates"})]

    monkeypatch.setattr(simulation_api, "ZepEntityReader", _Reader)
    monkeypatch.setattr(simulation_api, "OasisProfileGenerator", Generator)
    return made


def _generate(client, body, accept="zh-CN"):
    response = client.post(
        "/api/simulation/generate-profiles", json=body, headers={"Accept-Language": accept},
    )
    assert response.status_code == 200, response.get_json()
    return response.get_json()["data"]


@pytest.mark.parametrize("language", ["en", "zh"])
def test_profiles_are_written_in_the_language_of_the_graphs_gathering(client, generators, language):
    _project(language, graph_id="mirofish_crowd")

    data = _generate(client, {"graph_id": "mirofish_crowd"}, accept="zh-CN" if language == "en" else "en-US")

    assert data["profiles"] == [{"name": "Socrates"}]
    assert generators == [{"language": language}]


def test_profiles_follow_the_gathering_named_not_the_thread_or_the_visitor(client, generators):
    set_locale("zh")
    english = _project("en")
    SimulationManager()._save_simulation_state(
        SimulationState(simulation_id="sim_wired_en", project_id=english.project_id, graph_id="mirofish_any")
    )

    _generate(client, {"graph_id": "mirofish_any", "simulation_id": "sim_wired_en"})
    _generate(client, {"graph_id": "mirofish_any", "project_id": english.project_id})

    assert generators == [{"language": "en"}, {"language": "en"}]


def test_profiles_for_an_unclaimed_graph_are_english_not_the_visitors(client, generators):
    _generate(client, {"graph_id": "mirofish_unclaimed"}, accept="zh-CN")

    assert generators == [{"language": "en"}]


def test_no_other_route_builds_a_generator_without_a_language():
    source = open(simulation_api.__file__, encoding="utf-8").read()

    assert source.count("OasisProfileGenerator(") == 1
    assert "OasisProfileGenerator(language=" in source
    assert "SimulationConfigGenerator(" not in source


# ---------------------------------------------------------------- 3. the rows carry the language


def _crowd(simulation_id, project, question):
    manager = SimulationManager()
    manager._save_simulation_state(SimulationState(
        simulation_id=simulation_id,
        project_id=project.project_id,
        graph_id=f"mirofish_{simulation_id}",
        status=SimulationStatus.COMPLETED,
        created_at="2026-09-26T09:00:00",
    ))
    with open(os.path.join(manager._get_simulation_dir(simulation_id), "simulation_config.json"),
              "w", encoding="utf-8") as handle:
        json.dump({"simulation_requirement": question, "time_config": {"total_simulation_hours": 3}}, handle)
    SimulationRunner._run_states.pop(simulation_id, None)


@pytest.fixture
def shelf(client):
    english = _project("en", requirement=CHINESE_QUESTION)
    chinese = _project("zh", requirement=ENGLISH_QUESTION)
    older = _project(None, requirement=CHINESE_QUESTION)
    _crowd("sim_row_en", english, CHINESE_QUESTION)
    _crowd("sim_row_zh", chinese, ENGLISH_QUESTION)
    _crowd("sim_row_old", older, CHINESE_QUESTION)
    _crowd("sim_row_en_again", english, ENGLISH_QUESTION)
    yield client
    for simulation_id in ("sim_row_en", "sim_row_zh", "sim_row_old", "sim_row_en_again"):
        SimulationRunner._run_states.pop(simulation_id, None)


EXPECTED = {"sim_row_en": "en", "sim_row_zh": "zh", "sim_row_old": "zh", "sim_row_en_again": "en"}


def _languages(response):
    assert response.status_code == 200, response.get_json()
    return {row["simulation_id"]: row["language"] for row in response.get_json()["data"]}


def test_every_history_row_carries_its_record_language(shelf):
    assert _languages(shelf.get("/api/simulation/history", headers={"Accept-Language": "en"})) == EXPECTED


def test_every_list_row_carries_its_record_language(shelf):
    assert _languages(shelf.get("/api/simulation/list", headers={"Accept-Language": "zh-CN"})) == EXPECTED


def test_one_crowd_carries_its_record_language(shelf):
    for simulation_id, language in EXPECTED.items():
        response = shelf.get(f"/api/simulation/{simulation_id}", headers={"Accept-Language": "en"})
        assert response.status_code == 200
        assert response.get_json()["data"]["language"] == language


def test_the_public_shelf_is_all_english(shelf, monkeypatch):
    monkeypatch.setenv(RECORD_LANGUAGE_ENV, "en")

    assert set(_languages(shelf.get("/api/simulation/history")).values()) == {"en"}
    assert set(_languages(shelf.get("/api/simulation/list")).values()) == {"en"}


def test_a_crowd_reads_its_project_once_per_response(shelf, monkeypatch):
    real = simulation_api.record_language
    asked = []

    def counting(**kwargs):
        asked.append(kwargs.get("project_id"))
        return real(**kwargs)

    monkeypatch.setattr(simulation_api, "record_language", counting)

    _languages(shelf.get("/api/simulation/list"))

    # Four crowds, three gatherings: the English one is read once for its two crowds.
    assert len(asked) == 3
