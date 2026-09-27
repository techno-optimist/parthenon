"""
Questions as tickets.

On the public steps every request passes through Cloudflare, which gives up
on an answer after 100 seconds, and a question to the city can take longer
than that (a whole crowd, the Scribe with her searches, the Oracle's draft).
So a question is answered at once, 202:

    {"success": true, "data": {"ticket": "<id>", "status": "thinking",
     "budget_seconds": 240, "poll": "/api/parthenon/ticket/<id>"}}

and the question itself is worked in a thread of its own, under its own
budget (PARTHENON_QUESTION_SECONDS, 240 by default). The page asks
GET /api/parthenon/ticket/<id> until the answer is there:

    {"success": true, "ticket": "<id>", "status": "thinking" | "done" | "failed",
     "result": <exactly the JSON the question's route answers when it is asked
                directly, success and data included; null while thinking>,
     "http_status": <the status that answer has>, "error": <the city's words
     when failed>, "code": <the refusal's code when there is one>,
     "retry_after_seconds"?, "budget_seconds", "elapsed_seconds"}

"done" is an answer with a 2xx status whose body is not success: false;
anything else is "failed" (a question the route refused, one that ran out of
its budget: code slow_down, or one the city stumbled over). A ticket that is
not known (never handed out, older than 30 minutes, or lost with a restart)
is 404 {success: false, status: "failed", code: "ticket_lost", error}.

How the question is worked: the request's own WSGI environ is copied, with
its body, and handed to the Flask app again in the ticket's thread, marked
with WORK_KEY. The question's route therefore runs its one synchronous code
path, with every hook around it (the guard, the scrubbing of what leaves,
the city's words), and its answer is kept whole. The guard knows the mark:
the invite, the size checks and the hourly count were already made when the
ticket was handed out, so the thread only takes the budget and holds the
gathering's open square while it thinks (and a refused or timed-out question
is given back to the visitor, as a direct one is).

The id is secrets.token_urlsafe(24): a ticket is read only by whoever holds
it. Tickets live in this process's memory: a restart loses them (the page
says so calmly and keeps the question). Nothing here runs on the owner's own
machine, where the question routes answer directly as they always have.
"""

import io
import json
import logging
import re
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Tuple

from flask import current_app, jsonify, request

from .words import SLOW_DOWN, TICKET_LOST, refusal, words


logger = logging.getLogger('mirofish.public')

WORK_KEY = 'parthenon.ticket'
TICKET_TTL_SECONDS = 30 * 60
# A ticket still thinking this long past its budget is told as run out of time.
GRACE_SECONDS = 30
# How often the page is asked to look (it may slow down after a while).
POLL_SECONDS = 2
MAX_TICKETS = 2000
BUSY_RETRY_SECONDS = 30
TIMED_OUT_RETRY_SECONDS = 60
TICKET_ID = re.compile(r'[A-Za-z0-9_-]{20,64}')
THINKING, DONE, FAILED = 'thinking', 'done', 'failed'
# Environ keys that belong to the request that handed the ticket out.
_ENVIRON_DROPPED = ('werkzeug.request', 'werkzeug.debug.preserve_context', WORK_KEY)


def valid_ticket_id(value) -> bool:
    return isinstance(value, str) and bool(TICKET_ID.fullmatch(value))


@dataclass(frozen=True)
class Work:
    """What the ticket's thread is given: the ticket, its budget and the counts it holds."""

    ticket_id: str
    budget_seconds: float
    taken: Tuple[tuple, ...] = ()


@dataclass
class Ticket:
    id: str
    endpoint: str
    budget_seconds: float
    lang: str
    created: float
    status: str = THINKING
    http_status: Optional[int] = None
    result: Optional[Any] = None
    error: Optional[str] = None
    code: Optional[str] = None
    retry_after_seconds: Optional[int] = None
    settled: Optional[float] = None

    def view(self, now: float) -> Dict[str, Any]:
        body = {
            'ticket': self.id,
            'status': self.status,
            'result': self.result,
            'http_status': self.http_status,
            'error': self.error,
            'code': self.code,
            'budget_seconds': int(self.budget_seconds),
            'elapsed_seconds': round(max(0.0, (self.settled or now) - self.created), 1),
        }
        if self.retry_after_seconds is not None:
            body['retry_after_seconds'] = self.retry_after_seconds
        return body


