#!/usr/bin/env python3
"""
Grok subscription bridge for Parthenon (a local MiroFish instance).

MiroFish and the OASIS simulator it drives call an OpenAI-style Chat
Completions API with a fixed API key. This bridge lets them run on a
SuperGrok / X Premium+ subscription instead of a pay-per-token xAI API key.

    login   one-time OAuth device-code sign-in at auth.x.ai
    serve   OpenAI-compatible endpoint on 127.0.0.1 that attaches a fresh
            subscription token to each request and forwards it to api.x.ai
    status  show sign-in state (never prints tokens)
    probe   send a couple of tiny requests and report what xAI accepts
    logout  delete the stored sign-in

Tokens live in ~/.config/parthenon/grok-oauth.json (mode 0600), separate from
any other app's sign-in: xAI rotates the refresh token on every refresh, so two
apps sharing one grant would keep invalidating each other.

Caveat: this uses xAI's unpublished CLI OAuth client (the same flow Hermes
Agent uses). xAI may reject some subscription tiers or change it at any time.

The Grok upstream also passes xAI's Imagine and voice endpoints through for
"Film the Chronicle" (POST /v1/images/generations, POST /v1/videos/generations,
GET /v1/videos/<request_id>, POST /v1/tts), under their own concurrency limit
(GROK_BRIDGE_IMAGINE_CONCURRENCY) so slow renders never hold up chat requests.

With PARTHENON_UPSTREAM=openrouter the same endpoint forwards to OpenRouter's
free models instead (OPENROUTER_API_KEY, optional OPENROUTER_MODELS and
OPENROUTER_RPM), with model fallback and a throttle sized for the free tier.
Filming needs the Grok upstream: there the Imagine and voice routes answer 501.
"""

from __future__ import annotations

import argparse
import base64
import fcntl
import json
import logging
import os
import random
import re
import sys
import threading
import time
import uuid
import webbrowser
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Tuple, Union
from urllib.parse import urlparse

import httpx
from dotenv import dotenv_values, load_dotenv
from flask import Flask, Response, jsonify, request

PROJECT_ROOT = Path(__file__).resolve().parent.parent
# GROK_BRIDGE_* / OPENROUTER_* settings may live in the shared .env, which wins over stale shell
# exports just as it does for the backend (backend/app/config.py also loads it with override=True).
load_dotenv(PROJECT_ROOT / ".env", override=True)

