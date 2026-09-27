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
With PARTHENON_PUBLIC=1 the default list leaves out OpenRouter's free-model
router and the app is attributed to projectforty2.ai/parthenon
(OPENROUTER_APP_URL overrides the attribution).

With PARTHENON_UPSTREAM=xai, openai or anthropic it forwards to that provider's
OpenAI-compatible endpoint with a pay-per-token API key (XAI_API_KEY,
OPENAI_API_KEY, ANTHROPIC_API_KEY). Whatever model the caller names is replaced
by the provider's configured one (XAI_MODEL, OPENAI_MODEL, ANTHROPIC_MODEL), and
a parameter the provider refuses for that model is dropped and remembered.
PARTHENON_UPSTREAM=auto picks the first of those keys that is set, else
OpenRouter. An xAI key also serves Imagine and voice; OpenAI and Anthropic 501.
PARTHENON_PROVIDER_RPM optionally paces the keyed providers.

PARTHENON_UPSTREAM=auto puts the Grok subscription first: while
GROK_BRIDGE_TOKEN_FILE holds a usable sign-in every request goes there (with
Imagine and voice), else to the first keyed provider, else OpenRouter. It is
decided again on every request from the token file, so running `login` beside a
running bridge switches it to the subscription and `logout` (or a revoked grant)
falls back, with no restart. A server signs in with its own grant (`login` on the
server, GROK_BRIDGE_TOKEN_FILE pointing at its disk), never a copy of another
machine's file. In that mode a model name that is not a Grok model (the public
default parthenon-free) is sent as GROK_MODEL (default grok-4.7).
xAI refuses a token it will not take with 401 or with 400 "Incorrect API key"; in
auto (and on the public server) both get one refresh and a retry. A grant xAI
will not refresh is marked revoked; a token refused even after a refresh (or
one that cannot be refreshed right now) rests for GROK_BRIDGE_REJECTED_RETRY_SECONDS
(default 300) and is tried again after it. Either way that request, and those
after it, are answered by the fallback.