def outcome(http_status: int, payload: Any) -> Tuple[str, Optional[str], Optional[str], Optional[int]]:
    """(status, error, code, retry_after) of a question's answer."""

    body = payload if isinstance(payload, dict) else {}
    if 200 <= http_status < 300 and isinstance(payload, dict) and body.get('success') is not False:
        return DONE, None, None, None
    error = body.get('error')
    code = body.get('code')
    retry = body.get('retry_after_seconds')
    return (
        FAILED,
        error if isinstance(error, str) and error else None,
        code if isinstance(code, str) and code else None,
        int(retry) if isinstance(retry, (int, float)) and not isinstance(retry, bool) else None,
    )


class TicketDesk:
    """The tickets of one app: handed out, settled by their threads, read by the page."""

    def __init__(self, ttl_seconds: float = TICKET_TTL_SECONDS, max_thinking: int = 24,
                 clock: Callable[[], float] = time.monotonic):
        self.ttl_seconds = float(ttl_seconds)
        self.max_thinking = int(max_thinking)
        self.clock = clock
        self._lock = threading.Lock()
        self._tickets: Dict[str, Ticket] = {}

    # ------------------------------------------------------------------ handing out

    def open(self, endpoint: str, budget_seconds: float, lang: str) -> Optional[Ticket]:
        """A new thinking ticket, or None when the city already has max_thinking questions in hand."""

        now = self.clock()
        with self._lock:
            self._prune(now)
            if self._thinking(now) >= self.max_thinking:
                return None
            ticket_id = secrets.token_urlsafe(24)
            while ticket_id in self._tickets:
                ticket_id = secrets.token_urlsafe(24)
            ticket = Ticket(ticket_id, endpoint or '', float(budget_seconds), lang, now)
            self._tickets[ticket_id] = ticket
            return ticket

    def settle(self, ticket_id: str, http_status: int, payload: Any) -> None:
        """The thread's answer; a ticket already given up on keeps what it said."""

        now = self.clock()
        with self._lock:
            ticket = self._tickets.get(ticket_id)
            if ticket is None or ticket.status != THINKING:
                return
            status, error, code, retry = outcome(http_status, payload)
            if status == FAILED and error is None:
                error = words('stumbled', ticket.lang)
            ticket.status, ticket.http_status = status, int(http_status)
            ticket.result = payload if isinstance(payload, dict) else None
            ticket.error, ticket.code, ticket.retry_after_seconds = error, code, retry
            ticket.settled = now

    # ------------------------------------------------------------------ reading

    def read(self, ticket_id: str) -> Optional[Dict[str, Any]]:
        """What the page is told about a ticket, or None when it is not known (or has expired)."""

        if not valid_ticket_id(ticket_id):
            return None
        now = self.clock()
        with self._lock:
            ticket = self._tickets.get(ticket_id)
            if ticket is None:
                return None
            if now - ticket.created > self.ttl_seconds:
                del self._tickets[ticket_id]
                return None
            if ticket.status == THINKING and self._overdue(ticket, now):
                self._give_up(ticket, now)
            return ticket.view(now)

    def thinking(self) -> int:
        now = self.clock()
        with self._lock:
            return self._thinking(now)

    def __len__(self) -> int:
        with self._lock:
            return len(self._tickets)

    # ------------------------------------------------------------------ inside the lock

    def _overdue(self, ticket: Ticket, now: float) -> bool:
        return now - ticket.created > ticket.budget_seconds + GRACE_SECONDS

    def _give_up(self, ticket: Ticket, now: float) -> None:
        """A thread that outlived its budget: the page is told calmly, and a late answer is dropped."""

        error = words('tookTooLong', ticket.lang)
        ticket.status, ticket.http_status = FAILED, 503
        ticket.error, ticket.code = error, SLOW_DOWN
        ticket.retry_after_seconds = TIMED_OUT_RETRY_SECONDS
        ticket.result = {
            'success': False, 'error': error, 'code': SLOW_DOWN,
            'retry_after_seconds': TIMED_OUT_RETRY_SECONDS,
        }
        ticket.settled = now

    def _thinking(self, now: float) -> int:
        return sum(
            1 for ticket in self._tickets.values()
            if ticket.status == THINKING and not self._overdue(ticket, now)
        )

    def _prune(self, now: float) -> None:
        for ticket_id in [key for key, ticket in self._tickets.items() if now - ticket.created > self.ttl_seconds]:
            del self._tickets[ticket_id]
        if len(self._tickets) < MAX_TICKETS:
            return
        # Too many kept: the oldest settled answers go first.
        settled = sorted(
            (ticket for ticket in self._tickets.values() if ticket.status != THINKING),
            key=lambda ticket: ticket.created,
        )
        for ticket in settled[:len(self._tickets) - MAX_TICKETS + 1]:
            del self._tickets[ticket.id]


