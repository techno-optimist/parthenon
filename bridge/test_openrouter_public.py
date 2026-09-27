"""OpenRouter on the public site: the free-model router never takes over, and the app is attributed to
projectforty2.ai/parthenon. No network: httpx.MockTransport only."""

import json
import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

import grok_bridge as gb
from test_openrouter_upstream import (
    GEMMA, MODELS, NEMOTRON, QWEN, REQUEST, ROUTER, FakeClock, chat_ok, make_upstream, rate_limited, recording,
    served,
)


def overloaded():
    return httpx.Response(503, json={"error": {"message": "Upstream error from Nvidia: Service temporarily overloaded",
                                               "code": 503}})


def labelled(model):
    return lambda body: httpx.Response(200, json=chat_ok(model))


# --------------------------------------------------------------------------- the router entry


def test_a_reply_through_the_router_does_not_change_the_next_requests_order():
    # What the check saw: one 503 on the first model, the retry's fallback list reaches openrouter/free,
    # which answers as some other model. Every later request used to start at openrouter/free.
    handler, sent = recording([overloaded(), labelled("cohere/north-mini-code:free"), served, served])
    upstream = make_upstream(handler)
    fresh_handler, fresh = recording([served])
    make_upstream(fresh_handler).chat_completion(REQUEST)

    status, data = upstream.chat_completion({**REQUEST, "model": "parthenon-free"})
    assert status == 200 and data["model"] == "cohere/north-mini-code:free"
    assert sent[1] == (GEMMA, [GEMMA, QWEN, ROUTER])
    assert upstream.health_info()["current_model"] is None

    upstream.chat_completion({**REQUEST, "model": "parthenon-free"})
    upstream.chat_completion({**REQUEST, "model": "parthenon-free"})
    assert sent[2] == sent[3] == fresh[0] == (NEMOTRON, [NEMOTRON, GEMMA, QWEN])


def test_a_router_reply_keeps_the_named_model_that_was_answering():
    handler, sent = recording([rate_limited(), served, labelled("liquid/lfm-2.5-2.6b:free"), served])
    upstream = make_upstream(handler)
    upstream.chat_completion(REQUEST)
    assert upstream.health_info()["current_model"] == GEMMA

    # A caller that names the router gets it, and its pick is not remembered.
    upstream.chat_completion({**REQUEST, "model": ROUTER})
    assert sent[2] == (ROUTER, [ROUTER, NEMOTRON, GEMMA])
    assert upstream.health_info()["current_model"] == GEMMA

    upstream.chat_completion(REQUEST)
    assert sent[3] == (GEMMA, [GEMMA, QWEN, ROUTER])


def test_a_named_model_reached_through_the_fallback_list_is_still_remembered():
    handler, sent = recording([overloaded(), labelled(QWEN), served])
    upstream = make_upstream(handler)
    upstream.chat_completion(REQUEST)
    assert sent[1] == (GEMMA, [GEMMA, QWEN, ROUTER])
    assert upstream.health_info()["current_model"] == QWEN
    upstream.chat_completion(REQUEST)
    assert sent[2][0] == QWEN


@pytest.mark.parametrize("reported, tried, expected", [
    (QWEN, [GEMMA, QWEN, ROUTER], QWEN),
    ("qwen/qwen3.8-27b", [GEMMA, QWEN, ROUTER], QWEN),  # the ":free" suffix dropped
    ("cohere/north-mini-code:free", [GEMMA, QWEN, ROUTER], None),
    ("nvidia/nemotron-3.5-content-safety:free", [ROUTER, NEMOTRON, GEMMA], None),
    (None, [GEMMA, QWEN, ROUTER], None),
    (ROUTER, [ROUTER, NEMOTRON, GEMMA], ROUTER),
    ("some/renamed-model", [NEMOTRON, GEMMA, QWEN], NEMOTRON),  # no router tried: as before
    ("openrouter/auto-picked", [NEMOTRON, "openrouter/auto"], None),
])
def test_matching_entry(reported, tried, expected):
    assert gb._matching_entry(reported, tried) == expected


def test_the_model_router_never_starts_from_a_router_entry():
    clock = FakeClock()
    router = gb.ModelRouter(MODELS, clock=clock)
    router.answered(ROUTER, [ROUTER, NEMOTRON, GEMMA])
    router.answered("openrouter/auto", ["openrouter/auto"])
    assert router.healthy is None
    assert router.order_for("parthenon-free") == MODELS

    router.answered(GEMMA, [GEMMA, QWEN, ROUTER])
    router.answered("anything/else:free", [QWEN, ROUTER, NEMOTRON])
    assert router.healthy == GEMMA


