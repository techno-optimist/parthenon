"""
The public steps: Parthenon served to anyone at projectforty2.ai/parthenon.

PARTHENON_PUBLIC=1 turns this on (create_app calls configure()). Without it
nothing here runs, and the owner's own machine behaves as it always has.

In public mode:
- every route is classified (guard.ROUTES) and enforced: reads are open,
  questions are counted per visitor per hour, control actions need the owner
  key of that gathering (X-Parthenon-Owner) or the keepers' key
  (X-Parthenon-Admin), and debug routes are closed;
- beginning a gathering (POST /api/graph/ontology/generate) is counted per
  day, site-wide and per visitor, and hands back data.owner_token at once
  with data.task_id: the scroll is read, and its Web built, in that task
  (the page's own POST /api/graph/build answers with the same task while the
  scroll is read; GET project shows it as hearing_task_id); only the key's
  sha256 is kept, on the project record, and its simulations and Chronicles
  are owned through the lineage; a scroll that cannot be read gives the
  visitor's gathering back;
- a question (the symposium class: interviews, the Scribe's chat, the one
  who had the floor, the Oracle's draft) is answered 202 at once with a
  ticket, and worked in a thread of its own within PARTHENON_QUESTION_SECONDS
  (240); the page reads GET /api/parthenon/ticket/<id> until the answer is
  there, exactly as the route would have given it (tickets.py). With
  PARTHENON_QUESTION_TICKETS=0 a question is answered directly instead, and
  waits on the model for at most PARTHENON_REQUEST_SECONDS (85; the edge
  gives up at 100). Either way a question that runs out of time is answered
  503 slow_down in the city's words and given back (utils/time_budget.py);
- PARTHENON_INVITE_CODE (one or more words, comma separated) asks for an
  invite, in X-Parthenon-Invite or ?invite=, of whatever makes something
  new: beginning a gathering, every question, the Oracle's draft, the
  voices, and starting portraits, a film or a stance reading. Reading never
  needs it; the keepers pass without it; wrong words are limited per visitor
  per hour (guard.py). POST /api/parthenon/invite checks a word and does
  nothing else. The status says invite_required;
- a square left open after its run holds a seat of
  PARTHENON_CONCURRENT_RUNS; idle ones close to make room for a new run, and
  after PARTHENON_IDLE_ENV_MINUTES (20) unused (public/envs.py);
- a browser's own Accept-Language ('en-US,en;q=0.9') is read as 'en' or
  'zh', and an error a view wrote in the other language is put in the
  city's words, in a refusal and in the notes of an answer that succeeded
  (a task's or a run's error; a Chinese progress note for an English
  visitor goes); the status says which language the records are written in
  (recordLanguage, PARTHENON_RECORD_LANGUAGE);
- the mend (/api/parthenon/mend, api/mend.py) is the keepers' alone;
- the crowd, the run length, the concurrent runs, the scroll and the upload
  are capped; the counters live in <PARTHENON_DATA_DIR>/parthenon_public.sqlite3;
- the shelf shows the featured gatherings and those the visitor names in
  X-Parthenon-Owned; the keepers feature and unfeature with
  POST /api/parthenon/featured;
- portraits, film and server voices are offered only when this server's
  provider can make them;
- a stop (a deploy) cancels the preparations' queued work and does not wait
  for pool workers (utils/pools.py); a preparation it cut short reads failed,
  in the city's words, from the next start, and the owner's page prepares it
  again; a second summons while one is at work follows that same task, and
  the preparation's status by the gathering alone shows the task at work;
- no stack trace, server path or setting leaves in a response.

The refusals have one shape: {success: false, error: <the city's words, en
or zh>, code: city_full | come_back_tomorrow | slow_down | too_long |
not_yours | not_on_public_steps | invite_needed | ticket_lost,
retry_after_seconds?}.
"""

import logging
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional

from flask import Blueprint, current_app, g, has_request_context, jsonify, request

from . import envs, lineage, tickets
from .guard import (
    PublicGuard, report_on_shelf, running_runs, shelf_ids, simulation_on_shelf,
)
from .providers import features_of, provider_of
from .settings import PublicSettings, load_settings
from .store import PublicStore, day_window
from .words import TOO_LONG, refusal, words
from ..utils import pools


