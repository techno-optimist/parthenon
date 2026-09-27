"""Questions as tickets (app/public/tickets.py).

On the public steps a question is answered 202 at once with a ticket, and
worked in a thread of its own within PARTHENON_QUESTION_SECONDS; the ticket
then holds exactly what the route would have answered directly. On the
owner's own machine the question routes answer directly, byte for byte as
before.
"""

import json
import threading
import time

import pytest
from flask import jsonify

from app.api import parthenon as parthenon_api
from app.public import envs, tickets
from app.public.tickets import TicketDesk, outcome, valid_ticket_id, work_environ
from app.services.stage_oracle import OracleUnavailableError
from app.utils import time_budget

from test_public_mode import (  # noqa: F401 - fixtures
    ADMIN_KEY, EXHIBIT_SIM, VISITOR_A, VISITOR_B, TicketAnswer, _stub, _visitor, ask, city, follow,
    speaker,
)


SPEAKER_URL = f'/api/parthenon/gathering/{EXHIBIT_SIM}/speaker'

# Every question route, the body the page sends it, and its endpoint.
QUESTIONS = [
    ('simulation.interview_agent', '/api/simulation/interview',
     {'simulation_id': EXHIBIT_SIM, 'agent_id': 0, 'prompt': 'Why?'}),
    ('simulation.interview_agents_batch', '/api/simulation/interview/batch',
     {'simulation_id': EXHIBIT_SIM, 'interviews': [{'agent_id': 0, 'prompt': 'Why?'}]}),
    ('simulation.interview_all_agents', '/api/simulation/interview/all',
     {'simulation_id': EXHIBIT_SIM, 'prompt': 'Why?'}),
    ('report.chat_with_report_agent', '/api/report/chat',
     {'simulation_id': EXHIBIT_SIM, 'message': 'Why?', 'chat_history': []}),
    ('parthenon.ask_the_speaker', SPEAKER_URL, {'question': 'Why?'}),
    ('parthenon.draft_stage', '/api/parthenon/stage/draft', {'stage': {'title': 'A stage'}, 'fill': ['audience']}),
]


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def _desk(app):
    return app.extensions['parthenon_public'].tickets


def _blocked_view(started, release, answer=None):
    """A question the city is still thinking over until release is set."""

    def view(**_kwargs):
        started.set()
        release.wait(10)
        return jsonify(answer or {'success': True, 'data': {'answer': 'At last.'}})
    return view


# ================================================================== the owner's own machine

def _reference_bytes(app, url, body, view):
    """What the view itself gives, with no hook around it."""

    with app.test_request_context(url, method='POST', json=body):
        return app.make_response(view()).get_data()


@pytest.mark.parametrize('endpoint, url, body', QUESTIONS)
def test_on_the_owners_machine_a_question_is_answered_directly_byte_for_byte(city, endpoint, url, body):
    city.env(PARTHENON_INVITE_CODE='olive', PARTHENON_QUESTION_SECONDS=30)  # read only on the public steps
    app = city.app(public=False)
    seen = []

    def view(**kwargs):
        seen.append((threading.current_thread() is threading.main_thread(), time_budget.remaining()))
        return jsonify({'success': True, 'data': {'answer': 'Κνῶθι σαυτόν, 认识你自己', 'args': kwargs}})

    app.view_functions[endpoint] = view
    response = app.test_client().post(url, json=body)

    assert response.status_code == 200
    assert response.get_data() == _reference_bytes(app, url, body, lambda: view(**_view_args(app, url)))
    assert seen[0] == (True, None)  # in the request's own thread, with no budget
    assert 'parthenon_public' not in app.extensions


def _view_args(app, url):
    adapter = app.url_map.bind('localhost')
    return adapter.match(url, method='POST')[1]


def test_on_the_owners_machine_the_speaker_answers_as_it_always_has(city, speaker):
    app = city.app(public=False)

    response = app.test_client().post(SPEAKER_URL, json={'question': 'Why?'})

    assert response.status_code == 200
    assert response.json == {'success': True, 'data': {
        'answer': 'Know thyself.', 'from_memory': True, 'lang': 'en', 'speaker': {'name': 'Socrates'},
    }}
    assert app.test_client().get('/api/parthenon/ticket/' + 'a' * 32).status_code == 404


