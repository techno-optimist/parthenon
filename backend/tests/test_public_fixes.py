"""What the check of the public steps found, fixed and held:

- the Scribe's chapters and answers never carry a model's call markup,
  planning or a soup of fragments (services/model_output.py);
- nothing a visitor asks waits on the model past the edge's 100 s, and
  beginning a gathering answers at once with its key (utils/time_budget.py,
  the Hearing's task);
- a square left open after its argument holds a seat, and idle ones close
  (public/envs.py);
- records are written whole (utils/json_files.py);
- a browser's own Accept-Language is read as the city's language;
- citizens are from where their scroll places them, not China.
"""

import json
import os
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import openai
import pytest
from flask import jsonify

from app.api import graph as graph_api
from app.models.project import ProjectManager, ProjectStatus
from app.models.task import TaskManager, TaskStatus
from app.public import envs, lineage
from app.public import guard as guard_module
from app.public.words import header_language, in_other_language
from app.services import model_output, symposium_memory
from app.services.oasis_profile_generator import DEFAULT_COUNTRY, OasisAgentProfile, OasisProfileGenerator
from app.services.report_agent import ReportAgent, ReportManager, ReportOutline, ReportSection
from app.services.simulation_ipc import SimulationIPCClient, CommandType
from app.services.simulation_runner import RunnerStatus, SimulationRunner
from app.utils import json_files, time_budget
from app.utils import locale as locale_utils
from app.utils.llm_client import LLMClient
from app.utils.locale import set_locale, t

from test_public_mode import (  # noqa: F401 - fixtures
    ADMIN_KEY, EXHIBIT_SIM, OWNED_PROJECT, OWNED_SIM, OWNER_TOKEN, VISITOR_A, _begin, _start,
    _stub, _visitor, ask, city, fake_ontology, make_project, make_simulation, ready_gathering, speaker,
)


# The check's own evidence (report_c9d23068fad0, the Scribe's answer to visitor C).
LFM_CALL = (
    "<|tool_call_start|>[panorama_search(query='who changed their mind about locking the Kerameikos well'), "
    "quick_search(query='Kerameikos well lock change of mind Lysias potter Phaedra')]<|tool_call_end|>"
)
FUNCTION_CALL = (
    "<tool_call>\n<function=interview_citizens>\n<parameter=interview_topic>\n"
    "whether the well of the Kerameikos should be locked at night\n</parameter>\n"
    "<parameter=max_citizens>\n5\n</parameter>\n</function>\n</tool_call>"
)
PLANNING = (
    '" then the chapter.\n\nI\'ll structure it something like:\n\nThe question of the Kerameikos well '
    'divided the city...\n\nBut I need to quote by name. Let\'s list the quotes I want to use:'
)
SOUP = (
    "( ( 1 C C C C They C C C C they C C Pl C Ch C C C C C C C C they they C C C they there they they g th "
    "T T B C R Pl / C h they C C H Ch g they C pas g they g ... w ( py ros ( sk y ( ( bro x y y / tro ( dom "
    "... nr pin broist gar char gira ru ( h ... ( ( hyper nr pin dom dom ( gar spinina y ... / da y ( coll "
    "( dom dom br spin y ~ ( / py da b mi dom y ( y ( dom y y y chip y dom dom ( / / h y ru y y kg bra dom "
    "* u ** / mi pie y gira pic (mer giraudo rag bra mer / ( mi dom mer (// a y y / dom br y yña -- dom "
    "gira ña dom ( / d * ( bra pic dom ña h ( dom dom y ña y / / dom y ña -parseroo ( a ros y y n yña ( ( "
)
PROSE = (
    "The question of the Kerameikos well divided the city within a day. Kleon the magistrate asked for a "
    "small fee on every jar, to pay for a second well, and promised that the silver would go to nothing "
    "else. The potters answered first: their kilns need water before dawn, and a lock at dusk would close "
    "their night's work. Phaedra, who carries water for three households, said that a fee falls hardest "
    "on those who carry the most, and the Stoa took up her words by evening. By the second day the city "
    "had not changed its mind so much as sharpened it: the vote at the Pnyx was set, and no one expected "
    "it to settle the matter of who may drink at night."
)
CHINESE_PROSE = (
    "关于凯拉米克斯水井的问题，城邦在一天之内就分成了几派。行政官克勒翁提议对每一罐水收取少量费用，"
    "用来修建第二口井，并承诺这笔钱不会挪作他用。陶工们最先回应：他们的窑在黎明前需要水，"
    "黄昏上锁会断了他们一夜的活计。为三户人家挑水的菲德拉说，收费对挑水最多的人最重。"
)


# ================================================================== the Scribe's words

