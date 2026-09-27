"""OpenRouter free-model upstream (PARTHENON_UPSTREAM=openrouter). No network: httpx.MockTransport only."""

import json
import logging
import threading

import httpx
import pytest

import grok_bridge as gb


KEY = "sk-or-v1-test-secret-0123456789abcdef"
NEMOTRON = "nvidia/nemotron-3-super-120b-a12b:free"
GEMMA = "google/gemma-4-31b-it:free"
QWEN = "qwen/qwen3.8-27b:free"
ROUTER = "openrouter/free"
MODELS = [NEMOTRON, GEMMA, QWEN, ROUTER]
REQUEST = {"model": "grok-4.20-0309-non-reasoning", "messages": [{"role": "user", "content": "hi"}]}


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def chat_ok(model, content="hi"):
    return {
        "id": "gen-1", "object": "chat.completion", "created": 1, "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4},
    }


def rate_limited(message="Provider returned error: temporarily rate-limited upstream", **headers):
    return httpx.Response(429, headers=headers, json={"error": {"message": message, "code": 429}})


def make_upstream(handler, *, clock=None, sleeps=None, **kwargs):
    kwargs.setdefault("rpm", 0)  # throttle off unless a test is about the throttle
    return gb.OpenRouterUpstream(
        KEY,
        httpx.Client(transport=httpx.MockTransport(handler)),
        models=MODELS,
        clock=clock or FakeClock(),
        sleep=(sleeps if sleeps is not None else []).append,
        **kwargs,
    )


def recording(replies):
    """A handler that records each (model, models) sent and answers from `replies` in turn."""
    sent = []
    replies = iter(replies)

    def handler(request):
        body = json.loads(request.content)
        sent.append((body["model"], body["models"]))
        reply = next(replies)
        return reply(body) if callable(reply) else reply

    return handler, sent


def served(body):
    return httpx.Response(200, json=chat_ok(body["model"]))


# --------------------------------------------------------------------------- routing


def test_model_list_env_parsing():
    assert gb._model_list(None) == MODELS
    assert gb._model_list("  ") == MODELS
    assert gb._model_list(" a/b:free , c/d ,") == ["a/b:free", "c/d"]


def test_request_is_forwarded_with_native_fallback_list_and_app_headers():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=chat_ok(NEMOTRON))

    request = {
        **REQUEST,
        "temperature": 0.3,
        "response_format": {"type": "json_object"},
        "tools": [{"type": "function", "function": {"name": "like_post", "parameters": {"type": "object"}}}],
    }
    status, data = make_upstream(handler).chat_completion(request)

    assert status == 200 and data["model"] == NEMOTRON
    (sent,) = seen
    assert str(sent.url) == "https://openrouter.ai/api/v1/chat/completions"
    assert sent.headers["authorization"] == f"Bearer {KEY}"
    assert sent.headers["x-title"] == "Parthenon"
    assert sent.headers["http-referer"] == "http://localhost:3000"
    body = json.loads(sent.content)
    assert body["model"] == NEMOTRON
    assert body["models"] == [NEMOTRON, GEMMA, QWEN]  # OpenRouter takes at most three
    assert {k: body[k] for k in ("messages", "temperature", "response_format", "tools")} == {
        k: request[k] for k in ("messages", "temperature", "response_format", "tools")
    }


@pytest.mark.parametrize("model, expected", [
    ("", [NEMOTRON, GEMMA, QWEN]),
    (None, [NEMOTRON, GEMMA, QWEN]),
    ("parthenon-free", [NEMOTRON, GEMMA, QWEN]),
    ("some/unknown-model", [NEMOTRON, GEMMA, QWEN]),
    (QWEN, [QWEN, ROUTER, NEMOTRON]),
    (ROUTER, [ROUTER, NEMOTRON, GEMMA]),
])
def test_requested_model_picks_where_the_list_starts(model, expected):
    handler, sent = recording([served])
    make_upstream(handler).chat_completion({**REQUEST, "model": model})
    assert sent == [(expected[0], expected)]


