"""Where a gathering stands, and its Chronicle in the city's words.

GET /api/parthenon/gathering/<id> resolves any of a gathering's ids to the act
it has reached. The Chronicle routes serve Chronicles written before the Scribe
learnt the city's words in them (parthenon.py _serve_in_city_words).
"""

import json
import os

import pytest

from app import create_app
from app.models.project import ProjectManager
from app.api import parthenon as parthenon_api
from app.services.report_agent import (
    Report, ReportManager, ReportOutline, ReportSection, ReportStatus,
)
from app.services.simulation_manager import SimulationManager
from app.services.simulation_runner import SimulationRunner


PROJECT_ID = 'proj_0123456789ab'
SIM_ID = 'sim_0123456789ab'
REPORT_ID = 'report_0123456789ab'


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(ProjectManager, 'PROJECTS_DIR', str(tmp_path / 'projects'))
    monkeypatch.setattr(ReportManager, 'REPORTS_DIR', str(tmp_path / 'reports'))
    monkeypatch.setattr(SimulationRunner, '_run_states', {})
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def _project(project_id=PROJECT_ID):
    folder = os.path.join(ProjectManager.PROJECTS_DIR, project_id)
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, 'project.json'), 'w', encoding='utf-8') as handle:
        json.dump({'project_id': project_id, 'name': 'Psammos', 'status': 'graph_completed',
                   'created_at': '2026-09-25T09:00:00', 'updated_at': '2026-09-25T09:00:00'}, handle)


def _simulation(sim_id=SIM_ID, project_id=PROJECT_ID, *, status='ready', created_at='2026-09-25T10:00:00'):
    folder = os.path.join(SimulationManager.SIMULATION_DATA_DIR, sim_id)
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, 'state.json'), 'w', encoding='utf-8') as handle:
        json.dump({'simulation_id': sim_id, 'project_id': project_id, 'graph_id': 'graph_test',
                   'status': status, 'profiles_generated': True, 'created_at': created_at}, handle)


def _run(sim_id=SIM_ID, runner_status='running', current_round=3):
    folder = os.path.join(SimulationRunner.RUN_STATE_DIR, sim_id)
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, 'run_state.json'), 'w', encoding='utf-8') as handle:
        json.dump({'simulation_id': sim_id, 'runner_status': runner_status,
                   'current_round': current_round, 'total_rounds': 12}, handle)


def _report(report_id=REPORT_ID, sim_id=SIM_ID, status=ReportStatus.COMPLETED,
            created_at='2026-09-25T12:00:00'):
    ReportManager.save_report(Report(
        report_id=report_id, simulation_id=sim_id, graph_id='graph_test',
        simulation_requirement='Should Psammos sign the Kiln Compact?', status=status,
        created_at=created_at,
    ))


def _resolve(client, gathering_id):
    response = client.get(f'/api/parthenon/gathering/{gathering_id}')
    assert response.status_code == 200, response.get_json()
    return response.get_json()['data']


def _expect(project_id=PROJECT_ID, simulation_id=SIM_ID, report_id=None, act=2,
            runner_status=None, report_status=None):
    return {'project_id': project_id, 'simulation_id': simulation_id, 'report_id': report_id,
            'act': act, 'runner_status': runner_status, 'report_status': report_status}


def test_a_project_without_a_simulation_is_at_the_hearing(client):
    _project()
    assert _resolve(client, PROJECT_ID) == _expect(simulation_id=None, act=1)


def test_a_prepared_simulation_that_never_ran_is_at_the_gathering(client):
    _project()
    _simulation()
    assert _resolve(client, PROJECT_ID) == _expect(act=2)
    assert _resolve(client, SIM_ID) == _expect(act=2)


def test_a_simulation_still_preparing_is_at_the_gathering(client):
    _simulation(status='preparing')
    assert _resolve(client, SIM_ID)['act'] == 2


def test_an_idle_run_state_is_not_a_run(client):
    _simulation()
    _run(runner_status='idle', current_round=0)
    assert _resolve(client, SIM_ID) == _expect(act=2, runner_status='idle')


def test_a_run_without_a_chronicle_is_in_the_agora(client):
    _project()
    _simulation()
    _run(runner_status='running')
    assert _resolve(client, PROJECT_ID) == _expect(act=3, runner_status='running')
    assert _resolve(client, SIM_ID) == _expect(act=3, runner_status='running')