def test_a_models_own_call_markup_is_read_as_calls():
    assert model_output.pythonic_tool_calls(LFM_CALL) == [
        {'name': 'panorama_search', 'parameters': {'query': 'who changed their mind about locking the Kerameikos well'}},
        {'name': 'quick_search', 'parameters': {'query': 'Kerameikos well lock change of mind Lysias potter Phaedra'}},
    ]
    assert model_output.function_tag_calls(FUNCTION_CALL) == [{
        'name': 'interview_citizens',
        'parameters': {'interview_topic': 'whether the well of the Kerameikos should be locked at night',
                       'max_citizens': 5},
    }]
    # Never evaluated: anything but a literal is dropped.
    assert model_output.pythonic_tool_calls("<|tool_call_start|>[quick_search(query=__import__('os'))]") == [
        {'name': 'quick_search', 'parameters': {}}
    ]


def test_markup_is_stripped_and_what_is_left_is_judged():
    assert model_output.strip_markup(LFM_CALL) == ''
    assert model_output.strip_markup(FUNCTION_CALL) == ''
    assert model_output.strip_markup('The city voted.<|im_end|>') == 'The city voted.'
    assert model_output.problem('') == 'empty'
    assert model_output.problem('Let me search: panorama_search(query="well")') == 'markup'
    assert model_output.problem('<|toolcallstart|>[x]') == 'markup'
    assert model_output.problem(PLANNING) == 'planning'
    assert model_output.problem('User Safety: safe') == 'planning'
    assert model_output.problem('I now have enough material. Final Answer: The city voted.') == 'planning'
    assert model_output.problem(PROSE + ' ' + SOUP) == 'degenerate'
    assert model_output.problem('The ' + 'C ' * 30) == 'degenerate'


@pytest.mark.parametrize('text', [
    PROSE,
    CHINESE_PROSE * 3,
    # A chapter may quote a citizen who says "I need" and use Markdown's marks.
    '**The Vote Is Set**\n\n> "I need the water before dawn," said Lysias the potter.\n\n' + PROSE,
    '| Citizen | Where they stood |\n| --- | --- |\n| Kleon | for the fee |\n| Phaedra | against |\n\n' + PROSE,
    # A short sentence said again and again is not a soup.
    'Despina Nomikou still holds the casting vote. ' * 20,
    # An answer may open plainly; a rule is not a repeat.
    'Let me put it plainly: the potters changed their minds first.',
    'Well, I saw Phaedra at the well before dawn.',
    '====================\n\n* * * * * * * * * *\n\n' + PROSE,
    'The simulated agents on Twitter cheered for hours and would not stop. ' * 12,
])
def test_real_prose_is_left_alone(text):
    assert model_output.problem(text) is None


class ScriptedLLM:
    def __init__(self, replies):
        self.replies = list(replies)
        self.seen = []

    def chat(self, messages, **_kwargs):
        self.seen.append([dict(m) for m in messages])
        return self.replies.pop(0)


SEARCHES = [
    '<tool_call>{"name": "panorama_search", "parameters": {"query": "well"}}</tool_call>',
    '<tool_call>{"name": "quick_search", "parameters": {"query": "fee"}}</tool_call>',
    '<tool_call>{"name": "insight_forge", "parameters": {"query": "lock"}}</tool_call>',
]


def make_agent(llm, monkeypatch=None):
    agent = ReportAgent(graph_id='g', simulation_id='sim_scribe_fix', simulation_requirement='Lock the well?',
                        llm_client=llm, zep_tools=MagicMock())
    agent.report_logger = None
    agent._execute_tool = MagicMock(return_value='Kleon: a fee for a second well.')
    return agent


def write_section(agent):
    outline = ReportOutline(title='The Well', summary='', sections=[ReportSection(title='The Question')])
    return agent._generate_section_react(outline.sections[0], outline, previous_sections=[])


@pytest.fixture
def english_thread():
    """This thread reads English for the test, and the test leaves no locale behind."""

    set_locale('en')
    yield
    vars(locale_utils._thread_local).pop('locale', None)


def test_a_chapter_of_notes_and_soup_is_asked_for_once_more():
    llm = ScriptedLLM([*SEARCHES, 'Final Answer: ' + PLANNING + ' ' + SOUP, 'Final Answer: ' + PROSE])
    agent = make_agent(llm)

    assert write_section(agent) == PROSE
    again = llm.seen[-1]
    assert again[-1]['content'] == 'That was not the chapter: it held notes, plans or markup. Write the chapter ' \
        'itself now, in plain prose, as the Scribe: begin with "Final Answer:" and then only the chapter. ' \
        'No plans, no searches, no tags.'
    # The bad reply is not shown back to the model.
    assert all(SOUP not in m['content'] for m in again)


