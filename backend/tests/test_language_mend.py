"""The mend: records already written in the wrong language, put right in place.

Every test runs in temp folders (projects, crowds, Chronicles and the memory
store under a temp upload folder). The model is a fake that answers from a
fixed list of translations and remembers every line it was sent; the real
translator is never built.
"""

import csv
import io
import json
import os
import sqlite3

import pytest

from app import create_app
from app.config import Config
from app.memory.activity import ingest_activity_episode
from app.memory.store import MemoryStore, new_id, utcnow_iso
from app.memory.textnorm import name_key
from app.models.project import ProjectManager
from app.services import language_guard, language_mend
from app.services.report_agent import ReportManager
from app.services.simulation_manager import SimulationManager
from app.services.simulation_runner import SimulationRunner
from app.services.zep_graph_memory_updater import AgentActivity
from app.utils.locale import t


PROJECT = 'proj_hemlock0001'
SIMULATION = 'sim_hemlock0001'
REPORT = 'report_hemlock0001'
GRAPH = 'mirofish_hemlock0001'
ZH_PROJECT = 'proj_chinese0001'
ZH_SIMULATION = 'sim_chinese0001'
ZH_REPORT = 'report_chinese0001'
ADMIN_KEY = 'keeper-key-for-tests-0123456789abcdef'

REQUIREMENT = 'The jury has sentenced Socrates to death. What will Athens do in the thirty days?'
QUOTE_A = '"苏格拉底在对话中坚定论证，逃跑将违背他一生尊崇的城邦法律"'
QUOTE_B = '"若Crito的计划成功，城邦会视此为公然违抗"'
MIXED = 'By the will of Athena，我观察到一种新趋势。'
TITLE = '克里托的逃跑计划'
TURN = '欢迎Nerve条款使其转为支持。'
BIO = '来自雅典的公民，热爱辩论。'
LLM_FACT = '苏格拉底拒绝了逃跑的计划。'
POST = 'The gods have been avenged.'
TOOL_RESULT = '### 采访结果\n采访人数: 2 / 5\n苏格拉底说：法律如父母。'
NARRATION = '雅典的圣船已驶往提洛岛。'
CITIZEN_POST = '法律如父母般养育我们。'
SCROLL = '雅典的陪审团判处苏格拉底死刑。'
# A Chronicle of the English gathering written wholly in Chinese (the old default locale).
MANDARIN = 'report_mandarin0001'
ZH_CHRONICLE_TITLE = '毒芹之后'
ZH_CHAPTER = '雅典人争论了三十天。圣船还在提洛岛，城邦有一个月的时间来决定判决的意义。'

TRANSLATIONS = {
    ZH_CHRONICLE_TITLE: 'After the Hemlock',
    ZH_CHAPTER: 'The Athenians argued for thirty days. The sacred ship was still at Delos, and the city had '
                'a month to decide what the verdict meant.',
    QUOTE_A: '"In the dialogue Socrates argued firmly that fleeing would break the laws he had honoured all his life"',
    QUOTE_B: '"Had Crito\'s plan succeeded, the city would have seen it as open defiance"',
    MIXED: 'By the will of Athena, I observed a new trend.',
    TITLE: "Crito's Escape Plan",
    '希腊': 'Greece',
    TURN: 'Welcoming the Nerve clause brought it round to support.',
    BIO: 'A citizen of Athens who loves debate.',
    LLM_FACT: 'Socrates refused the plan to flee.',
}
EN_TITLE = TRANSLATIONS[TITLE]
EN_QUOTE_A = TRANSLATIONS[QUOTE_A]
EN_QUOTE_B = TRANSLATIONS[QUOTE_B]

NOTE_NUMBERS = {'status': 'stopping', 'round': 136, 'total': 336, 'pid': 52863}
ZH_NOTE = t('api.simRunInterrupted', locale='zh', **NOTE_NUMBERS)
EN_NOTE = t('api.simRunInterrupted', locale='en', **NOTE_NUMBERS)
ZH_ENV_NOTE = t('api.simEnvNotRunningInterview', locale='zh', id=SIMULATION)
EN_ENV_NOTE = t('api.simEnvNotRunningInterview', locale='en', id=SIMULATION)

# An English Chronicle reads as English: its prose outweighs the Chinese quoted in it.
CHAPTER_ONE = (
    'Athens argued for thirty days. The sacred ship was away at Delos, and no one could be put to death '
    'until it came home, so the city had a month to decide what the verdict meant. The priests said the '
    'gods had been answered; the young men who followed Socrates said the city had condemned its own '
    'conscience. In the agora the two sides met every morning and parted every evening further apart, '
    'and by the third week even the shopkeepers had chosen a side.\n\n> "The gods are avenged."'
)
PERSONAS = (
    'Socrates walks the agora barefoot and questions everyone he meets about justice, courage and the good life.',
    'Crito is a wealthy friend of Socrates who has the money and the will to bribe the guards of the prison.',
    'Plato is a young student who writes down what his teacher says and fears what the city will do to him.',
)
ENGLISH_FACT = 'Crito offered to bribe the guards so that Socrates could leave before the sacred ship returned from Delos.'
CHAPTER_TWO = f"Crito's plan failed.\n\n> {QUOTE_A}\n\n> **Crito:** {QUOTE_B}\n\n{MIXED}"


class FakeTranslator:
    """The model: fixed translations, and every line it was sent."""

    def __init__(self, fail=False):
        self.sent = []
        self.fail = fail

    def chat_json(self, messages, temperature=None, max_tokens=None):
        lines = json.loads(messages[-1]['content'])['lines']
        self.sent.extend(lines)
        if self.fail:
            raise RuntimeError('the model is away')
        return {'lines': [TRANSLATIONS.get(line, 'UNKNOWN LINE') for line in lines]}


def _no_model():
    raise AssertionError('the real translator must never be built in these tests')


def _write_json(path, data, indent=2):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump(data, handle, ensure_ascii=False, indent=indent)


def _write_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='') as handle:
        handle.write(text)


def _read(path):
    with open(path, 'r', encoding='utf-8', newline='') as handle:
        return handle.read()


def _load(path):
    with open(path, 'r', encoding='utf-8') as handle:
        return json.load(handle)


def _agent_log(rows):
    return ''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows)


class World:
    """A temp upload folder holding an English gathering written partly in Chinese, and a Chinese one."""

    def __init__(self, uploads):
        self.uploads = str(uploads)
        self.reports = os.path.join(self.uploads, 'reports')
        self.simulations = os.path.join(self.uploads, 'simulations')
        self.projects = os.path.join(self.uploads, 'projects')
        self.db = os.path.join(self.uploads, 'memory', 'local_memory.sqlite3')

    def report(self, name, report_id=REPORT):
        return os.path.join(self.reports, report_id, name)

    def simulation(self, name, simulation_id=SIMULATION):
        return os.path.join(self.simulations, simulation_id, name)

    def snapshot(self):
        """Every file's bytes (the memory store's rows through SQL: its WAL files move on a read)."""

        files = {}
        for root, _dirs, names in os.walk(self.uploads):
            for name in names:
                path = os.path.join(root, name)
                if 'memory' in os.path.relpath(path, self.uploads).split(os.sep)[0]:
                    continue
                with open(path, 'rb') as handle:
                    files[os.path.relpath(path, self.uploads)] = handle.read()
        files['memory rows'] = self.memory_rows()
        return files

    def memory_rows(self):
        conn = sqlite3.connect(self.db)
        try:
            return (
                conn.execute('SELECT id, fact, fact_key FROM edges ORDER BY id').fetchall(),
                conn.execute('SELECT id, name, summary FROM nodes ORDER BY id').fetchall(),
                conn.execute('SELECT id, content FROM episodes ORDER BY id').fetchall(),
            )
        finally:
            conn.close()

    def memory(self, sql, *args):
        conn = sqlite3.connect(self.db)
        conn.row_factory = sqlite3.Row
        try:
            return conn.execute(sql, args).fetchall()
        finally:
            conn.close()


