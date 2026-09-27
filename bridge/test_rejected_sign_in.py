"""A Grok token xAI refuses, whatever status it refuses it with.

xAI does not always answer a token it will not take with 401: it says 400 "Incorrect API key provided" (the
check saw it on the public server). In auto and on the public server that counts as a 401: one refresh and a
retry. A grant xAI will not refresh is marked revoked; a token refused even after a refresh rests while the
fallback answers, and is tried again after the rest (at once after a new sign-in). Words about permission are
not a refusal. The local grok bridge keeps its old behaviour. Temporary token files with fake tokens and
httpx.MockTransport fakes only (conftest.py keeps every test away from the owner's sign-in).
"""

import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

import grok_bridge as gb
from test_auto_grok import (
    BACKEND_REQUEST, GEMMA, IMAGE_REQUEST, NEMOTRON, OR_KEY, XAI_KEY, FakeClock, ask, chat_ok, make_jwt, no_network,
    sign_in,
)

# What api.x.ai answered the check for a token it did not accept (the key fragment is xAI's own masking).
INCORRECT_KEY = {
    "code": "Client specified an invalid argument",
    "error": "Incorrect API key provided: ey***ig. You can obtain an API key from https://console.x.ai.",
}
REFUSALS = [
    pytest.param(400, INCORRECT_KEY, id="400-incorrect-api-key"),
    pytest.param(403, {"error": {"message": "Invalid API key", "type": "invalid_request_error"}}, id="403-invalid-key"),
    pytest.param(401, {"error": {"message": "expired"}}, id="401"),
]


class Xai:
    """Fake api.x.ai (which takes only the tokens in `accepted`), auth.x.ai and openrouter.ai."""

    def __init__(self, *, refusal=(400, INCORRECT_KEY), refresh=None, accepted=()):
        self.requests = []
        self.accepted = set(accepted)
        self.refusal = refusal
        self.issued = []  # access tokens the refresh handed out
        self.refresh = refresh or self.issue

    def issue(self, accept=True):
        token = make_jwt(email="owner@example.com", n=len(self.issued))
        self.issued.append(token)
        if accept:
            self.accepted.add(token)
        return httpx.Response(200, json={"access_token": token, "refresh_token": f"refresh-{len(self.issued)}"})

    def __call__(self, request):
        self.requests.append(request)
        host, path = request.url.host, request.url.path
        if host == "auth.x.ai":
            return self.refresh()
        if host == "openrouter.ai" and path.endswith("/chat/completions"):
            return httpx.Response(200, json=chat_ok(NEMOTRON, "from openrouter"))
        if host == "api.x.ai":
            bearer = request.headers.get("authorization", "")
            if bearer == f"Bearer {XAI_KEY}":  # the xAI key fallback
                if path.endswith("/images/generations"):
                    return httpx.Response(200, json={"data": [{"url": "https://imgen.x.ai/by-key.jpg"}]})
                return httpx.Response(200, json=chat_ok("grok-4.20-0309-non-reasoning", "from the xai key"))
            if bearer.removeprefix("Bearer ") not in self.accepted:
                status, body = self.refusal
                return httpx.Response(status, json=body)
            if path.endswith("/chat/completions"):
                return httpx.Response(200, json=chat_ok(json.loads(request.content)["model"], "from grok"))
            if path.endswith("/images/generations"):
                return httpx.Response(200, json={"data": [{"url": "https://imgen.x.ai/a.jpg"}]})
        raise AssertionError(f"unexpected request to {request.url}")

    def to(self, host):
        return [r for r in self.requests if r.url.host == host]