def test_a_chapter_that_fails_twice_is_set_down_unfinished(english_thread):
    llm = ScriptedLLM([*SEARCHES, 'Final Answer: ' + PLANNING, 'Final Answer: ' + SOUP])

    assert write_section(make_agent(llm)) == t('scribe.chapterUnwritten')


def test_the_forced_chapter_is_checked_too(english_thread):
    llm = ScriptedLLM([
        *SEARCHES,
        SEARCHES[0], SEARCHES[1],  # the iterations run out
        'Okay, let me write "Final Answer:" then the chapter. ' + SOUP,  # forced: notes and soup
        LFM_CALL,  # asked again: only markup
    ])

    assert write_section(make_agent(llm)) == t('scribe.chapterUnwritten')


def test_a_function_tag_call_is_run_as_a_search():
    llm = ScriptedLLM([FUNCTION_CALL, *SEARCHES[:2], 'Final Answer: ' + PROSE])
    agent = make_agent(llm)

    assert write_section(agent) == PROSE
    assert agent._execute_tool.call_args_list[0].args[:2] == (
        'interview_agents',
        {'interview_topic': 'whether the well of the Kerameikos should be locked at night', 'max_citizens': 5},
    )


@pytest.fixture
def no_chronicle(monkeypatch):
    monkeypatch.setattr(ReportManager, 'get_report_by_simulation', classmethod(lambda _cls, _sid: None))


def test_the_scribe_runs_a_call_in_her_own_markup_then_answers(no_chronicle):
    llm = ScriptedLLM([LFM_CALL, 'Phaedra changed her mind when the fee was named.'])
    agent = make_agent(llm)

    result = agent.chat('Who changed their mind about locking the well, and why?')

    assert result['response'] == 'Phaedra changed her mind when the fee was named.'
    assert agent._execute_tool.call_args_list[0].args[0] == 'panorama_search'


def test_the_scribe_never_answers_with_markup(no_chronicle, english_thread):
    # Markup the parser cannot take apart, twice: the fallback line, never the markup.
    llm = ScriptedLLM(['<|tool_call_start|>[panoramasearch(query=]<|tool_call_end|>',
                       '<|toolcallstart|>[quicksearch(query="well")]<|toolcallend|>'])

    result = make_agent(llm).chat('Who changed their mind?')

    assert result['response'] == t('scribe.answerLost')
    assert '<|' not in result['response']


def test_the_scribes_answer_loses_a_final_answer_marker(no_chronicle):
    llm = ScriptedLLM(['**Final Answer:** The potters changed their minds first.'])
    assert make_agent(llm).chat('Who moved?')['response'] == 'The potters changed their minds first.'


def test_the_scribe_is_asked_once_more_and_her_second_answer_stands(no_chronicle):
    llm = ScriptedLLM(['User Safety: safe', 'The potters changed their minds first.'])

    assert make_agent(llm).chat('Who moved?')['response'] == 'The potters changed their minds first.'
    assert llm.seen[-1][-1]['content'].startswith("Answer the visitor's question now")


def test_a_remembered_answer_loses_the_markup():
    g = SimpleNamespace(roster={}, time_unit='hour', requirement='Lock the well?', citizens={})
    answer = symposium_memory.tidy_answer('<|tool_call_start|>[quick_search(query="x")]<|tool_call_end|>The well '
                                          'should stay open.', g, lang='en')
    assert answer == 'The well should stay open.'


# ================================================================== the time a question may take

def test_the_budget_belongs_to_the_request_thread():
    time_budget.clear()
    assert time_budget.remaining() is None and time_budget.cap(40) == 40 and time_budget.call_seconds() is None
    time_budget.begin(30)
    try:
        assert 29 < time_budget.remaining() <= 30
        assert time_budget.cap(200) <= 30 and time_budget.cap(5) == 5
        seen = []
        worker = threading.Thread(target=lambda: seen.append(time_budget.remaining()))
        worker.start()
        worker.join()
        assert seen == [None]
        time_budget.begin(1)
        with pytest.raises(time_budget.TimeBudgetSpent):
            time_budget.call_seconds()
        assert time_budget.spent()
    finally:
        time_budget.clear()
    assert not time_budget.spent() and time_budget.remaining() is None


class FakeCompletions:
    def __init__(self, owner):
        self.owner = owner

    def create(self, **kwargs):
        self.owner.calls.append(dict(self.owner.options))
        if self.owner.raise_timeout:
            raise openai.APITimeoutError(request=MagicMock())
        message = SimpleNamespace(content='The city answers.')
        return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason='stop')])


class FakeOpenAI:
    def __init__(self, timeout=None, calls=None, raise_timeout=False, options=None):
        self.timeout = timeout
        self.calls = [] if calls is None else calls
        self.raise_timeout = raise_timeout
        self.options = options or {}
        self.chat = SimpleNamespace(completions=FakeCompletions(self))

    def with_options(self, **options):
        return FakeOpenAI(timeout=options.get('timeout'), calls=self.calls,
                          raise_timeout=self.raise_timeout, options=options)


