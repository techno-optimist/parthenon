"""PARTHENON_UPSTREAM=auto with the Grok subscription first.

The token file is read again without a restart (a sign-in that appears is served on the next request, one that
is deleted or revoked falls back), /health says which provider serves, the server's refresh rotates only its
own file, login and status work with GROK_BRIDGE_TOKEN_FILE, and each upstream attempt fits inside the caller's
budget. Temporary token files with fake tokens and httpx.MockTransport fakes only: no network, and never the
owner's sign-in (conftest.py points TOKEN_FILE at a temporary file for every test).
"""

import base64
import json
import logging
import os
import stat
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

import grok_bridge as gb


TOKEN_ENDPOINT = "https://auth.x.ai/oauth2/token"
OR_KEY = "sk-or-v1-test-secret-0123456789abcdef"
XAI_KEY = "xai-test-secret-0123456789abcdefABCDEF"
NEMOTRON = "nvidia/nemotron-3-super-120b-a12b:free"
GEMMA = "google/gemma-4-31b-it:free"
BACKEND_REQUEST = {"model": "parthenon-free", "messages": [{"role": "user", "content": "Speak, Socrates."}]}
IMAGE_REQUEST = {"model": "grok-imagine-image-2.0", "prompt": "A marble agora at dusk", "n": 1}
MP3 = b"ID3\x04\x00\x00\x00" + bytes(range(64))


def make_jwt(expires_in: float = 3600, **claims) -> str:
    def encode(obj):
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()

    return f"{encode({'alg': 'none'})}.{encode({'exp': time.time() + expires_in, **claims})}.sig"


def no_network(request):
    raise AssertionError(f"unexpected request to {request.url}")


def sign_in(path: Path, *, access=None, refresh="refresh-server-1", **extra):
    """What `login` leaves behind, written by another TokenStore, as the login process would."""
    other_process = gb.TokenStore(path, httpx.Client(transport=httpx.MockTransport(no_network)))
    state = {
        "access_token": access or make_jwt(email="owner@example.com"),
        "refresh_token": refresh,
        "token_endpoint": TOKEN_ENDPOINT,
        **extra,
    }
    with other_process.file_lock():
        other_process.save(state)
    return state


def chat_ok(model, content):
    return {
        "id": "chatcmpl-1", "object": "chat.completion", "created": 1, "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4},
    }


class World:
    """Fake api.x.ai, auth.x.ai and openrouter.ai that record every request."""

    def __init__(self, refresh_reply=None):
        self.requests = []
        self.refresh_reply = refresh_reply or (
            lambda: httpx.Response(200, json={"access_token": make_jwt(email="owner@example.com"),
                                              "refresh_token": "refresh-server-2"})
        )

    def __call__(self, request):
        self.requests.append(request)
        host, path = request.url.host, request.url.path
        if host == "auth.x.ai":
            return self.refresh_reply()
        if host == "openrouter.ai" and path.endswith("/chat/completions"):
            return httpx.Response(200, json=chat_ok(NEMOTRON, "from openrouter"))
        if host == "api.x.ai":
            if path.endswith("/chat/completions"):
                return httpx.Response(200, json=chat_ok(json.loads(request.content)["model"], "from grok"))
            if path.endswith("/images/generations"):
                return httpx.Response(200, json={"data": [{"url": "https://imgen.x.ai/a.jpg"}]})
            if path.endswith("/tts"):
                return httpx.Response(200, content=MP3, headers={"content-type": "audio/mpeg"})
            if path.endswith("/models"):
                return httpx.Response(200, json={"object": "list", "data": [{"id": "grok-4.7"}]})
        raise AssertionError(f"unexpected request to {request.url}")

    def to(self, host):
        return [r for r in self.requests if r.url.host == host]


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def make_auto(tmp_path, world, *, fallback="openrouter", **kwargs):
    http = httpx.Client(transport=httpx.MockTransport(world))
    path = tmp_path / "data" / "grok-oauth.json"
    grok = gb.Upstream(gb.TokenStore(path, http), http, mode="chat", sleep=lambda s: None, follow_budget=True)
    if fallback == "openrouter":
        backup = gb.OpenRouterUpstream(OR_KEY, http, models=[NEMOTRON, GEMMA], rpm=0, sleep=lambda s: None,
                                       app_headers={})
    else:
        backup = gb.KeyedUpstream(gb.PROVIDERS["xai"], XAI_KEY, http, rpm=0, model="grok-4.20-0309-non-reasoning",
                                  sleep=lambda s: None)
    return gb.AutoUpstream(grok, backup, **kwargs), path


def ask(client, body=BACKEND_REQUEST, **headers):
    response = client.post("/v1/chat/completions", json=body, headers=headers)
    assert response.status_code == 200, response.get_json()
    return response.get_json()["choices"][0]["message"]["content"]