def build(tmp_path, xai, *, fallback="openrouter", detect=True, clock=None):
    http = httpx.Client(transport=httpx.MockTransport(xai))
    path = tmp_path / "data" / "grok-oauth.json"
    grok = gb.Upstream(gb.TokenStore(path, http), http, mode="chat", sleep=lambda s: None, follow_budget=True,
                       detect_rejection=detect)
    if fallback == "openrouter":
        backup = gb.OpenRouterUpstream(OR_KEY, http, models=[NEMOTRON, GEMMA], rpm=0, sleep=lambda s: None,
                                       app_headers={})
    else:
        backup = gb.KeyedUpstream(gb.PROVIDERS["xai"], XAI_KEY, http, rpm=0, model="grok-4.20-0309-non-reasoning",
                                  sleep=lambda s: None)
    auto = gb.AutoUpstream(grok, backup, clock=clock or FakeClock(), rejected_retry_seconds=300)
    return auto, path


def saved(path):
    return json.loads(path.read_text())


# --------------------------------------------------------------------------- one refresh, then the answer


@pytest.mark.parametrize("status, body", REFUSALS)
def test_a_refused_token_is_refreshed_once_and_the_request_retried(tmp_path, status, body):
    xai = Xai(refusal=(status, body))
    auto, path = build(tmp_path, xai)
    old = sign_in(path)  # a token xAI does not take (a fresh JWT all the same: only xAI's answer says so)
    client = gb.create_app(auto).test_client()

    assert ask(client) == "from grok"
    assert len(xai.to("auth.x.ai")) == 1 and len(xai.to("api.x.ai")) == 2
    assert xai.to("api.x.ai")[-1].headers["authorization"] == f"Bearer {xai.issued[0]}"
    state = saved(path)
    assert state["access_token"] == xai.issued[0] != old["access_token"] and "revoked" not in state
    assert client.get("/health").get_json()["provider"] == "grok-subscription"


# --------------------------------------------------------------------------- what the check found


def test_a_400_for_a_grant_xai_will_not_refresh_is_answered_by_the_fallback(tmp_path):
    """The check's case: chat answers 400 "Incorrect API key provided", the refresh answers invalid_grant."""
    xai = Xai(refresh=lambda: httpx.Response(400, json={"error": "invalid_grant"}))
    auto, path = build(tmp_path, xai)
    sign_in(path)
    client = gb.create_app(auto).test_client()

    assert ask(client) == "from openrouter"  # the same request, not an error
    assert len(xai.to("api.x.ai")) == 1 and len(xai.to("auth.x.ai")) == 1
    assert saved(path)["revoked"] == "invalid_grant"
    health = client.get("/health").get_json()
    assert health["provider"] == "free" and health["grok_signed_in"] is False
    assert "grok_retry_in_seconds" not in health  # revoked is not a rest: it needs a new sign-in

    assert ask(client) == "from openrouter"
    assert len(xai.to("api.x.ai")) == 1 and len(xai.to("auth.x.ai")) == 1  # the dead grant is not tried again


def test_a_token_refused_even_after_a_refresh_rests_and_is_tried_again(tmp_path):
    clock = FakeClock()
    xai = Xai(refresh=lambda: xai.issue(accept=False))
    auto, path = build(tmp_path, xai, clock=clock)
    sign_in(path)
    client = gb.create_app(auto).test_client()

    assert ask(client) == "from openrouter"
    assert len(xai.to("api.x.ai")) == 2 and len(xai.to("auth.x.ai")) == 1
    assert "revoked" not in saved(path)  # a rest, not a sign-out: a passing fault at xAI heals by itself
    health = client.get("/health").get_json()
    assert health["provider"] == "free" and health["grok_signed_in"] is False
    assert health["grok_retry_in_seconds"] == 300 and health["imagine"] is False

    clock.now += 120
    assert ask(client) == "from openrouter"
    assert len(xai.to("api.x.ai")) == 2  # resting: xAI is not asked
    assert client.get("/health").get_json()["grok_retry_in_seconds"] == 180

    clock.now += 181
    xai.accepted.add(xai.issued[-1])  # xAI takes the token again
    assert ask(client) == "from grok"
    health = client.get("/health").get_json()
    assert health["provider"] == "grok-subscription" and "grok_retry_in_seconds" not in health