# xAI OAuth device-code grant, using the public client the Grok CLI and Hermes Agent use.
ISSUER = "https://auth.x.ai"
DISCOVERY_URL = f"{ISSUER}/.well-known/openid-configuration"
DEVICE_CODE_URL = f"{ISSUER}/oauth2/device/code"
CLIENT_ID = "b1a00492-073a-47ea-816f-4c329264a828"
SCOPE = "openid profile email offline_access grok-cli:access api:access"
DEVICE_CODE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
FORM_HEADERS = {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"}

UPSTREAM_BASE_URL = "https://api.x.ai/v1"
REFRESH_SKEW_SECONDS = 120  # refresh this long before the access token's JWT `exp`
REVOKED_GRANT_ERRORS = {"invalid_grant", "invalid_token", "invalid_client", "unauthorized_client"}

TOKEN_FILE = Path(
    os.environ.get("GROK_BRIDGE_TOKEN_FILE", "~/.config/parthenon/grok-oauth.json")
).expanduser()
PORT = int(os.environ.get("GROK_BRIDGE_PORT", "5055"))
MAX_CONCURRENCY = int(os.environ.get("GROK_BRIDGE_MAX_CONCURRENCY", "6"))
MAX_RETRIES = int(os.environ.get("GROK_BRIDGE_MAX_RETRIES", "5"))
MODE = os.environ.get("GROK_BRIDGE_MODE", "auto")  # auto | chat | responses
# Image/video/voice calls take their own slots: a 17 s image render must never hold a chat slot.
IMAGINE_CONCURRENCY = max(1, int(os.environ.get("GROK_BRIDGE_IMAGINE_CONCURRENCY", "3")))
IMAGINE_UNAVAILABLE = "Filming needs the Grok subscription upstream (set PARTHENON_UPSTREAM=grok)."
# xAI video request ids go into the poll URL, so only plain id characters are let through.
VIDEO_REQUEST_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")

LOGIN_HINT = "Run `npm run grok:login` in the parthenon folder to sign in with your Grok subscription."

# Which service `serve` forwards to: the Grok subscription or OpenRouter's free models.
UPSTREAMS = ("grok", "openrouter")
UPSTREAM = (os.environ.get("PARTHENON_UPSTREAM") or "grok").strip().lower()

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_APP_HEADERS = {"X-Title": "Parthenon", "HTTP-Referer": "http://localhost:3000"}
DEFAULT_OPENROUTER_MODELS = (
    "nvidia/nemotron-3-super-120b-a12b:free,google/gemma-4-31b-it:free,qwen/qwen3.8-27b:free,openrouter/free"
)
FREE_MODEL_ALIAS = "parthenon-free"  # request model that means "use OPENROUTER_MODELS"
OPENROUTER_RPM = float(os.environ.get("OPENROUTER_RPM", "18"))  # free models allow ~20/min; 0 turns the throttle off
OPENROUTER_BURST = 2  # any 60 s window then carries at most BURST + RPM (= 20) requests
OPENROUTER_FALLBACK_LIMIT = 3  # OpenRouter accepts at most 3 entries in `models`
OPENROUTER_THROTTLE_WAIT = 120.0  # longest a request queues for a throttle token before it gets a 429
HEALTHY_MODEL_SECONDS = 300.0  # keep starting with the model that last answered for this long
DAILY_LIMIT_RECHECK_SECONDS = 300.0  # after a per-day 429, answer locally for this long instead of asking again

UPSTREAM_TIMEOUT = 300.0  # longest the bridge waits for one upstream reply
CONNECT_TIMEOUT = 15.0
# How long a caller waits for its reply. The OpenAI SDK says so in x-stainless-read-timeout (180 s for
# the OASIS agents, 600 s for the backend); a caller that does not is assumed to give up at about this.
DEFAULT_CALLER_BUDGET = 150.0
CALLER_TIMEOUT_MARGIN = 10.0  # finish this long before the caller's own timeout so it still reads the reply
MIN_ATTEMPT_SECONDS = 10.0  # never start an upstream call with less than this left of the caller's budget
BRIDGE_RETRY_AFTER = 20  # Retry-After on the bridge's own 429s: about one pass of 6 slots through 18/min

OPENROUTER_KEY_HINT = (
    "OPENROUTER_API_KEY is not set. Add it to the .env in the parthenon folder (a running bridge "
    "picks it up on the next request), or switch PARTHENON_UPSTREAM to grok and restart `npm run dev`."
)
DAILY_LIMIT_MESSAGE = (
    "OpenRouter's free daily limit is used up; it resets at 00:00 UTC. "
    "Add credits to OpenRouter or switch PARTHENON_UPSTREAM to grok."
)


def _model_list(raw: Optional[str]) -> List[str]:
    """OPENROUTER_MODELS as an ordered list, falling back to the defaults when unset or blank."""
    models = [m.strip() for m in (raw or "").split(",") if m.strip()]
    return models or [m.strip() for m in DEFAULT_OPENROUTER_MODELS.split(",")]


OPENROUTER_MODELS = _model_list(os.environ.get("OPENROUTER_MODELS"))

log = logging.getLogger("grok-bridge")


class AuthError(Exception):
    """No usable sign-in: never signed in, signed out, or the grant was revoked."""


class RefreshUnavailable(Exception):
    """A token refresh failed for a transient reason (network, xAI outage)."""


def _json_body(response: httpx.Response) -> Dict[str, Any]:
    try:
        data = response.json()
    except ValueError:
        return {"error": {"message": response.text[:500] or f"HTTP {response.status_code}"}}
    return data if isinstance(data, dict) else {"data": data}


def _error_body(message: str, code: str, error_type: str = "grok_bridge_error") -> Dict[str, Any]:
    return {"error": {"message": message, "type": error_type, "code": code}}


class Audio(NamedTuple):
    """A binary upstream reply (xAI text-to-speech) that the bridge hands back byte for byte."""

    content: bytes
    content_type: str


def _valid_request_id(request_id: Any) -> bool:
    return isinstance(request_id, str) and VIDEO_REQUEST_ID.fullmatch(request_id) is not None


def _jwt_claims(token: Any) -> Dict[str, Any]:
    """Decode a JWT payload for expiry/display only (no signature check)."""
    if not isinstance(token, str) or token.count(".") < 2:
        return {}
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
    except ValueError:
        return {}
    return claims if isinstance(claims, dict) else {}


def _identity(state: Dict[str, Any]) -> str:
    claims = _jwt_claims(state.get("id_token")) or _jwt_claims(state.get("access_token"))
    for key in ("email", "preferred_username", "name", "sub"):
        if claims.get(key):
            return str(claims[key])
    return "your Grok account"


def _require_xai_url(url: str, field: str) -> str:
    """Only ever send tokens to https://*.x.ai (guards against a tampered discovery doc or token file)."""
    parsed = urlparse(url or "")
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not (host == "x.ai" or host.endswith(".x.ai")):
        raise AuthError(f"Refusing to use non-xAI {field}: {url!r}")
    return url


def discover_token_endpoint(http: httpx.Client) -> str:
    response = http.get(DISCOVERY_URL, headers={"Accept": "application/json"})
    response.raise_for_status()
    return _require_xai_url(str(response.json().get("token_endpoint", "")), "token_endpoint")


# --------------------------------------------------------------------------- tokens


class TokenStore:
    """Reads, refreshes and persists the subscription tokens.

    Refresh tokens are single-use, so refreshes are serialised with a thread
    lock plus an flock on a sibling lock file, and the file is re-read under
    the lock in case another process (e.g. a re-login) already updated it.
    """

    def __init__(self, path: Path, http: httpx.Client):
        self.path = path
        self.http = http
        self._lock = threading.Lock()
        self._state: Optional[Dict[str, Any]] = None
        self._mtime: Optional[int] = None

    def load(self) -> Optional[Dict[str, Any]]:
        try:
            mtime = self.path.stat().st_mtime_ns
        except FileNotFoundError:
            self._state, self._mtime = None, None
            return None
        if mtime != self._mtime:
            self._state = json.loads(self.path.read_text())
            self._mtime = mtime
        return self._state

    def save(self, state: Dict[str, Any]) -> None:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as handle:
            json.dump(state, handle, indent=2)
        os.replace(tmp, self.path)
        self._state, self._mtime = state, self.path.stat().st_mtime_ns

    def delete(self) -> bool:
        with self.file_lock():
            try:
                self.path.unlink()
            except FileNotFoundError:
                return False
        self._state, self._mtime = None, None
        return True

    @contextmanager
    def file_lock(self):
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with open(self.path.with_name(self.path.name + ".lock"), "a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def access_token(self, *, rejected: Optional[str] = None) -> str:
        """A usable access token; refreshes near expiry or when `rejected` just got a 401."""
        with self._lock:
            token = self._current_token()
            if not self._needs_refresh(token, rejected):
                return token
            with self.file_lock():
                token = self._current_token()
                if not self._needs_refresh(token, rejected):
                    return token
                return self._refresh(self.load())["access_token"]

    def _current_token(self) -> str:
        state = self.load()
        if not state or not state.get("access_token"):
            raise AuthError(f"Not signed in to Grok. {LOGIN_HINT}")
        if state.get("revoked"):
            raise AuthError(f"Grok sign-in stopped working ({state['revoked']}). {LOGIN_HINT}")
        return state["access_token"]

    @staticmethod
    def _needs_refresh(token: str, rejected: Optional[str]) -> bool:
        if rejected is not None and token == rejected:
            return True
        exp = _jwt_claims(token).get("exp")
        return isinstance(exp, (int, float)) and exp - time.time() < REFRESH_SKEW_SECONDS

    def _refresh(self, state: Dict[str, Any]) -> Dict[str, Any]:
        try:
            endpoint = _require_xai_url(
                state.get("token_endpoint") or discover_token_endpoint(self.http), "token_endpoint"
            )
            response = self.http.post(
                endpoint,
                headers=FORM_HEADERS,
                data={
                    "grant_type": "refresh_token",
                    "client_id": CLIENT_ID,
                    "refresh_token": state["refresh_token"],
                },
            )
        except httpx.HTTPError as exc:
            raise RefreshUnavailable(f"Could not reach xAI to refresh the Grok sign-in: {exc}") from exc

        payload = _json_body(response)
        if response.status_code == 200 and payload.get("access_token"):
            refreshed = {
                **state,
                "access_token": payload["access_token"],
                "refresh_token": payload.get("refresh_token") or state["refresh_token"],
                "id_token": payload.get("id_token") or state.get("id_token"),
                "expires_in": payload.get("expires_in"),
                "token_endpoint": endpoint,
                "refreshed_at": int(time.time()),
            }
            self.save(refreshed)
            log.info("Refreshed the Grok subscription token")
            return refreshed

        error = payload.get("error")
        if response.status_code in (400, 401) and error in REVOKED_GRANT_ERRORS:
            # Remember it so every queued request doesn't retry a dead refresh token.
            self.save({**state, "revoked": error})
            raise AuthError(f"Grok sign-in expired or was revoked ({error}). {LOGIN_HINT}")
        raise RefreshUnavailable(f"xAI token refresh failed: HTTP {response.status_code} {error or ''}".strip())


# --------------------------------------------------------------------------- translation
# Used only when xAI refuses Chat Completions for subscription tokens and the
# bridge has to speak the Responses API instead.


def _text_of(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    return "".join(
        part.get("text", "")
        for part in content
        if isinstance(part, dict) and part.get("type") in ("text", "input_text", "output_text")
    )


def _user_content(content: Any) -> Any:
    if not isinstance(content, list):
        return content or ""
    parts: List[Dict[str, Any]] = []
    for part in content:
        kind = part.get("type") if isinstance(part, dict) else None
        if kind == "text":
            parts.append({"type": "input_text", "text": part.get("text", "")})
        elif kind == "image_url":
            image = part.get("image_url")
            converted = {"type": "input_image", "image_url": image.get("url") if isinstance(image, dict) else image}
            if isinstance(image, dict) and image.get("detail"):
                converted["detail"] = image["detail"]
            parts.append(converted)
        elif kind is not None:
            parts.append(part)
    return parts


def chat_to_responses(body: Dict[str, Any]) -> Dict[str, Any]:
    """Chat Completions request -> Responses API request."""
    items: List[Dict[str, Any]] = []
    for message in body.get("messages") or []:
        role = message.get("role")
        if role in ("system", "developer"):
            items.append({"role": "system", "content": _text_of(message.get("content"))})
        elif role == "user":
            items.append({"role": "user", "content": _user_content(message.get("content"))})
        elif role == "assistant":
            text = _text_of(message.get("content"))
            if text:
                items.append({"role": "assistant", "content": text})
            for call in message.get("tool_calls") or []:
                function = call.get("function") or {}
                items.append({
                    "type": "function_call",
                    "call_id": call.get("id"),
                    "name": function.get("name"),
                    "arguments": function.get("arguments") or "{}",
                })
        elif role == "tool":
            items.append({
                "type": "function_call_output",
                "call_id": message.get("tool_call_id"),
                "output": _text_of(message.get("content")),
            })

    converted: Dict[str, Any] = {"model": body.get("model"), "input": items, "store": False}
    for key in ("temperature", "top_p", "parallel_tool_calls"):
        if body.get(key) is not None:
            converted[key] = body[key]
    limit = body.get("max_completion_tokens") or body.get("max_tokens")
    if limit:
        converted["max_output_tokens"] = limit
    if body.get("reasoning_effort"):
        converted["reasoning"] = {"effort": body["reasoning_effort"]}

    tools = []
    for tool in body.get("tools") or []:
        if tool.get("type") != "function":
            continue
        function = tool.get("function") or {}
        spec = {
            "type": "function",
            "name": function.get("name"),
            "description": function.get("description", ""),
            "parameters": function.get("parameters") or {"type": "object", "properties": {}},
        }
        if "strict" in function:
            spec["strict"] = function["strict"]
        tools.append(spec)
    if tools:
        converted["tools"] = tools

    choice = body.get("tool_choice")
    if isinstance(choice, dict) and choice.get("type") == "function":
        converted["tool_choice"] = {"type": "function", "name": (choice.get("function") or {}).get("name")}
    elif choice is not None:
        converted["tool_choice"] = choice

    response_format = body.get("response_format")
    if isinstance(response_format, dict):
        if response_format.get("type") == "json_object":
            converted["text"] = {"format": {"type": "json_object"}}
        elif response_format.get("type") == "json_schema":
            schema = response_format.get("json_schema") or {}
            text_format = {
                "type": "json_schema",
                "name": schema.get("name", "response"),
                "schema": schema.get("schema") or {},
            }
            if "strict" in schema:
                text_format["strict"] = schema["strict"]
            converted["text"] = {"format": text_format}
    return converted


def responses_to_chat(response: Dict[str, Any], request_body: Dict[str, Any]) -> Dict[str, Any]:
    """Responses API result -> Chat Completions result."""
    texts: List[str] = []
    tool_calls: List[Dict[str, Any]] = []
    reasoning: List[str] = []
    for item in response.get("output") or []:
        kind = item.get("type")
        if kind == "message":
            for part in item.get("content") or []:
                if part.get("type") in ("output_text", "text"):
                    texts.append(part.get("text", ""))
                elif part.get("type") == "refusal":
                    texts.append(part.get("refusal", ""))
        elif kind == "function_call":
            tool_calls.append({
                "id": item.get("call_id") or item.get("id"),
                "type": "function",
                "function": {"name": item.get("name"), "arguments": item.get("arguments") or "{}"},
            })
        elif kind == "reasoning":
            reasoning.extend(s.get("text", "") for s in item.get("summary") or [] if isinstance(s, dict))

    message: Dict[str, Any] = {"role": "assistant", "content": "".join(texts) if texts or not tool_calls else None}
    if tool_calls:
        message["tool_calls"] = tool_calls
    if reasoning:
        message["reasoning_content"] = "\n".join(reasoning)

    incomplete = (response.get("incomplete_details") or {}).get("reason")
    if tool_calls:
        finish_reason = "tool_calls"
    elif response.get("status") == "incomplete" and incomplete in ("max_output_tokens", "max_tokens"):
        finish_reason = "length"
    elif response.get("status") == "incomplete" and incomplete == "content_filter":
        finish_reason = "content_filter"
    else:
        finish_reason = "stop"

    usage = response.get("usage") or {}
    prompt_tokens = usage.get("input_tokens", 0)
    completion_tokens = usage.get("output_tokens", 0)
    return {
        "id": response.get("id") or f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(response.get("created_at") or time.time()),
        "model": response.get("model") or request_body.get("model"),
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason, "logprobs": None}],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": usage.get("total_tokens", prompt_tokens + completion_tokens),
        },
    }