def test_429_rotates_the_list_and_later_requests_start_with_the_model_that_answered():
    clock, sleeps = FakeClock(), []
    handler, sent = recording([rate_limited(), served, served, served])
    upstream = make_upstream(handler, clock=clock, sleeps=sleeps)

    status, data = upstream.chat_completion(REQUEST)
    assert status == 200 and data["model"] == GEMMA
    assert sent[0] == (NEMOTRON, [NEMOTRON, GEMMA, QWEN])
    assert sent[1] == (GEMMA, [GEMMA, QWEN, ROUTER])  # failed first model moved to the end
    assert len(sleeps) == 1
    assert upstream.health_info()["current_model"] == GEMMA

    upstream.chat_completion({**REQUEST, "model": "parthenon-free"})
    assert sent[2] == (GEMMA, [GEMMA, QWEN, ROUTER])

    clock.now += gb.HEALTHY_MODEL_SECONDS + 1  # the memory is only kept for a few minutes
    upstream.chat_completion(REQUEST)
    assert sent[3][0] == NEMOTRON


def test_router_entry_is_never_remembered_when_it_answers_under_another_models_id():
    # openrouter/free picks any free model (a safety classifier, a 2.6B model...) under that model's
    # own id: starting later requests there handed the whole city to random models.
    handler, sent = recording([
        rate_limited(), rate_limited(), rate_limited(),
        httpx.Response(200, json=chat_ok("meta-llama/llama-4-scout:free")),
        served,
    ])
    upstream = make_upstream(handler)
    assert upstream.chat_completion(REQUEST)[0] == 200
    assert sent[3] == (ROUTER, [ROUTER, NEMOTRON, GEMMA])
    assert upstream.health_info()["current_model"] is None
    upstream.chat_completion(REQUEST)
    assert sent[4] == (NEMOTRON, [NEMOTRON, GEMMA, QWEN])


def test_5xx_and_errors_inside_a_200_body_are_retried_on_the_next_model():
    handler, sent = recording([
        httpx.Response(503, json={"error": {"message": "no healthy upstream", "code": 503}}),
        httpx.Response(200, json={"error": {"message": "Provider returned error", "code": 502}}),
        served,
    ])
    sleeps = []
    status, data = make_upstream(handler, sleeps=sleeps).chat_completion(REQUEST)
    assert status == 200 and data["model"] == QWEN
    assert [model for model, _ in sent] == [NEMOTRON, GEMMA, QWEN]
    assert len(sleeps) == 2


def test_retry_after_is_honoured():
    handler, _ = recording([rate_limited(**{"retry-after": "7"}), served])
    sleeps = []
    assert make_upstream(handler, sleeps=sleeps).chat_completion(REQUEST)[0] == 200
    assert sleeps and sleeps[0] >= 7


def test_gives_up_after_max_retries_with_the_last_upstream_error():
    handler, sent = recording([lambda body: rate_limited()] * 3)
    sleeps = []
    status, data = make_upstream(handler, sleeps=sleeps, max_retries=2).chat_completion(REQUEST)
    assert status == 429 and "rate-limited upstream" in data["error"]["message"]
    assert [model for model, _ in sent] == [NEMOTRON, GEMMA, QWEN]
    assert len(sleeps) == 2


def test_client_errors_pass_through_without_retrying():
    error = {"error": {"message": "Invalid tool schema", "code": 400}}
    handler, sent = recording([httpx.Response(400, json=error)])
    assert make_upstream(handler).chat_completion(REQUEST) == (400, error)
    assert len(sent) == 1


