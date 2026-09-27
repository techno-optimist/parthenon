"""The public steps (PARTHENON_PUBLIC=1): owner keys, limits, the shelf, and nothing leaking.

Every test runs in temp folders: projects, reports and voices here, simulations
through conftest. Views that would reach an LLM, a simulator or the bridge are
replaced by stubs that report what reached them.
"""

import hashlib
import io
import json
import os
import threading
import time

import pytest
from flask import jsonify, request

import app.public as public_pkg
from app import create_app
from app.api import graph as graph_api
from app.api import parthenon as parthenon_api
from app.api import simulation as simulation_api
from app.config import Config
from app.models.project import ProjectManager
from app.public import guard as guard_module
from app.public import lineage
from app.public.guard import ROUTES
from app.public.site import register_site
from app.services import chronicle_film, citizen_portraits
from app.services.report_agent import ReportManager
from app.services.simulation_manager import SimulationManager


ADMIN_KEY = 'keeper-key-for-tests-0123456789abcdef'
OWNER_TOKEN = 'owner-token-for-tests-0123456789abcdef'
OTHER_TOKEN = 'another-token-for-tests-0123456789abcd'
EXHIBIT_PROJECT = 'proj_527f80721255'
EXHIBIT_SIM = 'sim_2c79002f1b0c'
EXHIBIT_REPORT = 'report_53d558ea0a3d'
OWNED_PROJECT = 'proj_visitor00001'
OWNED_SIM = 'sim_visitor00001'
OWNED_REPORT = 'report_visitor00001'
UNLISTED_PROJECT = 'proj_stranger0001'
UNLISTED_SIM = 'sim_stranger0001'
UNLISTED_REPORT = 'report_stranger0001'
VISITOR_A = '203.0.113.5'
VISITOR_B = '198.51.100.7'
VISITOR_C = '192.0.2.44'
ONTOLOGY = {'entity_types': [{'name': 'Citizen'}], 'edge_types': [], 'analysis_summary': 'A city.'}
KEYED_ENVS = ('XAI_API_KEY', 'OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'OPENROUTER_API_KEY', 'GROK_BRIDGE_TOKEN_FILE')


def _sha(token):
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump(data, handle)


def make_project(project_id, token=None, graph_id=None, created_at='2026-09-01T00:00:00'):
    record = {
        'project_id': project_id, 'name': project_id, 'status': 'graph_completed',
        'created_at': created_at, 'updated_at': created_at, 'graph_id': graph_id,
        'simulation_requirement': 'Should Athens listen?', 'files': [],
    }
    if token:
        record['owner_token_hash'] = _sha(token)
    _write_json(os.path.join(ProjectManager.PROJECTS_DIR, project_id, 'project.json'), record)


def make_simulation(simulation_id, project_id, graph_id=None, status='ready'):
    _write_json(os.path.join(SimulationManager.SIMULATION_DATA_DIR, simulation_id, 'state.json'), {
        'simulation_id': simulation_id, 'project_id': project_id,
        'graph_id': graph_id or f'graph_{project_id}', 'status': status,
        'created_at': '2026-09-02T00:00:00', 'updated_at': '2026-09-02T00:00:00',
    })


def make_report(report_id, simulation_id):
    _write_json(os.path.join(ReportManager.REPORTS_DIR, report_id, 'meta.json'), {
        'report_id': report_id, 'simulation_id': simulation_id, 'graph_id': 'g',
        'simulation_requirement': 'Should Athens listen?', 'status': 'completed',
        'created_at': '2026-09-03T00:00:00',
    })


class City:
    """The public app under test, its env and its switches."""

    def __init__(self, tmp_path, monkeypatch):
        self.tmp_path = tmp_path
        self.monkeypatch = monkeypatch
        self.data = tmp_path / 'data'
        self.features = {'portraits': False, 'film': False, 'voice': False}
        self.runs = {'count': 0}

    def env(self, **values):
        for name, value in values.items():
            self.monkeypatch.setenv(name, str(value))

    def app(self, public=True, site=False):
        if public:
            self.monkeypatch.setenv('PARTHENON_PUBLIC', '1')
        else:
            self.monkeypatch.delenv('PARTHENON_PUBLIC', raising=False)
        app = create_app()
        app.config.update(TESTING=True)
        if site:
            register_site(app, str(self.tmp_path / 'dist'))
        return app

    def client(self, public=True):
        return self.app(public=public).test_client()


@pytest.fixture
def city(tmp_path, monkeypatch):
    uploads = tmp_path / 'data' / 'uploads'
    monkeypatch.setattr(ProjectManager, 'PROJECTS_DIR', str(uploads / 'projects'))
    monkeypatch.setattr(ReportManager, 'REPORTS_DIR', str(uploads / 'reports'))
    monkeypatch.setattr(Config, 'UPLOAD_FOLDER', str(uploads))
    monkeypatch.setattr(Config, 'LLM_BASE_URL', 'https://llm.example.test/v1')
    # Never the owner's memory database: Zep semantics (conftest) with no network.
    monkeypatch.setattr(Config, 'LOCAL_MEMORY_DB_PATH', str(tmp_path / 'memory' / 'local_memory.sqlite3'))
    monkeypatch.setattr(parthenon_api, '_zep_key_status', lambda: (True, None))
    monkeypatch.setattr(simulation_api, '_get_report_id_for_simulation', lambda _sid: None)
    for name in list(os.environ):
        if name.startswith('PARTHENON_') or name in KEYED_ENVS:
            monkeypatch.delenv(name, raising=False)
    world = City(tmp_path, monkeypatch)
    monkeypatch.setenv('PARTHENON_DATA_DIR', str(world.data))
    monkeypatch.setenv('PARTHENON_ADMIN_KEY', ADMIN_KEY)
    monkeypatch.setenv('PARTHENON_TRUST_PROXY', '1')
    monkeypatch.setattr(guard_module, 'current_features', lambda: dict(world.features))
    monkeypatch.setattr(guard_module, 'running_runs', lambda exclude=None: world.runs['count'])
    monkeypatch.setattr(public_pkg, 'running_runs', lambda exclude=None: world.runs['count'])
    return world


def _stub(app, endpoint, status=200):
    """Replace a view: it answers what reached it, so the guard's pass (and edits) show."""

    def view(**kwargs):
        body = request.get_json(silent=True) if request.is_json else None
        return jsonify({'success': True, 'data': {'passed': True, 'body': body, 'args': kwargs}}), status

    app.view_functions[endpoint] = view


def _visitor(ip, **extra):
    return {'CF-Connecting-IP': ip, **extra}


class TicketAnswer:
    """A question's answer as the page ends up with it: the route's own status and body."""

    def __init__(self, ticket):
        self.ticket = ticket
        self.status_code = ticket['http_status']
        self.json = ticket['result']


def follow(client, ticket_id, timeout=10.0):
    """Read a ticket until it is no longer thinking; its final reading."""

    deadline = time.monotonic() + timeout
    while True:
        read = client.get(f'/api/parthenon/ticket/{ticket_id}')
        assert read.status_code == 200, read.json
        if read.json['status'] != 'thinking':
            return read.json
        assert time.monotonic() < deadline, 'the ticket is still thinking'
        time.sleep(0.01)


def ask(client, url, body, headers=None, timeout=10.0):
    """Put a question as the page does: a refusal comes at once, an answer by its ticket."""

    response = client.post(url, json=body, headers=headers or {})
    if response.status_code != 202:
        return response
    assert response.json['data']['status'] == 'thinking'
    return TicketAnswer(follow(client, response.json['data']['ticket'], timeout))


def _scroll(text='The steps are warm in the sun.', name='scroll.md', requirement='Should Athens listen?'):
    return {
        'simulation_requirement': requirement,
        'project_name': 'A test gathering',
        'files': (io.BytesIO(text.encode('utf-8')), name),
    }


@pytest.fixture
def fake_ontology(monkeypatch):
    """The scroll is read at once, inline (the public Hearing's task), and its Web is only noted."""

    class FakeGenerator:
        def generate(self, **_kwargs):
            return dict(ONTOLOGY)

    webs = []
    monkeypatch.setattr(graph_api, 'OntologyGenerator', FakeGenerator)
    monkeypatch.setattr(graph_api, '_in_background', lambda target, _name: target())
    monkeypatch.setattr(graph_api, '_build_after_hearing',
                        lambda _app, project_id, task_id: webs.append((project_id, task_id)))
    return webs


def _begin(client, ip=VISITOR_A, **scroll):
    return client.post(
        '/api/graph/ontology/generate', data=_scroll(**scroll),
        content_type='multipart/form-data', headers=_visitor(ip),
    )


# ------------------------------------------------------------------ local mode stays as it was

def test_local_mode_hands_out_no_key_and_asks_for_none(city, fake_ontology):
    client = city.client(public=False)

    response = _begin(client)

    assert response.status_code == 200
    data = response.json['data']
    assert 'owner_token' not in data
    with open(os.path.join(ProjectManager.PROJECTS_DIR, data['project_id'], 'project.json')) as handle:
        record = json.load(handle)
    assert 'owner_token_hash' not in record
    # Control routes need no key; the view answers as it always has.
    reset = client.post(f'/api/graph/project/{OWNED_PROJECT}/reset')
    assert reset.status_code == 404 and 'code' not in reset.json
    # Debug routes are still there.
    assert client.post('/api/report/tools/search', json={}).status_code == 400
    assert not (city.data / 'parthenon_public.sqlite3').exists()


def test_local_mode_has_no_public_routes(city):
    app = city.app(public=False)
    endpoints = {rule.endpoint for rule in app.url_map.iter_rules()}
    assert not any(endpoint.startswith('public.') for endpoint in endpoints)
    assert 'parthenon_public' not in app.extensions


def test_local_status_reports_public_false(city):
    response = city.client(public=False).get('/api/parthenon/status')

    data = response.json['data']
    assert data['public'] is False
    assert data['limits'] is None
    assert data['provider'] == 'grok-subscription'  # PARTHENON_UPSTREAM unset: the subscription
    assert data['features'] == {'portraits': False, 'film': False, 'voice': False}
    for field in ('memoryBackend', 'zepConfigured', 'zepKeyValid', 'zepProblem',
                  'llmConfigured', 'llmProblem', 'upstream', 'model'):
        assert field in data


def test_local_history_is_not_cut(city):
    make_project(UNLISTED_PROJECT)
    make_simulation(UNLISTED_SIM, UNLISTED_PROJECT)

    ids = [item['simulation_id'] for item in city.client(public=False).get('/api/simulation/history').json['data']]

    assert UNLISTED_SIM in ids


# ------------------------------------------------------------------ every route has a class

def test_every_public_route_is_classified(city):
    app = city.app(site=True)
    unclassified = sorted(
        rule.endpoint for rule in app.url_map.iter_rules() if rule.endpoint not in ROUTES
    )
    assert unclassified == []


def test_an_unclassified_route_is_closed(city):
    app = city.app()

    @app.route('/api/new/thing', methods=['POST'])
    def new_thing():
        return jsonify({'success': True})

    response = app.test_client().post('/api/new/thing')
    assert response.status_code == 404
    assert response.json['code'] == 'not_on_public_steps'


# ------------------------------------------------------------------ owner keys

def test_beginning_hands_back_a_key_and_keeps_only_its_hash(city, fake_ontology):
    client = city.client()

    response = _begin(client)

    assert response.status_code == 200
    data = response.json['data']
    token = data['owner_token']
    assert isinstance(token, str) and len(token) >= 40
    path = os.path.join(ProjectManager.PROJECTS_DIR, data['project_id'], 'project.json')
    with open(path) as handle:
        text = handle.read()
    assert token not in text
    assert json.loads(text)['owner_token_hash'] == _sha(token)
    # The API's view of the project never shows the hash.
    shown = client.get(f"/api/graph/project/{data['project_id']}").get_data(as_text=True)
    assert 'owner_token_hash' not in shown and token not in shown
    # A later save (the build, a reset) keeps the hash.
    project = ProjectManager.get_project(data['project_id'])
    ProjectManager.save_project(project)
    with open(path) as handle:
        assert json.load(handle)['owner_token_hash'] == _sha(token)


@pytest.mark.parametrize('endpoint, method, url, body', [
    ('graph.build_graph', 'post', '/api/graph/build', {'project_id': OWNED_PROJECT}),
    ('graph.reset_project', 'post', f'/api/graph/project/{OWNED_PROJECT}/reset', None),
    ('graph.delete_project', 'delete', f'/api/graph/project/{OWNED_PROJECT}', None),
    ('graph.delete_graph', 'delete', '/api/graph/delete/graph_visitor', None),
    ('simulation.create_simulation', 'post', '/api/simulation/create', {'project_id': OWNED_PROJECT}),
    ('simulation.prepare_simulation', 'post', '/api/simulation/prepare', {'simulation_id': OWNED_SIM}),
    ('simulation.stop_simulation', 'post', '/api/simulation/stop', {'simulation_id': OWNED_SIM}),
    ('simulation.close_simulation_env', 'post', '/api/simulation/close-env', {'simulation_id': OWNED_SIM}),
    ('report.generate_report', 'post', '/api/report/generate', {'simulation_id': OWNED_SIM}),
    ('report.delete_report', 'delete', f'/api/report/{OWNED_REPORT}', None),
    ('parthenon.start_citizen_stances', 'post', f'/api/parthenon/gathering/{OWNED_SIM}/stances', {'force': True}),
])
def test_control_needs_the_gathering_key(city, endpoint, method, url, body):
    make_project(OWNED_PROJECT, token=OWNER_TOKEN, graph_id='graph_visitor')
    make_simulation(OWNED_SIM, OWNED_PROJECT, graph_id='graph_visitor')
    make_report(OWNED_REPORT, OWNED_SIM)
    app = city.app()
    _stub(app, endpoint)
    client = app.test_client()
    send = getattr(client, method)
    kwargs = {'json': body} if body is not None else {}

    nobody = send(url, **kwargs)
    stranger = send(url, headers={'X-Parthenon-Owner': OTHER_TOKEN}, **kwargs)
    owner = send(url, headers={'X-Parthenon-Owner': OWNER_TOKEN}, **kwargs)
    keeper = send(url, headers={'X-Parthenon-Admin': ADMIN_KEY}, **kwargs)

    for refused in (nobody, stranger):
        assert refused.status_code == 403
        assert refused.json['success'] is False and refused.json['code'] == 'not_yours'
    assert owner.status_code == 200 and owner.json['data']['passed'] is True
    assert keeper.status_code == 200 and keeper.json['data']['passed'] is True


def test_an_exhibit_answers_only_to_the_keepers(city):
    make_project(EXHIBIT_PROJECT)  # no owner: shipped with the steps
    make_simulation(EXHIBIT_SIM, EXHIBIT_PROJECT)
    app = city.app()
    _stub(app, 'simulation.stop_simulation')
    client = app.test_client()

    assert client.post('/api/simulation/stop', json={'simulation_id': EXHIBIT_SIM},
                       headers={'X-Parthenon-Owner': OWNER_TOKEN}).status_code == 403
    assert client.post('/api/simulation/stop', json={'simulation_id': EXHIBIT_SIM},
                       headers={'X-Parthenon-Admin': ADMIN_KEY}).status_code == 200
    assert client.post('/api/simulation/stop', json={'simulation_id': EXHIBIT_SIM},
                       headers={'X-Parthenon-Admin': 'not-the-key'}).status_code == 403


def test_reads_and_the_city_words_are_open(city):
    make_project(OWNED_PROJECT, token=OWNER_TOKEN)
    make_simulation(OWNED_SIM, OWNED_PROJECT)
    client = city.client()

    assert client.get(f'/api/simulation/{OWNED_SIM}').status_code == 200
    assert client.get(f'/api/graph/project/{OWNED_PROJECT}').status_code == 200
    assert client.get(f'/api/parthenon/gathering/{OWNED_SIM}').status_code == 200


def test_malformed_ids_are_not_found(city):
    client = city.client()
    response = client.get('/api/simulation/..%2F..%2Fetc/profiles')
    assert response.status_code == 404
    response = client.get('/api/report/not-a-report')
    assert response.status_code == 404 and response.json['success'] is False


def test_a_crowd_is_drawn_from_its_own_web(city):
    make_project(OWNED_PROJECT, token=OWNER_TOKEN, graph_id='graph_visitor')
    app = city.app()
    _stub(app, 'simulation.create_simulation')
    body = {'project_id': OWNED_PROJECT, 'graph_id': 'graph_of_an_exhibit'}

    response = app.test_client().post('/api/simulation/create', json=body,
                                      headers={'X-Parthenon-Owner': OWNER_TOKEN})

    assert response.json['data']['body'] == {'project_id': OWNED_PROJECT}


def test_build_knobs_are_clamped(city):
    make_project(OWNED_PROJECT, token=OWNER_TOKEN)
    app = city.app()
    _stub(app, 'graph.build_graph')

    response = app.test_client().post('/api/graph/build', json={
        'project_id': OWNED_PROJECT, 'chunk_size': 1, 'chunk_overlap': 9999,
    }, headers={'X-Parthenon-Owner': OWNER_TOKEN})

    assert response.json['data']['body']['chunk_size'] == 300
    assert response.json['data']['body']['chunk_overlap'] == 200


# ------------------------------------------------------------------ beginning a gathering: the daily limits

def test_daily_limits_per_visitor_and_site_wide(city, fake_ontology):
    city.env(PARTHENON_DAILY_GATHERINGS=2, PARTHENON_DAILY_PER_VISITOR=1)
    client = city.client()

    assert _begin(client, VISITOR_A).status_code == 200
    again = _begin(client, VISITOR_A)
    assert again.status_code == 429
    assert again.json['code'] == 'come_back_tomorrow'
    assert again.json['retry_after_seconds'] > 0
    assert again.headers['Retry-After'] == str(again.json['retry_after_seconds'])
    assert 'visitor' in again.json['error'] or 'You have' in again.json['error']

    assert _begin(client, VISITOR_B).status_code == 200
    full = _begin(client, VISITOR_C)
    assert full.status_code == 429 and full.json['code'] == 'come_back_tomorrow'
    assert 'Athens has gathered' in full.json['error']

    # A restart keeps the day's counts (they live under PARTHENON_DATA_DIR).
    assert _begin(city.client(), VISITOR_C).status_code == 429


def test_a_refused_scroll_costs_nothing(city, fake_ontology):
    city.env(PARTHENON_DAILY_PER_VISITOR=1)
    client = city.client()

    no_file = client.post('/api/graph/ontology/generate', data={'simulation_requirement': 'Q?'},
                          content_type='multipart/form-data', headers=_visitor(VISITOR_A))
    assert no_file.status_code == 400
    assert _begin(client, VISITOR_A).status_code == 200


def test_the_keepers_are_not_counted(city, fake_ontology):
    city.env(PARTHENON_DAILY_GATHERINGS=0)
    client = city.client()

    refused = _begin(client)
    assert refused.status_code == 429
    keeper = client.post('/api/graph/ontology/generate', data=_scroll(), content_type='multipart/form-data',
                         headers=_visitor(VISITOR_A, **{'X-Parthenon-Admin': ADMIN_KEY}))
    assert keeper.status_code == 200


def test_visitors_are_kept_as_hashes(city, fake_ontology):
    client = city.client()
    assert _begin(client, VISITOR_A).status_code == 200

    with open(city.data / 'parthenon_public.sqlite3', 'rb') as handle:
        raw = handle.read()
    assert VISITOR_A.encode() not in raw


def test_the_visitor_is_the_cloudflare_address_then_the_first_forwarded(city, fake_ontology):
    city.env(PARTHENON_DAILY_PER_VISITOR=1, PARTHENON_DAILY_GATHERINGS=10)
    client = city.client()

    first = client.post('/api/graph/ontology/generate', data=_scroll(), content_type='multipart/form-data',
                        headers={'X-Forwarded-For': f'{VISITOR_A}, 10.0.0.1'})
    assert first.status_code == 200
    # The same visitor by X-Forwarded-For: refused.
    assert client.post('/api/graph/ontology/generate', data=_scroll(), content_type='multipart/form-data',
                       headers={'X-Forwarded-For': VISITOR_A}).status_code == 429
    # CF-Connecting-IP wins over X-Forwarded-For.
    assert client.post('/api/graph/ontology/generate', data=_scroll(), content_type='multipart/form-data',
                       headers={'X-Forwarded-For': VISITOR_A, 'CF-Connecting-IP': VISITOR_B}).status_code == 200


def test_without_trust_the_forwarded_headers_are_ignored(city, fake_ontology):
    city.env(PARTHENON_DAILY_PER_VISITOR=1, PARTHENON_DAILY_GATHERINGS=10, PARTHENON_TRUST_PROXY=0)
    client = city.client()

    assert _begin(client, VISITOR_A).status_code == 200
    # A different claimed address is the same peer.
    assert _begin(client, VISITOR_B).status_code == 429


def test_a_long_scroll_is_refused_and_forgotten(city, fake_ontology):
    city.env(PARTHENON_MAX_SCROLL_CHARS=50, PARTHENON_DAILY_PER_VISITOR=1)
    client = city.client()

    response = _begin(client, text='x' * 51)

    assert response.status_code == 413
    assert response.json['code'] == 'too_long'
    assert '50' in response.json['error']
    assert os.listdir(ProjectManager.PROJECTS_DIR) == []
    assert _begin(client, text='short').status_code == 200  # the refused scroll was not counted


def test_a_heavy_upload_is_refused(city, fake_ontology):
    city.env(PARTHENON_MAX_UPLOAD_MB=1)
    client = city.client()

    response = _begin(client, text='x' * (1024 * 1024 + 10))

    assert response.status_code == 413
    assert response.json['code'] == 'too_long'


def test_a_heap_of_scrolls_is_refused(city, fake_ontology):
    client = city.client()
    data = {'simulation_requirement': 'Q?', 'files': [
        (io.BytesIO(b'words'), f'scroll{i}.md') for i in range(6)
    ]}

    response = client.post('/api/graph/ontology/generate', data=data, content_type='multipart/form-data',
                           headers=_visitor(VISITOR_A))

    assert response.status_code == 413 and response.json['code'] == 'too_long'


def test_the_refusal_speaks_chinese_when_asked(city, fake_ontology):
    city.env(PARTHENON_DAILY_GATHERINGS=0)
    client = city.client()

    response = client.post('/api/graph/ontology/generate', data=_scroll(), content_type='multipart/form-data',
                           headers=_visitor(VISITOR_A, **{'Accept-Language': 'zh'}))

    assert response.status_code == 429
    assert '雅典' in response.json['error']


# ------------------------------------------------------------------ questions

@pytest.fixture
def speaker(monkeypatch):
    calls = []

    def answer(simulation_id, **kwargs):
        calls.append(simulation_id)
        return {'answer': 'Know thyself.', 'lang': 'en', 'speaker': {'name': 'Socrates'}}

    monkeypatch.setattr(parthenon_api.symposium_memory, 'answer_as_speaker', answer)
    return calls


def test_questions_are_counted_per_visitor_per_hour(city, speaker):
    city.env(PARTHENON_QUESTIONS_PER_HOUR=2)
    client = city.client()
    url = f'/api/parthenon/gathering/{EXHIBIT_SIM}/speaker'

    for _ in range(2):
        assert ask(client, url, {'question': 'Why?'}, _visitor(VISITOR_A)).status_code == 200
    third = ask(client, url, {'question': 'Why?'}, _visitor(VISITOR_A))

    assert third.status_code == 429
    assert third.json['code'] == 'slow_down' and 0 < third.json['retry_after_seconds'] <= 3600
    assert len(speaker) == 2
    assert ask(client, url, {'question': 'Why?'}, _visitor(VISITOR_B)).status_code == 200
    assert ask(client, url, {'question': 'Why?'},
               _visitor(VISITOR_A, **{'X-Parthenon-Admin': ADMIN_KEY})).status_code == 200


def test_a_question_that_fails_its_checks_is_given_back(city, speaker):
    city.env(PARTHENON_QUESTIONS_PER_HOUR=1)
    client = city.client()
    url = f'/api/parthenon/gathering/{EXHIBIT_SIM}/speaker'

    assert ask(client, url, {'question': ''}, _visitor(VISITOR_A)).status_code == 400
    assert ask(client, url, {'question': 'Why?'}, _visitor(VISITOR_A)).status_code == 200


def test_a_long_question_is_too_long(city, speaker):
    client = city.client()

    response = client.post(f'/api/parthenon/gathering/{EXHIBIT_SIM}/speaker',
                           json={'question': 'why ' * 2000}, headers=_visitor(VISITOR_A))

    assert response.status_code == 413 and response.json['code'] == 'too_long'
    assert speaker == []


def test_the_symposium_and_the_scribe_share_the_hourly_count(city):
    city.env(PARTHENON_QUESTIONS_PER_HOUR=2)
    app = city.app()
    for endpoint in ('simulation.interview_agents_batch', 'report.chat_with_report_agent',
                     'parthenon.draft_stage'):
        _stub(app, endpoint)
    client = app.test_client()

    assert ask(client, '/api/simulation/interview/batch', {
        'simulation_id': EXHIBIT_SIM, 'interviews': [{'agent_id': 0, 'prompt': 'Why?'}],
    }, _visitor(VISITOR_A)).status_code == 200
    assert ask(client, '/api/report/chat', {'simulation_id': EXHIBIT_SIM, 'message': 'Why?'},
               _visitor(VISITOR_A)).status_code == 200
    oracle = ask(client, '/api/parthenon/stage/draft', {'stage': {}}, _visitor(VISITOR_A))
    assert oracle.status_code == 429 and oracle.json['code'] == 'slow_down'


# ------------------------------------------------------------------ the square: runs

@pytest.fixture
def ready_gathering(city):
    make_project(OWNED_PROJECT, token=OWNER_TOKEN)
    make_simulation(OWNED_SIM, OWNED_PROJECT)
    app = city.app()
    _stub(app, 'simulation.start_simulation')
    return app.test_client()


def _start(client, **body):
    return client.post('/api/simulation/start', json={'simulation_id': OWNED_SIM, **body},
                       headers={'X-Parthenon-Owner': OWNER_TOKEN})


def test_a_longer_run_is_clamped_to_the_longest_allowed(ready_gathering):
    assert _start(ready_gathering, max_rounds=168).json['data']['body']['max_rounds'] == 24
    assert _start(ready_gathering).json['data']['body']['max_rounds'] == 24
    assert _start(ready_gathering, max_rounds=12).json['data']['body']['max_rounds'] == 12


def test_the_square_holds_one_run_at_a_time(city, ready_gathering):
    city.runs['count'] = 1

    response = _start(ready_gathering)

    assert response.status_code == 429
    assert response.json['code'] == 'city_full' and response.json['retry_after_seconds'] > 0


def test_a_gathering_argues_a_few_times_a_day(city):
    city.env(PARTHENON_RUNS_PER_GATHERING=2)
    make_project(OWNED_PROJECT, token=OWNER_TOKEN)
    make_simulation(OWNED_SIM, OWNED_PROJECT)
    app = city.app()
    _stub(app, 'simulation.start_simulation')
    client = app.test_client()

    assert _start(client).status_code == 200
    assert _start(client).status_code == 200
    third = _start(client)
    assert third.status_code == 429 and third.json['code'] == 'come_back_tomorrow'


def test_the_start_lock_is_released(city, ready_gathering):
    city.runs['count'] = 1
    assert _start(ready_gathering).status_code == 429
    city.runs['count'] = 0
    done = []
    thread = threading.Thread(target=lambda: done.append(_start(ready_gathering).status_code))
    thread.start()
    thread.join(timeout=10)
    assert done == [200]


def test_running_runs_counts_only_active_runs(monkeypatch):
    from app.services.simulation_runner import RunnerStatus, SimulationRunner

    class State:
        def __init__(self, status):
            self.runner_status = status

    states = {'sim_a': State(RunnerStatus.RUNNING), 'sim_b': State(RunnerStatus.COMPLETED),
              'sim_c': State(RunnerStatus.STARTING)}
    monkeypatch.setattr(SimulationRunner, '_processes', {'sim_a': object(), 'sim_b': object()})
    monkeypatch.setattr(SimulationRunner, '_start_claims', {'sim_c'})
    monkeypatch.setattr(SimulationRunner, 'get_run_state', classmethod(lambda cls, sid: states.get(sid)))

    assert guard_module.running_runs() == 2
    assert guard_module.running_runs(exclude='sim_a') == 1


# ------------------------------------------------------------------ the crowd

class _Entity:
    def __init__(self, name, edges, label='Citizen'):
        self.name = name
        self.related_edges = [{}] * edges
        self.labels = ['Entity', label]

    def get_entity_type(self):
        return self.labels[1]


class _Filtered:
    def __init__(self, entities):
        self.entities = entities
        self.filtered_count = len(entities)
        self.total_count = len(entities)
        self.entity_types = {e.get_entity_type() for e in entities}


def test_the_crowd_keeps_the_best_connected_in_order():
    crowd = _Filtered([_Entity(f'c{i}', edges=i % 5, label='Elder' if i == 0 else 'Citizen') for i in range(30)])

    capped = public_pkg.cap_entities(crowd, 12)

    assert capped.filtered_count == 12 and len(capped.entities) == 12
    names = [e.name for e in capped.entities]
    assert names == sorted(names, key=lambda n: int(n[1:]))  # original order kept
    assert all(len(e.related_edges) >= 3 for e in capped.entities)
    assert public_pkg.cap_entities(_Filtered([_Entity('a', 1)]), 12).filtered_count == 1


def test_prepare_caps_the_crowd(city, monkeypatch):
    city.env(PARTHENON_MAX_CITIZENS=12)
    make_project(OWNED_PROJECT, token=OWNER_TOKEN)
    make_simulation(OWNED_SIM, OWNED_PROJECT, status='created')
    seen = {}
    called = threading.Event()

    class Reader:
        def filter_defined_entities(self, **_kwargs):
            return _Filtered([_Entity(f'c{i}', 1) for i in range(30)])

    def prepare(self, **kwargs):
        seen.update(kwargs)
        called.set()
        return SimulationManager().get_simulation(OWNED_SIM)

    monkeypatch.setattr(simulation_api, 'ZepEntityReader', Reader)
    monkeypatch.setattr(simulation_api, '_check_simulation_prepared', lambda _sid: (False, {}))
    monkeypatch.setattr(SimulationManager, 'prepare_simulation', prepare)
    client = city.client()

    response = client.post('/api/simulation/prepare', json={
        'simulation_id': OWNED_SIM, 'parallel_profile_count': 50,
    }, headers={'X-Parthenon-Owner': OWNER_TOKEN})

    assert response.status_code == 200, response.json
    assert response.json['data']['expected_entities_count'] == 12
    assert called.wait(10)
    assert seen['max_entities'] == 12
    assert seen['parallel_profile_count'] == 5


# ------------------------------------------------------------------ the shelf

@pytest.fixture
def shelf(city):
    make_project(EXHIBIT_PROJECT)
    make_simulation(EXHIBIT_SIM, EXHIBIT_PROJECT)
    make_report(EXHIBIT_REPORT, EXHIBIT_SIM)
    make_project(OWNED_PROJECT, token=OWNER_TOKEN)
    make_simulation(OWNED_SIM, OWNED_PROJECT)
    make_report(OWNED_REPORT, OWNED_SIM)
    make_project(UNLISTED_PROJECT, token=OTHER_TOKEN)
    make_simulation(UNLISTED_SIM, UNLISTED_PROJECT)
    make_report(UNLISTED_REPORT, UNLISTED_SIM)
    return city.client()


def _shelf_ids(client, url='/api/simulation/history', key='simulation_id', **headers):
    return {item[key] for item in client.get(url, headers=headers).json['data']}


def test_the_shelf_shows_the_featured_and_the_visitors_own(shelf):
    assert _shelf_ids(shelf) == {EXHIBIT_SIM}
    assert _shelf_ids(shelf, **{'X-Parthenon-Owned': f'{OWNED_PROJECT},{OWNED_SIM}'}) == {EXHIBIT_SIM, OWNED_SIM}
    # A Chronicle's id alone finds its gathering.
    assert _shelf_ids(shelf, **{'X-Parthenon-Owned': OWNED_REPORT}) == {EXHIBIT_SIM, OWNED_SIM}
    # Rubbish in the header is ignored.
    assert _shelf_ids(shelf, **{'X-Parthenon-Owned': '../etc, <script>, proj_'}) == {EXHIBIT_SIM}
    assert _shelf_ids(shelf, **{'X-Parthenon-Admin': ADMIN_KEY}) == {EXHIBIT_SIM, OWNED_SIM, UNLISTED_SIM}


def test_every_list_is_cut_to_the_shelf(shelf):
    assert _shelf_ids(shelf, '/api/graph/project/list', 'project_id') == {EXHIBIT_PROJECT}
    assert _shelf_ids(shelf, '/api/simulation/list', 'simulation_id') == {EXHIBIT_SIM}
    assert _shelf_ids(shelf, '/api/report/list', 'report_id') == {EXHIBIT_REPORT}
    # A gathering's link opens its own crowds.
    assert _shelf_ids(shelf, f'/api/simulation/list?project_id={UNLISTED_PROJECT}', 'simulation_id') == {UNLISTED_SIM}
    assert _shelf_ids(shelf, f'/api/report/list?simulation_id={UNLISTED_SIM}', 'report_id') == {UNLISTED_REPORT}


def test_the_keepers_feature_and_unfeature(shelf):
    refused = shelf.post('/api/parthenon/featured', json={'id': UNLISTED_SIM, 'featured': True})
    assert refused.status_code == 403 and refused.json['code'] == 'not_yours'

    featured = shelf.post('/api/parthenon/featured', json={'id': UNLISTED_SIM, 'featured': True},
                          headers={'X-Parthenon-Admin': ADMIN_KEY})
    assert featured.status_code == 200 and featured.json['data']['id'] == UNLISTED_PROJECT
    assert _shelf_ids(shelf) == {EXHIBIT_SIM, UNLISTED_SIM}

    shelf.post('/api/parthenon/featured', json={'id': EXHIBIT_PROJECT, 'featured': False},
               headers={'X-Parthenon-Admin': ADMIN_KEY})
    assert _shelf_ids(shelf) == {UNLISTED_SIM}
    assert shelf.get('/api/parthenon/featured').json['data']['featured'] == ['proj_ce8edd07eb88', UNLISTED_PROJECT]
    missing = shelf.post('/api/parthenon/featured', json={'id': 'proj_nobody', 'featured': True},
                         headers={'X-Parthenon-Admin': ADMIN_KEY})
    assert missing.status_code == 404


def test_featured_follows_the_environment(city):
    city.env(PARTHENON_FEATURED=f'{OWNED_PROJECT}')
    make_project(EXHIBIT_PROJECT)
    make_simulation(EXHIBIT_SIM, EXHIBIT_PROJECT)
    make_project(OWNED_PROJECT, token=OWNER_TOKEN)
    make_simulation(OWNED_SIM, OWNED_PROJECT)

    assert _shelf_ids(city.client()) == {OWNED_SIM}


# ------------------------------------------------------------------ status

def test_public_status_reports_the_limits(city, fake_ontology):
    city.env(PARTHENON_DAILY_GATHERINGS=5, PARTHENON_DAILY_PER_VISITOR=2, PARTHENON_MAX_RUN='threeDays')
    client = city.client()
    _begin(client, VISITOR_A)

    data = client.get('/api/parthenon/status', headers=_visitor(VISITOR_A)).json['data']

    assert data['public'] is True
    assert data['provider'] == 'free'
    assert data['features'] == {'portraits': False, 'film': False, 'voice': False}
    limits = data['limits']
    assert limits['daily_gatherings'] == 5 and limits['per_visitor'] == 2
    assert limits['max_citizens'] == 12 and limits['max_run'] == 'threeDays'
    assert limits['max_run_hours'] == 72
    assert limits['today_left'] == 4 and limits['visitor_left'] == 1
    assert limits['running'] == 0 and limits['concurrent_runs'] == 1
    other = client.get('/api/parthenon/status', headers=_visitor(VISITOR_B)).json['data']['limits']
    assert other['visitor_left'] == 2


def test_public_status_reads_the_bridge(city, monkeypatch):
    monkeypatch.setattr(parthenon_api, '_llm_status_and_health', lambda: (
        False, 'The LLM bridge at http://127.0.0.1:5055 is not answering. Check that npm run dev is still running.',
        {'provider': 'grok', 'imagine': True, 'voice': True},
    ))
    monkeypatch.setattr(chronicle_film, 'find_tool', lambda name: f'/bin/{name}')

    data = city.client().get('/api/parthenon/status').json['data']

    assert data['provider'] == 'grok'
    assert data['features'] == {'portraits': True, 'film': True, 'voice': True}
    assert 'npm' not in data['llmProblem'] and '127.0.0.1' not in data['llmProblem']


@pytest.mark.parametrize('env, provider', [
    ({}, 'free'),
    ({'XAI_API_KEY': 'x'}, 'grok'),
    ({'OPENAI_API_KEY': 'x', 'ANTHROPIC_API_KEY': 'y'}, 'openai'),
    ({'ANTHROPIC_API_KEY': 'y'}, 'claude'),
    ({'PARTHENON_UPSTREAM': 'anthropic'}, 'claude'),
    ({'PARTHENON_UPSTREAM': 'openrouter', 'XAI_API_KEY': 'x'}, 'free'),
    ({'PARTHENON_UPSTREAM': 'grok'}, 'grok-subscription'),
])
def test_the_provider_without_the_bridge(env, provider):
    from app.public.providers import provider_from_env

    assert provider_from_env(env, public=True) == provider


def test_features_follow_the_bridge(monkeypatch):
    from app.public.providers import features_of

    monkeypatch.setattr(chronicle_film, 'find_tool', lambda name: None)
    assert features_of({'imagine': True, 'voice': True}) == {'portraits': True, 'film': False, 'voice': True}
    assert features_of({'imagine': False, 'voice': False}) == {'portraits': False, 'film': False, 'voice': False}
    assert features_of({'imagine': True, 'signed_in': False}) == {'portraits': False, 'film': False, 'voice': False}
    assert features_of(None) == {'portraits': False, 'film': False, 'voice': False}


# ------------------------------------------------------------------ portraits, film and voice

def test_nothing_new_is_made_when_the_steps_cannot(city, monkeypatch):
    make_project(OWNED_PROJECT, token=OWNER_TOKEN)
    make_simulation(OWNED_SIM, OWNED_PROJECT)
    make_report(OWNED_REPORT, OWNED_SIM)

    def never(*_args, **_kwargs):
        raise AssertionError('the bridge was asked')

    monkeypatch.setattr(citizen_portraits, 'start_portraits', never)
    monkeypatch.setattr(citizen_portraits, 'speak', never)
    monkeypatch.setattr(chronicle_film, 'start_film', never)
    client = city.client()
    owner = {'X-Parthenon-Owner': OWNER_TOKEN}

    portraits = client.post(f'/api/parthenon/gathering/{OWNED_SIM}/portraits', json={}, headers=owner)
    film = client.post(f'/api/parthenon/chronicle/{OWNED_REPORT}/film', json={}, headers=owner)
    voice = client.post('/api/parthenon/voice', json={'text': 'Hello'}, headers=owner)

    for response in (portraits, film, voice):
        assert response.status_code == 503
        assert response.json['code'] == 'not_on_public_steps'
    assert 'painters' in portraits.json['error'] and 'film' in film.json['error']
    assert 'browser' in voice.json['error']


@pytest.mark.parametrize('stale', [False, True])
def test_what_is_already_painted_is_answered_for_anyone(city, monkeypatch, stale):
    make_project(EXHIBIT_PROJECT)
    make_simulation(EXHIBIT_SIM, EXHIBIT_PROJECT)
    monkeypatch.setattr(citizen_portraits, 'get_portraits', lambda _sid: {'status': 'completed'})
    monkeypatch.setattr(citizen_portraits, 'get_stances', lambda _sid: {'status': 'completed', 'stale': stale})
    monkeypatch.setattr(citizen_portraits, 'start_stances', lambda *a, **k: pytest.fail('read again'))
    client = city.client()

    portraits = client.post(f'/api/parthenon/gathering/{EXHIBIT_SIM}/portraits', json={})
    stances = client.post(f'/api/parthenon/gathering/{EXHIBIT_SIM}/stances', json={})

    assert portraits.status_code == 200 and portraits.json['data']['status'] == 'completed'
    assert stances.status_code == 200 and stances.json['data']['status'] == 'completed'
    # Asking to read again is the owner's (and here the keepers') alone.
    forced = client.post(f'/api/parthenon/gathering/{EXHIBIT_SIM}/stances', json={'force': True})
    assert forced.status_code == 403


def test_the_owner_has_a_new_cast_painted(city, monkeypatch):
    city.features['portraits'] = True
    make_project(OWNED_PROJECT, token=OWNER_TOKEN)
    make_simulation(OWNED_SIM, OWNED_PROJECT)
    monkeypatch.setattr(citizen_portraits, 'get_portraits', lambda _sid: {'status': 'completed'})
    app = city.app()
    _stub(app, 'parthenon.start_citizen_portraits', status=202)

    owner = app.test_client().post(f'/api/parthenon/gathering/{OWNED_SIM}/portraits', json={},
                                   headers={'X-Parthenon-Owner': OWNER_TOKEN})
    guest = app.test_client().post(f'/api/parthenon/gathering/{OWNED_SIM}/portraits', json={})

    assert owner.status_code == 202 and owner.json['data']['passed'] is True
    assert guest.status_code == 200 and guest.json['data']['status'] == 'completed'


def test_the_owner_has_an_outgrown_reading_read_again(city, monkeypatch):
    make_project(OWNED_PROJECT, token=OWNER_TOKEN)
    make_simulation(OWNED_SIM, OWNED_PROJECT)
    monkeypatch.setattr(citizen_portraits, 'get_stances', lambda _sid: {'status': 'completed', 'stale': True})
    app = city.app()
    _stub(app, 'parthenon.start_citizen_stances', status=202)

    response = app.test_client().post(f'/api/parthenon/gathering/{OWNED_SIM}/stances', json={},
                                      headers={'X-Parthenon-Owner': OWNER_TOKEN})

    assert response.status_code == 202 and response.json['data']['passed'] is True


def test_voices_when_the_server_has_them(city, monkeypatch):
    city.env(PARTHENON_QUESTIONS_PER_HOUR=1)  # four parts an hour
    city.features['voice'] = True
    monkeypatch.setattr(citizen_portraits, 'speak', lambda *a, **k: {
        'file': 'a.mp3', 'voice': 'scribe', 'voice_id': 'eve', 'language': 'en',
        'part': 0, 'parts': 1, 'cached': False, 'truncated': False,
    })
    client = city.client()

    codes = [client.post('/api/parthenon/voice', json={'text': 'Hi'}, headers=_visitor(VISITOR_A)).status_code
             for _ in range(5)]

    assert codes == [200, 200, 200, 200, 429]
    url = client.post('/api/parthenon/voice', json={'text': 'Hi'}, headers=_visitor(VISITOR_B)).json['data']['url']
    assert url == '/api/parthenon/voice/a.mp3'  # backend-relative, as on the owner's machine


# ------------------------------------------------------------------ closed and kept routes

@pytest.mark.parametrize('method, url', [
    ('post', '/api/report/tools/search'),
    ('post', '/api/report/tools/statistics'),
    ('get', '/api/simulation/script/run_parallel_simulation.py/download'),
])
def test_debug_routes_are_closed(city, method, url):
    client = city.client()
    response = getattr(client, method)(url, json={}, headers={'X-Parthenon-Admin': ADMIN_KEY})
    assert response.status_code == 404
    assert response.json['code'] == 'not_on_public_steps'


def test_keepers_routes(city):
    client = city.client()
    refused = client.get('/api/graph/tasks')
    assert refused.status_code == 403 and refused.json['code'] == 'not_yours'
    assert client.get('/api/graph/tasks', headers={'X-Parthenon-Admin': ADMIN_KEY}).status_code == 200


# ------------------------------------------------------------------ nothing internal leaves

def test_no_trace_or_path_in_a_public_error(city, monkeypatch):
    def broken(*_args, **_kwargs):
        raise OSError("[Errno 2] No such file or directory: '/data/uploads/simulations/x/state.json'")

    monkeypatch.setattr(SimulationManager, 'list_simulations', broken)
    client = city.client()

    response = client.get('/api/simulation/list')

    text = response.get_data(as_text=True)
    assert response.status_code == 500
    assert 'traceback' not in text.lower() and '/data/' not in text and 'Errno' not in text
    assert response.json['success'] is False and response.json['error']


def test_an_unhandled_error_is_the_citys_stumble(city):
    app = city.app()

    def boom():
        raise RuntimeError('secret at /Users/someone/.env')

    app.view_functions['parthenon.instance_status'] = boom
    response = app.test_client().get('/api/parthenon/status')

    assert response.status_code == 500
    text = response.get_data(as_text=True)
    assert '/Users' not in text and '.env' not in text and 'RuntimeError' not in text
    assert response.json == {'success': False, 'error': 'The city stumbled. Try again in a moment.'}


def test_unknown_routes_answer_in_json(city):
    response = city.client().get('/api/nothing/here')
    assert response.status_code == 404
    assert response.json['success'] is False


def test_paths_in_a_task_message_are_scrubbed(city, monkeypatch):
    from app.models.task import TaskManager

    manager = TaskManager()
    task_id = manager.create_task(task_type='graph_build', metadata={})
    manager.fail_task(task_id, 'could not open /app/backend/uploads/projects/p/files/a.pdf')

    text = city.client().get(f'/api/graph/task/{task_id}').get_data(as_text=True)

    assert '/app/backend' not in text


def test_pages_from_the_public_origin_are_welcome(city):
    client = city.client()
    ok = client.get('/api/parthenon/status', headers={'Origin': 'https://projectforty2.ai'},
                    base_url='http://parthenon-abcd:10000')
    assert ok.status_code == 200
    refused = client.post('/api/parthenon/stage/draft', json={},
                          headers={'Origin': 'https://evil.example'}, base_url='http://parthenon-abcd:10000')
    assert refused.status_code == 403


def test_the_owner_machine_still_only_serves_localhost(city):
    client = city.client(public=False)
    response = client.get('/api/parthenon/status', base_url='http://parthenon-abcd:10000')
    assert response.status_code == 403


# ------------------------------------------------------------------ lineage

def test_lineage_finds_the_project(city):
    make_project(OWNED_PROJECT, token=OWNER_TOKEN, graph_id='graph_visitor')
    make_simulation(OWNED_SIM, OWNED_PROJECT)
    make_report(OWNED_REPORT, OWNED_SIM)

    assert lineage.project_of(OWNED_PROJECT) == OWNED_PROJECT
    assert lineage.project_of(OWNED_SIM) == OWNED_PROJECT
    assert lineage.project_of(OWNED_REPORT) == OWNED_PROJECT
    assert lineage.project_of('sim_unknown') is None
    assert lineage.project_of('../proj_x') is None
    assert lineage.projects_of_graph('graph_visitor') == [OWNED_PROJECT]
    assert lineage.token_owns(OWNER_TOKEN, OWNED_PROJECT)
    assert not lineage.token_owns(OTHER_TOKEN, OWNED_PROJECT)
    assert not lineage.token_owns(None, OWNED_PROJECT)
    assert lineage.parse_id_list(' proj_a , sim_b,report_c,../x, proj_a') == ['proj_a', 'sim_b', 'report_c']