# --------------------------------------------------------------------------- upstream


class Upstream:
    """Forwards Chat Completions requests to xAI with the subscription token.

    mode "auto" tries Chat Completions first and permanently switches to the
    Responses API if xAI answers 403/404 for the subscription token.

    Imagine (image/video) and text-to-speech requests are passed through
    unchanged, on a separate semaphore from chat so long renders cannot
    starve the simulation's chat completions.
    """

    imagine = True  # serves the Imagine / voice routes (OpenRouterUpstream does not)

    def __init__(
        self,
        store: TokenStore,
        http: httpx.Client,
        *,
        mode: str = MODE,
        max_concurrency: int = MAX_CONCURRENCY,
        imagine_concurrency: int = IMAGINE_CONCURRENCY,
        max_retries: int = MAX_RETRIES,
        sleep: Callable[[float], None] = time.sleep,
    ):
        if mode not in ("auto", "chat", "responses"):
            raise ValueError(f"GROK_BRIDGE_MODE must be auto, chat or responses (got {mode!r})")
        self.store = store
        self.http = http
        self.mode = mode
        self.max_retries = max_retries
        self.imagine_concurrency = imagine_concurrency
        self._slots = threading.BoundedSemaphore(max_concurrency)
        self._imagine_slots = threading.BoundedSemaphore(imagine_concurrency)
        self._sleep = sleep

    def chat_completion(self, body: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        with self._slots:
            if self.mode != "responses":
                status, data = self._request("POST", "/chat/completions", body)
                if not (self.mode == "auto" and status in (403, 404)):
                    if self.mode == "auto" and status == 200:
                        self.mode = "chat"
                        log.info("xAI accepts Chat Completions for the subscription token")
                    return status, data
                log.warning(
                    "xAI rejected Chat Completions for the subscription token (HTTP %s); "
                    "using the Responses API from now on",
                    status,
                )
                self.mode = "responses"
            status, data = self._request("POST", "/responses", chat_to_responses(body))
            if status != 200:
                return status, data
            return 200, responses_to_chat(data, body)

    def models(self) -> Tuple[int, Dict[str, Any]]:
        return self._request("GET", "/models")

    # Imagine and voice: JSON in, xAI's status and body out (202 included, for a video still rendering).

    def generate_image(self, body: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        with self._imagine_slots:
            return self._request("POST", "/images/generations", body)

    def generate_video(self, body: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        with self._imagine_slots:
            return self._request("POST", "/videos/generations", body)

    def video_status(self, request_id: str) -> Tuple[int, Dict[str, Any]]:
        if not _valid_request_id(request_id):  # checked again here because it becomes part of the URL
            return 400, _error_body("Invalid video request_id", "invalid_request_error")
        with self._imagine_slots:
            return self._request("GET", f"/videos/{request_id}")

    def speech(self, body: Dict[str, Any]) -> Tuple[int, Union[Audio, Dict[str, Any]]]:
        """Text to speech: the audio bytes and their Content-Type on success, xAI's JSON error otherwise."""
        with self._imagine_slots:
            response = self._send("POST", "/tts", body, accept="*/*")
        if isinstance(response, tuple):
            return response
        content_type = response.headers.get("content-type", "")
        if response.status_code == 200 and not content_type.startswith("application/json"):
            return 200, Audio(response.content, content_type or "audio/mpeg")
        return response.status_code, _json_body(response)

    def _request(self, method: str, path: str, payload: Optional[Dict[str, Any]] = None) -> Tuple[int, Dict[str, Any]]:
        response = self._send(method, path, payload)
        if isinstance(response, tuple):
            return response
        return response.status_code, _json_body(response)

    def _send(
        self, method: str, path: str, payload: Optional[Dict[str, Any]] = None, *, accept: str = "application/json",
    ) -> Union[httpx.Response, Tuple[int, Dict[str, Any]]]:
        """xAI's final reply after the 401 refresh and 429/5xx backoff, or the bridge's own error if unreachable."""
        token = self.store.access_token()
        refreshed_after_401 = False
        attempt = 0
        while True:
            try:
                response = self.http.request(
                    method,
                    UPSTREAM_BASE_URL + path,
                    json=payload,
                    headers={"Authorization": f"Bearer {token}", "Accept": accept},
                )
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                # The request never reached xAI, so sending it again cannot run it twice.
                if attempt >= self.max_retries:
                    return 502, _error_body(f"Could not reach xAI: {exc}", "upstream_unreachable")
                self._backoff(attempt, None)
                attempt += 1
                continue
            except httpx.TimeoutException:
                # xAI may still be working on it: no automatic retry of a POST it may already have run.
                return 504, _error_body("xAI did not answer in time.", "upstream_timeout")
            except httpx.TransportError as exc:
                return 502, _error_body(f"Lost the connection to xAI: {exc}", "upstream_unreachable")
            if response.status_code == 401 and not refreshed_after_401:
                token = self.store.access_token(rejected=token)
                refreshed_after_401 = True
                continue
            if (response.status_code == 429 or response.status_code >= 500) and attempt < self.max_retries:
                self._backoff(attempt, response.headers.get("retry-after"))
                attempt += 1
                continue
            return response

    def _backoff(self, attempt: int, retry_after: Optional[str]) -> None:
        delay = _retry_delay(attempt, retry_after)
        log.warning("xAI is busy or unavailable; retrying in %.1fs", delay)
        self._sleep(delay)

    def health_info(self) -> Dict[str, Any]:
        state = self.store.load() or {}
        signed_in = bool(state.get("access_token")) and not state.get("revoked")
        return {"upstream": "grok", "signed_in": signed_in, "mode": self.mode, "imagine": True}


def _retry_delay(attempt: int, retry_after: Optional[str]) -> float:
    """Exponential backoff with jitter, stretched to honour Retry-After, capped at 60 s."""
    try:
        delay = float(retry_after) if retry_after else 0.0
    except ValueError:
        delay = 0.0
    return min(max(delay, 2 ** attempt + random.random()), 60.0)


# --------------------------------------------------------------------------- OpenRouter upstream


class TokenBucket:
    """Thread-safe token bucket: `rate_per_minute` sustained, up to `capacity` back to back.

    A caller that has to wait reserves its token by taking the balance below
    zero before sleeping, so concurrent callers queue in arrival order instead
    of all waking at once and racing for the same token.
    """

    def __init__(
        self,
        rate_per_minute: float,
        capacity: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        if rate_per_minute <= 0:
            raise ValueError("rate_per_minute must be positive")
        self.rate = rate_per_minute / 60.0  # tokens per second
        self.capacity = max(1.0, float(capacity))
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._tokens = self.capacity
        self._updated = clock()

    def acquire(self, max_wait: float) -> bool:
        """Take a token, sleeping until it is due; False (and nothing taken) if that exceeds `max_wait`."""
        with self._lock:
            now = self._clock()
            self._tokens = min(self.capacity, self._tokens + (now - self._updated) * self.rate)
            self._updated = now
            wait = 0.0 if self._tokens >= 1 else (1 - self._tokens) / self.rate
            if wait > max_wait:
                return False
            self._tokens -= 1
        if wait > 0:
            self._sleep(wait)
        return True


class ModelRouter:
    """Orders the free models for each request and remembers which one last answered."""

    def __init__(
        self,
        models: List[str],
        *,
        healthy_seconds: float = HEALTHY_MODEL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ):
        if not models:
            raise ValueError("OPENROUTER_MODELS is empty")
        self.models = list(models)
        self._healthy_seconds = healthy_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._healthy: Optional[str] = None
        self._healthy_until = 0.0

    @property
    def healthy(self) -> Optional[str]:
        with self._lock:
            return self._healthy if self._clock() < self._healthy_until else None

    def order_for(self, requested: Any) -> List[str]:
        """The whole list, starting from the requested model if it is one of ours, else from the healthy one."""
        start = requested if isinstance(requested, str) and requested in self.models else self.healthy
        if start is None:
            return list(self.models)
        index = self.models.index(start)
        return self.models[index:] + self.models[:index]

    def answered(self, reported: Any, tried: List[str]) -> None:
        """Remember which of the `tried` entries produced a reply OpenRouter labels `reported`."""
        entry = _matching_entry(reported, tried)
        with self._lock:
            self._healthy = entry
            self._healthy_until = self._clock() + self._healthy_seconds

    def failed(self, model: str) -> None:
        with self._lock:
            if self._healthy == model:
                self._healthy = None


def _matching_entry(reported: Any, tried: List[str]) -> str:
    if isinstance(reported, str):
        if reported in tried:
            return reported
        base = reported.split(":")[0]  # OpenRouter may drop the ":free" variant suffix
        for entry in tried:
            if entry.split(":")[0] == base:
                return entry
    # A router entry such as openrouter/free replies under the id of whichever model it picked.
    return next((entry for entry in tried if entry.startswith("openrouter/")), tried[0])


def _error_message(data: Dict[str, Any]) -> str:
    error = data.get("error")
    if isinstance(error, dict):
        return str(error.get("message") or "")
    return str(error or "")


def _is_free_model(model: Dict[str, Any]) -> bool:
    if str(model.get("id", "")).endswith(":free"):
        return True
    pricing = model.get("pricing") or {}
    try:
        return float(pricing.get("prompt")) == 0 and float(pricing.get("completion")) == 0
    except (TypeError, ValueError):
        return False


class OpenRouterUpstream:
    """Forwards Chat Completions requests to OpenRouter's free models (PARTHENON_UPSTREAM=openrouter).

    Each request carries OpenRouter's native fallback list ("models", at most
    three entries). On a 429/5xx the bridge also rotates its own ordering and
    retries, remembers the model that answered so later requests start there,
    and a TokenBucket keeps every attempt under the free tier's per-minute cap.
    """

    mode = "openrouter"  # shown in the request log line, like Upstream.mode
    imagine = False  # OpenRouter has no Grok Imagine / voice: those routes answer 501

    def __init__(
        self,
        api_key: Optional[str],
        http: httpx.Client,
        *,
        models: Optional[List[str]] = None,
        rpm: float = OPENROUTER_RPM,
        max_concurrency: int = MAX_CONCURRENCY,
        max_retries: int = MAX_RETRIES,
        throttle_wait: float = OPENROUTER_THROTTLE_WAIT,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        reload_key: Optional[Callable[[], str]] = None,
    ):
        self.api_key = (api_key or "").strip()
        self.http = http
        self.router = ModelRouter(models or OPENROUTER_MODELS, clock=clock)
        self.rpm = rpm
        self.max_concurrency = max_concurrency
        self.max_retries = max_retries
        self.throttle_wait = throttle_wait
        self._bucket = TokenBucket(rpm, OPENROUTER_BURST, clock=clock, sleep=sleep) if rpm > 0 else None
        self._slots = threading.BoundedSemaphore(max_concurrency)
        self._sleep = sleep
        self._clock = clock
        self._reload_key = reload_key
        self._daily_limit_until: Optional[float] = None

    def chat_completion(self, body: Dict[str, Any], budget: Optional[float] = None) -> Tuple[int, Dict[str, Any]]:
        """Forward one request, giving up before the caller's `budget` (seconds it will wait) runs out.

        Werkzeug keeps running a handler after its caller hangs up, and the caller's SDK then sends a
        duplicate, so work past the budget would only spend free-tier quota on replies nobody reads.
        """
        if not self._ensure_key():
            return 401, _error_body(OPENROUTER_KEY_HINT, "openrouter_key_missing", "openrouter_bridge_error")
        budget = DEFAULT_CALLER_BUDGET if budget is None else budget
        arrived = self._clock()
        deadline = arrived + budget
        last_start = deadline - min(MIN_ATTEMPT_SECONDS, budget / 2)  # latest moment worth calling OpenRouter
        # The semaphore waits in real time; the clock is time.monotonic outside tests.
        if not self._slots.acquire(timeout=max(0.0, last_start - arrived)):
            return self._throttled(last_start - arrived)
        try:
            order = self.router.order_for(body.get("model"))
            attempt = 0
            while True:
                if self._daily_limit_until is not None and self._clock() < self._daily_limit_until:
                    return 429, _error_body(DAILY_LIMIT_MESSAGE, "openrouter_daily_limit", "openrouter_bridge_error")
                max_wait = max(0.0, min(self.throttle_wait, last_start - self._clock()))
                if self._bucket is not None and not self._bucket.acquire(max_wait):
                    return self._throttled(max_wait)
                tried = order[:OPENROUTER_FALLBACK_LIMIT]
                timeout = max(1.0, min(UPSTREAM_TIMEOUT, deadline - self._clock()))
                try:
                    response = self.http.post(
                        OPENROUTER_BASE_URL + "/chat/completions",
                        json={**body, "model": tried[0], "models": tried},
                        headers=self._headers(),
                        timeout=httpx.Timeout(timeout, connect=min(CONNECT_TIMEOUT, timeout)),
                    )
                except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                    # The request never reached OpenRouter, so sending it again cannot run it twice.
                    message = f"Could not reach OpenRouter: {self._scrub(str(exc))}"
                    if attempt < self.max_retries and self._backoff(attempt, None, message, last_start):
                        attempt += 1
                        continue
                    return 502, _error_body(message, "upstream_unreachable", "openrouter_bridge_error")
                except httpx.TimeoutException:
                    # OpenRouter may still be generating (and counting it against the free quota): no
                    # automatic retry, the caller decides, and its own timeout is close anyway.
                    message = f"OpenRouter did not answer within {timeout:.0f}s."
                    return 504, _error_body(message, "upstream_timeout", "openrouter_bridge_error")
                except httpx.TransportError as exc:
                    # The connection broke after the request went out, so OpenRouter may have run it.
                    message = f"Lost the connection to OpenRouter: {self._scrub(str(exc))}"
                    return 502, _error_body(message, "upstream_unreachable", "openrouter_bridge_error")

                status, data = response.status_code, _json_body(response)
                if status == 200 and not data.get("choices") and isinstance(data.get("error"), dict):
                    # OpenRouter can report a provider failure inside an HTTP 200 body.
                    code = data["error"].get("code")
                    status = code if isinstance(code, int) and 400 <= code < 600 else 502
                if status == 200:
                    self.router.answered(data.get("model"), tried)
                    return 200, data
                if status == 429 and "per-day" in _error_message(data).lower():
                    # The daily free quota is account-wide: other models or retries cannot help.
                    self._daily_limit_until = self._clock() + DAILY_LIMIT_RECHECK_SECONDS
                    log.warning("OpenRouter's free daily limit is used up (resets at 00:00 UTC)")
                    return 429, _error_body(DAILY_LIMIT_MESSAGE, "openrouter_daily_limit", "openrouter_bridge_error")
                if (status == 429 or status >= 500) and attempt < self.max_retries:
                    self.router.failed(tried[0])
                    order = order[1:] + order[:1]
                    reason = f"OpenRouter HTTP {status} for {tried[0]} ({self._scrub(_error_message(data))[:160]})"
                    retry_after = response.headers.get("retry-after")
                    if self._backoff(attempt, retry_after, f"{reason}; next up {order[0]}", last_start):
                        attempt += 1
                        continue
                return status, data
        finally:
            self._slots.release()

    def _throttled(self, waited: float) -> Tuple[int, Dict[str, Any]]:
        """The bridge's own 429 (create_app adds Retry-After) for a request it could not start in time."""
        if self._bucket is not None:
            message = (
                f"The bridge paces OpenRouter to {self.rpm:g} requests/min for the free tier and this "
                f"request would have waited more than {waited:.0f}s. Retry shortly, or raise "
                "OPENROUTER_RPM if your OpenRouter account allows more."
            )
        else:
            message = (
                f"All {self.max_concurrency} of the bridge's OpenRouter slots stayed busy for more than "
                f"{waited:.0f}s. Retry shortly."
            )
        return 429, _error_body(message, "bridge_throttled", "openrouter_bridge_error")

    def _ensure_key(self) -> bool:
        """Whether a key is set; while it is missing, re-read it so one added to .env works without a restart."""
        if not self.api_key and self._reload_key is not None:
            self.api_key = self._reload_key()
            if self.api_key:
                log.info("Picked up OPENROUTER_API_KEY from .env")
        return bool(self.api_key)

    def models(self) -> Tuple[int, Dict[str, Any]]:
        """OpenRouter's model list, cut down to the free models."""
        try:
            response = self.http.get(OPENROUTER_BASE_URL + "/models", headers=self._headers())
        except httpx.TransportError as exc:
            message = f"Could not reach OpenRouter: {self._scrub(str(exc))}"
            return 502, _error_body(message, "upstream_unreachable", "openrouter_bridge_error")
        data = _json_body(response)
        if response.status_code != 200:
            return response.status_code, data
        free = [m for m in data.get("data") or [] if isinstance(m, dict) and _is_free_model(m)]
        return 200, {"object": "list", "data": free}

    def health_info(self) -> Dict[str, Any]:
        return {
            "upstream": "openrouter",
            "api_key_set": self._ensure_key(),
            "models": list(self.router.models),
            "current_model": self.router.healthy,
            "requests_per_minute": self.rpm if self._bucket is not None else None,
            "imagine": False,
        }

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Accept": "application/json", **OPENROUTER_APP_HEADERS}

    def _scrub(self, text: str) -> str:
        """Belt and braces: never echo the API key, even if an error message somehow contains it."""
        return text.replace(self.api_key, "[redacted]") if self.api_key else text

    def _backoff(self, attempt: int, retry_after: Optional[str], reason: str, last_start: float) -> bool:
        """Sleep before the next attempt; False, without sleeping, if it could only start after `last_start`."""
        delay = _retry_delay(attempt, retry_after)
        if self._clock() + delay > last_start:
            log.warning("%s; not retrying, the caller would give up first", reason)
            return False
        log.warning("%s; retrying in %.1fs", reason, delay)
        self._sleep(delay)
        return True


# --------------------------------------------------------------------------- HTTP server

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _error(status: int, message: str, code: str):
    return jsonify(_error_body(message, code)), status


def _caller_budget(read_timeout: Optional[str]) -> Optional[float]:
    """Seconds the caller will wait for its reply, from the OpenAI SDK's x-stainless-read-timeout header."""
    try:
        timeout = float(read_timeout or "")
    except ValueError:
        return None
    if not 0 < timeout < float("inf"):  # also rejects nan
        return None
    return max(timeout - CALLER_TIMEOUT_MARGIN, timeout / 2)


def create_app(upstream: Union[Upstream, OpenRouterUpstream]) -> Flask:
    app = Flask("grok-bridge")

    @app.before_request
    def only_local_programs():
        # Browsers always send Origin on cross-site requests; the OpenAI SDK
        # clients MiroFish uses never do. Rejecting it (and non-local Host
        # headers, against DNS rebinding) stops web pages from spending the
        # subscription through this port.
        if request.headers.get("Origin"):
            return _error(403, "Browser requests are not accepted by the Grok bridge", "forbidden")
        host = request.host.rsplit(":", 1)[0] if not request.host.endswith("]") else request.host
        if host.strip("[]").lower() not in LOCAL_HOSTS:
            return _error(403, "The Grok bridge only serves localhost", "forbidden")
        return None

    def call(fn: Callable[[], Tuple[int, Union[Audio, Dict[str, Any]]]]):
        try:
            status, data = fn()
        except AuthError as exc:
            return _error(401, str(exc), "grok_not_signed_in")
        except RefreshUnavailable as exc:
            return _error(503, str(exc), "grok_refresh_unavailable")
        if isinstance(data, Audio):
            return Response(data.content, status=status, content_type=data.content_type), status
        response = jsonify(data)
        error = data.get("error")
        if status == 429 and isinstance(error, dict) and error.get("code") == "bridge_throttled":
            # The OpenAI SDK waits this long before it retries, instead of coming straight back.
            response.headers["Retry-After"] = str(BRIDGE_RETRY_AFTER)
        return response, status

    @app.get("/health")
    def health():
        return jsonify({"status": "ok", **upstream.health_info()})

    @app.get("/v1/models")
    def models():
        return call(upstream.models)

    @app.post("/v1/chat/completions")
    def chat_completions():
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or not isinstance(body.get("messages"), list):
            return _error(400, "Expected a JSON Chat Completions request body", "invalid_request_error")
        if body.get("stream"):
            return _error(400, "Streaming is not supported by the Grok bridge", "invalid_request_error")
        started = time.time()
        if isinstance(upstream, OpenRouterUpstream):
            budget = _caller_budget(request.headers.get("x-stainless-read-timeout"))
            result = call(lambda: upstream.chat_completion(body, budget))
        else:
            result = call(lambda: upstream.chat_completion(body))
        data = result[0].get_json() or {}
        usage = data.get("usage") or {}
        served = data.get("model") if result[1] == 200 else None
        log.info(
            "%s -> HTTP %s in %.1fs via %s%s (%s tokens)",
            body.get("model"), result[1], time.time() - started, upstream.mode,
            f" as {served}" if served and served != body.get("model") else "", usage.get("total_tokens", "?"),
        )
        return result

    # ----- Imagine and voice passthrough ("Film the Chronicle"); Grok upstream only.

    imagine = bool(getattr(upstream, "imagine", False))

    def imagine_call(label: str, fn: Callable[[], Tuple[int, Union[Audio, Dict[str, Any]]]]):
        started = time.time()
        result = call(fn)
        if result[1] != 202:  # a rendering video is polled every few seconds; log only the outcome
            log.info("%s -> HTTP %s in %.1fs via imagine", label, result[1], time.time() - started)
        return result

    def imagine_post(label: str, forward: Callable[[Dict[str, Any]], Tuple[int, Union[Audio, Dict[str, Any]]]]):
        if not imagine:
            return _error(501, IMAGINE_UNAVAILABLE, "imagine_unavailable")
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return _error(400, "Expected a JSON object request body", "invalid_request_error")
        return imagine_call(f"{label} {body.get('model') or ''}".rstrip(), lambda: forward(body))

    @app.post("/v1/images/generations")
    def image_generations():
        return imagine_post("image", lambda body: upstream.generate_image(body))

    @app.post("/v1/videos/generations")
    def video_generations():
        return imagine_post("video", lambda body: upstream.generate_video(body))

    @app.get("/v1/videos/<request_id>")
    def video_status(request_id: str):
        if not imagine:
            return _error(501, IMAGINE_UNAVAILABLE, "imagine_unavailable")
        if not _valid_request_id(request_id):
            return _error(400, "Invalid video request_id", "invalid_request_error")
        return imagine_call(f"video poll {request_id}", lambda: upstream.video_status(request_id))

    @app.post("/v1/tts")
    def tts():
        return imagine_post("tts", lambda body: upstream.speech(body))

    return app


# --------------------------------------------------------------------------- CLI


def _http_client(timeout: float = UPSTREAM_TIMEOUT) -> httpx.Client:
    return httpx.Client(
        timeout=httpx.Timeout(timeout, connect=CONNECT_TIMEOUT),
        limits=httpx.Limits(
            max_connections=MAX_CONCURRENCY + IMAGINE_CONCURRENCY + 4,
            max_keepalive_connections=MAX_CONCURRENCY + IMAGINE_CONCURRENCY,
        ),
    )


def cmd_login(args: argparse.Namespace) -> int:
    with _http_client(30.0) as http:
        store = TokenStore(TOKEN_FILE, http)
        token_endpoint = discover_token_endpoint(http)
        response = http.post(DEVICE_CODE_URL, headers=FORM_HEADERS, data={"client_id": CLIENT_ID, "scope": SCOPE})
        device = _json_body(response)
        if response.status_code != 200 or "device_code" not in device:
            print(f"xAI refused to start sign-in: HTTP {response.status_code} {device.get('error', '')}")
            return 1

        url = device.get("verification_uri_complete") or device["verification_uri"]
        print("\nSign in to Grok for Parthenon:")
        print(f"  1. Open {url}")
        print(f"  2. Check the code matches: {device.get('user_code')}")
        print("  3. Sign in with the account that has your SuperGrok / X Premium+ subscription and approve.")
        print("Waiting for approval...\n")
        if not args.no_browser:
            webbrowser.open(url)

        interval = max(1, int(device.get("interval") or 5))
        deadline = time.time() + int(device.get("expires_in") or 600)
        while True:
            if time.time() > deadline:
                print("The sign-in code expired before it was approved. Run `npm run grok:login` again.")
                return 1
            time.sleep(interval)
            response = http.post(
                token_endpoint,
                headers=FORM_HEADERS,
                data={"grant_type": DEVICE_CODE_GRANT, "client_id": CLIENT_ID, "device_code": device["device_code"]},
            )
            tokens = _json_body(response)
            if response.status_code == 200 and tokens.get("access_token"):
                break
            error = tokens.get("error")
            if error == "authorization_pending":
                continue
            if error == "slow_down":
                interval += 5
                continue
            print(f"Sign-in failed: {error or f'HTTP {response.status_code}'} {tokens.get('error_description') or ''}")
            return 1

        if not tokens.get("refresh_token"):
            print("xAI did not return a refresh token, so the sign-in could not be kept. Try again.")
            return 1
        state = {
            "access_token": tokens["access_token"],
            "refresh_token": tokens["refresh_token"],
            "id_token": tokens.get("id_token"),
            "token_type": tokens.get("token_type", "Bearer"),
            "expires_in": tokens.get("expires_in"),
            "token_endpoint": token_endpoint,
            "obtained_at": int(time.time()),
        }
        with store.file_lock():
            store.save(state)
    print(f"Signed in to Grok as {_identity(state)}. Sign-in saved to {TOKEN_FILE}")
    return 0


def _openrouter_key() -> str:
    return (os.environ.get("OPENROUTER_API_KEY") or "").strip()


def _env_file_openrouter_key() -> str:
    """OPENROUTER_API_KEY as the .env file has it now (read only while the running bridge has none)."""
    try:
        return (dotenv_values(PROJECT_ROOT / ".env").get("OPENROUTER_API_KEY") or "").strip()
    except OSError:
        return ""


def cmd_status(_args: argparse.Namespace) -> int:
    print(f"Upstream:     {UPSTREAM} (PARTHENON_UPSTREAM)")
    if UPSTREAM == "openrouter":
        key_set = bool(_openrouter_key())
        print(f"API key:      {'set' if key_set else 'missing. ' + OPENROUTER_KEY_HINT}")
        print(f"Free models:  {', '.join(OPENROUTER_MODELS)}")
        print(f"Throttle:     {f'{OPENROUTER_RPM:g} requests/min' if OPENROUTER_RPM > 0 else 'off'}")
        return 0 if key_set else 1
    with _http_client(15.0) as http:
        state = TokenStore(TOKEN_FILE, http).load()
    if not state:
        print(f"Not signed in. {LOGIN_HINT}")
        return 1
    print(f"Signed in as: {_identity(state)}")
    print(f"Sign-in file: {TOKEN_FILE}")
    if state.get("revoked"):
        print(f"Status:       needs a new sign-in ({state['revoked']}). {LOGIN_HINT}")
        return 1
    exp = _jwt_claims(state.get("access_token")).get("exp")
    if isinstance(exp, (int, float)):
        minutes = (exp - time.time()) / 60
        if minutes > 0:
            print(f"Access token: valid for {minutes:.0f} more min (refreshes automatically)")
        else:
            print("Access token: expired (refreshes automatically on the next request)")
    return 0


def cmd_logout(_args: argparse.Namespace) -> int:
    with _http_client(15.0) as http:
        removed = TokenStore(TOKEN_FILE, http).delete()
    print("Signed out; the stored Grok sign-in was deleted." if removed else "Already signed out.")
    return 0


def cmd_probe(args: argparse.Namespace) -> int:
    kind = args.upstream or UPSTREAM
    if kind not in UPSTREAMS:
        print(f"PARTHENON_UPSTREAM must be one of {', '.join(UPSTREAMS)} (got {kind!r})")
        return 2
    with _http_client(120.0) as http:
        upstream: Union[Upstream, OpenRouterUpstream]
        if kind == "openrouter":
            model = args.model or FREE_MODEL_ALIAS
            upstream = OpenRouterUpstream(_openrouter_key(), http, max_retries=1)
            if not upstream.api_key:
                print(OPENROUTER_KEY_HINT)
                return 1
            max_tokens = 1024  # free reasoning models spend part of the budget thinking before they answer
        else:
            model = args.model or os.environ.get("LLM_MODEL_NAME") or "grok-4.3"
            upstream = Upstream(TokenStore(TOKEN_FILE, http), http, mode=args.mode, max_retries=1)
            max_tokens = 300

        def via(reply: Dict[str, Any]) -> str:
            return f"served by {reply.get('model')}" if kind == "openrouter" else f"via {upstream.mode}"

        try:
            status, data = upstream.models()
            if isinstance(upstream, OpenRouterUpstream) and status == 200:
                free_ids = {m.get("id") for m in data.get("data") or []}
                configured = ", ".join(
                    f"{m} ({'listed' if m in free_ids else 'NOT listed'})" for m in upstream.router.models
                )
                print(f"GET /models -> HTTP {status}: {len(free_ids)} free models; configured: {configured}")
            else:
                ids = sorted(m.get("id", "?") for m in data.get("data") or [])
                print(f"GET /models -> HTTP {status}: {', '.join(ids) or data.get('error') or data}")

            status, data = upstream.chat_completion({
                "model": model,
                "messages": [
                    {"role": "system", "content": "You reply with JSON only."},
                    {"role": "user", "content": 'Return exactly {"ping": "pong"}.'},
                ],
                "response_format": {"type": "json_object"},
                "temperature": 0,
                "max_tokens": max_tokens,
            })
            reply = (data.get("choices") or [{}])[0].get("message", {}).get("content") if status == 200 else data
            print(f"JSON chat ({model}) -> HTTP {status} {via(data)}: {reply}")

            status, data = upstream.chat_completion({
                "model": model,
                "messages": [{"role": "user", "content": "Like post 42 using the tool."}],
                "tools": [{
                    "type": "function",
                    "function": {
                        "name": "like_post",
                        "description": "Like a post by id.",
                        "parameters": {
                            "type": "object",
                            "properties": {"post_id": {"type": "integer"}},
                            "required": ["post_id"],
                        },
                    },
                }],
                "tool_choice": "auto",
                "max_tokens": max_tokens,
            })
            calls = (data.get("choices") or [{}])[0].get("message", {}).get("tool_calls") if status == 200 else data
            print(f"Tool call ({model}) -> HTTP {status} {via(data)}: {calls}")
        except (AuthError, RefreshUnavailable) as exc:
            print(exc)
            return 1
    return 0 if status == 200 else 1


def cmd_serve(_args: argparse.Namespace) -> int:
    http = _http_client()
    upstream: Union[Upstream, OpenRouterUpstream]
    if UPSTREAM == "openrouter":
        upstream = OpenRouterUpstream(_openrouter_key(), http, reload_key=_env_file_openrouter_key)
        if not upstream.api_key:
            log.warning("%s LLM requests will fail until it is set.", OPENROUTER_KEY_HINT)
        log.info(
            "Parthenon bridge on http://127.0.0.1:%s/v1 -> OpenRouter free models %s (%s, up to %s requests at once)",
            PORT, ", ".join(upstream.router.models),
            f"{OPENROUTER_RPM:g} requests/min" if OPENROUTER_RPM > 0 else "no throttle", MAX_CONCURRENCY,
        )
    else:
        store = TokenStore(TOKEN_FILE, http)
        upstream = Upstream(store, http)
        state = store.load()
        if not state:
            log.warning("Not signed in yet; LLM requests will fail until you run `npm run grok:login`.")
        else:
            log.info("Using the Grok subscription sign-in for %s", _identity(state))
        log.info(
            "Grok bridge on http://127.0.0.1:%s/v1 (mode=%s, up to %s requests at once, "
            "plus %s image/video/voice requests)",
            PORT, upstream.mode, MAX_CONCURRENCY, IMAGINE_CONCURRENCY,
        )
    create_app(upstream).run(host="127.0.0.1", port=PORT, threaded=True)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    sys.stdout.reconfigure(line_buffering=True)
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    parser =argparse.ArgumentParser(description="Grok subscription bridge for Parthenon")
    commands = parser.add_subparsers(dest="command", required=True)
    login = commands.add_parser("login", help="sign in with your Grok subscription")
    login.add_argument("--no-browser", action="store_true", help="print the sign-in link instead of opening it")
    commands.add_parser("serve", help="run the local OpenAI-compatible endpoint (upstream from PARTHENON_UPSTREAM)")
    commands.add_parser("status", help="show the configured upstream and sign-in state")
    commands.add_parser("logout", help="delete the stored sign-in")
    probe = commands.add_parser("probe", help="check what the upstream accepts (JSON reply and a tool call)")
    probe.add_argument("--upstream", choices=UPSTREAMS, help="upstream to test (defaults to PARTHENON_UPSTREAM)")
    probe.add_argument("--model", help="model to test (defaults to LLM_MODEL_NAME for grok, parthenon-free for openrouter)")
    probe.add_argument("--mode", default="auto", choices=["auto", "chat", "responses"], help="grok only")
    args = parser.parse_args(argv)
    if args.command in ("serve", "status") and UPSTREAM not in UPSTREAMS:
        print(f"PARTHENON_UPSTREAM must be one of {', '.join(UPSTREAMS)} (got {UPSTREAM!r})")
        return 2
    handlers = {"login": cmd_login, "serve": cmd_serve, "status": cmd_status, "logout": cmd_logout, "probe": cmd_probe}
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
