import base64
import json
import stat
import threading
import time

import httpx
import pytest

import grok_bridge as gb


TOKEN_ENDPOINT = "https://auth.x.ai/oauth2/token"


def make_jwt(expires_in: float = 3600, **claims) -> str:
    def encode(obj):
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()

    return f"{encode({'alg': 'none'})}.{encode({'exp': time.time() + expires_in, **claims})}.sig"


def make_store(path, handler, **state):
    http = httpx.Client(transport=httpx.MockTransport(handler))
    store = gb.TokenStore(path, http)
    store.save({
        "access_token": make_jwt(),
        "refresh_token": "refresh-1",
        "token_endpoint": TOKEN_ENDPOINT,
        **state,
    })
    return store


def no_network(request):
    raise AssertionError(f"unexpected request to {request.url}")


# --------------------------------------------------------------------------- tokens


def test_fresh_token_is_used_without_refreshing(tmp_path):
    store = make_store(tmp_path / "t.json", no_network)
    assert store.access_token() == store.load()["access_token"]


def test_expiring_token_refreshes_and_saves_rotated_refresh_token(tmp_path):
    seen = []
    new_access = make_jwt()

    def handler(request):
        seen.append(dict(httpx.QueryParams(request.content.decode())))
        return httpx.Response(200, json={"access_token": new_access, "refresh_token": "refresh-2"})

    path = tmp_path / "t.json"
    store = make_store(path, handler, access_token=make_jwt(expires_in=30))

    assert store.access_token() == new_access
    assert seen == [{"grant_type": "refresh_token", "client_id": gb.CLIENT_ID, "refresh_token": "refresh-1"}]
    saved = json.loads(path.read_text())
    assert saved["refresh_token"] == "refresh-2"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_concurrent_callers_refresh_only_once(tmp_path):
    calls = []

    def handler(request):
        calls.append(1)
        time.sleep(0.05)
        return httpx.Response(200, json={"access_token": make_jwt(), "refresh_token": f"refresh-{len(calls) + 1}"})

    store = make_store(tmp_path / "t.json", handler, access_token=make_jwt(expires_in=10))
    tokens = []
    threads = [threading.Thread(target=lambda: tokens.append(store.access_token())) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(calls) == 1
    assert len(set(tokens)) == 1


def test_revoked_grant_is_remembered_and_not_retried(tmp_path):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(400, json={"error": "invalid_grant"})

    path = tmp_path / "t.json"
    store = make_store(path, handler, access_token=make_jwt(expires_in=-5))

    with pytest.raises(gb.AuthError, match="grok:login"):
        store.access_token()
    with pytest.raises(gb.AuthError, match="invalid_grant"):
        store.access_token()
    assert len(calls) == 1
    assert json.loads(path.read_text())["revoked"] == "invalid_grant"


def test_transient_refresh_failure_is_not_treated_as_revoked(tmp_path):
    path = tmp_path / "t.json"
    store = make_store(path, lambda r: httpx.Response(503, text="down"), access_token=make_jwt(expires_in=-5))
    with pytest.raises(gb.RefreshUnavailable):
        store.access_token()
    assert "revoked" not in json.loads(path.read_text())


def test_refuses_to_send_refresh_token_off_xai(tmp_path):
    store = make_store(
        tmp_path / "t.json", no_network,
        access_token=make_jwt(expires_in=-5), token_endpoint="https://evil.example/token",
    )
    with pytest.raises(gb.AuthError, match="non-xAI"):
        store.access_token()


def test_not_signed_in(tmp_path):
    store = gb.TokenStore(tmp_path / "missing.json", httpx.Client(transport=httpx.MockTransport(no_network)))
    with pytest.raises(gb.AuthError, match="Not signed in"):
        store.access_token()


# --------------------------------------------------------------------------- upstream


def chat_ok(content="hi"):
    return {
        "id": "chatcmpl-1", "object": "chat.completion", "created": 1, "model": "grok",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
    }


def test_401_triggers_one_refresh_and_retry(tmp_path):
    fresh = make_jwt()
    auth_headers = []

    def handler(request):
        if request.url.host == "auth.x.ai":
            return httpx.Response(200, json={"access_token": fresh, "refresh_token": "refresh-2"})
        auth_headers.append(request.headers["authorization"])
        if len(auth_headers) == 1:
            return httpx.Response(401, json={"error": {"message": "expired"}})
        return httpx.Response(200, json=chat_ok())

    store = make_store(tmp_path / "t.json", handler)
    upstream = gb.Upstream(store, store.http, mode="chat")
    status, data = upstream.chat_completion({"model": "grok", "messages": []})

    assert status == 200 and data["choices"][0]["message"]["content"] == "hi"
    assert auth_headers[-1] == f"Bearer {fresh}"


def test_auto_mode_falls_back_to_responses_api_and_sticks(tmp_path):
    paths = []

    def handler(request):
        paths.append(request.url.path)
        if request.url.path.endswith("/chat/completions"):
            return httpx.Response(403, json={"error": "chat completions not allowed for this token"})
        body = json.loads(request.content)
        assert body["input"][0] == {"role": "user", "content": "hello"}
        assert body["store"] is False
        return httpx.Response(200, json={
            "id": "resp_1", "model": "grok", "status": "completed",
            "output": [{"type": "message", "content": [{"type": "output_text", "text": "hey"}]}],
            "usage": {"input_tokens": 3, "output_tokens": 1, "total_tokens": 4},
        })

    store = make_store(tmp_path / "t.json", handler)
    upstream = gb.Upstream(store, store.http, mode="auto")
    request = {"model": "grok", "messages": [{"role": "user", "content": "hello"}]}

    status, data = upstream.chat_completion(request)
    assert status == 200
    assert data["choices"][0]["message"]["content"] == "hey"
    assert data["usage"] == {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4}
    assert upstream.mode == "responses"

    upstream.chat_completion(request)
    assert paths == ["/v1/chat/completions", "/v1/responses", "/v1/responses"]


def test_rate_limits_are_retried_with_backoff(tmp_path):
    responses = iter([
        httpx.Response(429, headers={"retry-after": "3"}, json={"error": "slow down"}),
        httpx.Response(200, json=chat_ok()),
    ])
    store = make_store(tmp_path / "t.json", lambda r: next(responses))
    sleeps = []
    upstream = gb.Upstream(store, store.http, mode="chat", sleep=sleeps.append)

    status, _ = upstream.chat_completion({"model": "grok", "messages": []})
    assert status == 200
    assert sleeps and sleeps[0] >= 3


def test_provider_errors_pass_through_unchanged(tmp_path):
    error = {"error": {"message": "response_format is not supported", "param": "response_format"}}
    store = make_store(tmp_path / "t.json", lambda r: httpx.Response(400, json=error))
    status, data = gb.Upstream(store, store.http, mode="chat").chat_completion({"model": "grok", "messages": []})
    assert (status, data) == (400, error)


# --------------------------------------------------------------------------- translation


def test_chat_to_responses_converts_tools_json_mode_and_history():
    converted = gb.chat_to_responses({
        "model": "grok-4.3",
        "temperature": 0.2,
        "max_tokens": 512,
        "response_format": {"type": "json_object"},
        "tool_choice": {"type": "function", "function": {"name": "like_post"}},
        "tools": [{"type": "function", "function": {
            "name": "like_post", "description": "Like a post",
            "parameters": {"type": "object", "properties": {"post_id": {"type": "integer"}}},
        }}],
        "messages": [
            {"role": "system", "content": "be terse"},
            {"role": "user", "content": [{"type": "text", "text": "like it"}]},
            {"role": "assistant", "content": None, "tool_calls": [
                {"id": "call_1", "type": "function", "function": {"name": "like_post", "arguments": '{"post_id": 4}'}},
            ]},
            {"role": "tool", "tool_call_id": "call_1", "content": "ok"},
        ],
    })

    assert converted["input"] == [
        {"role": "system", "content": "be terse"},
        {"role": "user", "content": [{"type": "input_text", "text": "like it"}]},
        {"type": "function_call", "call_id": "call_1", "name": "like_post", "arguments": '{"post_id": 4}'},
        {"type": "function_call_output", "call_id": "call_1", "output": "ok"},
    ]
    assert converted["tools"][0]["name"] == "like_post"
    assert converted["tool_choice"] == {"type": "function", "name": "like_post"}
    assert converted["text"] == {"format": {"type": "json_object"}}
    assert converted["max_output_tokens"] == 512
    assert converted["temperature"] == 0.2
    assert "messages" not in converted and "max_tokens" not in converted


def test_responses_to_chat_maps_tool_calls_and_finish_reasons():
    tool_result = gb.responses_to_chat({
        "output": [
            {"type": "reasoning", "summary": [{"type": "summary_text", "text": "thinking"}]},
            {"type": "function_call", "call_id": "call_9", "name": "like_post", "arguments": '{"post_id": 1}'},
        ],
        "status": "completed",
    }, {"model": "grok"})
    message = tool_result["choices"][0]["message"]
    assert tool_result["choices"][0]["finish_reason"] == "tool_calls"
    assert message["content"] is None
    assert message["tool_calls"][0]["id"] == "call_9"
    assert message["tool_calls"][0]["function"]["name"] == "like_post"
    assert message["reasoning_content"] == "thinking"

    truncated = gb.responses_to_chat({
        "output": [{"type": "message", "content": [{"type": "output_text", "text": '{"a":'}]}],
        "status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"},
    }, {"model": "grok"})
    assert truncated["choices"][0]["finish_reason"] == "length"