# --------------------------------------------------------------------------- switching without a restart


def test_no_sign_in_serves_the_fallback(tmp_path):
    world = World()
    auto, path = make_auto(tmp_path, world)
    client = gb.create_app(auto).test_client()

    assert ask(client) == "from openrouter"
    assert world.to("api.x.ai") == [] and world.to("auth.x.ai") == []
    health = client.get("/health").get_json()
    assert health["provider"] == "free" and health["upstream"] == "openrouter"
    assert health["imagine"] is False and health["voice"] is False
    assert health["auto"] is True and health["grok_signed_in"] is False and health["fallback"] == "free"
    assert "signed_in" not in health  # the backend reads signed_in false as "the LLM is not configured"
    assert health["api_key_set"] is True
    assert not path.exists()


def test_a_sign_in_that_appears_is_served_on_the_next_request(tmp_path):
    world = World()
    auto, path = make_auto(tmp_path, world)
    client = gb.create_app(auto).test_client()
    assert ask(client) == "from openrouter"
    assert client.post("/v1/images/generations", json=IMAGE_REQUEST).status_code == 501

    state = sign_in(path)  # `login` in another process, beside the running bridge

    assert ask(client) == "from grok"
    (grok_call,) = world.to("api.x.ai")
    assert grok_call.headers["authorization"] == f"Bearer {state['access_token']}"
    health = client.get("/health").get_json()
    assert health["provider"] == "grok-subscription" and health["upstream"] == "grok"
    assert health["imagine"] is True and health["voice"] is True
    assert health["signed_in"] is True and health["grok_signed_in"] is True
    assert health["model"] == "grok-4.7" and health["fallback"] == "free"

    image = client.post("/v1/images/generations", json=IMAGE_REQUEST)
    assert image.status_code == 200
    assert world.to("api.x.ai")[-1].url.path == "/v1/images/generations"
    voice = client.post("/v1/tts", json={"text": "The city spoke.", "voice_id": "eve"})
    assert voice.status_code == 200 and voice.data == MP3
    assert len(world.to("openrouter.ai")) == 1  # only the request before the sign-in


def test_a_deleted_sign_in_falls_back_on_the_next_request(tmp_path):
    world = World()
    auto, path = make_auto(tmp_path, world)
    client = gb.create_app(auto).test_client()
    sign_in(path)
    assert ask(client) == "from grok"

    path.unlink()  # or `logout`

    assert ask(client) == "from openrouter"
    assert client.get("/health").get_json()["provider"] == "free"
    image = client.post("/v1/images/generations", json=IMAGE_REQUEST)
    assert image.status_code == 501
    assert image.get_json()["error"] == {
        "message": gb.AUTO_IMAGINE_UNAVAILABLE, "type": "grok_bridge_error", "code": "imagine_unavailable",
    }

    sign_in(path, refresh="refresh-server-9")  # signing in again switches back, still without a restart
    assert ask(client) == "from grok"


def test_logout_falls_back(tmp_path):
    world = World()
    auto, path = make_auto(tmp_path, world)
    client = gb.create_app(auto).test_client()
    sign_in(path)
    assert ask(client) == "from grok"
    assert gb.TokenStore(path, httpx.Client(transport=httpx.MockTransport(no_network))).delete() is True
    assert ask(client) == "from openrouter"


def test_a_revoked_sign_in_falls_back(tmp_path):
    world = World()
    auto, path = make_auto(tmp_path, world)
    sign_in(path, revoked="invalid_grant")
    client = gb.create_app(auto).test_client()
    assert ask(client) == "from openrouter"
    assert world.to("api.x.ai") == [] and world.to("auth.x.ai") == []


def test_a_grant_xai_refuses_to_refresh_is_answered_by_the_fallback(tmp_path):
    world = World(refresh_reply=lambda: httpx.Response(400, json={"error": "invalid_grant"}))
    auto, path = make_auto(tmp_path, world)
    sign_in(path, access=make_jwt(expires_in=-60))
    client = gb.create_app(auto).test_client()

    assert ask(client) == "from openrouter"  # the same request, not an error
    assert len(world.to("auth.x.ai")) == 1 and world.to("api.x.ai") == []
    assert json.loads(path.read_text())["revoked"] == "invalid_grant"

    assert ask(client) == "from openrouter"
    assert len(world.to("auth.x.ai")) == 1  # the dead grant is not tried again
    assert client.get("/health").get_json()["provider"] == "free"


def test_a_transient_refresh_failure_is_not_a_fallback(tmp_path):
    world = World(refresh_reply=lambda: httpx.Response(503, text="down"))
    auto, path = make_auto(tmp_path, world)
    sign_in(path, access=make_jwt(expires_in=-60))
    response = gb.create_app(auto).test_client().post("/v1/chat/completions", json=BACKEND_REQUEST)
    assert response.status_code == 503
    assert response.get_json()["error"]["code"] == "grok_refresh_unavailable"
    assert world.to("openrouter.ai") == []


