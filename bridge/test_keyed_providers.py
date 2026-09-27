"""Keyed providers (PARTHENON_UPSTREAM=xai, openai, anthropic, auto). No network: httpx.MockTransport only."""

import copy
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from dotenv import dotenv_values

import grok_bridge as gb


KEYS = {
    "xai": "xai-test-secret-0123456789abcdefABCDEF",
    "openai": "sk-proj-test-secret-0123456789abcdefABCDEF",
    "anthropic": "sk-ant-api03-test-secret-0123456789abcdef",
}
MODELS = {"xai": "grok-4.20-0309-non-reasoning", "openai": "gpt-4.1-mini", "anthropic": "claude-sonnet-5"}
URLS = {
    "xai": "https://api.x.ai/v1/chat/completions",
    "openai": "https://api.openai.com/v1/chat/completions",
    "anthropic": "https://api.anthropic.com/v1/chat/completions",
}
KINDS = ["xai", "openai", "anthropic"]
# What the backend sends: the model name from its own config, JSON mode, a temperature and a token cap.
BACKEND_REQUEST = {
    "model": "grok-4.7",
    "messages": [
        {"role": "system", "content": "You are the Scribe."},
        {"role": "user", "content": "Summarise the night as JSON."},
    ],
    "response_format": {"type": "json_object"},
    "temperature": 0.3,
    "max_tokens": 4096,
}
# What OASIS (camel) sends: tools with strict schemas, no token cap, no temperature.
TOOL = {
    "type": "function",
    "function": {
        "name": "like_post", "description": "Like a post by id.", "strict": True,
        "parameters": {
            "type": "object", "properties": {"post_id": {"type": "integer"}},
            "required": ["post_id"], "additionalProperties": False,
        },
    },
}
OASIS_REQUEST = {
    "model": "grok-4.7",
    "messages": [
        {"role": "system", "content": "You are a citizen of Athens."},
        {"role": "user", "content": "Here is your feed."},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "call_1", "type": "function", "function": {"name": "like_post", "arguments": '{"post_id": 1}'}},
        ]},
        {"role": "tool", "tool_call_id": "call_1", "content": "ok"},
    ],
    "tools": [TOOL],
}


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def chat_ok(model, content='{"ok": true}'):
    return {
        "id": "chatcmpl-1", "object": "chat.completion", "created": 1, "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4},
    }


def recording(*replies):
    """A handler that records each request and answers from `replies` in turn (callables get the sent body)."""
    seen = []
    replies_iter = iter(replies)

    def handler(request):
        seen.append(request)
        reply = next(replies_iter)
        return reply(json.loads(request.content or b"{}")) if callable(reply) else reply

    return handler, seen


def served(body):
    return httpx.Response(200, json=chat_ok(body["model"]))


def no_network(request):
    raise AssertionError(f"unexpected request to {request.url}")


def make_upstream(kind, handler, *, key=None, sleeps=None, clock=None, **kwargs):
    kwargs.setdefault("rpm", 0)
    kwargs.setdefault("model", MODELS[kind])
    return gb.KeyedUpstream(
        gb.PROVIDERS[kind],
        KEYS[kind] if key is None else key,
        httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=(sleeps if sleeps is not None else []).append,
        clock=clock or FakeClock(),
        **kwargs,
    )


def sent_body(request):
    return json.loads(request.content)


# --------------------------------------------------------------------------- choosing the upstream


@pytest.mark.parametrize("kind", ["grok", "openrouter", "xai", "openai", "anthropic"])
def test_explicit_upstreams_are_kept(kind):
    assert gb.resolve_upstream(kind, {"XAI_API_KEY": "x"}) == kind


@pytest.mark.parametrize("environ, expected", [
    ({}, "openrouter"),
    ({"OPENROUTER_API_KEY": "or"}, "openrouter"),
    ({"ANTHROPIC_API_KEY": "a"}, "anthropic"),
    ({"OPENAI_API_KEY": "o", "ANTHROPIC_API_KEY": "a"}, "openai"),
    ({"XAI_API_KEY": "x", "OPENAI_API_KEY": "o", "ANTHROPIC_API_KEY": "a"}, "xai"),
    ({"XAI_API_KEY": "  ", "OPENAI_API_KEY": "", "ANTHROPIC_API_KEY": "a"}, "anthropic"),
])
def test_auto_takes_the_first_key_that_is_set_else_openrouter(environ, expected):
    assert gb.resolve_upstream("auto", environ) == expected
    assert gb.resolve_upstream(" AUTO ", environ) == expected


