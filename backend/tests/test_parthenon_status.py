from datetime import datetime

import httpx
import pytest
from openai import OpenAI
from zep_cloud.core.api_error import ApiError as ZepApiError

from app import create_app
from app.api import graph as graph_api
from app.api import parthenon as parthenon_api
from app.config import Config
from app.models.project import Project, ProjectStatus
from app.services.stage_oracle import StageOracle
from app.utils.llm_client import LLMClient


PLACEHOLDER_ZEP_KEY = "PASTE_YOUR_ZEP_API_KEY_HERE"
DRAFT_URL = "/api/parthenon/stage/draft"
TOPIC = "Should AI agents be allowed to vote on behalf of citizens?"
STAGE = {"topic": TOPIC, "speakers": [{"name": "Socrates"}]}

# Response headers Zep Cloud sent with the 401 of a real failed build.
ZEP_HEADERS = {
    "content-type": "text/plain; charset=utf-8",
    "server": "cloudflare",
    "cf-ray": "a40ba5bc0a4e7c38-DEN",
}


def _zep_error(status_code, body="unauthorized"):
    return ZepApiError(status_code=status_code, headers=dict(ZEP_HEADERS), body=body)


def _assert_no_zep_details(text, body="unauthorized"):
    for detail in ("headers", "cf-ray", "cloudflare", "Traceback", body):
        assert detail not in text


def _client():
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


@pytest.mark.parametrize("status_code", [401, 403])
def test_zep_auth_failure_becomes_plain_language(status_code):
    message = graph_api._public_build_error(_zep_error(status_code))
    assert "ZEP_API_KEY" in message and f"HTTP {status_code}" in message
    _assert_no_zep_details(message)


def test_wrapped_zep_auth_failure_is_still_recognised():
    try:
        try:
            raise _zep_error(401)
        except ZepApiError as error:
            raise RuntimeError(f"Zep graph create failed: {error}") from error
    except RuntimeError as wrapped:
        message = graph_api._public_build_error(wrapped)
    assert "ZEP_API_KEY" in message and "HTTP 401" in message
    _assert_no_zep_details(message)


def test_other_zep_failures_hide_provider_details():
    message = graph_api._public_build_error(_zep_error(503, body="upstream overloaded"))
    assert message.startswith("Zep Cloud request failed (HTTP 503)")
    _assert_no_zep_details(message, body="upstream overloaded")


def test_non_zep_errors_pass_through():
    assert graph_api._public_build_error(ValueError("boom")) == "boom"


def test_placeholders_are_detected(monkeypatch):
    assert Config.is_placeholder(None)
    assert Config.is_placeholder(PLACEHOLDER_ZEP_KEY)
    assert not Config.is_placeholder("z_real-looking-key")
    monkeypatch.setattr(Config, "ZEP_API_KEY", PLACEHOLDER_ZEP_KEY)
    assert any("ZEP_API_KEY" in w for w in Config.warnings())


def test_placeholder_zep_key_is_rejected_before_any_zep_call(monkeypatch):
    calls = []
    monkeypatch.setattr(Config, "ZEP_API_KEY", PLACEHOLDER_ZEP_KEY)
    monkeypatch.setattr(graph_api, "GraphBuilderService", lambda *a, **k: calls.append("zep"))
    monkeypatch.setattr(
        graph_api.ProjectManager,
        "get_project",
        classmethod(lambda _cls, _project_id: calls.append("get_project")),
    )

    response = _client().post("/api/graph/build", json={"project_id": "proj_6f1694479331"})

    assert response.status_code == 503
    assert response.json["success"] is False
    assert "ZEP_API_KEY" in response.json["error"]
    assert calls == []


