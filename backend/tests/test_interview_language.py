"""Interviews made for the Chronicle are in the record's language, and so is what the Scribe reads.

The citizens are asked in the gathering's record language (never the
thread's or the request's), the questions, the reasoning, the answers and the
summary pass the language guard before the Scribe sees them, the key quotes
are cut where the language ends its sentences, and the tools' texts carry
their headings in the record's language. A Chinese record keeps its Chinese.

No network and no real model: the Scribe's client and the translator are fakes.
"""

import json
import os
import re

import pytest

from app.models.project import ProjectManager
from app.services import language_guard
from app.services import zep_tools
from app.services.simulation_manager import SimulationManager
from app.services.simulation_runner import SimulationRunner
from app.services.zep_tools import (
    AgentInterview,
    InsightForgeResult,
    InterviewResult,
    NodeInfo,
    PanoramaResult,
    SearchResult,
    ZepToolsService,
    extract_key_quotes,
    interview_prefix,
)
from app.utils.locale import language_instruction_for, set_locale


HAN = re.compile('[一-鿿]')

PROFILES = [
    {'realname': 'Crito', 'username': 'crito_719', 'profession': 'Friend and guarantor', 'bio': 'An old friend.'},
    {'realname': 'Plato', 'username': 'plato_218', 'profession': 'Student', 'bio': '他记下了一切。'},
    {'realname': 'Meletus', 'username': 'meletus_458', 'profession': 'Accuser', 'bio': 'The accuser.'},
]

ZH_QUESTION = '作为苏格拉底的亲密追随者，你如何看待越狱计划？'
EN_QUESTION = "As one of Socrates' closest followers, what do you make of the escape plan?"
ZH_ANSWER = '问题1：苏格拉底在对话中坚定论证，逃跑将违背他一生尊崇的城邦法律。'
EN_ANSWER_LINE = "Question 1: Socrates argued firmly that escaping would betray the city's laws he honoured all his life."
PLATO_EN = (
    'Question 1: I wrote down every word he said in the cell, and he never once wavered about the laws. '
    'He asked us whether a city can stand if its verdicts are undone by private men.'
)
TRANSLATIONS = {
    ZH_QUESTION: EN_QUESTION,
    ZH_ANSWER: EN_ANSWER_LINE,
    '他记下了一切。': 'He wrote everything down.',
    '“我不会走”，他说。': '"I will not go," he said.',
}


class FakeTranslator:
    """language_guard's model: the table's translation of each line; records every call."""

    def __init__(self, table=None, error=None):
        self.table = dict(table or {})
        self.error = error
        self.calls = []

    def chat_json(self, messages, **_kwargs):
        lines = json.loads(messages[-1]['content'])['lines']
        self.calls.append(lines)
        if self.error is not None:
            raise self.error
        return {'lines': [self.table.get(line, line) for line in lines]}


class FakeScribe:
    """The service's LLM: selection, questions and summary by what the system prompt asks for."""

    def __init__(self, questions=None, summary='Crito and Plato agree the laws bind him.'):
        self.questions = questions if questions is not None else [ZH_QUESTION, 'What happens next?']
        self.summary = summary
        self.systems = []
        self.users = []

    def chat_json(self, messages, temperature=0.3, **_kwargs):
        system, user = messages[0]['content'], messages[-1]['content']
        self.systems.append(system)
        self.users.append(user)
        if 'You plan interviews' in system:
            return {'selected_indices': [0, 1], 'reasoning': 'Crito planned it; Plato recorded it.'}
        if 'experienced interviewer' in system:
            return {'questions': list(self.questions)}
        if 'You analyse questions' in system:
            return {'sub_queries': ['Who planned the escape?', '谁反对越狱？']}
        raise AssertionError(system[:60])

    def chat(self, messages, temperature=0.3, max_tokens=None, **_kwargs):
        self.systems.append(messages[0]['content'])
        self.users.append(messages[-1]['content'])
        return self.summary


@pytest.fixture(autouse=True)
def _clean(monkeypatch, tmp_path):
    monkeypatch.setattr(ProjectManager, 'PROJECTS_DIR', str(tmp_path / 'projects'))
    monkeypatch.delenv(language_guard.RECORD_LANGUAGE_ENV, raising=False)
    language_guard.clear_cache()
    yield
    language_guard.clear_cache()


