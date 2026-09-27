"""The invite (PARTHENON_INVITE_CODE): speaking on the public steps asks for the word.

Beginning a gathering, every question, the Oracle's draft, the voices and
starting portraits, a film or a stance reading ask for one of the invite's
words in X-Parthenon-Invite (or ?invite=). Reading never does, the keepers
pass without it, and wrong words are limited per visitor per hour. Unset, or
on the owner's own machine, nothing asks for it.
"""

import io
import os

import pytest

from app.public import guard as guard_module
from app.public.guard import invite_matches
from app.public.settings import invite_word, load_settings, parse_invite_codes
from app.services import citizen_portraits

from test_public_mode import (  # noqa: F401 - fixtures
    ADMIN_KEY, EXHIBIT_PROJECT, EXHIBIT_SIM, OWNED_PROJECT, OWNED_REPORT, OWNED_SIM, OWNER_TOKEN,
    VISITOR_A, VISITOR_B, _begin, _stub, _visitor, ask, city, fake_ontology, make_project,
    make_report, make_simulation, speaker,
)


CODE = 'olive-branch-7Qx'
OTHER_CODE = 'laurel+wreath/9='
SPEAKER_URL = f'/api/parthenon/gathering/{EXHIBIT_SIM}/speaker'
INVITE_WORDS = 'The steps are open to all. To speak, bring the word you were given.'
WRONG_WORDS = 'That is not the word the city was given. Look again at the one you were handed.'


def _invited(ip=VISITOR_A, code=CODE, **extra):
    return _visitor(ip, **{'X-Parthenon-Invite': code, **extra})


@pytest.fixture
def invite(city):
    city.env(PARTHENON_INVITE_CODE=f' {CODE} , {OTHER_CODE} ,,')
    return city


def _left_today(client, ip=VISITOR_A):
    return client.get('/api/parthenon/status', headers=_visitor(ip)).json['data']['limits']['visitor_left']


# ================================================================== the status

def test_the_status_says_whether_the_invite_is_asked_for(city):
    assert city.client().get('/api/parthenon/status').json['data']['invite_required'] is False
    city.env(PARTHENON_INVITE_CODE=CODE)
    assert city.client().get('/api/parthenon/status').json['data']['invite_required'] is True
    # Never on the owner's own machine.
    assert city.client(public=False).get('/api/parthenon/status').json['data']['invite_required'] is False


# ================================================================== beginning a gathering

def test_beginning_a_gathering_asks_for_the_invite(invite, fake_ontology):
    client = invite.client()

    refused = _begin(client, VISITOR_A)

    assert refused.status_code == 403
    assert refused.json == {'success': False, 'code': 'invite_needed', 'invite': 'missing', 'error': INVITE_WORDS}
    assert fake_ontology == [] and _left_today(client) == 2  # nothing counted
    begun = client.post('/api/graph/ontology/generate', data=_scroll_form(),
                        content_type='multipart/form-data', headers=_invited())
    assert begun.status_code == 200 and begun.json['data']['owner_token']
    assert _left_today(client) == 1


def _scroll_form():
    return {
        'simulation_requirement': 'Should Athens listen?', 'project_name': 'A test gathering',
        'files': (io.BytesIO(b'The steps are warm in the sun.'), 'scroll.md'),
    }


def test_the_invite_may_come_in_the_address(invite, fake_ontology):
    client = invite.client()

    begun = client.post(f'/api/graph/ontology/generate?invite={CODE}', data=_scroll_form(),
                        content_type='multipart/form-data', headers=_visitor(VISITOR_A))

    assert begun.status_code == 200
    # A '+' in a link comes back as a space; the word still opens the steps.
    other = client.post('/api/graph/ontology/generate?invite=laurel+wreath/9%3D', data=_scroll_form(),
                        content_type='multipart/form-data', headers=_visitor(VISITOR_B))
    assert other.status_code == 200


def test_the_invite_refusal_speaks_chinese_when_asked(invite, fake_ontology):
    refused = invite.client().post('/api/graph/ontology/generate', data=_scroll_form(),
                                   content_type='multipart/form-data',
                                   headers=_visitor(VISITOR_A, **{'Accept-Language': 'zh-CN,zh;q=0.9'}))

    assert refused.status_code == 403 and refused.json['code'] == 'invite_needed'
    assert refused.json['error'] == '台阶向所有人敞开。若要发言，请带上交给你的那句口令。'


# ================================================================== questions, the Oracle, the voices

