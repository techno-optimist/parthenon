"""
Parthenon API routes.

POST /api/parthenon/stage/draft asks the Oracle to draft the missing parts of
a custom stage from the "Build your own stage" panel.
GET /api/parthenon/status tells the home page what this instance can run.
/api/parthenon/chronicle/<report_id>/film turns a finished Chronicle into a
narrated short film made with Grok (see services/chronicle_film.py).
/api/parthenon/gathering/<simulation_id>/portraits paints every citizen of a
gathering (see services/citizen_portraits.py).
/api/parthenon/gathering/<simulation_id>/stances reads where each citizen
stood, period by period, from what they said (the Agora's "who moved").
POST /api/parthenon/voice speaks an answer in the speaker's own voice (the
Symposium), and GET /api/parthenon/voice/<file> serves the recording.
POST /api/parthenon/gathering/<simulation_id>/speaker lets the visitor question
the one who had the floor on the steps, after the square has closed: they
answer from the record, in their own manner (see services/symposium_memory.py
and services/floor.py).
GET /api/parthenon/gathering/<id> tells where a gathering stands from any of
its ids (project, simulation or report).

The Chronicle routes of the report blueprint are served in the Scribe's voice
(see _serve_in_city_words below): Chronicles written before the Scribe learnt
the city's words are put into them on the way out, never on disk.
"""

import csv
import hashlib
import json
import os
import re
import threading
import time
from collections import OrderedDict
from urllib.parse import urlsplit

import httpx
from flask import current_app, jsonify, request, send_file, url_for
from openai import APIConnectionError, AuthenticationError, PermissionDeniedError

from . import parthenon_bp
from .. import public
from ..config import Config
from ..public.providers import remember_health
from ..models.project import ProjectManager
from ..services import chronicle_film, citizen_portraits, symposium_memory
from ..services.floor import speaker_for_file
from ..services.language_guard import (
    configured_record_language,
    ensure_language,
    ensure_language_many,
    foreign_script,
    record_language,
)
from ..services.report_agent import ReportManager, ReportStatus, chronicle_language, scribe_voice
from ..services.simulation_manager import SimulationManager
from ..services.simulation_runner import SimulationRunner
from ..services.stage_oracle import (
    OracleUnavailableError,
    StageOracle,
    StageValidationError,
)
from ..utils.llm_client import LLMResponseError
from ..utils.locale import get_locale, normalize_lang, t
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

    configured, problem, _health = _llm_status_and_health()
    return configured, problem