# --------------------------------------------------------------------------- HTTP guard


class FakeUpstream:
    mode = "chat"

    def __init__(self, store):
        self.store = store
        self.bodies = []

    def chat_completion(self, body):
        self.bodies.append(body)
        return 200, chat_ok("from fake")

    def models(self):
        return 200, {"data": []}


@pytest.fixture
def client_and_upstream(tmp_path):
    upstream = FakeUpstream(make_store(tmp_path / "t.json", no_network))
    return gb.create_app(upstream).test_client(), upstream


def test_local_sdk_requests_are_forwarded(client_and_upstream):
    client, upstream = client_and_upstream
    response = client.post("/v1/chat/completions", json={"model": "grok", "messages": []},
                           headers={"Authorization": "Bearer anything"})
    assert response.status_code == 200
    assert response.get_json()["choices"][0]["message"]["content"] == "from fake"
    assert upstream.bodies == [{"model": "grok", "messages": []}]


@pytest.mark.parametrize("headers", [
    {"Origin": "https://some-website.example"},
    {"Host": "attacker.example:5055"},
])
def test_browser_and_non_local_requests_are_refused(client_and_upstream, headers):
    client, upstream = client_and_upstream
    response = client.post("/v1/chat/completions", json={"model": "grok", "messages": []}, headers=headers)
    assert response.status_code == 403
    assert upstream.bodies == []