@pytest.mark.parametrize('endpoint, url, body', [
    ('simulation.interview_agent', '/api/simulation/interview',
     {'simulation_id': EXHIBIT_SIM, 'agent_id': 0, 'prompt': 'Why?'}),
    ('simulation.interview_agents_batch', '/api/simulation/interview/batch',
     {'simulation_id': EXHIBIT_SIM, 'interviews': [{'agent_id': 0, 'prompt': 'Why?'}]}),
    ('simulation.interview_all_agents', '/api/simulation/interview/all',
     {'simulation_id': EXHIBIT_SIM, 'prompt': 'Why?'}),
    ('report.chat_with_report_agent', '/api/report/chat', {'simulation_id': EXHIBIT_SIM, 'message': 'Why?'}),
    ('parthenon.ask_the_speaker', SPEAKER_URL, {'question': 'Why?'}),
    ('parthenon.draft_stage', '/api/parthenon/stage/draft', {'stage': {}}),
])
def test_every_question_asks_for_the_invite(invite, endpoint, url, body):
    invite.env(PARTHENON_QUESTIONS_PER_HOUR=1)
    app = invite.app()
    _stub(app, endpoint)
    client = app.test_client()

    refused = client.post(url, json=body, headers=_visitor(VISITOR_A))

    assert refused.status_code == 403 and refused.json['code'] == 'invite_needed'
    # Not counted: the one question of the hour is still there.
    answered = ask(client, url, body, _invited())
    assert answered.status_code == 200 and answered.json['data']['passed'] is True


def test_the_owners_key_is_not_the_invite(invite, speaker):
    make_project(OWNED_PROJECT, token=OWNER_TOKEN)
    make_simulation(OWNED_SIM, OWNED_PROJECT)
    client = invite.client()

    refused = client.post(f'/api/parthenon/gathering/{OWNED_SIM}/speaker', json={'question': 'Why?'},
                          headers=_visitor(VISITOR_A, **{'X-Parthenon-Owner': OWNER_TOKEN}))

    assert refused.status_code == 403 and refused.json['code'] == 'invite_needed'


def test_the_voices_ask_for_the_invite_when_the_server_has_them(invite, monkeypatch):
    monkeypatch.setattr(citizen_portraits, 'speak', lambda *a, **k: {
        'file': 'a.mp3', 'voice': 'scribe', 'voice_id': 'eve', 'language': 'en',
        'part': 0, 'parts': 1, 'cached': False, 'truncated': False,
    })
    client = invite.client()

    # Without voices the page is told so first (it reads aloud in the browser).
    off = client.post('/api/parthenon/voice', json={'text': 'Hi'}, headers=_visitor(VISITOR_A))
    assert off.status_code == 503 and off.json['code'] == 'not_on_public_steps'

    invite.features['voice'] = True
    refused = client.post('/api/parthenon/voice', json={'text': 'Hi'}, headers=_visitor(VISITOR_A))
    assert refused.status_code == 403 and refused.json['code'] == 'invite_needed'
    spoken = client.post('/api/parthenon/voice', json={'text': 'Hi'}, headers=_invited())
    assert spoken.status_code == 200 and spoken.json['data']['url'] == '/api/parthenon/voice/a.mp3'


# ================================================================== portraits, film and stances

@pytest.fixture
def owned(invite):
    make_project(OWNED_PROJECT, token=OWNER_TOKEN)
    make_simulation(OWNED_SIM, OWNED_PROJECT)
    make_report(OWNED_REPORT, OWNED_SIM)
    invite.features.update(portraits=True, film=True)
    app = invite.app()
    for endpoint in ('parthenon.start_citizen_portraits', 'parthenon.start_chronicle_film',
                     'parthenon.start_citizen_stances'):
        _stub(app, endpoint, status=202)
    return app.test_client()


@pytest.mark.parametrize('url', [
    f'/api/parthenon/gathering/{OWNED_SIM}/portraits',
    f'/api/parthenon/chronicle/{OWNED_REPORT}/film',
    f'/api/parthenon/gathering/{OWNED_SIM}/stances',
])
def test_making_portraits_a_film_or_a_reading_asks_for_the_invite(owned, monkeypatch, url):
    monkeypatch.setattr(citizen_portraits, 'get_portraits', lambda _sid: {'status': 'none'})
    monkeypatch.setattr(citizen_portraits, 'get_stances', lambda _sid: {'status': 'none'})
    owner = {'X-Parthenon-Owner': OWNER_TOKEN}

    refused = owned.post(url, json={}, headers=_visitor(VISITOR_A, **owner))
    allowed = owned.post(url, json={}, headers=_invited(**owner))

    assert refused.status_code == 403 and refused.json['code'] == 'invite_needed'
    assert allowed.status_code == 202 and allowed.json['data']['passed'] is True