def test_every_upstream_value_is_accepted_by_the_cli():
    assert set(gb.UPSTREAMS) == {"grok", "openrouter", "xai", "openai", "anthropic", "auto"}


@pytest.mark.parametrize("kind", KINDS)
def test_configured_model_defaults_and_overrides(kind):
    provider = gb.PROVIDERS[kind]
    assert gb.provider_model(provider, {}) == provider.default_model == MODELS[kind]
    assert gb.provider_model(provider, {provider.model_env: " my-model "}) == "my-model"


def test_provider_labels():
    assert gb.PROVIDER_LABELS == {
        "grok": "grok-subscription", "openrouter": "free", "xai": "grok", "openai": "openai", "anthropic": "claude",
    }


# --------------------------------------------------------------------------- request shape


@pytest.mark.parametrize("kind", KINDS)
def test_request_goes_to_the_provider_with_its_key_and_its_model(kind):
    handler, seen = recording(served)
    status, data = make_upstream(kind, handler).chat_completion(BACKEND_REQUEST)

    assert status == 200 and data["model"] == MODELS[kind]
    (sent,) = seen
    assert str(sent.url) == URLS[kind]
    assert sent.headers["authorization"] == f"Bearer {KEYS[kind]}"
    body = sent_body(sent)
    assert body["model"] == MODELS[kind]  # grok-4.7 from the backend's config never reaches the provider
    assert "models" not in body and "stream" not in body


@pytest.mark.parametrize("kind", KINDS)
def test_whatever_model_the_caller_names_is_replaced(kind):
    handler, seen = recording(served, served, served)
    upstream = make_upstream(kind, handler)
    for model in ("grok-4.7", "parthenon-free", "gpt-5"):
        upstream.chat_completion({**BACKEND_REQUEST, "model": model})
    assert [sent_body(r)["model"] for r in seen] == [MODELS[kind]] * 3


def test_the_model_comes_from_the_environment_when_not_given(monkeypatch):
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4.1")
    upstream = gb.KeyedUpstream(gb.PROVIDERS["openai"], KEYS["openai"], httpx.Client(transport=httpx.MockTransport(no_network)))
    assert upstream.model == "gpt-4.1"
    monkeypatch.delenv("OPENAI_MODEL")
    upstream = gb.KeyedUpstream(gb.PROVIDERS["openai"], KEYS["openai"], httpx.Client(transport=httpx.MockTransport(no_network)))
    assert upstream.model == "gpt-4.1-mini"


def test_xai_gets_the_request_as_sent_apart_from_the_model():
    handler, seen = recording(served, served)
    upstream = make_upstream("xai", handler)
    upstream.chat_completion(BACKEND_REQUEST)
    upstream.chat_completion(OASIS_REQUEST)
    assert sent_body(seen[0]) == {**BACKEND_REQUEST, "model": MODELS["xai"]}
    assert sent_body(seen[1]) == {**OASIS_REQUEST, "model": MODELS["xai"]}


def test_openai_gets_max_completion_tokens_and_keeps_json_mode_and_temperature():
    handler, seen = recording(served, served)
    upstream = make_upstream("openai", handler)
    upstream.chat_completion(BACKEND_REQUEST)
    body = sent_body(seen[0])
    assert "max_tokens" not in body and body["max_completion_tokens"] == 4096
    assert body["response_format"] == {"type": "json_object"}
    assert body["temperature"] == 0.3
    assert body["messages"] == BACKEND_REQUEST["messages"]

    upstream.chat_completion(OASIS_REQUEST)  # tools, strict schemas and tool history pass unchanged
    assert sent_body(seen[1]) == {**OASIS_REQUEST, "model": MODELS["openai"]}


@pytest.mark.parametrize("model", ["gpt-5-mini", "gpt-6-luna", "o4-mini"])
def test_openai_reasoning_models_get_no_temperature(model):
    handler, seen = recording(served)
    make_upstream("openai", handler, model=model).chat_completion({**BACKEND_REQUEST, "top_p": 0.9})
    body = sent_body(seen[0])
    assert "temperature" not in body and "top_p" not in body
    assert body["max_completion_tokens"] == 4096 and body["model"] == model


