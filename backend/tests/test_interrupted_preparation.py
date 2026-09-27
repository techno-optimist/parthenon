"""A preparation cut short by a stop, a deploy or a kill, on the public steps:

- the next start marks a gathering left 'preparing' with nothing at work as
  failed, in the city's words, so the owner's page prepares it again and no
  one waits on it forever (the owner's own machine is left as it was);
- a second summons while a preparation is at work follows that task, and a
  guest who knows only the gathering sees the task at work;
- a stop cancels the preparation's queued profiles and exit no longer waits
  for pool workers, so the backend ends within the platform's grace
  (utils/pools.py; the SIGTERM cleanup releases them first).
"""

import json
import os
import signal
import subprocess
import sys
import textwrap
import threading
import time
import weakref

import pytest

from app.models.task import TaskManager, TaskStatus
from app.services import simulation_manager as simulation_manager_module
from app.services.oasis_profile_generator import OasisAgentProfile, OasisProfileGenerator
from app.services.simulation_manager import (
    SimulationManager,
    SimulationState,
    SimulationStatus,
    interrupted_preparation_note,
    live_preparation_task,
)
from app.services.simulation_runner import SimulationRunner
from app.services.zep_entity_reader import EntityNode, FilteredEntities
from app.utils import pools

from test_public_mode import (  # noqa: F401 - fixtures
    OTHER_TOKEN, OWNED_PROJECT, OWNED_SIM, OWNER_TOKEN, city, make_project, make_simulation,
)


EN_NOTE = 'The gathering was interrupted before all its citizens arrived. The one who began it can call them again.'
POOLS_FILE = os.path.join(os.path.dirname(pools.__file__), 'pools.py')


def _state(simulation_id):
    path = os.path.join(SimulationManager.SIMULATION_DATA_DIR, simulation_id, 'state.json')
    with open(path, encoding='utf-8') as handle:
        return json.load(handle)


def _write_state(simulation_id, project_id=OWNED_PROJECT, **fields):
    make_simulation(simulation_id, project_id, status=fields.pop('status', 'preparing'))
    path = os.path.join(SimulationManager.SIMULATION_DATA_DIR, simulation_id, 'state.json')
    data = _state(simulation_id)
    data.update(fields)
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump(data, handle)


@pytest.fixture
def tasks():
    """Preparation tasks made by a test, forgotten afterwards (TaskManager is process wide)."""

    manager = TaskManager()
    made = []

    def live(simulation_id, status=TaskStatus.PROCESSING):
        task_id = manager.create_task('simulation_prepare', metadata={
            'simulation_id': simulation_id, 'project_id': OWNED_PROJECT,
        })
        manager.update_task(task_id, status=status, progress=40, message='[2/4] calling the citizens')
        made.append(task_id)
        return task_id

    yield live
    with manager._task_lock:
        for task_id in made:
            manager._tasks.pop(task_id, None)


@pytest.fixture
def public_stop(monkeypatch):
    """pools as on the public steps, with its own stop (restored afterwards)."""

    monkeypatch.setattr(pools, '_enabled', True)
    monkeypatch.setattr(pools, '_stopping', threading.Event())
    monkeypatch.setattr(pools, '_cancel_on_exit', weakref.WeakSet())
    return pools


# ================================================================== the next start

def test_the_next_start_marks_an_interrupted_preparation_failed(city, tasks):
    make_project(OWNED_PROJECT, token=OWNER_TOKEN)
    _write_state(OWNED_SIM, profiles_count=0, config_generated=False)
    _write_state('sim_settingswritten', config_generated=True)
    _write_state('sim_stillatwork', config_generated=False)
    _write_state('sim_alreadyready', status='ready', config_generated=True)
    tasks('sim_stillatwork')

    client = city.client()

    interrupted = _state(OWNED_SIM)
    assert interrupted['status'] == 'failed'
    assert interrupted['error'] == EN_NOTE
    # Settings already written: _check_simulation_prepared calls it ready.
    assert _state('sim_settingswritten')['status'] == 'preparing'
    # A task of this process still at work on it.
    assert _state('sim_stillatwork')['status'] == 'preparing'
    assert _state('sim_alreadyready')['status'] == 'ready'

    # The realtime reads now say so, instead of "still generating" forever.
    shown = client.get(f'/api/simulation/{OWNED_SIM}/config/realtime').json['data']
    assert shown['status'] == 'failed' and shown['is_generating'] is False
    assert shown['error'] == EN_NOTE