def test_a_stopped_simulation_without_a_run_state_still_ran(client):
    _simulation(status='stopped')
    assert _resolve(client, SIM_ID)['act'] == 3


@pytest.mark.parametrize('status', [ReportStatus.PENDING, ReportStatus.PLANNING,
                                    ReportStatus.GENERATING, ReportStatus.COMPLETED])
def test_a_chronicle_puts_the_gathering_in_act_four(client, status):
    _project()
    _simulation()
    _run(runner_status='completed', current_round=12)
    _report(status=status)
    expected = _expect(report_id=REPORT_ID, act=4, runner_status='completed', report_status=status.value)
    assert _resolve(client, PROJECT_ID) == expected
    assert _resolve(client, SIM_ID) == expected
    assert _resolve(client, REPORT_ID) == expected


def test_a_failed_chronicle_sends_the_visitor_back_to_the_agora(client):
    _simulation()
    _run(runner_status='stopped')
    _report(status=ReportStatus.FAILED)
    assert _resolve(client, SIM_ID) == _expect(
        report_id=REPORT_ID, act=3, runner_status='stopped', report_status='failed'
    )


def test_the_newest_simulation_and_chronicle_are_chosen(client):
    _project()
    _simulation('sim_old', created_at='2026-09-20T10:00:00')
    _simulation('sim_new', created_at='2026-09-24T10:00:00')
    _simulation('sim_other', 'proj_elsewhere', created_at='2026-09-25T10:00:00')
    _report('report_first', 'sim_new', created_at='2026-09-24T12:00:00')
    _report('report_second', 'sim_new', status=ReportStatus.GENERATING, created_at='2026-09-24T18:00:00')
    _report('report_old', 'sim_old', created_at='2026-09-25T18:00:00')
    # A corrupt neighbour is skipped, not fatal.
    broken = os.path.join(SimulationManager.SIMULATION_DATA_DIR, 'sim_broken')
    os.makedirs(broken)
    with open(os.path.join(broken, 'state.json'), 'w', encoding='utf-8') as handle:
        handle.write('{not json')
    os.makedirs(os.path.join(ReportManager.REPORTS_DIR, 'report_broken'))
    with open(os.path.join(ReportManager.REPORTS_DIR, 'report_broken', 'meta.json'), 'w') as handle:
        handle.write('{not json')

    data = _resolve(client, PROJECT_ID)
    assert data == _expect(simulation_id='sim_new', report_id='report_second', act=4,
                           report_status='generating')
    # A report id resolves to that Chronicle, even when a newer one exists.
    assert _resolve(client, 'report_first') == _expect(
        simulation_id='sim_new', report_id='report_first', act=4, report_status='completed'
    )


def test_a_project_opens_the_night_that_got_furthest(client):
    """A later night prepared and then left never hides a written Chronicle."""

    _project()
    _simulation('sim_held', status='stopped', created_at='2026-09-25T10:00:00')
    _run('sim_held', runner_status='stopped', current_round=17)
    _report('report_held', 'sim_held', created_at='2026-09-25T12:00:00')
    _simulation('sim_left', status='ready', created_at='2026-09-25T23:00:00')
    assert _resolve(client, PROJECT_ID) == _expect(
        simulation_id='sim_held', report_id='report_held', act=4,
        runner_status='stopped', report_status='completed',
    )
    # Each night still resolves to itself by its own id.
    assert _resolve(client, 'sim_left') == _expect(simulation_id='sim_left', act=2)


def test_a_run_outranks_a_newer_gathering_and_newest_breaks_ties(client):
    _project()
    _simulation('sim_ran', status='running', created_at='2026-09-24T10:00:00')
    _run('sim_ran', runner_status='running', current_round=4)
    _simulation('sim_ready', status='ready', created_at='2026-09-25T10:00:00')
    assert _resolve(client, PROJECT_ID)['simulation_id'] == 'sim_ran'

    # Two nights in the Agora: the newer one. A failed Chronicle counts as none.
    _simulation('sim_ran_again', status='stopped', created_at='2026-09-25T11:00:00')
    _run('sim_ran_again', runner_status='stopped', current_round=2)
    _report('report_failed', 'sim_ran_again', status=ReportStatus.FAILED)
    data = _resolve(client, PROJECT_ID)
    assert (data['simulation_id'], data['act'], data['report_status']) == ('sim_ran_again', 3, 'failed')

    # Two nights at the Gathering: the newer one.
    _project('proj_twoready')
    _simulation('sim_first', 'proj_twoready', created_at='2026-09-20T10:00:00')
    _simulation('sim_second', 'proj_twoready', created_at='2026-09-21T10:00:00')
    assert _resolve(client, 'proj_twoready') == _expect(
        project_id='proj_twoready', simulation_id='sim_second', act=2
    )