@pytest.mark.parametrize("asked, sent", [
    ("parthenon-free", "grok-4.7"),
    ("gpt-4o-mini", "grok-4.7"),
    (None, "grok-4.7"),
    ("grok-4.7", "grok-4.7"),
    ("grok-4.20-0309-non-reasoning", "grok-4.20-0309-non-reasoning"),
])
def test_on_the_subscription_a_model_that_is_not_groks_is_sent_as_grok_model(tmp_path, asked, sent):
    world = World()
    auto, path = make_auto(tmp_path, world)
    sign_in(path)
    body = {**BACKEND_REQUEST, "model": asked}
    status, data = auto.chat_completion(body)
    assert status == 200 and data["model"] == sent
    assert json.loads(world.to("api.x.ai")[0].content)["model"] == sent
    assert body["model"] == asked  # the caller's request is never changed


def test_grok_model_can_be_chosen(tmp_path):
    world = World()
    auto, path = make_auto(tmp_path, world, grok_model="grok-4.20-0309-non-reasoning")
    sign_in(path)
    auto.chat_completion(BACKEND_REQUEST)
    assert json.loads(world.to("api.x.ai")[0].content)["model"] == "grok-4.20-0309-non-reasoning"


def test_an_xai_key_fallback_keeps_portraits_and_voice_without_a_sign_in(tmp_path):
    world = World()
    auto, path = make_auto(tmp_path, world, fallback="xai")
    client = gb.create_app(auto).test_client()
    health = client.get("/health").get_json()
    assert health["provider"] == "grok" and health["imagine"] is True and health["fallback"] == "grok"

    assert client.post("/v1/images/generations", json=IMAGE_REQUEST).status_code == 200
    assert world.to("api.x.ai")[-1].headers["authorization"] == f"Bearer {XAI_KEY}"

    state = sign_in(path)
    assert client.post("/v1/images/generations", json=IMAGE_REQUEST).status_code == 200
    assert world.to("api.x.ai")[-1].headers["authorization"] == f"Bearer {state['access_token']}"


def test_models_follow_the_sign_in(tmp_path):
    world = World()
    auto, path = make_auto(tmp_path, world, fallback="xai")
    client = gb.create_app(auto).test_client()
    assert client.get("/v1/models").get_json()["data"][0]["id"] == "grok-4.20-0309-non-reasoning"
    sign_in(path)
    assert client.get("/v1/models").get_json()["data"][0]["id"] == "grok-4.7"


def test_switches_are_logged_once_without_any_token(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    world = World()
    auto, path = make_auto(tmp_path, world)
    client = gb.create_app(auto).test_client()
    ask(client)
    ask(client)
    state = sign_in(path)
    ask(client)
    ask(client)
    path.unlink()
    ask(client)
    messages = [r.getMessage() for r in caplog.records]
    assert sum("No usable Grok sign-in" in m for m in messages) == 2
    assert sum("Grok sign-in found" in m for m in messages) == 1
    assert any("owner@example.com" in m for m in messages)
    assert state["access_token"] not in caplog.text and state["refresh_token"] not in caplog.text


# --------------------------------------------------------------------------- the token file


def test_a_refresh_rotates_only_the_servers_own_file(tmp_path):
    """Two holders of one grant log each other out: the server refreshes its own grant, in its own file."""
    macs = tmp_path / "mac" / "grok-oauth.json"
    sign_in(macs, refresh="refresh-mac")
    mac_bytes, mac_stat = macs.read_bytes(), macs.stat()
    mac_folder = sorted(p.name for p in macs.parent.iterdir())

    world = World()
    auto, servers = make_auto(tmp_path, world)
    sign_in(servers, access=make_jwt(expires_in=30, email="owner@example.com"), refresh="refresh-server-1")
    client = gb.create_app(auto).test_client()
    assert ask(client) == "from grok"

    (refresh,) = world.to("auth.x.ai")
    sent = dict(httpx.QueryParams(refresh.content.decode()))
    assert sent["refresh_token"] == "refresh-server-1" and sent["grant_type"] == "refresh_token"
    saved = json.loads(servers.read_text())
    assert saved["refresh_token"] == "refresh-server-2"
    assert stat.S_IMODE(servers.stat().st_mode) == 0o600
    assert world.to("api.x.ai")[0].headers["authorization"] == f"Bearer {saved['access_token']}"

    assert macs.read_bytes() == mac_bytes
    assert macs.stat().st_mtime_ns == mac_stat.st_mtime_ns and macs.stat().st_ino == mac_stat.st_ino
    assert sorted(p.name for p in macs.parent.iterdir()) == mac_folder


def test_the_store_rereads_a_file_rewritten_in_place_within_one_mtime_tick(tmp_path):
    path = tmp_path / "grok-oauth.json"
    store = gb.TokenStore(path, httpx.Client(transport=httpx.MockTransport(no_network)))
    path.write_text(json.dumps({"access_token": "a.a.a", "refresh_token": "r1"}))
    os.chmod(path, 0o600)
    before = path.stat()
    assert store.load()["refresh_token"] == "r1"

    path.write_text(json.dumps({"access_token": "b.b.b", "refresh_token": "r2"}))  # same size, same inode
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))  # and the same mtime
    assert path.stat().st_mtime_ns == before.st_mtime_ns and path.stat().st_size == before.st_size

    assert store.load()["refresh_token"] == "r2"