def test_the_owners_own_machine_keeps_its_old_start(city):
    make_project(OWNED_PROJECT)
    _write_state(OWNED_SIM, config_generated=False)

    city.client(public=False)

    assert _state(OWNED_SIM)['status'] == 'preparing'
    assert _state(OWNED_SIM).get('error') is None


def test_the_note_is_the_citys_words_in_both_languages():
    assert interrupted_preparation_note() == EN_NOTE
    assert interrupted_preparation_note('en') == EN_NOTE
    chinese = interrupted_preparation_note('zh')
    assert chinese != EN_NOTE and any('一' <= ch <= '鿿' for ch in chinese)
    assert '—' not in EN_NOTE + chinese


def test_a_broken_state_file_does_not_stop_the_scan(city):
    make_project(OWNED_PROJECT, token=OWNER_TOKEN)
    broken = os.path.join(SimulationManager.SIMULATION_DATA_DIR, 'sim_brokenfile0', 'state.json')
    os.makedirs(os.path.dirname(broken))
    with open(broken, 'w', encoding='utf-8') as handle:
        handle.write('{"status": "prep')
    _write_state(OWNED_SIM, config_generated=False)

    marked = SimulationManager().reconcile_interrupted_preparations()

    assert marked == [OWNED_SIM]
    assert _state(OWNED_SIM)['status'] == 'failed'


# ================================================================== while it is at work

def test_a_guest_sees_the_preparation_at_work(city, tasks):
    make_project(OWNED_PROJECT, token=OWNER_TOKEN)
    _write_state(OWNED_SIM, config_generated=False)
    task_id = tasks(OWNED_SIM)
    client = city.client()

    shown = client.post('/api/simulation/prepare/status', json={'simulation_id': OWNED_SIM})

    assert shown.status_code == 200
    data = shown.json['data']
    assert data['task_id'] == task_id and data['status'] == 'processing'
    assert data['simulation_id'] == OWNED_SIM and data['already_prepared'] is False
    assert data['progress'] == 40

    # Once it is over, the old answer for a gathering alone.
    TaskManager().fail_task(task_id, 'stopped')
    after = client.post('/api/simulation/prepare/status', json={'simulation_id': OWNED_SIM}).json['data']
    assert after['status'] == 'not_started'


def test_the_owners_own_machine_answers_status_as_before(city, tasks):
    make_project(OWNED_PROJECT)
    _write_state(OWNED_SIM, config_generated=False)
    tasks(OWNED_SIM)
    client = city.client(public=False)

    data = client.post('/api/simulation/prepare/status', json={'simulation_id': OWNED_SIM}).json['data']

    assert data['status'] == 'not_started' and 'task_id' not in data


def test_a_second_summons_follows_the_task_at_work(city, tasks, monkeypatch):
    make_project(OWNED_PROJECT, token=OWNER_TOKEN)
    _write_state(OWNED_SIM, config_generated=False, entities_count=7, entity_types=['Citizen'])
    task_id = tasks(OWNED_SIM)
    started = []
    monkeypatch.setattr(threading.Thread, 'start', lambda self: started.append(self.name))
    client = city.client()
    before = len(TaskManager().list_tasks('simulation_prepare'))

    response = client.post('/api/simulation/prepare', json={'simulation_id': OWNED_SIM},
                           headers={'X-Parthenon-Owner': OWNER_TOKEN})

    assert response.status_code == 200
    data = response.json['data']
    assert data['task_id'] == task_id and data['status'] == 'preparing'
    assert data['already_prepared'] is False and data['expected_entities_count'] == 7
    assert data['entity_types'] == ['Citizen']
    assert len(TaskManager().list_tasks('simulation_prepare')) == before
    assert started == []
    # Still the owner's alone.
    assert client.post('/api/simulation/prepare', json={'simulation_id': OWNED_SIM},
                       headers={'X-Parthenon-Owner': OTHER_TOKEN}).status_code == 403