def _llm_status_and_health():
    """(configured, problem, the bridge's /health or None)."""

    configured = not Config.is_placeholder(Config.LLM_API_KEY)
    origin = _loopback_origin(Config.LLM_BASE_URL)
    if origin is None:
        return configured, None, None

    try:
        response = httpx.get(
            f'{origin}/health', timeout=BRIDGE_HEALTH_TIMEOUT_SECONDS, trust_env=False
        )
        health = response.json() if response.status_code == 200 else None
    except (httpx.HTTPError, ValueError):
        health = None
    # The public steps' feature checks reuse this answer for a while.
    remember_health(origin, health)

    if not isinstance(health, dict):
        return configured, (
            f'The LLM bridge at {origin} is not answering. '
            'Check that npm run dev is still running.'
        ), None
    if health.get('api_key_set') is False:
        return False, (
            'OPENROUTER_API_KEY is not set for the LLM bridge. Add it to .env and '
            'restart npm run dev, or switch PARTHENON_UPSTREAM to grok.'
        ), health
    if health.get('signed_in') is False:
        return False, (
            'The LLM bridge is not signed in to Grok. Run npm run grok:login, then reload.'
        ), health
    return configured, None, health


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
    reach a working LLM, or is None. recordLanguage is the language every
    gathering's record is written in when this instance fixes one
    (PARTHENON_RECORD_LANGUAGE: 'en' on the public steps), else None: each
    gathering then keeps the language it was begun in.
    """

    backend = _memory_backend()
    zep_key_valid, zep_problem = _zep_key_status()
    llm_configured, llm_problem, health = _llm_status_and_health()
    return jsonify({
        'success': True,
        'data': {
            'memoryBackend': backend,
            'zepConfigured': backend == 'local' or (
                backend == 'zep' and not Config.is_placeholder(Config.ZEP_API_KEY)
            ),
            'zepKeyValid': zep_key_valid,
            # On the public steps a problem is told in the city's words, never
            # with settings, files or commands.
            'zepProblem': public.public_problem(zep_problem),
            'llmConfigured': llm_configured,
            'llmProblem': public.public_problem(llm_problem),
            'upstream': (os.environ.get('PARTHENON_UPSTREAM') or 'grok').strip().lower(),
            'model': Config.LLM_MODEL_NAME,
            'recordLanguage': configured_record_language(),
            # public, provider, features {portraits, film, voice} and limits
            # (None off the public steps).
            **public.status_fields(health),
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
        mode = body.get('mode', 'fill')
        if mode == 'proposal':
            draft = StageOracle().propose(body.get('brief'), body.get('current'), body.get('sources', ''))
        elif mode == 'fill':
            draft = StageOracle().draft(body.get('stage'), body.get('fill'))
        else:
            raise StageValidationError('Choose a supported Oracle request mode: fill or proposal.')
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

    return jsonify({'success': True, 'data': draft_in_visitor_language(draft)})


def draft_in_visitor_language(draft):
    """The Oracle's draft in the language of the visitor who asked for it.

    The draft is a live answer: the visitor reads it and edits it on the
    stage, so it is checked for their language (the one the Oracle was told
    to write in), never rewritten into the record's. What they then submit is
    their own writing, kept as a question they wrote is kept; whatever writes
    the record from it writes in the record language. On a Chinese visitor's
    stage nothing is sent to the translator. The speakers' names are the
    visitor's own and are left as they are.
    """

    if not isinstance(draft, dict):
        return draft
    lang = get_locale()
    places = []  # (path, text): where each drafted text sits in the draft
    for key in ('title', 'question', 'happensNext'):
        places.append(((key,), draft.get(key)))
    for group, fields in (('speakers', ('words',)), ('audience', ('name', 'description'))):
        items = draft.get(group)
        for index, item in enumerate(items if isinstance(items, list) else []):
            if isinstance(item, dict):
                places.extend(((group, index, field), item.get(field)) for field in fields)
    if not any(foreign_script(text, lang) for _path, text in places):
        return draft
    checked = ensure_language_many(
        [text for _path, text in places], lang, context='a stage drafted for a gathering in ancient Athens'
    )
    draft = {**draft, 'speakers': [dict(item) if isinstance(item, dict) else item
                                   for item in draft.get('speakers') or []],
             'audience': [dict(item) if isinstance(item, dict) else item
                          for item in draft.get('audience') or []]}
    for (path, _text), text in zip(places, checked):
        if len(path) == 1:
            draft[path[0]] = text
        else:
            draft[path[0]][path[1]][path[2]] = text
    return draft


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
        # Filmed in the Chronicle's own language, whoever presses Film: there is
        # one film of a Chronicle, and every visitor sees it.
        chronicle_film.start_film(report, voice=voice, shots=shots, locale=chronicle_language(report))
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


# ============== Citizens' portraits ==============

def _force_option(what):
    """(force, None) from a POST body of {"force": true|false}, or (None, a 400 response)."""

    body = request.get_json(silent=True)
    if body is None:
        if request.get_data(cache=True):
            return None, _error(f'Send a JSON object with the {what} options.', 400)
        body = {}
    if not isinstance(body, dict):
        return None, _error(f'Send a JSON object with the {what} options.', 400)
    force = body.get('force')
    if force is None:
        force = False
    if not isinstance(force, bool):
        return None, _error('force must be true or false.', 400)
    return force, None


def _portrait_url(simulation_id, name):
    path = citizen_portraits.portrait_file_path(simulation_id, name)
    if path is None:
        return None
    # The version stamp keeps browsers from showing an earlier portrait of the citizen.
    version = os.stat(path).st_mtime_ns // 1_000_000
    return url_for(
        'parthenon.citizen_portrait_file', simulation_id=simulation_id, name=name, v=version
    )


@parthenon_bp.route('/gathering/<simulation_id>/portraits', methods=['POST'])
def start_citizen_portraits(simulation_id):
    """Paint every citizen of a gathering in the background.

    Request JSON (optional): {"force": true} repaints everyone.
    202: {"success": true, "data": {"status": "running", "simulation_id": "..."}}
    200: the same with status "completed" when the cast is already painted.
    Idempotent: a painting already running (or finished for the same cast) is
    left as it is unless force; a failed painting resumes where it stopped.
    400 bad body, 404 unknown gathering, 409 citizens not ready yet or a
    forced repaint while a painting runs.
    """

    force, failure = _force_option('painting')
    if failure:
        return failure

    try:
        manifest = citizen_portraits.start_portraits(simulation_id, force=force)
    except citizen_portraits.PortraitsNotFound as error:
        return _error(str(error), 404)
    except (citizen_portraits.PortraitsNotReady, citizen_portraits.PortraitsConflict) as error:
        return _error(str(error), 409)
    except OSError as error:
        logger.error(
            'Could not start the portraits of %s: type=%s', simulation_id, type(error).__name__
        )
        return _error('The painters could not start; check the server logs.', 500)

    status = manifest.get('status') or 'running'
    data = {'status': status, 'simulation_id': manifest.get('simulation_id')}
    return jsonify({'success': True, 'data': data}), 200 if status == 'completed' else 202


@parthenon_bp.route('/gathering/<simulation_id>/portraits', methods=['GET'])
def citizen_portraits_status(simulation_id):
    """The portraits manifest with a versioned URL for every finished portrait.

    data: {simulation_id, status: none|running|completed|failed, progress,
    error, created_at, updated_at, portraits: [{agent_id, name, entity_type,
    status: pending|painting|done|failed, url}]}
    """

    canonical = citizen_portraits.find_simulation(simulation_id)
    if canonical is None:
        return _error(citizen_portraits.NOT_FOUND_MESSAGE, 404)
    manifest = citizen_portraits.get_portraits(canonical)
    types = None
    portraits = []
    for item in manifest.get('portraits') or []:
        if not isinstance(item, dict):
            continue
        entity_type = item.get('entity_type')
        if not entity_type:
            # Painting may start before the gathering's configuration names every type.
            if types is None:
                types = citizen_portraits.entity_types(canonical)
            entity_type = types.get(item.get('agent_id'))
        name = item.get('file')
        done = item.get('status') == 'done' and isinstance(name, str)
        portraits.append({
            'agent_id': item.get('agent_id'),
            'name': item.get('name'),
            'entity_type': entity_type or None,
            'status': item.get('status'),
            'url': _portrait_url(canonical, name) if done else None,
        })
    data = {
        'simulation_id': canonical,
        'status': manifest.get('status'),
        'progress': manifest.get('progress'),
        'error': manifest.get('error'),
        'created_at': manifest.get('created_at'),
        'updated_at': manifest.get('updated_at'),
        'portraits': portraits,
    }
    return jsonify({'success': True, 'data': data})


@parthenon_bp.route('/gathering/<simulation_id>/portraits/<name>', methods=['GET'])
def citizen_portrait_file(simulation_id, name):
    """<agent_id>.jpg; a versioned URL (?v=) may be cached for good."""

    canonical = citizen_portraits.find_simulation(simulation_id)
    path = citizen_portraits.portrait_file_path(canonical, name) if canonical else None
    if path is None:
        return _error('Portrait not found.', 404)
    versioned = bool(request.args.get('v'))
    response = send_file(
        path, mimetype='image/jpeg', conditional=True, max_age=31536000 if versioned else 0
    )
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


# ============== Where the citizens stood ==============

STANCE_FIELDS = (
    'status', 'error', 'stale', 'created_at', 'updated_at', 'through_round',
    'minutes_per_round', 'lang', 'periods', 'citizens',
)


@parthenon_bp.route('/gathering/<simulation_id>/stances', methods=['POST'])
def start_citizen_stances(simulation_id):
    """Read where each citizen stood, period by period, in the background.

    Request JSON (optional): {"force": true} reads the record again.
    202: {"success": true, "data": {"status": "reading", "simulation_id": "..."}}
    200: the same with status "completed" when the record has not grown since
    the last reading. Idempotent: a reading already running is left alone.
    400 bad body, 404 unknown gathering, 409 nobody has spoken yet or a
    forced reading while one runs.
    """

    force, failure = _force_option('reading')
    if failure:
        return failure
    try:
        reading = citizen_portraits.start_stances(simulation_id, force=force)
    except citizen_portraits.PortraitsNotFound as error:
        return _error(str(error), 404)
    except (citizen_portraits.StancesNotReady, citizen_portraits.StancesConflict) as error:
        return _error(str(error), 409)
    except OSError as error:
        logger.error(
            'Could not start reading the stances of %s: type=%s', simulation_id, type(error).__name__
        )
        return _error('The record could not be read; check the server logs.', 500)

    status = reading.get('status') or 'reading'
    data = {'status': status, 'simulation_id': reading.get('simulation_id')}
    return jsonify({'success': True, 'data': data}), 200 if status == 'completed' else 202


@parthenon_bp.route('/gathering/<simulation_id>/stances', methods=['GET'])
def citizen_stances(simulation_id):
    """Where the citizens stood.

    data: {simulation_id, status: none|reading|completed|failed, error, stale,
    created_at, updated_at, through_round, minutes_per_round, periods:
    [{period, from_round, to_round}], citizens: [{agent_id, name, entity_type,
    stance (where they began), spoke, stance_history: [{period, from_round,
    to_round, stance}], final_stance, moved, turn}], lang}. Stances are supportive,
    opposing or neutral; stale means more was said after the reading. lang is
    the gathering's language, the one turns are written in: a turn stored in
    another language (by an older reader) comes back as "".
    """

    canonical = citizen_portraits.find_simulation(simulation_id)
    if canonical is None:
        return _error(citizen_portraits.NOT_FOUND_MESSAGE, 404)
    reading = citizen_portraits.get_stances(canonical)
    data = {'simulation_id': canonical, **{key: reading.get(key) for key in STANCE_FIELDS}}
    data['citizens'] = turns_in_language(data.get('citizens'), data.get('lang'))
    return jsonify({'success': True, 'data': data})


def turns_in_language(citizens, lang):
    """The ledger's citizens with every turn in lang, the gathering's language (new copies).

    A turn in another language altogether is already hidden by the reader;
    this catches the one that quotes a line in another script.
    """

    if not isinstance(citizens, list):
        return citizens
    turns = [item.get('turn') if isinstance(item, dict) else None for item in citizens]
    if not any(foreign_script(turn, lang) for turn in turns):
        return citizens
    checked = ensure_language_many(turns, lang, context='how a citizen of Athens changed their mind')
    return [
        {**item, 'turn': turn} if isinstance(item, dict) and turn != item.get('turn') else item
        for item, turn in zip(citizens, checked)
    ]


# ============== The one who had the floor ==============

SPEAKER_ERRORS = {
    'unreachable': ('api.speaker.unreachable', 503),
    'timed_out': ('api.speaker.unreachable', 503),
    'signed_out': ('api.speaker.signedOut', 503),
    'no_scribe': ('api.speaker.noScribe', 503),
    'silent': ('api.speaker.silent', 502),
    'failed': ('api.speaker.silent', 502),
}


def _speaker_error(key, status, **kwargs):
    return jsonify(symposium_memory.error_body(t(key, **kwargs))), status


def _text_field(body, key):
    value = body.get(key)
    return value if isinstance(value, str) and value.strip() else None


@parthenon_bp.route('/gathering/<simulation_id>/speaker', methods=['POST'])
def ask_the_speaker(simulation_id):
    """Question the one who had the floor on the steps; they answer from the record.

    Request JSON: {"question": "...", "history"?: [{"role": "user" |
    "assistant", "content": "..."}], "lang"?: "en" | "zh" | ..., "name"?,
    "file_name"?, "report_id"?}. The backend decides who answers, from the
    gathering's own first scroll; name and file_name only check that the page
    is current (a mismatch is a 404). report_id picks the Chronicle the
    visitor is reading when it belongs to this gathering.
    200: {"success": true, "data": {"answer", "from_memory": true, "lang",
    "speaker": {name, zh, file_name, agent_id, voice: "speaker", voice_id}}}.
    Every error body is {"success": false, "error": "<city words>",
    "from_memory": true}: 400 no question, too long or a bad history; 404 no
    such gathering, nobody had the floor, or not the one named; 502 no answer;
    503 unreachable, signed out or no Scribe; 500 anything else.
    """

    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return _speaker_error('api.speaker.needQuestion', 400)
    question = body.get('question')
    if not isinstance(question, str) or not question.strip():
        return _speaker_error('api.speaker.needQuestion', 400)
    if len(question) > symposium_memory.MAX_QUESTION_INPUT:
        return _speaker_error('api.memory.tooLong', 400)
    try:
        history = symposium_memory.clean_history(body.get('history'))
    except ValueError:
        return _speaker_error('api.memory.badHistory', 400)
    sent_name = _text_field(body, 'name')
    try:
        answer = symposium_memory.answer_as_speaker(
            simulation_id, question=question.strip(), history=history, lang=_text_field(body, 'lang'),
            name=sent_name, file_name=_text_field(body, 'file_name'),
            report_id=_text_field(body, 'report_id'),
        )
    except symposium_memory.GatheringNotFound:
        return _speaker_error('api.memory.notFound', 404)
    except symposium_memory.FloorNotFound:
        return _speaker_error('api.speaker.noFloor', 404)
    except symposium_memory.WrongSpeaker:
        return _speaker_error('api.speaker.wrongSpeaker', 404)
    except symposium_memory.RecordError as error:
        key, status = SPEAKER_ERRORS.get(error.code, ('api.speaker.failed', 500))
        return _speaker_error(key, status, name=_speaker_name(error.entry, sent_name))
    except Exception as error:  # noqa: BLE001 - never str(e) or a traceback
        logger.error('The speaker of %s could not answer: type=%s', simulation_id, type(error).__name__)
        try:
            entry = speaker_for_file(citizen_portraits.gathering_scroll_name(simulation_id))
        except Exception:  # noqa: BLE001 - only the name is missing then
            entry = None
        return _speaker_error('api.speaker.failed', 500, name=_speaker_name(entry, sent_name))
    # A live answer: in the language the visitor asked in (a quotation from a
    # record in another is translated).
    return jsonify({'success': True, 'data': {
        'answer': ensure_language(answer['answer'], answer['lang'], context='an answer at the Symposium'),
        'from_memory': True,
        'lang': answer['lang'],
        'speaker': answer['speaker'],
    }})


def _speaker_name(entry, sent_name):
    """The one who had the floor, named in the visitor's language."""

    if entry:
        return entry['zh'] if get_locale() == 'zh' else entry['name']
    return sent_name or ''