# ================================================================== a ticket, then its answer

def test_a_question_is_answered_at_once_with_a_ticket(city, speaker):
    client = city.client()

    response = client.post(SPEAKER_URL, json={'question': 'Why?'}, headers=_visitor(VISITOR_A))

    assert response.status_code == 202
    data = response.json['data']
    assert response.json['success'] is True
    assert data['status'] == 'thinking' and valid_ticket_id(data['ticket'])
    assert data['budget_seconds'] == 240
    assert data['poll'] == f'/api/parthenon/ticket/{data["ticket"]}'
    assert response.headers['Cache-Control'] == 'no-store'

    ticket = follow(client, data['ticket'])
    assert ticket['status'] == 'done' and ticket['http_status'] == 200
    assert ticket['error'] is None and ticket['code'] is None
    assert ticket['result'] == {'success': True, 'data': {
        'answer': 'Know thyself.', 'from_memory': True, 'lang': 'en', 'speaker': {'name': 'Socrates'},
    }}
    assert speaker == [EXHIBIT_SIM]


@pytest.mark.parametrize('endpoint, url, body', QUESTIONS)
def test_the_ticket_holds_exactly_what_the_route_answers_directly(city, endpoint, url, body):
    body = {**body, 'lang': 'zh', 'note': '认识你自己'}
    city.env(PARTHENON_QUESTION_TICKETS=0)
    direct_app = city.app()
    _stub(direct_app, endpoint)
    direct = direct_app.test_client().post(url, json=body, headers=_visitor(VISITOR_A))

    city.env(PARTHENON_QUESTION_TICKETS=1)
    app = city.app()
    _stub(app, endpoint)
    answered = ask(app.test_client(), url, body, _visitor(VISITOR_A))

    assert isinstance(answered, TicketAnswer)
    assert answered.status_code == direct.status_code == 200
    assert answered.json == direct.json
    assert answered.json['data']['body'] == body  # the body reached the route whole


def test_the_oracles_draft_comes_by_ticket_as_the_route_gives_it(city, monkeypatch):
    class Oracle:
        def draft(self, stage, fill):
            return {'title': stage['title'], 'filled': list(fill or []), 'speakers': [], 'audience': []}

    monkeypatch.setattr(parthenon_api, 'StageOracle', Oracle)
    body = {'stage': {'title': 'The well at night'}, 'fill': ['audience']}
    client = city.client()

    answered = ask(client, '/api/parthenon/stage/draft', body, _visitor(VISITOR_A))

    assert answered.status_code == 200
    assert answered.json == {'success': True, 'data': {
        'title': 'The well at night', 'filled': ['audience'], 'speakers': [], 'audience': [],
    }}


def test_a_silent_oracle_is_a_failed_ticket_with_the_routes_own_answer(city, monkeypatch):
    class Oracle:
        def draft(self, stage, fill):
            raise OracleUnavailableError('The Oracle is silent.')

    monkeypatch.setattr(parthenon_api, 'StageOracle', Oracle)
    client = city.client()

    answered = ask(client, '/api/parthenon/stage/draft', {'stage': {}}, _visitor(VISITOR_A))

    assert answered.status_code == 503
    assert answered.ticket['status'] == 'failed'
    assert answered.json == {'success': False, 'error': 'The Oracle is silent.'}
    assert answered.ticket['error'] == 'The Oracle is silent.' and answered.ticket['code'] is None


def test_a_refused_question_fails_its_ticket_and_is_given_back(city, speaker):
    city.env(PARTHENON_QUESTIONS_PER_HOUR=1)
    client = city.client()

    refused = ask(client, SPEAKER_URL, {'question': '   '}, _visitor(VISITOR_A))

    assert refused.ticket['status'] == 'failed' and refused.status_code == 400
    assert refused.json['success'] is False and refused.ticket['error'] == refused.json['error']
    # Given back: the one question of the hour is still there.
    assert ask(client, SPEAKER_URL, {'question': 'Why?'}, _visitor(VISITOR_A)).status_code == 200