@pytest.fixture
def translator(monkeypatch):
    fake = FakeTranslator(TRANSLATIONS)
    monkeypatch.setattr(language_guard, 'default_translator', lambda: fake)
    return fake


def _gathering(language, requirement='Will Socrates escape before the ship returns from Delos?'):
    """A project with its record language and a simulation pointing at it: the simulation's id."""

    project = ProjectManager.create_project(name='hemlock', language=language)
    project.simulation_requirement = requirement
    ProjectManager.save_project(project)
    simulation_id = f'sim_{project.project_id[5:]}'
    folder = os.path.join(SimulationManager.SIMULATION_DATA_DIR, simulation_id)
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, 'state.json'), 'w', encoding='utf-8') as handle:
        json.dump({'simulation_id': simulation_id, 'project_id': project.project_id}, handle)
    return simulation_id


def _service(scribe, translator=None):
    service = object.__new__(ZepToolsService)
    service.client = None
    service._llm_client = scribe
    service._translator = translator
    service._load_agent_profiles = lambda _simulation_id: [dict(p) for p in PROFILES]
    return service


def _runner(monkeypatch, answers, success=True, error=None):
    """SimulationRunner.interview_agents_batch answering from answers {'twitter_0': text, ...}."""

    sent = []

    def batch(**kwargs):
        sent.append(kwargs)
        if isinstance(error, Exception):
            raise error
        if not success:
            return {'success': False, 'error': error}
        return {'success': True, 'interviews_count': len(answers), 'result': {'results': {
            key: {'response': text} for key, text in answers.items()
        }}}

    monkeypatch.setattr(SimulationRunner, 'interview_agents_batch', batch)
    return sent


# ═══════════════════════════════════════════════════════════════
# The prefix and the key quotes
# ═══════════════════════════════════════════════════════════════

def test_the_interview_prefix_is_in_the_records_language():
    english = interview_prefix('en')
    assert not HAN.search(english) and not language_guard.foreign_script(english, 'en')
    assert '"Question X:"' in english and 'Answer in English' in english
    assert english.rstrip().endswith(language_instruction_for('en'))
    assert interview_prefix('en-US') == interview_prefix(None) == interview_prefix('fr') == english
    assert interview_prefix('zh-CN') == zep_tools.INTERVIEW_PREFIX_ZH
    assert '「问题X：」' in zep_tools.INTERVIEW_PREFIX_ZH
    assert '\u2014' not in english


def test_english_answers_give_whole_english_key_quotes():
    answers = [
        'Question 1: I think the laws of Athens bind even a man condemned unjustly, and I would not run. '
        'My friends begged me to take the ship, but a promise to the city is not undone by a bad verdict! '
        'Short one.',
        'Question 2: The city is split, and I feel it in the market every morning when I pass the stalls.',
    ]
    quotes = extract_key_quotes(answers, 'en')
    assert len(quotes) == 3
    assert quotes[0] == 'My friends begged me to take the ship, but a promise to the city is not undone by a bad verdict!'
    for quote in quotes:
        assert '。' not in quote and 'Question' not in quote and quote[-1] in '.!?'


def test_chinese_answers_keep_their_own_marks_and_an_english_record_keeps_none_of_them():
    zh = ['问题1：我认为城邦的法律即使对一个被不公正判决的人也有约束力，我不会逃避它们！'
          '朋友们恳求我登上那艘船，但对城邦的承诺不会因一个坏判决而解除']
    quotes = extract_key_quotes(zh, 'zh')
    assert quotes == ['我认为城邦的法律即使对一个被不公正判决的人也有约束力，我不会逃避它们！',
                      '朋友们恳求我登上那艘船，但对城邦的承诺不会因一个坏判决而解除。']
    assert extract_key_quotes(zh, 'en') == []
    mixed = [ZH_ANSWER + ' ' + PLATO_EN]
    assert all(not HAN.search(quote) for quote in extract_key_quotes(mixed, 'en'))


def test_a_long_english_quote_is_cut_at_a_sentence_and_numbered_scaffolding_is_skipped():
    long = ('The laws raised me and fed me and taught me. ' * 8).strip() + ' And so I stay'
    text = AgentInterview('Crito', 'friend', '', 'q', 'a', key_quotes=[long, 'Question 2: skip me please'],
                          language='en').to_text()
    quoted = [line for line in text.split('\n') if line.startswith('> ')]
    assert len(quoted) == 1 and len(quoted[0]) <= 305 and quoted[0].endswith('taught me."')
    assert '**Key quotes:**' in text and '_Bio: _' in text