def _client(fake):
    llm = LLMClient(api_key='test-key', base_url='http://127.0.0.1:9/v1', model='m')
    llm.client = fake
    return llm


def test_a_call_inside_the_budget_gets_the_time_left_and_no_retries():
    fake = FakeOpenAI()
    llm = _client(fake)
    assert llm.chat([{'role': 'user', 'content': 'Why?'}]) == 'The city answers.'
    assert fake.calls == [{}]  # no budget: the client as it is

    time_budget.begin(50)
    try:
        llm.chat([{'role': 'user', 'content': 'Why?'}])
        options = fake.calls[-1]
        assert options['max_retries'] == 0 and 45 < options['timeout'] <= 50
        # A caller's own shorter timeout stands (the Symposium's per-answer clock).
        _client(FakeOpenAI(timeout=12.0, calls=fake.calls)).chat([{'role': 'user', 'content': 'Why?'}])
        assert fake.calls[-1]['timeout'] == 12.0
    finally:
        time_budget.clear()


def test_a_call_that_runs_out_the_budget_says_so():
    llm = _client(FakeOpenAI(raise_timeout=True))
    with pytest.raises(openai.APITimeoutError):
        llm.chat([{'role': 'user', 'content': 'Why?'}])  # no budget: the provider's error
    time_budget.begin(40)
    try:
        with pytest.raises(time_budget.TimeBudgetSpent):
            llm.chat([{'role': 'user', 'content': 'Why?'}])
        assert time_budget.spent()
    finally:
        time_budget.clear()


def test_a_wait_on_the_square_is_cut_to_the_budget(tmp_path):
    ipc = SimulationIPCClient(str(tmp_path))
    time_budget.begin(1)
    try:
        with pytest.raises(time_budget.TimeBudgetSpent):
            ipc.send_command(CommandType.INTERVIEW, {'agent_id': 0}, timeout=120)
        assert os.listdir(tmp_path / 'ipc_commands') == []  # nothing was sent to wait on
        time_budget.begin(3.5)
        started = time.monotonic()
        with pytest.raises(TimeoutError):
            ipc.send_command(CommandType.INTERVIEW, {'agent_id': 0}, timeout=120, poll_interval=0.1)
        assert time.monotonic() - started < 10
        assert time_budget.spent()
    finally:
        time_budget.clear()


def test_remembered_answers_keep_within_the_budget():
    assert symposium_memory.deadline(None, 'batch') == symposium_memory.DEFAULT_DEADLINES['batch']
    time_budget.begin(85)
    try:
        assert symposium_memory.deadline(None, 'batch') <= 85
        assert symposium_memory.deadline(250, 'single') <= 85
    finally:
        time_budget.clear()


def _slow_view(seen):
    def view(**_kwargs):
        seen.append(time_budget.remaining())
        try:
            time_budget.begin(0)
            time_budget.call_seconds()
        except time_budget.TimeBudgetSpent as error:
            return jsonify({'success': False, 'error': str(error), 'traceback': 'Traceback ...'}), 500
        return jsonify({'success': True}), 200
    return view


def test_a_question_that_runs_out_of_time_is_answered_calmly_and_given_back(city):
    # Questions answered directly (without tickets) keep the request's own budget.
    city.env(PARTHENON_QUESTIONS_PER_HOUR=1, PARTHENON_REQUEST_SECONDS=60, PARTHENON_QUESTION_TICKETS=0)
    app = city.app()
    seen = []
    app.view_functions['report.chat_with_report_agent'] = _slow_view(seen)
    client = app.test_client()

    first = client.post('/api/report/chat', json={'simulation_id': EXHIBIT_SIM, 'message': 'Why?'},
                        headers=_visitor(VISITOR_A, **{'Accept-Language': 'en-US,en;q=0.9'}))

    assert 55 < seen[0] <= 60
    assert first.status_code == 503
    assert first.json == {
        'success': False, 'code': 'slow_down', 'retry_after_seconds': 60,
        'error': 'The city took too long over that and set it down. Ask again in a little while.',
    }
    # The question was given back: the visitor may ask again this hour.
    second = client.post('/api/report/chat', json={'simulation_id': EXHIBIT_SIM, 'message': 'Why?'},
                         headers=_visitor(VISITOR_A, **{'Accept-Language': 'zh-CN'}))
    assert second.status_code == 503 and '城邦' in second.json['error']
    assert time_budget.remaining() is None  # the request's budget ended with it