logger = logging.getLogger('mirofish.public')

__all__ = [
    'PublicSettings', 'configure', 'crowd_cap', 'give_back_later', 'is_public', 'load_settings',
    'new_owner_hash', 'report_on_shelf', 'scroll_refusal', 'shelf_ids',
    'simulation_on_shelf', 'status_fields', 'cap_entities',
]


@dataclass
class PublicState:
    settings: PublicSettings
    store: PublicStore
    guard: PublicGuard

    @property
    def tickets(self):
        """The questions' tickets (tickets.TicketDesk)."""

        return self.guard.tickets


def _state() -> Optional[PublicState]:
    if not has_request_context():
        return None
    return current_app.extensions.get('parthenon_public')


def is_public() -> bool:
    return _state() is not None


# ---------------------------------------------------------------- the keepers' featured list

featured_bp = Blueprint('public', __name__)


@featured_bp.route('/featured', methods=['GET'])
def featured_list():
    state = _state()
    return jsonify({'success': True, 'data': {
        'featured': state.store.featured_ids(state.settings.featured),
    }})


@featured_bp.route('/featured', methods=['POST'])
def set_featured():
    """{id, featured: true|false}; X-Parthenon-Admin (the guard checks it)."""

    state = _state()
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({'success': False, 'error': 'Send {"id": "...", "featured": true}.'}), 400
    gathering_id = body.get('id')
    featured = body.get('featured', True)
    if not lineage.valid_id(gathering_id) or not isinstance(featured, bool):
        return jsonify({'success': False, 'error': 'Send {"id": "...", "featured": true}.'}), 400
    # The shelf goes by project: a crowd or a Chronicle features its whole gathering.
    project_id = lineage.project_of(gathering_id)
    if project_id is None:
        return refusal(404, 'notFound')
    state.store.set_featured(project_id, featured)
    return jsonify({'success': True, 'data': {
        'id': project_id,
        'featured': featured,
        'all': state.store.featured_ids(state.settings.featured),
    }})


# ---------------------------------------------------------------- questions as tickets

@featured_bp.route('/ticket/<ticket_id>', methods=['GET'])
def ticket_status(ticket_id):
    """{status: thinking | done | failed, result, http_status, error, code, ...} (tickets.py)."""

    return tickets.ticket_response(_state().tickets, ticket_id)


# ---------------------------------------------------------------- the invite

@featured_bp.route('/invite', methods=['POST'])
def check_invite():
    """Whether the word in X-Parthenon-Invite (or ?invite=) opens speaking; the guard has checked it.

    200 {success: true, data: {valid: true, invite_required}}; a missing or
    wrong word is 403 invite_needed, and too many wrong ones 429 slow_down.
    """

    state = _state()
    return jsonify({'success': True, 'data': {
        'valid': True,
        'invite_required': state.settings.invite_required,
    }})


# ---------------------------------------------------------------- set up

def configure(app, settings: Optional[PublicSettings] = None) -> Optional[PublicState]:
    """Turn public mode on for this app when PARTHENON_PUBLIC=1; returns its state or None."""

    settings = settings or load_settings()
    if not settings.public:
        return None
    store = PublicStore(settings.db_path)
    guard = PublicGuard(settings, store)
    state = PublicState(settings, store, guard)
    app.extensions['parthenon_public'] = state
    app.config['MAX_CONTENT_LENGTH'] = min(
        app.config.get('MAX_CONTENT_LENGTH') or settings.max_upload_bytes, settings.max_upload_bytes
    )
    app.config['DEBUG'] = False
    app.config['PROPAGATE_EXCEPTIONS'] = False
    app.register_blueprint(featured_bp, url_prefix='/api/parthenon')
    app.before_request(guard.before_request)
    app.after_request(guard.after_request)
    app.teardown_request(guard.teardown_request)
    app.register_error_handler(Exception, guard.handle_error)
    envs.start_reaper(settings.idle_env_minutes)
    # A stop no longer waits on queued preparations or pool workers (utils/pools.py).
    pools.enable()
    return state


# ---------------------------------------------------------------- hooks the routes call