def _build_english_gathering(world):
    _write_json(os.path.join(world.projects, PROJECT, 'project.json'), {
        'project_id': PROJECT, 'name': 'The Hemlock Horizon', 'status': 'graph_completed',
        'created_at': '2026-09-25T14:00:00', 'updated_at': '2026-09-25T14:00:00', 'graph_id': GRAPH,
        'simulation_requirement': REQUIREMENT, 'files': [], 'analysis_summary': 'Athens after the verdict.',
        'ontology': {
            'entity_types': [
                {'name': 'Philosopher', 'description': 'A lover of wisdom who questions what others take for granted.'},
                {'name': 'Citizen', 'description': 'A free man of Athens who may speak and vote in the assembly.'},
            ],
            'edge_types': [{'name': 'PERSUADES', 'description': 'One speaker moves another to change his mind.'}],
        },
    })

    # The crowd: a note left at startup in Chinese, a Chinese stance turn and country.
    _write_json(world.simulation('state.json'), {
        'simulation_id': SIMULATION, 'project_id': PROJECT, 'graph_id': GRAPH, 'status': 'stopped',
        'entity_types': ['Philosopher'], 'config_reasoning': 'Thirty days in Athens.', 'error': ZH_NOTE,
    })
    _write_json(world.simulation('run_state.json'), {
        'simulation_id': SIMULATION, 'runner_status': 'stopped', 'current_round': 136, 'total_rounds': 336,
        'error': ZH_NOTE, 'process_pid': 52863,
        'recent_actions': [{
            'round_num': 3, 'platform': 'twitter', 'agent_id': 1, 'agent_name': 'Crito',
            'action_type': 'CREATE_POST', 'action_args': {'content': CITIZEN_POST},
        }],
    })
    _write_json(world.simulation('stances.json'), {
        'status': 'completed', 'error': None, 'citizens': [
            {'agent_id': 0, 'name': 'Sand', 'stance': 'observer', 'final_stance': 'supportive', 'turn': TURN},
            {'agent_id': 1, 'name': 'Crito', 'stance': 'opposing', 'turn': 'Crito never moved.'},
        ],
    })
    _write_json(world.simulation('reddit_profiles.json'), [
        {'user_id': 0, 'username': 'socrates_468', 'name': 'Socrates', 'bio': 'A gadfly.', 'persona': PERSONAS[0],
         'country': '希腊'},
        {'user_id': 1, 'username': 'crito_1', 'name': 'Crito', 'bio': 'A friend.', 'persona': PERSONAS[1],
         'country': '希腊'},
        {'user_id': 2, 'username': 'plato_2', 'name': 'Plato', 'bio': 'A student.', 'persona': PERSONAS[2],
         'country': 'Greece'},
    ])
    buffer = io.StringIO()
    csv.writer(buffer).writerows([
        ['user_id', 'name', 'username', 'user_char', 'description'],
        ['0', 'Socrates', 'socrates_468', 'A gadfly, he says, "know yourself".', 'A gadfly.'],
        ['1', 'Crito', 'crito_1', 'A friend.', BIO],
    ])
    _write_text(world.simulation('twitter_profiles.csv'), buffer.getvalue())

    # The Chronicle: the quotes in every copy, the chapter title in Chinese.
    outline = {
        'title': 'The Hemlock Horizon',
        'summary': 'Athens in the thirty days.',
        'sections': [{'title': 'Polarization', 'content': CHAPTER_ONE}, {'title': TITLE, 'content': CHAPTER_TWO}],
    }
    markdown = f'# The Hemlock Horizon\n\n## Polarization\n\n{CHAPTER_ONE}\n\n## {TITLE}\n\n{CHAPTER_TWO}\n'
    _write_json(world.report('meta.json'), {
        'report_id': REPORT, 'simulation_id': SIMULATION, 'graph_id': GRAPH,
        'simulation_requirement': REQUIREMENT, 'status': 'completed', 'outline': outline,
        'markdown_content': markdown, 'created_at': '2026-09-25T14:38:49', 'completed_at': '2026-09-25T14:43:49',
        'error': None,
    })
    _write_json(world.report('outline.json'), outline)
    _write_json(world.report('progress.json'), {
        'status': 'completed', 'progress': 100, 'message': 'Report generation complete',
        'completed_sections': ['Polarization', TITLE],
    })
    _write_text(world.report('full_report.md'), markdown)
    _write_text(world.report('section_01.md'), f'## Polarization\n\n{CHAPTER_ONE}\n\n')
    _write_text(world.report('section_02.md'), f'## {TITLE}\n\n{CHAPTER_TWO}\n\n')
    _write_text(world.report('console_log.txt'), (
        '[14:40:01] INFO: Section 2 generation complete\n'
        f'[14:40:02] WARNING: Interview API call failed (env not running?): {ZH_ENV_NOTE}\n'
    ))
    _write_text(world.report('agent_log.jsonl'), _agent_log([
        {'action': 'report_start', 'section_title': None, 'section_index': None,
         'details': {'simulation_requirement': REQUIREMENT, 'message': 'Report generation started'}},
        {'action': 'planning_complete', 'section_title': None, 'section_index': None,
         'details': {'outline': {'title': outline['title'], 'summary': outline['summary'],
                                 'sections': [{'title': 'Polarization'}, {'title': TITLE}]},
                     'message': 'Outline ready'}},
        {'action': 'tool_call', 'section_title': TITLE, 'section_index': 2,
         'details': {'tool_name': 'interview_agents', 'parameters': {'interview_topic': 'Crito and the escape'},
                     'iteration': 1, 'message': 'Calling interview_agents'}},
        {'action': 'tool_result', 'section_title': TITLE, 'section_index': 2,
         'details': {'tool_name': 'interview_agents', 'result': TOOL_RESULT, 'result_length': len(TOOL_RESULT),
                     'iteration': 1, 'message': 'interview_agents returned'}},
        {'action': 'llm_response', 'section_title': TITLE, 'section_index': 2,
         'details': {'response': f'Final Answer: {CHAPTER_TWO}', 'response_length': 0, 'message': 'LLM answered'}},
        {'action': 'section_content', 'section_title': TITLE, 'section_index': 2,
         'details': {'content': CHAPTER_TWO, 'content_length': len(CHAPTER_TWO), 'message': 'Section written'}},
        {'action': 'section_complete', 'section_title': TITLE, 'section_index': 2,
         'details': {'content': CHAPTER_TWO, 'content_length': len(CHAPTER_TWO), 'message': 'Section complete'}},
        {'action': 'report_complete', 'section_title': None, 'section_index': None,
         'details': {'message': 'Report generation complete'}},
    ]))
    _write_json(world.report('film/film.json'), {
        'status': 'completed', 'title': 'Before the Hemlock', 'shots': [{'index': 1, 'narration': NARRATION}],
    })


def _build_chinese_gathering(world):
    _write_json(os.path.join(world.projects, ZH_PROJECT, 'project.json'), {
        'project_id': ZH_PROJECT, 'name': '毒芹', 'status': 'graph_completed', 'graph_id': 'mirofish_chinese0001',
        'simulation_requirement': '陪审团判处苏格拉底死刑，雅典会怎样？', 'files': [], 'language': 'zh',
        'created_at': '2026-09-25T14:00:00', 'updated_at': '2026-09-25T14:00:00',
    })
    _write_json(world.simulation('state.json', ZH_SIMULATION), {
        'simulation_id': ZH_SIMULATION, 'project_id': ZH_PROJECT, 'graph_id': 'mirofish_chinese0001',
        'status': 'stopped', 'error': ZH_NOTE,
    })
    _write_json(world.simulation('reddit_profiles.json', ZH_SIMULATION), [
        {'user_id': 0, 'username': 'socrates_1', 'name': '苏格拉底', 'bio': '雅典的哲学家。', 'country': '希腊'},
    ])
    _write_json(world.report('meta.json', ZH_REPORT), {
        'report_id': ZH_REPORT, 'simulation_id': ZH_SIMULATION, 'graph_id': 'mirofish_chinese0001',
        'simulation_requirement': '陪审团判处苏格拉底死刑，雅典会怎样？', 'status': 'completed',
        'outline': {'title': '毒芹', 'summary': '三十天。', 'sections': [{'title': TITLE, 'content': f'> {QUOTE_A}'}]},
        'markdown_content': f'# 毒芹\n\n> {QUOTE_A}\n',
    })
    _write_text(world.report('full_report.md', ZH_REPORT), f'# 毒芹\n\n> {QUOTE_A}\n')