def test_on_the_owners_machine_a_question_has_no_budget(city):
    app = city.app(public=False)
    seen = []
    app.view_functions['report.chat_with_report_agent'] = lambda: (seen.append(time_budget.remaining()), jsonify({}))[1]
    app.test_client().post('/api/report/chat', json={'simulation_id': EXHIBIT_SIM, 'message': 'Why?'})
    assert seen == [None]


# ------------------------------------------------------------------ the Hearing is a task

def test_beginning_answers_at_once_with_the_key_and_a_task(city, fake_ontology):
    client = city.client()

    response = _begin(client)

    assert response.status_code == 200
    data = response.json['data']
    assert data['owner_token'] and data['task_id'] and data['status'] == 'created'
    assert lineage.token_owns(data['owner_token'], data['project_id'])
    # The reading (inline here) set the ontology, and the Web began in the same task.
    project = ProjectManager.get_project(data['project_id'])
    assert project.status == ProjectStatus.ONTOLOGY_GENERATED and project.ontology['entity_types']
    assert fake_ontology == [(data['project_id'], data['task_id'])]


def test_the_web_asked_for_during_the_reading_is_the_same_task(city, fake_ontology, monkeypatch):
    held = []
    monkeypatch.setattr(graph_api, '_in_background', lambda target, _name: held.append(target))
    monkeypatch.setattr(graph_api, '_zep_key_unusable', lambda: False)
    client = city.client()
    begun = _begin(client).json['data']
    owner = {'X-Parthenon-Owner': begun['owner_token']}

    build = client.post('/api/graph/build', json={'project_id': begun['project_id']}, headers=owner)

    assert build.status_code == 200 and build.json['data']['task_id'] == begun['task_id']
    polled = client.get(f"/api/graph/task/{begun['task_id']}")
    assert polled.status_code == 200 and polled.json['data']['status'] == 'pending'
    # A page opened afresh finds the task on the project.
    project = client.get(f"/api/graph/project/{begun['project_id']}").json['data']
    assert project['status'] == 'created' and project['hearing_task_id'] == begun['task_id']
    held[0]()  # the scroll is read
    assert fake_ontology == [(begun['project_id'], begun['task_id'])]
    assert TaskManager().get_task(begun['task_id']).progress == 5
    assert 'hearing_task_id' not in client.get(f"/api/graph/project/{begun['project_id']}").json['data']


def test_a_scroll_that_cannot_be_read_gives_the_day_back(city, fake_ontology, monkeypatch):
    city.env(PARTHENON_DAILY_PER_VISITOR=1)

    class Broken:
        def generate(self, **_kwargs):
            raise RuntimeError('provider said no at /Users/someone/.env')

    monkeypatch.setattr(graph_api, 'OntologyGenerator', Broken)
    client = city.client()

    begun = _begin(client).json['data']

    project = ProjectManager.get_project(begun['project_id'])
    assert project.status == ProjectStatus.FAILED
    task = client.get(f"/api/graph/task/{begun['task_id']}").json['data']
    assert task['status'] == 'failed' and '/Users' not in json.dumps(task)
    assert fake_ontology == []
    status = client.get('/api/parthenon/status', headers=_visitor(VISITOR_A)).json['data']
    assert status['limits']['visitor_left'] == 1
    monkeypatch.setattr(graph_api, 'OntologyGenerator', lambda: SimpleNamespace(generate=lambda **_k: {}))
    assert _begin(client).status_code == 200  # the day's gathering came back


def test_on_the_owners_machine_the_hearing_is_still_one_answer(city, fake_ontology):
    data = _begin(city.client(public=False)).json['data']
    assert data['ontology']['entity_types'] == [{'name': 'Citizen'}]
    assert 'task_id' not in data and fake_ontology == []


def test_the_hearing_continues_into_the_real_build(city, monkeypatch):
    """_build_graph_impl continues the Hearing's task instead of making a new one."""

    class Builder:
        def __init__(self, api_key=None):
            pass

        def validate_batch_chunks(self, chunks, batch_size):
            pass

        def create_graph(self, name, graph_id_callback):
            graph_id_callback('graph_heard')
            return 'graph_heard'

        def set_ontology(self, graph_id, ontology):
            pass

        def add_text_batches(self, graph_id, chunks, **kwargs):
            kwargs['batch_created_callback']('batch', 'operation')
            return SimpleNamespace(batch_id='batch')

        def _wait_for_batch(self, submission, callback):
            pass

        def get_graph_data(self, graph_id):
            return {'node_count': 3, 'edge_count': 2}

    monkeypatch.setattr(graph_api, 'GraphBuilderService', Builder)
    monkeypatch.setattr(graph_api, '_zep_key_unusable', lambda: False)
    app = city.app()
    project = ProjectManager.create_project(name='heard')
    project.status = ProjectStatus.ONTOLOGY_GENERATED
    project.ontology = {'entity_types': [{'name': 'Citizen'}], 'edge_types': []}
    ProjectManager.save_project(project)
    ProjectManager.save_extracted_text(project.project_id, 'The well is locked at night. ' * 20)
    task_id = TaskManager().create_task('ontology_generate')

    with graph_api._project_build_lock(project.project_id):
        graph_api._build_after_hearing(app, project.project_id, task_id)
    for _ in range(100):
        if TaskManager().get_task(task_id).status == TaskStatus.COMPLETED:
            break
        time.sleep(0.05)

    assert TaskManager().get_task(task_id).status == TaskStatus.COMPLETED
    built = ProjectManager.get_project(project.project_id)
    assert built.status == ProjectStatus.GRAPH_COMPLETED and built.graph_build_task_id == task_id