@pytest.mark.parametrize("content, problem", [
    ("{not json", "is not valid JSON"),
    ('["a list"]', "does not hold a sign-in"),
])
def test_a_broken_file_is_no_sign_in_and_is_tried_again(tmp_path, content, problem):
    world = World()
    auto, path = make_auto(tmp_path, world)
    path.parent.mkdir(parents=True)
    path.write_text(content)
    client = gb.create_app(auto).test_client()

    assert ask(client) == "from openrouter"
    assert client.get("/health").status_code == 200
    assert auto.store.problem == problem

    sign_in(path)
    assert ask(client) == "from grok"
    assert auto.store.problem is None


@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root reads any file")
def test_a_file_the_bridge_cannot_read_is_no_sign_in_until_it_can(tmp_path):
    world = World()
    auto, path = make_auto(tmp_path, world)
    sign_in(path)
    os.chmod(path, 0o000)
    try:
        client = gb.create_app(auto).test_client()
        assert ask(client) == "from openrouter"
        assert "cannot be read" in auto.store.problem
        os.chmod(path, 0o600)  # what the entrypoint does for a file root left behind
        assert ask(client) == "from grok"
    finally:
        os.chmod(path, 0o600)


def test_a_lock_file_left_read_only_by_another_user_still_locks(tmp_path):
    world = World()
    auto, path = make_auto(tmp_path, world)
    sign_in(path, access=make_jwt(expires_in=30))
    lock = path.with_name(path.name + ".lock")
    os.chmod(lock, 0o400)
    try:
        assert auto.store.access_token() != ""
        assert json.loads(path.read_text())["refresh_token"] == "refresh-server-2"
    finally:
        os.chmod(lock, 0o600)


def test_saving_never_leaves_a_file_others_can_read(tmp_path):
    path = tmp_path / "grok-oauth.json"
    stale = path.with_name(path.name + ".tmp")  # what an older bridge wrote through, left behind as 0644
    stale.write_text("{}")
    os.chmod(stale, 0o644)
    sign_in(path)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp") and p != stale] == []


def test_root_hands_the_sign_in_to_the_folders_owner(tmp_path, monkeypatch):
    """A `login` run as root over `render ssh` must still leave a file the service user can read."""
    chowns = []
    monkeypatch.setattr(gb.os, "geteuid", lambda: 0)
    monkeypatch.setattr(gb.os, "chown", lambda path, uid, gid: chowns.append((Path(path), uid, gid)))
    folder = tmp_path / "data"
    folder.mkdir()
    owner = folder.stat()
    sign_in(folder / "grok-oauth.json")
    named = {p.name for p, _, _ in chowns}
    assert "grok-oauth.json.lock" in named
    assert any(name.startswith(".grok-oauth.json.") and name.endswith(".tmp") for name in named)
    assert {(uid, gid) for _, uid, gid in chowns} == {(owner.st_uid, owner.st_gid)}


def test_nobody_but_root_changes_owners(tmp_path, monkeypatch):
    chowns = []
    monkeypatch.setattr(gb.os, "chown", lambda *a: chowns.append(a))
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        monkeypatch.setattr(gb.os, "geteuid", lambda: 1000)
    sign_in(tmp_path / "grok-oauth.json")
    assert chowns == []


@pytest.mark.parametrize("saved, usable", [
    ({"access_token": "a.b.c", "refresh_token": "r"}, True),
    ({"access_token": make_jwt(expires_in=-60), "refresh_token": "r"}, True),  # refreshes on the next request
    ({"access_token": make_jwt(expires_in=600)}, True),
    ({"access_token": make_jwt(expires_in=-60)}, False),  # expired and nothing to refresh it with
    ({"access_token": "a.b.c", "refresh_token": "r", "revoked": "invalid_grant"}, False),
    ({"refresh_token": "r"}, False),
])
def test_what_counts_as_a_usable_sign_in(tmp_path, saved, usable):
    path = tmp_path / "grok-oauth.json"
    path.write_text(json.dumps(saved))
    assert (gb.usable_sign_in(path) is not None) is usable