def _build_memory(world):
    """The Hemlock Web as the rules wrote it in Chinese, an LLM fact in Chinese and the scroll."""

    store = MemoryStore(world.db)
    try:
        with store.write() as conn:
            conn.execute(
                'INSERT INTO graphs(graph_id, uuid, name, created_at) VALUES (?, ?, ?, ?)',
                (GRAPH, new_id(), GRAPH, utcnow_iso()),
            )
        post = AgentActivity(
            platform='twitter', agent_id=10, agent_name='Priests of Athena', action_type='CREATE_POST',
            action_args={'content': POST}, round_num=0, timestamp='2026-09-25T14:04:36.896458',
        ).to_episode_text('zh')
        second = AgentActivity(
            platform='twitter', agent_id=1, agent_name='Crito', action_type='CREATE_POST',
            action_args={'content': 'First line.\nSecond line.'}, round_num=1,
            timestamp='2026-09-25T15:04:36.896458',
        ).to_episode_text('zh')
        episode = new_id()
        with store.write() as conn:
            conn.execute(
                "INSERT INTO episodes(uuid, graph_id, kind, content, source, source_description, metadata_json, "
                "simulation_id, reference_time, reference_time_explicit, created_at, extraction_status) "
                "VALUES (?, ?, 'activity', ?, 'text', 'MiroFish simulation activity batch', ?, ?, ?, 1, ?, 'pending')",
                (episode, GRAPH, f'{post}\n{second}', json.dumps({'source': 'mirofish_simulation'}),
                 SIMULATION, '2026-09-25T14:04:36Z', utcnow_iso()),
            )
            ingest_activity_episode(conn, episode, mode='rules')
            nodes = {row[0]: row[1] for row in conn.execute(
                'SELECT name, uuid FROM nodes WHERE graph_id = ?', (GRAPH,))}
            for name, fact in (('REFUSED', LLM_FACT), ('OFFERED', ENGLISH_FACT)):
                conn.execute(
                    'INSERT INTO edges(uuid, graph_id, name, fact, fact_key, source_node_uuid, target_node_uuid, '
                    "origin, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'llm', ?)",
                    (new_id(), GRAPH, name, fact, name_key(fact), nodes['Crito'], nodes['Priests of Athena'],
                     utcnow_iso()),
                )
            conn.execute(
                "INSERT INTO episodes(uuid, graph_id, kind, content, source, source_description, metadata_json, "
                "reference_time, created_at, extraction_status) "
                "VALUES (?, ?, 'document', ?, 'text', 'the scroll', '{}', ?, ?, 'succeeded')",
                (new_id(), GRAPH, SCROLL, '2026-09-25T14:00:00Z', utcnow_iso()),
            )
    finally:
        store.close()


@pytest.fixture
def world(tmp_path, monkeypatch):
    uploads = tmp_path / 'uploads'
    for folder in ('projects', 'simulations', 'reports', 'memory'):
        (uploads / folder).mkdir(parents=True)
    monkeypatch.setattr(Config, 'UPLOAD_FOLDER', str(uploads))
    monkeypatch.setattr(ProjectManager, 'PROJECTS_DIR', str(uploads / 'projects'))
    monkeypatch.setattr(ReportManager, 'REPORTS_DIR', str(uploads / 'reports'))
    monkeypatch.setattr(SimulationManager, 'SIMULATION_DATA_DIR', str(uploads / 'simulations'))
    monkeypatch.setattr(SimulationRunner, 'RUN_STATE_DIR', str(uploads / 'simulations'))
    monkeypatch.setattr(Config, 'LOCAL_MEMORY_DB_PATH', str(uploads / 'memory' / 'local_memory.sqlite3'))
    monkeypatch.delenv('PARTHENON_RECORD_LANGUAGE', raising=False)
    monkeypatch.setattr(language_guard, 'default_translator', _no_model)
    language_guard.clear_cache()
    built = World(uploads)
    _build_english_gathering(built)
    _build_chinese_gathering(built)
    _build_memory(built)
    yield built
    language_guard.clear_cache()


def _entry(summary, record):
    return next(entry for entry in summary['records'] if entry['record'] == record)


def _reasons(entry):
    return {item['reason']: item['count'] for item in entry['left']}


# ------------------------------------------------------------------ scan: no model, no writes

def test_scan_finds_the_wrong_language_without_the_model_or_a_write(world):
    before = world.snapshot()

    summary = language_mend.scan('all')

    assert world.snapshot() == before
    report = _entry(summary, f'report:{REPORT}')
    assert report['language'] == 'en'
    assert report['to_mend'] > 0 and report['for_model'] > 0
    assert f'reports/{REPORT}/agent_log.jsonl' in report['files']
    reasons = _reasons(report)
    assert reasons[language_mend.TOOL_RESULT] == 1
    assert reasons[language_mend.FILM] == 1
    crowd = _entry(summary, f'simulation:{SIMULATION}')
    # The two startup notes are written again from their key: no model.
    assert crowd['by_rules'] == 2
    assert _reasons(crowd)[language_mend.POSTS] == 1
    graph = _entry(summary, f'graph:{GRAPH}')
    assert graph['by_rules'] >= 4  # the rules fact, two summaries and the activity episode
    assert _reasons(graph)[language_mend.SCROLL] == 1
    assert _entry(summary, f'report:{ZH_REPORT}')['skipped'].startswith('written in Chinese')
    assert not os.path.exists(os.path.join(world.uploads, language_mend.BACKUP_DIR_NAME))


# ------------------------------------------------------------------ a dry run

def test_a_dry_run_translates_and_writes_nothing(world):
    before = world.snapshot()
    model = FakeTranslator()

    summary = language_mend.mend('all', apply=False, llm=model)

    assert world.snapshot() == before
    assert summary['apply'] is False and summary['files_written'] == [] and summary['backup_dir'] is None
    assert summary['llm_calls'] >= 1 and summary['changed'] > 0
    report = _entry(summary, f'report:{REPORT}')
    assert f'reports/{REPORT}/full_report.md' in report['files']
    pairs = {(item['before'], item['after']) for item in report['preview']}
    assert (f'> {QUOTE_A}', f'> {EN_QUOTE_A}') in pairs
    assert (f'> **Crito:** {QUOTE_B}', f'> **Crito:** {EN_QUOTE_B}') in pairs
    assert not os.path.exists(os.path.join(world.uploads, language_mend.BACKUP_DIR_NAME))

    # Applying afterwards costs no further call: the translations are kept.
    applied = language_mend.mend('all', apply=True, llm=FakeTranslator(fail=True))

    assert applied['llm_calls'] == 0
    assert applied['changed'] == summary['changed']


# ------------------------------------------------------------------ applying