Every upstream gives up on a reply the caller will no longer read: the OpenAI SDK
says how long it waits (x-stainless-read-timeout), and each upstream attempt's
timeout and every retry fit inside that budget.
"""

from __future__ import annotations

import argparse
import base64
import fcntl
import hashlib
import json
import logging
import math
import os
import random
import re
import stat
import sys
import tempfile
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
REFRESH_TIMEOUT = 30.0  # longest a token refresh (or the discovery it needs) may take
REVOKED_GRANT_ERRORS = {"invalid_grant", "invalid_token", "invalid_client", "unauthorized_client"}
# xAI does not always answer a token it refuses with 401: it says 400 "Incorrect API key provided..." (the
# same words it gives a wrong API key). A 400 or 403 whose error names the key or token as bad is taken as
# that refusal. Words about permission (a model the subscription may not use, "not allowed for this token")
# are not: they say nothing about the sign-in, and a 403 there is what switches to the Responses API.
TOKEN_REJECTED_TEXT = re.compile(
    r"incorrect api key|invalid[ _-]?api[ _-]?key|no api key|api key (?:is |was |has been )?"
    r"(?:invalid|incorrect|revoked|expired|disabled)|invalid_token|invalid (?:access |bearer |oauth )token"
    r"|(?:access|bearer|oauth) token (?:is |was |has )?(?:invalid|expired|revoked)|token (?:has )?expired"
    r"|unauthenticated|valid authentication credentials",
    re.IGNORECASE,
)
# After xAI refuses even a freshly refreshed token, auto serves the fallback for this long before it tries the
# sign-in again (at once after a new `login`). A rest, not a sign-out: a passing fault at xAI heals by itself.
REJECTED_RETRY_SECONDS = max(1.0, float(os.environ.get("GROK_BRIDGE_REJECTED_RETRY_SECONDS") or "300"))

TOKEN_FILE = Path(
    os.environ.get("GROK_BRIDGE_TOKEN_FILE", "~/.config/parthenon/grok-oauth.json")
).expanduser()
HOST = (os.environ.get("GROK_BRIDGE_HOST") or "127.0.0.1").strip()
PORT = int(os.environ.get("GROK_BRIDGE_PORT") or "5055")
MAX_CONCURRENCY = int(os.environ.get("GROK_BRIDGE_MAX_CONCURRENCY", "6"))
MAX_RETRIES = int(os.environ.get("GROK_BRIDGE_MAX_RETRIES", "5"))
MODE = os.environ.get("GROK_BRIDGE_MODE", "auto")  # auto | chat | responses
# Image/video/voice calls take their own slots: a 17 s image render must never hold a chat slot.
IMAGINE_CONCURRENCY = max(1, int(os.environ.get("GROK_BRIDGE_IMAGINE_CONCURRENCY", "3")))
IMAGINE_UNAVAILABLE = "Filming needs the Grok subscription upstream (set PARTHENON_UPSTREAM=grok)."
# xAI video request ids go into the poll URL, so only plain id characters are let through.
VIDEO_REQUEST_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")

LOCAL_LOGIN_HINT = "Run `npm run grok:login` in the parthenon folder to sign in with your Grok subscription."
# On the server the owner signs in over `render ssh` as the service user (docs/DEPLOY.md).
SERVER_LOGIN_HINT = (
    "Sign the server in with `python bridge/grok_bridge.py login` run as the service user, "
    "with GROK_BRIDGE_TOKEN_FILE set to the file on its disk (see docs/DEPLOY.md)."
)

# Which service `serve` forwards to: the Grok subscription, OpenRouter's free models, a provider
# with a pay-per-token API key, or (auto) the Grok subscription while the server is signed in,
# else the first provider whose key is set, else OpenRouter.
UPSTREAMS = ("grok", "openrouter", "xai", "openai", "anthropic", "auto")
UPSTREAM = (os.environ.get("PARTHENON_UPSTREAM") or "grok").strip().lower()
# In auto mode on the subscription, a request naming a model that is not Grok's (parthenon-free,
# gpt-4o-mini...) is sent as this one. The grok upstream on its own passes the model through unchanged.
GROK_MODEL = (os.environ.get("GROK_MODEL") or "").strip() or "grok-4.7"

TRUE_WORDS = frozenset({"1", "true", "yes", "on"})  # as the backend reads PARTHENON_PUBLIC


def _public(environ: Any) -> bool:
    """Whether PARTHENON_PUBLIC turns on the public site (projectforty2.ai/parthenon)."""
    return str(environ.get("PARTHENON_PUBLIC") or "").strip().lower() in TRUE_WORDS


PUBLIC = _public(os.environ)
LOGIN_HINT = SERVER_LOGIN_HINT if PUBLIC else LOCAL_LOGIN_HINT

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
LOCAL_SITE_URL = "http://localhost:3000"
PUBLIC_SITE_URL = "https://projectforty2.ai/parthenon"


def _openrouter_app_headers(environ: Any) -> Dict[str, str]:
    """OpenRouter's app attribution: OPENROUTER_APP_URL if it is an http(s) URL, else the site this runs as."""
    url = str(environ.get("OPENROUTER_APP_URL") or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc or any(c.isspace() or ord(c) < 32 for c in url):
        url = PUBLIC_SITE_URL if _public(environ) else LOCAL_SITE_URL
    return {"X-Title": "Parthenon", "HTTP-Referer": url}


OPENROUTER_APP_HEADERS = _openrouter_app_headers(os.environ)
# The last entry is OpenRouter's free-model router, which picks any free model (a safety classifier, a
# 2.6B model, a code model...) under that model's own id. It stays a last resort locally; the public
# site leaves it out so only these instruction models write the city (_model_list).
DEFAULT_OPENROUTER_MODELS = (
    "nvidia/nemotron-3-super-120b-a12b:free,google/gemma-4-31b-it:free,qwen/qwen3.8-27b:free,openrouter/free"
)
ROUTER_PREFIX = "openrouter/"  # openrouter/free, openrouter/auto...: an entry that picks a model per request
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


def _is_router(entry: str) -> bool:
    return entry.startswith(ROUTER_PREFIX)


def _model_list(raw: Optional[str], public: bool = False) -> List[str]:
    """OPENROUTER_MODELS as an ordered list, falling back to the defaults when unset or blank.

    The public site's defaults leave out router entries; a list the owner sets is taken as it is.
    """
    models = [m.strip() for m in (raw or "").split(",") if m.strip()]
    if models:
        return models
    defaults = [m.strip() for m in DEFAULT_OPENROUTER_MODELS.split(",") if m.strip()]
    return [m for m in defaults if not _is_router(m)] if public else defaults


OPENROUTER_MODELS = _model_list(os.environ.get("OPENROUTER_MODELS"), PUBLIC)


class Provider(NamedTuple):
    """A provider served with a pay-per-token API key through its OpenAI-compatible endpoint."""

    kind: str  # the PARTHENON_UPSTREAM value
    label: str  # what /health calls it for the backend's status route
    name: str  # for people, in messages
    base_url: str
    key_env: str
    model_env: str
    default_model: str
    imagine: bool  # the same key also serves Grok Imagine and voice


PROVIDERS: Dict[str, Provider] = {
    "xai": Provider(
        "xai", "grok", "xAI", "https://api.x.ai/v1", "XAI_API_KEY", "XAI_MODEL",
        "grok-4.20-0309-non-reasoning", True,
    ),
    "openai": Provider(
        "openai", "openai", "OpenAI", "https://api.openai.com/v1", "OPENAI_API_KEY", "OPENAI_MODEL",
        "gpt-4.1-mini", False,
    ),
    # Anthropic's OpenAI SDK compatibility endpoint (https://api.anthropic.com/v1/chat/completions).
    "anthropic": Provider(
        "anthropic", "claude", "Anthropic", "https://api.anthropic.com/v1", "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL",
        "claude-sonnet-5", False,
    ),
}
AUTO_ORDER = ("xai", "openai", "anthropic")  # PARTHENON_UPSTREAM=auto takes the first whose key is set
# The provider label /health reports, for every upstream the bridge can serve.
PROVIDER_LABELS = {"grok": "grok-subscription", "openrouter": "free", **{k: p.label for k, p in PROVIDERS.items()}}

PROVIDER_RPM = float(os.environ.get("PARTHENON_PROVIDER_RPM") or "0")  # keyed providers: 0 leaves them unpaced
PROVIDER_BURST = 4
# Anthropic needs a token cap; OASIS sends none. Thinking, where the model uses it, counts against it.
ANTHROPIC_MAX_TOKENS = int(os.environ.get("ANTHROPIC_MAX_TOKENS") or "8192")
# OpenAI reasoning families take max_completion_tokens and only the default temperature.
OPENAI_REASONING_MODEL = re.compile(r"(o\d|gpt-[5-9])", re.IGNORECASE)
MAX_ADAPTATIONS = 4  # parameters one request may drop after a provider refuses them
# Request parameters a provider may refuse for a model; the bridge drops them (max_tokens it renames) and asks again.
ADAPTABLE_PARAMS = {
    "max_tokens", "temperature", "top_p", "presence_penalty", "frequency_penalty", "logprobs", "top_logprobs",
    "logit_bias", "seed", "stop", "n", "user", "parallel_tool_calls", "reasoning_effort", "response_format",
    "service_tier", "store", "metadata",
}
UNSUPPORTED_CODES = {"unsupported_parameter", "unsupported_value", "unknown_parameter", "invalid_parameter"}
UNSUPPORTED_PHRASES = (
    "not support", "unsupported", "unknown parameter", "unrecognized", "not allowed", "not permitted",
    "extra inputs", "only the default",
)
JSON_INSTRUCTION = (
    "Reply with one valid JSON object and nothing else: no text before or after it and no Markdown code fences."
)
KEYED_IMAGINE_UNAVAILABLE = (
    "Portraits, films and voices need Grok Imagine: set XAI_API_KEY (PARTHENON_UPSTREAM=xai or auto) "
    "or use the Grok subscription (PARTHENON_UPSTREAM=grok)."
)
AUTO_IMAGINE_UNAVAILABLE = (
    "Portraits, films and voices need Grok Imagine, and this bridge has no Grok sign-in: sign it in to the "
    "Grok subscription (`grok_bridge.py login` with the same GROK_BRIDGE_TOKEN_FILE) or set XAI_API_KEY."
)


def _env_key(name: str, environ: Optional[Any] = None) -> str:
    return ((os.environ if environ is None else environ).get(name) or "").strip()


def resolve_fallback(environ: Optional[Any] = None) -> str:
    """What auto serves without a Grok sign-in: the first provider whose key is set, else openrouter."""
    for name in AUTO_ORDER:
        if _env_key(PROVIDERS[name].key_env, environ):
            return name
    return "openrouter"


def resolve_upstream(kind: str, environ: Optional[Any] = None, *, token_file: Optional[Path] = None) -> str:
    """The upstream `serve` runs now: `kind` itself; for auto, grok while `token_file` holds a usable
    sign-in, else resolve_fallback. The token file is only looked at when it is passed."""
    kind = (kind or "grok").strip().lower()
    if kind != "auto":
        return kind
    if token_file is not None and usable_sign_in(token_file) is not None:
        return "grok"
    return resolve_fallback(environ)


def provider_model(provider: Provider, environ: Optional[Any] = None) -> str:
    """The model every request to `provider` uses (XAI_MODEL, OPENAI_MODEL, ANTHROPIC_MODEL, else the default)."""
    return _env_key(provider.model_env, environ) or provider.default_model


log = logging.getLogger("grok-bridge")


class AuthError(Exception):
    """No usable sign-in: never signed in, signed out, or the grant was revoked."""


class SignInRejected(AuthError):
    """xAI refused the sign-in's access token and a refresh gave none it accepts (or was refused, or could not
    be made).

    `fingerprint` names the refused token by a hash, never the token itself, so auto can rest exactly that
    sign-in and take a new one at once."""

    def __init__(self, message: str, fingerprint: str):
        super().__init__(message)
        self.fingerprint = fingerprint


def _fingerprint(token: Any) -> str:
    return hashlib.sha256(str(token or "").encode()).hexdigest()[:16]


def _token_rejected(response: httpx.Response) -> bool:
    """Whether xAI refused the bearer token itself: a 401, or a 400/403 whose error names the key or token."""
    if response.status_code == 401:
        return True
    if response.status_code not in (400, 403):
        return False
    data = _json_body(response)
    error = data.get("error")
    words = [data.get("code"), data.get("message")]
    words += [error.get(k) for k in ("message", "code", "type")] if isinstance(error, dict) else [error]
    return bool(TOKEN_REJECTED_TEXT.search(" ".join(str(w) for w in words if w)))


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
    response = http.get(DISCOVERY_URL, headers={"Accept": "application/json"}, timeout=REFRESH_TIMEOUT)
    response.raise_for_status()
    return _require_xai_url(str(response.json().get("token_endpoint", "")), "token_endpoint")


# --------------------------------------------------------------------------- tokens


def _file_signature(info: os.stat_result) -> Tuple[int, ...]:
    """What changes whenever the token file is replaced (a new inode on every save), rewritten, or
    re-owned (chmod/chown move ctime), even within one mtime tick."""
    return (
        info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns,
        info.st_mode, info.st_uid, info.st_gid,
    )


def _give_to_folder_owner(path: Path) -> None:
    """When root writes the sign-in (a `login` over `render ssh` as root), hand the file to the owner of its
    folder, the service user the bridge runs as: a root-owned 0600 file is one the bridge cannot read."""
    if not hasattr(os, "geteuid") or os.geteuid() != 0:
        return
    try:
        folder = path.parent.stat()
        if folder.st_uid != 0:
            os.chown(path, folder.st_uid, folder.st_gid)
    except OSError as exc:
        log.warning("Could not give %s to the owner of its folder: %s", path, exc)


class TokenStore:
    """Reads, refreshes and persists the subscription tokens.

    Refresh tokens are single-use, so refreshes are serialised with a thread
    lock plus an flock on a sibling lock file, and the file is re-read under
    the lock in case another process (e.g. a re-login) already updated it.

    The file is read again whenever it changes (replaced, rewritten, re-owned)
    and looked for on every call while it is missing, so a sign-in written by
    `login` in another process is used without a restart. A file that cannot be
    read or parsed counts as no sign-in (`problem` says why) and is tried again.
    Only this store's own file (and its .lock and temporary siblings) is ever
    written: a refresh rotates this grant's refresh token and no other.
    """

    def __init__(self, path: Path, http: httpx.Client):
        self.path = path
        self.http = http
        self._lock = threading.Lock()  # serialises refreshes
        self._load_lock = threading.Lock()  # guards the cached state below
        self._state: Optional[Dict[str, Any]] = None
        self._signature: Optional[Tuple[int, ...]] = None
        self._warned: Optional[Tuple[Any, ...]] = None
        self.problem: Optional[str] = None  # why an existing file could not be used, for status and logs

    def load(self) -> Optional[Dict[str, Any]]:
        with self._load_lock:
            try:
                info = self.path.stat()
            except FileNotFoundError:
                self._state, self._signature, self.problem = None, None, None
                return None
            except OSError as exc:  # e.g. a folder this user may not search
                return self._unusable(None, f"cannot be read ({exc.strerror or exc})")
            signature = _file_signature(info)
            if signature == self._signature:
                return self._state
            try:
                state = json.loads(self.path.read_text())
            except FileNotFoundError:  # removed between stat and read
                self._state, self._signature, self.problem = None, None, None
                return None
            except OSError as exc:
                return self._unusable(signature, f"cannot be read ({exc.strerror or exc})")
            except ValueError:
                return self._unusable(signature, "is not valid JSON")
            if not isinstance(state, dict):
                return self._unusable(signature, "does not hold a sign-in")
            self._state, self._signature, self.problem = state, signature, None
            return state

    def _unusable(self, signature: Optional[Tuple[int, ...]], problem: str) -> None:
        """No sign-in for now; nothing is cached, so the file is tried again on the next call."""
        self._state, self._signature, self.problem = None, None, problem
        if self._warned != (signature, problem):
            self._warned = (signature, problem)
            log.warning("The Grok sign-in file %s %s; treating it as no sign-in", self.path, problem)
        return None

    def usable_state(self) -> Optional[Dict[str, Any]]:
        """The stored sign-in if it can be used, else None: it has an access token, was not revoked, and has
        a refresh token or an access token that has not expired yet."""
        state = self.load()
        if not state or not state.get("access_token") or state.get("revoked"):
            return None
        if not state.get("refresh_token"):
            exp = _jwt_claims(state["access_token"]).get("exp")
            if isinstance(exp, (int, float)) and exp <= time.time():
                return None
        return state

    def save(self, state: Dict[str, Any]) -> None:
        """Write the sign-in atomically, mode 0600 (a fresh temporary file, then a rename over the old one)."""
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent)
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "w") as handle:
                os.fchmod(handle.fileno(), 0o600)
                json.dump(state, handle, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            _give_to_folder_owner(tmp)
            os.replace(tmp, self.path)
        except BaseException:
            try:
                tmp.unlink()
            except FileNotFoundError:
                pass
            raise
        with self._load_lock:
            self._state, self._signature, self.problem = state, _file_signature(self.path.stat()), None

    def delete(self) -> bool:
        with self.file_lock():
            try:
                self.path.unlink()
            except FileNotFoundError:
                return False
        with self._load_lock:
            self._state, self._signature, self.problem = None, None, None
        return True

    @contextmanager
    def file_lock(self):
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        lock_path = self.path.with_name(self.path.name + ".lock")
        fd: Optional[int] = None
        try:
            fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        except PermissionError:
            try:  # made by another user (a root sign-in): flock works on a read-only descriptor too
                fd = os.open(lock_path, os.O_RDONLY)
            except OSError as exc:
                log.warning("Cannot open the sign-in lock %s (%s); going on without it", lock_path, exc)
        else:
            _give_to_folder_owner(lock_path)
        try:
            if fd is not None:
                fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            if fd is not None:
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)

    def access_token(self, *, rejected: Optional[str] = None) -> str:
        """A usable access token; refreshes near expiry or when `rejected` just got a 401."""
        with self._lock:
            token = self._current_state()["access_token"]
            if not self._needs_refresh(token, rejected):
                return token
            with self.file_lock():
                state = self._current_state()  # another process may have refreshed or signed in again
                if not self._needs_refresh(state["access_token"], rejected):
                    return state["access_token"]
                return self._refresh(state)["access_token"]

    def _current_state(self) -> Dict[str, Any]:
        state = self.load()
        if not state or not state.get("access_token"):
            problem = f" (the sign-in file {self.problem})" if self.problem else ""
            raise AuthError(f"Not signed in to Grok{problem}. {LOGIN_HINT}")
        if state.get("revoked"):
            raise AuthError(f"Grok sign-in stopped working ({state['revoked']}). {LOGIN_HINT}")
        return state

    def _current_token(self) -> str:
        return self._current_state()["access_token"]

    @staticmethod
    def _needs_refresh(token: str, rejected: Optional[str]) -> bool:
        if rejected is not None and token == rejected:
            return True
        exp = _jwt_claims(token).get("exp")
        return isinstance(exp, (int, float)) and exp - time.time() < REFRESH_SKEW_SECONDS

    def _refresh(self, state: Dict[str, Any]) -> Dict[str, Any]:
        if not state.get("refresh_token"):
            raise AuthError(f"The Grok sign-in has no refresh token. {LOGIN_HINT}")
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
                timeout=REFRESH_TIMEOUT,
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
        error = error if isinstance(error, str) else ""  # a proxy's HTML page or a nested error names no grant error
        if response.status_code in (400, 401) and error in REVOKED_GRANT_ERRORS:
            # Remember it so every queued request doesn't retry a dead refresh token.
            self.save({**state, "revoked": error})
            raise AuthError(f"Grok sign-in expired or was revoked ({error}). {LOGIN_HINT}")
        raise RefreshUnavailable(f"xAI token refresh failed: HTTP {response.status_code} {error or ''}".strip())