@pytest.mark.parametrize("signed_in, environ, expected", [
    (False, {}, "openrouter"),
    (False, {"OPENAI_API_KEY": "o"}, "openai"),
    (True, {}, "grok"),
    (True, {"XAI_API_KEY": "x"}, "grok"),
])
def test_auto_resolves_to_grok_while_the_token_file_is_usable(tmp_path, signed_in, environ, expected):
    path = tmp_path / "grok-oauth.json"
    if signed_in:
        sign_in(path)
    assert gb.resolve_upstream("auto", environ, token_file=path) == expected
    assert gb.resolve_upstream("openrouter", environ, token_file=path) == "openrouter"
    assert gb.resolve_upstream("auto", environ) == gb.resolve_fallback(environ)  # no file: no Grok


def _imported(**env):
    """TOKEN_FILE and GROK_MODEL as a fresh bridge process computes them from `env` (not from the .env)."""
    child = {k: v for k, v in os.environ.items() if k not in ("GROK_BRIDGE_TOKEN_FILE", "GROK_MODEL")}
    child.update(env)
    script = (
        "import dotenv; dotenv.load_dotenv = lambda *a, **k: False\n"
        "import json, grok_bridge as gb\n"
        "print(json.dumps({'token_file': str(gb.TOKEN_FILE), 'grok_model': gb.GROK_MODEL}))\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", script], cwd=Path(gb.__file__).parent, env=child,
        capture_output=True, text=True, timeout=60, check=True,
    ).stdout
    return json.loads(out.strip().splitlines()[-1])


def test_the_token_file_and_grok_model_come_from_the_environment():
    server = _imported(GROK_BRIDGE_TOKEN_FILE="/data/grok-oauth.json", GROK_MODEL="grok-5")
    assert server == {"token_file": "/data/grok-oauth.json", "grok_model": "grok-5"}
    local = _imported()
    assert local["token_file"] == str(Path("~/.config/parthenon/grok-oauth.json").expanduser())
    assert local["grok_model"] == "grok-4.7"


# --------------------------------------------------------------------------- the caller's budget


def timed_grok(tmp_path, handler, **kwargs):
    http = httpx.Client(transport=httpx.MockTransport(handler), timeout=httpx.Timeout(gb.UPSTREAM_TIMEOUT))
    store = gb.TokenStore(tmp_path / "grok-oauth.json", http)
    sign_in(store.path)
    sleeps = []
    kwargs.setdefault("follow_budget", True)
    return gb.Upstream(store, http, mode="chat", sleep=sleeps.append, clock=kwargs.pop("clock", FakeClock()),
                       **kwargs), sleeps


def recorded_timeouts(seen):
    return [(r.extensions["timeout"]["read"], r.extensions["timeout"]["connect"]) for r in seen]


@pytest.mark.parametrize("budget, read", [(75, 75), (230, 230), (590, gb.UPSTREAM_TIMEOUT)])
def test_each_attempt_times_out_when_the_caller_stops_reading(tmp_path, budget, read):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=chat_ok("grok-4.7", "ok"))

    upstream, _ = timed_grok(tmp_path, handler)
    assert upstream.chat_completion({"model": "grok-4.7", "messages": []}, budget)[0] == 200
    assert recorded_timeouts(seen) == [(read, gb.CONNECT_TIMEOUT)]


def test_without_a_budget_the_clients_own_timeout_is_kept(tmp_path):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=chat_ok("grok-4.7", "ok"))

    upstream, _ = timed_grok(tmp_path, handler)
    upstream.chat_completion({"model": "grok-4.7", "messages": []})
    assert recorded_timeouts(seen) == [(gb.UPSTREAM_TIMEOUT, gb.UPSTREAM_TIMEOUT)]


def test_the_local_grok_bridge_keeps_its_timeouts_and_retries_whatever_the_budget(tmp_path):
    """PARTHENON_UPSTREAM=grok without PARTHENON_PUBLIC behaves exactly as before: a budget only bounds the
    wait for a slot."""
    seen = []
    replies = iter([httpx.Response(429, headers={"retry-after": "40"}, json={"error": "slow down"}),
                    httpx.Response(200, json=chat_ok("grok-4.7", "ok"))])

    def handler(request):
        seen.append(request)
        return next(replies)

    upstream, sleeps = timed_grok(tmp_path, handler, follow_budget=False)
    status, _ = upstream.chat_completion({"model": "grok-4.7", "messages": []}, budget=30)
    assert status == 200 and sleeps == [40.0]
    assert recorded_timeouts(seen) == [(gb.UPSTREAM_TIMEOUT, gb.UPSTREAM_TIMEOUT)] * 2


