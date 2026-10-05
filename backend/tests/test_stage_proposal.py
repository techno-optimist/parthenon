"""Oracle setup contracts. Every provider is local and mocked."""
import copy
import json

import pytest

from app import create_app
from app.api import parthenon as api
from app.services.stage_oracle import StageOracle, StageValidationError
from app.services.stage_proposal import AUDIENCES
from app.utils.llm_client import LLMResponseError
from test_stage_oracle import FakeLLM, ExplodingLLM
from test_public_mode import city, ask, _visitor, VISITOR_A, TicketAnswer  # noqa: F401 - fixture


def proposal():
    return {
        'stage': {
            'title': 'A city considers AI tutors', 'format': 'dialogue', 'era': 'now',
            'setting': 'A hypothetical city council in 2026', 'topic': 'AI tutors in public schools',
            'speakers': [
                {'figureId': 'socrates', 'name': 'Socrates', 'role': 'Questioner',
                 'ideas': 'Examine claims to knowledge', 'voice': 'Questions', 'words': 'What does a tutor know?'},
                {'figureId': 'aristotle', 'name': 'Aristotle', 'role': 'Philosopher',
                 'ideas': 'Learning through practice', 'voice': 'Precise', 'words': 'We learn by doing.'},
            ],
            'audience': [{'name': name, 'description': 'A fictional role weighing access and cost.'} for name in AUDIENCES['now'][:8]],
            'question': 'Who accepts AI tutors? What does the council decide?',
            'happensNext': 'A council vote tomorrow decides the pilot.',
        },
        'runLength': 'day', 'assumptions': ['The city and vote are hypothetical.'],
    }


def test_brief_proposes_complete_stage_once_without_external_tools():
    llm = FakeLLM(proposal())
    result = StageOracle(llm).propose('Explore AI tutors with Greek philosophers')
    assert result['proposal']['stage']['speakers'][0]['figureId'] == 'socrates'
    assert result['proposal']['runLength'] == 'day'
    assert result['proposal']['sourceBasis'] == 'hypothetical'
    assert llm.calls[0]['max_attempts'] == 1
    assert llm.calls[0]['single_request'] is True
    assert len(llm.calls) == 1
    system = llm.calls[0]['messages'][0]['content']
    assert 'Never claim' in system and 'source context' in system


@pytest.mark.parametrize('brief,sources', [('', ''), ('x' * 6001, ''), ('Brief', 'x' * 8001), (True, ''), ('Brief', {})])
def test_invalid_input_is_rejected_before_provider(brief, sources):
    with pytest.raises(StageValidationError):
        StageOracle(ExplodingLLM()).propose(brief, sources=sources)


def test_refinement_passes_only_validated_current_proposal_and_source_context():
    current = proposal()
    llm = FakeLLM(proposal())
    result = StageOracle(llm).propose('Make the vote tomorrow', current=current, sources='User note: a pilot is proposed.')
    sent = json.loads(llm.calls[0]['messages'][1]['content'])
    assert sent['current']['stage']['title'] == current['stage']['title']
    assert sent['sources'] == 'User note: a pilot is proposed.'
    assert result['proposal']['sourceBasis'] == 'user-supplied'
    assert current == proposal()


@pytest.mark.parametrize('change', [
    lambda p: p.update(runLength='forever'),
    lambda p: p['stage'].update(format='bogus'),
    lambda p: p['stage'].update(era='unknown'),
    lambda p: p['stage'].update(speakers=p['stage']['speakers'][:1]),
    lambda p: p['stage']['speakers'][0].update(figureId='real-private-person', name='Pat Smith'),
    lambda p: p['stage']['speakers'][0].update(name='Not Socrates'),
    lambda p: p['stage']['speakers'][0].update(words=''),
    lambda p: p['stage'].update(question=''),
    lambda p: p['stage'].update(audience=[]),
    lambda p: p['stage']['audience'].append(p['stage']['audience'][0]),
    lambda p: p['stage'].update(title='x' * 121),
    lambda p: p.update(assumptions=['x' * 501]),
])
def test_malformed_model_output_is_rejected_whole(change):
    raw = proposal()
    change(raw)
    with pytest.raises(LLMResponseError):
        StageOracle(FakeLLM(raw)).propose('Explore AI tutors')


