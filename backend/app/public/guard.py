"""
Who may do what on the public steps.

Every Flask endpoint is in ROUTES with one class:

- read: anyone with the link (GETs, and the POSTs that only read a status).
- shelf: a read whose list is cut to the featured gatherings and the ones the
  visitor names in X-Parthenon-Owned (see shelf_ids()).
- create: begins a gathering; counted against the daily limits, and hands
  back the owner key.
- symposium: a question put to the city (the Symposium, the Scribe, the one
  who had the floor, the Oracle); open, counted per visitor per hour, and
  answered 202 with a ticket that is worked in a thread (see tickets.py).
- voice: a spoken answer; only when this server has voices, counted per hour.
- invite: checks an invite word, and does nothing else.
- owner: steers one gathering; needs X-Parthenon-Owner (the key handed back
  when it was begun) or X-Parthenon-Admin.
- admin: X-Parthenon-Admin only.
- disabled: not offered in public (debug tools, script downloads).

An endpoint missing from ROUTES is disabled, so a new route is closed in
public until someone classifies it.

The invite (PARTHENON_INVITE_CODE, one or more words separated by commas):
when it is set, whatever makes something new asks for one of its words in
X-Parthenon-Invite (or ?invite=): beginning a gathering, every question, the
Oracle's draft, the voices, and starting portraits, a film or a stance
reading (a guest asking for what is already painted or read is told so
without one). Reading never asks for it, and the keepers pass without it. A
missing word is 403 invite_needed; a wrong one is too, and counts: after
PARTHENON_INVITE_TRIES_PER_HOUR (10) wrong words in an hour a visitor gets
429 slow_down, whatever word comes next, until the hour turns.
"""

import hashlib
import hmac
import ipaddress
import json
import logging
import re
import threading
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from flask import current_app, g, jsonify, request
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge

from ..utils import time_budget
from . import envs, lineage, tickets
from .providers import current_features
from .settings import PublicSettings, invite_word
from .store import (
    PublicStore, day_window, hour_window, seconds_to_next_day, seconds_to_next_hour,
)
from .words import (
    CITY_FULL, COME_BACK_TOMORROW, INVITE_NEEDED, NOT_ON_PUBLIC_STEPS, NOT_YOURS, SLOW_DOWN,
    TOO_LONG, has_chinese, in_other_language, refusal, request_language, settle_request_language, words,
)


logger = logging.getLogger('mirofish.public')

READ = 'read'
SHELF = 'shelf'
CREATE = 'create'
SYMPOSIUM = 'symposium'
VOICE = 'voice'
OWNER = 'owner'
ADMIN = 'admin'
INVITE = 'invite'
DISABLED = 'disabled'

OWNER_HEADER = 'X-Parthenon-Owner'
ADMIN_HEADER = 'X-Parthenon-Admin'
OWNED_HEADER = 'X-Parthenon-Owned'
INVITE_HEADER = 'X-Parthenon-Invite'
INVITE_QUERY = 'invite'

# The largest body a question may come in (history included), and a question itself.
MAX_SYMPOSIUM_BODY = 128 * 1024
MAX_QUESTION_CHARS = 4000
MAX_INTERVIEWS = 40
MAX_REQUIREMENT_CHARS = 4000
MAX_SCROLL_FILES = 5
# A square that is full: try again after this long.
CITY_FULL_RETRY_SECONDS = 300
# A question that ran out of time: ask again after this long.
TOOK_TOO_LONG_RETRY_SECONDS = 60
# Starts are taken one at a time (the count of runs, then the launch).
START_LOCK_SECONDS = 30
# Build and prepare knobs a visitor may not turn past these.
CHUNK_SIZE_RANGE = (300, 2000)
CHUNK_OVERLAP_RANGE = (0, 200)
MAX_PARALLEL_PROFILES = 5


@dataclass(frozen=True)
class Rule:
    kind: str
    # Where the gathering's id is: ('view', name) or ('json', name), first found wins.
    target: Tuple[Tuple[str, str], ...] = ()
    feature: Optional[str] = None
    extra: Optional[str] = None
    # An owner route that makes something new asks for the invite too.
    invite: bool = False


def _owner(*target, feature=None, extra=None, invite=False):
    return Rule(OWNER, tuple(target), feature, extra, invite)