# ═══════════════════════════════════════════════════════════════
# The interview for the Chronicle
# ═══════════════════════════════════════════════════════════════

def test_an_english_record_is_interviewed_and_read_in_english(monkeypatch, translator):
    simulation_id = _gathering('en')
    set_locale('zh')  # the thread's language is not the record's
    sent = _runner(monkeypatch, {
        'twitter_0': ZH_ANSWER, 'reddit_0': EN_ANSWER_LINE,
        'twitter_1': PLATO_EN, 'reddit_1': '',
    })
    scribe = FakeScribe(summary='They quoted him: \n> “我不会走”，他说。\nThe city is split.')
    result = _service(scribe).interview_agents(simulation_id, 'the escape plan', 'Will Socrates escape?')

    assert result.language == 'en'
    # The citizens were asked in English, with English questions (a Chinese one translated first).
    prompt = sent[0]['interviews'][0]['prompt']
    assert prompt.startswith(zep_tools.INTERVIEW_PREFIX_EN)
    assert prompt.endswith(f'1. {EN_QUESTION}\n2. What happens next?')
    assert result.interview_questions == [EN_QUESTION, 'What happens next?']
    # Every helper prompt asks for the record's language.
    assert scribe.systems and all(s.rstrip().endswith(language_instruction_for('en')) for s in scribe.systems)
    assert all('in English' in s for s in scribe.systems)
    # One call for the questions, one for every answer and bio, one for the summary.
    assert len(translator.calls) == 3
    assert translator.calls[0] == [ZH_QUESTION]
    assert sorted(translator.calls[1]) == sorted([ZH_ANSWER, '他记下了一切。'])

    text = result.to_text()
    assert not language_guard.foreign_script(text, 'en'), [line for line in text.split('\n') if HAN.search(line)]
    crito, plato = result.interviews
    assert crito.response == f'[On Twitter]\n{EN_ANSWER_LINE}\n\n[On Reddit]\n{EN_ANSWER_LINE}'
    assert plato.response.endswith('[On Reddit]\n(no answer here)')
    assert plato.agent_bio == 'He wrote everything down.'
    assert crito.key_quotes and all(q.endswith('.') and '。' not in q for q in crito.key_quotes)
    assert result.summary == 'They quoted him: \n> "I will not go," he said.\nThe city is split.'
    for heading in ('## Interviews', '**Interviewed:** 2 / 3 citizens', '### Why these citizens',
                    '#### Interview #1: Crito', '#### Interview #2: Plato', '**Key quotes:**',
                    '### Summary and main views'):
        assert heading in text


def test_the_frontend_digest_still_reads_the_english_interview(monkeypatch, translator):
    simulation_id = _gathering('en')
    _runner(monkeypatch, {'twitter_0': PLATO_EN, 'reddit_0': PLATO_EN, 'twitter_1': PLATO_EN})
    text = _service(FakeScribe(questions=['Why?'])).interview_agents(simulation_id, 'the escape').to_text()
    # Step4Report.vue digestResult's own patterns.
    counted = re.search(r'(?:采访人数|interviewed)[^0-9\n]*(\d+)\s*/\s*(\d+)', text, re.I)
    assert counted and counted.groups() == ('2', '3')
    names = re.findall(r'^####\s*(?:采访|interview)\s*#?\s*\d+\s*[:：]\s*(.+)$', text, re.I | re.M)
    assert names == ['Crito', 'Plato']
    assert len(re.findall(r'\bTwitter\b', text)) == 2 and len(re.findall(r'\bReddit\b', text)) == 2


def test_a_chinese_record_keeps_its_chinese_and_calls_no_translator(monkeypatch, translator):
    simulation_id = _gathering('zh', requirement='苏格拉底会在船从提洛岛回来之前逃走吗？')
    set_locale('en')
    sent = _runner(monkeypatch, {'twitter_0': ZH_ANSWER, 'reddit_0': ZH_ANSWER, 'twitter_1': ZH_ANSWER})
    scribe = FakeScribe(summary='克里托与柏拉图都认为法律约束着他。')
    result = _service(scribe).interview_agents(simulation_id, '越狱计划')
    assert result.language == 'zh'
    assert sent[0]['interviews'][0]['prompt'].startswith(zep_tools.INTERVIEW_PREFIX_ZH)
    assert translator.calls == []
    assert all(s.rstrip().endswith(language_instruction_for('zh')) for s in scribe.systems)
    text = result.to_text()
    assert text.startswith('## 深度采访报告') and '【Twitter平台回答】' in text and '**关键引言:**' in text
    assert result.interviews[0].key_quotes == ['苏格拉底在对话中坚定论证，逃跑将违背他一生尊崇的城邦法律。']
    assert result.summary == '克里托与柏拉图都认为法律约束着他。'