def test_live_preparation_task_is_the_newest_live_one(tasks):
    assert live_preparation_task('sim_nobodyhome00') is None
    tasks('sim_twotasks0000', status=TaskStatus.FAILED)
    assert live_preparation_task('sim_twotasks0000') is None
    live = tasks('sim_twotasks0000', status=TaskStatus.PENDING)
    assert live_preparation_task('sim_twotasks0000')['task_id'] == live


# ================================================================== the stop

def _entity(index):
    return EntityNode(uuid=f'uuid-{index}', name=f'Citizen {index}', labels=['Entity', 'Citizen'],
                      summary='A citizen of Athens.', attributes={})


def test_a_stop_cancels_the_queued_profiles_without_stand_ins(public_stop, tmp_path, monkeypatch):
    generator = OasisProfileGenerator.__new__(OasisProfileGenerator)
    generator.graph_id = None
    first_began = threading.Event()
    let_go = threading.Event()
    asked = []

    def slow_profile(entity, user_id, use_llm=True):
        asked.append(user_id)
        first_began.set()
        let_go.wait(10)
        return OasisAgentProfile(user_id=user_id, user_name=f'citizen_{user_id}', name=entity.name,
                                 bio='bio', persona='persona')

    monkeypatch.setattr(generator, 'generate_profile_from_entity', slow_profile)
    monkeypatch.setattr(generator, '_print_generated_profile', lambda *args: None)
    realtime = tmp_path / 'reddit_profiles.json'
    outcome = {}

    def prepare():
        try:
            generator.generate_profiles_from_entities(
                entities=[_entity(index) for index in range(5)], use_llm=True,
                parallel_count=1, realtime_output_path=str(realtime), output_platform='reddit',
            )
            outcome['result'] = 'finished'
        except Exception as error:  # noqa: BLE001 - the test reads what came out
            outcome['result'] = error

    thread = threading.Thread(target=prepare, daemon=True)
    thread.start()
    assert first_began.wait(5)

    left = pools.release()
    let_go.set()
    thread.join(10)

    assert isinstance(outcome['result'], pools.Interrupted)
    assert asked == [0]  # the queued four were never begun
    assert left >= 1  # its worker is no longer waited for at exit
    # The one that was being written may be kept; no stand-in pasts for the crowd that never came.
    kept = json.loads(realtime.read_text(encoding='utf-8')) if realtime.exists() else []
    assert [profile['username'] for profile in kept] in ([], ['citizen_0'])
    # A pool asked for after the stop is refused at once.
    from concurrent.futures import ThreadPoolExecutor
    with pytest.raises(pools.Interrupted):
        pools.cancel_on_exit(ThreadPoolExecutor(max_workers=1))


def test_an_interrupted_preparation_reads_failed_in_the_citys_words(public_stop, monkeypatch):
    class Reader:
        def filter_defined_entities(self, **kwargs):
            return FilteredEntities(entities=[_entity(0)], entity_types={'Citizen'},
                                    total_count=1, filtered_count=1)

    class Generator:
        def __init__(self, **kwargs):
            pass

        def generate_profiles_from_entities(self, **kwargs):
            raise pools.Interrupted('The process is stopping.')

    monkeypatch.setattr(simulation_manager_module, 'ZepEntityReader', Reader)
    monkeypatch.setattr(simulation_manager_module, 'OasisProfileGenerator', Generator)
    manager = SimulationManager()
    manager._save_simulation_state(SimulationState(
        simulation_id='sim_stoppedmid00', project_id='project', graph_id='graph',
        status=SimulationStatus.CREATED,
    ))

    with pytest.raises(pools.Interrupted) as raised:
        manager.prepare_simulation('sim_stoppedmid00', 'Should Athens listen?', 'text')

    # The route's own handler writes str(error): the same calm words.
    note = interrupted_preparation_note('zh')  # the thread's locale in tests
    assert str(raised.value) == note
    state = _state('sim_stoppedmid00')
    assert state['status'] == 'failed' and state['error'] == note


def test_release_does_nothing_on_the_owners_own_machine(monkeypatch):
    monkeypatch.setattr(pools, '_enabled', False)
    monkeypatch.setattr(pools, '_stopping', threading.Event())
    from concurrent.futures import ThreadPoolExecutor

    pool = pools.cancel_on_exit(ThreadPoolExecutor(max_workers=1))
    gate = threading.Event()
    running = pool.submit(gate.wait, 5)
    queued = pool.submit(lambda: 'done')

    assert pools.release() == 0
    assert not pools.stopping() and not queued.cancelled()
    gate.set()
    assert queued.result(5) == 'done' and running.result(5) is True
    pool.shutdown()