def usable_sign_in(path: Path) -> Optional[Dict[str, Any]]:
    """The sign-in stored in `path` if it can be used (see TokenStore.usable_state), with no network call."""
    return TokenStore(path, None).usable_state()  # type: ignore[arg-type]  # no refresh, so no client


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


class ImaginePassthrough:
    """xAI's Imagine (image/video) and text-to-speech routes, passed through unchanged.

    They run on their own semaphore (`_imagine_slots`) so long renders cannot starve chat.
    A subclass supplies `_send`, which returns xAI's final reply after its retries or the
    bridge's own (status, error body) when xAI could not be reached.
    """

    _imagine_slots: threading.BoundedSemaphore

    def _send(
        self, method: str, path: str, payload: Optional[Dict[str, Any]] = None, *, accept: str = "application/json",
    ) -> Union[httpx.Response, Tuple[int, Dict[str, Any]]]:
        raise NotImplementedError

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


class Upstream(ImaginePassthrough):
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
        clock: Callable[[], float] = time.monotonic,
        follow_budget: bool = False,
        detect_rejection: bool = False,
    ):
        if mode not in ("auto", "chat", "responses"):
            raise ValueError(f"GROK_BRIDGE_MODE must be auto, chat or responses (got {mode!r})")
        self.store = store
        self.http = http
        self.mode = mode
        self.max_retries = max_retries
        self.imagine_concurrency = imagine_concurrency
        self.max_concurrency = max_concurrency
        self._slots = threading.BoundedSemaphore(max_concurrency)
        self._imagine_slots = threading.BoundedSemaphore(imagine_concurrency)
        self._sleep = sleep
        self._clock = clock
        # Bound each attempt and retry by the caller's budget too: on for auto and the public server; the
        # local grok bridge keeps the client's own timeout and the full retries, as it always had.
        self.follow_budget = follow_budget
        # Also on for auto and the public server: xAI's 400/403 "Incorrect API key" counts as a 401 (one refresh
        # and a retry), and a token refused again raises SignInRejected so auto answers from its fallback. The
        # local grok bridge refreshes on 401 only and passes every other reply through, as it always did.
        self.detect_rejection = detect_rejection

    def chat_completion(self, body: Dict[str, Any], budget: Optional[float] = None) -> Tuple[int, Dict[str, Any]]:
        """Forward one chat. A caller that says how long it will wait (`budget`, seconds) gets a slot only
        while its reply could still reach it: Werkzeug keeps a handler running after the caller hangs up,
        so a call started later would spend the subscription on an answer nobody reads. With follow_budget,
        each attempt's timeout and every retry then fit inside that budget too, so an abandoned call frees
        its slot. Without a budget, nothing changes: the client's own timeout and the full retries."""
        deadline: Optional[float] = None
        if budget is None:
            self._slots.acquire()
        else:
            arrived = self._clock()
            deadline = arrived + budget
            wait = max(0.0, budget - min(MIN_ATTEMPT_SECONDS, budget / 2))
            if not self._slots.acquire(timeout=wait):
                return 429, _error_body(
                    f"All {self.max_concurrency} of the bridge's chat slots stayed busy for more than "
                    f"{wait:.0f}s. Retry shortly.",
                    "bridge_throttled",
                )
        try:
            return self._chat_in_slot(body, deadline if self.follow_budget else None)
        finally:
            self._slots.release()

    def _chat_in_slot(self, body: Dict[str, Any], deadline: Optional[float] = None) -> Tuple[int, Dict[str, Any]]:
        if self.mode != "responses":
            status, data = self._request("POST", "/chat/completions", body, deadline=deadline)
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
        status, data = self._request("POST", "/responses", chat_to_responses(body), deadline=deadline)
        if status != 200:
            return status, data
        return 200, responses_to_chat(data, body)

    def models(self) -> Tuple[int, Dict[str, Any]]:
        return self._request("GET", "/models")

    def _request(
        self, method: str, path: str, payload: Optional[Dict[str, Any]] = None, *, deadline: Optional[float] = None,
    ) -> Tuple[int, Dict[str, Any]]:
        response = self._send(method, path, payload, deadline=deadline)
        if isinstance(response, tuple):
            return response
        return response.status_code, _json_body(response)

    def _send(
        self, method: str, path: str, payload: Optional[Dict[str, Any]] = None, *, accept: str = "application/json",
        deadline: Optional[float] = None,
    ) -> Union[httpx.Response, Tuple[int, Dict[str, Any]]]:
        """xAI's final reply after the 401 refresh and 429/5xx backoff, or the bridge's own error if unreachable.

        With a `deadline` (the caller's budget on this bridge's clock) each attempt times out when the caller
        would stop reading, and a retry that could only start after it is not made. With `detect_rejection`
        a 400/403 that refuses the token is refreshed like a 401, and a refused refreshed token (or a refresh
        that is refused or cannot be made) raises SignInRejected instead of reaching the caller.
        """
        token = self.store.access_token()
        refreshed_after_401 = False
        attempt = 0
        last_start = None if deadline is None else deadline - MIN_ATTEMPT_SECONDS  # no retry with less left
        while True:
            options: Dict[str, Any] = {}
            timeout = None
            if deadline is not None:
                timeout = max(1.0, min(UPSTREAM_TIMEOUT, deadline - self._clock()))
                options["timeout"] = httpx.Timeout(timeout, connect=min(CONNECT_TIMEOUT, timeout))
            try:
                response = self.http.request(
                    method,
                    UPSTREAM_BASE_URL + path,
                    json=payload,
                    headers={"Authorization": f"Bearer {token}", "Accept": accept},
                    **options,
                )
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                # The request never reached xAI, so sending it again cannot run it twice.
                if attempt >= self.max_retries or not self._backoff(attempt, None, last_start):
                    return 502, _error_body(f"Could not reach xAI: {exc}", "upstream_unreachable")
                attempt += 1
                continue
            except httpx.TimeoutException:
                # xAI may still be working on it: no automatic retry of a POST it may already have run.
                when = "in time" if timeout is None else f"within {timeout:.0f}s"
                return 504, _error_body(f"xAI did not answer {when}.", "upstream_timeout")
            except httpx.TransportError as exc:
                return 502, _error_body(f"Lost the connection to xAI: {exc}", "upstream_unreachable")
            if not self.detect_rejection:
                if response.status_code == 401 and not refreshed_after_401:
                    token = self.store.access_token(rejected=token)
                    refreshed_after_401 = True
                    continue
            elif _token_rejected(response):
                if refreshed_after_401:
                    raise SignInRejected(
                        f"xAI refused the Grok sign-in even after a refresh (HTTP {response.status_code}). "
                        f"{LOGIN_HINT}",
                        _fingerprint(token),
                    )
                log.warning("xAI refused the Grok access token (HTTP %s); refreshing it once", response.status_code)
                try:
                    token = self.store.access_token(rejected=token)
                except AuthError as exc:  # a refresh xAI refused (now marked revoked), or none to make
                    raise SignInRejected(str(exc), _fingerprint(token)) from exc
                except RefreshUnavailable as exc:  # the token is known bad and cannot be renewed right now
                    log.warning("Could not refresh the refused Grok token: %s", exc)
                    raise SignInRejected(
                        f"xAI refused the Grok access token (HTTP {response.status_code}) and it could not be "
                        f"refreshed ({exc}). {LOGIN_HINT}",
                        _fingerprint(token),
                    ) from exc
                refreshed_after_401 = True
                continue
            if (response.status_code == 429 or response.status_code >= 500) and attempt < self.max_retries:
                if self._backoff(attempt, response.headers.get("retry-after"), last_start):
                    attempt += 1
                    continue
            return response

    def _backoff(self, attempt: int, retry_after: Optional[str], last_start: Optional[float] = None) -> bool:
        """Sleep before the next attempt; False, without sleeping, if it could only start after `last_start`."""
        delay = _retry_delay(attempt, retry_after)
        if last_start is not None and self._clock() + delay > last_start:
            log.warning("xAI is busy or unavailable; not retrying, the caller would give up first")
            return False
        log.warning("xAI is busy or unavailable; retrying in %.1fs", delay)
        self._sleep(delay)
        return True

    def health_info(self) -> Dict[str, Any]:
        state = self.store.load() or {}
        signed_in = bool(state.get("access_token")) and not state.get("revoked")
        return {
            "upstream": "grok", "signed_in": signed_in, "mode": self.mode, "imagine": True,
            "provider": PROVIDER_LABELS["grok"], "voice": True,
        }


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
        """Remember which of the `tried` entries produced a reply OpenRouter labels `reported`.

        Only a named model is remembered. A router entry (openrouter/free) answers with whichever
        model it picked, so starting later requests there would hand them to a new random model
        each time; its replies leave the next request's order as it was.
        """
        entry = _matching_entry(reported, tried)
        if entry is None or _is_router(entry):
            return
        with self._lock:
            self._healthy = entry
            self._healthy_until = self._clock() + self._healthy_seconds

    def failed(self, model: str) -> None:
        with self._lock:
            if self._healthy == model:
                self._healthy = None