VIEW_PROJECT = ('view', 'project_id')
VIEW_SIMULATION = ('view', 'simulation_id')
VIEW_REPORT = ('view', 'report_id')
VIEW_GRAPH = ('view', 'graph_id')
JSON_PROJECT = ('json', 'project_id')
JSON_SIMULATION = ('json', 'simulation_id')

ROUTES: Dict[str, Rule] = {
    # The app
    'health': Rule(READ),
    'static': Rule(READ),
    # Graph (the Hearing)
    'graph.generate_ontology': Rule(CREATE),
    'graph.build_graph': _owner(JSON_PROJECT, extra='build'),
    'graph.get_graph_data': Rule(READ),
    'graph.delete_graph': _owner(VIEW_GRAPH),
    'graph.get_project': Rule(READ),
    'graph.delete_project': _owner(VIEW_PROJECT),
    'graph.reset_project': _owner(VIEW_PROJECT),
    'graph.list_projects': Rule(SHELF),
    'graph.get_task': Rule(READ),
    'graph.list_tasks': Rule(ADMIN),
    # Simulation (the Gathering, the Agora)
    'simulation.get_graph_entities': Rule(READ),
    'simulation.get_entity_detail': Rule(READ),
    'simulation.get_entities_by_type': Rule(READ),
    'simulation.create_simulation': _owner(JSON_PROJECT, extra='create_simulation'),
    'simulation.prepare_simulation': _owner(JSON_SIMULATION, extra='prepare'),
    'simulation.get_prepare_status': Rule(READ),
    'simulation.get_simulation': Rule(READ),
    'simulation.list_simulations': Rule(SHELF),
    'simulation.get_simulation_history': Rule(SHELF),
    'simulation.get_simulation_profiles': Rule(READ),
    'simulation.get_simulation_profiles_realtime': Rule(READ),
    'simulation.get_simulation_config_realtime': Rule(READ),
    'simulation.get_simulation_config': Rule(READ),
    'simulation.download_simulation_config': Rule(READ),
    'simulation.download_simulation_script': Rule(DISABLED),
    'simulation.generate_profiles': Rule(ADMIN),
    'simulation.start_simulation': _owner(JSON_SIMULATION, extra='start'),
    'simulation.stop_simulation': _owner(JSON_SIMULATION),
    'simulation.get_run_status': Rule(READ),
    'simulation.get_run_status_detail': Rule(READ),
    'simulation.get_simulation_actions': Rule(READ),
    'simulation.get_simulation_timeline': Rule(READ),
    'simulation.get_agent_stats': Rule(READ),
    'simulation.get_simulation_posts': Rule(READ),
    'simulation.get_simulation_comments': Rule(READ),
    'simulation.interview_agent': Rule(SYMPOSIUM),
    'simulation.interview_agents_batch': Rule(SYMPOSIUM),
    'simulation.interview_all_agents': Rule(SYMPOSIUM),
    'simulation.get_interview_history': Rule(READ),
    'simulation.get_env_status': Rule(READ),
    'simulation.close_simulation_env': _owner(JSON_SIMULATION),
    # Report (the Chronicle, the Scribe)
    'report.generate_report': _owner(JSON_SIMULATION),
    'report.get_generate_status': Rule(READ),
    'report.get_report': Rule(READ),
    'report.get_report_by_simulation': Rule(READ),
    'report.list_reports': Rule(SHELF),
    'report.download_report': Rule(READ),
    'report.delete_report': _owner(VIEW_REPORT),
    'report.chat_with_report_agent': Rule(SYMPOSIUM),
    'report.get_report_progress': Rule(READ),
    'report.get_report_sections': Rule(READ),
    'report.get_single_section': Rule(READ),
    'report.check_report_status': Rule(READ),
    'report.get_agent_log': Rule(READ),
    'report.stream_agent_log': Rule(READ),
    'report.get_console_log': Rule(READ),
    'report.stream_console_log': Rule(READ),
    'report.search_graph_tool': Rule(DISABLED),
    'report.get_graph_statistics_tool': Rule(DISABLED),
    # Parthenon
    'parthenon.instance_status': Rule(READ),
    'parthenon.draft_stage': Rule(SYMPOSIUM),
    'parthenon.start_chronicle_film': _owner(VIEW_REPORT, feature='film', invite=True),
    'parthenon.chronicle_film_status': Rule(READ),
    'parthenon.chronicle_film_file': Rule(READ),
    'parthenon.start_citizen_portraits': _owner(
        VIEW_SIMULATION, feature='portraits', extra='portraits', invite=True,
    ),
    'parthenon.citizen_portraits_status': Rule(READ),
    'parthenon.citizen_portrait_file': Rule(READ),
    'parthenon.start_citizen_stances': _owner(VIEW_SIMULATION, extra='stances', invite=True),
    'parthenon.citizen_stances': Rule(READ),
    'parthenon.ask_the_speaker': Rule(SYMPOSIUM),
    'parthenon.speak_words': Rule(VOICE),
    'parthenon.voice_file': Rule(READ),
    'parthenon.resolve_gathering': Rule(READ),
    # The mend (api/mend.py): old records put in their record language
    'mend.scan_records': Rule(ADMIN),
    'mend.mend_records': Rule(ADMIN),
    # Added by app/public
    'public.featured_list': Rule(READ),
    'public.set_featured': Rule(ADMIN),
    'public.ticket_status': Rule(READ),
    'public.check_invite': Rule(INVITE),
    'site.healthz': Rule(READ),
    'site.index': Rule(READ),
    'site.page': Rule(READ),
}