def test_anthropic_json_mode_is_asked_for_in_words_and_the_fence_comes_off():
    fenced = '```json\n{"belief": "the city listened"}\n```'
    handler, seen = recording(lambda body: httpx.Response(200, json=chat_ok(body["model"], fenced)))
    status, data = make_upstream("anthropic", handler).chat_completion({**BACKEND_REQUEST, "temperature": 1.4})

    assert status == 200
    assert data["choices"][0]["message"]["content"] == '{"belief": "the city listened"}'
    body = sent_body(seen[0])
    assert "response_format" not in body  # ignored by Anthropic's compatibility endpoint
    assert body["temperature"] == 1.0  # Anthropic takes 0..1
    assert body["max_tokens"] == 4096
    assert body["messages"] == [
        BACKEND_REQUEST["messages"][0],
        {"role": "system", "content": gb.JSON_INSTRUCTION},
        BACKEND_REQUEST["messages"][1],
    ]


def test_anthropic_json_schema_puts_the_schema_in_the_instruction():
    schema = {"type": "object", "properties": {"stance": {"type": "string"}}, "required": ["stance"]}
    request = {
        "model": "grok-4.7",
        "messages": [{"role": "user", "content": "Your stance?"}],
        "response_format": {"type": "json_schema", "json_schema": {"name": "stance", "schema": schema}},
    }
    handler, seen = recording(served)
    make_upstream("anthropic", handler).chat_completion(request)
    first = sent_body(seen[0])["messages"][0]
    assert first["role"] == "system"
    assert first["content"].startswith(gb.JSON_INSTRUCTION)
    assert json.dumps(schema) in first["content"]


def test_anthropic_gets_a_token_cap_and_no_empty_text_beside_tool_calls():
    handler, seen = recording(served)
    make_upstream("anthropic", handler, anthropic_max_tokens=2048).chat_completion({**OASIS_REQUEST, "n": 1})
    body = sent_body(seen[0])
    assert body["max_tokens"] == 2048
    assert "n" not in body
    assert body["tools"] == [TOOL]
    assert body["messages"][2] == {**OASIS_REQUEST["messages"][2], "content": None}
    assert body["messages"][3] == OASIS_REQUEST["messages"][3]
    assert all(m["role"] != "system" or m["content"] != gb.JSON_INSTRUCTION for m in body["messages"])


def test_anthropic_keeps_the_callers_max_completion_tokens():
    handler, seen = recording(served)
    request = {"model": "x", "messages": [{"role": "user", "content": "hi"}], "max_completion_tokens": 300}
    make_upstream("anthropic", handler).chat_completion(request)
    body = sent_body(seen[0])
    assert body["max_completion_tokens"] == 300 and "max_tokens" not in body


def test_json_replies_are_left_alone_where_json_mode_is_honoured():
    fenced = '```json\n{"a": 1}\n```'
    handler, _ = recording(lambda body: httpx.Response(200, json=chat_ok(body["model"], fenced)))
    status, data = make_upstream("openai", handler).chat_completion(BACKEND_REQUEST)
    assert data["choices"][0]["message"]["content"] == fenced


@pytest.mark.parametrize("kind", KINDS)
def test_the_callers_request_is_never_changed(kind):
    request = copy.deepcopy(OASIS_REQUEST)
    handler, _ = recording(served, served)
    upstream = make_upstream(kind, handler)
    upstream.chat_completion(request)
    upstream.chat_completion({**BACKEND_REQUEST})
    assert request == OASIS_REQUEST


# --------------------------------------------------------------------------- refused parameters


def openai_refusal(param, message, code="unsupported_parameter"):
    return httpx.Response(400, json={"error": {
        "message": message, "type": "invalid_request_error", "param": param, "code": code,
    }})