def _matching_entry(reported: Any, tried: List[str]) -> Optional[str]:
    """The `tried` entry a reply labelled `reported` came from; None when a router entry picked another model."""
    if isinstance(reported, str):
        if reported in tried:
            return reported
        base = reported.split(":")[0]  # OpenRouter may drop the ":free" variant suffix
        for entry in tried:
            if entry.split(":")[0] == base:
                return entry
    # A router entry such as openrouter/free replies under the id of whichever model it picked.
    if any(_is_router(entry) for entry in tried):
        return None
    return tried[0]


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
        app_headers: Optional[Dict[str, str]] = None,
    ):
        self.api_key = (api_key or "").strip()
        self.http = http
        self.router = ModelRouter(models or OPENROUTER_MODELS, clock=clock)
        self.app_headers = dict(OPENROUTER_APP_HEADERS if app_headers is None else app_headers)
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
            "provider": PROVIDER_LABELS["openrouter"],
            "voice": False,
        }

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Accept": "application/json", **self.app_headers}

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


# --------------------------------------------------------------------------- keyed providers


def _snake_case(word: str) -> str:
    return re.sub(r"(?<=[a-z0-9])([A-Z])", r"_\1", word).lower()


def _refused_param(status: int, data: Dict[str, Any], sent: Dict[str, Any]) -> Optional[str]:
    """The request parameter a provider's 400/422 says it does not support for this model, if the bridge can drop it.

    Only a parameter that was actually sent counts, so the same refusal can never loop.
    """
    if status not in (400, 422):
        return None
    error = data.get("error")
    if isinstance(error, str):  # xAI's shape: {"code": "Client specified an invalid argument", "error": "..."}
        error = {"message": error, "code": data.get("code")}
    if not isinstance(error, dict):
        return None
    message = str(error.get("message") or "")
    code = str(error.get("code") or "").lower()
    if code not in UNSUPPORTED_CODES and not any(phrase in message.lower() for phrase in UNSUPPORTED_PHRASES):
        return None
    candidates = [str(error.get("param") or "")] + re.findall(r"[A-Za-z_]+", message)
    for candidate in candidates:
        name = _snake_case(candidate.split(".")[0].split("[")[0].strip())
        if name in ADAPTABLE_PARAMS and name in sent:
            return name
    return None