# ============== The citizens' voices ==============

VOICE_TEXT_FIELDS = ('voice', 'simulation_id', 'name', 'lang')


@parthenon_bp.route('/voice', methods=['POST'])
def speak_words():
    """Speak an answer in the speaker's voice (the Symposium).

    Request JSON: {"text": "...", "voice": "scribe" | "elder" | "official" |
    "common" | "machine" (or a role family, or "plain") | "speaker" (the one
    who had the floor: with simulation_id, the voice of the gathering's
    scroll's narrator clip, e.g. rex for the Apology, ara for When Sand
    Speaks; for a scroll the city does not know, the voice chosen as if none
    were named), "simulation_id",
    "agent_id" or "name" (the citizen speaking: their role and how their
    portrait presents them choose the voice when "voice" is left out, and a
    man's or a woman's voice either way), "lang": "en" | "zh" | ..., "part":
    0 (the default) .. parts - 1}.
    200: {"success": true, "data": {url, voice, voice_id, language, part,
    parts, cached, truncated}}; url is backend-relative. A long answer is
    spoken in parts so the first words come in seconds: play part 0, and ask
    for the next part while it plays. The same words in the same voice are
    recorded once.
    400 nothing to speak, too much, no such part or an unknown voice; 502
    the words could not be spoken; 503 no voice service, busy or signed out
    (the page can fall back to the browser's own voice).
    """

    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return _error('Send a JSON object with the words to speak.', 400)
    for key in VOICE_TEXT_FIELDS:
        if body.get(key) is not None and not isinstance(body.get(key), str):
            return _error(f'{key} must be text.', 400)
    agent_id = body.get('agent_id')
    if agent_id is not None and (isinstance(agent_id, bool) or not isinstance(agent_id, (int, str))):
        return _error('agent_id must be a number.', 400)
    part = body.get('part')
    if part is not None and (isinstance(part, bool) or not isinstance(part, int)):
        return _error('part must be a number.', 400)
    text = body.get('text')
    if (
        body.get('lang') is not None
        and isinstance(text, str)
        and len(text) <= citizen_portraits.MAX_VOICE_INPUT_CHARS
        and foreign_script(text, body['lang'])
    ):
        # The visitor hears the words in the language they read in.
        text = ensure_language(text, body['lang'], context='words spoken aloud at the Symposium')
    try:
        spoken = citizen_portraits.speak(
            text, voice=body.get('voice'), simulation_id=body.get('simulation_id'),
            agent_id=agent_id, name=body.get('name'), lang=body.get('lang'), part=part,
        )
    except citizen_portraits.VoiceValidationError as error:
        return _error(str(error), 400)
    except citizen_portraits.VoiceUnavailable as error:
        return _error(str(error), 503)
    except citizen_portraits.VoiceError as error:
        return _error(str(error), 502)
    except OSError as error:
        logger.error('Could not keep a recording: type=%s', type(error).__name__)
        return _error('The words could not be spoken; check the server logs.', 500)

    data = {
        'url': url_for('parthenon.voice_file', name=spoken['file']),
        **{key: spoken[key] for key in (
            'voice', 'voice_id', 'language', 'part', 'parts', 'cached', 'truncated'
        )},
    }
    return jsonify({'success': True, 'data': data})


