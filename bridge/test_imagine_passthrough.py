"""Imagine (image/video) and voice passthrough for "Film the Chronicle". No network: httpx.MockTransport only."""

import base64
import json
import threading
import time

import httpx
import pytest

import grok_bridge as gb


TOKEN_ENDPOINT = "https://auth.x.ai/oauth2/token"
IMAGE_REQUEST = {
    "model": "grok-imagine-image-2.0", "prompt": "A marble agora at dusk", "n": 1,
    "aspect_ratio": "16:9", "response_format": "b64_json",
}
VIDEO_REQUEST = {
    "model": "grok-imagine-video-1.5", "prompt": "Slow push in on the agora",
    "image": {"url": "data:image/jpeg;base64,/9j/4AAQSkZJRg=="}, "duration": 5,
}
TTS_REQUEST = {"text": "In the first week, [pause] the city spoke.", "voice_id": "eve", "language": "en"}
MP3 = b"ID3\x04\x00\x00\x00\x00\x00\x00\xff\xfb\x90\x00" + bytes(range(256))


def make_jwt(expires_in: float = 3600) -> str:
    def encode(obj):
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()

    return f"{encode({'alg': 'none'})}.{encode({'exp': time.time() + expires_in})}.sig"


def no_network(request):
    raise AssertionError(f"unexpected request to {request.url}")


def make_upstream(tmp_path, handler, **kwargs):
    http = httpx.Client(transport=httpx.MockTransport(handler))
    store = gb.TokenStore(tmp_path / "t.json", http)
    store.save({"access_token": make_jwt(), "refresh_token": "refresh-1", "token_endpoint": TOKEN_ENDPOINT})
    kwargs.setdefault("mode", "chat")
    return gb.Upstream(store, http, **kwargs)


def recording(*replies):
    """A handler that records each request and answers from `replies` in turn."""
    seen = []
    replies_iter = iter(replies)

    def handler(request):
        seen.append(request)
        return next(replies_iter)

    return handler, seen


def client_for(upstream):
    return gb.create_app(upstream).test_client()


ROUTES = [
    ("post", "/v1/images/generations", IMAGE_REQUEST),
    ("post", "/v1/videos/generations", VIDEO_REQUEST),
    ("get", "/v1/videos/7f3c2a1e-5b4d-4c8e-9a0b-1d2e3f4a5b6c", None),
    ("post", "/v1/tts", TTS_REQUEST),
]


def send(client, method, path, body, **kwargs):
    if body is None:
        return getattr(client, method)(path, **kwargs)
    return getattr(client, method)(path, json=body, **kwargs)


# --------------------------------------------------------------------------- forwarding


@pytest.mark.parametrize("path, body, reply", [
    ("/v1/images/generations", IMAGE_REQUEST, {"data": [{"b64_json": "aGVsbG8=", "mime_type": "image/jpeg"}]}),
    ("/v1/videos/generations", VIDEO_REQUEST, {"request_id": "7f3c2a1e-5b4d-4c8e-9a0b-1d2e3f4a5b6c"}),
])
def test_json_posts_are_forwarded_unchanged_with_the_subscription_token(tmp_path, path, body, reply):
    handler, seen = recording(httpx.Response(200, json=reply))
    upstream = make_upstream(tmp_path, handler)
    response = client_for(upstream).post(path, json=body, headers={"Authorization": "Bearer caller-key-ignored"})

    assert response.status_code == 200
    assert response.get_json() == reply
    (sent,) = seen
    assert sent.method == "POST"
    assert str(sent.url) == "https://api.x.ai" + path
    assert json.loads(sent.content) == body
    assert sent.headers["authorization"] == f"Bearer {upstream.store.load()['access_token']}"


