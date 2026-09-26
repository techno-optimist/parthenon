"""Work survives a restart: leases, the resume branch of ``/api/graph/build`` (spec §4.3, §7)."""

from __future__ import annotations

import time
from dataclasses import replace
from datetime import datetime

import pytest

import app.memory as memory_package
from app import create_app
from app.api import graph as graph_api
from app.config import Config
from app.memory import LocalZep, clear_local_memory_clients, register_local_memory_client
from app.memory.extraction import claim_window
from app.models.project import Project, ProjectStatus
from app.models.task import TaskManager, TaskStatus
from app.services.graph_builder import GraphBuilderService
from app.services.text_processor import TextProcessor

T0 = 1_800_000_000.0
PEOPLE = ["Alice", "Bruno", "Chandra", "Dmitri", "Esther", "Farouk", "Greta", "Hiro", "Imani", "Jonas"]
ORGS = ["Acme", "Globex", "Initech", "Umbrella", "Hooli", "Vandelay", "Wonka", "Stark", "Tyrell", "Cyberdyne"]
TEXT = " ".join(
    f"{person} works for {org}. their office tracks wind turbine blades every single week."
    for person, org in zip(PEOPLE, ORGS)
)


class FakeClock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> float:
        return self.now


def _wait_for(predicate, timeout=15.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


@pytest.fixture
def env(memory_db_path, monkeypatch, fake_llm, memory_settings):
    monkeypatch.setattr(Config, "MEMORY_BACKEND", "local", raising=False)
    monkeypatch.setattr(Config, "LOCAL_MEMORY_DB_PATH", str(memory_db_path), raising=False)
    monkeypatch.setattr(Config, "ZEP_API_KEY", None)
    settings = replace(memory_settings, window_chars=600, dedup_pass="off")

    def open_client(**kwargs) -> LocalZep:
        client = LocalZep(db_path=memory_db_path, settings=kwargs.pop("settings", settings),
                          llm_client_factory=lambda: fake_llm, autostart_worker=kwargs.pop("autostart", False),
                          sleep=lambda _s: None, **kwargs)
        register_local_memory_client(client)
        return client

    yield open_client, settings
    clear_local_memory_clients()


def _interrupted_build(open_client, settings, clock):
    """Submit a batch, claim its first window under a lease, then "crash" (close)."""

    first = open_client(clock=clock)
    builder = GraphBuilderService()
    assert builder.client is first
    graph_id = builder.create_graph("Resume me")
    chunks = TextProcessor.split_text(TEXT, chunk_size=500, overlap=50)
    assert len(chunks) >= 2
    submission = builder.add_text_batches(graph_id, chunks, batch_size=350)
    window = claim_window(first.store, settings, owner=first.worker.owner, clock=clock)
    assert window is not None and 0 < len(window.episodes) < len(chunks)
    first.close()
    clear_local_memory_clients()
    return graph_id, submission, window


def test_new_client_resumes_after_the_lease_expires(env):
    open_client, settings = env
    clock = FakeClock()
    graph_id, submission, window = _interrupted_build(open_client, settings, clock)

    second = open_client(clock=clock)
    summary = second.batch.get(submission.batch_id)
    assert summary.status == "processing"
    assert summary.progress.processing_items == len(window.episodes)
    assert summary.progress.percent_complete < 100.0

    # Before the lease expires the dead owner's window is left alone.
    second.worker.drain()
    assert second.batch.get(submission.batch_id).status == "processing"

    clock.now += settings.lease_seconds + 1
    stats = second.worker.drain()
    assert stats.recovered == len(window.episodes) and stats.batches_finalized == 1
    final = second.batch.get(submission.batch_id)
    assert final.status == "succeeded" and final.progress.succeeded_items == submission.item_count
    names = {node.name for node in second.graph.node.get_by_graph_id(graph_id)}
    assert set(PEOPLE) <= names


def test_background_worker_recovers_an_expired_lease_on_its_own(env):
    open_client, settings = env
    graph_id, submission, _window = _interrupted_build(open_client, settings, time.time)
    # Let the dead owner's lease run out in about a second; the restarted
    # worker's dispatcher recovers and finishes the batch without any help.
    second = open_client(autostart=True)
    with second.store.write() as conn:
        conn.execute("UPDATE episodes SET lease_until = ? WHERE extraction_status = 'processing'",
                     (time.time() + 1.0,))
    assert _wait_for(lambda: second.batch.get(submission.batch_id).status == "succeeded")
    assert {node.name for node in second.graph.node.get_by_graph_id(graph_id)} >= set(PEOPLE)


def _project(graph_id, submission) -> Project:
    now = datetime.now().isoformat()
    return Project(
        project_id="proj_resume000001",
        name="Resume me",
        status=ProjectStatus.GRAPH_BUILDING,
        created_at=now,
        updated_at=now,
        ontology={"entity_types": [], "edge_types": []},
        graph_id=graph_id,
        graph_build_task_id="task-lost-in-restart",
        zep_batch_id=submission.batch_id,
        zep_batch_operation_id=submission.operation_id,
        chunk_size=500,
        chunk_overlap=50,
    )


@pytest.fixture
def flask_client(monkeypatch):
    monkeypatch.setattr(memory_package, "start_local_memory_in_background", lambda *a, **k: None)
    flask_app = create_app()
    flask_app.config.update(TESTING=True)
    return flask_app.test_client()


def _patch_projects(monkeypatch, project):
    saved = []
    monkeypatch.setattr(graph_api.ProjectManager, "get_project", classmethod(lambda _cls, _pid: project))
    monkeypatch.setattr(graph_api.ProjectManager, "get_extracted_text", classmethod(lambda _cls, _pid: TEXT))
    monkeypatch.setattr(graph_api.ProjectManager, "save_project",
                        classmethod(lambda _cls, saved_project: saved.append(saved_project.status)))
    return saved


def test_build_endpoint_resumes_the_persisted_batch_after_restart(env, monkeypatch, flask_client):
    open_client, settings = env
    clock = FakeClock()
    graph_id, submission, _window = _interrupted_build(open_client, settings, clock)
    second = open_client(clock=clock)
    project = _project(graph_id, submission)
    saved = _patch_projects(monkeypatch, project)

    response = flask_client.post("/api/graph/build", json={"project_id": project.project_id})
    assert response.status_code == 200, response.json
    body = response.json["data"]
    assert body["resumed"] is True
    task_id = body["task_id"]

    # The build thread now polls the resumed batch; the restarted worker finishes it.
    clock.now += settings.lease_seconds + 1
    second.worker.drain()
    assert second.batch.get(submission.batch_id).status == "succeeded"
    assert _wait_for(lambda: TaskManager().get_task(task_id).status == TaskStatus.COMPLETED, timeout=20)
    task = TaskManager().get_task(task_id)
    assert task.result["zep_batch_id"] == submission.batch_id
    assert task.result["node_count"] >= len(PEOPLE)
    assert project.status == ProjectStatus.GRAPH_COMPLETED
    assert saved[-1] == ProjectStatus.GRAPH_COMPLETED


def test_a_missing_batch_is_not_resumable(env, monkeypatch, flask_client):
    open_client, _settings = env
    open_client()
    project = _project("mirofish_0123456789abcdef", type("S", (), {"batch_id": "gone", "operation_id": "op"})())
    _patch_projects(monkeypatch, project)
    response = flask_client.post("/api/graph/build", json={"project_id": project.project_id})
    assert response.status_code == 409
    assert response.json["recoverable"] is True
    assert project.status == ProjectStatus.FAILED
