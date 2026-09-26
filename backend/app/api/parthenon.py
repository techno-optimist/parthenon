"""
Parthenon API routes.

POST /api/parthenon/stage/draft asks the Oracle to draft the missing parts of
a custom stage from the "Build your own stage" panel.
GET /api/parthenon/status tells the home page what this instance can run.
/api/parthenon/chronicle/<report_id>/film turns a finished Chronicle into a
narrated short film made with Grok (see services/chronicle_film.py).
"""

import hashlib
import os
import re
import threading
import time
from urllib.parse import urlsplit

import httpx
from flask import jsonify, request, send_file, url_for
from openai import APIConnectionError, AuthenticationError, PermissionDeniedError

from . import parthenon_bp
from ..config import Config
from ..services import chronicle_film
from ..services.report_agent import ReportManager, ReportStatus
from ..services.stage_oracle import (
    OracleUnavailableError,
    StageOracle,
    StageValidationError,
)
from ..utils.llm_client import LLMResponseError
from ..utils.locale import get_locale
from ..utils.logger import get_logger
from ..utils.zep import ZepApiError, get_zep_client


logger = get_logger('mirofish.parthenon.api')

# The status check asks Zep Cloud once whether ZEP_API_KEY works and reuses
# the answer; after a network failure (validity unknown) it asks again sooner.
ZEP_KEY_CHECK_TTL_SECONDS = 300
ZEP_KEY_RECHECK_SECONDS = 30
ZEP_KEY_CHECK_TIMEOUT_SECONDS = 5.0
BRIDGE_HEALTH_TIMEOUT_SECONDS = 1.5

# Hosts the local LLM bridge serves (LOCAL_HOSTS in bridge/grok_bridge.py).
LOOPBACK_HOSTS = {'127.0.0.1', 'localhost', '::1'}
BRIDGE_ERROR_TYPES = {'grok_bridge_error', 'openrouter_bridge_error'}
# Bridge errors whose messages are written for people and never echo the prompt.
BRIDGE_PUBLIC_ERROR_CODES = {
    'grok_not_signed_in',
    'grok_refresh_unavailable',
    'openrouter_key_missing',
    'openrouter_daily_limit',
    'bridge_throttled',
    'upstream_unreachable',
}
MAX_BRIDGE_MESSAGE_CHARS = 300

_zep_key_check_lock = threading.Lock()
_zep_key_check = {'fingerprint': None, 'expires': 0.0, 'result': (None, None)}


def _error(message: str, status: int):
    return jsonify({'success': False, 'error': message}), status


def _loopback_origin(base_url):
    """The origin of LLM_BASE_URL when it points at the local bridge, else None."""

    try:
        parts = urlsplit(base_url or '')
        host = (parts.hostname or '').lower()
    except ValueError:
        return None
    if parts.scheme not in ('http', 'https') or host not in LOOPBACK_HOSTS or '@' in parts.netloc:
        return None
    return f'{parts.scheme}://{parts.netloc}'


def _memory_backend():
    """'local' or 'zep'; None when MEMORY_BACKEND is invalid."""

    try:
        return Config.memory_backend()
    except ValueError:
        return None


def _zep_key_status():
    """(valid, problem) for ZEP_API_KEY: True, False or None (unknown).

    With the local memory backend no key is needed, so this is (True, None)
    without a network call. Never returns the key or the provider's
    response body.
    """

    if _memory_backend() == 'local':
        return True, None
    key = (Config.ZEP_API_KEY or '').strip()
    if Config.is_placeholder(key):
        return None, None
    fingerprint = hashlib.sha256(key.encode('utf-8')).hexdigest()
    with _zep_key_check_lock:
        if (
            _zep_key_check['fingerprint'] == fingerprint
            and time.monotonic() < _zep_key_check['expires']
        ):
            return _zep_key_check['result']

    ttl = ZEP_KEY_CHECK_TTL_SECONDS
    try:
        get_zep_client(key, timeout=ZEP_KEY_CHECK_TIMEOUT_SECONDS).project.get()
        result = (True, None)
    except Exception as error:  # noqa: BLE001 - reduced to a status code
        status = error.status_code if isinstance(error, ZepApiError) else None
        if status in (401, 403):
            result = (
                False,
                f'Zep Cloud rejected ZEP_API_KEY (HTTP {status}). Put a valid key from '
                'https://app.getzep.com in .env and restart npm run dev.',
            )
            logger.warning('Zep Cloud rejected ZEP_API_KEY during the status check (HTTP %s)', status)
        else:
            result = (None, None)
            ttl = ZEP_KEY_RECHECK_SECONDS
            logger.warning(
                'Zep key check could not finish: type=%s status=%s',
                type(error).__name__,
                status or 'none',
            )

    with _zep_key_check_lock:
        _zep_key_check.update(
            fingerprint=fingerprint, expires=time.monotonic() + ttl, result=result
        )
    return result