def test_video_poll_is_a_get_to_the_request_id_and_keeps_the_final_status(tmp_path):
    done = {
        "status": "done", "model": "grok-imagine-video-1.5", "progress": 100,
        "video": {"url": "https://vidgen.x.ai/abc.mp4", "duration": 5, "respect_moderation": True},
    }
    handler, seen = recording(httpx.Response(200, json=done))
    upstream = make_upstream(tmp_path, handler)
    response = client_for(upstream).get("/v1/videos/7f3c2a1e-5b4d-4c8e-9a0b-1d2e3f4a5b6c")

    assert response.status_code == 200 and response.get_json() == done
    (sent,) = seen
    assert sent.method == "GET"
    assert str(sent.url) == "https://api.x.ai/v1/videos/7f3c2a1e-5b4d-4c8e-9a0b-1d2e3f4a5b6c"
    assert sent.content == b""
    assert sent.headers["authorization"] == f"Bearer {upstream.store.load()['access_token']}"


def test_pending_video_poll_passes_202_through(tmp_path):
    handler, seen = recording(httpx.Response(202, json={"status": "pending"}))
    response = client_for(make_upstream(tmp_path, handler)).get("/v1/videos/req_123")
    assert response.status_code == 202
    assert response.get_json() == {"status": "pending"}
    assert len(seen) == 1  # a 202 is an answer, not something to retry


@pytest.mark.parametrize("status, body", [
    (200, {"status": "failed", "error": "moderated"}),
    (200, {"status": "expired"}),
    (400, {"error": "Invalid argument: resolution"}),
    (404, {"error": "request not found"}),
])
def test_imagine_errors_and_terminal_statuses_pass_through(tmp_path, status, body):
    handler, _ = recording(httpx.Response(status, json=body))
    response = client_for(make_upstream(tmp_path, handler)).get("/v1/videos/req_123")
    assert (response.status_code, response.get_json()) == (status, body)


def test_tts_returns_the_raw_audio_bytes_with_the_upstream_content_type(tmp_path):
    handler, seen = recording(httpx.Response(200, content=MP3, headers={"content-type": "audio/mpeg"}))
    upstream = make_upstream(tmp_path, handler)
    response = client_for(upstream).post("/v1/tts", json=TTS_REQUEST)

    assert response.status_code == 200
    assert response.data == MP3
    assert response.headers["Content-Type"] == "audio/mpeg"
    (sent,) = seen
    assert sent.method == "POST"
    assert str(sent.url) == "https://api.x.ai/v1/tts"
    assert json.loads(sent.content) == TTS_REQUEST
    assert sent.headers["authorization"] == f"Bearer {upstream.store.load()['access_token']}"


def test_tts_keeps_other_audio_content_types(tmp_path):
    handler, _ = recording(httpx.Response(200, content=b"RIFF....WAVE", headers={"content-type": "audio/wav"}))
    response = client_for(make_upstream(tmp_path, handler)).post("/v1/tts", json=TTS_REQUEST)
    assert response.data == b"RIFF....WAVE" and response.headers["Content-Type"] == "audio/wav"


def test_tts_errors_come_back_as_json(tmp_path):
    error = {"error": "voice_id must be one of eve, ara, rex"}
    handler, _ = recording(httpx.Response(400, json=error))
    response = client_for(make_upstream(tmp_path, handler)).post("/v1/tts", json={**TTS_REQUEST, "voice_id": "x"})
    assert response.status_code == 400
    assert response.get_json() == error


# --------------------------------------------------------------------------- auth and retries


@pytest.mark.parametrize("method, path, body", ROUTES)
def test_401_refreshes_the_token_once_and_retries(tmp_path, method, path, body):
    fresh = make_jwt()
    auth_headers = []
    refreshes = []

    def handler(request):
        if request.url.host == "auth.x.ai":
            refreshes.append(1)
            return httpx.Response(200, json={"access_token": fresh, "refresh_token": "refresh-2"})
        auth_headers.append(request.headers["authorization"])
        if len(auth_headers) == 1:
            return httpx.Response(401, json={"error": "token expired"})
        if path == "/v1/tts":
            return httpx.Response(200, content=MP3, headers={"content-type": "audio/mpeg"})
        return httpx.Response(200, json={"ok": True})

    response = send(client_for(make_upstream(tmp_path, handler)), method, path, body)
    assert response.status_code == 200
    assert len(refreshes) == 1
    assert len(auth_headers) == 2 and auth_headers[-1] == f"Bearer {fresh}"