@parthenon_bp.route('/voice/<name>', methods=['GET'])
def voice_file(name):
    """A recording, named by its content (so it may be cached for good), with Range support."""

    path = citizen_portraits.voice_file_path(name)
    if path is None:
        return _error('Voice not found.', 404)
    response = send_file(
        path, mimetype=citizen_portraits.voice_file_type(name), conditional=True, max_age=31536000
    )
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


# ============== Gatherings ==============

GATHERING_ID_PATTERN = re.compile(r'(proj|sim|report)_[A-Za-z0-9_-]{1,120}')
# Simulation statuses that mean a run was started at some point.
RAN_SIMULATION_STATUSES = {'running', 'stopping', 'paused', 'stopped', 'completed'}


def _project_simulations(project_id):
    """Every readable simulation of the project (a corrupt state.json is skipped)."""

    root = SimulationManager.SIMULATION_DATA_DIR
    try:
        names = os.listdir(root)
    except OSError:
        return []
    manager = SimulationManager()
    found = []
    for name in names:
        if (
            name.startswith('.')
            or not citizen_portraits.valid_simulation_id(name)
            or not os.path.isfile(os.path.join(root, name, 'state.json'))
        ):
            continue
        try:
            state = manager.get_simulation(name)
        except Exception as error:  # noqa: BLE001 - one corrupt state.json must not hide the rest
            logger.warning('Simulation %s could not be read: type=%s', name, type(error).__name__)
            continue
        if state is not None and state.project_id == project_id:
            found.append(state)
    return found