def test_a_refused_parameter_is_dropped_retried_and_remembered(caplog):
    caplog.set_level(logging.INFO)
    refusal = openai_refusal(
        "temperature",
        "Unsupported value: 'temperature' does not support 0.3 with this model. Only the default (1) value is supported.",
        code="unsupported_value",
    )
    handler, seen = recording(refusal, served, served)
    sleeps = []
    upstream = make_upstream("openai", handler, sleeps=sleeps)

    assert upstream.chat_completion(BACKEND_REQUEST)[0] == 200
    assert "temperature" in sent_body(seen[0]) and "temperature" not in sent_body(seen[1])
    assert sleeps == []  # a refusal is fixed at once, not backed off

    assert upstream.chat_completion(BACKEND_REQUEST)[0] == 200  # later requests leave it out from the start
    assert len(seen) == 3 and "temperature" not in sent_body(seen[2])
    assert sum("refused 'temperature'" in r.getMessage() for r in caplog.records) == 1


def test_a_refused_max_tokens_becomes_max_completion_tokens():
    refusal = httpx.Response(400, json={"error": {
        "message": "Unsupported parameter: 'max_tokens' is not supported with this model. "
                   "Use 'max_completion_tokens' instead.",
        "type": "invalid_request_error", "param": "max_tokens", "code": "unsupported_parameter",
    }})
    handler, seen = recording(refusal, served)
    assert make_upstream("xai", handler).chat_completion(BACKEND_REQUEST)[0] == 200
    body = sent_body(seen[1])
    assert "max_tokens" not in body and body["max_completion_tokens"] == 4096


@pytest.mark.parametrize("error", [
    # xAI answers with a plain string error next to a code...
    {"code": "Client specified an invalid argument", "error": "Argument not supported on this model: presencePenalty"},
    # ...and the OpenAI shape is read the same way.
    {"error": {"message": "Model grok-4 does not support parameter presencePenalty."}},
])
def test_camel_case_parameter_names_in_refusals_are_understood(error):
    handler, seen = recording(httpx.Response(400, json=error), served)
    request = {**BACKEND_REQUEST, "presence_penalty": 0.5}
    assert make_upstream("xai", handler).chat_completion(request)[0] == 200
    assert "presence_penalty" in sent_body(seen[0]) and "presence_penalty" not in sent_body(seen[1])


def test_a_refused_response_format_is_replaced_by_the_json_instruction():
    refusal = openai_refusal("response_format", "response_format is not supported by this model")
    handler, seen = recording(refusal, served)
    assert make_upstream("xai", handler).chat_completion(BACKEND_REQUEST)[0] == 200
    body = sent_body(seen[1])
    assert "response_format" not in body
    assert {"role": "system", "content": gb.JSON_INSTRUCTION} in body["messages"]


@pytest.mark.parametrize("error", [
    {"error": {"message": "Unsupported parameter: 'logprobs'", "param": "logprobs", "code": "unsupported_parameter"}},
    {"error": {"message": "Invalid value for 'temperature': must be at most 2", "param": "temperature"}},
    {"error": {"message": "messages: text content blocks must be non-empty"}},
    {"error": "bad request"},
])
def test_other_400s_come_back_unchanged_without_a_retry(error):
    # logprobs was never sent; a plain invalid value is not a refusal; nothing in the others can be dropped.
    handler, seen = recording(httpx.Response(400, json=error))
    status, data = make_upstream("openai", handler).chat_completion(BACKEND_REQUEST)
    assert status == 400 and len(seen) == 1
    assert isinstance(data["error"], dict) and isinstance(data["error"]["message"], str)
    assert "type" in data["error"] and "code" in data["error"]


def test_refusals_stop_after_a_few_adaptations():
    params = ["temperature", "top_p", "seed", "stop", "user", "metadata"]
    replies = [openai_refusal(p, f"Unsupported parameter: '{p}'") for p in params]
    handler, seen = recording(*replies)
    request = {**BACKEND_REQUEST, "top_p": 1, "seed": 1, "stop": ["x"], "user": "u", "metadata": {"a": "b"}}
    status, data = make_upstream("openai", handler).chat_completion(request)
    assert status == 400
    assert len(seen) == gb.MAX_ADAPTATIONS + 1
    assert data["error"]["param"] == params[gb.MAX_ADAPTATIONS]


# --------------------------------------------------------------------------- errors, retries, keys