def _json_requested(body: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    response_format = body.get("response_format")
    if isinstance(response_format, dict) and response_format.get("type") in ("json_object", "json_schema"):
        return response_format
    return None


def _json_instruction(response_format: Dict[str, Any]) -> str:
    schema = None
    if response_format.get("type") == "json_schema":
        schema = (response_format.get("json_schema") or {}).get("schema")
    if isinstance(schema, dict) and schema:
        return f"{JSON_INSTRUCTION} It must follow this JSON schema: {json.dumps(schema, ensure_ascii=False)}"
    return JSON_INSTRUCTION


def _with_system_note(messages: List[Any], note: str) -> List[Any]:
    """`messages` with a system message added after the leading system/developer ones."""
    index = 0
    while index < len(messages) and isinstance(messages[index], dict) and messages[index].get("role") in (
        "system", "developer",
    ):
        index += 1
    return [*messages[:index], {"role": "system", "content": note}, *messages[index:]]


def _empty_tool_call_text(message: Any) -> bool:
    return (
        isinstance(message, dict) and message.get("role") == "assistant"
        and bool(message.get("tool_calls")) and message.get("content") == ""
    )


FENCED_JSON = re.compile(r"^\s*```(?:json)?[ \t]*\n?(.*?)\n?```\s*$", re.IGNORECASE | re.DOTALL)


def _unfenced(content: Any) -> Any:
    if isinstance(content, str):
        match = FENCED_JSON.match(content)
        if match:
            return match.group(1).strip()
    return content


class KeyedUpstream(ImaginePassthrough):
    """Forwards Chat Completions to xAI, OpenAI or Anthropic with a pay-per-token API key.

    Every request uses the provider's configured model, whatever the caller named (the backend's
    configs say grok-4.7, which must never reach OpenAI). Requests are adapted to what the provider
    takes: OpenAI gets max_completion_tokens, Anthropic's compatibility endpoint gets a token cap,
    a temperature within 0..1 and, as it ignores response_format, a JSON instruction instead. A
    parameter the provider still refuses for the model is dropped, remembered and the request sent
    again. 429/5xx are retried within the caller's budget, like OpenRouterUpstream. The key is
    never logged or echoed: the provider's own 401 text is replaced, everything else is scrubbed.

    With an xAI key the Imagine and voice routes are served too (ImaginePassthrough); OpenAI and
    Anthropic answer them 501.
    """

    def __init__(
        self,
        provider: Provider,
        api_key: Optional[str],
        http: httpx.Client,
        *,
        model: Optional[str] = None,
        rpm: float = PROVIDER_RPM,
        max_concurrency: int = MAX_CONCURRENCY,
        imagine_concurrency: int = IMAGINE_CONCURRENCY,
        max_retries: int = MAX_RETRIES,
        throttle_wait: float = OPENROUTER_THROTTLE_WAIT,
        anthropic_max_tokens: int = ANTHROPIC_MAX_TOKENS,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        reload_key: Optional[Callable[[], str]] = None,
    ):
        self.provider = provider
        self.mode = provider.kind  # shown in the request log line, like Upstream.mode
        self.imagine = provider.imagine
        self.imagine_unavailable = KEYED_IMAGINE_UNAVAILABLE
        self.api_key = (api_key or "").strip()
        self.http = http
        self.model = (model or "").strip() or provider_model(provider)
        self.rpm = rpm
        self.max_concurrency = max_concurrency
        self.imagine_concurrency = imagine_concurrency
        self.max_retries = max_retries
        self.throttle_wait = throttle_wait
        self.anthropic_max_tokens = anthropic_max_tokens
        self._bucket = TokenBucket(rpm, PROVIDER_BURST, clock=clock, sleep=sleep) if rpm > 0 else None
        self._slots = threading.BoundedSemaphore(max_concurrency)
        self._imagine_slots = threading.BoundedSemaphore(imagine_concurrency)
        self._sleep = sleep
        self._clock = clock
        self._reload_key = reload_key
        self._lock = threading.Lock()
        self._refused: set = set()  # parameters the provider refused for this model; never sent again

    # ----- chat

    def chat_completion(self, body: Dict[str, Any], budget: Optional[float] = None) -> Tuple[int, Dict[str, Any]]:
        """Forward one request, giving up before the caller's `budget` (seconds it will wait) runs out."""
        if not self._ensure_key():
            return 401, _error_body(self.key_hint(), "provider_key_missing")
        budget = DEFAULT_CALLER_BUDGET if budget is None else budget
        arrived = self._clock()
        deadline = arrived + budget
        last_start = deadline - min(MIN_ATTEMPT_SECONDS, budget / 2)  # latest moment worth calling the provider
        if not self._slots.acquire(timeout=max(0.0, last_start - arrived)):
            return self._throttled(last_start - arrived)
        try:
            attempt = adaptations = 0
            name = self.provider.name
            while True:
                max_wait = max(0.0, min(self.throttle_wait, last_start - self._clock()))
                if self._bucket is not None and not self._bucket.acquire(max_wait):
                    return self._throttled(max_wait)
                sent = self.prepare(body)
                timeout = max(1.0, min(UPSTREAM_TIMEOUT, deadline - self._clock()))
                try:
                    response = self.http.post(
                        self.provider.base_url + "/chat/completions",
                        json=sent,
                        headers=self._headers(),
                        timeout=httpx.Timeout(timeout, connect=min(CONNECT_TIMEOUT, timeout)),
                    )
                except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                    # The request never reached the provider, so sending it again cannot run it twice.
                    message = f"Could not reach {name}: {self._scrub(str(exc))}"
                    if attempt < self.max_retries and self._backoff(attempt, None, message, last_start):
                        attempt += 1
                        continue
                    return 502, _error_body(message, "upstream_unreachable")
                except httpx.TimeoutException:
                    # The provider may still be generating (and billing it): the caller decides whether to retry.
                    return 504, _error_body(f"{name} did not answer within {timeout:.0f}s.", "upstream_timeout")
                except httpx.TransportError as exc:
                    # The connection broke after the request went out, so the provider may have run it.
                    message = f"Lost the connection to {name}: {self._scrub(str(exc))}"
                    return 502, _error_body(message, "upstream_unreachable")

                status, data = response.status_code, _json_body(response)
                if status == 200:
                    return 200, self._finished(data, body, sent)
                if status == 401:
                    # The provider's own text can quote part of the key: say it in the bridge's words.
                    log.warning("%s rejected the API key in %s (HTTP 401)", name, self.provider.key_env)
                    return 401, _error_body(self._key_rejected(), "provider_key_rejected")
                refused = _refused_param(status, data, sent)
                if refused is not None and adaptations < MAX_ADAPTATIONS:
                    self._refuse(refused)
                    adaptations += 1
                    continue
                if (status == 429 or status >= 500) and attempt < self.max_retries:
                    reason = f"{name} HTTP {status} ({self._scrub(_error_message(data))[:160]})"
                    if self._backoff(attempt, response.headers.get("retry-after"), reason, last_start):
                        attempt += 1
                        continue
                return status, self._openai_error(status, data)
        finally:
            self._slots.release()

    def prepare(self, body: Dict[str, Any]) -> Dict[str, Any]:
        """The request as this provider gets it: its model, and only parameters it takes for that model."""
        sent = {key: value for key, value in body.items() if key not in ("model", "models", "stream", "stream_options")}
        sent["model"] = self.model
        with self._lock:
            refused = set(self._refused)
        kind = self.provider.kind
        if kind == "openai":
            refused.add("max_tokens")  # deprecated in favour of max_completion_tokens, refused by reasoning models
            if OPENAI_REASONING_MODEL.match(self.model):
                refused.update(("temperature", "top_p"))
        elif kind == "anthropic":
            refused.update(("response_format", "n"))  # ignored (JSON asked for in words instead), must be 1
            if isinstance(sent.get("temperature"), (int, float)):
                sent["temperature"] = min(1.0, max(0.0, float(sent["temperature"])))
            if sent.get("max_tokens") is None and sent.get("max_completion_tokens") is None:
                sent["max_tokens"] = self.anthropic_max_tokens
            messages = sent.get("messages")
            if isinstance(messages, list):
                # An empty text alongside tool calls is refused as an empty content block.
                sent["messages"] = [{**m, "content": None} if _empty_tool_call_text(m) else m for m in messages]
        if "max_tokens" in refused and "max_tokens" in sent:
            limit = sent.pop("max_tokens")
            if limit is not None and sent.get("max_completion_tokens") is None:
                sent["max_completion_tokens"] = limit
        for name in refused - {"max_tokens"}:
            sent.pop(name, None)
        wanted = _json_requested(body)
        if wanted is not None and "response_format" not in sent and isinstance(sent.get("messages"), list):
            sent["messages"] = _with_system_note(sent["messages"], _json_instruction(wanted))
        return sent

    def _refuse(self, name: str) -> None:
        with self._lock:
            if name in self._refused:
                return
            self._refused.add(name)
        action = "sending max_completion_tokens instead" if name == "max_tokens" else "leaving it out"
        log.warning("%s refused %r for %s; %s from now on", self.provider.name, name, self.model, action)

    def _finished(self, data: Dict[str, Any], body: Dict[str, Any], sent: Dict[str, Any]) -> Dict[str, Any]:
        """The provider's reply; JSON asked for in words may come back fenced, and the fence is taken off."""
        if _json_requested(body) is None or "response_format" in sent:
            return data
        for choice in data.get("choices") or []:
            message = choice.get("message") if isinstance(choice, dict) else None
            if isinstance(message, dict):
                message["content"] = _unfenced(message.get("content"))
        return data

    def _openai_error(self, status: int, data: Dict[str, Any]) -> Dict[str, Any]:
        """The provider's error as an OpenAI-style body ({"error": {message, type, code}}), with the key scrubbed."""
        error = data.get("error")
        if isinstance(error, dict):
            shaped = dict(error)
            shaped["message"] = str(error.get("message") or f"{self.provider.name} answered HTTP {status}")
        else:
            text = error if isinstance(error, str) else data.get("message") or data.get("detail")
            shaped = {"message": str(text or f"{self.provider.name} answered HTTP {status}")}
        shaped.setdefault("type", f"{self.provider.kind}_error")
        shaped.setdefault("code", None)
        return self._scrub_data({"error": shaped})

    def _throttled(self, waited: float) -> Tuple[int, Dict[str, Any]]:
        """The bridge's own 429 (create_app adds Retry-After) for a request it could not start in time."""
        if self._bucket is not None:
            message = (
                f"The bridge paces {self.provider.name} to {self.rpm:g} requests/min (PARTHENON_PROVIDER_RPM) and "
                f"this request would have waited more than {waited:.0f}s. Retry shortly."
            )
        else:
            message = (
                f"All {self.max_concurrency} of the bridge's {self.provider.name} slots stayed busy for more than "
                f"{waited:.0f}s. Retry shortly."
            )
        return 429, _error_body(message, "bridge_throttled")

    def _backoff(self, attempt: int, retry_after: Optional[str], reason: str, last_start: float) -> bool:
        """Sleep before the next attempt; False, without sleeping, if it could only start after `last_start`."""
        delay = _retry_delay(attempt, retry_after)
        if self._clock() + delay > last_start:
            log.warning("%s; not retrying, the caller would give up first", reason)
            return False
        log.warning("%s; retrying in %.1fs", reason, delay)
        self._sleep(delay)
        return True

    def models(self) -> Tuple[int, Dict[str, Any]]:
        """The one model this bridge sends every request to."""
        return 200, {"object": "list", "data": [{"id": self.model, "object": "model", "owned_by": self.provider.kind}]}

    # ----- Imagine and voice (xAI only; create_app answers 501 for the others before calling these)

    def _send(
        self, method: str, path: str, payload: Optional[Dict[str, Any]] = None, *, accept: str = "application/json",
    ) -> Union[httpx.Response, Tuple[int, Dict[str, Any]]]:
        if not self._ensure_key():
            return 401, _error_body(self.key_hint(), "provider_key_missing")
        name = self.provider.name
        attempt = 0
        while True:
            try:
                response = self.http.request(
                    method, self.provider.base_url + path, json=payload, headers=self._headers(accept),
                )
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                if attempt >= self.max_retries:
                    return 502, _error_body(f"Could not reach {name}: {self._scrub(str(exc))}", "upstream_unreachable")
                self._imagine_backoff(attempt, None)
                attempt += 1
                continue
            except httpx.TimeoutException:
                return 504, _error_body(f"{name} did not answer in time.", "upstream_timeout")
            except httpx.TransportError as exc:
                message = f"Lost the connection to {name}: {self._scrub(str(exc))}"
                return 502, _error_body(message, "upstream_unreachable")
            if response.status_code == 401:
                log.warning("%s rejected the API key in %s (HTTP 401)", name, self.provider.key_env)
                return 401, _error_body(self._key_rejected(), "provider_key_rejected")
            if (response.status_code == 429 or response.status_code >= 500) and attempt < self.max_retries:
                self._imagine_backoff(attempt, response.headers.get("retry-after"))
                attempt += 1
                continue
            return response

    def _request(self, method: str, path: str, payload: Optional[Dict[str, Any]] = None) -> Tuple[int, Dict[str, Any]]:
        status, data = super()._request(method, path, payload)
        return status, (self._scrub_data(data) if status >= 400 else data)

    def speech(self, body: Dict[str, Any]) -> Tuple[int, Union[Audio, Dict[str, Any]]]:
        status, data = super().speech(body)
        return status, (self._scrub_data(data) if isinstance(data, dict) else data)

    def _imagine_backoff(self, attempt: int, retry_after: Optional[str]) -> None:
        delay = _retry_delay(attempt, retry_after)
        log.warning("%s is busy or unavailable; retrying in %.1fs", self.provider.name, delay)
        self._sleep(delay)

    # ----- key and health

    def _ensure_key(self) -> bool:
        """Whether a key is set; while it is missing, re-read it so one added to .env works without a restart."""
        if not self.api_key and self._reload_key is not None:
            self.api_key = (self._reload_key() or "").strip()
            if self.api_key:
                log.info("Picked up %s from .env", self.provider.key_env)
        return bool(self.api_key)

    def key_hint(self) -> str:
        return (
            f"{self.provider.key_env} is not set. Set it where the bridge runs (the service's environment, or the "
            f".env in the parthenon folder), or choose another PARTHENON_UPSTREAM."
        )

    def _key_rejected(self) -> str:
        return (
            f"{self.provider.name} rejected the API key in {self.provider.key_env}. "
            "Check the key, and that its account has credits."
        )

    def _headers(self, accept: str = "application/json") -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Accept": accept}

    def _scrub(self, text: str) -> str:
        """Belt and braces: never echo the API key, even if an error message somehow contains it."""
        return text.replace(self.api_key, "[redacted]") if self.api_key else text

    def _scrub_data(self, data: Any) -> Any:
        if isinstance(data, str):
            return self._scrub(data)
        if isinstance(data, dict):
            return {key: self._scrub_data(value) for key, value in data.items()}
        if isinstance(data, list):
            return [self._scrub_data(value) for value in data]
        return data

    def health_info(self) -> Dict[str, Any]:
        return {
            "upstream": self.provider.kind,
            "provider": self.provider.label,
            "api_key_set": self._ensure_key(),
            "api_key_env": self.provider.key_env,
            "model": self.model,
            "requests_per_minute": self.rpm if self._bucket is not None else None,
            "imagine": self.imagine,
            "voice": self.imagine,
        }


# --------------------------------------------------------------------------- auto: the subscription first


def _is_grok_model(model: Any) -> bool:
    return isinstance(model, str) and model.strip().lower().startswith("grok")


class AutoUpstream:
    """PARTHENON_UPSTREAM=auto: the Grok subscription while the token file holds a usable sign-in, else
    `fallback` (the first provider whose key is set, else OpenRouter's free models).

    Decided again on every request from the token file (TokenStore re-reads it when it changes), so a
    `login` run beside the running bridge switches it to the subscription on the next request, and a
    logout or a revoked grant falls back. A request whose sign-in turns out to be dead (xAI refuses the
    refresh, or refuses the token even after one: its 400 "Incorrect API key") is answered by the fallback
    instead. A token xAI refused then rests for `rejected_retry_seconds` while the fallback serves, and is
    tried again after it; a new sign-in written to the file is served at once. On the subscription a model
    name that is not Grok's (the public default parthenon-free) is sent as `grok_model`; the fallbacks
    choose their own models.
    """

    def __init__(
        self,
        grok: "Upstream",
        fallback: Union["OpenRouterUpstream", "KeyedUpstream"],
        *,
        grok_model: str = GROK_MODEL,
        clock: Callable[[], float] = time.monotonic,
        rejected_retry_seconds: float = REJECTED_RETRY_SECONDS,
    ):
        self.grok = grok
        self.store = grok.store
        self.fallback = fallback
        self.grok_model = (grok_model or "").strip() or "grok-4.7"
        self._clock = clock
        self.rejected_retry_seconds = rejected_retry_seconds
        self._lock = threading.Lock()
        self._serving: Optional[bool] = None  # whether the last decision was the subscription, for the log
        self._rejected: Optional[Tuple[str, float]] = None  # (fingerprint of a token xAI refused, its rest ends)

    # ----- which one

    def rest_left(self) -> float:
        """Seconds the stored sign-in still rests because xAI refused its token; 0 when it does not rest."""
        state = self.store.usable_state()
        return 0.0 if state is None else self._rest_left(state)

    def _rest_left(self, state: Dict[str, Any]) -> float:
        with self._lock:
            if self._rejected is None:
                return 0.0
            fingerprint, until = self._rejected
            left = until - self._clock()
            if left > 0 and _fingerprint(state.get("access_token")) == fingerprint:
                return left
            self._rejected = None  # the rest is over, or a new sign-in replaced the refused token
            return 0.0

    def grok_ready(self) -> bool:
        state = self.store.usable_state()
        return state is not None and self._rest_left(state) <= 0

    def active(self) -> Union["Upstream", "OpenRouterUpstream", "KeyedUpstream"]:
        ready = self.grok_ready()
        with self._lock:
            changed, self._serving = ready != self._serving, ready
        if changed:
            if ready:
                log.info(
                    "Grok sign-in found in %s: serving the Grok subscription (%s)",
                    self.store.path, _identity(self.store.load() or {}),
                )
            else:
                why = f" (the file {self.store.problem})" if self.store.problem else ""
                log.info("No usable Grok sign-in in %s%s: serving %s", self.store.path, why, self.fallback_name)
        return self.grok if ready else self.fallback

    @property
    def fallback_name(self) -> str:
        provider = getattr(self.fallback, "provider", None)
        return f"{provider.name} {self.fallback.model}" if provider else "OpenRouter's free models"

    @property
    def fallback_label(self) -> str:
        provider = getattr(self.fallback, "provider", None)
        return provider.label if provider else PROVIDER_LABELS["openrouter"]

    @property
    def mode(self) -> str:
        active = self.active()
        return f"auto:grok-{active.mode}" if active is self.grok else f"auto:{active.mode}"

    @property
    def imagine(self) -> bool:
        return bool(self.active().imagine)

    @property
    def imagine_unavailable(self) -> str:
        return AUTO_IMAGINE_UNAVAILABLE

    def _dead_sign_in(self, exc: Exception) -> None:
        with self._lock:
            self._serving = False
            if isinstance(exc, SignInRejected):
                self._rejected = (exc.fingerprint, self._clock() + self.rejected_retry_seconds)
        if isinstance(exc, SignInRejected) and self.store.usable_state() is not None:
            log.warning(
                "xAI refuses the Grok sign-in and a refresh did not give a token it takes; %s answers for the next "
                "%.0fs, then the sign-in is tried again (at once after a new login)",
                self.fallback_name, self.rejected_retry_seconds,
            )
            return
        log.warning("The Grok sign-in stopped working (%s); %s answers instead", exc, self.fallback_name)

    # ----- chat

    def _for_grok(self, body: Dict[str, Any]) -> Dict[str, Any]:
        return body if _is_grok_model(body.get("model")) else {**body, "model": self.grok_model}

    def chat_completion(self, body: Dict[str, Any], budget: Optional[float] = None) -> Tuple[int, Dict[str, Any]]:
        if self.active() is self.grok:
            arrived = self._clock()
            try:
                return self.grok.chat_completion(self._for_grok(body), budget)
            except AuthError as exc:  # xAI refused the refresh, or the file went away mid-request
                self._dead_sign_in(exc)
                if budget is not None:
                    budget = max(1.0, budget - (self._clock() - arrived))
        return self.fallback.chat_completion(body, budget)

    def models(self) -> Tuple[int, Dict[str, Any]]:
        if self.active() is self.grok:
            try:
                return self.grok.models()
            except AuthError as exc:
                self._dead_sign_in(exc)
        return self.fallback.models()

    # ----- Imagine and voice: the subscription, or an xAI key as the fallback

    def _imagine(self, name: str, *args: Any) -> Tuple[int, Union[Audio, Dict[str, Any]]]:
        if self.active() is self.grok:
            try:
                return getattr(self.grok, name)(*args)
            except AuthError as exc:
                self._dead_sign_in(exc)
        if not self.fallback.imagine:
            return 501, _error_body(AUTO_IMAGINE_UNAVAILABLE, "imagine_unavailable")
        return getattr(self.fallback, name)(*args)

    def generate_image(self, body: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        return self._imagine("generate_image", body)  # type: ignore[return-value]

    def generate_video(self, body: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        return self._imagine("generate_video", body)  # type: ignore[return-value]

    def video_status(self, request_id: str) -> Tuple[int, Dict[str, Any]]:
        return self._imagine("video_status", request_id)  # type: ignore[return-value]

    def speech(self, body: Dict[str, Any]) -> Tuple[int, Union[Audio, Dict[str, Any]]]:
        return self._imagine("speech", body)

    # ----- health

    def health_info(self) -> Dict[str, Any]:
        """The serving upstream's own health, plus which way auto went. Without a sign-in there is no
        signed_in key at all: the backend reads signed_in false as "the LLM is not configured"."""
        active = self.active()
        info = dict(active.health_info())
        info.update({
            "auto": True,
            "grok_signed_in": active is self.grok,
            "fallback": self.fallback_label,
        })
        if active is self.grok:
            info["model"] = self.grok_model
        else:
            resting = self.rest_left()
            if resting > 0:  # signed in, but xAI refused the token: when the sign-in is tried again
                info["grok_retry_in_seconds"] = int(math.ceil(resting))
        return info


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


def create_app(
    upstream: Union[Upstream, OpenRouterUpstream, "KeyedUpstream", "AutoUpstream"], *,
    allowed_hosts: Optional[Any] = None,
) -> Flask:
    """The OpenAI-compatible app. `allowed_hosts` are the Host names it answers (default: loopback only)."""
    app = Flask("grok-bridge")
    hosts = {h.strip("[]").lower() for h in (allowed_hosts or LOCAL_HOSTS)}

    @app.before_request
    def only_local_programs():
        # Browsers always send Origin on cross-site requests; the OpenAI SDK
        # clients MiroFish uses never do. Rejecting it (and non-local Host
        # headers, against DNS rebinding) stops web pages from spending the
        # subscription through this port.
        if request.headers.get("Origin"):
            return _error(403, "Browser requests are not accepted by the Grok bridge", "forbidden")
        host = request.host.rsplit(":", 1)[0] if not request.host.endswith("]") else request.host
        if host.strip("[]").lower() not in hosts:
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
        budget = _caller_budget(request.headers.get("x-stainless-read-timeout"))
        if isinstance(upstream, (OpenRouterUpstream, KeyedUpstream, AutoUpstream)) or budget is not None:
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

    # ----- Imagine and voice passthrough ("Film the Chronicle"); the Grok subscription or an xAI key only.
    # Asked on every request: in auto mode it follows the Grok sign-in.

    def imagine_ready() -> bool:
        return bool(getattr(upstream, "imagine", False))

    def imagine_unavailable() -> Tuple[Response, int]:
        return _error(501, str(getattr(upstream, "imagine_unavailable", IMAGINE_UNAVAILABLE)), "imagine_unavailable")

    def imagine_call(label: str, fn: Callable[[], Tuple[int, Union[Audio, Dict[str, Any]]]]):
        started = time.time()
        result = call(fn)
        if result[1] != 202:  # a rendering video is polled every few seconds; log only the outcome
            log.info("%s -> HTTP %s in %.1fs via imagine", label, result[1], time.time() - started)
        return result

    def imagine_post(label: str, forward: Callable[[Dict[str, Any]], Tuple[int, Union[Audio, Dict[str, Any]]]]):
        if not imagine_ready():
            return imagine_unavailable()
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
        if not imagine_ready():
            return imagine_unavailable()
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


def _login_again() -> str:
    return "Run the login again." if PUBLIC else "Run `npm run grok:login` again."


def _can_open_browser(platform: Optional[str] = None, environ: Optional[Any] = None) -> bool:
    """A desktop to open the sign-in page on. A server (`render ssh`) has none: the owner opens the link
    on their own device, and Python's console browsers must never take over the terminal."""
    platform = sys.platform if platform is None else platform
    environ = os.environ if environ is None else environ
    if platform == "darwin" or platform.startswith("win"):
        return True
    return bool(environ.get("DISPLAY") or environ.get("WAYLAND_DISPLAY"))


def cmd_login(args: argparse.Namespace) -> int:
    """Device-code sign-in: prints a link and a code to approve at x.ai, then saves this machine's own grant
    to TOKEN_FILE (GROK_BRIDGE_TOKEN_FILE or --token-file), mode 0600."""
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
        print(f"The sign-in will be saved to {TOKEN_FILE}")
        print("Waiting for approval...\n")
        if not getattr(args, "no_browser", False) and _can_open_browser():
            webbrowser.open(url)

        interval = max(1, int(device.get("interval") or 5))
        deadline = time.time() + int(device.get("expires_in") or 600)
        while True:
            if time.time() > deadline:
                print(f"The sign-in code expired before it was approved. {_login_again()}")
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
        try:
            with store.file_lock():
                store.save(state)
        except OSError as exc:
            print(
                f"Signed in, but the sign-in could not be saved to {TOKEN_FILE}: {exc.strerror or exc}. "
                "Run the login as the user the bridge runs as, with GROK_BRIDGE_TOKEN_FILE pointing at a folder "
                "it can write."
            )
            return 1
    print(f"Signed in to Grok as {_identity(state)}. Sign-in saved to {TOKEN_FILE}")
    if UPSTREAM == "auto":
        print("A bridge running with PARTHENON_UPSTREAM=auto and this file serves the Grok subscription from its next request.")
    return 0


def _openrouter_key() -> str:
    return (os.environ.get("OPENROUTER_API_KEY") or "").strip()


def _env_file_openrouter_key() -> str:
    """OPENROUTER_API_KEY as the .env file has it now (read only while the running bridge has none)."""
    try:
        return (dotenv_values(PROJECT_ROOT / ".env").get("OPENROUTER_API_KEY") or "").strip()
    except OSError:
        return ""


def _env_file_value(name: str) -> str:
    """`name` as the .env file has it now (read only while the running bridge has no value for it)."""
    try:
        return (dotenv_values(PROJECT_ROOT / ".env").get(name) or "").strip()
    except OSError:
        return ""


def keyed_upstream(kind: str, http: httpx.Client, **kwargs: Any) -> "KeyedUpstream":
    """The KeyedUpstream for PARTHENON_UPSTREAM=`kind` (xai, openai or anthropic), keyed from the environment."""
    provider = PROVIDERS[kind]
    kwargs.setdefault("reload_key", lambda: _env_file_value(provider.key_env))
    return KeyedUpstream(provider, _env_key(provider.key_env), http, **kwargs)


def _sign_in_file_warnings(path: Path) -> List[str]:
    """What is wrong with how the sign-in file is kept: readable by others, or not its folder owner's."""
    try:
        info, folder = path.stat(), path.parent.stat()
    except OSError:
        return []
    warnings = []
    mode = stat.S_IMODE(info.st_mode)
    if mode & 0o077:
        warnings.append(f"Warning:      the sign-in file is mode {mode:04o}; it should be 0600 (chmod 600 {path})")
    if info.st_uid != folder.st_uid:
        warnings.append(
            f"Warning:      the sign-in file belongs to uid {info.st_uid} but its folder to uid {folder.st_uid}; "
            f"the bridge runs as the folder's owner and may not be able to read it (chown {folder.st_uid} {path})"
        )
    return warnings


def _print_sign_in(store: TokenStore) -> bool:
    """The Grok sign-in lines of `status` (never a token); whether the sign-in can be used."""
    state = store.load()
    if not state:
        problem = f" The sign-in file {TOKEN_FILE} {store.problem}." if store.problem else ""
        print(f"Not signed in.{problem} {LOGIN_HINT}")
        for warning in _sign_in_file_warnings(TOKEN_FILE):
            print(warning)
        return False
    print(f"Signed in as: {_identity(state)}")
    print(f"Sign-in file: {TOKEN_FILE}")
    for warning in _sign_in_file_warnings(TOKEN_FILE):
        print(warning)
    if state.get("revoked"):
        print(f"Status:       needs a new sign-in ({state['revoked']}). {LOGIN_HINT}")
        return False
    exp = _jwt_claims(state.get("access_token")).get("exp")
    if isinstance(exp, (int, float)):
        minutes = (exp - time.time()) / 60
        if minutes > 0:
            print(f"Access token: valid for {minutes:.0f} more min (refreshes automatically)")
        else:
            print("Access token: expired (refreshes automatically on the next request)")
    return store.usable_state() is not None


def _print_keyed_or_free(kind: str) -> bool:
    """The status lines of a keyed provider or OpenRouter; whether its key is set."""
    if kind in PROVIDERS:
        provider = PROVIDERS[kind]
        key_set = bool(_env_key(provider.key_env))
        print(f"API key:      {'set' if key_set else 'missing'} ({provider.key_env})")
        print(f"Model:        {provider_model(provider)} ({provider.model_env})")
        print(f"Imagine:      {'yes (images, video and voice)' if provider.imagine else 'no'}")
        pace = f"{PROVIDER_RPM:g} requests/min" if PROVIDER_RPM > 0 else "off"
        print(f"Throttle:     {pace} (PARTHENON_PROVIDER_RPM)")
        return key_set
    key_set = bool(_openrouter_key())
    print(f"API key:      {'set' if key_set else 'missing. ' + OPENROUTER_KEY_HINT}")
    print(f"Free models:  {', '.join(OPENROUTER_MODELS)}")
    print(f"Throttle:     {f'{OPENROUTER_RPM:g} requests/min' if OPENROUTER_RPM > 0 else 'off'}")
    return key_set


def _bridge_address() -> str:
    host = HOST if HOST and HOST not in ("0.0.0.0", "::") else "127.0.0.1"
    return f"[{host}]:{PORT}" if ":" in host else f"{host}:{PORT}"


def _running_bridge_health() -> Optional[Dict[str, Any]]:
    """The running bridge's /health on GROK_BRIDGE_HOST:GROK_BRIDGE_PORT, or None when nothing answers."""
    try:
        response = httpx.get(f"http://{_bridge_address()}/health", timeout=3.0, trust_env=False)
        health = response.json() if response.status_code == 200 else None
    except (httpx.HTTPError, ValueError):
        return None
    return health if isinstance(health, dict) else None


def _print_running(expect_grok: bool) -> None:
    """Which provider the running bridge serves right now (`status --live`, and always on the public server)."""
    health = _running_bridge_health()
    if health is None:
        print(f"Running:      no bridge answers on {_bridge_address()}")
        return
    makes = "portraits, film and voice" if health.get("imagine") and health.get("voice") else (
        "portraits and film" if health.get("imagine") else "no portraits, film or voice"
    )
    provider = health.get("provider") or health.get("upstream") or "unknown"
    print(f"Running:      {provider} on {_bridge_address()} ({makes})")
    resting = health.get("grok_retry_in_seconds")
    if isinstance(resting, (int, float)) and not isinstance(resting, bool) and resting > 0:
        print(
            f"Note:         xAI refused the Grok sign-in and a refresh did not fix it; the bridge tries it again in "
            f"{resting:.0f}s. If this keeps happening, sign in again. {LOGIN_HINT}"
        )
    elif expect_grok and provider != PROVIDER_LABELS["grok"]:
        print(
            "Warning:      the running bridge does not see this sign-in. Check that it has the same "
            "GROK_BRIDGE_TOKEN_FILE and that its user can read the file."
        )


def cmd_status(args: Optional[argparse.Namespace]) -> int:
    """The configured upstream, what auto chose, the Grok sign-in (never a token) and, with --live or on the
    public server, the provider the running bridge serves right now."""
    kind = resolve_upstream(UPSTREAM, token_file=TOKEN_FILE if UPSTREAM == "auto" else None)
    print(f"Upstream:     {UPSTREAM if kind == UPSTREAM else f'{UPSTREAM} -> {kind}'} (PARTHENON_UPSTREAM)")
    if kind == "grok":
        with _http_client(15.0) as http:
            ok = _print_sign_in(TokenStore(TOKEN_FILE, http))
        if UPSTREAM == "auto":
            print(f"Fallback:     {resolve_fallback()} (when the Grok sign-in is gone)")
    else:
        if UPSTREAM == "auto":
            store = TokenStore(TOKEN_FILE, None)  # type: ignore[arg-type]  # read only
            state = store.load()
            if store.problem:
                why = f"unusable, the file {store.problem}"
            else:
                why = "needs a new sign-in" if state else "none yet"
            print(f"Grok sign-in: {why} ({TOKEN_FILE}); auto serves the Grok subscription once it is signed in")
            for warning in _sign_in_file_warnings(TOKEN_FILE):
                print(warning)
        ok = _print_keyed_or_free(kind)
    if getattr(args, "live", False) or PUBLIC:
        _print_running(expect_grok=kind == "grok" and ok)
    return 0 if ok else 1


def cmd_logout(_args: Optional[argparse.Namespace]) -> int:
    with _http_client(15.0) as http:
        removed = TokenStore(TOKEN_FILE, http).delete()
    print("Signed out; the stored Grok sign-in was deleted." if removed else "Already signed out.")
    if removed and UPSTREAM == "auto":
        print(f"A bridge running with PARTHENON_UPSTREAM=auto serves {resolve_fallback()} from its next request.")
    return 0


def cmd_probe(args: argparse.Namespace) -> int:
    kind = args.upstream or UPSTREAM
    if kind not in UPSTREAMS:
        print(f"PARTHENON_UPSTREAM must be one of {', '.join(UPSTREAMS)} (got {kind!r})")
        return 2
    kind = resolve_upstream(kind, token_file=TOKEN_FILE if kind == "auto" else None)
    with _http_client(120.0) as http:
        upstream: Union[Upstream, OpenRouterUpstream, KeyedUpstream]
        if kind in PROVIDERS:
            upstream = keyed_upstream(kind, http, max_retries=1, reload_key=None)
            model = args.model or "parthenon"  # replaced by the provider's configured model
            if not upstream.api_key:
                print(upstream.key_hint())
                return 1
            max_tokens = 1024
        elif kind == "openrouter":
            model = args.model or FREE_MODEL_ALIAS
            upstream = OpenRouterUpstream(_openrouter_key(), http, max_retries=1)
            if not upstream.api_key:
                print(OPENROUTER_KEY_HINT)
                return 1
            max_tokens = 1024  # free reasoning models spend part of the budget thinking before they answer
        else:
            model = args.model or os.environ.get("LLM_MODEL_NAME") or "grok-4.3"
            if (args.upstream or UPSTREAM) == "auto" and not _is_grok_model(model):
                model = GROK_MODEL  # as auto sends a non-Grok model name on the subscription
            upstream = Upstream(TokenStore(TOKEN_FILE, http), http, mode=args.mode, max_retries=1)
            max_tokens = 300

        def via(reply: Dict[str, Any]) -> str:
            return f"served by {reply.get('model')}" if kind != "grok" else f"via {upstream.mode}"

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


def _allowed_hosts(host: str) -> set:
    """Host names the bridge answers: loopback, plus the listen address when it is a specific one."""
    host = host.strip().strip("[]").lower()
    return LOCAL_HOSTS | ({host} if host and host not in ("0.0.0.0", "::") else set())


def build_upstream(kind: str, http: httpx.Client) -> Union[Upstream, OpenRouterUpstream, KeyedUpstream, AutoUpstream]:
    """What `serve` forwards to for PARTHENON_UPSTREAM=`kind`, from the environment and TOKEN_FILE."""
    kind = (kind or "grok").strip().lower()
    if kind == "auto":
        fallback = build_upstream(resolve_fallback(), http)
        grok = Upstream(TokenStore(TOKEN_FILE, http), http, follow_budget=True, detect_rejection=True)
        return AutoUpstream(grok, fallback)  # type: ignore[arg-type]
    if kind in PROVIDERS:
        return keyed_upstream(kind, http)
    if kind == "openrouter":
        return OpenRouterUpstream(_openrouter_key(), http, reload_key=_env_file_openrouter_key)
    return Upstream(TokenStore(TOKEN_FILE, http), http, follow_budget=PUBLIC, detect_rejection=PUBLIC)


def _log_serving(upstream: Union[Upstream, OpenRouterUpstream, KeyedUpstream, AutoUpstream]) -> None:
    if isinstance(upstream, AutoUpstream):
        state = upstream.store.usable_state()
        log.info(
            "Parthenon bridge on http://%s:%s/v1 -> auto: the Grok subscription while %s holds a usable sign-in "
            "(%s; model %s for non-Grok model names, up to %s requests at once, plus %s image/video/voice "
            "requests), else %s",
            HOST, PORT, upstream.store.path,
            f"signed in as {_identity(state)}" if state else "not signed in yet", upstream.grok_model,
            MAX_CONCURRENCY, IMAGINE_CONCURRENCY, upstream.fallback_name,
        )
        fallback = upstream.fallback
        if isinstance(fallback, KeyedUpstream) and not fallback.api_key:
            log.warning("Without a Grok sign-in: %s", fallback.key_hint())
        elif isinstance(fallback, OpenRouterUpstream) and not fallback.api_key:
            log.warning("Without a Grok sign-in LLM requests fail: %s", OPENROUTER_KEY_HINT)
        return
    if isinstance(upstream, KeyedUpstream):
        if not upstream.api_key:
            log.warning("%s LLM requests will fail until it is set.", upstream.key_hint())
        log.info(
            "Parthenon bridge on http://%s:%s/v1 -> %s %s (%s, up to %s requests at once%s)",
            HOST, PORT, upstream.provider.name, upstream.model,
            f"{PROVIDER_RPM:g} requests/min" if PROVIDER_RPM > 0 else "no throttle", MAX_CONCURRENCY,
            f", plus {IMAGINE_CONCURRENCY} image/video/voice requests" if upstream.imagine else "",
        )
    elif isinstance(upstream, OpenRouterUpstream):
        if not upstream.api_key:
            log.warning("%s LLM requests will fail until it is set.", OPENROUTER_KEY_HINT)
        log.info(
            "Parthenon bridge on http://%s:%s/v1 -> OpenRouter free models %s (%s, up to %s requests at once)",
            HOST, PORT, ", ".join(upstream.router.models),
            f"{OPENROUTER_RPM:g} requests/min" if OPENROUTER_RPM > 0 else "no throttle", MAX_CONCURRENCY,
        )
    else:
        state = upstream.store.load()
        if not state:
            log.warning("Not signed in yet; LLM requests will fail until you run `npm run grok:login`.")
        else:
            log.info("Using the Grok subscription sign-in for %s", _identity(state))
        log.info(
            "Grok bridge on http://%s:%s/v1 (mode=%s, up to %s requests at once, "
            "plus %s image/video/voice requests)",
            HOST, PORT, upstream.mode, MAX_CONCURRENCY, IMAGINE_CONCURRENCY,
        )


def cmd_serve(_args: Optional[argparse.Namespace]) -> int:
    http = _http_client()
    kind = resolve_upstream(UPSTREAM, token_file=TOKEN_FILE if UPSTREAM == "auto" else None)
    if kind != UPSTREAM:
        log.info("PARTHENON_UPSTREAM=%s chose %s for now", UPSTREAM, kind)
    upstream = build_upstream(UPSTREAM, http)
    _log_serving(upstream)
    create_app(upstream, allowed_hosts=_allowed_hosts(HOST)).run(host=HOST, port=PORT, threaded=True)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    global TOKEN_FILE
    sys.stdout.reconfigure(line_buffering=True)
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    parser = argparse.ArgumentParser(description="Grok subscription bridge for Parthenon")
    commands = parser.add_subparsers(dest="command", required=True)
    login = commands.add_parser("login", help="sign in with your Grok subscription")
    login.add_argument("--no-browser", action="store_true", help="print the sign-in link instead of opening it")
    commands.add_parser("serve", help="run the local OpenAI-compatible endpoint (upstream from PARTHENON_UPSTREAM)")
    status = commands.add_parser("status", help="show the configured upstream and sign-in state")
    status.add_argument(
        "--live", action="store_true",
        help="also ask the running bridge which provider it serves now (always on with PARTHENON_PUBLIC)",
    )
    logout = commands.add_parser("logout", help="delete the stored sign-in")
    probe = commands.add_parser("probe", help="check what the upstream accepts (JSON reply and a tool call)")
    probe.add_argument("--upstream", choices=UPSTREAMS, help="upstream to test (defaults to PARTHENON_UPSTREAM)")
    probe.add_argument(
        "--model",
        help="model to test (defaults to LLM_MODEL_NAME for grok, parthenon-free for openrouter; "
        "xai, openai and anthropic always use XAI_MODEL, OPENAI_MODEL or ANTHROPIC_MODEL)",
    )
    probe.add_argument("--mode", default="auto", choices=["auto", "chat", "responses"], help="grok only")
    for command in (login, status, logout, probe):
        command.add_argument(
            "--token-file", help="the sign-in file (default: GROK_BRIDGE_TOKEN_FILE, else ~/.config/parthenon/grok-oauth.json)",
        )
    args = parser.parse_args(argv)
    if getattr(args, "token_file", None):
        TOKEN_FILE = Path(args.token_file).expanduser()
    if args.command in ("serve", "status") and UPSTREAM not in UPSTREAMS:
        print(f"PARTHENON_UPSTREAM must be one of {', '.join(UPSTREAMS)} (got {UPSTREAM!r})")
        return 2
    handlers = {"login": cmd_login, "serve": cmd_serve, "status": cmd_status, "logout": cmd_logout, "probe": cmd_probe}
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