def _furthest_night(project_id):
    """(simulation, report_id, report_status) of the project's night that got furthest.

    A project resolves to the night with the highest act, and among those to
    the newest: a Chronicle already written is never hidden behind a later
    night that was prepared and then left, and nobody's abandoned gathering
    is opened (and painted) from a project link. (None, None, None) when the
    project has no simulation yet.
    """

    best = None
    for state in _project_simulations(project_id):
        report_id, report_status = _latest_report(state.simulation_id)
        runner_status, current_round = _run_progress(state.simulation_id)
        act = gathering_act(
            state.simulation_id, getattr(state.status, 'value', None),
            runner_status, current_round, report_status,
        )
        key = (act, state.created_at or '', state.simulation_id)
        if best is None or key > best[0]:
            best = (key, state, report_id, report_status)
    if best is None:
        return None, None, None
    return best[1], best[2], best[3]


def _latest_report(simulation_id):
    """(report_id, status) of the simulation's newest Chronicle, or (None, None).

    Reads only each Chronicle's meta.json, as the history shelf does.
    """

    root = ReportManager.REPORTS_DIR
    try:
        names = os.listdir(root)
    except OSError:
        return None, None
    latest = None
    for name in names:
        if not chronicle_film.valid_report_id(name):
            continue
        meta_path = os.path.join(root, name, 'meta.json')
        try:
            with open(meta_path, 'r', encoding='utf-8') as handle:
                meta = json.load(handle)
        except (OSError, ValueError):
            continue
        if not isinstance(meta, dict) or meta.get('simulation_id') != simulation_id:
            continue
        report_id = meta.get('report_id')
        if not chronicle_film.valid_report_id(report_id):
            continue
        key = (str(meta.get('created_at') or ''), report_id)
        if latest is None or key > latest[0]:
            latest = (key, report_id, meta.get('status'))
    if latest is None:
        return None, None
    status = latest[2] if isinstance(latest[2], str) else None
    return latest[1], status


