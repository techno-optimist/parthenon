"""
Which model serves the city, and what else it can make here.

The local bridge's /health says which provider it forwards to ("provider":
free, grok, openai, claude or grok-subscription) and whether that provider
also paints and films ("imagine") and speaks ("voice"). Portraits and film
need Grok Imagine (a Grok subscription, or an xAI key), film also needs
ffmpeg, and server voices need Grok's text to speech.

When the bridge cannot be asked, the provider is worked out from
PARTHENON_UPSTREAM and the keys that are set, and nothing new is made.
PARTHENON_UPSTREAM=auto is the Grok subscription when the bridge's token
file (GROK_BRIDGE_TOKEN_FILE) is there, else the first key of XAI_API_KEY,
OPENAI_API_KEY and ANTHROPIC_API_KEY, else the free models; here the file is
only looked at, never read (the bridge alone knows whether its sign-in is
still good, and says so in /health).
"""

import os
import threading
import time
from typing import Any, Dict, Mapping, Optional
from urllib.parse import urlsplit

import httpx

from ..config import Config


PROVIDERS = ('free', 'grok', 'openai', 'claude', 'grok-subscription')
UPSTREAM_PROVIDER = {
    'openrouter': 'free',
    'free': 'free',
    'xai': 'grok',
    'openai': 'openai',
    'anthropic': 'claude',
    'claude': 'claude',
    'grok': 'grok-subscription',
}
KEYED_UPSTREAMS = (('XAI_API_KEY', 'grok'), ('OPENAI_API_KEY', 'openai'), ('ANTHROPIC_API_KEY', 'claude'))
LOOPBACK_HOSTS = {'127.0.0.1', 'localhost', '::1'}
HEALTH_TTL_SECONDS = 30.0
HEALTH_TIMEOUT_SECONDS = 1.5
NO_FEATURES = {'portraits': False, 'film': False, 'voice': False}

_health_lock = threading.Lock()
_health_cache: Dict[str, Any] = {'origin': None, 'expires': 0.0, 'health': None}


def bridge_origin(base_url: Optional[str] = None) -> Optional[str]:
    """The origin of LLM_BASE_URL when it is the local bridge, else None."""

    try:
        parts = urlsplit(base_url if base_url is not None else (Config.LLM_BASE_URL or ''))
        host = (parts.hostname or '').lower()
    except ValueError:
        return None
    if parts.scheme not in ('http', 'https') or host not in LOOPBACK_HOSTS or '@' in parts.netloc:
        return None
    return f'{parts.scheme}://{parts.netloc}'


def remember_health(origin: Optional[str], health: Optional[dict]) -> None:
    """Keep a /health answer another caller already fetched (the status route)."""

    with _health_lock:
        _health_cache.update(
            origin=origin, health=health if isinstance(health, dict) else None,
            expires=time.monotonic() + HEALTH_TTL_SECONDS,
        )


def bridge_health(fresh: bool = False) -> Optional[dict]:
    """The bridge's /health (cached for 30 s), or None when it is not the bridge or does not answer."""

    origin = bridge_origin()
    if origin is None:
        return None
    with _health_lock:
        if (
            not fresh
            and _health_cache['origin'] == origin
            and time.monotonic() < _health_cache['expires']
        ):
            return _health_cache['health']
    try:
        response = httpx.get(f'{origin}/health', timeout=HEALTH_TIMEOUT_SECONDS, trust_env=False)
        health = response.json() if response.status_code == 200 else None
    except (httpx.HTTPError, ValueError):
        health = None
    remember_health(origin, health)
    return health if isinstance(health, dict) else None


def grok_token_file_present(environ: Mapping[str, str]) -> bool:
    """Whether GROK_BRIDGE_TOKEN_FILE names a file with something in it (it is never opened here)."""

    path = str(environ.get('GROK_BRIDGE_TOKEN_FILE') or '').strip()
    if not path:
        return False
    try:
        return os.path.isfile(path) and os.path.getsize(path) > 0
    except OSError:
        return False


def provider_from_env(environ: Optional[Mapping[str, str]] = None, public: bool = False) -> str:
    env = os.environ if environ is None else environ
    upstream = str(env.get('PARTHENON_UPSTREAM') or ('auto' if public else 'grok')).strip().lower()
    if upstream == 'auto':
        if grok_token_file_present(env):
            return 'grok-subscription'
        for key, provider in KEYED_UPSTREAMS:
            if str(env.get(key) or '').strip():
                return provider
        return 'free'
    return UPSTREAM_PROVIDER.get(upstream, 'free' if public else 'grok-subscription')


def provider_of(health: Optional[dict], public: bool = False) -> str:
    if isinstance(health, dict):
        label = health.get('provider')
        if isinstance(label, str) and label in PROVIDERS:
            return label
        upstream = health.get('upstream')
        if isinstance(upstream, str) and upstream.lower() in UPSTREAM_PROVIDER:
            return UPSTREAM_PROVIDER[upstream.lower()]
    return provider_from_env(public=public)


def features_of(health: Optional[dict]) -> Dict[str, bool]:
    """{portraits, film, voice}: what can be newly made on this server."""

    if not isinstance(health, dict):
        return dict(NO_FEATURES)
    declared = health.get('features')
    if isinstance(declared, dict):
        found = {name: declared.get(name) is True for name in NO_FEATURES}
    else:
        imagine = health.get('imagine') is True
        voice = health.get('voice')
        found = {'portraits': imagine, 'film': imagine, 'voice': imagine if voice is None else voice is True}
    if health.get('signed_in') is False or health.get('api_key_set') is False:
        return dict(NO_FEATURES)
    if found['film']:
        from ..services.chronicle_film import find_tool

        found['film'] = bool(find_tool('ffmpeg') and find_tool('ffprobe'))
    return found


def current_features() -> Dict[str, bool]:
    return features_of(bridge_health())