def test_a_chronicle_whose_simulation_is_gone_still_resolves(client):
    _report(sim_id='sim_vanished')
    assert _resolve(client, REPORT_ID) == _expect(
        project_id=None, simulation_id='sim_vanished', report_id=REPORT_ID, act=4,
        report_status='completed',
    )


def test_unknown_ids_are_not_found(client):
    _project()
    _simulation()
    for gathering_id in ('proj_missing', 'sim_missing', 'report_missing', 'task_0123', 'sim_',
                         'SIM', 'sim_a.b', 'sim_%2E%2E'):
        response = client.get(f'/api/parthenon/gathering/{gathering_id}')
        assert response.status_code == 404, gathering_id
        assert response.get_json() == {'success': False, 'error': 'Gathering not found.'}
    assert client.get('/api/parthenon/gathering/..%2Fsim_0123456789ab').status_code == 404
    # Looking up an unknown simulation never creates its folder.
    assert not os.path.exists(os.path.join(SimulationManager.SIMULATION_DATA_DIR, 'sim_missing'))


# ── The Chronicle in the city's words ──

OLD_SUMMARY = "In the simulated month between Socrates' sentencing and the ship's return, Athens fractures."
CITY_SUMMARY = "In the month between Socrates' sentencing and the ship's return, Athens fractures."
OLD_CHAPTER = 'Crito on the simulated platforms'
OLD_WORDS = '@crito_7 pleaded on Twitter: "the simulated world is ours, #FreeSocrates".'


def _older_chronicle(status=ReportStatus.COMPLETED):
    """A Chronicle written before the Scribe learnt the city's words, and its gathering."""

    _simulation()
    folder = os.path.join(SimulationManager.SIMULATION_DATA_DIR, SIM_ID)
    with open(os.path.join(folder, 'reddit_profiles.json'), 'w', encoding='utf-8') as handle:
        json.dump([{'user_id': 7, 'username': 'crito_7', 'name': 'Crito'}], handle)
    with open(os.path.join(folder, 'simulation_config.json'), 'w', encoding='utf-8') as handle:
        json.dump({'time_config': {'minutes_per_round': 1440}}, handle)
    chapter = f'{OLD_WORDS}\n\nThe simulated city held its breath.'
    outline = ReportOutline(title='The Hemlock Horizon', summary=OLD_SUMMARY,
                            sections=[ReportSection(title=OLD_CHAPTER, content=chapter)])
    ReportManager.save_report(Report(
        report_id=REPORT_ID, simulation_id=SIM_ID, graph_id='graph_test',
        simulation_requirement='What happens in the month before the hemlock?', status=status,
        outline=outline, markdown_content=outline.to_markdown(), created_at='2026-09-25T12:00:00',
    ))
    ReportManager.save_section(REPORT_ID, 1, ReportSection(title=OLD_CHAPTER, content=chapter))
    log = [
        {'action': 'planning_complete', 'details': {'outline': outline.to_dict()}},
        {'action': 'section_content', 'section_title': OLD_CHAPTER, 'details': {'content': chapter}},
        {'action': 'tool_call', 'details': {'parameters': {'query': 'the simulated agents'}}},
    ]
    with open(os.path.join(ReportManager.REPORTS_DIR, REPORT_ID, 'agent_log.jsonl'), 'w',
              encoding='utf-8') as handle:
        handle.write('\n'.join(json.dumps(entry) for entry in log) + '\n')
    return os.path.join(ReportManager.REPORTS_DIR, REPORT_ID)


def _in_city_words(text):
    assert 'simulated' not in text.replace('"the simulated world is ours', '')
    assert '@crito_7' not in text and '#FreeSocrates' not in text and 'Twitter' not in text
    return text