def _run_progress(simulation_id):
    """(runner_status, current_round) of the simulation's run; (None, 0) when it never ran."""

    try:
        run_state = SimulationRunner.get_run_state(simulation_id)
    except Exception as error:  # noqa: BLE001 - an unreadable run state means no run to show
        logger.warning('Run state of %s could not be read: type=%s', simulation_id, type(error).__name__)
        return None, 0
    if run_state is None:
        return None, 0
    status = getattr(run_state.runner_status, 'value', run_state.runner_status)
    round_number = run_state.current_round if isinstance(run_state.current_round, int) else 0
    return (status if isinstance(status, str) else None), round_number


def gathering_act(simulation_id, simulation_status, runner_status, current_round, report_status):
    """The furthest act a gathering has reached (the Symposium, 5, is chosen by the visitor).

    1 before a simulation exists; 2 while it is prepared but never run; 3 once
    a run exists and no Chronicle stands (a failed Chronicle sends the visitor
    back to the Agora to commission another); 4 once a Chronicle exists, also
    while the Scribe is still writing it.
    """

    if not simulation_id and not report_status:
        return 1
    if report_status and report_status != ReportStatus.FAILED.value:
        return 4
    ran = (
        (runner_status is not None and runner_status != 'idle')
        or current_round > 0
        or simulation_status in RAN_SIMULATION_STATUSES
    )
    return 3 if ran or report_status else 2


@parthenon_bp.route('/gathering/<gathering_id>', methods=['GET'])
def resolve_gathering(gathering_id):
    """Where a gathering stands, from its project, simulation or report id.

    data: {project_id, simulation_id, report_id, act: 1..4, runner_status,
    report_status}. A project resolves to the night that got furthest (the
    newest of those), a simulation to its newest Chronicle; a report id
    resolves to that Chronicle.
    404 when nothing matches.
    """

    match = GATHERING_ID_PATTERN.fullmatch(gathering_id or '')
    if match is None:
        return _error(citizen_portraits.NOT_FOUND_MESSAGE, 404)
    kind = match.group(1)
    project_id = simulation_id = report_id = report_status = None
    simulation = None
    try:
        if kind == 'report':
            report = ReportManager.get_report(gathering_id)
            if report is None or not chronicle_film.valid_report_id(report.report_id):
                return _error(citizen_portraits.NOT_FOUND_MESSAGE, 404)
            report_id = report.report_id
            report_status = report.status.value
            simulation_id = report.simulation_id or None
            canonical = citizen_portraits.find_simulation(simulation_id)
            if canonical is not None:
                simulation_id = canonical
                simulation = SimulationManager().get_simulation(canonical)
        elif kind == 'sim':
            canonical = citizen_portraits.find_simulation(gathering_id)
            simulation = SimulationManager().get_simulation(canonical) if canonical else None
            if simulation is None:
                return _error(citizen_portraits.NOT_FOUND_MESSAGE, 404)
            simulation_id = canonical
            report_id, report_status = _latest_report(simulation_id)
        else:
            project = ProjectManager.get_project(gathering_id)
            if project is None:
                return _error(citizen_portraits.NOT_FOUND_MESSAGE, 404)
            project_id = project.project_id
            simulation, report_id, report_status = _furthest_night(project_id)
            if simulation is not None:
                simulation_id = simulation.simulation_id
        if simulation is not None and not project_id:
            project_id = simulation.project_id or None
    except Exception as error:  # noqa: BLE001 - a corrupt meta file
        logger.error('Gathering %s could not be resolved: type=%s', gathering_id, type(error).__name__)
        return _error('The gathering could not be read.', 500)

    runner_status, current_round = _run_progress(simulation_id) if simulation_id else (None, 0)
    simulation_status = getattr(simulation.status, 'value', None) if simulation is not None else None
    data = {
        'project_id': project_id,
        'simulation_id': simulation_id,
        'report_id': report_id,
        'act': gathering_act(
            simulation_id, simulation_status, runner_status, current_round, report_status
        ),
        'runner_status': runner_status,
        'report_status': report_status,
    }
    return jsonify({'success': True, 'data': data})


# ============== The Chronicle in the city's words ==============
#
# The Scribe now writes in the city's words (report_agent.scribe_voice runs
# over everything she hands back). Chronicles written before that are stored
# as they were written, "In the simulated month..." and all. The routes below
# read them, so their JSON goes through the same pass on the way out: every
# older Chronicle reads in the city's words wherever it is shown (the
# Chronicle, the Symposium, the shelf) and nothing on disk changes. For a
# Chronicle already in the city's words the pass changes nothing.

CITY_WORDS_ENDPOINTS = frozenset({
    'report.get_report',
    'report.get_report_by_simulation',
    'report.list_reports',
    'report.get_report_sections',
    'report.get_single_section',
    'report.get_agent_log',
    'simulation.get_simulation_history',
})
# Agent log entries whose details carry what the Scribe wrote.
SCRIBE_LOG_ACTIONS = frozenset({'planning_complete', 'section_content', 'section_complete'})
CITY_FACTS_CACHE_SIZE = 32
CHRONICLE_FACTS_CACHE_SIZE = 256
_BARE_HANDLE_NAME = re.compile(r'[a-z0-9]+(?:_[a-z0-9]+)*_\d+', re.I)