def test_non_json_and_streaming_requests_are_refused(client_and_upstream):
    client, upstream = client_and_upstream
    assert client.post("/v1/chat/completions", data='{"messages": []}',
                       content_type="text/plain").status_code == 400
    assert client.post("/v1/chat/completions", json={"messages": [], "stream": True}).status_code == 400
    assert upstream.bodies == []


def test_missing_sign_in_is_a_clear_401(tmp_path):
    http = httpx.Client(transport=httpx.MockTransport(no_network))
    upstream = gb.Upstream(gb.TokenStore(tmp_path / "missing.json", http), http)
    response = gb.create_app(upstream).test_client().post(
        "/v1/chat/completions", json={"model": "grok", "messages": []})
    assert response.status_code == 401
    assert "grok:login" in response.get_json()["error"]["message"]


def test_a_caller_with_a_deadline_is_not_queued_past_it(tmp_path):
    """A busy bridge answers a timed caller with its own 429 instead of calling xAI after the caller left."""
    calls = []

    def fake_request(self, method, path, body=None):
        calls.append(path)
        return 200, chat_ok("late")

    store = make_store(tmp_path / "t.json", no_network)
    upstream = gb.Upstream(store, store.http, mode="chat", max_concurrency=1)
    upstream._request = fake_request.__get__(upstream)
    upstream._slots.acquire()  # the only slot is busy
    try:
        status, data = upstream.chat_completion({"model": "grok", "messages": []}, budget=0.2)
    finally:
        upstream._slots.release()
    assert status == 429
    assert data["error"]["code"] == "bridge_throttled"
    assert calls == []
    status, data = upstream.chat_completion({"model": "grok", "messages": []}, budget=30)
    assert status == 200 and calls == ["/chat/completions"]


def test_the_route_passes_the_sdk_read_timeout_as_the_budget(tmp_path):
    seen = []

    class Timed(FakeUpstream):
        def chat_completion(self, body, budget=None):
            seen.append(budget)
            return 200, chat_ok("ok")

    client = gb.create_app(Timed(make_store(tmp_path / "t.json", no_network))).test_client()
    client.post("/v1/chat/completions", json={"model": "grok", "messages": []})
    client.post("/v1/chat/completions", json={"model": "grok", "messages": []},
                headers={"x-stainless-read-timeout": "90"})
    assert seen == [None, 90 - gb.CALLER_TIMEOUT_MARGIN]