def test_applying_mends_every_copy_the_same_way(world):
    model = FakeTranslator()
    tool_row = _read(world.report('agent_log.jsonl')).splitlines(keepends=True)[3]

    summary = language_mend.mend('all', apply=True, llm=model)

    assert set(model.sent) <= set(TRANSLATIONS), set(model.sent) - set(TRANSLATIONS)
    # Each distinct line went to the model once, however many copies held it.
    assert model.sent.count(QUOTE_A) == 1 and model.sent.count(TITLE) == 1

    chapter = f"Crito's plan failed.\n\n> {EN_QUOTE_A}\n\n> **Crito:** {EN_QUOTE_B}\n\n{TRANSLATIONS[MIXED]}"
    meta = _load(world.report('meta.json'))
    outline = _load(world.report('outline.json'))
    assert meta['outline']['sections'][1] == {'title': EN_TITLE, 'content': chapter}
    assert outline['sections'][1] == {'title': EN_TITLE, 'content': chapter}
    assert f'## {EN_TITLE}\n\n{chapter}' in meta['markdown_content']
    assert f'## {EN_TITLE}\n\n{chapter}' in _read(world.report('full_report.md'))
    assert _read(world.report('section_02.md')) == f'## {EN_TITLE}\n\n{chapter}\n\n'
    assert _load(world.report('progress.json'))['completed_sections'] == ['Polarization', EN_TITLE]
    # The console keeps its time and level; the note in it is written again from its key.
    assert _read(world.report('console_log.txt')) == (
        '[14:40:01] INFO: Section 2 generation complete\n'
        f'[14:40:02] WARNING: Interview API call failed (env not running?): {EN_ENV_NOTE}\n'
    )
    assert meta['simulation_requirement'] == REQUIREMENT

    lines = _read(world.report('agent_log.jsonl')).splitlines(keepends=True)
    rows = [json.loads(line) for line in lines]
    assert rows[1]['details']['outline']['sections'][1]['title'] == EN_TITLE
    for row in rows[4:7]:
        assert row['section_title'] == EN_TITLE
    assert rows[4]['details']['response'] == f'Final Answer: {chapter}'
    for row in rows[5:7]:
        assert row['details']['content'] == chapter
        assert row['details']['content_length'] == len(chapter)
    # The tool's raw result is the record of what the Scribe read: left, byte for byte.
    assert lines[3].replace(TITLE, EN_TITLE) == tool_row.replace(TITLE, EN_TITLE)
    assert rows[3]['details']['result'] == TOOL_RESULT
    assert _load(world.report('film/film.json'))['shots'][0]['narration'] == NARRATION

    # The crowd: the startup note written again from its key, the stance, the country, the profile.
    assert _load(world.simulation('state.json'))['error'] == EN_NOTE
    run = _load(world.simulation('run_state.json'))
    assert run['error'] == EN_NOTE
    assert run['recent_actions'][0]['action_args']['content'] == CITIZEN_POST
    assert _load(world.simulation('stances.json'))['citizens'][0]['turn'] == TRANSLATIONS[TURN]
    profiles = _load(world.simulation('reddit_profiles.json'))
    assert [p['country'] for p in profiles] == ['Greece', 'Greece', 'Greece']
    assert [p['name'] for p in profiles] == ['Socrates', 'Crito', 'Plato']
    rows = list(csv.reader(io.StringIO(_read(world.simulation('twitter_profiles.csv')), newline='')))
    assert rows[2] == ['1', 'Crito', 'crito_1', 'A friend.', TRANSLATIONS[BIO]]
    assert rows[1] == ['0', 'Socrates', 'socrates_468', 'A gadfly, he says, "know yourself".', 'A gadfly.']

    # Nothing an English reader looks at is left in Chinese.
    for name in ('meta.json', 'outline.json', 'progress.json', 'full_report.md', 'section_02.md'):
        assert not language_guard.foreign_script(_read(world.report(name)), 'en'), name
    for name in ('state.json', 'stances.json', 'reddit_profiles.json', 'twitter_profiles.csv'):
        assert not language_guard.foreign_script(_read(world.simulation(name)), 'en'), name

    backup = os.path.join(world.uploads, summary['backup_dir'])
    assert summary['backup_dir'].startswith(language_mend.BACKUP_DIR_NAME + '/')
    assert QUOTE_A in _read(os.path.join(backup, 'reports', REPORT, 'full_report.md'))
    assert _load(os.path.join(backup, 'simulations', SIMULATION, 'state.json'))['error'] == ZH_NOTE
    assert f'reports/{REPORT}/agent_log.jsonl' in summary['files_written']


def test_applying_mends_the_memory_graph_and_keeps_its_index(world):
    language_mend.mend(f'graph:{GRAPH}', apply=True, llm=FakeTranslator())

    facts = {row['name']: row for row in world.memory(
        'SELECT name, fact, fact_key FROM edges WHERE graph_id = ? ORDER BY id', GRAPH)}
    posted = world.memory("SELECT fact, fact_key FROM edges WHERE graph_id = ? AND name = 'POSTED' ORDER BY id", GRAPH)
    assert posted[0]['fact'] == f'On Twitter, Priests of Athena posted: “{POST}”'
    assert all(row['fact_key'] == name_key(row['fact']) for row in posted)
    assert facts['REFUSED']['fact'] == TRANSLATIONS[LLM_FACT]
    assert facts['REFUSED']['fact_key'] == name_key(TRANSLATIONS[LLM_FACT])
    summaries = {row['name']: row['summary'] for row in world.memory(
        'SELECT name, summary FROM nodes WHERE graph_id = ?', GRAPH)}
    assert summaries['Twitter'] == 'Twitter is the social media platform used in the simulation.'
    assert summaries['Priests of Athena'] == 'Priests of Athena is a simulated account on Twitter.'
    [activity] = world.memory("SELECT content FROM episodes WHERE graph_id = ? AND kind = 'activity'", GRAPH)
    assert activity['content'] == (
        f'[2026-09-25T14:04:36.896458] [twitter round 0] Priests of Athena: posted: “{POST}”\n'
        '[2026-09-25T15:04:36.896458] [twitter round 1] Crito: posted: “First line.\nSecond line.”'
    )
    [scroll] = world.memory("SELECT content FROM episodes WHERE graph_id = ? AND kind = 'document'", GRAPH)
    assert scroll['content'] == SCROLL
    assert world.memory('SELECT version FROM graphs WHERE graph_id = ?', GRAPH)[0]['version'] >= 1

    store = MemoryStore(world.db)
    try:
        assert store.fts_integrity_check() == []
        if store.caps.fts5:
            with store.read() as conn:
                found = conn.execute("SELECT rowid FROM episodes_fts WHERE episodes_fts MATCH 'posted'").fetchall()
                gone = conn.execute("SELECT rowid FROM episodes_fts WHERE episodes_fts MATCH '发布了一条帖子'").fetchall()
            assert len(found) == 1 and gone == []
    finally:
        store.close()

    backups = os.path.join(world.uploads, language_mend.BACKUP_DIR_NAME)
    [stamp] = os.listdir(backups)
    conn = sqlite3.connect(os.path.join(backups, stamp, 'memory', 'local_memory.sqlite3'))
    try:
        assert conn.execute("SELECT fact FROM edges WHERE name = 'REFUSED'").fetchone()[0] == LLM_FACT
    finally:
        conn.close()


def test_a_second_run_changes_nothing(world):
    language_mend.mend('all', apply=True, llm=FakeTranslator())
    after = world.snapshot()
    model = FakeTranslator()

    again = language_mend.mend('all', apply=True, llm=model)

    assert model.sent == [] and again['llm_calls'] == 0
    assert again['changed'] == 0 and again['files_written'] == [] and again['backup_dir'] is None
    snapshot = world.snapshot()
    assert {k: v for k, v in snapshot.items() if not k.startswith(language_mend.BACKUP_DIR_NAME)} == {
        k: v for k, v in after.items() if not k.startswith(language_mend.BACKUP_DIR_NAME)
    }
    assert language_mend.scan('all')['to_mend'] == 0


def test_a_chinese_gathering_is_never_touched(world):
    before = world.snapshot()

    summary = language_mend.mend('all', apply=True, llm=FakeTranslator())

    after = world.snapshot()
    for key, value in before.items():
        if ZH_REPORT in key or ZH_SIMULATION in key or ZH_PROJECT in key:
            assert after[key] == value, key
    for record in (f'report:{ZH_REPORT}', f'simulation:{ZH_SIMULATION}', f'project:{ZH_PROJECT}'):
        assert _entry(summary, record)['language'] == 'zh'
        assert 'skipped' in _entry(summary, record)


def test_the_configured_record_language_decides(world, monkeypatch):
    # The public steps write English: every gathering is mended to it.
    monkeypatch.setenv('PARTHENON_RECORD_LANGUAGE', 'en')

    summary = language_mend.scan(f'report:{ZH_REPORT}')

    assert _entry(summary, f'report:{ZH_REPORT}')['language'] == 'en'
    assert _entry(summary, f'report:{ZH_REPORT}')['to_mend'] > 0


def test_a_failed_translation_writes_nothing_of_that_record(world):
    before = world.snapshot()

    summary = language_mend.mend('all', apply=True, llm=FakeTranslator(fail=True))

    assert world.snapshot() == before
    assert summary['files_written'] == []
    report = _entry(summary, f'report:{REPORT}')
    assert report['changed'] == 0
    assert _reasons(report)[language_mend.UNTRANSLATED] > 0


def test_a_short_answer_counts_as_failed(world):
    class Short(FakeTranslator):
        def chat_json(self, messages, temperature=None, max_tokens=None):
            answer = super().chat_json(messages, temperature, max_tokens)
            return {'lines': answer['lines'][:-1]}

    before = world.snapshot()

    language_mend.mend(f'report:{REPORT}', apply=True, llm=Short())

    assert world.snapshot() == before