def test_a_second_401_is_returned_rather_than_refreshing_again(tmp_path):
    refreshes = []

    def handler(request):
        if request.url.host == "auth.x.ai":
            refreshes.append(1)
            return httpx.Response(200, json={"access_token": make_jwt(), "refresh_token": "refresh-2"})
        return httpx.Response(401, json={"error": "subscription does not include Imagine"})

    response = client_for(make_upstream(tmp_path, handler)).post("/v1/images/generations", json=IMAGE_REQUEST)
    assert response.status_code == 401
    assert response.get_json() == {"error": "subscription does not include Imagine"}
    assert len(refreshes) == 1


@pytest.mark.parametrize("method, path, body", ROUTES)
def test_429_and_5xx_back_off_honouring_retry_after(tmp_path, method, path, body):
    final = (
        httpx.Response(200, content=MP3, headers={"content-type": "audio/mpeg"}) if path == "/v1/tts"
        else httpx.Response(200, json={"ok": True})
    )
    handler, seen = recording(
        httpx.Response(429, headers={"retry-after": "7"}, json={"error": "rate limited"}),
        httpx.Response(503, json={"error": "busy"}),
        final,
    )
    sleeps = []
    upstream = make_upstream(tmp_path, handler, sleep=sleeps.append)
    response = send(client_for(upstream), method, path, body)

    assert response.status_code == 200
    assert len(seen) == 3
    assert len(sleeps) == 2 and sleeps[0] >= 7


def test_unreachable_xai_is_a_json_502_even_for_tts(tmp_path):
    def broken(request):
        raise httpx.ConnectError("connection refused")

    upstream = make_upstream(tmp_path, broken, max_retries=1, sleep=lambda s: None)
    response = client_for(upstream).post("/v1/tts", json=TTS_REQUEST)
    assert response.status_code == 502
    assert response.get_json()["error"]["code"] == "upstream_unreachable"


@pytest.mark.parametrize("method, path, body", ROUTES)
def test_missing_sign_in_is_a_clear_401(tmp_path, method, path, body):
    http = httpx.Client(transport=httpx.MockTransport(no_network))
    upstream = gb.Upstream(gb.TokenStore(tmp_path / "missing.json", http), http)
    response = send(client_for(upstream), method, path, body)
    assert response.status_code == 401
    assert response.get_json()["error"]["code"] == "grok_not_signed_in"


# --------------------------------------------------------------------------- validation and guards


@pytest.mark.parametrize("request_id", [
    "bad.id", "..", "a%20b", "abc$", "id%3Bdrop", "x" * 129, "%2E%2E",
])
def test_invalid_video_request_ids_are_rejected_before_any_call(tmp_path, request_id):
    response = client_for(make_upstream(tmp_path, no_network)).get(f"/v1/videos/{request_id}")
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "invalid_request_error"


def test_slashes_in_a_request_id_never_reach_xai(tmp_path):
    client = client_for(make_upstream(tmp_path, no_network))
    assert client.get("/v1/videos/a%2Fb").status_code == 404
    assert client.get("/v1/videos/../models").status_code == 404


@pytest.mark.parametrize("request_id", ["../models", "a/b", "a?b=c", "a#b", "", "é", None, 42])
def test_upstream_refuses_unsafe_request_ids_even_when_called_directly(tmp_path, request_id):
    status, data = make_upstream(tmp_path, no_network).video_status(request_id)
    assert status == 400 and data["error"]["code"] == "invalid_request_error"


def test_valid_request_id_shapes():
    assert gb._valid_request_id("7f3c2a1e-5b4d-4c8e-9a0b-1d2e3f4a5b6c")
    assert gb._valid_request_id("req_ABC123")
    assert not gb._valid_request_id("x" * 129)


@pytest.mark.parametrize("path", ["/v1/images/generations", "/v1/videos/generations", "/v1/tts"])
def test_non_json_bodies_are_refused(tmp_path, path):
    client = client_for(make_upstream(tmp_path, no_network))
    assert client.post(path, data="prompt=hi", content_type="text/plain").status_code == 400
    assert client.post(path, json=["not", "an", "object"]).status_code == 400