def test_per_day_limit_stops_retrying_with_a_clear_error():
    clock, sleeps = FakeClock(), []
    daily = rate_limited(
        "Rate limit exceeded: free-models-per-day. Add 10 credits to unlock 1000 free model requests per day",
        **{"retry-after": "30"},
    )
    handler, sent = recording([daily, served])
    upstream = make_upstream(handler, clock=clock, sleeps=sleeps)

    status, data = upstream.chat_completion(REQUEST)
    assert status == 429
    assert data["error"]["message"] == gb.DAILY_LIMIT_MESSAGE
    assert data["error"]["message"] == (
        "OpenRouter's free daily limit is used up; it resets at 00:00 UTC. "
        "Add credits to OpenRouter or switch PARTHENON_UPSTREAM to grok."
    )
    assert len(sent) == 1 and sleeps == []

    # Queued requests fail fast for a while instead of spending more of the day's attempts.
    assert upstream.chat_completion(REQUEST)[1]["error"]["message"] == gb.DAILY_LIMIT_MESSAGE
    assert len(sent) == 1

    clock.now += gb.DAILY_LIMIT_RECHECK_SECONDS + 1
    assert upstream.chat_completion(REQUEST)[0] == 200
    assert len(sent) == 2


def test_missing_key_is_a_clear_401_without_calling_openrouter():
    def no_network(request):
        raise AssertionError(f"unexpected request to {request.url}")

    upstream = gb.OpenRouterUpstream("", httpx.Client(transport=httpx.MockTransport(no_network)), models=MODELS)
    status, data = upstream.chat_completion(REQUEST)
    assert status == 401 and "OPENROUTER_API_KEY" in data["error"]["message"]


# --------------------------------------------------------------------------- throttle


def test_token_bucket_spaces_out_a_burst_and_refills_only_to_capacity():
    clock, sleeps = FakeClock(), []
    bucket = gb.TokenBucket(18, 2, clock=clock, sleep=sleeps.append)
    interval = 60 / 18

    assert all(bucket.acquire(120) for _ in range(5))
    assert sleeps == pytest.approx([interval, 2 * interval, 3 * interval])  # the first two go straight out

    assert bucket.acquire(4 * interval - 0.1) is False  # over the wait cap: refused, nothing reserved
    assert bucket.acquire(120) is True
    assert sleeps[-1] == pytest.approx(4 * interval)

    clock.now += 3600  # a long idle spell does not bank more than `capacity`
    sleeps.clear()
    for _ in range(3):
        bucket.acquire(120)
    assert sleeps == pytest.approx([interval])


def test_token_bucket_queues_concurrent_callers():
    clock, sleeps = FakeClock(), []
    bucket = gb.TokenBucket(60, 1, clock=clock, sleep=sleeps.append)
    threads = [threading.Thread(target=bucket.acquire, args=(120,)) for _ in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(sleeps) == pytest.approx([float(k) for k in range(1, 20)])


def test_throttle_paces_upstream_calls_and_429s_past_the_wait_cap():
    clock, sleeps = FakeClock(), []
    handler, sent = recording([served] * 3)
    upstream = make_upstream(handler, clock=clock, sleeps=sleeps, rpm=6, throttle_wait=15)

    assert upstream.chat_completion(REQUEST)[0] == 200
    assert upstream.chat_completion(REQUEST)[0] == 200  # burst of two
    assert upstream.chat_completion(REQUEST)[0] == 200  # waits 10 s for the next token
    assert sleeps == pytest.approx([10.0])

    status, data = upstream.chat_completion(REQUEST)  # would wait 20 s > 15 s cap
    assert status == 429
    assert data["error"]["code"] == "bridge_throttled"
    assert "OPENROUTER_RPM" in data["error"]["message"]
    assert len(sent) == 3


# --------------------------------------------------------------------------- HTTP server


MODELS_PAYLOAD = {"data": [
    {"id": NEMOTRON, "pricing": {"prompt": "0", "completion": "0"}},
    {"id": ROUTER, "pricing": {"prompt": "0", "completion": "0"}},
    {"id": "some/zero-priced", "pricing": {"prompt": "0", "completion": "0.0"}},
    {"id": "openai/gpt-5", "pricing": {"prompt": "0.00000125", "completion": "0.00001"}},
    {"id": "openrouter/auto", "pricing": {"prompt": "-1", "completion": "-1"}},
    {"id": "odd/no-pricing"},
]}


def test_models_are_proxied_and_filtered_to_free_ones():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=MODELS_PAYLOAD)

    client = gb.create_app(make_upstream(handler)).test_client()
    response = client.get("/v1/models")
    assert response.status_code == 200
    assert [m["id"] for m in response.get_json()["data"]] == [NEMOTRON, ROUTER, "some/zero-priced"]
    assert str(seen[0].url) == "https://openrouter.ai/api/v1/models"