class Echo(FakeTranslator):
    """A model that hands every line back as it came: the guard would cut the Chinese out of it."""

    def chat_json(self, messages, temperature=None, max_tokens=None):
        lines = json.loads(messages[-1]['content'])['lines']
        self.sent.extend(lines)
        return {'lines': list(lines)}


class Halfway(FakeTranslator):
    """A model that leaves a word of Chinese in one quotation and translates the rest."""

    def chat_json(self, messages, temperature=None, max_tokens=None):
        answer = super().chat_json(messages, temperature, max_tokens)
        return {'lines': [
            '"Crito said: 「快走」 (he urged Socrates to flee)"' if line == TRANSLATIONS[QUOTE_A] else line
            for line in answer['lines']
        ]}


def test_a_model_that_echoes_the_chinese_writes_nothing(world):
    before = world.snapshot()

    summary = language_mend.mend('all', apply=True, llm=Echo())

    # Nothing is cut out of any record: the quotes, the title, the country all stay for the next run.
    assert world.snapshot() == before
    assert summary['files_written'] == [] and summary['changed'] == 0 and summary['backup_dir'] is None
    for record in (f'report:{REPORT}', f'simulation:{SIMULATION}', f'graph:{GRAPH}'):
        assert _reasons(_entry(summary, record))[language_mend.UNTRANSLATED] > 0, record


def test_a_model_that_leaves_a_word_of_chinese_writes_nothing_of_that_record(world):
    summary = language_mend.mend('all', apply=True, llm=Halfway())

    report = _entry(summary, f'report:{REPORT}')
    assert report['changed'] == 0 and report['files'] == []
    assert _reasons(report)[language_mend.UNTRANSLATED] > 0
    for name in ('full_report.md', 'section_02.md', 'meta.json', 'outline.json', 'agent_log.jsonl'):
        assert f'> {QUOTE_A}' in _read(world.report(name)).replace('\\"', '"'), name
    assert not os.path.exists(os.path.join(world.uploads, language_mend.BACKUP_DIR_NAME, 'reports'))
    # The other records came back whole and are mended.
    assert _load(world.simulation('reddit_profiles.json'))[0]['country'] == 'Greece'


def test_a_text_the_guard_had_to_cut_writes_nothing(world, monkeypatch):
    def broken(*_args, **_kwargs):
        raise RuntimeError('a slip inside the guard')

    # The guard never raises: it cuts the foreign script out and says so. The mend hears it.
    monkeypatch.setattr(language_guard, '_ensure_many', broken)
    before = world.snapshot()

    summary = language_mend.mend(f'report:{REPORT}', apply=True, llm=FakeTranslator())

    assert world.snapshot() == before
    assert _reasons(_entry(summary, f'report:{REPORT}'))[language_mend.UNTRANSLATED] > 0


@pytest.mark.parametrize('whole', [False, True])
def test_a_text_the_guard_says_it_could_not_translate_writes_nothing(world, monkeypatch, whole):
    handed = []

    def quiet(texts, lang, llm, context, memo=None, untranslated=None):
        # No failed call, no warning: the guard's untranslated list is the only word that a text came back cut.
        handed.append(untranslated)
        if not whole:
            untranslated.append(0)
        return ['Plain English.' if language_guard.foreign_script(text, lang) else text for text in texts]

    monkeypatch.setattr(language_guard, '_ensure_many', quiet)
    before = world.snapshot()

    summary = language_mend.mend(f'report:{REPORT}', apply=True, llm=FakeTranslator())

    assert handed and all(isinstance(item, list) for item in handed)
    entry = _entry(summary, f'report:{REPORT}')
    if whole:
        assert entry['changed'] > 0 and summary['files_written']
        return
    assert world.snapshot() == before
    assert entry['changed'] == 0 and summary['files_written'] == []
    assert _reasons(entry)[language_mend.UNTRANSLATED] > 0


def test_an_answer_that_splits_a_line_counts_as_failed(world):
    class Split(FakeTranslator):
        def chat_json(self, messages, temperature=None, max_tokens=None):
            answer = super().chat_json(messages, temperature, max_tokens)
            return {'lines': [line.replace(', ', ',\n', 1) for line in answer['lines']]}

    before = world.snapshot()

    language_mend.mend(f'report:{REPORT}', apply=True, llm=Split())

    assert world.snapshot() == before


class Meanwhile(FakeTranslator):
    """The model, while something else in the app writes to the record (once)."""

    def __init__(self, happen):
        super().__init__()
        self.happen = happen

    def chat_json(self, messages, temperature=None, max_tokens=None):
        if self.happen is not None:
            self.happen()
            self.happen = None
        return super().chat_json(messages, temperature, max_tokens)


def _project_path():
    return os.path.join(Config.UPLOAD_FOLDER, 'projects', PROJECT, 'project.json')


def test_a_project_written_while_the_model_works_is_not_overwritten(world):
    project = _load(_project_path())
    _write_json(_project_path(), {**project, 'status': 'ontology_generated', 'graph_id': None, 'analysis_summary': BIO})

    def build_finishes():
        built = _load(_project_path())
        _write_json(_project_path(), {**built, 'status': 'graph_completed', 'graph_id': 'mirofish_new'})

    summary = language_mend.mend(f'project:{PROJECT}', apply=True, llm=Meanwhile(build_finishes))

    after = _load(_project_path())
    assert (after['status'], after['graph_id'], after['analysis_summary']) == ('graph_completed', 'mirofish_new', BIO)
    entry = _entry(summary, f'project:{PROJECT}')
    assert entry['changed'] == 0
    assert _reasons(entry)[language_mend.MOVED] == 1
    assert f'projects/{PROJECT}/project.json' not in summary['files_written']

    # The next run finds it settled and mends it, keeping the finished build.
    language_mend.mend(f'project:{PROJECT}', apply=True, llm=FakeTranslator())

    after = _load(_project_path())
    assert (after['status'], after['graph_id'], after['analysis_summary']) == (
        'graph_completed', 'mirofish_new', TRANSLATIONS[BIO],
    )


def test_a_project_still_building_is_left_for_later(world):
    project = _load(_project_path())
    _write_json(_project_path(), {**project, 'status': 'graph_building', 'analysis_summary': BIO})
    before = world.snapshot()

    summary = language_mend.mend(f'project:{PROJECT}', apply=False, llm=FakeTranslator())

    assert _entry(summary, f'project:{PROJECT}')['skipped'].startswith('its scroll is still being read')
    assert world.snapshot() == before


def test_a_run_that_begins_while_the_model_works_is_not_overwritten(world):
    os.remove(world.simulation('run_state.json'))

    def run_begins():
        state = _load(world.simulation('state.json'))
        _write_json(world.simulation('state.json'), {**state, 'status': 'running'})
        _write_json(world.simulation('run_state.json'), {'simulation_id': SIMULATION, 'runner_status': 'starting'})

    summary = language_mend.mend(f'simulation:{SIMULATION}', apply=True, llm=Meanwhile(run_begins))

    state = _load(world.simulation('state.json'))
    assert state['status'] == 'running' and state['error'] == ZH_NOTE
    assert _load(world.simulation('run_state.json')) == {'simulation_id': SIMULATION, 'runner_status': 'starting'}
    assert _load(world.simulation('stances.json'))['citizens'][0]['turn'] == TURN
    entry = _entry(summary, f'simulation:{SIMULATION}')
    assert entry['changed'] == 0 and summary['files_written'] == []
    moved = next(item for item in entry['left'] if item['reason'] == language_mend.MOVED)
    assert set(moved['where']) == {f'simulations/{SIMULATION}/state.json', f'simulations/{SIMULATION}/run_state.json'}


def test_a_run_held_in_memory_is_never_dropped(world):
    from app.services.simulation_runner import RunnerStatus, SimulationRunState

    live = SimulationRunState(simulation_id=SIMULATION, runner_status=RunnerStatus.RUNNING)

    def run_begins():
        SimulationRunner._run_states[SIMULATION] = live

    try:
        summary = language_mend.mend(f'simulation:{SIMULATION}', apply=True, llm=Meanwhile(run_begins))

        assert SimulationRunner._run_states.get(SIMULATION) is live
        assert _load(world.simulation('state.json'))['error'] == ZH_NOTE
        assert _reasons(_entry(summary, f'simulation:{SIMULATION}'))[language_mend.MOVED] == 1

        # While it runs, the crowd is left alone from the start.
        again = language_mend.scan(f'simulation:{SIMULATION}')
        assert _entry(again, f'simulation:{SIMULATION}')['skipped'] == 'the crowd is still at work'
    finally:
        SimulationRunner._run_states.pop(SIMULATION, None)


