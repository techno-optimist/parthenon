"""
What the public steps allow, read from the environment.

Every setting is optional. PARTHENON_PUBLIC=1 turns public mode on; without
it nothing in app/public runs and the owner's own machine behaves as it
always has. See app/public/__init__.py for the whole contract.
"""

import logging
import os
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, Mapping, Optional, Tuple

from ..config import Config


logger = logging.getLogger('mirofish.public')

TRUE_WORDS = frozenset({'1', 'true', 'yes', 'on'})
FALSE_WORDS = frozenset({'0', 'false', 'no', 'off'})

# The two finished gatherings that ship with the public steps (When Sand
# Speaks and Socrates' Apology), by project id.
EXHIBIT_PROJECT_IDS = ('proj_527f80721255', 'proj_ce8edd07eb88')

# The run lengths a visitor chooses from (frontend RUN_LENGTHS): rounds, which
# the frontend counts as hours.
RUN_LENGTH_ROUNDS: Dict[str, int] = {
    'afternoon': 12,
    'day': 24,
    'threeDays': 72,
    'week': 168,
}

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
FRONTEND_DIR_CANDIDATES = (
    os.path.abspath(os.path.join(BACKEND_DIR, '..', 'frontend', 'dist')),
    '/app/frontend/dist',
)
PUBLIC_DB_NAME = 'parthenon_public.sqlite3'
# A question's budget stays well inside a ticket's 30 minutes.
MAX_QUESTION_SECONDS = 1500


def _flag(environ: Mapping[str, str], name: str) -> bool:
    return str(environ.get(name) or '').strip().lower() in TRUE_WORDS


def _text(environ: Mapping[str, str], name: str, default: str = '') -> str:
    value = environ.get(name)
    if value is None or not str(value).strip():
        return default
    return str(value).strip()


def _flag_default_on(environ: Mapping[str, str], name: str) -> bool:
    raw = str(environ.get(name) or '').strip().lower()
    return raw not in FALSE_WORDS


def invite_word(value) -> str:
    """An invite code as it is compared: trimmed, and a space read as '+'.

    A code carried in a link (?invite=...) comes back with its '+' turned into
    a space by the query's decoding; reading both sides alike keeps such a
    code working.
    """

    return str(value or '').strip().replace(' ', '+')


def parse_invite_codes(raw) -> Tuple[str, ...]:
    """PARTHENON_INVITE_CODE: one code, or several separated by commas; empty means no invite."""

    return tuple(dict.fromkeys(
        code for code in (invite_word(part) for part in str(raw or '').split(',')) if code
    ))