def test_health_reports_the_upstream(tmp_path):
    http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    store = gb.TokenStore(tmp_path / "t.json", http)
    store.save({"access_token": "a.b.c", "refresh_token": "r"})
    grok = gb.create_app(gb.Upstream(store, http, mode="chat")).test_client().get("/health").get_json()
    assert grok == {
        "status": "ok", "upstream": "grok", "signed_in": True, "mode": "chat", "imagine": True,
        "provider": "grok-subscription", "voice": True,
    }

    openrouter = gb.create_app(make_upstream(lambda r: httpx.Response(500))).test_client().get("/health").get_json()
    assert openrouter["status"] == "ok"
    assert openrouter["upstream"] == "openrouter"
    assert openrouter["models"] == MODELS
    assert openrouter["api_key_set"] is True
    assert openrouter["imagine"] is False
    assert openrouter["provider"] == "free" and openrouter["voice"] is False


def test_security_guards_apply_in_openrouter_mode():
    handler, sent = recording([served])
    client = gb.create_app(make_upstream(handler)).test_client()
    assert client.post("/v1/chat/completions", json=REQUEST, headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.post("/v1/chat/completions", json=REQUEST, headers={"Host": "evil.example:5055"}).status_code == 403
    assert sent == []


def test_api_key_never_appears_in_responses_or_logs(caplog):
    caplog.set_level(logging.DEBUG)
    auth_headers = []
    replies = iter([
        rate_limited(),
        httpx.Response(200, json=chat_ok(GEMMA)),
        httpx.Response(401, json={"error": {"message": "No auth credentials found", "code": 401}}),
        rate_limited("Rate limit exceeded: free-models-per-day."),
    ])

    def handler(request):
        auth_headers.append(request.headers.get("authorization"))
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json=MODELS_PAYLOAD)
        return next(replies)

    def broken_network(request):
        auth_headers.append(request.headers.get("authorization"))
        raise httpx.ConnectError(f"connection failed while sending Bearer {KEY}")

    bodies = []
    for upstream in (make_upstream(handler), make_upstream(broken_network, max_retries=1)):
        client = gb.create_app(upstream).test_client()
        bodies.append(client.get("/health").get_data(as_text=True))
        bodies.append(client.get("/v1/models").get_data(as_text=True))
        for _ in range(3):
            bodies.append(client.post("/v1/chat/completions", json=REQUEST).get_data(as_text=True))

    assert f"Bearer {KEY}" in auth_headers  # the key was really used...
    assert all(KEY not in body for body in bodies)  # ...but never echoed back
    assert "[redacted]" in "".join(bodies)
    assert KEY not in caplog.text
    assert any("OpenRouter HTTP 429" in record.getMessage() for record in caplog.records)


def test_status_reports_the_openrouter_upstream_without_the_key(monkeypatch, capsys):
    monkeypatch.setattr(gb, "UPSTREAM", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", KEY)
    assert gb.cmd_status(None) == 0
    out = capsys.readouterr().out
    assert "openrouter" in out and "API key:      set" in out
    assert KEY not in out

    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    assert gb.cmd_status(None) == 1
    assert "missing" in capsys.readouterr().out