# ================================================================== open squares

class FakeProcess:
    def __init__(self, alive=True):
        self.alive = alive

    def poll(self):
        return None if self.alive else 0


@pytest.fixture
def squares(monkeypatch):
    states = {}
    processes = {}
    closed = []

    def close_finished_run(cls, simulation_id):
        closed.append(simulation_id)
        processes[simulation_id].alive = False

    monkeypatch.setattr(SimulationRunner, '_processes', processes)
    monkeypatch.setattr(SimulationRunner, '_start_claims', set())
    monkeypatch.setattr(SimulationRunner, 'get_run_state',
                        classmethod(lambda cls, sid: SimpleNamespace(runner_status=states[sid])))
    monkeypatch.setattr(SimulationRunner, 'close_finished_run', classmethod(close_finished_run))
    monkeypatch.setattr(envs, '_last_used', {})
    monkeypatch.setattr(envs, '_in_use', {})
    world = SimpleNamespace(states=states, processes=processes, closed=closed)

    def square(simulation_id, status=RunnerStatus.COMPLETED):
        states[simulation_id] = status
        processes[simulation_id] = FakeProcess()

    world.square = square
    return world


def test_an_open_square_after_its_run_is_found(squares):
    squares.square('sim_open1')
    squares.square('sim_running', RunnerStatus.RUNNING)
    squares.square('sim_gone')
    squares.processes['sim_gone'].alive = False

    assert envs.open_environments() == ['sim_open1']
    assert envs.open_environments(exclude='sim_open1') == []


def test_room_is_made_by_closing_the_least_recently_used_idle_square(squares):
    squares.square('sim_older')
    squares.square('sim_newer')
    envs.touch('sim_older')
    time.sleep(0.01)
    envs.touch('sim_newer')

    assert envs.make_room(2)
    assert squares.closed == ['sim_older']
    assert envs.make_room(1)
    assert squares.closed == ['sim_older', 'sim_newer']


def test_a_square_in_use_is_not_closed(squares, monkeypatch):
    squares.square('sim_asked')
    squares.square('sim_chronicled')
    held = envs.enter('sim_asked')
    TaskManager().create_task('report_generate', metadata={'simulation_id': 'sim_chronicled'})
    try:
        assert envs.busy('sim_asked') and envs.busy('sim_chronicled')
        assert not envs.make_room(1)
        assert squares.closed == []
        assert envs.busy_environments() == 2
    finally:
        envs.leave(held)
        for task in TaskManager().list_tasks('report_generate'):
            if task['metadata'].get('simulation_id') == 'sim_chronicled':
                TaskManager().update_task(task['task_id'], status=TaskStatus.COMPLETED)
    assert not envs.busy('sim_asked')


def test_idle_squares_close_after_a_while(squares, monkeypatch):
    squares.square('sim_idle')
    squares.square('sim_fresh')
    now = time.monotonic()
    envs._last_used.update({'sim_idle': now - 3600, 'sim_fresh': now})

    assert envs.close_idle(20 * 60) == ['sim_idle']


def test_a_new_run_closes_an_idle_square_first(city, squares):
    make_project(OWNED_PROJECT, token=OWNER_TOKEN)
    make_simulation(OWNED_SIM, OWNED_PROJECT)
    app = city.app()
    _stub(app, 'simulation.start_simulation')
    client = app.test_client()
    squares.square('sim_last_night')

    assert _start(client).status_code == 200
    assert squares.closed == ['sim_last_night']


def test_a_new_run_waits_while_the_open_square_is_in_use(city, squares, monkeypatch):
    make_project(OWNED_PROJECT, token=OWNER_TOKEN)
    make_simulation(OWNED_SIM, OWNED_PROJECT)
    app = city.app()
    _stub(app, 'simulation.start_simulation')
    client = app.test_client()
    squares.square('sim_last_night')
    held = envs.enter('sim_last_night')
    try:
        refused = _start(client)
        status = client.get('/api/parthenon/status').json['data']['limits']
    finally:
        envs.leave(held)

    assert refused.status_code == 429 and refused.json['code'] == 'city_full'
    assert squares.closed == []
    assert status['running'] == 1 and status['environments_open'] == 1
    # The run of the gathering was given back with the refusal: it may start once the square is free.
    assert _start(client).status_code == 200


