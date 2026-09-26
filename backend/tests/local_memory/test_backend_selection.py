"""Choosing between Zep Cloud and the local backend (spec §1)."""

from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

import app.memory as memory_package
from app import create_app
from app.api import graph as graph_api
from app.config import Config
from app.memory import LocalZep, get_local_memory_client
from app.services.graph_builder import GraphBuilderService
from app.services.oasis_profile_generator import OasisProfileGenerator
from app.services.zep_entity_reader import ZepEntityReader
from app.services.zep_graph_memory_updater import ZepGraphMemoryUpdater
from app.services.zep_tools import ZepToolsService
from app.utils import zep

PLACEHOLDER = "PASTE_YOUR_ZEP_API_KEY_HERE"
REAL_KEY = "z_real-looking-key"


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    """Point Config at a temporary local store and close shared clients afterwards."""

    path = tmp_path / "selection.sqlite3"
    monkeypatch.setattr(Config, "LOCAL_MEMORY_DB_PATH", str(path))
    yield path
    memory_package.clear_local_memory_clients()


# ---------------------------------------------------------------------------
# Config.memory_backend()
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "mode, key, argument, expected",
    [
        ("auto", None, None, "local"),
        ("auto", "", None, "local"),
        ("auto", PLACEHOLDER, None, "local"),
        ("auto", REAL_KEY, None, "zep"),
        ("auto", None, " test-key ", "zep"),
        ("auto", PLACEHOLDER, PLACEHOLDER, "local"),
        (" AUTO ", REAL_KEY, None, "zep"),
        ("local", REAL_KEY, "test-key", "local"),
        ("zep", None, None, "zep"),
        ("", None, None, "local"),
        (None, REAL_KEY, None, "zep"),
    ],
)
def test_memory_backend_truth_table(monkeypatch, mode, key, argument, expected):
    monkeypatch.setattr(Config, "MEMORY_BACKEND", mode)
    monkeypatch.setattr(Config, "ZEP_API_KEY", key)
    assert Config.memory_backend(argument) == expected


def test_invalid_memory_backend_is_rejected(monkeypatch):
    monkeypatch.setattr(Config, "MEMORY_BACKEND", "cloud")
    with pytest.raises(ValueError, match="MEMORY_BACKEND"):
        Config.memory_backend()
    assert "MEMORY_BACKEND must be auto, local or zep" in Config.validate()
    assert zep.is_local_memory_backend() is False


# ---------------------------------------------------------------------------
# Config.validate() / warnings()
# ---------------------------------------------------------------------------


def test_validate_requires_a_zep_key_only_for_zep(monkeypatch):
    monkeypatch.setattr(Config, "LLM_API_KEY", "sk-test")
    monkeypatch.setattr(Config, "ZEP_API_KEY", None)
    monkeypatch.delenv("ZEP_API_URL", raising=False)
    for mode in ("auto", "local"):
        monkeypatch.setattr(Config, "MEMORY_BACKEND", mode)
        assert Config.validate() == []
    monkeypatch.setattr(Config, "MEMORY_BACKEND", "zep")
    assert "ZEP_API_KEY 未配置" in Config.validate()


def test_validate_reports_zep_api_url_only_for_the_cloud_backend(monkeypatch):
    monkeypatch.setattr(Config, "LLM_API_KEY", "sk-test")
    monkeypatch.setenv("ZEP_API_URL", "https://self-hosted.invalid")
    monkeypatch.setattr(Config, "MEMORY_BACKEND", "local")
    monkeypatch.setattr(Config, "ZEP_API_KEY", None)
    assert not any("ZEP_API_URL" in error for error in Config.validate())
    monkeypatch.setattr(Config, "MEMORY_BACKEND", "zep")
    monkeypatch.setattr(Config, "ZEP_API_KEY", REAL_KEY)
    assert any("ZEP_API_URL" in error for error in Config.validate())