def _llm_status():
    """(configured, problem), including what the local LLM bridge reports."""

    configured = not Config.is_placeholder(Config.LLM_API_KEY)
    origin = _loopback_origin(Config.LLM_BASE_URL)
    if origin is None:
        return configured, None

    try:
        response = httpx.get(
            f'{origin}/health', timeout=BRIDGE_HEALTH_TIMEOUT_SECONDS, trust_env=False
        )
        health = response.json() if response.status_code == 200 else None
    except (httpx.HTTPError, ValueError):
        health = None

    if not isinstance(health, dict):
        return configured, (
            f'The LLM bridge at {origin} is not answering. '
            'Check that npm run dev is still running.'
        )
    if health.get('api_key_set') is False:
        return False, (
            'OPENROUTER_API_KEY is not set for the LLM bridge. Add it to .env and '
            'restart npm run dev, or switch PARTHENON_UPSTREAM to grok.'
        )
    if health.get('signed_in') is False:
        return False, (
            'The LLM bridge is not signed in to Grok. Run npm run grok:login, then reload.'
        )
    return configured, None


def _bridge_error_message(error):
    """The local bridge's own message for a failed call, when it is safe to show."""

    if _loopback_origin(Config.LLM_BASE_URL) is None:
        return None
    body = getattr(error, 'body', None)
    if isinstance(body, dict) and isinstance(body.get('error'), dict):
        body = body['error']
    if not isinstance(body, dict):
        return None
    error_type, code, message = body.get('type'), body.get('code'), body.get('message')
    if not (
        isinstance(error_type, str) and error_type in BRIDGE_ERROR_TYPES
        and isinstance(code, str) and code in BRIDGE_PUBLIC_ERROR_CODES
        and isinstance(message, str)
    ):
        return None
    message = ' '.join(re.sub(r'[\x00-\x1f\x7f-\x9f]', ' ', message).split())
    return message[:MAX_BRIDGE_MESSAGE_CHARS] or None


@parthenon_bp.route('/status', methods=['GET'])
def instance_status():
    """What this instance can run right now. Never includes secrets.

    memoryBackend is 'local' (SQLite store in this process, no key needed)
    or 'zep' (Zep Cloud). zepConfigured is True whenever runs have a usable
    memory backend. zepKeyValid is True once Zep Cloud accepted ZEP_API_KEY
    (always True locally), False when it rejected it (zepProblem says why)
    and None when unknown. llmProblem says why the Oracle and runs cannot
    reach a working LLM, or is None.
    """

    backend = _memory_backend()
    zep_key_valid, zep_problem = _zep_key_status()
    llm_configured, llm_problem = _llm_status()
    return jsonify({
        'success': True,
        'data': {
            'memoryBackend': backend,
            'zepConfigured': backend == 'local' or (
                backend == 'zep' and not Config.is_placeholder(Config.ZEP_API_KEY)
            ),
            'zepKeyValid': zep_key_valid,
            'zepProblem': zep_problem,
            'llmConfigured': llm_configured,
            'llmProblem': llm_problem,
            'upstream': (os.environ.get('PARTHENON_UPSTREAM') or 'grok').strip().lower(),
            'model': Config.LLM_MODEL_NAME,
        },
    })