def test_a_log_row_holding_a_line_separator_is_mended_whole(world):
    row = {'action': 'section_content', 'section_title': TITLE, 'section_index': 2,
           'details': {'content': CHAPTER_TWO, 'message': 'Section written\u0085here'}}
    with open(world.report('agent_log.jsonl'), 'a', encoding='utf-8', newline='') as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + '\n')
        handle.write('not a row: 克里托\n')

    summary = language_mend.mend(f'report:{REPORT}', apply=True, llm=FakeTranslator())

    lines = _read(world.report('agent_log.jsonl')).split('\n')
    assert lines[-1] == '' and lines[-2] == 'not a row: 克里托'
    mended = json.loads(lines[-3])
    assert mended['section_title'] == EN_TITLE
    assert mended['details']['message'] == 'Section written\u0085here'
    assert not language_guard.foreign_script(mended['details']['content'], 'en')
    left = next(item for item in _entry(summary, f'report:{REPORT}')['left']
                if item['reason'] == language_mend.UNREADABLE_ROW)
    assert left['where'] == [f'reports/{REPORT}/agent_log.jsonl:{len(lines) - 1}']


def test_a_record_scope_mends_that_record_alone(world):
    summary = language_mend.mend(f'report:{REPORT}', apply=True, llm=FakeTranslator())

    assert [entry['record'] for entry in summary['records']] == [f'report:{REPORT}']
    assert all(path.startswith(f'reports/{REPORT}/') for path in summary['files_written'])
    assert _load(world.simulation('state.json'))['error'] == ZH_NOTE


def test_a_project_scope_is_the_whole_gathering(world):
    summary = language_mend.scan(f'project:{PROJECT}')

    assert [entry['record'] for entry in summary['records']] == [
        f'project:{PROJECT}', f'simulation:{SIMULATION}', f'report:{REPORT}', f'graph:{GRAPH}',
    ]


@pytest.mark.parametrize('scope', ['everything', 'report:', 'report:../etc', 'simulation:proj_x', 'graph:a/b'])
def test_a_scope_that_names_no_record_is_refused(world, scope):
    with pytest.raises(language_mend.ScopeError):
        language_mend.scan(scope)


def test_a_run_state_in_memory_reads_the_mended_note(world):
    SimulationRunner._run_states.pop(SIMULATION, None)
    assert SimulationRunner.get_run_state(SIMULATION).error == ZH_NOTE

    language_mend.mend(f'simulation:{SIMULATION}', apply=True, llm=FakeTranslator())

    assert SimulationRunner.get_run_state(SIMULATION).error == EN_NOTE
    SimulationRunner._run_states.pop(SIMULATION, None)


def test_a_busy_crowd_or_chronicle_is_left_for_later(world):
    state = _load(world.simulation('state.json'))
    _write_json(world.simulation('state.json'), {**state, 'status': 'running'})
    meta = _load(world.report('meta.json'))
    _write_json(world.report('meta.json'), {**meta, 'status': 'generating'})

    summary = language_mend.scan('all')

    assert _entry(summary, f'simulation:{SIMULATION}')['skipped'] == 'the crowd is still at work'
    assert _entry(summary, f'report:{REPORT}')['skipped'] == 'the Scribe is still writing it'


# ------------------------------------------------------------------ a language only guessed

EN_CHAPTER = TRANSLATIONS[ZH_CHAPTER]


def _chinese_chronicle(world):
    """A Chronicle of the English gathering written wholly in Chinese: its question reads English."""

    chapter = f'{ZH_CHAPTER}\n\n> {QUOTE_A}'
    markdown = f'# {ZH_CHRONICLE_TITLE}\n\n## {TITLE}\n\n{chapter}\n'
    outline = {'title': ZH_CHRONICLE_TITLE, 'summary': ZH_CHAPTER, 'sections': [{'title': TITLE, 'content': chapter}]}
    _write_json(world.report('meta.json', MANDARIN), {
        'report_id': MANDARIN, 'simulation_id': SIMULATION, 'graph_id': GRAPH, 'simulation_requirement': REQUIREMENT,
        'status': 'completed', 'outline': outline, 'markdown_content': markdown, 'error': None,
    })
    _write_json(world.report('outline.json', MANDARIN), outline)
    _write_text(world.report('full_report.md', MANDARIN), markdown)


def _files_of(snapshot, record_id):
    return {key: value for key, value in snapshot.items() if record_id in key}


def test_a_guessed_english_record_that_reads_chinese_is_left_uncertain(world):
    _chinese_chronicle(world)
    before = world.snapshot()

    scanned = language_mend.scan('all')

    entry = _entry(scanned, f'report:{MANDARIN}')
    assert (entry['language'], entry['language_source'], entry['uncertain']) == ('en', 'guessed', True)
    assert entry['to_mend'] == 0 and entry['for_model'] == 0 and entry['files'] == []
    assert _reasons(entry)[language_mend.LANGUAGE_UNCERTAIN] == entry['found'] > 0
    assert scanned['uncertain'] == [f'report:{MANDARIN}']
    # The Hemlock Chronicle reads English, Chinese quotes and all: its guess stands.
    assert 'uncertain' not in _entry(scanned, f'report:{REPORT}')

    model = FakeTranslator()
    summary = language_mend.mend('all', apply=True, llm=model)

    entry = _entry(summary, f'report:{MANDARIN}')
    assert entry['uncertain'] is True and entry['changed'] == 0 and entry['files'] == [] and entry['llm_calls'] == 0
    assert _reasons(entry)[language_mend.LANGUAGE_UNCERTAIN] > 0
    assert ZH_CHAPTER not in model.sent and ZH_CHRONICLE_TITLE not in model.sent
    assert _files_of(world.snapshot(), MANDARIN) == _files_of(before, MANDARIN)
    assert summary['uncertain'] == [f'report:{MANDARIN}']
    # The rest of the gathering is mended as before.
    assert _load(world.report('meta.json'))['outline']['sections'][1]['title'] == EN_TITLE


def test_only_a_request_that_names_it_with_lang_decides(world):
    _chinese_chronicle(world)
    before = _files_of(world.snapshot(), MANDARIN)

    # 'all' names no record, and naming it without lang decides nothing.
    for scope, lang in (('all', 'en'), (f'report:{MANDARIN}', None), (f'simulation:{SIMULATION}', 'en')):
        summary = language_mend.mend(scope, apply=True, llm=FakeTranslator(), lang=lang)
        assert summary['lang'] == lang
        assert _files_of(world.snapshot(), MANDARIN) == before, (scope, lang)
    # The whole gathering, named with lang, names it too.
    gathering = _entry(language_mend.scan(f'project:{PROJECT}', lang='en'), f'report:{MANDARIN}')
    assert gathering['language_source'] == 'explicit' and gathering['to_mend'] > 0

    model = FakeTranslator()
    summary = language_mend.mend(f'report:{MANDARIN}', apply=True, llm=model, lang='en')

    entry = _entry(summary, f'report:{MANDARIN}')
    assert entry['language'] == 'en' and entry['language_source'] == 'explicit' and 'uncertain' not in entry
    assert entry['changed'] > 0 and summary['uncertain'] == []
    assert set(model.sent) <= set(TRANSLATIONS), set(model.sent) - set(TRANSLATIONS)
    assert _read(world.report('full_report.md', MANDARIN)) == (
        f'# {TRANSLATIONS[ZH_CHRONICLE_TITLE]}\n\n## {EN_TITLE}\n\n{EN_CHAPTER}\n\n> {EN_QUOTE_A}\n'
    )
    meta = _load(world.report('meta.json', MANDARIN))
    assert meta['outline']['summary'] == EN_CHAPTER
    assert meta['simulation_requirement'] == REQUIREMENT
    for name in ('meta.json', 'outline.json', 'full_report.md'):
        assert not language_guard.foreign_script(_read(world.report(name, MANDARIN)), 'en'), name
    assert language_mend.scan('all')['uncertain'] == []