def test_warnings(monkeypatch):
    monkeypatch.setattr(Config, "LLM_API_KEY", "sk-test")
    monkeypatch.setattr(Config, "ZEP_API_KEY", PLACEHOLDER)
    monkeypatch.setattr(Config, "MEMORY_BACKEND", "auto")
    warnings = Config.warnings()
    assert len(warnings) == 1
    assert "using the local memory backend" in warnings[0] and Config.LOCAL_MEMORY_DB_PATH in warnings[0]
    assert "MEMORY_BACKEND=zep" in warnings[0]

    monkeypatch.setattr(Config, "MEMORY_BACKEND", "local")
    assert Config.warnings() == []

    monkeypatch.setattr(Config, "MEMORY_BACKEND", "zep")
    assert any("ZEP_API_KEY is still a placeholder" in w for w in Config.warnings())

    monkeypatch.setattr(Config, "MEMORY_BACKEND", "auto")
    monkeypatch.setattr(Config, "ZEP_API_KEY", REAL_KEY)
    assert Config.warnings() == []


# ---------------------------------------------------------------------------
# get_zep_client() and helpers
# ---------------------------------------------------------------------------


def test_local_mode_returns_the_shared_local_client_even_with_zep_api_url(monkeypatch, isolated_db):
    monkeypatch.setattr(Config, "MEMORY_BACKEND", "local")
    monkeypatch.setenv("ZEP_API_URL", "https://self-hosted.invalid")
    monkeypatch.setattr(zep, "Zep", lambda **_kwargs: pytest.fail("the Cloud SDK must not be built"))

    first = zep.get_zep_client()
    second = zep.get_zep_client(timeout=5)
    assert isinstance(first, LocalZep) and first is second
    assert first.db_path == str(isolated_db)
    assert first.worker.running  # the shared client resumes work in the background
    assert get_local_memory_client() is first


def test_zep_mode_builds_the_cloud_sdk_client(monkeypatch):
    created = []
    monkeypatch.setattr(Config, "MEMORY_BACKEND", "zep")
    monkeypatch.delenv("ZEP_API_URL", raising=False)
    monkeypatch.setattr(zep, "Zep", lambda **kwargs: created.append(kwargs) or SimpleNamespace(**kwargs))
    zep.clear_zep_client_cache()
    try:
        client = zep.get_zep_client(REAL_KEY)
        assert created == [{"api_key": REAL_KEY, "base_url": zep.ZEP_CLOUD_BASE_URL,
                            "timeout": zep.ZEP_HTTP_REQUEST_TIMEOUT_SECONDS}]
        assert not isinstance(client, LocalZep)
    finally:
        zep.clear_zep_client_cache()


def test_auto_mode_with_an_explicit_key_uses_the_cloud(monkeypatch):
    monkeypatch.setattr(Config, "MEMORY_BACKEND", "auto")
    monkeypatch.setattr(Config, "ZEP_API_KEY", None)
    monkeypatch.delenv("ZEP_API_URL", raising=False)
    monkeypatch.setattr(zep, "Zep", lambda **kwargs: SimpleNamespace(**kwargs))
    zep.clear_zep_client_cache()
    try:
        assert zep.get_zep_client(" test-key ").api_key == "test-key"
    finally:
        zep.clear_zep_client_cache()


def test_clear_zep_client_cache_closes_local_clients(monkeypatch, isolated_db):
    monkeypatch.setattr(Config, "MEMORY_BACKEND", "local")
    client = zep.get_zep_client()
    zep.clear_zep_client_cache()
    assert client.closed and client.store.closed and not client.worker.running
    replacement = zep.get_zep_client()
    assert replacement is not client and not replacement.closed


def test_backend_helpers(monkeypatch):
    monkeypatch.setattr(Config, "MEMORY_BACKEND", "local")
    monkeypatch.setattr(Config, "LOCAL_MEMORY_INGESTION_TIMEOUT_SECONDS", 1800.0)
    assert zep.is_local_memory_backend() is True
    assert zep.ingestion_wait_timeout_seconds() == 1800.0
    assert zep.memory_backend_label() == "Local memory"
    monkeypatch.setattr(Config, "MEMORY_BACKEND", "zep")
    assert zep.is_local_memory_backend() is False
    assert zep.ingestion_wait_timeout_seconds() == zep.ZEP_INGESTION_WAIT_TIMEOUT_SECONDS
    assert zep.memory_backend_label() == "Zep Cloud"