def test_only_auto_and_the_public_server_bound_attempts_by_the_budget(monkeypatch):
    http = httpx.Client(transport=httpx.MockTransport(no_network))
    monkeypatch.setattr(gb, "PUBLIC", False)
    assert gb.build_upstream("grok", http).follow_budget is False
    assert gb.build_upstream("auto", http).grok.follow_budget is True
    monkeypatch.setattr(gb, "PUBLIC", True)
    assert gb.build_upstream("grok", http).follow_budget is True


def test_the_route_turns_the_sdk_read_timeout_into_the_attempt_timeout(tmp_path):
    """The backend's PARTHENON_REQUEST_SECONDS=85 arrives as x-stainless-read-timeout: 85."""
    world = World()
    auto, path = make_auto(tmp_path, world)
    sign_in(path)
    client = gb.create_app(auto).test_client()
    ask(client, **{"x-stainless-read-timeout": "85"})
    read = world.to("api.x.ai")[0].extensions["timeout"]["read"]
    assert 0 < read <= 85 - gb.CALLER_TIMEOUT_MARGIN


def test_a_retry_that_would_outlast_the_budget_is_not_made(tmp_path):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(429, headers={"retry-after": "40"}, json={"error": "slow down"})

    upstream, sleeps = timed_grok(tmp_path, handler)
    status, _ = upstream.chat_completion({"model": "grok-4.7", "messages": []}, budget=30)
    assert status == 429 and len(seen) == 1 and sleeps == []


def test_retries_that_fit_the_budget_are_made_and_shrink_the_timeout(tmp_path):
    clock = FakeClock()
    seen = []
    replies = iter([httpx.Response(503, json={"error": "busy"}), httpx.Response(200, json=chat_ok("grok-4.7", "ok"))])

    def handler(request):
        seen.append(request)
        return next(replies)

    upstream, sleeps = timed_grok(tmp_path, handler, clock=clock)
    upstream._sleep = lambda delay: (sleeps.append(delay), setattr(clock, "now", clock.now + delay))
    status, _ = upstream.chat_completion({"model": "grok-4.7", "messages": []}, budget=100)
    assert status == 200 and len(sleeps) == 1
    first, second = recorded_timeouts(seen)
    assert first[0] == 100 and second[0] == pytest.approx(100 - sleeps[0])


def test_an_upstream_timeout_is_a_504_that_says_how_long_it_waited(tmp_path):
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    upstream, _ = timed_grok(tmp_path, handler)
    status, data = upstream.chat_completion({"model": "grok-4.7", "messages": []}, budget=75)
    assert status == 504
    assert data["error"]["code"] == "upstream_timeout" and "within 75s" in data["error"]["message"]


def test_the_fallback_gets_what_is_left_of_the_budget(tmp_path):
    clock = FakeClock()
    world = World(refresh_reply=lambda: (setattr(clock, "now", clock.now + 20), httpx.Response(
        400, json={"error": "invalid_grant"}))[1])
    auto, path = make_auto(tmp_path, world, clock=clock)
    auto.fallback._clock = clock
    sign_in(path, access=make_jwt(expires_in=-60))
    status, _ = auto.chat_completion(BACKEND_REQUEST, budget=75)
    assert status == 200
    assert world.to("openrouter.ai")[0].extensions["timeout"]["read"] == pytest.approx(55)


# --------------------------------------------------------------------------- serve, login, status


def test_serve_builds_auto_with_the_right_fallback(monkeypatch):
    for name in ("XAI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", OR_KEY)
    http = httpx.Client(transport=httpx.MockTransport(no_network))

    auto = gb.build_upstream("auto", http)
    assert isinstance(auto, gb.AutoUpstream)
    assert isinstance(auto.fallback, gb.OpenRouterUpstream)
    assert auto.store.path == gb.TOKEN_FILE and auto.grok.store is auto.store
    assert auto.health_info()["provider"] == "free"

    monkeypatch.setenv("XAI_API_KEY", XAI_KEY)
    auto = gb.build_upstream("auto", http)
    assert isinstance(auto.fallback, gb.KeyedUpstream) and auto.fallback.provider.kind == "xai"

    assert isinstance(gb.build_upstream("grok", http), gb.Upstream)
    assert isinstance(gb.build_upstream("openrouter", http), gb.OpenRouterUpstream)