@parthenon_bp.route('/stage/draft', methods=['POST'])
def draft_stage():
    """Draft a custom stage.

    Request JSON: {"stage": {...}, "fill": ["words", "audience", ...]}
    Response: {"success": true, "data": {title, speakers, audience, question,
    happensNext, filled}}
    """

    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return _error('Send a JSON object with the stage to draft.', 400)

    try:
        draft = StageOracle().draft(body.get('stage'), body.get('fill'))
    except LLMResponseError as error:
        # LLMResponseError messages are written to be safe to show.
        logger.warning(
            'Oracle returned an unusable response: %s (finish_reason=%s)',
            error,
            error.finish_reason or 'unknown',
        )
        return _error(f'The Oracle could not answer: {error}', 502)
    except StageValidationError as error:
        return _error(str(error), 400)
    except OracleUnavailableError as error:
        logger.error('Oracle unavailable: LLM client is not configured')
        return _error(str(error), 503)
    except Exception as error:  # noqa: BLE001 - mapped to safe public errors
        provider_status = getattr(error, 'status_code', None)
        request_id = getattr(error, 'request_id', None)

        if isinstance(provider_status, int):
            # Only the local bridge's own, prompt-free messages are shown.
            bridge_message = _bridge_error_message(error)
            if (
                bridge_message is None
                and isinstance(error, (AuthenticationError, PermissionDeniedError))
                and Config.LLM_API_KEY
                and Config.is_placeholder(Config.LLM_API_KEY)
                and _loopback_origin(Config.LLM_BASE_URL) is None
            ):
                logger.error(
                    'Oracle provider rejected the placeholder LLM_API_KEY (status=%s)',
                    provider_status,
                )
                return _error(
                    'The Oracle is silent: LLM_API_KEY in .env is still a placeholder. '
                    'Add a real key and restart npm run dev.',
                    503,
                )

            if bridge_message:
                public_error = (
                    f'The Oracle\'s LLM bridge could not answer (HTTP {provider_status}): '
                    f'{bridge_message}'
                )
            else:
                public_error = (
                    f'The Oracle\'s LLM provider request failed (HTTP {provider_status})'
                )
            if request_id:
                safe_request_id = re.sub(
                    r'[^a-zA-Z0-9._:-]', '', str(request_id)
                )[:128]
                if safe_request_id:
                    public_error += f' (request_id: {safe_request_id})'
            # Provider bodies may echo the prompt; never log or return them.
            logger.error(
                'Oracle provider request failed: type=%s status=%s request_id=%s bridge=%s',
                type(error).__name__,
                provider_status,
                request_id or 'unknown',
                'yes' if bridge_message else 'no',
            )
            return _error(public_error, 502)

        if isinstance(error, APIConnectionError):
            logger.error(
                'Oracle could not reach the LLM provider: type=%s',
                type(error).__name__,
            )
            return _error('The Oracle could not reach the LLM provider.', 502)

        logger.error(
            'Unexpected Oracle failure: type=%s', type(error).__name__,
            exc_info=True,
        )
        return _error('The Oracle could not draft the stage; check the server logs.', 500)

    return jsonify({'success': True, 'data': draft})


# ============== Film the Chronicle ==============

CHRONICLE_NOT_FOUND = 'Chronicle not found.'


def _chronicle(report_id):
    """(report, error response) for a film route.

    Film routes key everything on report.report_id, the id stored in meta.json:
    on a case-insensitive disk REPORT_X finds the folder of report_x, and the
    film job, its manifest and its file URLs must all use the one spelling.
    """

    if not chronicle_film.valid_report_id(report_id):
        return None, _error(CHRONICLE_NOT_FOUND, 404)
    try:
        report = ReportManager.get_report(report_id)
    except Exception as error:  # noqa: BLE001 - a corrupt meta.json
        logger.error('Chronicle %s could not be read: type=%s', report_id, type(error).__name__)
        return None, _error('The Chronicle could not be read.', 500)
    if report is None:
        return None, _error(CHRONICLE_NOT_FOUND, 404)
    if not chronicle_film.valid_report_id(getattr(report, 'report_id', None)):
        logger.error('Chronicle %s has an invalid id in its meta.json', report_id)
        return None, _error('The Chronicle could not be read.', 500)
    return report, None