def test_a_question_holds_its_square_while_it_is_asked(city, squares):
    app = city.app()
    seen = []

    def view():
        seen.append(envs.busy(EXHIBIT_SIM))
        return jsonify({'success': True})

    app.view_functions['simulation.interview_agents_batch'] = view
    ask(app.test_client(), '/api/simulation/interview/batch', {
        'simulation_id': EXHIBIT_SIM, 'interviews': [{'agent_id': 0, 'prompt': 'Why?'}],
    }, _visitor(VISITOR_A))

    assert seen == [True] and not envs.busy(EXHIBIT_SIM)


# ================================================================== records written whole

def test_a_record_is_written_whole_with_the_same_bytes(tmp_path):
    path = tmp_path / 'project.json'
    record = {'project_id': 'proj_x', 'name': 'Ἀθῆναι', 'files': [1, 2]}

    json_files.write_json_atomic(str(path), record)

    with open(tmp_path / 'expected.json', 'w', encoding='utf-8') as handle:
        json.dump(record, handle, ensure_ascii=False, indent=2)
    assert path.read_bytes() == (tmp_path / 'expected.json').read_bytes()
    assert sorted(os.listdir(tmp_path)) == ['expected.json', 'project.json']
    assert oct(path.stat().st_mode & 0o777) == oct(0o644)


def test_a_reader_never_sees_a_record_half_written(tmp_path):
    path = str(tmp_path / 'state.json')
    json_files.write_json_atomic(path, {'n': 0, 'pad': 'x' * 20000})
    stop = threading.Event()
    torn = []

    def writer():
        n = 0
        while not stop.is_set():
            n += 1
            json_files.write_json_atomic(path, {'n': n, 'pad': 'x' * 20000})

    def reader():
        for _ in range(400):
            try:
                with open(path, encoding='utf-8') as handle:
                    json.load(handle)
            except ValueError:
                torn.append(1)

    thread = threading.Thread(target=writer)
    thread.start()
    try:
        reader()
    finally:
        stop.set()
        thread.join()
    assert torn == []


def test_a_torn_record_is_read_again(tmp_path, monkeypatch):
    project_dir = tmp_path / 'projects' / 'proj_torn'
    project_dir.mkdir(parents=True)
    meta = project_dir / 'project.json'
    meta.write_text('{"project_id": "proj_to')
    monkeypatch.setattr(ProjectManager, 'PROJECTS_DIR', str(tmp_path / 'projects'))

    def finish_writing(_seconds):
        meta.write_text(json.dumps({'project_id': 'proj_torn', 'name': 'n', 'status': 'created'}))

    monkeypatch.setattr(json_files.time, 'sleep', finish_writing)

    assert ProjectManager.get_project('proj_torn').project_id == 'proj_torn'
    meta.write_text('{"project_id": "proj_to')
    assert lineage.project_record('proj_torn')['project_id'] == 'proj_torn'


def test_the_records_are_saved_whole(tmp_path, monkeypatch):
    writes = []
    real = json_files.write_json_atomic
    monkeypatch.setattr(json_files, 'write_json_atomic', lambda path, data, **kw: (writes.append(path), real(path, data, **kw)))
    from app.models import project as project_module
    from app.services import report_agent, simulation_manager, simulation_runner
    for module in (project_module, report_agent, simulation_manager, simulation_runner):
        monkeypatch.setattr(module, 'write_json_atomic', json_files.write_json_atomic)
    monkeypatch.setattr(ProjectManager, 'PROJECTS_DIR', str(tmp_path / 'projects'))

    ProjectManager.create_project(name='whole')

    assert writes and writes[0].endswith('project.json')


# ================================================================== the visitor's language

@pytest.mark.parametrize('header, expected', [
    ('en-US,en;q=0.9', 'en'), ('zh-CN,zh;q=0.9,en;q=0.8', 'zh'), ('en', 'en'), ('zh', 'zh'),
    ('fr-FR,fr;q=0.9', 'en'), ('', 'en'), (None, 'en'), ('de, zh-TW;q=0.5', 'zh'),
])
def test_a_browsers_language_is_the_citys(header, expected):
    assert header_language(header) == expected


def test_other_language_is_noticed():
    assert in_other_language('项目不存在: proj_x', 'en')
    assert not in_other_language('Project not found: proj_x', 'en')
    assert in_other_language('Chronicle not found.', 'zh')
    assert not in_other_language('找不到编年史。', 'zh')
    assert not in_other_language('', 'zh')