def fake_xai_sign_in(approved_after=1, refresh_token="refresh-server-1"):
    """auth.x.ai's device-code flow: discovery, the code, `authorization_pending` a few times, then tokens."""
    seen = []
    polls = []
    access = make_jwt(email="owner@example.com")

    def handler(request):
        seen.append(request)
        if request.url.path.endswith("openid-configuration"):
            return httpx.Response(200, json={"token_endpoint": TOKEN_ENDPOINT})
        if request.url.path.endswith("/device/code"):
            return httpx.Response(200, json={
                "device_code": "device-1", "user_code": "ABCD-EFGH", "interval": 1, "expires_in": 600,
                "verification_uri": "https://auth.x.ai/device",
                "verification_uri_complete": "https://auth.x.ai/device?user_code=ABCD-EFGH",
            })
        polls.append(request)
        if len(polls) <= approved_after:
            return httpx.Response(400, json={"error": "authorization_pending"})
        return httpx.Response(200, json={"access_token": access, "refresh_token": refresh_token, "expires_in": 3600})

    return handler, seen, access


def run_login(monkeypatch, handler, *argv):
    monkeypatch.setattr(gb, "_http_client", lambda timeout=None: httpx.Client(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(gb.time, "sleep", lambda seconds: None)
    opened = []
    monkeypatch.setattr(gb.webbrowser, "open", opened.append)
    return gb.main(["login", *argv]), opened


def test_login_saves_the_servers_own_grant_0600_where_the_token_file_says(tmp_path, monkeypatch, capsys):
    macs = tmp_path / "mac" / "grok-oauth.json"
    sign_in(macs, refresh="refresh-mac")
    mac_bytes = macs.read_bytes()
    target = tmp_path / "data" / "grok-oauth.json"
    target.parent.mkdir()
    stale = target.with_name(target.name + ".tmp")
    stale.write_text("{}")
    os.chmod(stale, 0o644)
    monkeypatch.setattr(gb, "TOKEN_FILE", target)  # GROK_BRIDGE_TOKEN_FILE=/data/grok-oauth.json

    handler, seen, access = fake_xai_sign_in()
    code, opened = run_login(monkeypatch, handler, "--no-browser")

    assert code == 0 and opened == []
    saved = json.loads(target.read_text())
    assert saved["access_token"] == access and saved["refresh_token"] == "refresh-server-1"
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert macs.read_bytes() == mac_bytes
    assert all(request.url.host == "auth.x.ai" for request in seen)
    out = capsys.readouterr().out
    assert "https://auth.x.ai/device?user_code=ABCD-EFGH" in out and "ABCD-EFGH" in out
    assert str(target) in out and "owner@example.com" in out
    assert access not in out and "refresh-server-1" not in out


def test_login_takes_the_token_file_from_the_command_line(tmp_path, monkeypatch):
    target = tmp_path / "elsewhere" / "grok-oauth.json"
    handler, _, _ = fake_xai_sign_in(approved_after=0)
    code, _ = run_login(monkeypatch, handler, "--no-browser", "--token-file", str(target))
    assert code == 0 and gb.TOKEN_FILE == target
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


@pytest.mark.parametrize("platform, environ, desktop", [
    ("linux", {}, False),  # a server over `render ssh`
    ("linux", {"DISPLAY": ":0"}, True),
    ("linux", {"WAYLAND_DISPLAY": "wayland-0"}, True),
    ("darwin", {}, True),
])
def test_only_a_desktop_opens_the_sign_in_page(platform, environ, desktop):
    assert gb._can_open_browser(platform, environ) is desktop


def test_login_on_a_server_never_opens_a_browser(tmp_path, monkeypatch):
    monkeypatch.setattr(gb, "_can_open_browser", lambda: False)
    handler, _, _ = fake_xai_sign_in(approved_after=0)
    code, opened = run_login(monkeypatch, handler)
    assert code == 0 and opened == []


def test_login_on_a_desktop_opens_the_sign_in_page(tmp_path, monkeypatch):
    monkeypatch.setattr(gb, "_can_open_browser", lambda: True)
    handler, _, _ = fake_xai_sign_in(approved_after=0)
    code, opened = run_login(monkeypatch, handler)
    assert code == 0 and opened == ["https://auth.x.ai/device?user_code=ABCD-EFGH"]


def test_login_that_cannot_save_says_so(tmp_path, monkeypatch, capsys):
    handler, _, access = fake_xai_sign_in(approved_after=0)

    def refuse(self, state):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(gb.TokenStore, "save", refuse)
    code, _ = run_login(monkeypatch, handler, "--no-browser")
    out = capsys.readouterr().out
    assert code == 1 and "could not be saved" in out and "Permission denied" in out and access not in out


def test_a_running_auto_bridge_serves_a_login_made_beside_it(tmp_path, monkeypatch):
    world = World()
    auto, path = make_auto(tmp_path, world)
    client = gb.create_app(auto).test_client()
    assert ask(client) == "from openrouter"

    monkeypatch.setattr(gb, "TOKEN_FILE", path)
    handler, _, access = fake_xai_sign_in(approved_after=0)
    assert run_login(monkeypatch, handler, "--no-browser")[0] == 0

    assert ask(client) == "from grok"
    assert world.to("api.x.ai")[0].headers["authorization"] == f"Bearer {access}"


@pytest.fixture
def auto_env(monkeypatch):
    monkeypatch.setattr(gb, "UPSTREAM", "auto")
    monkeypatch.setattr(gb, "PUBLIC", False)
    for name in ("XAI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", OR_KEY)
    asked = []
    monkeypatch.setattr(gb, "_running_bridge_health", lambda: asked.append(1) or None)
    return asked


def test_status_says_auto_is_on_the_fallback_without_a_sign_in(auto_env, capsys):
    assert gb.cmd_status(None) == 0
    out = capsys.readouterr().out
    assert "Upstream:     auto -> openrouter (PARTHENON_UPSTREAM)" in out
    assert f"Grok sign-in: none yet ({gb.TOKEN_FILE})" in out
    assert OR_KEY not in out and auto_env == []


def test_status_says_auto_is_on_the_subscription_once_signed_in(auto_env, capsys):
    state = sign_in(gb.TOKEN_FILE)
    assert gb.cmd_status(None) == 0
    out = capsys.readouterr().out
    assert "Upstream:     auto -> grok (PARTHENON_UPSTREAM)" in out
    assert "Signed in as: owner@example.com" in out and f"Sign-in file: {gb.TOKEN_FILE}" in out
    assert "Fallback:     openrouter" in out and "Warning" not in out
    assert state["access_token"] not in out and state["refresh_token"] not in out


def test_status_names_a_revoked_or_broken_sign_in(auto_env, capsys):
    sign_in(gb.TOKEN_FILE, revoked="invalid_grant")
    gb.cmd_status(None)
    assert "Grok sign-in: needs a new sign-in" in capsys.readouterr().out
    gb.TOKEN_FILE.write_text("{oops")
    gb.cmd_status(None)
    assert "Grok sign-in: unusable, the file is not valid JSON" in capsys.readouterr().out


def test_status_warns_about_a_sign_in_others_can_read(auto_env, capsys):
    sign_in(gb.TOKEN_FILE)
    os.chmod(gb.TOKEN_FILE, 0o644)
    gb.cmd_status(None)
    assert "mode 0644; it should be 0600" in capsys.readouterr().out


@pytest.mark.parametrize("health, line", [
    ({"provider": "grok-subscription", "imagine": True, "voice": True},
     "Running:      grok-subscription on 127.0.0.1:5055 (portraits, film and voice)"),
    ({"provider": "free", "imagine": False, "voice": False},
     "Running:      free on 127.0.0.1:5055 (no portraits, film or voice)"),
    (None, "Running:      no bridge answers on 127.0.0.1:5055"),
])
def test_status_live_says_which_provider_the_server_is_on(auto_env, monkeypatch, capsys, health, line):
    monkeypatch.setattr(gb, "HOST", "127.0.0.1")
    monkeypatch.setattr(gb, "PORT", 5055)
    monkeypatch.setattr(gb, "_running_bridge_health", lambda: health)
    sign_in(gb.TOKEN_FILE)
    gb.cmd_status(SimpleNamespace(live=True))
    out = capsys.readouterr().out
    assert line in out
    assert ("does not see this sign-in" in out) is (health is not None and health["provider"] == "free")


def test_status_asks_the_running_bridge_on_the_public_server(auto_env, monkeypatch, capsys):
    monkeypatch.setattr(gb, "PUBLIC", True)
    monkeypatch.setattr(gb, "_running_bridge_health", lambda: {"provider": "free"})
    gb.cmd_status(None)
    assert "Running:      free" in capsys.readouterr().out


def test_the_running_bridge_is_asked_on_loopback_without_proxies(monkeypatch):
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return httpx.Response(200, json={"status": "ok", "provider": "grok-subscription"})

    monkeypatch.setattr(gb.httpx, "get", fake_get)
    monkeypatch.setattr(gb, "HOST", "0.0.0.0")
    monkeypatch.setattr(gb, "PORT", 6055)
    assert gb._running_bridge_health()["provider"] == "grok-subscription"
    assert calls == [("http://127.0.0.1:6055/health", {"timeout": 3.0, "trust_env": False})]


def test_logout_says_where_auto_goes_next(auto_env, capsys):
    sign_in(gb.TOKEN_FILE)
    assert gb.cmd_logout(None) == 0
    out = capsys.readouterr().out
    assert "deleted" in out and "serves openrouter from its next request" in out
    assert not gb.TOKEN_FILE.exists()


def test_the_server_hints_at_the_server_sign_in():
    assert "grok_bridge.py login" in gb.SERVER_LOGIN_HINT and "GROK_BRIDGE_TOKEN_FILE" in gb.SERVER_LOGIN_HINT
    assert "npm run grok:login" in gb.LOCAL_LOGIN_HINT