def test_a_guest_is_shown_what_is_already_painted_and_read_without_the_invite(invite, monkeypatch):
    make_project(EXHIBIT_PROJECT)
    make_simulation(EXHIBIT_SIM, EXHIBIT_PROJECT)
    monkeypatch.setattr(citizen_portraits, 'get_portraits', lambda _sid: {'status': 'completed'})
    monkeypatch.setattr(citizen_portraits, 'get_stances', lambda _sid: {'status': 'completed', 'stale': True})
    client = invite.client()

    portraits = client.post(f'/api/parthenon/gathering/{EXHIBIT_SIM}/portraits', json={})
    stances = client.post(f'/api/parthenon/gathering/{EXHIBIT_SIM}/stances', json={})

    assert portraits.status_code == 200 and portraits.json['data']['status'] == 'completed'
    assert stances.status_code == 200 and stances.json['data']['status'] == 'completed'


# ================================================================== reading never asks

def test_reading_never_asks_for_the_invite(invite):
    make_project(EXHIBIT_PROJECT, graph_id='mirofish_exhibit')
    make_simulation(EXHIBIT_SIM, EXHIBIT_PROJECT)
    client = invite.client()

    for url in (
        '/api/parthenon/status',
        '/api/parthenon/featured',
        f'/api/graph/project/{EXHIBIT_PROJECT}',
        f'/api/simulation/{EXHIBIT_SIM}',
        '/api/simulation/history',
        f'/api/parthenon/gathering/{EXHIBIT_SIM}',
        f'/api/parthenon/gathering/{EXHIBIT_SIM}/portraits',
        f'/api/parthenon/ticket/{"a" * 32}',
    ):
        response = client.get(url, headers=_visitor(VISITOR_A))
        assert response.status_code != 403 and (response.json or {}).get('code') != 'invite_needed', url


# ================================================================== wrong words

def test_wrong_words_are_limited_per_visitor_per_hour(invite, speaker):
    invite.env(PARTHENON_INVITE_TRIES_PER_HOUR=3)
    client = invite.client()

    for _ in range(3):
        wrong = client.post(SPEAKER_URL, json={'question': 'Why?'}, headers=_invited(code='fig-leaf'))
        assert wrong.status_code == 403
        assert wrong.json == {'success': False, 'code': 'invite_needed', 'invite': 'wrong', 'error': WRONG_WORDS}
    # Past the tries of the hour, even the right word waits.
    held = client.post(SPEAKER_URL, json={'question': 'Why?'}, headers=_invited())
    assert held.status_code == 429 and held.json['code'] == 'slow_down'
    assert 0 < held.json['retry_after_seconds'] <= 3600 and held.headers['Retry-After']
    assert speaker == []
    # Another visitor is not held.
    assert ask(client, SPEAKER_URL, {'question': 'Why?'}, _invited(VISITOR_B)).status_code == 200


def test_the_default_is_ten_wrong_words_an_hour(invite, speaker):
    client = invite.client()

    codes = [client.post(SPEAKER_URL, json={'question': 'Why?'}, headers=_invited(code=f'guess-{n}')).status_code
             for n in range(11)]

    assert codes == [403] * 10 + [429]


def test_coming_without_a_word_is_not_a_wrong_word(invite, speaker):
    invite.env(PARTHENON_INVITE_TRIES_PER_HOUR=2)
    client = invite.client()

    for _ in range(5):
        missing = client.post(SPEAKER_URL, json={'question': 'Why?'}, headers=_visitor(VISITOR_A))
        assert missing.status_code == 403 and missing.json['invite'] == 'missing'

    assert ask(client, SPEAKER_URL, {'question': 'Why?'}, _invited()).status_code == 200


def test_the_keepers_pass_without_the_invite(invite, speaker, fake_ontology):
    client = invite.client()
    keeper = _visitor(VISITOR_A, **{'X-Parthenon-Admin': ADMIN_KEY})

    assert ask(client, SPEAKER_URL, {'question': 'Why?'}, keeper).status_code == 200
    begun = client.post('/api/graph/ontology/generate', data=_scroll_form(),
                        content_type='multipart/form-data', headers=keeper)
    assert begun.status_code == 200


# ================================================================== checking a word