def test_a_new_sign_in_ends_the_rest_at_once(tmp_path):
    xai = Xai(refresh=lambda: xai.issue(accept=False))
    auto, path = build(tmp_path, xai)
    sign_in(path)
    client = gb.create_app(auto).test_client()
    assert ask(client) == "from openrouter"

    fresh = make_jwt(email="owner@example.com", login=2)
    xai.accepted.add(fresh)
    sign_in(path, access=fresh, refresh="refresh-new-login")  # `login` over render ssh, beside the bridge
    assert ask(client) == "from grok"
    assert "grok_retry_in_seconds" not in client.get("/health").get_json()


def test_a_refused_token_after_a_refresh_is_a_clear_401_on_the_public_grok_bridge(tmp_path, monkeypatch):
    monkeypatch.setattr(gb, "LOGIN_HINT", gb.SERVER_LOGIN_HINT)
    xai = Xai(refresh=lambda: xai.issue(accept=False))
    http = httpx.Client(transport=httpx.MockTransport(xai))
    store = gb.TokenStore(tmp_path / "grok-oauth.json", http)
    sign_in(store.path)
    upstream = gb.Upstream(store, http, mode="chat", follow_budget=True, detect_rejection=True)
    response = gb.create_app(upstream).test_client().post("/v1/chat/completions", json=BACKEND_REQUEST)
    assert response.status_code == 401
    error = response.get_json()["error"]
    assert error["code"] == "grok_not_signed_in" and "even after a refresh (HTTP 400)" in error["message"]
    assert "Incorrect API key" not in error["message"] and "ey***" not in error["message"]


def test_a_refresh_that_cannot_be_made_after_a_refusal_is_answered_by_the_fallback_and_rests(tmp_path):
    """The token is known bad and cannot be renewed now: the visitor gets an answer, and the sign-in is kept."""
    clock = FakeClock()
    xai = Xai(refresh=lambda: httpx.Response(503, text="down"))
    auto, path = build(tmp_path, xai, clock=clock)
    sign_in(path)
    client = gb.create_app(auto).test_client()
    assert ask(client) == "from openrouter"
    assert "revoked" not in saved(path)
    assert client.get("/health").get_json()["grok_retry_in_seconds"] == 300

    clock.now += 301
    xai.refresh = xai.issue  # xAI's sign-in service is back
    assert ask(client) == "from grok"
    assert len(xai.to("auth.x.ai")) == 2


@pytest.mark.parametrize("reply", [
    lambda: httpx.Response(400, text="<html>Bad Request</html>"),
    lambda: httpx.Response(401, json={"error": {"message": "nope"}}),
])
def test_a_refresh_answered_with_no_grant_error_is_unavailable_not_a_crash(tmp_path, reply):
    """Before, a token endpoint's HTML page or nested error made the bridge crash (unhashable dict)."""
    xai = Xai(refresh=reply)
    http = httpx.Client(transport=httpx.MockTransport(xai))
    store = gb.TokenStore(tmp_path / "grok-oauth.json", http)
    state = sign_in(store.path)
    with pytest.raises(gb.RefreshUnavailable, match=r"xAI token refresh failed: HTTP 40[01]$"):
        store.access_token(rejected=state["access_token"])
    assert "revoked" not in saved(store.path)

    auto, path = build(tmp_path / "auto", xai)
    sign_in(path)
    assert ask(gb.create_app(auto).test_client()) == "from openrouter"  # refused, then no refresh: the fallback


def test_an_expiring_token_whose_refresh_cannot_be_made_is_still_a_503(tmp_path):
    """Unchanged: without a refusal from xAI, a refresh that cannot be made is not a reason to leave Grok."""
    xai = Xai(refresh=lambda: httpx.Response(503, text="down"))
    auto, path = build(tmp_path, xai)
    sign_in(path, access=make_jwt(expires_in=-60))
    client = gb.create_app(auto).test_client()
    response = client.post("/v1/chat/completions", json=BACKEND_REQUEST)
    assert response.status_code == 503 and response.get_json()["error"]["code"] == "grok_refresh_unavailable"
    assert xai.to("openrouter.ai") == [] and xai.to("api.x.ai") == []
    assert client.get("/health").get_json()["provider"] == "grok-subscription"