def test_client_ingestion_timeout_only_trusts_numbers():
    assert zep.client_ingestion_timeout(SimpleNamespace(ingestion_wait_timeout_seconds=42.0), 600) == 42.0
    assert zep.client_ingestion_timeout(SimpleNamespace(), 600) == 600
    assert zep.client_ingestion_timeout(SimpleNamespace(ingestion_wait_timeout_seconds="soon"), 600) == 600
    assert zep.client_ingestion_timeout(SimpleNamespace(ingestion_wait_timeout_seconds=True), 600) == 600


# ---------------------------------------------------------------------------
# Service key gates (§1.4)
# ---------------------------------------------------------------------------


def _construct_services():
    GraphBuilderService()
    ZepEntityReader()
    ZepToolsService()
    ZepGraphMemoryUpdater("g1")


def test_services_need_no_key_in_local_mode(local, monkeypatch):
    monkeypatch.setattr(Config, "ZEP_API_KEY", None)
    _construct_services()
    generator = OasisProfileGenerator(api_key="sk-test", base_url="http://127.0.0.1:9/v1", graph_id="g1")
    assert generator.zep_client is local


@pytest.mark.parametrize("service", [GraphBuilderService, ZepEntityReader, ZepToolsService,
                                     lambda: ZepGraphMemoryUpdater("g1")])
def test_services_still_require_a_key_in_zep_mode(monkeypatch, service):
    monkeypatch.setattr(Config, "MEMORY_BACKEND", "zep")
    monkeypatch.setattr(Config, "ZEP_API_KEY", None)
    with pytest.raises(ValueError, match="ZEP_API_KEY"):
        service()


def test_profile_generator_skips_memory_without_a_key_in_zep_mode(monkeypatch):
    monkeypatch.setattr(Config, "MEMORY_BACKEND", "zep")
    monkeypatch.setattr(Config, "ZEP_API_KEY", None)
    generator = OasisProfileGenerator(api_key="sk-test", base_url="http://127.0.0.1:9/v1", graph_id="g1")
    assert generator.zep_client is None


# ---------------------------------------------------------------------------
# Flask endpoints (§1.4)
# ---------------------------------------------------------------------------


@pytest.fixture
def flask_client(monkeypatch):
    started = []
    monkeypatch.setattr(memory_package, "start_local_memory_in_background",
                        lambda *args, **kwargs: started.append(args) or threading.Thread())
    flask_app = create_app()
    flask_app.config.update(TESTING=True)
    client = flask_app.test_client()
    client.started = started
    return client


def test_build_is_not_rejected_for_a_missing_key_in_local_mode(local, monkeypatch, flask_client):
    monkeypatch.setattr(Config, "ZEP_API_KEY", PLACEHOLDER)
    monkeypatch.setattr(graph_api.ProjectManager, "get_project", classmethod(lambda _cls, _pid: None))
    response = flask_client.post("/api/graph/build", json={"project_id": "proj_missing"})
    assert response.status_code == 404  # reached the project lookup, no 503 key gate


def test_build_is_still_rejected_for_a_placeholder_key_in_zep_mode(monkeypatch, flask_client):
    monkeypatch.setattr(Config, "MEMORY_BACKEND", "zep")
    monkeypatch.setattr(Config, "ZEP_API_KEY", PLACEHOLDER)
    response = flask_client.post("/api/graph/build", json={"project_id": "proj_missing"})
    assert response.status_code == 503 and "ZEP_API_KEY" in response.json["error"]