def test_one_essential_clarification_is_allowed_without_partial_stage():
    llm = FakeLLM({'clarification': 'Which decision should this community face?'})
    assert StageOracle(llm).propose('Help with this')['clarification'].startswith('Which')
    with pytest.raises(LLMResponseError):
        StageOracle(FakeLLM({'clarification': 'Which?', **proposal()})).propose('Help')


def test_proposal_uses_existing_draft_route_and_error_mapping(monkeypatch):
    llm = FakeLLM(proposal())
    monkeypatch.setattr(api, 'StageOracle', lambda: StageOracle(llm))
    app = create_app()
    app.config['TESTING'] = True
    client = app.test_client()
    result = client.post('/api/parthenon/stage/draft', json={'mode': 'proposal', 'brief': 'Explore AI tutors'})
    assert result.status_code == 200
    assert result.json['data']['proposal']['stage']['title'] == proposal()['stage']['title']
    assert client.post('/api/parthenon/stage/draft', json={'mode': 'anything', 'brief': 'Brief'}).status_code == 400
    assert len(llm.calls) == 1


def test_public_proposal_requires_invite_before_provider_and_uses_existing_ticket(city, monkeypatch):
    city.env(PARTHENON_INVITE_CODE='olive', PARTHENON_QUESTION_TICKETS=1)
    llm = FakeLLM(proposal())
    monkeypatch.setattr(api, 'StageOracle', lambda: StageOracle(llm))
    client = city.client()
    body = {'mode': 'proposal', 'brief': 'A city considering AI tutors'}
    refused = client.post('/api/parthenon/stage/draft', json=body, headers=_visitor(VISITOR_A))
    assert refused.status_code == 403
    assert refused.json['code'] == 'invite_needed'
    assert llm.calls == []
    answer = ask(client, '/api/parthenon/stage/draft', body, _visitor(VISITOR_A, **{'X-Parthenon-Invite': 'olive'}))
    assert isinstance(answer, TicketAnswer)
    assert answer.status_code == 200
    assert answer.json['data']['proposal']['stage']['title'] == proposal()['stage']['title']
    assert len(llm.calls) == 1


def test_invalid_brief_is_rejected_before_llm_initialization(monkeypatch):
    def no_key():
        raise AssertionError('Invalid input must not initialize the provider')
    monkeypatch.setattr('app.services.stage_oracle.LLMClient', no_key)
    with pytest.raises(StageValidationError):
        StageOracle().propose('')


def test_model_cannot_invent_person_names_links_or_documented_beliefs():
    raw = proposal()
    raw['stage']['audience'][0]['name'] = 'Pat Smith'
    with pytest.raises(LLMResponseError):
        StageOracle(FakeLLM(raw)).propose('Make Pat Smith a parent')
    raw = proposal()
    raw['stage']['topic'] += ' See https://invented.example/source'
    with pytest.raises(LLMResponseError):
        StageOracle(FakeLLM(raw)).propose('AI tutors')
    raw = proposal()
    raw['stage']['speakers'][0]['ideas'] = 'Socrates privately supported this company.'
    result = StageOracle(FakeLLM(raw)).propose('AI tutors')
    assert 'privately supported' not in result['proposal']['stage']['speakers'][0]['ideas']


def test_supplied_links_remain_usable_when_followed_by_newlines_in_model_prose():
    raw = proposal()
    raw['stage']['topic'] += '\nhttps://example.org/user-source\nA user-provided excerpt.'
    result = StageOracle(FakeLLM(raw)).propose('AI tutors', sources='https://example.org/user-source\nThe supplied excerpt.')
    assert 'https://example.org/user-source' in result['proposal']['stage']['topic']