def test_an_answer_that_says_it_failed_is_a_failed_ticket(city):
    app = city.app()
    app.view_functions['simulation.interview_agent'] = lambda: jsonify({
        'success': False, 'data': {'success': False, 'error': 'The citizen did not answer.'},
    })

    answered = ask(app.test_client(), '/api/simulation/interview',
                   {'simulation_id': EXHIBIT_SIM, 'agent_id': 0, 'prompt': 'Why?'}, _visitor(VISITOR_A))

    assert answered.ticket['status'] == 'failed' and answered.status_code == 200
    assert answered.json['data']['error'] == 'The citizen did not answer.'
    assert answered.ticket['error']  # the city's words when the answer names none


def test_a_question_the_city_stumbles_over_leaves_no_trace(city):
    app = city.app()

    def broken():
        raise RuntimeError('/Users/someone/secret/path exploded')

    app.view_functions['report.chat_with_report_agent'] = broken

    answered = ask(app.test_client(), '/api/report/chat', {'simulation_id': EXHIBIT_SIM, 'message': 'Why?'},
                   _visitor(VISITOR_A))

    assert answered.ticket['status'] == 'failed' and answered.status_code == 500
    text = json.dumps(answered.ticket)
    assert '/Users' not in text and 'Traceback' not in text and 'exploded' not in text
    assert answered.ticket['error'] == 'The city stumbled. Try again in a moment.'


# ================================================================== its own budget

def test_the_question_thinks_in_its_own_thread_within_its_budget(city):
    city.env(PARTHENON_QUESTION_SECONDS=100)
    app = city.app()
    seen = []

    def view():
        seen.append((threading.current_thread().name, time_budget.remaining()))
        return jsonify({'success': True, 'data': {}})

    app.view_functions['report.chat_with_report_agent'] = view
    client = app.test_client()

    answered = ask(client, '/api/report/chat', {'simulation_id': EXHIBIT_SIM, 'message': 'Why?'},
                   _visitor(VISITOR_A))

    assert answered.status_code == 200
    name, left = seen[0]
    assert name == 'parthenon-question' and 95 < left <= 100
    assert time_budget.remaining() is None  # the request that handed it out had none


def test_the_default_budget_is_four_minutes(city):
    app = city.app()
    seen = []
    app.view_functions['parthenon.draft_stage'] = lambda: (seen.append(time_budget.remaining()), jsonify({}))[1]

    ask(app.test_client(), '/api/parthenon/stage/draft', {'stage': {}}, _visitor(VISITOR_A))

    assert 235 < seen[0] <= 240


def _spends_the_budget():
    time_budget.begin(0)
    try:
        time_budget.call_seconds()
    except time_budget.TimeBudgetSpent as error:
        return jsonify({'success': False, 'error': str(error), 'traceback': 'Traceback ...'}), 500
    return jsonify({'success': True})


def test_a_question_that_runs_out_of_time_fails_calmly_and_is_given_back(city):
    city.env(PARTHENON_QUESTIONS_PER_HOUR=1)
    app = city.app()
    app.view_functions['report.chat_with_report_agent'] = _spends_the_budget
    client = app.test_client()
    body = {'simulation_id': EXHIBIT_SIM, 'message': 'Why?'}

    first = ask(client, '/api/report/chat', body, _visitor(VISITOR_A, **{'Accept-Language': 'en-US,en;q=0.9'}))

    assert first.ticket['status'] == 'failed' and first.status_code == 503
    assert first.ticket['code'] == 'slow_down' and first.ticket['retry_after_seconds'] == 60
    assert first.json == {
        'success': False, 'code': 'slow_down', 'retry_after_seconds': 60,
        'error': 'The city took too long over that and set it down. Ask again in a little while.',
    }
    second = ask(client, '/api/report/chat', body, _visitor(VISITOR_A, **{'Accept-Language': 'zh-CN'}))
    assert second.status_code == 503 and '城邦' in second.ticket['error']