def test_an_explicit_language_wins_and_a_record_without_one_reads_its_question(monkeypatch, translator):
    older = _gathering(None, requirement='苏格拉底会逃走吗？这是城邦的问题。')
    _runner(monkeypatch, {'twitter_0': ZH_ANSWER})
    assert _service(FakeScribe()).interview_agents(older, 'x').language == 'zh'
    assert _service(FakeScribe()).interview_agents(older, 'x', language='en').language == 'en'
    monkeypatch.setenv(language_guard.RECORD_LANGUAGE_ENV, 'en')
    assert _service(FakeScribe()).interview_agents(older, 'x').language == 'en'


def test_a_failed_interview_is_told_in_the_records_language(monkeypatch, translator):
    simulation_id = _gathering('en')
    _runner(monkeypatch, {}, success=False, error='模拟环境未运行或已关闭，无法执行Interview')
    result = _service(FakeScribe()).interview_agents(simulation_id, 'x')
    assert result.summary == 'The interviews could not be held: the square did not answer. Check that the square is still open.'
    _runner(monkeypatch, {}, error=ValueError('模拟环境未运行或已关闭，无法执行Interview: sim_x'))
    result = _service(FakeScribe()).interview_agents(simulation_id, 'x')
    assert result.summary.startswith('The interviews failed: the square did not answer.')
    # A square that ran out of time says so in the record's words, not the IPC's.
    _runner(monkeypatch, {}, error=TimeoutError('No answer to the command within 180.0 seconds'))
    result = _service(FakeScribe()).interview_agents(simulation_id, 'x')
    assert result.summary == 'The interviews ran into an error: the square did not answer in time'
    chinese = _service(FakeScribe()).interview_agents(_gathering('zh'), 'x').summary
    assert chinese == '采访过程发生错误：模拟环境未在规定时间内回应'
    for text in (result.to_text(), InterviewResult('x', [], language='en').to_text()):
        assert not language_guard.foreign_script(text, 'en')
    service = _service(FakeScribe())
    service._load_agent_profiles = lambda _simulation_id: []
    assert service.interview_agents(simulation_id, 'x').summary == 'No roll of citizens was found to interview.'


def test_the_helpers_fall_back_in_the_records_language():
    class Broken:
        def chat_json(self, **_kwargs):
            raise RuntimeError('down')

        def chat(self, **_kwargs):
            raise RuntimeError('down')

    service = _service(Broken())
    assert service._generate_interview_questions('the escape', '', PROFILES, language='en') == [
        'What is your view on the escape?',
        'What did it mean for you, or for the people you speak for?',
        'How do you think it should be settled or improved?',
    ]
    assert service._generate_interview_questions('越狱', '', PROFILES, language='zh')[0] == '关于越狱，您的观点是什么？'
    assert service._select_agents_for_interview(PROFILES, 'x', '', 2, language='en')[2] == (
        'The first citizens on the roll (the default choice).')
    assert service._select_agents_for_interview(PROFILES, 'x', '', 2, language='zh')[2] == '使用默认选择策略'
    interviews = [AgentInterview('Crito', 'friend', '', 'q', 'a'), AgentInterview('Plato', 'student', '', 'q', 'a')]
    assert service._generate_interview_summary(interviews, 'x', language='en') == 'Interviewed 2 citizens: Crito, Plato'
    assert service._generate_interview_summary([], 'x', language='en') == 'No interviews were completed.'
    assert service._generate_sub_queries('the escape', 'req', language='en') == [
        'the escape', 'the escape: who took part', 'the escape: causes and effects', 'the escape: how it unfolded',
    ]
    assert service._generate_sub_queries('越狱', 'req', language='zh')[1] == '越狱 的主要参与者'