def _film_file_url(report_id, name):
    path = chronicle_film.film_file_path(report_id, name)
    if path is None:
        return None
    # The version stamp keeps browsers from showing an earlier film of the Chronicle.
    version = int(os.stat(path).st_mtime)
    return url_for('parthenon.chronicle_film_file', report_id=report_id, name=name, v=version)


@parthenon_bp.route('/chronicle/<report_id>/film', methods=['POST'])
def start_chronicle_film(report_id):
    """Film a completed Chronicle in the background.

    Request JSON (optional): {"voice": "rex" | "eve" | "ara", "shots": 4..8}
    202: {"success": true, "data": {"status": "running", "report_id": "..."}}
    400 bad voice/shots, 404 unknown Chronicle, 409 Chronicle not finished or a
    film already running, 503 ffmpeg missing.
    """

    report, failure = _chronicle(report_id)
    if failure:
        return failure

    body = request.get_json(silent=True)
    if body is None:
        if request.get_data(cache=True):
            return _error('Send a JSON object with the film options.', 400)
        body = {}
    if not isinstance(body, dict):
        return _error('Send a JSON object with the film options.', 400)
    try:
        voice = chronicle_film.normalise_voice(body.get('voice'))
        shots = chronicle_film.normalise_shot_count(body.get('shots'))
    except chronicle_film.FilmValidationError as error:
        return _error(str(error), 400)

    if report.status != ReportStatus.COMPLETED:
        return _error('The Chronicle is not finished yet; film it once it is complete.', 409)

    try:
        chronicle_film.start_film(report, voice=voice, shots=shots, locale=get_locale())
    except chronicle_film.FilmValidationError as error:
        return _error(str(error), 400)
    except chronicle_film.FilmConflictError as error:
        return _error(str(error), 409)
    except chronicle_film.FilmUnavailableError as error:
        return _error(str(error), 503)
    except OSError as error:
        logger.error(
            'Could not start the film of %s: type=%s', report.report_id, type(error).__name__
        )
        return _error('The film could not be started; check the server logs.', 500)

    data = {'status': 'running', 'report_id': report.report_id}
    return jsonify({'success': True, 'data': data}), 202


@parthenon_bp.route('/chronicle/<report_id>/film', methods=['GET'])
def chronicle_film_status(report_id):
    """The film manifest with file URLs.

    data: {report_id, status: none|running|completed|failed, stage, progress,
    message, title, logline, voice, duration, error, created_at, updated_at,
    video_url, poster_url, captions_url, voices: [{id, tone}],
    shots: [{index, narration, status, thumb, thumb_url}]}
    """

    report, failure = _chronicle(report_id)
    if failure:
        return failure

    # The URL may spell the id differently from the running job (see _chronicle).
    report_id = report.report_id
    manifest = chronicle_film.get_film(report_id)
    completed = manifest.get('status') == 'completed'
    shots = []
    for shot in manifest.get('shots') or []:
        if not isinstance(shot, dict):
            continue
        thumb = shot.get('thumb')
        shots.append({
            **shot,
            'thumb_url': _film_file_url(report_id, thumb) if isinstance(thumb, str) else None,
        })
    data = {
        **manifest,
        'report_id': report_id,
        'shots': shots,
        'video_url': _film_file_url(report_id, chronicle_film.FILM_NAME) if completed else None,
        'poster_url': _film_file_url(report_id, chronicle_film.POSTER_NAME) if completed else None,
        'captions_url': _film_file_url(report_id, chronicle_film.CAPTIONS_NAME) if completed else None,
        'voices': [{'id': voice, 'tone': tone} for voice, tone in chronicle_film.VOICES.items()],
    }
    return jsonify({'success': True, 'data': data})


@parthenon_bp.route('/chronicle/<report_id>/film/<name>', methods=['GET'])
def chronicle_film_file(report_id, name):
    """film.mp4, poster.jpg, captions.vtt or shot_XX.jpg, with Range support."""

    path = chronicle_film.film_file_path(report_id, name)
    if path is None:
        return _error('Film file not found.', 404)
    response = send_file(
        path, mimetype=chronicle_film.film_file_type(name), conditional=True, max_age=0
    )
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response