def test_a_ticket_still_thinking_past_its_budget_is_given_up_calmly(city):
    city.env(PARTHENON_QUESTION_SECONDS=60)
    app = city.app()
    clock = Clock()
    _desk(app).clock = clock
    started, release = threading.Event(), threading.Event()
    app.view_functions['parthenon.ask_the_speaker'] = _blocked_view(started, release)
    client = app.test_client()

    handed = client.post(SPEAKER_URL, json={'question': 'Why?'}, headers=_visitor(VISITOR_A, **{'Accept-Language': 'zh'}))
    ticket_id = handed.json['data']['ticket']
    assert started.wait(5)

    clock.now += 60 + tickets.GRACE_SECONDS - 1
    assert client.get(f'/api/parthenon/ticket/{ticket_id}').json['status'] == 'thinking'
    clock.now += 2
    read = client.get(f'/api/parthenon/ticket/{ticket_id}').json
    assert read['status'] == 'failed' and read['code'] == 'slow_down' and read['http_status'] == 503
    assert '城邦' in read['error'] and read['result']['code'] == 'slow_down'

    release.set()
    time.sleep(0.2)
    # A late answer does not change what the page was told.
    assert client.get(f'/api/parthenon/ticket/{ticket_id}').json['status'] == 'failed'


# ================================================================== reading a ticket

def test_a_ticket_expires_after_half_an_hour(city, speaker):
    app = city.app()
    clock = Clock()
    _desk(app).clock = clock
    client = app.test_client()
    handed = client.post(SPEAKER_URL, json={'question': 'Why?'}, headers=_visitor(VISITOR_A))
    ticket_id = handed.json['data']['ticket']
    assert follow(client, ticket_id)['status'] == 'done'

    clock.now += 30 * 60 - 1
    assert client.get(f'/api/parthenon/ticket/{ticket_id}').status_code == 200
    clock.now += 2
    gone = client.get(f'/api/parthenon/ticket/{ticket_id}')

    assert gone.status_code == 404
    assert gone.json == {
        'success': False, 'status': 'failed', 'result': None, 'code': 'ticket_lost',
        'error': 'The city lost the thread of that question. Ask it again.',
    }
    assert gone.headers['Cache-Control'] == 'no-store'
    assert len(_desk(app)) == 0


@pytest.mark.parametrize('ticket_id', ['a' * 32, 'short', 'x' * 65, 'bad$id' * 5])
def test_an_unknown_ticket_is_lost(city, ticket_id):
    response = city.client().get(f'/api/parthenon/ticket/{ticket_id}',
                                 headers={'Accept-Language': 'zh'})

    assert response.status_code == 404
    assert response.json['code'] == 'ticket_lost' and response.json['status'] == 'failed'
    assert '城邦' in response.json['error']


def test_tickets_are_unguessable_and_read_by_anyone_who_holds_one(city, speaker):
    client = city.client()
    ids = [client.post(SPEAKER_URL, json={'question': 'Why?'}, headers=_visitor(VISITOR_A)).json['data']['ticket']
           for _ in range(3)]

    assert len(set(ids)) == 3
    assert all(valid_ticket_id(ticket_id) and len(ticket_id) >= 32 for ticket_id in ids)
    # No invite, no owner key: the id is the key.
    read = client.get(f'/api/parthenon/ticket/{ids[0]}', headers=_visitor(VISITOR_B))
    assert read.status_code == 200 and read.headers['Cache-Control'] == 'no-store'


# ================================================================== counted when handed out

def test_a_ticket_counts_against_the_hour_when_it_is_handed_out(city):
    city.env(PARTHENON_QUESTIONS_PER_HOUR=1)
    app = city.app()
    started, release = threading.Event(), threading.Event()
    app.view_functions['parthenon.ask_the_speaker'] = _blocked_view(started, release)
    client = app.test_client()

    handed = client.post(SPEAKER_URL, json={'question': 'Why?'}, headers=_visitor(VISITOR_A))
    assert handed.status_code == 202 and started.wait(5)
    second = client.post(SPEAKER_URL, json={'question': 'And?'}, headers=_visitor(VISITOR_A))

    assert second.status_code == 429 and second.json['code'] == 'slow_down'
    release.set()
    assert follow(client, handed.json['data']['ticket'])['status'] == 'done'
    # An answered question stays counted.
    assert client.post(SPEAKER_URL, json={'question': 'Why?'}, headers=_visitor(VISITOR_A)).status_code == 429