@pytest.mark.parametrize("kind", KINDS)
def test_a_rejected_key_is_the_bridges_own_401_without_any_of_the_key(kind):
    key = KEYS[kind]
    upstream_error = {"error": {
        "message": f"Incorrect API key provided: {key[:8]}****{key[-4:]}.", "type": "invalid_request_error",
        "code": "invalid_api_key",
    }}
    handler, seen = recording(httpx.Response(401, json=upstream_error))
    status, data = make_upstream(kind, handler).chat_completion(BACKEND_REQUEST)
    assert status == 401 and len(seen) == 1
    assert data["error"]["code"] == "provider_key_rejected"
    assert data["error"]["type"] == "grok_bridge_error"
    assert gb.PROVIDERS[kind].key_env in data["error"]["message"]
    assert key[-4:] not in json.dumps(data)


def test_a_missing_key_is_a_clear_401_without_calling_the_provider():
    upstream = make_upstream("openai", no_network, key="")
    status, data = upstream.chat_completion(BACKEND_REQUEST)
    assert status == 401
    assert data["error"]["code"] == "provider_key_missing"
    assert "OPENAI_API_KEY" in data["error"]["message"]
    assert upstream.health_info()["api_key_set"] is False


def test_a_key_added_later_is_picked_up():
    handler, seen = recording(served)
    keys = iter(["", KEYS["anthropic"]])
    upstream = make_upstream("anthropic", handler, key="", reload_key=lambda: next(keys))
    assert upstream.chat_completion(BACKEND_REQUEST)[0] == 401
    assert upstream.chat_completion(BACKEND_REQUEST)[0] == 200
    assert seen[0].headers["authorization"] == f"Bearer {KEYS['anthropic']}"