def test_an_older_chronicle_is_served_in_the_citys_words(client):
    folder = _older_chronicle()
    with open(os.path.join(folder, 'meta.json'), 'rb') as handle:
        on_disk = handle.read()

    data = client.get(f'/api/report/{REPORT_ID}').get_json()['data']
    outline = data['outline']
    assert outline['summary'] == CITY_SUMMARY
    assert outline['title'] == 'The Hemlock Horizon'
    assert outline['sections'][0]['title'] == 'Crito in the Agora and the Stoa'
    markdown = _in_city_words(data['markdown_content'])
    # Her summary opens the whole Chronicle as a quotation, and is voiced there too.
    assert f'> {CITY_SUMMARY}' in markdown
    # A citizen's quoted words stay theirs: only the tag and the handle change.
    assert 'Crito pleaded in the Agora: "the simulated world is ours, Free Socrates".' in markdown
    assert 'The city held its breath.' in markdown

    by_simulation = client.get(f'/api/report/by-simulation/{SIM_ID}').get_json()['data']
    assert by_simulation['outline']['summary'] == CITY_SUMMARY
    (listed,) = client.get('/api/report/list').get_json()['data']
    assert listed['outline']['summary'] == CITY_SUMMARY

    sections = client.get(f'/api/report/{REPORT_ID}/sections').get_json()['data']['sections']
    _in_city_words(sections[0]['content'])
    single = client.get(f'/api/report/{REPORT_ID}/section/1').get_json()['data']
    _in_city_words(single['content'])

    logs = client.get(f'/api/report/{REPORT_ID}/agent-log').get_json()['data']['logs']
    assert logs[0]['details']['outline']['summary'] == CITY_SUMMARY
    assert logs[1]['section_title'] == 'Crito in the Agora and the Stoa'
    _in_city_words(logs[1]['details']['content'])
    # Only what the Scribe wrote is voiced; her working notes are left as logged.
    assert logs[2]['details'] == {'parameters': {'query': 'the simulated agents'}}

    # Nothing on disk changes.
    with open(os.path.join(folder, 'meta.json'), 'rb') as handle:
        assert handle.read() == on_disk


def test_the_shelf_reads_chronicle_titles_in_the_citys_words():
    payload = {'success': True, 'data': [
        {'simulation_id': SIM_ID, 'simulation_requirement': 'Q', 'report_title': 'The simulated Athens'},
        {'simulation_id': 'sim_other', 'report_title': None},
        'not a gathering',
    ]}
    voiced, rewrites = parthenon_api.chronicle_in_city_words('simulation.get_simulation_history', {}, payload)
    assert rewrites == 1
    assert voiced['data'][0]['report_title'] == 'Athens'
    assert voiced['data'][1:] == payload['data'][1:]
    assert payload['data'][0]['report_title'] == 'The simulated Athens'  # the original is left as it was


def test_the_city_words_pass_leaves_everything_else_alone(client, monkeypatch):
    _older_chronicle()
    # A Chronicle already in the city's words is served byte for byte.
    ReportManager.save_report(Report(
        report_id='report_clean', simulation_id=SIM_ID, graph_id='graph_test',
        simulation_requirement='Q', status=ReportStatus.COMPLETED,
        outline=ReportOutline(title='Clean', summary='Athens waits.', sections=[]),
        markdown_content='# Clean\n\n> Athens waits.\n', created_at='2026-09-25T13:00:00',
    ))
    direct = parthenon_api.chronicle_in_city_words(
        'report.get_report', {}, {'success': True, 'data': ReportManager.get_report('report_clean').to_dict()}
    )
    assert direct[1] == 0
    assert client.get('/api/report/report_clean').get_json()['data']['markdown_content'] == '# Clean\n\n> Athens waits.\n'

    # Failures, other routes and other methods pass through untouched.
    missing = client.get('/api/report/report_missing')
    assert missing.status_code == 404
    assert parthenon_api.chronicle_in_city_words('report.get_report', {}, {'success': False}) == ({'success': False}, 0)
    assert parthenon_api.chronicle_in_city_words('report.chat_with_report_agent', {}, {'success': True, 'data': 'the simulated'})[1] == 0

    # The Chronicle is never lost to its proofreading.
    def broken(*_args, **_kwargs):
        raise RuntimeError('the pass broke')

    monkeypatch.setattr(parthenon_api, 'scribe_voice', broken)
    response = client.get(f'/api/report/{REPORT_ID}')
    assert response.status_code == 200
    assert response.get_json()['data']['outline']['summary'] == OLD_SUMMARY