def test_a_record_with_no_question_that_reads_chinese_is_uncertain(world):
    _write_json(os.path.join(world.projects, 'proj_nameless0001', 'project.json'), {
        'project_id': 'proj_nameless0001', 'name': 'Nameless', 'status': 'graph_completed', 'files': [],
        'analysis_summary': '雅典的陪审团判处苏格拉底死刑，城邦在三十天里争论不休。',
        'created_at': '2026-09-25T14:00:00', 'updated_at': '2026-09-25T14:00:00',
    })

    entry = _entry(language_mend.scan('all'), 'project:proj_nameless0001')

    assert (entry['language'], entry['language_source'], entry['uncertain']) == ('en', 'default', True)
    assert entry['to_mend'] == 0


def test_a_web_whose_own_facts_read_chinese_is_uncertain_until_named(world):
    conn = sqlite3.connect(world.db)
    try:
        conn.execute("DELETE FROM edges WHERE name = 'OFFERED'")
        conn.commit()
    finally:
        conn.close()

    summary = language_mend.mend('all', apply=True, llm=FakeTranslator())

    graph = _entry(summary, f'graph:{GRAPH}')
    assert graph['uncertain'] is True and graph['changed'] == 0 and summary['uncertain'] == [f'graph:{GRAPH}']
    # The rules' templates wait with the rest: the whole Web is mended in one language or not at all.
    assert world.memory("SELECT fact FROM edges WHERE name = 'REFUSED'")[0]['fact'] == LLM_FACT
    assert any(language_guard.foreign_script(row['summary'], 'en') for row in world.memory(
        'SELECT summary FROM nodes WHERE graph_id = ?', GRAPH))

    decided = language_mend.mend(f'graph:{GRAPH}', apply=True, llm=FakeTranslator(), lang='en')

    assert _entry(decided, f'graph:{GRAPH}')['changed'] > 0
    assert world.memory("SELECT fact FROM edges WHERE name = 'REFUSED'")[0]['fact'] == TRANSLATIONS[LLM_FACT]


def test_a_kept_language_is_never_doubted(world):
    # The gathering keeps English: its Chinese Chronicle is mended with no word from the request.
    _chinese_chronicle(world)
    project = _load(_project_path())
    _write_json(_project_path(), {**project, 'language': 'en'})

    summary = language_mend.mend('all', apply=True, llm=FakeTranslator())

    entry = _entry(summary, f'report:{MANDARIN}')
    assert entry['language_source'] == 'stored' and 'uncertain' not in entry and entry['changed'] > 0
    assert not language_guard.foreign_script(_read(world.report('full_report.md', MANDARIN)), 'en')


def test_lang_never_changes_a_kept_language(world, monkeypatch):
    before = world.snapshot()

    kept = _entry(language_mend.mend(f'report:{ZH_REPORT}', apply=True, llm=FakeTranslator(), lang='en'),
                  f'report:{ZH_REPORT}')
    chinese = _entry(language_mend.mend(f'report:{REPORT}', apply=True, llm=FakeTranslator(), lang='zh'),
                     f'report:{REPORT}')
    monkeypatch.setenv('PARTHENON_RECORD_LANGUAGE', 'en')
    site = _entry(language_mend.scan(f'report:{REPORT}', lang='zh'), f'report:{REPORT}')

    assert (kept['language'], kept['language_source']) == ('zh', 'stored')
    assert kept['skipped'] == "its gathering keeps its language ('zh'): lang never changes it"
    # A record's own scope never turns a guess the other way: the rest of its gathering would still read it.
    assert (chinese['language'], chinese['language_source']) == ('en', 'guessed')
    assert chinese['skipped'] == language_mend.GUESS_KEPT.format(language='en', lang='zh')
    assert (site['language'], site['language_source']) == ('en', 'configured')
    assert site['skipped'] == "PARTHENON_RECORD_LANGUAGE sets its language ('en'): lang never changes it"
    assert world.snapshot() == before


ZH_REQUIREMENT = '陪审团判处苏格拉底死刑，雅典会怎样？'


def _forget_language(world, project_id=ZH_PROJECT):
    """A gathering older than the stored language: its language is only guessed from its question."""

    path = os.path.join(world.projects, project_id, 'project.json')
    project = _load(path)
    project.pop('language', None)
    _write_json(path, project)
    return path


def test_a_record_scope_never_turns_a_guess_the_other_way(world):
    _forget_language(world)
    assert language_guard.record_language_source(report_id=ZH_REPORT) == ('zh', 'guessed')
    before = world.snapshot()
    model = FakeTranslator()

    summary = language_mend.mend(f'report:{ZH_REPORT}', apply=True, llm=model, lang='en')

    entry = _entry(summary, f'report:{ZH_REPORT}')
    assert (entry['language'], entry['language_source']) == ('zh', 'guessed')
    assert entry['skipped'] == language_mend.GUESS_KEPT.format(language='zh', lang='en')
    assert model.sent == [] and summary['files_written'] == [] and world.snapshot() == before


def test_a_gathering_named_with_lang_keeps_it(world):
    # A Chinese question and no stored language: the whole gathering, named in English, becomes English on record.
    path = _forget_language(world)
    before = _read(path)

    dry = language_mend.mend(f'project:{ZH_PROJECT}', llm=FakeTranslator(), lang='en')

    project = _entry(dry, f'project:{ZH_PROJECT}')
    assert (project['language'], project['language_source'], project['keeps_language']) == ('en', 'explicit', 'en')
    assert project['files'] == [f'projects/{ZH_PROJECT}/project.json']
    assert dry['files_written'] == [] and _read(path) == before

    summary = language_mend.mend(f'project:{ZH_PROJECT}', apply=True, llm=FakeTranslator(), lang='en')

    assert _entry(summary, f'project:{ZH_PROJECT}')['files'] == [f'projects/{ZH_PROJECT}/project.json']
    assert _load(path)['language'] == 'en'
    backup = os.path.join(world.uploads, summary['backup_dir'], 'projects', ZH_PROJECT, 'project.json')
    assert _read(backup) == before
    for record in (dict(project_id=ZH_PROJECT), dict(simulation_id=ZH_SIMULATION), dict(report_id=ZH_REPORT)):
        assert language_guard.record_language_source(**record) == ('en', 'stored'), record
    # Its records follow; the visitor's question stays in their words.
    for record in (f'simulation:{ZH_SIMULATION}', f'report:{ZH_REPORT}'):
        assert _entry(summary, record)['changed'] > 0, record
    assert not language_guard.foreign_script(_read(world.report('full_report.md', ZH_REPORT)), 'en')
    assert _load(world.report('meta.json', ZH_REPORT))['simulation_requirement'] == ZH_REQUIREMENT
    # From now on every reader takes it as English: nothing guessed, nothing uncertain, nothing left to mend.
    again = language_mend.scan('all')
    assert again['uncertain'] == []
    for record in (f'project:{ZH_PROJECT}', f'simulation:{ZH_SIMULATION}', f'report:{ZH_REPORT}'):
        entry = _entry(again, record)
        assert (entry['language'], entry['language_source'], entry['to_mend']) == ('en', 'stored', 0), record


def test_a_gathering_decided_chinese_keeps_it_and_is_no_longer_uncertain(world):
    _chinese_chronicle(world)
    assert language_mend.scan('all')['uncertain'] == [f'report:{MANDARIN}']
    before = world.snapshot()
    model = FakeTranslator()

    summary = language_mend.mend(f'project:{PROJECT}', apply=True, llm=model, lang='zh')

    assert model.sent == [] and summary['files_written'] == [f'projects/{PROJECT}/project.json']
    assert _entry(summary, f'project:{PROJECT}')['keeps_language'] == 'zh'
    assert _load(_project_path())['language'] == 'zh'
    after = world.snapshot()
    changed = {key for key in after if after[key] != before.get(key)}
    assert {key for key in changed if not key.startswith(language_mend.BACKUP_DIR_NAME)} == {
        os.path.join('projects', PROJECT, 'project.json'),
    }
    assert language_guard.record_language_source(report_id=MANDARIN) == ('zh', 'stored')
    assert language_mend.scan('all')['uncertain'] == []