def test_sub_queries_are_asked_for_and_kept_in_the_records_language(translator):
    translator.table['谁反对越狱？'] = 'Who opposed the escape?'
    scribe = FakeScribe()
    queries = _service(scribe, translator)._generate_sub_queries('the escape', 'req', language='en')
    assert queries == ['Who planned the escape?', 'Who opposed the escape?']
    assert scribe.systems[0].rstrip().endswith(language_instruction_for('en'))
    assert 'Written in English' in scribe.systems[0]


# ═══════════════════════════════════════════════════════════════
# The tools' texts
# ═══════════════════════════════════════════════════════════════

def test_the_search_texts_are_english_for_an_english_record_and_upstream_for_a_chinese_one():
    forge = InsightForgeResult(
        query='the escape', simulation_requirement='Will he escape?', sub_queries=['Who planned it?'],
        semantic_facts=['Crito bribed the guard.'], total_facts=1, total_entities=1, total_relationships=0,
        entity_insights=[{'name': 'Crito', 'type': 'Person', 'summary': 'A friend.', 'related_facts': ['x']}],
    )
    panorama = PanoramaResult(query='the escape', active_facts=['a', 'b'], historical_facts=['[unknown - now] c'],
                              total_nodes=3, total_edges=4, active_count=2, historical_count=1,
                              all_nodes=[NodeInfo('u', 'Crito', ['Entity'], '', {})])
    search = SearchResult(facts=['a', 'b'], edges=[], nodes=[], query='the escape', total_count=2)
    for result in (forge, panorama, search):
        result.language = 'en'
        assert not language_guard.foreign_script(result.to_text(), 'en'), result.to_text()
    # Step4Report.vue digestResult's own patterns still count them.
    assert re.search(r'relevant facts[^0-9\n]{0,16}(\d+)', forge.to_text(), re.I).group(1) == '1'
    assert re.search(r'###\s*(?:sub-?questions)[^\n]*\n([\s\S]*?)(?=\n###|$)', forge.to_text(), re.I)
    assert re.search(r'active facts[^0-9\n]{0,16}(\d+)', panorama.to_text(), re.I).group(1) == '2'
    assert re.search(r'found[^0-9\n]{0,16}(\d+)', search.to_text(), re.I).group(1) == '2'
    assert '- **Crito** (entity)' in panorama.to_text()
    for result in (forge, panorama, search):
        result.language = 'zh'
    assert forge.to_text().startswith('## 未来预测深度分析\n分析问题: the escape')
    assert panorama.to_text().startswith('## 广度搜索结果（未来全景视图）')
    assert search.to_text().startswith('搜索查询: the escape\n找到 2 条相关信息')


def test_a_text_without_a_language_reads_in_the_threads():
    search = SearchResult(facts=[], edges=[], nodes=[], query='q', total_count=0)
    set_locale('zh')
    assert search.to_text().startswith('搜索查询')
    set_locale('en')
    assert search.to_text().startswith('Search query')


# ═══════════════════════════════════════════════════════════════
# The preparation's own failure, for the visitor watching
# ═══════════════════════════════════════════════════════════════

def test_a_failed_preparation_without_words_is_told_in_the_viewers_language(monkeypatch):
    import threading

    from app import create_app
    from app.api import simulation as simulation_api
    from app.models.task import TaskManager
    from app.services.simulation_manager import SimulationState, SimulationStatus
    from app.services.zep_entity_reader import FilteredEntities

    class Reader:
        def filter_defined_entities(self, **_kwargs):
            return FilteredEntities(entities=[], entity_types=set(), total_count=0, filtered_count=0)

    def failed(self, simulation_id, **_kwargs):
        return SimulationState(simulation_id=simulation_id, project_id='', graph_id='',
                               status=SimulationStatus.FAILED, error=None)

    simulation_id = _gathering('en')
    monkeypatch.setattr(simulation_api, 'ZepEntityReader', Reader)
    monkeypatch.setattr(SimulationManager, 'prepare_simulation', failed)
    monkeypatch.setattr(threading.Thread, 'start', lambda self: self.run())
    app = create_app()
    app.config.update(TESTING=True)
    client = app.test_client()
    errors = []
    for headers in ({'Accept-Language': 'en'}, {'Accept-Language': 'zh-CN,zh;q=0.9'}):
        response = client.post('/api/simulation/prepare', json={'simulation_id': simulation_id}, headers=headers)
        assert response.status_code == 200
        errors.append(TaskManager().get_task(response.get_json()['data']['task_id']).error)
    assert errors == [f'Preparation failed: {simulation_id}', f'准备失败: {simulation_id}']