_city_facts_lock = threading.Lock()
_city_facts_cache = OrderedDict()
_chronicle_facts_cache = OrderedDict()


def _remember(cache, key, value, size):
    with _city_facts_lock:
        cache[key] = value
        cache.move_to_end(key)
        while len(cache) > size:
            cache.popitem(last=False)


def _recall(cache, key):
    with _city_facts_lock:
        return cache.get(key)


def _file_stamp(path):
    try:
        info = os.stat(path)
    except OSError:
        return None
    return info.st_mtime_ns, info.st_size


def city_facts(simulation_id):
    """(roster, time_unit) of a gathering, as the Scribe reads them.

    roster maps citizen handles (lower case, with and without their number)
    to names; time_unit is "hour" or "day" when one step of the argument is
    that long. Read from the gathering's folder, never created; cached until
    those files change. ({}, None) for an unknown gathering.
    """

    canonical = citizen_portraits.find_simulation(simulation_id)
    if canonical is None:
        return {}, None
    folder = os.path.join(SimulationManager.SIMULATION_DATA_DIR, canonical)
    names = ('simulation_config.json', 'reddit_profiles.json', 'twitter_profiles.csv')
    stamp = tuple(_file_stamp(os.path.join(folder, name)) for name in names)
    cached = _recall(_city_facts_cache, canonical)
    if cached is not None and cached[0] == stamp:
        return cached[1], cached[2]

    time_unit = None
    try:
        with open(os.path.join(folder, names[0]), 'r', encoding='utf-8') as handle:
            minutes = (json.load(handle).get('time_config') or {}).get('minutes_per_round')
        time_unit = {60: 'hour', 1440: 'day'}.get(int(minutes)) if minutes else None
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    profiles = []
    try:
        with open(os.path.join(folder, names[1]), 'r', encoding='utf-8') as handle:
            data = json.load(handle)
        profiles.extend(item for item in data if isinstance(item, dict))
    except (OSError, ValueError, TypeError):
        pass
    try:
        with open(os.path.join(folder, names[2]), 'r', encoding='utf-8', newline='') as handle:
            profiles.extend(csv.DictReader(handle))
    except (OSError, ValueError, csv.Error):
        pass
    roster = {}
    for profile in profiles:
        handle = str(profile.get('username') or '').strip().lstrip('@')
        name = str(profile.get('name') or '').strip()
        if not handle or not name or _BARE_HANDLE_NAME.fullmatch(name):
            continue
        roster.setdefault(handle.lower(), name)
        roster.setdefault(re.sub(r'_\d+$', '', handle).lower(), name)
    _remember(_city_facts_cache, canonical, (stamp, roster, time_unit), CITY_FACTS_CACHE_SIZE)
    return roster, time_unit


def _chronicle_facts(report_id):
    """(simulation_id, question, language) of a Chronicle from its meta.json, or (None, '', None).

    language is the one the Chronicle is written in: stored with it, else
    (for one begun before it was stored) its gathering's record language.
    """

    if not chronicle_film.valid_report_id(report_id):
        return None, '', None
    path = os.path.join(ReportManager.REPORTS_DIR, report_id, 'meta.json')
    # Cached until meta.json changes: a mended Chronicle may be given its language.
    stamp = _file_stamp(path)
    cached = _recall(_chronicle_facts_cache, report_id)
    if cached is not None and cached[0] == stamp:
        return cached[1]
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            meta = json.load(handle)
    except (OSError, ValueError):
        return None, '', None
    if not isinstance(meta, dict):
        return None, '', None
    simulation_id = meta.get('simulation_id') if isinstance(meta.get('simulation_id'), str) else None
    question = meta.get('simulation_requirement')
    question = question if isinstance(question, str) else ''
    language = normalize_lang(meta.get('language'), default=None) or record_language(
        simulation_id=simulation_id, requirement=question or None,
    )
    facts = (simulation_id, question, language)
    _remember(_chronicle_facts_cache, report_id, (stamp, facts), CHRONICLE_FACTS_CACHE_SIZE)
    return facts


class _CityWords:
    """scribe_voice() with one gathering's roster, clock and question, in its Chronicle's language.

    The language is the Chronicle's, told, never guessed from the text: an
    English chapter quoting a Chinese answer must not be given Chinese words.
    """

    def __init__(self, simulation_id, question, lang=None):
        self.roster, self.time_unit = city_facts(simulation_id) if simulation_id else ({}, None)
        self.question = question if isinstance(question, str) else ''
        self.lang = normalize_lang(lang, default=None) or record_language(
            simulation_id=simulation_id, requirement=self.question or None,
        )
        self.rewrites = 0

    def __call__(self, text):
        if not isinstance(text, str) or not text.strip():
            return text
        voiced, notes = scribe_voice(
            text, roster=self.roster, time_unit=self.time_unit, question=self.question, lang=self.lang,
        )
        self.rewrites += sum(1 for note in notes if note.get('kind') == 'rewrote')
        return voiced