def test_build_request_hides_zep_error_details(monkeypatch):
    now = datetime.now().isoformat()
    project = Project(
        project_id="proj_6f1694479331",
        name="Arrivals",
        status=ProjectStatus.FAILED,
        created_at=now,
        updated_at=now,
        ontology={"entity_types": [], "edge_types": []},
        graph_id="mirofish_0123456789abcdef",
    )

    class Builder:
        def __init__(self, **_kwargs):
            pass

        def delete_graph(self, _graph_id):
            raise _zep_error(401)

    monkeypatch.setattr(Config, "ZEP_API_KEY", "z_real-looking-key")
    monkeypatch.setattr(graph_api, "GraphBuilderService", Builder)
    monkeypatch.setattr(graph_api, "_active_graph_consumers", lambda _graph_id: [])
    monkeypatch.setattr(
        graph_api.ProjectManager,
        "get_project",
        classmethod(lambda _cls, _project_id: project),
    )
    monkeypatch.setattr(
        graph_api.ProjectManager,
        "get_extracted_text",
        classmethod(lambda _cls, _project_id: "Socrates meets an AI agent."),
    )
    monkeypatch.setattr(
        graph_api.ProjectManager, "save_project", classmethod(lambda _cls, _saved: None)
    )

    response = _client().post("/api/graph/build", json={"project_id": project.project_id})

    body = response.json
    assert response.status_code >= 400
    assert body["success"] is False
    assert "traceback" not in body
    assert "ZEP_API_KEY" in body["error"] and "HTTP 401" in body["error"]
    _assert_no_zep_details(response.get_data(as_text=True))
    # The failed delete must keep the reference so a later retry can clean up.
    assert project.graph_id == "mirofish_0123456789abcdef"


def test_status_reports_configuration_without_secrets(monkeypatch):
    monkeypatch.setattr(Config, "ZEP_API_KEY", PLACEHOLDER_ZEP_KEY)
    monkeypatch.setattr(Config, "LLM_API_KEY", "sk-secret-value")
    # Not the local bridge, so the status check makes no network call.
    monkeypatch.setattr(Config, "LLM_BASE_URL", "https://llm.example.test/v1")
    monkeypatch.setenv("PARTHENON_UPSTREAM", "openrouter")
    response = _client().get("/api/parthenon/status")
    assert response.status_code == 200
    data = response.json["data"]
    assert data["zepConfigured"] is False
    assert data["llmConfigured"] is True
    assert data["upstream"] == "openrouter"
    assert "sk-secret-value" not in response.get_data(as_text=True)


def _oracle_client(monkeypatch, handler):
    """An Oracle whose real OpenAI client talks to the bridge through a MockTransport."""
    base_url = "http://127.0.0.1:5055/v1"
    monkeypatch.setattr(Config, "LLM_BASE_URL", base_url)
    llm = LLMClient(api_key="test-key", base_url=base_url, model="grok-test")
    llm.client = OpenAI(
        api_key="test-key",
        base_url=base_url,
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    monkeypatch.setattr(parthenon_api, "StageOracle", lambda: StageOracle(llm_client=llm))
    return _client()


def test_oracle_reports_an_unreachable_provider(monkeypatch):
    def refuse(request):
        raise httpx.ConnectError("Connection refused", request=request)

    client = _oracle_client(monkeypatch, refuse)

    response = client.post(DRAFT_URL, json={"stage": STAGE, "fill": ["words"]})

    assert response.status_code == 502
    assert response.json == {
        "success": False,
        "error": "The Oracle could not reach the LLM provider.",
    }


@pytest.mark.parametrize(
    "error_body, shown",
    [
        (
            {
                "message": "Not signed in to Grok. Run npm run grok:login",
                "type": "grok_bridge_error",
                "code": "grok_not_signed_in",
            },
            "Not signed in to Grok. Run npm run grok:login",
        ),
        # Not one of the bridge's own public codes: the body may echo the prompt.
        ({"message": f"Upstream rejected: {TOPIC}", "type": "invalid_request_error"}, None),
    ],
)
def test_oracle_maps_a_bridge_401_body(monkeypatch, error_body, shown):
    requests = []

    def reject(request):
        requests.append(request)
        return httpx.Response(
            401, headers={"x-request-id": "req-bridge-7"}, json={"error": error_body}
        )

    client = _oracle_client(monkeypatch, reject)

    response = client.post(DRAFT_URL, json={"stage": STAGE, "fill": ["words"]})

    text = response.get_data(as_text=True)
    assert len(requests) == 1 and TOPIC in requests[0].content.decode()
    assert response.status_code == 502
    assert response.json["success"] is False
    assert "HTTP 401" in response.json["error"]
    assert "req-bridge-7" in response.json["error"]
    assert error_body["type"] not in text and "grok_not_signed_in" not in text
    assert TOPIC not in text
    if shown:
        assert shown in response.json["error"]


def test_oracle_rejects_an_oversized_body_before_the_llm(monkeypatch):
    requests = []

    def record(request):
        requests.append(request)
        return httpx.Response(500)

    client = _oracle_client(monkeypatch, record)
    stage = dict(STAGE, topic="x" * (1024 * 1024))

    response = client.post(DRAFT_URL, json={"stage": stage, "fill": ["words"]})

    assert response.status_code == 413
    assert response.json["success"] is False
    assert requests == []