# --------------------------------------------------------------------------- the public default list


def test_public_default_models_leave_out_the_router():
    assert gb._model_list(None, public=True) == [NEMOTRON, GEMMA, QWEN]
    assert gb._model_list("  ", public=True) == [NEMOTRON, GEMMA, QWEN]
    assert gb._model_list(None) == MODELS  # the local default is unchanged
    # A list the owner sets is taken as it is, router and all.
    assert gb._model_list(f"{GEMMA}, {ROUTER}", public=True) == [GEMMA, ROUTER]


def test_public_default_never_sends_a_router_entry_even_when_every_model_fails():
    handler, sent = recording([lambda body: overloaded()] * 6)
    upstream = gb.OpenRouterUpstream(
        "sk-or-v1-test-secret", httpx.Client(transport=httpx.MockTransport(handler)),
        models=gb._model_list(None, public=True), clock=FakeClock(), sleep=[].append, rpm=0, max_retries=5,
    )
    status, _ = upstream.chat_completion(REQUEST)
    assert status == 503
    assert len(sent) == 6
    assert all(not gb._is_router(model) for first, models in sent for model in [first, *models])


# --------------------------------------------------------------------------- attribution


@pytest.mark.parametrize("value, public", [
    ("1", True), ("true", True), (" Yes ", True), ("on", True),
    ("0", False), ("", False), (None, False), ("false", False), ("no", False),
])
def test_public_flag_reads_like_the_backends(value, public):
    assert gb._public({} if value is None else {"PARTHENON_PUBLIC": value}) is public


@pytest.mark.parametrize("environ, referer", [
    ({}, "http://localhost:3000"),
    ({"PARTHENON_PUBLIC": "0"}, "http://localhost:3000"),
    ({"PARTHENON_PUBLIC": "1"}, "https://projectforty2.ai/parthenon"),
    ({"OPENROUTER_APP_URL": "https://example.org/city"}, "https://example.org/city"),
    ({"PARTHENON_PUBLIC": "1", "OPENROUTER_APP_URL": " https://example.org/city "}, "https://example.org/city"),
    ({"PARTHENON_PUBLIC": "1", "OPENROUTER_APP_URL": "javascript:alert(1)"}, "https://projectforty2.ai/parthenon"),
    ({"PARTHENON_PUBLIC": "1", "OPENROUTER_APP_URL": "https://a.example/\r\nX-Evil: 1"},
     "https://projectforty2.ai/parthenon"),
    ({"OPENROUTER_APP_URL": "not a url"}, "http://localhost:3000"),
    ({"OPENROUTER_APP_URL": "ftp://files.example"}, "http://localhost:3000"),
])
def test_openrouter_attribution(environ, referer):
    assert gb._openrouter_app_headers(environ) == {"X-Title": "Parthenon", "HTTP-Referer": referer}


def test_public_attribution_is_sent_to_openrouter():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=chat_ok(NEMOTRON))

    upstream = make_upstream(handler, app_headers=gb._openrouter_app_headers({"PARTHENON_PUBLIC": "1"}))
    assert upstream.chat_completion(REQUEST)[0] == 200
    assert seen[0].headers["http-referer"] == "https://projectforty2.ai/parthenon"
    assert seen[0].headers["x-title"] == "Parthenon"


# --------------------------------------------------------------------------- wiring at import


def _imported_settings(**env):
    """OPENROUTER_MODELS and OPENROUTER_APP_HEADERS as a fresh bridge process computes them from `env`."""
    child = {k: v for k, v in os.environ.items() if k not in (
        "PARTHENON_PUBLIC", "OPENROUTER_MODELS", "OPENROUTER_APP_URL",
    )}
    child.update(env)
    script = (
        "import dotenv; dotenv.load_dotenv = lambda *a, **k: False\n"  # this test's env only, not the .env
        "import json, grok_bridge as gb\n"
        "print(json.dumps({'models': gb.OPENROUTER_MODELS, 'headers': gb.OPENROUTER_APP_HEADERS}))\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", script], cwd=Path(gb.__file__).parent, env=child,
        capture_output=True, text=True, timeout=60, check=True,
    ).stdout
    return json.loads(out.strip().splitlines()[-1])


def test_public_mode_is_wired_at_import():
    public = _imported_settings(PARTHENON_PUBLIC="1")
    assert public["models"] == [NEMOTRON, GEMMA, QWEN]
    assert public["headers"]["HTTP-Referer"] == "https://projectforty2.ai/parthenon"

    local = _imported_settings()
    assert local["models"] == MODELS
    assert local["headers"] == {"X-Title": "Parthenon", "HTTP-Referer": "http://localhost:3000"}