def test_a_word_can_be_checked_before_it_is_needed(invite):
    client = invite.client()

    good = client.post('/api/parthenon/invite', headers=_invited(code=f'  {OTHER_CODE}  '))
    missing = client.post('/api/parthenon/invite', headers=_visitor(VISITOR_A))
    wrong = client.post('/api/parthenon/invite', headers=_invited(code='fig-leaf'))

    assert good.status_code == 200
    assert good.json == {'success': True, 'data': {'valid': True, 'invite_required': True}}
    assert missing.status_code == 403 and missing.json['invite'] == 'missing'
    assert wrong.status_code == 403 and wrong.json['invite'] == 'wrong'


def test_checking_a_word_counts_as_a_try(invite):
    invite.env(PARTHENON_INVITE_TRIES_PER_HOUR=1)
    client = invite.client()

    assert client.post('/api/parthenon/invite', headers=_invited(code='fig-leaf')).status_code == 403
    assert client.post('/api/parthenon/invite', headers=_invited()).status_code == 429


def test_without_an_invite_every_word_is_welcome(city, speaker):
    client = city.client()

    checked = client.post('/api/parthenon/invite', headers=_visitor(VISITOR_A))

    assert checked.json == {'success': True, 'data': {'valid': True, 'invite_required': False}}
    assert ask(client, SPEAKER_URL, {'question': 'Why?'}, _visitor(VISITOR_A)).status_code == 200


# ================================================================== the owner's own machine

def test_on_the_owners_machine_nothing_asks_for_the_invite(invite, speaker, fake_ontology):
    client = invite.client(public=False)

    begun = _begin(client, VISITOR_A)
    answered = client.post(SPEAKER_URL, json={'question': 'Why?'})

    assert begun.status_code == 200 and 'owner_token' not in begun.json['data']
    assert answered.status_code == 200 and answered.json['data']['answer'] == 'Know thyself.'
    assert client.post('/api/parthenon/invite').status_code == 404


# ================================================================== the words themselves

def test_the_invite_codes_are_read_from_the_environment():
    settings = load_settings({'PARTHENON_PUBLIC': '1', 'PARTHENON_INVITE_CODE': ' a1 , b 2,,a1 '})

    assert settings.invite_codes == ('a1', 'b+2')
    assert settings.invite_required is True
    assert 'a1' not in repr(settings)
    assert load_settings({'PARTHENON_PUBLIC': '1'}).invite_required is False
    assert load_settings({'PARTHENON_PUBLIC': '1', 'PARTHENON_INVITE_CODE': ' , '}).invite_codes == ()
    assert load_settings({'PARTHENON_INVITE_TRIES_PER_HOUR': '0'}).invite_tries_per_hour == 10


@pytest.mark.parametrize('sent, expected', [
    (CODE, True), (f'  {CODE}\t', True), (OTHER_CODE, True), ('laurel wreath/9=', True),
    (CODE.upper(), False), (CODE[:-1], False), ('', False), (CODE + 'x', False),
])
def test_a_word_matches_only_a_code(sent, expected):
    assert invite_matches(sent, parse_invite_codes(f'{CODE},{OTHER_CODE}')) is expected


def test_every_code_is_compared(monkeypatch):
    compared = []
    real = guard_module.hmac.compare_digest

    def counting(a, b):
        compared.append(b)
        return real(a, b)

    monkeypatch.setattr(guard_module.hmac, 'compare_digest', counting)
    assert invite_matches('first', ('first', 'second', 'third')) is True
    assert len(compared) == 3


def test_invite_words_are_trimmed_and_a_space_is_a_plus():
    assert invite_word('  a b  ') == 'a+b'
    assert invite_word(None) == ''


# ================================================================== the provider without the bridge

def test_auto_is_the_subscription_once_the_server_is_signed_in(tmp_path):
    from app.public.providers import provider_from_env

    token_file = tmp_path / 'grok-oauth.json'
    env = {'PARTHENON_UPSTREAM': 'auto', 'GROK_BRIDGE_TOKEN_FILE': str(token_file), 'XAI_API_KEY': 'x'}

    assert provider_from_env(env, public=True) == 'grok'  # no file yet: the key
    token_file.write_text('')
    assert provider_from_env(env, public=True) == 'grok'  # an empty file is no sign-in
    token_file.write_text('{"access_token": "fake-token-for-tests"}')
    assert provider_from_env(env, public=True) == 'grok-subscription'
    os.remove(token_file)
    assert provider_from_env({**env, 'XAI_API_KEY': ''}, public=True) == 'free'