@pytest.mark.parametrize("method, path, body", ROUTES)
@pytest.mark.parametrize("headers", [
    {"Origin": "https://some-website.example"},
    {"Origin": "null"},
    {"Host": "attacker.example:5055"},
])
def test_browser_and_non_local_requests_are_refused(tmp_path, method, path, body, headers):
    response = send(client_for(make_upstream(tmp_path, no_network)), method, path, body, headers=headers)
    assert response.status_code == 403
    assert response.get_json()["error"]["code"] == "forbidden"


# --------------------------------------------------------------------------- OpenRouter mode


@pytest.mark.parametrize("method, path, body", ROUTES)
def test_openrouter_upstream_answers_501(method, path, body):
    upstream = gb.OpenRouterUpstream("sk-or-v1-test", httpx.Client(transport=httpx.MockTransport(no_network)))
    response = send(client_for(upstream), method, path, body)
    assert response.status_code == 501
    error = response.get_json()["error"]
    assert error["message"] == "Filming needs the Grok subscription upstream (set PARTHENON_UPSTREAM=grok)."
    assert error["code"] == "imagine_unavailable"


def test_openrouter_501_comes_before_request_id_validation():
    upstream = gb.OpenRouterUpstream("sk-or-v1-test", httpx.Client(transport=httpx.MockTransport(no_network)))
    assert client_for(upstream).get("/v1/videos/bad.id").status_code == 501


def test_health_reports_whether_imagine_is_available(tmp_path):
    grok = client_for(make_upstream(tmp_path, no_network)).get("/health").get_json()
    assert grok["imagine"] is True
    openrouter = gb.OpenRouterUpstream("sk-or-v1-test", httpx.Client(transport=httpx.MockTransport(no_network)))
    assert client_for(openrouter).get("/health").get_json()["imagine"] is False


# --------------------------------------------------------------------------- concurrency


def test_imagine_concurrency_limit_is_its_own_semaphore(tmp_path):
    upstream = make_upstream(tmp_path, no_network)
    assert upstream.imagine_concurrency == gb.IMAGINE_CONCURRENCY
    assert isinstance(upstream._imagine_slots, type(threading.BoundedSemaphore(1)))
    assert upstream._imagine_slots is not upstream._slots
    assert make_upstream(tmp_path, no_network, imagine_concurrency=5).imagine_concurrency == 5


def test_slow_imagine_calls_queue_on_their_own_limit_and_never_block_chat(tmp_path):
    release = threading.Event()
    lock = threading.Lock()
    in_flight = {"images": 0, "peak": 0, "chat": 0}

    def handler(request):
        if request.url.path == "/v1/chat/completions":
            in_flight["chat"] += 1
            return httpx.Response(200, json={"choices": [{"message": {"content": "hi"}}]})
        with lock:
            in_flight["images"] += 1
            in_flight["peak"] = max(in_flight["peak"], in_flight["images"])
        release.wait(5)
        with lock:
            in_flight["images"] -= 1
        return httpx.Response(200, json={"data": []})

    upstream = make_upstream(tmp_path, handler, max_concurrency=1, imagine_concurrency=2)
    results = []
    threads = [
        threading.Thread(target=lambda: results.append(upstream.generate_image(IMAGE_REQUEST)[0])) for _ in range(4)
    ]
    for thread in threads:
        thread.start()
    deadline = time.time() + 5
    while in_flight["images"] < 2 and time.time() < deadline:
        time.sleep(0.01)
    time.sleep(0.05)  # give a third render the chance to (wrongly) start

    # Both Imagine slots are busy, and the only chat slot is still free: chat answers while renders run.
    assert in_flight["images"] == 2
    chat = []
    chat_request = {"model": "grok", "messages": []}
    chat_thread = threading.Thread(target=lambda: chat.append(upstream.chat_completion(chat_request)))
    chat_thread.start()
    chat_thread.join(2)
    assert not release.is_set() and chat and chat[0][0] == 200
    assert in_flight["chat"] == 1 and in_flight["images"] == 2

    release.set()
    for thread in threads:
        thread.join(5)
    assert results == [200, 200, 200, 200]
    assert in_flight["peak"] == 2