def test_the_stop_signal_releases_the_pools_before_the_cleanup(monkeypatch):
    from app.services import simulation_runner as runner_module

    handlers = {}
    calls = []
    monkeypatch.delenv('WERKZEUG_RUN_MAIN', raising=False)
    monkeypatch.delenv('FLASK_DEBUG', raising=False)
    monkeypatch.setattr(runner_module, '_cleanup_registered', False)
    monkeypatch.setattr(runner_module.signal, 'getsignal', lambda _sig: signal.SIG_DFL)
    monkeypatch.setattr(runner_module.signal, 'signal', lambda sig, handler: handlers.__setitem__(sig, handler))
    monkeypatch.setattr(runner_module.atexit, 'register', lambda _fn: None)
    monkeypatch.setattr(runner_module.pools, 'release', lambda: calls.append('release') or 0)
    monkeypatch.setattr(SimulationRunner, 'cleanup_all_simulations',
                        classmethod(lambda cls: calls.append('cleanup')))

    SimulationRunner.register_cleanup()
    with pytest.raises(KeyboardInterrupt):
        handlers[signal.SIGTERM](signal.SIGTERM, None)

    assert calls == ['release', 'cleanup']


def test_the_public_steps_turn_the_stop_on(city):
    city.client(public=True)
    assert pools.enabled()


# ------------------------------------------------------------------ the process's end, for real

EXIT_SCRIPT = textwrap.dedent('''
    import importlib.util, signal, sys, threading, time
    from concurrent.futures import ThreadPoolExecutor

    spec = importlib.util.spec_from_file_location('pools_under_test', sys.argv[1])
    pools = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pools)
    mode, job_seconds = sys.argv[2], float(sys.argv[3])
    if mode != 'local':
        pools.enable()

    began = threading.Event()

    def job(index):
        began.set()
        time.sleep(job_seconds)

    def prepare():  # a daemon thread, as the preparation's own
        try:
            with pools.cancel_on_exit(ThreadPoolExecutor(max_workers=2)) as pool:
                list(pool.map(job, range(6)))
        except Exception:
            pass

    threading.Thread(target=prepare, daemon=True).start()
    began.wait(5)

    if mode == 'signal':
        def on_stop(signum, frame):  # as simulation_runner's cleanup: release, then leave
            pools.release()
            raise KeyboardInterrupt
        signal.signal(signal.SIGTERM, on_stop)
        print('ready', flush=True)
        try:
            while True:
                time.sleep(0.05)
        except KeyboardInterrupt:
            pass
    else:
        print('ready', flush=True)
''')


def _time_to_exit(tmp_path, mode, job_seconds, stop=False, from_launch=False):
    """Seconds from 'ready' (or from launch) until the probe process has ended."""

    script = tmp_path / 'exit_probe.py'
    script.write_text(EXIT_SCRIPT, encoding='utf-8')
    launched = time.monotonic()
    process = subprocess.Popen(
        [sys.executable, str(script), POOLS_FILE, mode, str(job_seconds)],
        stdout=subprocess.PIPE, text=True,
    )
    try:
        assert process.stdout.readline().strip() == 'ready'
        began = launched if from_launch else time.monotonic()
        if stop:
            process.send_signal(signal.SIGTERM)
        process.wait(30)
        return time.monotonic() - began
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        process.stdout.close()


def test_exit_waited_for_the_queued_crowd_before(tmp_path):
    # The check's finding, as it stands without the public steps' stop:
    # six 1.2 s profiles on two workers hold the end for at least 3.6 s.
    assert _time_to_exit(tmp_path, 'local', 1.2, from_launch=True) >= 3.5


def test_on_the_public_steps_exit_does_not_wait(tmp_path):
    assert _time_to_exit(tmp_path, 'public', 5.0) < 3.0


def test_on_the_public_steps_a_sigterm_ends_the_process_at_once(tmp_path):
    assert _time_to_exit(tmp_path, 'signal', 5.0, stop=True) < 3.0