# The kind of id each view argument holds.
VIEW_ARG_KINDS = {
    'project_id': 'proj',
    'simulation_id': 'sim',
    'report_id': 'report',
    'gathering_id': None,
}
FREE_TEXT_FIELDS = ('question', 'message', 'prompt')

_start_lock = threading.Lock()


def rule_for(endpoint: Optional[str]) -> Rule:
    return ROUTES.get(endpoint or '', Rule(DISABLED))


# ------------------------------------------------------------------ who is asking

def _ip(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    candidate = value.strip().strip('"').strip('[]')
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return None


def client_ip(settings: PublicSettings) -> str:
    """CF-Connecting-IP, then the first X-Forwarded-For (only with PARTHENON_TRUST_PROXY=1), else the peer."""

    if settings.trust_proxy:
        found = _ip(request.headers.get('CF-Connecting-IP'))
        if found:
            return found
        forwarded = request.headers.get('X-Forwarded-For') or ''
        found = _ip(forwarded.split(',')[0]) if forwarded else None
        if found:
            return found
    return _ip(request.remote_addr) or 'unknown'


def visitor_key(settings: PublicSettings, store: PublicStore) -> str:
    """A salted hash of the visitor's address: the address itself is never stored."""

    ip = client_ip(settings)
    return hashlib.sha256(f'{store.salt}:{ip}'.encode('utf-8')).hexdigest()[:32]


def is_admin(settings: PublicSettings) -> bool:
    key = settings.admin_key
    sent = request.headers.get(ADMIN_HEADER) or ''
    return bool(key) and bool(sent) and hmac.compare_digest(sent.encode('utf-8'), key.encode('utf-8'))


def sent_invite() -> str:
    """The invite word this request brings: X-Parthenon-Invite, else ?invite=."""

    return invite_word(request.headers.get(INVITE_HEADER) or request.args.get(INVITE_QUERY) or '')


def invite_matches(sent: str, codes) -> bool:
    """Whether the word is one of the codes, compared in constant time against every one."""

    word = invite_word(sent).encode('utf-8')
    if not word:
        return False
    found = False
    for code in codes:
        if hmac.compare_digest(word, invite_word(code).encode('utf-8')):
            found = True
    return found


def _body() -> dict:
    if not request.is_json:
        return {}
    try:
        body = request.get_json(silent=True)
    except Exception:  # noqa: BLE001 - the view reports a bad body itself
        return {}
    return body if isinstance(body, dict) else {}


def _target_value(source: str, name: str):
    if source == 'view':
        return (request.view_args or {}).get(name)
    return _body().get(name)


# ------------------------------------------------------------------ the shelf

def shelf_ids() -> Optional[set]:
    """The ids a list may show, or None for no cut (not public, or the keepers)."""

    state = current_app.extensions.get('parthenon_public')
    if state is None or getattr(g, 'parthenon_admin', False):
        return None
    featured = state.store.featured_ids(state.settings.featured)
    owned = lineage.parse_id_list(request.headers.get(OWNED_HEADER))
    return lineage.expand_ids(list(featured) + owned)


def simulation_on_shelf(visible: Optional[set], simulation_id, project_id) -> bool:
    return visible is None or simulation_id in visible or project_id in visible


def report_on_shelf(visible: Optional[set], report_id, simulation_id) -> bool:
    if visible is None or report_id in visible or simulation_id in visible:
        return True
    state = lineage.simulation_record(simulation_id) if simulation_id else None
    return bool(state) and state.get('project_id') in visible


# ------------------------------------------------------------------ the city's run count

def running_runs(exclude: Optional[str] = None) -> int:
    """Runs this server is starting, running, pausing or stopping now."""

    from ..services.simulation_runner import ACTIVE_RUNNER_STATUSES, SimulationRunner

    ids = set(SimulationRunner._processes.keys()) | set(SimulationRunner._start_claims)
    count = 0
    for simulation_id in ids:
        if simulation_id == exclude:
            continue
        try:
            state = SimulationRunner.get_run_state(simulation_id)
        except Exception:  # noqa: BLE001 - an unreadable run holds no place
            continue
        if state is not None and state.runner_status in ACTIVE_RUNNER_STATUSES:
            count += 1
    return count


# ------------------------------------------------------------------ the checks

class PublicGuard:
    """The before/after request hooks of the public steps."""

    def __init__(self, settings: PublicSettings, store: PublicStore, desk: Optional[tickets.TicketDesk] = None):
        self.settings = settings
        self.store = store
        self.tickets = desk or tickets.TicketDesk(max_thinking=settings.tickets_in_flight)

    # -------------------------------------------------------------- before

    def before_request(self):
        settle_request_language()
        if request.method == 'OPTIONS' or request.endpoint is None:
            return None  # CORS preflight, or a 404 the error handler answers
        rule = rule_for(request.endpoint)
        g.parthenon_admin = is_admin(self.settings)

        bad_id = self._check_view_ids()
        if bad_id is not None:
            return bad_id
        if rule.kind == DISABLED:
            return refusal(404, 'notOnPublicSteps', NOT_ON_PUBLIC_STEPS)
        if rule.kind == ADMIN:
            return None if g.parthenon_admin else refusal(403, 'keepersOnly', NOT_YOURS)
        if rule.kind in (READ, SHELF):
            return None
        if rule.kind == INVITE:
            return self._invite()
        if rule.kind == CREATE:
            refused = self._invite()
            return refused if refused is not None else self._create()
        if rule.kind == SYMPOSIUM:
            return self._question()
        if rule.kind == VOICE:
            return self._voice()
        if rule.kind == OWNER:
            return self._owner(rule)
        return refusal(404, 'notOnPublicSteps', NOT_ON_PUBLIC_STEPS)

    def _question(self):
        work = request.environ.get(tickets.WORK_KEY)
        if isinstance(work, tickets.Work):
            # The ticket's own thread: the invite, the checks and the count were
            # made when it was handed out. It thinks within its own budget, holds
            # the gathering's open square meanwhile, and a refusal or a question
            # that runs out of time gives the count back (after_request).
            g.parthenon_taken = [tuple(bucket) for bucket in work.taken] or None
            time_budget.begin(work.budget_seconds)
            g.parthenon_env = envs.enter(self._question_simulation())
            return None
        refused = self._invite()
        if refused is None:
            refused = self._symposium()
        if refused is not None:
            return refused
        settings = self.settings
        if settings.question_tickets:
            # Answered at once; the question is worked in a thread of its own
            # (the edge gives up on an answer after 100 s).
            return tickets.hand_out(
                self.tickets, settings.question_seconds, request_language(),
                taken=getattr(g, 'parthenon_taken', None) or (),
            )
        # Without tickets: answered before the edge gives up (Cloudflare: 100 s).
        time_budget.begin(settings.request_seconds)
        g.parthenon_env = envs.enter(self._question_simulation())
        return None

    @staticmethod
    def _question_simulation():
        return _body().get('simulation_id') or (request.view_args or {}).get('simulation_id')

    def _invite(self):
        """None when this request may make something new; else the invite's refusal.

        A missing word is 403 invite_needed. A wrong one is 403 too, and
        counted: past invite_tries_per_hour in an hour, every word is 429
        slow_down until the hour turns (so the words cannot be guessed). The
        keepers pass without one.
        """

        settings = self.settings
        codes = settings.invite_codes
        if not codes or g.parthenon_admin:
            return None
        sent = sent_invite()
        if not sent:
            return refusal(403, 'inviteNeeded', INVITE_NEEDED, extra={'invite': 'missing'})
        visitor = visitor_key(settings, self.store)
        window = hour_window()
        limit = settings.invite_tries_per_hour
        if self.store.count('invite_misses', visitor, window) >= limit:
            return refusal(429, 'inviteTooManyTries', SLOW_DOWN, retry_after=seconds_to_next_hour())
        if invite_matches(sent, codes):
            return None
        # Counted, and never given back (not in g.parthenon_taken).
        self.store.take([('invite_misses', visitor, window, limit)])
        return refusal(403, 'inviteWrong', INVITE_NEEDED, extra={'invite': 'wrong'})

    def _check_view_ids(self):
        for name, value in (request.view_args or {}).items():
            if name not in VIEW_ARG_KINDS:
                continue
            if not lineage.valid_id(value, VIEW_ARG_KINDS[name]):
                return refusal(404, 'notFound')
        graph_id = (request.view_args or {}).get('graph_id')
        if graph_id is not None and not lineage.GRAPH_ID.fullmatch(str(graph_id)):
            return refusal(404, 'notFound')
        return None

    def _take(self, buckets):
        """take() the buckets for this request, remembered so a 4xx gives them back."""

        ok, full = self.store.take(buckets)
        if ok:
            g.parthenon_taken = list(getattr(g, 'parthenon_taken', [])) + list(buckets)
        return ok, full

    def _create(self):
        settings = self.settings
        if (request.content_length or 0) > settings.max_upload_bytes:
            return refusal(413, 'uploadTooLarge', TOO_LONG)
        try:
            form = request.form
            files = request.files.getlist('files')
        except RequestEntityTooLarge:
            return refusal(413, 'uploadTooLarge', TOO_LONG)
        if len(files) > MAX_SCROLL_FILES:
            return refusal(413, 'uploadTooLarge', TOO_LONG)
        for key in ('simulation_requirement', 'additional_context', 'project_name'):
            if len(form.get(key) or '') > MAX_REQUIREMENT_CHARS:
                return refusal(413, 'questionTooLong', TOO_LONG)
        if g.parthenon_admin:
            return None
        visitor = visitor_key(settings, self.store)
        day = day_window()
        ok, full = self._take([
            ('gatherings', '*', day, settings.daily_gatherings),
            ('visitor_gatherings', visitor, day, settings.per_visitor),
        ])
        if not ok:
            key = 'cityDoneToday' if full == 0 else 'visitorDoneToday'
            return refusal(429, key, COME_BACK_TOMORROW, retry_after=seconds_to_next_day())
        return None

    def _symposium(self):
        if (request.content_length or 0) > MAX_SYMPOSIUM_BODY:
            return refusal(413, 'questionTooLong', TOO_LONG)
        body = _body()
        texts = [body.get(key) for key in FREE_TEXT_FIELDS]
        interviews = body.get('interviews')
        if isinstance(interviews, list):
            if len(interviews) > MAX_INTERVIEWS:
                return refusal(413, 'questionTooLong', TOO_LONG)
            for item in interviews:
                if isinstance(item, dict):
                    texts.extend(item.get(key) for key in FREE_TEXT_FIELDS)
        if any(isinstance(text, str) and len(text) > MAX_QUESTION_CHARS for text in texts):
            return refusal(413, 'questionTooLong', TOO_LONG)
        if g.parthenon_admin:
            return None
        visitor = visitor_key(self.settings, self.store)
        ok, _full = self._take([('questions', visitor, hour_window(), self.settings.questions_per_hour)])
        if not ok:
            return refusal(429, 'slowDown', SLOW_DOWN, retry_after=seconds_to_next_hour())
        return None

    def _voice(self):
        if not current_features().get('voice'):
            return refusal(503, 'voiceOff', NOT_ON_PUBLIC_STEPS)
        refused = self._invite()
        if refused is not None:
            return refused
        if g.parthenon_admin:
            return None
        visitor = visitor_key(self.settings, self.store)
        ok, _full = self._take([('voice', visitor, hour_window(), self.settings.voice_per_hour)])
        if not ok:
            return refusal(429, 'slowDown', SLOW_DOWN, retry_after=seconds_to_next_hour())
        return None

    def _owner(self, rule: Rule):
        project_id = self._owned_project(rule)
        if project_id is False and rule.extra in ('portraits', 'stances'):
            # A guest who asks for what is already done (or under way) is told
            # so, and nothing reaches the painters or the readers: the reading
            # there is stands even when the record has outgrown it (an exhibit
            # unpacked with new file times reads as outgrown). Only the one
            # who began the gathering has it painted or read again.
            settled = self._already_settled(rule.extra)
            if settled is not None:
                return settled
        if rule.invite:
            refused = self._invite()
            if refused is not None:
                return refused
        if rule.feature and not current_features().get(rule.feature):
            key = 'portraitsOff' if rule.feature == 'portraits' else 'filmOff'
            return refusal(503, key, NOT_ON_PUBLIC_STEPS)
        if project_id is False:
            return refusal(403, 'notYours', NOT_YOURS)
        if rule.extra == 'start':
            return self._start(project_id)
        if rule.extra == 'prepare':
            self._clamp_prepare()
        elif rule.extra == 'build':
            self._clamp_build()
        elif rule.extra == 'create_simulation':
            _body().pop('graph_id', None)  # a crowd is drawn from its own gathering's Web
        return None

    def _owned_project(self, rule: Rule):
        """The project the request steers when the key owns it (None for the keepers), else False."""

        token = request.headers.get(OWNER_HEADER)
        for source, name in rule.target:
            value = _target_value(source, name)
            if value is None or value == '':
                continue
            if name == 'graph_id':
                projects = lineage.projects_of_graph(value)
                if g.parthenon_admin:
                    return projects[0] if projects else None
                if projects and all(lineage.token_owns(token, project) for project in projects):
                    return projects[0]
                return False
            project_id = lineage.project_of(value) if isinstance(value, str) else None
            if g.parthenon_admin:
                return project_id
            return project_id if lineage.token_owns(token, project_id) else False
        return None if g.parthenon_admin else False

    def _already_settled(self, what: str):
        from ..services import citizen_portraits

        body = _body()
        if body.get('force') is True:
            return None
        canonical = citizen_portraits.find_simulation((request.view_args or {}).get('simulation_id'))
        if canonical is None:
            return None
        try:
            if what == 'portraits':
                status = citizen_portraits.get_portraits(canonical).get('status')
                done, going = status == 'completed', status == 'running'
            else:
                reading = citizen_portraits.get_stances(canonical)
                status = reading.get('status')
                done = status == 'completed'
                going = status == 'reading'
        except Exception:  # noqa: BLE001 - then the usual checks decide
            return None
        if done:
            return jsonify({'success': True, 'data': {'status': 'completed', 'simulation_id': canonical}}), 200
        if going:
            data = {'status': 'running' if what == 'portraits' else 'reading', 'simulation_id': canonical}
            return jsonify({'success': True, 'data': data}), 202
        return None

    def _start(self, project_id):
        settings = self.settings
        body = _body()
        rounds = body.get('max_rounds')
        try:
            rounds = int(rounds) if rounds is not None and not isinstance(rounds, bool) else None
        except (TypeError, ValueError):
            rounds = None  # the view reports a bad max_rounds itself
            return None
        if not g.parthenon_admin:
            if rounds is None or rounds > settings.max_run_rounds:
                body['max_rounds'] = settings.max_run_rounds
        simulation_id = body.get('simulation_id')
        if g.parthenon_admin:
            # The keepers are not held to the seats, but an idle open square
            # still makes way (it holds about a gigabyte).
            envs.make_room(max(settings.concurrent_runs - running_runs(exclude=simulation_id), 1),
                           exclude=simulation_id)
            return None
        if not _start_lock.acquire(timeout=START_LOCK_SECONDS):
            return refusal(429, 'cityFull', CITY_FULL, retry_after=CITY_FULL_RETRY_SECONDS)
        g.parthenon_start_lock = True
        running = running_runs(exclude=simulation_id)
        if running >= settings.concurrent_runs:
            return refusal(429, 'cityFull', CITY_FULL, retry_after=CITY_FULL_RETRY_SECONDS)
        if project_id:
            ok, _full = self._take([('runs', project_id, day_window(), settings.runs_per_gathering)])
            if not ok:
                return refusal(
                    429, 'gatheringDoneToday', COME_BACK_TOMORROW, retry_after=seconds_to_next_day()
                )
        # A square left open after its argument holds a seat too: the idle ones
        # close to make room; one still in use (a question, a Chronicle) keeps it.
        if not envs.make_room(settings.concurrent_runs - running, exclude=simulation_id):
            return refusal(429, 'cityFull', CITY_FULL, retry_after=CITY_FULL_RETRY_SECONDS)
        return None

    def _clamp_prepare(self):
        body = _body()
        count = body.get('parallel_profile_count')
        if count is not None and (not isinstance(count, int) or isinstance(count, bool) or not 1 <= count <= MAX_PARALLEL_PROFILES):
            body['parallel_profile_count'] = MAX_PARALLEL_PROFILES

    def _clamp_build(self):
        body = _body()
        for key, (low, high) in (('chunk_size', CHUNK_SIZE_RANGE), ('chunk_overlap', CHUNK_OVERLAP_RANGE)):
            value = body.get(key)
            if value is None:
                continue
            try:
                number = int(value)
            except (TypeError, ValueError):
                body.pop(key, None)
                continue
            body[key] = min(max(number, low), high)

    # -------------------------------------------------------------- after

    def after_request(self, response):
        if time_budget.spent() and response.status_code >= 500:
            # The model ran past the request's time: one calm line, and the question back.
            logger.info('A question on %s ran out of time', request.endpoint)
            response = refusal(
                503, 'tookTooLong', SLOW_DOWN, retry_after=TOOK_TOO_LONG_RETRY_SECONDS
            )
            give_back = True
        else:
            give_back = 400 <= response.status_code < 500
        taken = getattr(g, 'parthenon_taken', None)
        if taken and give_back:
            try:
                self.store.give_back(taken)
            except Exception as error:  # noqa: BLE001 - a lost refund only costs one count
                logger.warning('Could not give back a count: type=%s', type(error).__name__)
            g.parthenon_taken = None
        token = getattr(g, 'parthenon_owner_token', None)
        if token and response.is_json and not response.direct_passthrough:
            payload = response.get_json(silent=True)
            data = payload.get('data') if isinstance(payload, dict) else None
            if isinstance(data, dict) and lineage.valid_id(data.get('project_id'), 'proj'):
                data['owner_token'] = token
                response.set_data(current_app.json.dumps(payload))
        scrub_response(response)
        speak_their_language(response)
        response.headers.setdefault('X-Content-Type-Options', 'nosniff')
        return response

    def teardown_request(self, _error=None):
        time_budget.clear()
        envs.leave(getattr(g, 'parthenon_env', None))
        g.parthenon_env = None
        if getattr(g, 'parthenon_start_lock', False):
            g.parthenon_start_lock = False
            _start_lock.release()

    # -------------------------------------------------------------- errors

    def handle_error(self, error):
        if isinstance(error, HTTPException):
            code = error.code or 500
            if code == 413:
                return refusal(413, 'uploadTooLarge', TOO_LONG)
            if code in (404, 405):
                return refusal(code, 'notFound')
            return jsonify({'success': False, 'error': words('stumbled')}), code
        logger.error('Unhandled error on %s: type=%s', request.endpoint, type(error).__name__, exc_info=error)
        return jsonify({'success': False, 'error': words('stumbled')}), 500


# ------------------------------------------------------------------ nothing internal leaves

_PATH = re.compile(
    r'(?<![\w/.~-])(?:/Users|/home|/app|/data|/private|/tmp|/var|/opt|/usr|/root|/srv|/etc|/proc)'
    r'/[^\s\'"`,;)\]}>]*'
)
_QUICK_MARKERS = (
    '/Users/', '/home/', '/app/', '/data/', '/private/', '/tmp/', '/var/', '/opt/', '/usr/',
    '/root/', '/srv/', '/etc/', '/proc/', 'Traceback', '"traceback"', '.env', 'npm run',
    '_API_KEY', 'Errno', 'File "',
)
_LEAKS = ('Traceback (most recent call last)', 'File "', '.env', 'npm run', '_API_KEY', 'Errno')
_MESSAGE_KEYS = ('error', 'message', 'detail', 'details')


def speak_their_language(response) -> None:
    """An error a view wrote in the other language (a fixed Chinese message for an
    English visitor, or an English one for a Chinese visitor) is put in the city's
    words in the visitor's own. Refusals with a code are already theirs.

    An answer that succeeded carries notes too (a task's or a run's error, a
    progress message); see _speak_in_success."""

    if response.direct_passthrough or not response.is_json:
        return
    if response.status_code < 400:
        _speak_in_success(response)
        return
    payload = response.get_json(silent=True)
    if not isinstance(payload, dict) or payload.get('success') is not False or payload.get('code'):
        return
    lang = request_language()
    if not in_other_language(payload.get('error'), lang):
        return
    status = response.status_code
    key = 'notFound' if status == 404 else 'stumbled' if status >= 500 else 'cannotDoThat'
    payload['error'] = words(key, lang)
    response.set_data(current_app.json.dumps(payload))


# A body that may hold an error field: only then is a Chinese visitor's answer read.
_ERROR_FIELD = re.compile(r'"error"\s*:\s*"')
# What a note describes has failed.
_FAILED_STATES = frozenset({'failed', 'error'})


def _note_holders(payload: dict):
    """The objects whose error and message the pages show: the body, its data (or each item
    of a data list), and what those hold one level down (a task, a run, a ticket's result)."""

    yield payload
    data = payload.get('data')
    tops = [data] if isinstance(data, dict) else (
        [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []
    )
    for top in tops:
        yield top
        for value in top.values():
            if isinstance(value, dict):
                yield value
            elif isinstance(value, list):
                yield from (item for item in value if isinstance(item, dict))


def _calm_notes(holder: dict, lang: str) -> bool:
    if holder.get('code'):
        return False  # a refusal, already in the city's words
    changed = False
    failed = str(holder.get('status') or '').lower() in _FAILED_STATES or bool(holder.get('error'))
    if in_other_language(holder.get('error'), lang):
        holder['error'] = words('stumbled', lang)
        changed = True
    # A progress note in Chinese is no note for an English visitor: it goes, or
    # is the calm line when what it describes failed. An English note stays
    # for a Chinese visitor (the public steps keep their records in English).
    if lang != 'zh' and in_other_language(holder.get('message'), lang):
        holder['message'] = words('stumbled', lang) if failed else ''
        changed = True
    return changed


def _speak_in_success(response) -> None:
    """The safety net of an answer that succeeded: an error in the other language, or a Chinese
    message for an English visitor, where the pages show one (_note_holders).

    Cheap: an English visitor's answer is read only when it holds Chinese, a
    Chinese visitor's only when it holds an error field."""

    try:
        text = response.get_data(as_text=True)
    except Exception:  # noqa: BLE001 - a body that cannot be read is left alone
        return
    lang = request_language()
    if not (_ERROR_FIELD.search(text) if lang == 'zh' else has_chinese(text)):
        return
    try:
        payload = json.loads(text)
    except ValueError:
        return
    if not isinstance(payload, dict) or payload.get('code'):
        return
    changed = False
    for holder in _note_holders(payload):
        changed = _calm_notes(holder, lang) or changed
    if changed:
        response.set_data(current_app.json.dumps(payload))


def scrub_text(text: str) -> str:
    return _PATH.sub('[…]', text)


def _leaky(text: str) -> bool:
    return any(marker in text for marker in _LEAKS) or bool(_PATH.search(text))


def _scrub(value: Any, key: Optional[str] = None, failed: bool = False):
    if isinstance(value, dict):
        return {k: _scrub(v, k, failed) for k, v in value.items() if k != 'traceback'}
    if isinstance(value, list):
        return [_scrub(item, key, failed) for item in value]
    if isinstance(value, str):
        if key in _MESSAGE_KEYS and _leaky(value):
            return words('stumbled')
        if failed and _leaky(value):
            return words('stumbled')
        return scrub_text(value) if _PATH.search(value) else value
    return value


def scrub_response(response) -> None:
    """No stack trace, server path or setting leaves in a JSON body."""

    if response.direct_passthrough or not response.is_json:
        return
    try:
        text = response.get_data(as_text=True)
    except Exception:  # noqa: BLE001 - a body that cannot be read is left alone
        return
    failed = response.status_code >= 400
    if not failed and not any(marker in text for marker in _QUICK_MARKERS):
        return
    try:
        payload = json.loads(text)
    except ValueError:
        return
    cleaned = _scrub(payload, failed=failed)
    if cleaned != payload:
        response.set_data(current_app.json.dumps(cleaned))