@pytest.mark.parametrize("kind", KINDS)
def test_429_and_5xx_are_retried_honouring_retry_after(kind):
    handler, seen = recording(
        httpx.Response(429, headers={"retry-after": "7"}, json={"error": {"message": "slow down"}}),
        httpx.Response(529, json={"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}}),
        served,
    )
    sleeps = []
    assert make_upstream(kind, handler, sleeps=sleeps).chat_completion(BACKEND_REQUEST)[0] == 200
    assert len(seen) == 3 and len(sleeps) == 2 and sleeps[0] >= 7


def test_gives_up_after_max_retries_with_an_openai_style_error():
    handler, seen = recording(*[httpx.Response(503, text="<html>upstream down</html>")] * 3)
    status, data = make_upstream("openai", handler, max_retries=2).chat_completion(BACKEND_REQUEST)
    assert status == 503 and len(seen) == 3
    assert data == {"error": {"message": "<html>upstream down</html>", "type": "openai_error", "code": None}}


def test_retries_stop_when_the_caller_would_have_given_up():
    clock = FakeClock()
    handler, seen = recording(httpx.Response(429, headers={"retry-after": "30"}, json={"error": {"message": "busy"}}))
    status, _ = make_upstream("xai", handler, clock=clock).chat_completion(BACKEND_REQUEST, budget=20)
    assert status == 429 and len(seen) == 1


def test_unreachable_provider_is_a_502_and_a_timeout_a_504():
    def broken(request):
        raise httpx.ConnectError("connection refused")

    status, data = make_upstream("openai", broken, max_retries=1).chat_completion(BACKEND_REQUEST)
    assert status == 502 and data["error"]["code"] == "upstream_unreachable"

    def slow(request):
        raise httpx.ReadTimeout("timed out")

    status, data = make_upstream("openai", slow).chat_completion(BACKEND_REQUEST)
    assert status == 504 and data["error"]["code"] == "upstream_timeout"


def test_throttle_paces_calls_and_429s_past_the_wait_cap():
    clock, sleeps = FakeClock(), []
    handler, seen = recording(*[served] * 5)
    upstream = make_upstream("openai", handler, clock=clock, sleeps=sleeps, rpm=6, throttle_wait=15)
    for _ in range(gb.PROVIDER_BURST + 1):
        assert upstream.chat_completion(BACKEND_REQUEST)[0] == 200
    assert sleeps == pytest.approx([10.0])
    status, data = upstream.chat_completion(BACKEND_REQUEST)
    assert status == 429 and data["error"]["code"] == "bridge_throttled"
    assert "PARTHENON_PROVIDER_RPM" in data["error"]["message"]
    assert len(seen) == gb.PROVIDER_BURST + 1


def test_the_key_never_appears_in_responses_or_logs(caplog):
    caplog.set_level(logging.DEBUG)
    key = KEYS["openai"]
    replies = iter([
        httpx.Response(429, json={"error": {"message": f"rate limited for Bearer {key}"}}),
        httpx.Response(400, json={"error": {"message": f"bad request from {key}", "param": None}}),
        httpx.Response(403, json={"error": f"key {key} lacks access"}),
        httpx.Response(401, json={"error": {"message": f"Incorrect API key provided: {key}"}}),
    ])
    auth_headers = []

    def handler(request):
        auth_headers.append(request.headers.get("authorization"))
        return next(replies)

    def broken(request):
        raise httpx.ConnectError(f"connection failed while sending Bearer {key}")

    bodies = []
    for fake, calls, retries in ((handler, 4, 0), (broken, 1, 1)):
        client = gb.create_app(make_upstream("openai", fake, max_retries=retries)).test_client()
        bodies.append(client.get("/health").get_data(as_text=True))
        bodies.append(client.get("/v1/models").get_data(as_text=True))
        for _ in range(calls):
            bodies.append(client.post("/v1/chat/completions", json=BACKEND_REQUEST).get_data(as_text=True))

    assert f"Bearer {key}" in auth_headers  # the key was really used...
    assert all(key not in body for body in bodies)  # ...but never echoed back
    assert "[redacted]" in "".join(bodies)
    assert key not in caplog.text


# --------------------------------------------------------------------------- HTTP server


@pytest.mark.parametrize("kind", KINDS)
def test_health_reports_provider_model_and_what_it_can_make(kind):
    health = gb.create_app(make_upstream(kind, no_network)).test_client().get("/health").get_json()
    assert health == {
        "status": "ok",
        "upstream": kind,
        "provider": gb.PROVIDERS[kind].label,
        "api_key_set": True,
        "api_key_env": gb.PROVIDERS[kind].key_env,
        "model": MODELS[kind],
        "requests_per_minute": None,
        "imagine": kind == "xai",
        "voice": kind == "xai",
    }


@pytest.mark.parametrize("kind", KINDS)
def test_models_lists_the_one_configured_model_without_calling_the_provider(kind):
    response = gb.create_app(make_upstream(kind, no_network)).test_client().get("/v1/models")
    assert response.status_code == 200
    assert [m["id"] for m in response.get_json()["data"]] == [MODELS[kind]]


def test_the_route_forwards_and_logs_the_model_it_was_served_as(caplog):
    caplog.set_level(logging.INFO)
    handler, seen = recording(lambda body: httpx.Response(200, json=chat_ok("gpt-4.1-mini-2025-04-14")))
    client = gb.create_app(make_upstream("openai", handler)).test_client()
    response = client.post(
        "/v1/chat/completions", json=BACKEND_REQUEST, headers={"x-stainless-read-timeout": "600"},
    )
    assert response.status_code == 200
    assert response.get_json()["model"] == "gpt-4.1-mini-2025-04-14"
    assert any(
        "grok-4.7 -> HTTP 200" in r.getMessage() and "via openai as gpt-4.1-mini-2025-04-14" in r.getMessage()
        for r in caplog.records
    )


def test_a_busy_bridge_says_when_to_come_back():
    upstream = make_upstream("openai", no_network, max_concurrency=1)
    upstream._slots.acquire()  # the only slot is taken
    client = gb.create_app(upstream).test_client()
    response = client.post("/v1/chat/completions", json=BACKEND_REQUEST, headers={"x-stainless-read-timeout": "0.2"})
    assert response.status_code == 429
    assert response.headers["Retry-After"] == str(gb.BRIDGE_RETRY_AFTER)
    assert response.get_json()["error"]["code"] == "bridge_throttled"


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("headers", [{"Origin": "https://some-website.example"}, {"Host": "attacker.example:5055"}])
def test_browser_and_non_local_requests_are_refused(kind, headers):
    client = gb.create_app(make_upstream(kind, no_network)).test_client()
    response = client.post("/v1/chat/completions", json=BACKEND_REQUEST, headers=headers)
    assert response.status_code == 403


def test_allowed_hosts_add_a_specific_listen_address_but_never_a_wildcard():
    assert gb._allowed_hosts("127.0.0.1") == gb.LOCAL_HOSTS
    assert gb._allowed_hosts("0.0.0.0") == gb.LOCAL_HOSTS
    assert gb._allowed_hosts("::") == gb.LOCAL_HOSTS
    assert gb._allowed_hosts("10.0.0.5") == gb.LOCAL_HOSTS | {"10.0.0.5"}

    handler, _ = recording(served)
    client = gb.create_app(make_upstream("xai", handler), allowed_hosts=gb._allowed_hosts("10.0.0.5")).test_client()
    assert client.post("/v1/chat/completions", json=BACKEND_REQUEST, headers={"Host": "10.0.0.5:5055"}).status_code == 200
    assert client.post("/v1/chat/completions", json=BACKEND_REQUEST, headers={"Host": "10.0.0.6:5055"}).status_code == 403


def _import_in_a_subprocess(env_overrides):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GROK_BRIDGE_")}
    env.update(env_overrides)
    code = "import grok_bridge as gb; print(gb.HOST, gb.PORT)"
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=Path(gb.__file__).parent, env=env,
        capture_output=True, text=True, timeout=60, check=True,
    )
    return result.stdout.split()


def test_listen_host_and_port_come_from_the_environment():
    # The module loads the project's .env over the environment; if it pins these, there is nothing to test here.
    if {"GROK_BRIDGE_HOST", "GROK_BRIDGE_PORT"} & set(dotenv_values(gb.PROJECT_ROOT / ".env")):
        pytest.skip(".env sets GROK_BRIDGE_HOST or GROK_BRIDGE_PORT")
    assert _import_in_a_subprocess({}) == ["127.0.0.1", "5055"]
    assert _import_in_a_subprocess({"GROK_BRIDGE_HOST": "0.0.0.0", "GROK_BRIDGE_PORT": "6055"}) == ["0.0.0.0", "6055"]


# --------------------------------------------------------------------------- Imagine and voice


IMAGE_REQUEST = {"model": "grok-imagine-image-2.0", "prompt": "A marble agora at dusk", "n": 1}
VIDEO_REQUEST = {"model": "grok-imagine-video-1.5", "prompt": "Slow push in", "duration": 5}
TTS_REQUEST = {"text": "The city spoke.", "voice_id": "eve", "language": "en"}
MP3 = b"ID3\x04\x00\x00\x00" + bytes(range(64))
ROUTES = [
    ("post", "/v1/images/generations", IMAGE_REQUEST),
    ("post", "/v1/videos/generations", VIDEO_REQUEST),
    ("get", "/v1/videos/req_123", None),
    ("post", "/v1/tts", TTS_REQUEST),
]


def send(client, method, path, body):
    return getattr(client, method)(path) if body is None else getattr(client, method)(path, json=body)


@pytest.mark.parametrize("path, body", [
    ("/v1/images/generations", IMAGE_REQUEST), ("/v1/videos/generations", VIDEO_REQUEST),
])
def test_xai_key_serves_imagine_unchanged(path, body):
    handler, seen = recording(httpx.Response(200, json={"data": [{"url": "https://imgen.x.ai/a.jpg"}]}))
    response = gb.create_app(make_upstream("xai", handler)).test_client().post(path, json=body)
    assert response.status_code == 200
    (sent,) = seen
    assert str(sent.url) == "https://api.x.ai" + path
    assert sent_body(sent) == body  # Imagine models are xAI's own: not replaced
    assert sent.headers["authorization"] == f"Bearer {KEYS['xai']}"


def test_xai_key_serves_video_polls_and_voice():
    handler, seen = recording(
        httpx.Response(202, json={"status": "pending"}),
        httpx.Response(200, content=MP3, headers={"content-type": "audio/mpeg"}),
    )
    client = gb.create_app(make_upstream("xai", handler)).test_client()
    poll = client.get("/v1/videos/req_123")
    assert poll.status_code == 202 and poll.get_json() == {"status": "pending"}
    assert seen[0].method == "GET" and str(seen[0].url) == "https://api.x.ai/v1/videos/req_123"

    voice = client.post("/v1/tts", json=TTS_REQUEST)
    assert voice.status_code == 200 and voice.data == MP3 and voice.headers["Content-Type"] == "audio/mpeg"
    assert str(seen[1].url) == "https://api.x.ai/v1/tts" and sent_body(seen[1]) == TTS_REQUEST


@pytest.mark.parametrize("method, path, body", ROUTES)
def test_xai_imagine_backs_off_on_429_and_5xx(method, path, body):
    final = (
        httpx.Response(200, content=MP3, headers={"content-type": "audio/mpeg"}) if path == "/v1/tts"
        else httpx.Response(200, json={"ok": True})
    )
    handler, seen = recording(
        httpx.Response(429, headers={"retry-after": "5"}, json={"error": "rate limited"}),
        httpx.Response(503, json={"error": "busy"}),
        final,
    )
    sleeps = []
    response = send(gb.create_app(make_upstream("xai", handler, sleeps=sleeps)).test_client(), method, path, body)
    assert response.status_code == 200 and len(seen) == 3
    assert len(sleeps) == 2 and sleeps[0] >= 5


@pytest.mark.parametrize("method, path, body", ROUTES)
def test_xai_imagine_errors_are_scrubbed_and_a_bad_key_is_the_bridges_401(method, path, body):
    key = KEYS["xai"]
    handler, _ = recording(
        httpx.Response(403, json={"error": f"team of {key} has no credits"}),
        httpx.Response(401, json={"error": f"invalid key {key}"}),
    )
    client = gb.create_app(make_upstream("xai", handler)).test_client()
    first = send(client, method, path, body)
    assert first.status_code == 403
    assert key not in first.get_data(as_text=True) and "[redacted]" in first.get_data(as_text=True)
    second = send(client, method, path, body)
    assert second.status_code == 401 and second.get_json()["error"]["code"] == "provider_key_rejected"
    assert key not in second.get_data(as_text=True)


@pytest.mark.parametrize("kind", ["openai", "anthropic"])
@pytest.mark.parametrize("method, path, body", ROUTES)
def test_openai_and_anthropic_answer_imagine_501(kind, method, path, body):
    response = send(gb.create_app(make_upstream(kind, no_network)).test_client(), method, path, body)
    assert response.status_code == 501
    error = response.get_json()["error"]
    assert error["code"] == "imagine_unavailable"
    assert error["message"] == gb.KEYED_IMAGINE_UNAVAILABLE
    assert "XAI_API_KEY" in error["message"]


def test_missing_xai_key_is_a_clear_401_for_imagine():
    response = gb.create_app(make_upstream("xai", no_network, key="")).test_client().post(
        "/v1/images/generations", json=IMAGE_REQUEST,
    )
    assert response.status_code == 401
    assert response.get_json()["error"]["code"] == "provider_key_missing"


# --------------------------------------------------------------------------- CLI


def test_status_reports_a_keyed_upstream_without_the_key(monkeypatch, capsys):
    monkeypatch.setattr(gb, "UPSTREAM", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", KEYS["openai"])
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4.1")
    assert gb.cmd_status(None) == 0
    out = capsys.readouterr().out
    assert "Upstream:     openai" in out and "API key:      set (OPENAI_API_KEY)" in out
    assert "Model:        gpt-4.1 (OPENAI_MODEL)" in out
    assert KEYS["openai"] not in out

    monkeypatch.setenv("OPENAI_API_KEY", "")
    assert gb.cmd_status(None) == 1
    assert "missing (OPENAI_API_KEY)" in capsys.readouterr().out


def test_status_shows_what_auto_chose(monkeypatch, capsys):
    monkeypatch.setattr(gb, "UPSTREAM", "auto")
    for name in ("XAI_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", KEYS["anthropic"])
    assert gb.cmd_status(None) == 0
    out = capsys.readouterr().out
    assert "Upstream:     auto -> anthropic" in out
    assert KEYS["anthropic"] not in out


def test_probe_without_a_key_says_which_one_is_missing(monkeypatch, capsys):
    monkeypatch.setenv("XAI_API_KEY", "")

    class Args:
        upstream, model, mode = "xai", None, "auto"

    assert gb.cmd_probe(Args) == 1
    assert "XAI_API_KEY is not set" in capsys.readouterr().out