def test_the_city_holds_only_so_many_questions_at_once(city):
    city.env(PARTHENON_TICKETS_IN_FLIGHT=1, PARTHENON_QUESTIONS_PER_HOUR=2)
    app = city.app()
    started, release = threading.Event(), threading.Event()
    app.view_functions['parthenon.ask_the_speaker'] = _blocked_view(started, release)
    client = app.test_client()

    first = client.post(SPEAKER_URL, json={'question': 'Why?'}, headers=_visitor(VISITOR_A))
    assert first.status_code == 202 and started.wait(5)
    busy = client.post(SPEAKER_URL, json={'question': 'Why?'}, headers=_visitor(VISITOR_B))

    assert busy.status_code == 429 and busy.json['code'] == 'slow_down'
    assert busy.json['retry_after_seconds'] == tickets.BUSY_RETRY_SECONDS
    assert busy.json['error'] == 'Many questions are before the city at once. Ask again in a moment.'
    release.set()
    follow(client, first.json['data']['ticket'])
    # The busy refusal gave B's question back: B still has both of the hour.
    for _ in range(2):
        assert ask(client, SPEAKER_URL, {'question': 'Why?'}, _visitor(VISITOR_B)).status_code == 200


def test_the_keepers_questions_come_by_ticket_too(city, speaker):
    city.env(PARTHENON_QUESTIONS_PER_HOUR=0)
    client = city.client()

    handed = client.post(SPEAKER_URL, json={'question': 'Why?'}, headers={'X-Parthenon-Admin': ADMIN_KEY})

    assert handed.status_code == 202
    assert follow(client, handed.json['data']['ticket'])['status'] == 'done'


def test_the_answer_is_handed_out_before_the_city_has_thought(city):
    app = city.app()
    started, release = threading.Event(), threading.Event()
    app.view_functions['report.chat_with_report_agent'] = _blocked_view(started, release)
    client = app.test_client()

    begun = time.monotonic()
    handed = client.post('/api/report/chat', json={'simulation_id': EXHIBIT_SIM, 'message': 'Why?'},
                         headers=_visitor(VISITOR_A))
    assert handed.status_code == 202 and time.monotonic() - begun < 2
    assert started.wait(5)
    assert client.get(handed.json['data']['poll']).json['status'] == 'thinking'
    release.set()
    assert follow(client, handed.json['data']['ticket'])['result'] == {'success': True, 'data': {'answer': 'At last.'}}


def test_the_ticket_holds_the_open_square_while_it_thinks(city):
    app = city.app()
    started, release = threading.Event(), threading.Event()
    app.view_functions['simulation.interview_agents_batch'] = _blocked_view(started, release)
    client = app.test_client()

    handed = client.post('/api/simulation/interview/batch', json={
        'simulation_id': EXHIBIT_SIM, 'interviews': [{'agent_id': 0, 'prompt': 'Why?'}],
    }, headers=_visitor(VISITOR_A))
    assert started.wait(5)
    assert envs.busy(EXHIBIT_SIM)
    release.set()
    follow(client, handed.json['data']['ticket'])
    assert not envs.busy(EXHIBIT_SIM)


def test_refusals_at_the_door_come_at_once(city, speaker):
    app = city.app()
    client = app.test_client()

    too_long = client.post(SPEAKER_URL, json={'question': 'why ' * 2000}, headers=_visitor(VISITOR_A))

    assert too_long.status_code == 413 and too_long.json['code'] == 'too_long'
    assert speaker == [] and len(_desk(app)) == 0


# ================================================================== without tickets, and the status

def test_without_tickets_a_question_is_answered_directly(city, speaker):
    city.env(PARTHENON_QUESTION_TICKETS='off')
    client = city.client()

    response = client.post(SPEAKER_URL, json={'question': 'Why?'}, headers=_visitor(VISITOR_A))

    assert response.status_code == 200 and response.json['data']['answer'] == 'Know thyself.'


def test_the_status_tells_the_page_how_long_a_question_may_take(city):
    limits = city.client().get('/api/parthenon/status').json['data']['limits']
    assert limits['question_tickets'] is True and limits['question_seconds'] == 240

    city.env(PARTHENON_QUESTION_TICKETS=0, PARTHENON_REQUEST_SECONDS=85)
    limits = city.client().get('/api/parthenon/status').json['data']['limits']
    assert limits['question_tickets'] is False and limits['question_seconds'] == 85


@pytest.mark.parametrize('raw, expected', [(None, 240), ('100', 100), ('5', 240), ('99999', 1500)])
def test_the_question_budget_setting(raw, expected):
    from app.public.settings import load_settings

    env = {'PARTHENON_PUBLIC': '1'}
    if raw is not None:
        env['PARTHENON_QUESTION_SECONDS'] = raw
    assert load_settings(env).question_seconds == expected