def test_not_found_follows_the_browsers_language(city):
    client = city.client()

    english = client.get('/api/graph/project/proj_doesnotexist', headers={'Accept-Language': 'en-US,en;q=0.9'})
    chinese = client.get('/api/graph/project/proj_doesnotexist', headers={'Accept-Language': 'zh-CN,zh;q=0.9'})

    assert english.status_code == 404 and english.json['error'] == 'Project not found: proj_doesnotexist'
    assert chinese.status_code == 404 and '项目不存在' in chinese.json['error']


def test_a_fixed_message_in_the_other_language_is_put_in_the_citys_words(city):
    app = city.app()
    app.view_functions['graph.get_project'] = lambda project_id: (
        jsonify({'success': False, 'error': f'模拟不存在: {project_id}'}), 404)
    app.view_functions['graph.get_task'] = lambda task_id: (
        jsonify({'success': False, 'error': 'Chronicle not found.'}), 400)
    client = app.test_client()

    english = client.get('/api/graph/project/proj_x', headers={'Accept-Language': 'en-US'})
    chinese = client.get('/api/graph/task/t1', headers={'Accept-Language': 'zh-CN'})

    assert english.json['error'] == 'Nothing stands at that address.'
    assert chinese.status_code == 400 and chinese.json['error'] == '城邦此刻做不到这件事。'


def test_on_the_owners_machine_the_browsers_language_is_read_too(city):
    # No public guard here: the engine's own words, in the browser's language,
    # and English when the browser names no language the city reads.
    client = city.client(public=False)

    english = client.get('/api/graph/project/proj_doesnotexist', headers={'Accept-Language': 'en-US'})
    chinese = client.get('/api/graph/project/proj_doesnotexist', headers={'Accept-Language': 'zh-CN,zh;q=0.9'})
    unnamed = client.get('/api/graph/project/proj_doesnotexist')
    other = client.get('/api/graph/project/proj_doesnotexist', headers={'Accept-Language': 'fr-FR,fr;q=0.9'})

    assert english.status_code == 404 and english.json['error'] == 'Project not found: proj_doesnotexist'
    assert chinese.status_code == 404 and '项目不存在' in chinese.json['error']
    assert unnamed.status_code == 404 and unnamed.json['error'] == 'Project not found: proj_doesnotexist'
    assert other.status_code == 404 and other.json['error'] == 'Project not found: proj_doesnotexist'


# ================================================================== where the citizens are from

def _profile(name, country=None):
    return OasisAgentProfile(user_id=0, user_name=name.lower(), name=name, bio='b', persona='p', country=country)


def test_a_citizen_without_a_country_is_from_where_the_crowd_is(tmp_path):
    generator = OasisProfileGenerator.__new__(OasisProfileGenerator)
    profiles = [_profile('Lysias', '希腊'), _profile('Kleon', '希腊'), _profile('Aristo', 'Greece'),
                _profile('Phaedra')]

    generator._save_reddit_json(profiles, str(tmp_path / 'reddit_profiles.json'))

    saved = json.loads((tmp_path / 'reddit_profiles.json').read_text(encoding='utf-8'))
    assert [item['country'] for item in saved] == ['希腊', '希腊', 'Greece', '希腊']
    assert OasisProfileGenerator.crowd_country([_profile('Phaedra')]) == DEFAULT_COUNTRY == 'Greece'


def _has_han(text):
    return any('一' <= ch <= '鿿' for ch in text)


def test_the_persona_prompts_no_longer_suggest_china():
    generator = OasisProfileGenerator.__new__(OasisProfileGenerator)
    chinese = OasisProfileGenerator.__new__(OasisProfileGenerator)
    chinese.language = 'zh'
    for name in ('_build_individual_persona_prompt', '_build_group_persona_prompt'):
        # A generator with no language writes for an English record: Greece, in English.
        prompt = getattr(generator, name)('Phaedra', 'WaterCarrier', 'carries water', {}, 'Athens, 410 BC')
        assert '"Greece"' in prompt and 'China' not in prompt and not _has_han(prompt)
        # A Chinese record, the generator's own or the one asked for: 希腊.
        for prompt in (
            getattr(chinese, name)('Phaedra', 'WaterCarrier', 'carries water', {}, 'Athens, 410 BC'),
            getattr(generator, name)('Phaedra', 'WaterCarrier', 'carries water', {}, 'Athens, 410 BC',
                                     language='zh'),
        ):
            assert '中国' not in prompt and '"希腊"' in prompt and '"Greece"' not in prompt
    for entity_type in ('student', 'expert', 'mediaoutlet', 'ngo', 'WaterCarrier'):
        profile = generator._generate_profile_rule_based('Phaedra', entity_type, 'carries water', {})
        assert profile['country'] is None