@pytest.mark.parametrize('way', ['busy', 'untranslated', 'moved'])
def test_nothing_of_a_gathering_is_written_unless_its_project_keeps_the_language(world, way):
    path = _forget_language(world)
    project = {**_load(path), 'analysis_summary': BIO}
    if way == 'busy':
        project['status'] = 'graph_building'
    _write_json(path, project)
    before = world.snapshot()

    def a_build_writes_it():
        _write_json(path, {**_load(path), 'updated_at': '2026-09-27T11:00:00'})

    model = {
        'busy': FakeTranslator(), 'untranslated': FakeTranslator(fail=True), 'moved': Meanwhile(a_build_writes_it),
    }[way]
    summary = language_mend.mend(f'project:{ZH_PROJECT}', apply=True, llm=model, lang='en')

    project = _entry(summary, f'project:{ZH_PROJECT}')
    if way == 'busy':
        assert project['skipped'] == 'its scroll is still being read or its Web built'
    else:
        assert (language_mend.UNTRANSLATED if way == 'untranslated' else language_mend.MOVED) in _reasons(project)
    undecided = language_mend.UNDECIDED.format(lang='en', project_id=ZH_PROJECT)
    for record in (f'simulation:{ZH_SIMULATION}', f'report:{ZH_REPORT}'):
        assert _entry(summary, record)['skipped'] == undecided, record
    assert set(model.sent) <= {BIO}  # the rest of the gathering never went to the model
    assert summary['files_written'] == [] and summary['backup_dir'] is None
    assert 'language' not in _load(path)
    for record_id in (ZH_SIMULATION, ZH_REPORT):
        assert _files_of(world.snapshot(), record_id) == _files_of(before, record_id), record_id
    assert language_guard.record_language_source(report_id=ZH_REPORT) == ('zh', 'guessed')


def test_a_decided_gathering_never_changes_a_web_it_shares_with_another_language(world):
    # The Hemlock gathering asked in Chinese, and a gathering that keeps Chinese shares its Web.
    _write_json(_project_path(), {**_load(_project_path()), 'simulation_requirement': ZH_REQUIREMENT})
    _write_json(os.path.join(world.projects, 'proj_sharing0001', 'project.json'), {
        'project_id': 'proj_sharing0001', 'name': 'Sharing', 'status': 'graph_completed', 'graph_id': GRAPH,
        'files': [], 'language': 'zh', 'created_at': '2026-09-25T14:00:00', 'updated_at': '2026-09-25T14:00:00',
    })
    assert language_guard.record_language_source(project_id=PROJECT) == ('zh', 'guessed')
    before = world.memory_rows()

    summary = language_mend.mend(f'project:{PROJECT}', apply=True, llm=FakeTranslator(), lang='en')

    assert _entry(summary, f'graph:{GRAPH}')['skipped'] == 'gatherings in different languages share this graph'
    assert world.memory_rows() == before
    assert _load(_project_path())['language'] == 'en'


@pytest.mark.parametrize('lang, expected', [
    (None, None), ('', None), ('  ', None), ('en', 'en'), ('EN-us', 'en'), ('zh_CN', 'zh'), ('zh-Hans', 'zh'),
])
def test_lang_is_english_or_chinese(lang, expected):
    assert language_mend.parse_lang(lang) == expected


@pytest.mark.parametrize('lang', ['fr', 'en,zh', 'zh;q=0.9', 1, True, ['en']])
def test_any_other_lang_is_refused(world, lang):
    with pytest.raises(language_mend.LanguageError):
        language_mend.scan(f'report:{REPORT}', lang=lang)
    with pytest.raises(language_mend.LanguageError):
        language_mend.mend(f'report:{REPORT}', lang=lang)


# ------------------------------------------------------------------ the pieces

def test_a_note_written_from_a_key_is_written_again_from_it():
    assert language_mend.known_note(ZH_NOTE, 'en') == EN_NOTE
    assert language_mend.known_note(f'Interview failed: {ZH_ENV_NOTE}', 'en') == f'Interview failed: {EN_ENV_NOTE}'
    assert language_mend.known_note('随便说一句话。', 'en') is None
    assert language_mend.known_note(EN_NOTE, 'en') is None


def test_an_activity_episode_changes_its_templates_only():
    content = (
        '[2026-09-25T14:04:36] [reddit round 2] Crito: 发布了一条帖子：「法律如父母。」\n'
        '[2026-09-25T14:05:36] [reddit round 2] Plato: posted: “Hello.”'
    )

    mended, still = language_mend.activity_text_in(content, 'en')

    assert mended == (
        '[2026-09-25T14:04:36] [reddit round 2] Crito: posted: “法律如父母。”\n'
        '[2026-09-25T14:05:36] [reddit round 2] Plato: posted: “Hello.”'
    )
    assert still == 1  # what the citizen wrote is theirs


# ------------------------------------------------------------------ the routes

def _app(monkeypatch, tmp_path, public):
    for name in list(os.environ):
        if name.startswith('PARTHENON_'):
            monkeypatch.delenv(name, raising=False)
    if public:
        monkeypatch.setenv('PARTHENON_PUBLIC', '1')
        monkeypatch.setenv('PARTHENON_DATA_DIR', str(tmp_path / 'data'))
        monkeypatch.setenv('PARTHENON_ADMIN_KEY', ADMIN_KEY)
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def test_the_routes_are_open_on_the_owners_machine(world, monkeypatch, tmp_path):
    client = _app(monkeypatch, tmp_path, public=False)
    model = FakeTranslator()
    monkeypatch.setattr(language_guard, 'default_translator', lambda: model)

    scan = client.get(f'/api/parthenon/mend/scan?scope=report:{REPORT}')
    dry = client.post('/api/parthenon/mend', json={'scope': f'report:{REPORT}'})
    bad = client.post('/api/parthenon/mend', json={'scope': 'nothing'})
    odd = client.post('/api/parthenon/mend', json={'scope': 'all', 'apply': 'yes'})

    assert scan.status_code == 200 and scan.json['data']['records'][0]['to_mend'] > 0
    assert dry.status_code == 200 and dry.json['data']['apply'] is False
    assert dry.json['data']['files_written'] == [] and model.sent
    assert QUOTE_A in _read(world.report('full_report.md'))
    assert bad.status_code == 400 and odd.status_code == 400


def test_the_routes_are_the_keepers_alone_on_the_public_steps(world, monkeypatch, tmp_path):
    client = _app(monkeypatch, tmp_path, public=True)

    scan = client.get('/api/parthenon/mend/scan?scope=all')
    mend = client.post('/api/parthenon/mend', json={'scope': 'all', 'apply': True})
    kept = client.get('/api/parthenon/mend/scan?scope=all', headers={'X-Parthenon-Admin': ADMIN_KEY})

    assert scan.status_code == 403 and scan.json['code'] == 'not_yours'
    assert mend.status_code == 403 and mend.json['code'] == 'not_yours'
    assert kept.status_code == 200 and kept.json['data']['found'] > 0
    assert QUOTE_A in _read(world.report('full_report.md'))


def test_the_routes_take_a_lang(world, monkeypatch, tmp_path):
    _chinese_chronicle(world)
    client = _app(monkeypatch, tmp_path, public=False)
    model = FakeTranslator()
    monkeypatch.setattr(language_guard, 'default_translator', lambda: model)
    before = _files_of(world.snapshot(), MANDARIN)

    doubted = client.get(f'/api/parthenon/mend/scan?scope=report:{MANDARIN}')
    decided = client.get(f'/api/parthenon/mend/scan?scope=report:{MANDARIN}&lang=en')
    dry = client.post('/api/parthenon/mend', json={'scope': f'report:{MANDARIN}', 'lang': 'en'})
    bad = client.get(f'/api/parthenon/mend/scan?scope=report:{MANDARIN}&lang=fr')
    odd = client.post('/api/parthenon/mend', json={'scope': f'report:{MANDARIN}', 'lang': 1})

    assert doubted.status_code == 200 and doubted.json['data']['uncertain'] == [f'report:{MANDARIN}']
    assert doubted.json['data']['to_mend'] == 0
    assert decided.status_code == 200 and decided.json['data']['uncertain'] == []
    assert decided.json['data']['lang'] == 'en' and decided.json['data']['to_mend'] > 0
    assert dry.status_code == 200 and dry.json['data']['changed'] > 0 and dry.json['data']['files_written'] == []
    assert ZH_CHAPTER in model.sent
    assert _files_of(world.snapshot(), MANDARIN) == before
    assert bad.status_code == 400 and odd.status_code == 400
    assert bad.json['error'] == odd.json['error'] == "lang is 'en' or 'zh'."