# ================================================================== the desk itself

def test_the_desk_keeps_what_the_thread_answered():
    clock = Clock()
    desk = TicketDesk(clock=clock)
    ticket = desk.open('parthenon.ask_the_speaker', 240, 'en')

    assert desk.read(ticket.id)['status'] == 'thinking' and desk.thinking() == 1
    clock.now += 12.5
    desk.settle(ticket.id, 200, {'success': True, 'data': {'answer': 'Yes.'}})
    read = desk.read(ticket.id)

    assert read['status'] == 'done' and read['result'] == {'success': True, 'data': {'answer': 'Yes.'}}
    assert read['elapsed_seconds'] == 12.5 and desk.thinking() == 0
    desk.settle(ticket.id, 500, None)  # settled once
    assert desk.read(ticket.id)['status'] == 'done'


@pytest.mark.parametrize('status, payload, expected', [
    (200, {'success': True}, ('done', None, None, None)),
    (200, {'data': {}}, ('done', None, None, None)),
    (200, {'success': False, 'error': 'No.'}, ('failed', 'No.', None, None)),
    (429, {'success': False, 'error': 'Wait.', 'code': 'slow_down', 'retry_after_seconds': 60},
     ('failed', 'Wait.', 'slow_down', 60)),
    (500, None, ('failed', None, None, None)),
    (200, ['not', 'a', 'dict'], ('failed', None, None, None)),
])
def test_what_an_answer_comes_to(status, payload, expected):
    assert outcome(status, payload) == expected


def test_the_desk_forgets_the_oldest_answers_first(monkeypatch):
    monkeypatch.setattr(tickets, 'MAX_TICKETS', 3)
    desk = TicketDesk(clock=Clock())
    kept = [desk.open('x', 240, 'en') for _ in range(3)]
    for ticket in kept[:2]:
        desk.settle(ticket.id, 200, {'success': True})

    newest = desk.open('x', 240, 'en')

    assert desk.read(kept[0].id) is None
    assert desk.read(kept[1].id) is not None and desk.read(kept[2].id)['status'] == 'thinking'
    assert desk.read(newest.id)['status'] == 'thinking'


def test_the_copied_request_carries_its_body_and_nothing_of_the_old_request():
    environ = {
        'REQUEST_METHOD': 'POST', 'PATH_INFO': '/api/report/chat', 'CONTENT_LENGTH': '99',
        'HTTP_TRANSFER_ENCODING': 'chunked', 'werkzeug.request': object(),
        'werkzeug.debug.preserve_context': object(), tickets.WORK_KEY: object(),
        'HTTP_ACCEPT_LANGUAGE': 'zh',
    }

    copied = work_environ(environ, b'{"message": "\xe4\xbd\xa0"}')

    assert copied['wsgi.input'].read() == b'{"message": "\xe4\xbd\xa0"}'
    assert copied['CONTENT_LENGTH'] == str(len(b'{"message": "\xe4\xbd\xa0"}'))
    for key in ('werkzeug.request', 'werkzeug.debug.preserve_context', tickets.WORK_KEY, 'HTTP_TRANSFER_ENCODING'):
        assert key not in copied
    assert copied['HTTP_ACCEPT_LANGUAGE'] == 'zh' and 'werkzeug.request' in environ


def test_a_question_with_no_thread_to_think_in_is_given_back(city, monkeypatch, speaker):
    city.env(PARTHENON_QUESTIONS_PER_HOUR=1)
    app = city.app()
    client = app.test_client()
    real_start = tickets.start_thread
    refusals = [RuntimeError("can't start new thread")]

    def start_thread(*args):
        if refusals:
            raise refusals.pop()
        return real_start(*args)

    monkeypatch.setattr(tickets, 'start_thread', start_thread)
    refused = client.post(SPEAKER_URL, json={'question': 'Why?'}, headers=_visitor(VISITOR_A))

    assert refused.status_code == 429 and refused.json['code'] == 'slow_down'
    assert _desk(app).thinking() == 0 and speaker == []
    # Given back: the one question of the hour is still there.
    assert ask(client, SPEAKER_URL, {'question': 'Why?'}, _visitor(VISITOR_A)).status_code == 200