# --------------------------------------------------------------------------- portraits, film and voice


def test_a_refused_token_on_a_portrait_falls_back_to_an_xai_key(tmp_path):
    xai = Xai(refresh=lambda: xai.issue(accept=False))
    auto, path = build(tmp_path, xai, fallback="xai")
    sign_in(path)
    response = gb.create_app(auto).test_client().post("/v1/images/generations", json=IMAGE_REQUEST)
    assert response.status_code == 200
    assert response.get_json()["data"][0]["url"] == "https://imgen.x.ai/by-key.jpg"


def test_a_refused_token_on_a_portrait_without_an_xai_key_is_a_calm_501(tmp_path):
    xai = Xai(refresh=lambda: httpx.Response(400, json={"error": "invalid_grant"}))
    auto, path = build(tmp_path, xai)
    sign_in(path)
    client = gb.create_app(auto).test_client()
    response = client.post("/v1/images/generations", json=IMAGE_REQUEST)
    assert response.status_code == 501 and response.get_json()["error"]["code"] == "imagine_unavailable"
    health = client.get("/health").get_json()
    assert health["imagine"] is False and health["voice"] is False


# --------------------------------------------------------------------------- what is not a refusal


@pytest.mark.parametrize("status, body", [
    (400, {"code": "Client specified an invalid argument", "error": "Invalid 'max_tokens': must be at least 1"}),
    (400, {"error": {"message": "The model grok-9 does not exist or your team does not have access to it"}}),
    (400, {"error": {"message": "This model's maximum prompt length is 131072 but the request has 200000 tokens"}}),
    (403, {"error": "chat completions not allowed for this token"}),
    (403, {"code": "The caller does not have permission to execute the specified operation",
           "error": "Your team does not have permission to use grok-4.7"}),
])
def test_words_about_the_request_or_permission_are_passed_through(tmp_path, status, body):
    xai = Xai(refusal=(status, body))
    auto, path = build(tmp_path, xai)
    sign_in(path)
    client = gb.create_app(auto).test_client()
    response = client.post("/v1/chat/completions", json=BACKEND_REQUEST)
    assert response.status_code == status and response.get_json() == body
    assert xai.to("auth.x.ai") == [] and xai.to("openrouter.ai") == []
    assert client.get("/health").get_json()["provider"] == "grok-subscription"


@pytest.mark.parametrize("status, body, refused", [
    (401, {}, True),
    (400, INCORRECT_KEY, True),
    (400, {"error": {"code": "invalid_api_key", "message": "bad"}}, True),
    (403, {"error": {"type": "authentication_error", "message": "Invalid bearer token"}}, True),
    (400, {"error": "invalid_token"}, True),
    (403, {"code": "Unauthenticated", "error": "The request does not have valid authentication credentials"}, True),
    (400, {"error": "Access token has expired"}, True),
    (400, {"error": "No API key provided"}, True),
    (400, {"error": "Invalid 'max_tokens'"}, False),
    (400, {"error": {"message": "invalid tool_choice", "type": "invalid_request_error"}}, False),
    (403, {"error": "chat completions not allowed for this token"}, False),
    (403, {"code": "The caller does not have permission to execute the specified operation"}, False),
    (404, {"error": "Incorrect API key provided"}, False),
    (429, {"error": "Incorrect API key provided"}, False),
    (500, INCORRECT_KEY, False),
])
def test_what_counts_as_xai_refusing_the_token(status, body, refused):
    assert gb._token_rejected(httpx.Response(status, json=body)) is refused


def test_a_refusal_that_is_not_json_is_read_as_text():
    assert gb._token_rejected(httpx.Response(400, text="Unauthenticated: bad credentials")) is True
    assert gb._token_rejected(httpx.Response(400, text="Bad Request")) is False


# --------------------------------------------------------------------------- the local bridge is unchanged