def _outline_in_city_words(outline, words):
    if not isinstance(outline, dict):
        return outline
    outline = dict(outline)
    for key in ('title', 'summary'):
        outline[key] = words(outline.get(key))
    sections = outline.get('sections')
    if isinstance(sections, list):
        outline['sections'] = [
            {**section, 'title': words(section.get('title')), 'content': words(section.get('content'))}
            if isinstance(section, dict) else section
            for section in sections
        ]
    return outline


def _record_in_city_words(record):
    """A report's to_dict() in the city's words."""

    if not isinstance(record, dict):
        return record, 0
    # The report routes answer with the Chronicle's language (report._chronicle_record).
    words = _CityWords(
        record.get('simulation_id'), record.get('simulation_requirement'), record.get('language'),
    )
    record = dict(record)
    outline = record.get('outline')
    markdown = record.get('markdown_content')
    if 'outline' in record:
        record['outline'] = _outline_in_city_words(outline, words)
    if isinstance(markdown, str):
        # The whole Chronicle opens with her summary as a quotation (> ...), which
        # the pass would keep as a citizen's words: it is hers, so it takes the
        # summary as voiced above.
        before = outline.get('summary') if isinstance(outline, dict) else None
        after = record['outline'].get('summary') if isinstance(record.get('outline'), dict) else None
        if isinstance(before, str) and isinstance(after, str) and before.strip() and before != after:
            markdown = markdown.replace(f'> {before}', f'> {after}', 1)
        record['markdown_content'] = words(markdown)
    return record, words.rewrites


def _log_in_city_words(entry, words):
    if not isinstance(entry, dict):
        return entry
    entry = dict(entry)
    if isinstance(entry.get('section_title'), str):
        entry['section_title'] = words(entry['section_title'])
    details = entry.get('details')
    if entry.get('action') in SCRIBE_LOG_ACTIONS and isinstance(details, dict):
        details = dict(details)
        if 'outline' in details:
            details['outline'] = _outline_in_city_words(details.get('outline'), words)
        if 'content' in details:
            details['content'] = words(details.get('content'))
        entry['details'] = details
    return entry


def chronicle_in_city_words(endpoint, view_args, payload):
    """The JSON body of a Chronicle route with what the Scribe wrote in the city's words.

    Returns (payload, rewrites); the payload is a new object, the one given is
    left as it was.
    """

    if not isinstance(payload, dict) or payload.get('success') is not True:
        return payload, 0
    data = payload.get('data')
    rewrites = 0
    if endpoint in ('report.get_report', 'report.get_report_by_simulation'):
        data, rewrites = _record_in_city_words(data)
    elif endpoint == 'report.list_reports' and isinstance(data, list):
        voiced = []
        for record in data:
            record, count = _record_in_city_words(record)
            voiced.append(record)
            rewrites += count
        data = voiced
    elif endpoint == 'simulation.get_simulation_history' and isinstance(data, list):
        voiced = []
        for item in data:
            if isinstance(item, dict) and isinstance(item.get('report_title'), str):
                language = _chronicle_facts(item.get('report_id'))[2] if item.get('report_id') else None
                words = _CityWords(item.get('simulation_id'), item.get('simulation_requirement'), language)
                item = {**item, 'report_title': words(item['report_title'])}
                rewrites += words.rewrites
            voiced.append(item)
        data = voiced
    elif endpoint in ('report.get_report_sections', 'report.get_single_section', 'report.get_agent_log'):
        if not isinstance(data, dict):
            return payload, 0
        words = _CityWords(*_chronicle_facts((view_args or {}).get('report_id')))
        data = dict(data)
        if endpoint == 'report.get_report_sections' and isinstance(data.get('sections'), list):
            data['sections'] = [
                {**section, 'content': words(section.get('content'))}
                if isinstance(section, dict) else section
                for section in data['sections']
            ]
        elif endpoint == 'report.get_single_section':
            data['content'] = words(data.get('content'))
        elif endpoint == 'report.get_agent_log' and isinstance(data.get('logs'), list):
            data['logs'] = [_log_in_city_words(entry, words) for entry in data['logs']]
        rewrites = words.rewrites
    else:
        return payload, 0
    return {**payload, 'data': data}, rewrites


@parthenon_bp.after_app_request
def _serve_in_city_words(response):
    """Put the Chronicle routes' JSON in the city's words on the way out."""

    endpoint = request.endpoint
    if (
        endpoint not in CITY_WORDS_ENDPOINTS
        or request.method != 'GET'
        or response.status_code != 200
        or response.direct_passthrough
        or not response.is_json
    ):
        return response
    try:
        payload = response.get_json(silent=True)
        voiced, rewrites = chronicle_in_city_words(endpoint, request.view_args, payload)
        if rewrites:
            response.set_data(current_app.json.dumps(voiced))
    except Exception as error:  # noqa: BLE001 - the Chronicle is never lost to its proofreading
        logger.warning(
            'The Chronicle could not be put in the city\'s words on %s: type=%s',
            endpoint, type(error).__name__,
        )
    return response