def test_status_reports_the_local_backend(local, monkeypatch, flask_client):
    monkeypatch.setattr(Config, "ZEP_API_KEY", PLACEHOLDER)
    monkeypatch.setattr(Config, "LLM_API_KEY", "sk-secret-value")
    monkeypatch.setattr(Config, "LLM_BASE_URL", "https://llm.example.test/v1")
    monkeypatch.setattr(zep, "Zep", lambda **_kwargs: pytest.fail("no Zep Cloud call in local mode"))
    data = flask_client.get("/api/parthenon/status").json["data"]
    assert data["zepConfigured"] is True
    assert data["memoryBackend"] == "local"
    assert data["zepKeyValid"] is True and data["zepProblem"] is None


def test_status_in_zep_mode_keeps_the_placeholder_check(monkeypatch, flask_client):
    monkeypatch.setattr(Config, "ZEP_API_KEY", PLACEHOLDER)
    monkeypatch.setattr(Config, "LLM_BASE_URL", "https://llm.example.test/v1")
    data = flask_client.get("/api/parthenon/status").json["data"]
    assert data["zepConfigured"] is False and data["memoryBackend"] == "zep"


def test_graph_and_entity_endpoints_are_not_gated_in_local_mode(local, seed, monkeypatch, flask_client):
    monkeypatch.setattr(Config, "ZEP_API_KEY", None)
    seed.graph("g1")
    person = seed.node("g1", "Alice Chen", "Person", summary="Alice Chen is an engineer.")
    org = seed.node("g1", "Acme Corp", "Organization")
    seed.edge("g1", person, org, "WORKS_FOR", "Alice Chen works for Acme Corp.")

    data = flask_client.get("/api/graph/data/g1").json
    assert data["success"] is True and data["data"]["node_count"] == 2

    entities = flask_client.get("/api/simulation/entities/g1").json
    assert entities["success"] is True
    assert {e["name"] for e in entities["data"]["entities"]} == {"Alice Chen", "Acme Corp"}

    detail = flask_client.get(f"/api/simulation/entities/g1/{person}").json
    assert detail["success"] is True and detail["data"]["related_edges"][0]["direction"] == "outgoing"

    by_type = flask_client.get("/api/simulation/entities/g1/by-type/Person").json
    assert by_type["data"]["count"] == 1


def test_graph_data_for_an_unknown_local_graph_hides_details(local, flask_client):
    response = flask_client.get("/api/graph/data/unknown-graph")
    assert response.status_code == 500
    assert response.json["error"].startswith("Local memory request failed (HTTP 404)")


# ---------------------------------------------------------------------------
# Startup resume hook (§4.3)
# ---------------------------------------------------------------------------


def test_startup_hook_resumes_local_work(monkeypatch):
    started = []
    monkeypatch.setattr(Config, "MEMORY_BACKEND", "local")
    monkeypatch.setattr(Config, "DEBUG", False)
    monkeypatch.setattr(memory_package, "start_local_memory_in_background",
                        lambda *args, **kwargs: started.append(True))
    create_app()
    assert started == [True]


def test_startup_hook_skips_the_reloader_parent_and_the_cloud(monkeypatch):
    started = []
    monkeypatch.setattr(memory_package, "start_local_memory_in_background",
                        lambda *args, **kwargs: started.append(True))
    monkeypatch.setattr(Config, "MEMORY_BACKEND", "local")
    monkeypatch.setattr(Config, "DEBUG", True)
    monkeypatch.delenv("WERKZEUG_RUN_MAIN", raising=False)
    create_app()  # debug parent process: no worker
    monkeypatch.setattr(Config, "DEBUG", False)
    monkeypatch.setattr(Config, "MEMORY_BACKEND", "zep")
    create_app()
    monkeypatch.setattr(Config, "MEMORY_BACKEND", "bogus")
    create_app()
    assert started == []


def test_background_start_opens_the_shared_client(isolated_db, monkeypatch):
    monkeypatch.setattr(Config, "MEMORY_BACKEND", "local")
    thread = memory_package.start_local_memory_in_background()
    thread.join(10)
    client = get_local_memory_client()
    assert client.db_path == str(isolated_db) and client.worker.running