def test_the_local_grok_bridge_passes_a_400_through_as_before(tmp_path):
    xai = Xai()
    http = httpx.Client(transport=httpx.MockTransport(xai))
    store = gb.TokenStore(tmp_path / "grok-oauth.json", http)
    sign_in(store.path)
    status, data = gb.Upstream(store, http, mode="chat").chat_completion({"model": "grok-4.7", "messages": []})
    assert (status, data) == (400, INCORRECT_KEY)
    assert xai.to("auth.x.ai") == [] and len(xai.to("api.x.ai")) == 1


def test_the_local_grok_bridge_returns_a_second_401_as_before(tmp_path):
    xai = Xai(refusal=(401, {"error": {"message": "expired"}}), refresh=lambda: xai.issue(accept=False))
    http = httpx.Client(transport=httpx.MockTransport(xai))
    store = gb.TokenStore(tmp_path / "grok-oauth.json", http)
    sign_in(store.path)
    status, data = gb.Upstream(store, http, mode="chat").chat_completion({"model": "grok-4.7", "messages": []})
    assert status == 401 and data == {"error": {"message": "expired"}}
    assert len(xai.to("auth.x.ai")) == 1 and len(xai.to("api.x.ai")) == 2


def test_only_auto_and_the_public_server_treat_a_400_as_a_refusal(monkeypatch):
    http = httpx.Client(transport=httpx.MockTransport(no_network))
    monkeypatch.setattr(gb, "PUBLIC", False)
    assert gb.build_upstream("grok", http).detect_rejection is False
    assert gb.build_upstream("auto", http).grok.detect_rejection is True
    monkeypatch.setattr(gb, "PUBLIC", True)
    assert gb.build_upstream("grok", http).detect_rejection is True


@pytest.mark.parametrize("value, seconds", [("90", 90.0), (None, 300.0), ("0", 1.0)])
def test_the_rest_length_comes_from_the_environment(value, seconds):
    """GROK_BRIDGE_REJECTED_RETRY_SECONDS as a fresh bridge process reads it (not from the .env)."""
    child = {k: v for k, v in os.environ.items() if k != "GROK_BRIDGE_REJECTED_RETRY_SECONDS"}
    if value is not None:
        child["GROK_BRIDGE_REJECTED_RETRY_SECONDS"] = value
    script = (
        "import dotenv; dotenv.load_dotenv = lambda *a, **k: False\n"
        "import grok_bridge as gb\n"
        "print(gb.REJECTED_RETRY_SECONDS)\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", script], cwd=Path(gb.__file__).parent, env=child,
        capture_output=True, text=True, timeout=60, check=True,
    ).stdout
    assert float(out.strip().splitlines()[-1]) == seconds
    assert gb.AutoUpstream.__init__.__kwdefaults__["rejected_retry_seconds"] == gb.REJECTED_RETRY_SECONDS


# --------------------------------------------------------------------------- what the owner sees


def test_the_rest_is_logged_once_without_any_token_or_xais_words(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    xai = Xai(refresh=lambda: xai.issue(accept=False))
    auto, path = build(tmp_path, xai)
    state = sign_in(path)
    client = gb.create_app(auto).test_client()
    ask(client)
    ask(client)
    messages = [r.getMessage() for r in caplog.records]
    assert sum("a refresh did not give a token it takes" in m for m in messages) == 1
    assert sum("refreshing it once" in m for m in messages) == 1
    for secret in (state["access_token"], state["refresh_token"], *xai.issued, "ey***ig", "refresh-1"):
        assert secret not in caplog.text


def test_status_live_explains_a_rest(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(gb, "UPSTREAM", "auto")
    monkeypatch.setattr(gb, "PUBLIC", False)
    for name in ("XAI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", OR_KEY)
    monkeypatch.setattr(gb, "_running_bridge_health", lambda: {
        "provider": "free", "imagine": False, "voice": False, "grok_signed_in": False, "grok_retry_in_seconds": 240,
    })
    sign_in(gb.TOKEN_FILE)
    gb.cmd_status(SimpleNamespace(live=True))
    out = capsys.readouterr().out
    assert "Running:      free" in out
    assert "xAI refused the Grok sign-in and a refresh did not fix it; the bridge tries it again in 240s" in out
    assert "does not see this sign-in" not in out