def _count(environ: Mapping[str, str], name: str, default: int, minimum: int = 0) -> int:
    raw = _text(environ, name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning('%s is not a whole number; using %s', name, default)
        return default
    if value < minimum:
        logger.warning('%s must be at least %s; using %s', name, minimum, default)
        return default
    return value


def normalize_base(value: str) -> str:
    """'/parthenon/' -> '/parthenon'; '' and '/' -> '' (served at the root only)."""

    base = '/' + (value or '').strip().strip('/')
    return '' if base == '/' else base


def parse_max_run(value: str) -> Tuple[object, int]:
    """(max_run as the status reports it, the most rounds a run may have).

    A run length id (afternoon, day, threeDays, week) or a whole number of
    hours; a number that is one of the lengths is reported by its id.
    Anything else falls back to 'day'.
    """

    raw = (value or '').strip()
    for run_id, rounds in RUN_LENGTH_ROUNDS.items():
        if raw.lower() == run_id.lower():
            return run_id, rounds
    try:
        hours = int(raw)
    except ValueError:
        if raw:
            logger.warning('PARTHENON_MAX_RUN %r is not a run length; using day', raw)
        return 'day', RUN_LENGTH_ROUNDS['day']
    if hours <= 0:
        logger.warning('PARTHENON_MAX_RUN must be positive; using day')
        return 'day', RUN_LENGTH_ROUNDS['day']
    for run_id, rounds in RUN_LENGTH_ROUNDS.items():
        if rounds == hours:
            return run_id, rounds
    return hours, hours


def _frontend_dir(environ: Mapping[str, str]) -> str:
    explicit = _text(environ, 'PARTHENON_FRONTEND_DIR')
    if explicit:
        return os.path.abspath(explicit)
    for candidate in FRONTEND_DIR_CANDIDATES:
        if os.path.isfile(os.path.join(candidate, 'index.html')):
            return candidate
    return FRONTEND_DIR_CANDIDATES[0]


@dataclass(frozen=True)
class PublicSettings:
    public: bool = False
    base: str = '/parthenon'
    frontend_dir: str = FRONTEND_DIR_CANDIDATES[0]
    data_dir: str = ''
    db_path: str = ''
    admin_key: str = field(default='', repr=False)
    trust_proxy: bool = False
    upstream: str = 'auto'
    public_origins: Tuple[str, ...] = ('https://projectforty2.ai',)
    daily_gatherings: int = 12
    per_visitor: int = 2
    max_citizens: int = 12
    max_run: object = 'day'
    max_run_rounds: int = 24
    concurrent_runs: int = 1
    questions_per_hour: int = 30
    max_scroll_chars: int = 20000
    max_upload_bytes: int = 5 * 1024 * 1024
    runs_per_gathering: int = 3
    featured: Tuple[str, ...] = EXHIBIT_PROJECT_IDS
    # How long a question may wait on the model (Cloudflare gives up at 100 s).
    request_seconds: int = 85
    # An environment left open after its run is closed after this long unused (0: never).
    idle_env_minutes: int = 20
    # Questions as tickets: answered 202 at once and worked in a thread with this budget.
    question_tickets: bool = True
    question_seconds: int = 240
    tickets_in_flight: int = 24
    # The words that open speaking (PARTHENON_INVITE_CODE); empty: no invite is asked for.
    invite_codes: Tuple[str, ...] = field(default=(), repr=False)
    invite_tries_per_hour: int = 10

    @property
    def invite_required(self) -> bool:
        return bool(self.invite_codes)

    @property
    def voice_per_hour(self) -> int:
        # A long answer is spoken in several parts: each part is one request.
        return self.questions_per_hour * 4

    @property
    def featured_set(self) -> FrozenSet[str]:
        return frozenset(self.featured)


def load_settings(environ: Optional[Mapping[str, str]] = None) -> PublicSettings:
    """The public settings from the environment (os.environ by default), read now."""

    env = os.environ if environ is None else environ
    data_dir = _text(env, 'PARTHENON_DATA_DIR')
    data_dir = os.path.abspath(data_dir) if data_dir else ''
    db_root = data_dir or os.path.abspath(Config.UPLOAD_FOLDER)
    max_run, max_run_rounds = parse_max_run(_text(env, 'PARTHENON_MAX_RUN', 'day'))
    featured_raw = env.get('PARTHENON_FEATURED')
    if featured_raw is None:
        featured = EXHIBIT_PROJECT_IDS
    else:
        featured = tuple(dict.fromkeys(
            item.strip() for item in str(featured_raw).split(',') if item.strip()
        ))
    origins = tuple(
        origin.strip().rstrip('/')
        for origin in _text(env, 'PARTHENON_PUBLIC_ORIGIN', 'https://projectforty2.ai').split(',')
        if origin.strip()
    )
    return PublicSettings(
        public=_flag(env, 'PARTHENON_PUBLIC'),
        base=normalize_base(_text(env, 'PARTHENON_BASE', '/parthenon')),
        frontend_dir=_frontend_dir(env),
        data_dir=data_dir,
        db_path=os.path.join(db_root, PUBLIC_DB_NAME),
        admin_key=_text(env, 'PARTHENON_ADMIN_KEY'),
        trust_proxy=_flag(env, 'PARTHENON_TRUST_PROXY'),
        upstream=_text(env, 'PARTHENON_UPSTREAM', 'auto').lower(),
        public_origins=origins,
        daily_gatherings=_count(env, 'PARTHENON_DAILY_GATHERINGS', 12),
        per_visitor=_count(env, 'PARTHENON_DAILY_PER_VISITOR', 2),
        max_citizens=_count(env, 'PARTHENON_MAX_CITIZENS', 12, minimum=1),
        max_run=max_run,
        max_run_rounds=max_run_rounds,
        concurrent_runs=_count(env, 'PARTHENON_CONCURRENT_RUNS', 1),
        questions_per_hour=_count(env, 'PARTHENON_QUESTIONS_PER_HOUR', 30),
        max_scroll_chars=_count(env, 'PARTHENON_MAX_SCROLL_CHARS', 20000, minimum=1),
        max_upload_bytes=_count(env, 'PARTHENON_MAX_UPLOAD_MB', 5, minimum=1) * 1024 * 1024,
        runs_per_gathering=_count(env, 'PARTHENON_RUNS_PER_GATHERING', 3),
        featured=featured,
        request_seconds=min(_count(env, 'PARTHENON_REQUEST_SECONDS', 85, minimum=10), 600),
        idle_env_minutes=_count(env, 'PARTHENON_IDLE_ENV_MINUTES', 20),
        question_tickets=_flag_default_on(env, 'PARTHENON_QUESTION_TICKETS'),
        question_seconds=min(_count(env, 'PARTHENON_QUESTION_SECONDS', 240, minimum=10), MAX_QUESTION_SECONDS),
        tickets_in_flight=_count(env, 'PARTHENON_TICKETS_IN_FLIGHT', 24, minimum=1),
        invite_codes=parse_invite_codes(env.get('PARTHENON_INVITE_CODE')),
        invite_tries_per_hour=_count(env, 'PARTHENON_INVITE_TRIES_PER_HOUR', 10, minimum=1),
    )