def new_owner_hash() -> Optional[str]:
    """For a gathering about to be made: the hash to keep, with its key kept for the response.

    None on the owner's own machine (no key is made or handed out).
    """

    if _state() is None:
        return None
    token = lineage.new_token()
    g.parthenon_owner_token = token
    return lineage.token_hash(token)


def crowd_cap() -> Optional[int]:
    """How many citizens a new crowd may have here, or None for no cap."""

    state = _state()
    if state is None or getattr(g, 'parthenon_admin', False):
        return None
    return state.settings.max_citizens


def cap_entities(filtered, cap: Optional[int]):
    """Keep at most `cap` entities of a FilteredEntities: the best connected, in their order."""

    if not cap or cap < 1 or len(filtered.entities) <= cap:
        return filtered
    ranked = sorted(
        range(len(filtered.entities)),
        key=lambda index: (-len(filtered.entities[index].related_edges or []), index),
    )
    keep = sorted(ranked[:cap])
    filtered.entities = [filtered.entities[index] for index in keep]
    filtered.filtered_count = len(filtered.entities)
    filtered.entity_types = {
        entity.get_entity_type() for entity in filtered.entities if entity.get_entity_type()
    }
    return filtered


def scroll_refusal(texts: Iterable[str]):
    """A too_long refusal when the scroll's text is past PARTHENON_MAX_SCROLL_CHARS, else None."""

    state = _state()
    if state is None:
        return None
    limit = state.settings.max_scroll_chars
    if sum(len(text or '') for text in texts) > limit:
        return refusal(413, 'scrollTooLong', TOO_LONG, max=limit)
    return None


def status_fields(health: Optional[dict]) -> Dict[str, Any]:
    """public, provider, features and limits for GET /api/parthenon/status."""

    state = _state()
    public = state is not None
    fields: Dict[str, Any] = {
        'public': public,
        'provider': provider_of(health, public=public),
        'features': features_of(health),
        # Whether speaking asks for the invite word (never off the public steps).
        'invite_required': bool(public and state.settings.invite_required),
        'limits': None,
    }
    if not public:
        return fields
    settings, store = state.settings, state.store
    try:
        from .guard import visitor_key

        day = day_window()
        used_today = store.count('gatherings', '*', day)
        used_visitor = store.count('visitor_gatherings', visitor_key(settings, store), day)
        # Seats taken: runs arguing now, and open squares still in use (idle
        # ones close to make room for a new run).
        running = running_runs() + envs.busy_environments()
        environments_open = len(envs.open_environments())
    except Exception:  # noqa: BLE001 - the counters are advisory here
        used_today = used_visitor = running = environments_open = 0
    fields['limits'] = {
        'daily_gatherings': settings.daily_gatherings,
        'per_visitor': settings.per_visitor,
        'max_citizens': settings.max_citizens,
        'max_run': settings.max_run,
        'max_run_hours': settings.max_run_rounds,
        'today_left': max(settings.daily_gatherings - used_today, 0),
        'visitor_left': max(min(settings.per_visitor - used_visitor, settings.daily_gatherings - used_today), 0),
        'running': running,
        'environments_open': environments_open,
        'concurrent_runs': settings.concurrent_runs,
        'questions_per_hour': settings.questions_per_hour,
        'max_scroll_chars': settings.max_scroll_chars,
        # A question answered with a ticket is worked for at most this long.
        'question_tickets': settings.question_tickets,
        'question_seconds': (
            settings.question_seconds if settings.question_tickets else settings.request_seconds
        ),
    }
    return fields


def give_back_later():
    """A function that gives back what this request was counted, for work that fails after the answer.

    (The Hearing reads the scroll after answering; if it cannot, the visitor's
    gathering for the day is given back.) A no-op off the public steps.
    """

    state = _state()
    taken = list(getattr(g, 'parthenon_taken', None) or []) if state is not None else []
    if not taken:
        return lambda: None
    store = state.store

    def give_back():
        try:
            store.give_back(taken)
        except Exception as error:  # noqa: BLE001 - a lost refund only costs one count
            logger.warning('Could not give back a count: type=%s', type(error).__name__)

    return give_back


def public_problem(problem: Optional[str]) -> Optional[str]:
    """A setup problem as a visitor may read it (no settings, files or commands)."""

    if problem is None or _state() is None:
        return problem
    return words('llmAway')