# ---------------------------------------------------------------------- the thread

def work_environ(environ: Dict[str, Any], body: bytes) -> Dict[str, Any]:
    """A copy of a request's environ that can be served again, with its body."""

    copied = {key: value for key, value in environ.items() if key not in _ENVIRON_DROPPED}
    copied['wsgi.input'] = io.BytesIO(body)
    copied['CONTENT_LENGTH'] = str(len(body))
    copied['wsgi.input_terminated'] = True
    copied.pop('HTTP_TRANSFER_ENCODING', None)
    return copied


def work(app, environ: Dict[str, Any], desk: TicketDesk, ticket_id: str) -> None:
    """Serve the question again, in this thread, and settle its ticket with the answer."""

    captured: Dict[str, Any] = {}
    chunks = []

    def start_response(status, _headers, _exc_info=None):
        captured['status'] = status
        return chunks.append

    http_status, payload = 500, None
    try:
        answer = app.wsgi_app(environ, start_response)
        try:
            for chunk in answer:
                chunks.append(chunk)
        finally:
            close = getattr(answer, 'close', None)
            if close is not None:
                close()
        http_status = int(str(captured.get('status') or '500').split(' ', 1)[0])
        payload = json.loads(b''.join(chunks).decode('utf-8'))
    except Exception as error:  # noqa: BLE001 - the ticket says the city stumbled
        logger.error('A question on its ticket failed: type=%s', type(error).__name__)
        http_status, payload = 500, None
    desk.settle(ticket_id, http_status, payload)


def start_thread(target, *args) -> threading.Thread:
    thread = threading.Thread(target=target, args=args, name='parthenon-question', daemon=True)
    thread.start()
    return thread


def hand_out(desk: TicketDesk, budget_seconds: float, lang: str, taken=()):
    """Answer this question 202 with a ticket, and work it in a thread of its own."""

    ticket = desk.open(request.endpoint, budget_seconds, lang)
    if ticket is None:
        return refusal(429, 'manyQuestions', SLOW_DOWN, retry_after=BUSY_RETRY_SECONDS)
    app = current_app._get_current_object()
    environ = work_environ(request.environ, request.get_data(cache=True))
    environ[WORK_KEY] = Work(ticket.id, float(budget_seconds), tuple(tuple(bucket) for bucket in taken or ()))
    try:
        start_thread(work, app, environ, desk, ticket.id)
    except RuntimeError as error:  # no thread to be had: the question is given back (a 4xx)
        logger.error('No thread for a question: type=%s', type(error).__name__)
        desk.settle(ticket.id, 503, None)
        return refusal(429, 'manyQuestions', SLOW_DOWN, retry_after=BUSY_RETRY_SECONDS)
    response = jsonify({'success': True, 'data': {
        'ticket': ticket.id,
        'status': THINKING,
        'budget_seconds': int(budget_seconds),
        'poll': f'/api/parthenon/ticket/{ticket.id}',
        'poll_seconds': POLL_SECONDS,
    }})
    response.status_code = 202
    response.headers['Cache-Control'] = 'no-store'
    return response


def ticket_response(desk: TicketDesk, ticket_id: str):
    """GET /api/parthenon/ticket/<id>."""

    found = desk.read(ticket_id)
    if found is None:
        response = refusal(404, 'ticketLost', TICKET_LOST, extra={'status': FAILED, 'result': None})
    else:
        response = jsonify({'success': True, **found})
    response.headers['Cache-Control'] = 'no-store'
    return response
