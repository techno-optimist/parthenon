"""Runs left active by a backend that has since restarted.

A run_state.json that still says STARTING/RUNNING/PAUSED/STOPPING after its
owner is gone must not block a new start forever, while a run that is really
live (process, graph memory drain, start in progress, surviving simulator)
must still be refused.
"""

import json
import os
import signal
import sys
import threading
import time
from types import SimpleNamespace

import pytest
from flask import Flask

from app.api import simulation as simulation_api
from app.config import Config
from app.services import simulation_runner as runner_module
from app.services.simulation_manager import (
    SimulationManager,
    SimulationState,
    SimulationStatus,
)
from app.services.simulation_runner import (
    AgentAction,
    RunnerStatus,
    SimulationRunState,
    SimulationRunner,
)
from app.utils.locale import set_locale

SIM_ID = "sim_stale_run"
DEAD_PID = 4242
# sim_env replaces threading.Thread for the runner; tests that need a real
# second thread (a concurrent request, a monitor draining) use this.
RealThread = threading.Thread

ALREADY_ACTIVE_EN = (
    f"Simulation {SIM_ID} is still running or finishing up. Wait for it to "
    "finish, or stop it, before starting it again."
)


class FakeMonitor:
    """A monitor thread that is alive until joined (or, if told, forever)."""

    def __init__(self, exits_on_join=True):
        self.alive = True
        self.exits_on_join = exits_on_join
        self.joins = []

    def is_alive(self):
        return self.alive

    def join(self, timeout=None):
        self.joins.append(timeout)
        if self.exits_on_join:
            self.alive = False


def _live_process(pid):
    process = SimpleNamespace(pid=pid, returncode=None)
    process.poll = lambda: process.returncode
    return process


def _record_terminations(monkeypatch, on_terminate=None):
    terminated = []

    def terminate(_cls, process, simulation_id, **_kwargs):
        if on_terminate is not None:
            on_terminate(process)
        terminated.append((simulation_id, process.pid))
        process.returncode = -15

    monkeypatch.setattr(SimulationRunner, "_terminate_process", classmethod(terminate))
    return terminated


@pytest.fixture
def sim_env(monkeypatch, tmp_path):
    root = tmp_path / "simulations"
    scripts = tmp_path / "scripts"
    root.mkdir()
    scripts.mkdir()
    for name in (
        "run_parallel_simulation.py",
        "run_twitter_simulation.py",
        "run_reddit_simulation.py",
    ):
        (scripts / name).write_text("pass\n", encoding="utf-8")

    monkeypatch.setattr(SimulationRunner, "RUN_STATE_DIR", str(root))
    monkeypatch.setattr(SimulationRunner, "SCRIPTS_DIR", str(scripts))
    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(root))
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(root))

    # pid -> command line of a process the "OS" reports as running.
    live_commands = {}
    monkeypatch.setattr(
        runner_module,
        "_process_command_line",
        lambda pid: live_commands.get(pid, ""),
    )
    monkeypatch.setattr(
        runner_module,
        "_process_table",
        lambda: list(live_commands.items()),
    )
    # Tests that exercise the wait use their own, shorter bound.
    monkeypatch.setattr(SimulationRunner, "START_CLAIM_WAIT_SECONDS", 5.0)
    monkeypatch.setattr(SimulationRunner, "ENV_CLOSE_MONITOR_TIMEOUT_SECONDS", 5.0)

    spawned = []

    class FakeProcess:
        def __init__(self, cmd, **_kwargs):
            self.cmd = cmd
            self.pid = 50000 + len(spawned)
            self.returncode = None
            spawned.append(self)

        def poll(self):
            return self.returncode

    class FakeThread:
        def __init__(self, *_args, **_kwargs):
            self.started = False

        def start(self):
            self.started = True

        def is_alive(self):
            return False

        def join(self, timeout=None):
            pass

    monkeypatch.setattr(runner_module.subprocess, "Popen", FakeProcess)
    monkeypatch.setattr(runner_module.threading, "Thread", FakeThread)

    env = SimpleNamespace(
        root=root,
        live_commands=live_commands,
        spawned=spawned,
        ids={SIM_ID},
    )
    yield env

    for simulation_id in env.ids:
        for registry in (
            SimulationRunner._run_states,
            SimulationRunner._processes,
            SimulationRunner._monitor_threads,
            SimulationRunner._action_queues,
            SimulationRunner._stderr_files,
            SimulationRunner._graph_memory_enabled,
        ):
            registry.pop(simulation_id, None)
        handle = SimulationRunner._stdout_files.pop(simulation_id, None)
        if handle is not None:
            handle.close()
        SimulationRunner._manual_stop_requests.discard(simulation_id)
        SimulationRunner._start_claims.discard(simulation_id)


def _write_prepared_simulation(root, simulation_id=SIM_ID, status=SimulationStatus.READY):
    sim_dir = root / simulation_id
    sim_dir.mkdir(parents=True, exist_ok=True)
    (sim_dir / "simulation_config.json").write_text(
        json.dumps({
            "time_config": {
                "total_simulation_hours": 168,
                "minutes_per_round": 30,
            }
        }),
        encoding="utf-8",
    )
    (sim_dir / "reddit_profiles.json").write_text("[]", encoding="utf-8")
    (sim_dir / "twitter_profiles.csv").write_text("", encoding="utf-8")
    SimulationManager()._save_simulation_state(
        SimulationState(
            simulation_id=simulation_id,
            project_id="proj_1",
            graph_id="graph_1",
            status=status,
            profiles_generated=True,
            config_generated=True,
        )
    )
    return sim_dir


def _write_run_state(
    root,
    runner_status,
    simulation_id=SIM_ID,
    pid=DEAD_PID,
    current_round=136,
    total_rounds=336,
):
    """Persist a run state as a previous backend left it, then forget it."""

    state = SimulationRunState(
        simulation_id=simulation_id,
        runner_status=runner_status,
        current_round=current_round,
        total_rounds=total_rounds,
        twitter_running=True,
        reddit_running=True,
        twitter_actions_count=900,
        reddit_actions_count=700,
        started_at="2026-09-24T10:00:00",
        process_pid=pid,
    )
    state.recent_actions.append(
        AgentAction(
            round_num=current_round,
            timestamp="2026-09-24T12:00:00",
            platform="twitter",
            agent_id=1,
            agent_name="Agent One",
            action_type="CREATE_POST",
        )
    )
    SimulationRunner._save_run_state(state)
    twitter_dir = root / simulation_id / "twitter"
    twitter_dir.mkdir(parents=True, exist_ok=True)
    (twitter_dir / "actions.jsonl").write_text(
        '{"round": 136, "agent_id": 1, "action_type": "CREATE_POST"}\n',
        encoding="utf-8",
    )
    # A fresh backend has nothing cached; everything comes from disk.
    SimulationRunner._run_states.pop(simulation_id, None)
    return state


def _persisted_run_status(root, simulation_id=SIM_ID):
    with open(root / simulation_id / "run_state.json", encoding="utf-8") as f:
        return json.load(f)


def _simulation_status(simulation_id=SIM_ID):
    return SimulationManager().get_simulation(simulation_id)


def _post_start(payload, locale="en"):
    app = Flask(__name__)
    with app.test_request_context(
        "/api/simulation/start",
        method="POST",
        json=payload,
        headers={"Accept-Language": locale},
    ):
        result = simulation_api.start_simulation()
    if isinstance(result, tuple):
        response, status = result
    else:
        response, status = result, result.status_code
    return response.get_json(), status


# ---------------------------------------------------------------- reconcile


def test_stale_stopping_run_is_reconciled_as_stopped_and_keeps_history(sim_env):
    set_locale("en")
    _write_prepared_simulation(sim_env.root)
    _write_run_state(sim_env.root, RunnerStatus.STOPPING)

    reconciled = SimulationRunner.reconcile_orphaned_run(SIM_ID)

    assert reconciled is not None
    assert reconciled.runner_status == RunnerStatus.STOPPED
    persisted = _persisted_run_status(sim_env.root)
    assert persisted["runner_status"] == "stopped"
    assert persisted["current_round"] == 136
    assert persisted["total_rounds"] == 336
    assert persisted["twitter_actions_count"] == 900
    assert persisted["reddit_actions_count"] == 700
    assert persisted["started_at"] == "2026-09-24T10:00:00"
    assert persisted["completed_at"]
    assert persisted["twitter_running"] is False
    assert persisted["reddit_running"] is False
    assert len(persisted["recent_actions"]) == 1
    note = persisted["error"]
    assert "'stopping'" in note and "136/336" in note and str(DEAD_PID) in note
    assert "marked as stopped" in note
    assert (sim_env.root / SIM_ID / "twitter" / "actions.jsonl").exists()

    simulation = _simulation_status()
    assert simulation.status == SimulationStatus.STOPPED
    assert simulation.error == note

    # Nothing left to do on a second pass.
    assert SimulationRunner.reconcile_orphaned_run(SIM_ID) is None


def test_start_succeeds_after_stale_stopping_run_with_dead_process(sim_env):
    _write_prepared_simulation(sim_env.root)
    _write_run_state(sim_env.root, RunnerStatus.STOPPING)

    run = SimulationRunner.start_simulation(SIM_ID, platform="parallel")

    assert run.runner_status == RunnerStatus.RUNNING
    assert len(sim_env.spawned) == 1
    assert run.process_pid == sim_env.spawned[0].pid
    assert _persisted_run_status(sim_env.root)["runner_status"] == "running"
    assert _simulation_status().status == SimulationStatus.RUNNING
    assert SIM_ID not in SimulationRunner._start_claims


def test_start_is_refused_while_process_is_alive_in_this_server(sim_env):
    set_locale("en")
    _write_prepared_simulation(sim_env.root, status=SimulationStatus.RUNNING)
    _write_run_state(sim_env.root, RunnerStatus.RUNNING, pid=5555)
    SimulationRunner._processes[SIM_ID] = SimpleNamespace(
        pid=5555, poll=lambda: None
    )

    assert SimulationRunner.reconcile_orphaned_run(SIM_ID) is None
    with pytest.raises(ValueError, match="still running or finishing up"):
        SimulationRunner.start_simulation(SIM_ID, platform="parallel")

    assert sim_env.spawned == []
    assert _persisted_run_status(sim_env.root)["runner_status"] == "running"
    assert SIM_ID not in SimulationRunner._start_claims


def test_start_is_refused_while_graph_memory_updater_is_active(sim_env, monkeypatch):
    set_locale("en")
    _write_prepared_simulation(sim_env.root)
    _write_run_state(sim_env.root, RunnerStatus.STOPPING)
    monkeypatch.setattr(
        runner_module.ZepGraphMemoryManager,
        "get_updater",
        classmethod(lambda _cls, _simulation_id: object()),
    )

    assert SimulationRunner.reconcile_orphaned_run(SIM_ID) is None
    with pytest.raises(ValueError, match="still running or finishing up"):
        SimulationRunner.start_simulation(SIM_ID, platform="parallel")

    assert sim_env.spawned == []
    assert _persisted_run_status(sim_env.root)["runner_status"] == "stopping"


def test_start_in_progress_in_this_server_is_refused_but_a_dead_one_is_not(sim_env):
    set_locale("en")
    _write_prepared_simulation(sim_env.root)
    _write_run_state(sim_env.root, RunnerStatus.STARTING, pid=None)

    SimulationRunner._start_claims.add(SIM_ID)
    assert SimulationRunner.reconcile_orphaned_run(SIM_ID) is None
    with pytest.raises(ValueError, match="still running or finishing up"):
        SimulationRunner.start_simulation(SIM_ID, platform="parallel")
    assert _persisted_run_status(sim_env.root)["runner_status"] == "starting"

    # The same STARTING left behind by a dead backend has no claim here.
    SimulationRunner._start_claims.discard(SIM_ID)
    run = SimulationRunner.start_simulation(SIM_ID, platform="parallel")
    assert run.runner_status == RunnerStatus.RUNNING


def test_surviving_simulator_process_blocks_start_and_stop(sim_env):
    set_locale("en")
    _write_prepared_simulation(sim_env.root)
    _write_run_state(sim_env.root, RunnerStatus.RUNNING, pid=7777)
    sim_env.live_commands[7777] = (
        "python scripts/run_parallel_simulation.py --config "
        f"/data/simulations/{SIM_ID}/simulation_config.json"
    )

    assert SimulationRunner.reconcile_orphaned_run(SIM_ID) is None
    with pytest.raises(ValueError, match="still being run by process 7777"):
        SimulationRunner.start_simulation(SIM_ID, platform="parallel")
    # Stopping it here would only relabel it; the simulator keeps writing.
    with pytest.raises(ValueError, match="still being run by process 7777"):
        SimulationRunner.stop_simulation(SIM_ID)

    assert sim_env.spawned == []
    assert _persisted_run_status(sim_env.root)["runner_status"] == "running"


def test_reused_pid_is_not_mistaken_for_the_simulator(sim_env):
    _write_prepared_simulation(sim_env.root)
    _write_run_state(sim_env.root, RunnerStatus.RUNNING, pid=7777)
    sim_env.live_commands[7777] = "/usr/sbin/some-unrelated-daemon --flag"

    reconciled = SimulationRunner.reconcile_orphaned_run(SIM_ID)

    assert reconciled is not None
    assert reconciled.runner_status == RunnerStatus.STOPPED


def test_refusal_message_follows_the_request_locale(sim_env):
    _write_prepared_simulation(sim_env.root)
    _write_run_state(sim_env.root, RunnerStatus.STOPPING)
    SimulationRunner._processes[SIM_ID] = SimpleNamespace(
        pid=DEAD_PID, poll=lambda: None
    )

    set_locale("zh")
    with pytest.raises(ValueError, match="模拟已在运行或结束处理中"):
        SimulationRunner.start_simulation(SIM_ID, platform="parallel")
    set_locale("en")
    with pytest.raises(ValueError, match=f"Simulation {SIM_ID} is still running"):
        SimulationRunner.start_simulation(SIM_ID, platform="parallel")


def test_rejected_graph_memory_start_leaves_no_starting_claim(sim_env):
    _write_prepared_simulation(sim_env.root)

    with pytest.raises(ValueError, match="graph_id"):
        SimulationRunner.start_simulation(
            SIM_ID,
            platform="parallel",
            enable_graph_memory_update=True,
            graph_id=None,
        )

    assert not (sim_env.root / SIM_ID / "run_state.json").exists()
    assert SIM_ID not in SimulationRunner._start_claims


# ---------------------------------------------------------------------- API


def test_api_force_start_clears_stale_run_when_state_is_ready(sim_env):
    # The reported case: state.json READY, run_state STOPPING, process gone.
    _write_prepared_simulation(sim_env.root, status=SimulationStatus.READY)
    _write_run_state(sim_env.root, RunnerStatus.STOPPING)

    body, status = _post_start(
        {"simulation_id": SIM_ID, "platform": "parallel", "force": True}
    )

    assert status == 200, body
    assert body["data"]["runner_status"] == "running"
    assert body["data"]["force_restarted"] is True
    assert len(sim_env.spawned) == 1
    # force cleaned the old run's logs even though state.json was READY.
    assert not (sim_env.root / SIM_ID / "twitter" / "actions.jsonl").exists()
    assert _simulation_status().status == SimulationStatus.RUNNING


def test_api_start_without_force_recovers_stale_run(sim_env):
    # The dead backend had projected STOPPING into state.json as well.
    _write_prepared_simulation(sim_env.root, status=SimulationStatus.STOPPING)
    _write_run_state(sim_env.root, RunnerStatus.STOPPING)

    body, status = _post_start({"simulation_id": SIM_ID, "platform": "parallel"})

    assert status == 200, body
    assert body["data"]["runner_status"] == "running"
    assert body["data"]["force_restarted"] is False
    # Without force the previous run's action log is left alone.
    assert (sim_env.root / SIM_ID / "twitter" / "actions.jsonl").exists()


def test_api_force_start_stops_a_live_run_even_when_state_is_ready(sim_env, monkeypatch):
    _write_prepared_simulation(sim_env.root, status=SimulationStatus.READY)
    _write_run_state(sim_env.root, RunnerStatus.RUNNING, pid=6000)
    live = SimpleNamespace(pid=6000, returncode=None)
    live.poll = lambda: live.returncode
    SimulationRunner._processes[SIM_ID] = live
    terminated = []

    def terminate(_cls, process, simulation_id, **_kwargs):
        terminated.append(simulation_id)
        process.returncode = -15

    monkeypatch.setattr(SimulationRunner, "_terminate_process", classmethod(terminate))

    body, status = _post_start({"simulation_id": SIM_ID, "force": True})

    assert status == 200, body
    assert terminated == [SIM_ID]
    assert body["data"]["force_restarted"] is True
    assert body["data"]["process_pid"] == sim_env.spawned[0].pid


def test_api_refuses_a_start_in_progress_without_wiping_it(sim_env):
    _write_prepared_simulation(sim_env.root)
    _write_run_state(sim_env.root, RunnerStatus.STARTING, pid=None)
    SimulationRunner._start_claims.add(SIM_ID)

    body, status = _post_start({"simulation_id": SIM_ID, "force": True})

    assert status == 400
    assert body["error"] == (
        f"Simulation {SIM_ID} is still running or finishing up. Wait for it "
        "to finish, or stop it, before starting it again."
    )
    assert _persisted_run_status(sim_env.root)["runner_status"] == "starting"
    assert (sim_env.root / SIM_ID / "twitter" / "actions.jsonl").exists()
    assert sim_env.spawned == []

    body, status = _post_start({"simulation_id": SIM_ID}, locale="zh")
    assert status == 400
    assert body["error"].startswith(f"模拟已在运行或结束处理中: {SIM_ID}")


def test_api_force_start_refuses_a_surviving_simulator(sim_env):
    _write_prepared_simulation(sim_env.root, status=SimulationStatus.RUNNING)
    _write_run_state(sim_env.root, RunnerStatus.RUNNING, pid=7777)
    sim_env.live_commands[7777] = f"python run_parallel_simulation.py {SIM_ID}"

    body, status = _post_start({"simulation_id": SIM_ID, "force": True})

    assert status == 409
    assert "still being run by process 7777" in body["error"]
    assert _persisted_run_status(sim_env.root)["runner_status"] == "running"
    assert (sim_env.root / SIM_ID / "twitter" / "actions.jsonl").exists()
    assert sim_env.spawned == []

    # Without force the answer is the same, not a hint to /stop or force
    # (both of which refuse this process).
    body, status = _post_start({"simulation_id": SIM_ID})
    assert status == 409
    assert "still being run by process 7777" in body["error"]
    assert "force" not in body["error"]

    # And it is translated whole, without an English prefix.
    body, status = _post_start({"simulation_id": SIM_ID, "force": True}, locale="zh")
    assert status == 409
    assert body["error"].startswith(f"模拟 {SIM_ID} 仍由进程 7777 运行")
    assert "Cannot" not in body["error"]
    assert sim_env.spawned == []


def test_api_force_path_failures_are_translated(sim_env, monkeypatch):
    _write_prepared_simulation(sim_env.root, status=SimulationStatus.RUNNING)
    _write_run_state(sim_env.root, RunnerStatus.RUNNING, pid=6000)
    SimulationRunner._processes[SIM_ID] = _live_process(6000)

    def failing_stop(_cls, _simulation_id):
        raise RuntimeError("boom")

    monkeypatch.setattr(SimulationRunner, "stop_simulation", classmethod(failing_stop))

    body, status = _post_start({"simulation_id": SIM_ID, "force": True})
    assert status == 409
    assert body["error"] == (
        "Cannot restart until the previous simulation finalizes safely: boom"
    )
    body, status = _post_start({"simulation_id": SIM_ID, "force": True}, locale="zh")
    assert status == 409
    assert body["error"] == "上一次模拟安全结束前无法重新开始：boom"
    assert sim_env.spawned == []

    SimulationRunner._processes.pop(SIM_ID)
    monkeypatch.setattr(
        SimulationRunner,
        "cleanup_simulation_logs",
        classmethod(
            lambda _cls, _simulation_id: {
                "success": False,
                "cleaned_files": [],
                "errors": ["run_state.json: locked"],
            }
        ),
    )
    SimulationRunner.reconcile_orphaned_run(SIM_ID)  # nothing owns it now
    body, status = _post_start({"simulation_id": SIM_ID, "force": True}, locale="zh")
    assert status == 500
    assert body["error"] == "清理上一次模拟日志失败：run_state.json: locked"
    assert sim_env.spawned == []


def test_api_says_a_draining_run_is_finishing_not_unprepared(sim_env, monkeypatch):
    _write_prepared_simulation(sim_env.root, status=SimulationStatus.STOPPING)
    _write_run_state(sim_env.root, RunnerStatus.STOPPING)
    monkeypatch.setattr(
        runner_module.ZepGraphMemoryManager,
        "get_updater",
        classmethod(lambda _cls, _simulation_id: object()),
    )

    body, status = _post_start({"simulation_id": SIM_ID, "force": True})

    assert status == 400
    assert body["error"] == ALREADY_ACTIVE_EN
    assert (sim_env.root / SIM_ID / "twitter" / "actions.jsonl").exists()
    assert sim_env.spawned == []


def test_api_force_start_of_a_new_simulation_is_not_reported_as_a_restart(sim_env):
    # Step 3 always sends force=true; a simulation that never ran has no
    # previous logs to clear, so the UI must not say it cleared any.
    _write_prepared_simulation(sim_env.root, status=SimulationStatus.READY)

    body, status = _post_start({"simulation_id": SIM_ID, "force": True})

    assert status == 200, body
    assert body["data"]["force_restarted"] is False
    assert len(sim_env.spawned) == 1


@pytest.mark.parametrize(
    "simulation_status",
    [SimulationStatus.STOPPING, SimulationStatus.READY],
)
def test_api_start_never_waits_for_a_finalization_in_progress(sim_env, simulation_status):
    # The monitor holds the finalization lock for the whole graph memory
    # drain (minutes). A start arriving meanwhile must answer at once, not
    # wait the drain out and then force-wipe the run that just finished.
    _write_prepared_simulation(sim_env.root, status=simulation_status)
    _write_run_state(sim_env.root, RunnerStatus.STOPPING, pid=None)
    SimulationRunner._monitor_threads[SIM_ID] = FakeMonitor(exits_on_join=False)
    lock = SimulationRunner._finalization_lock(SIM_ID)
    holding, release = threading.Event(), threading.Event()

    def drain():
        with lock:
            holding.set()
            release.wait(5)

    drainer = RealThread(target=drain, daemon=True)
    drainer.start()
    assert holding.wait(5)
    try:
        started = time.monotonic()
        body, status = _post_start({"simulation_id": SIM_ID, "force": True})
        elapsed = time.monotonic() - started
    finally:
        release.set()
        drainer.join(5)

    assert elapsed < 1.0
    assert status == 400
    assert body["error"] == ALREADY_ACTIVE_EN
    assert _persisted_run_status(sim_env.root)["runner_status"] == "stopping"
    assert (sim_env.root / SIM_ID / "twitter" / "actions.jsonl").exists()
    assert sim_env.spawned == []


# ------------------------------------- finished run, environment still open


def test_start_is_refused_while_a_finished_run_keeps_its_environment_open(sim_env):
    set_locale("en")
    _write_prepared_simulation(sim_env.root, status=SimulationStatus.COMPLETED)
    _write_run_state(sim_env.root, RunnerStatus.COMPLETED, pid=6000)
    SimulationRunner._processes[SIM_ID] = _live_process(6000)
    SimulationRunner._monitor_threads[SIM_ID] = FakeMonitor()

    with pytest.raises(ValueError, match="still open for interviews"):
        SimulationRunner.start_simulation(SIM_ID, platform="parallel")

    assert sim_env.spawned == []
    assert _persisted_run_status(sim_env.root)["runner_status"] == "completed"


def test_start_is_refused_while_the_previous_monitor_is_still_finishing(sim_env):
    set_locale("en")
    _write_prepared_simulation(sim_env.root, status=SimulationStatus.COMPLETED)
    _write_run_state(sim_env.root, RunnerStatus.COMPLETED, pid=6000)
    exited = _live_process(6000)
    exited.returncode = 0
    SimulationRunner._processes[SIM_ID] = exited
    SimulationRunner._monitor_threads[SIM_ID] = FakeMonitor()

    with pytest.raises(ValueError, match="still running or finishing up"):
        SimulationRunner.start_simulation(SIM_ID, platform="parallel")
    assert sim_env.spawned == []


def test_api_force_start_ends_a_finished_runs_environment_before_clearing_it(
    sim_env, monkeypatch
):
    _write_prepared_simulation(sim_env.root, status=SimulationStatus.COMPLETED)
    _write_run_state(sim_env.root, RunnerStatus.COMPLETED, pid=6000)
    database = sim_env.root / SIM_ID / "twitter_simulation.db"
    database.write_text("db", encoding="utf-8")
    SimulationRunner._processes[SIM_ID] = _live_process(6000)
    monitor = FakeMonitor()
    SimulationRunner._monitor_threads[SIM_ID] = monitor
    database_at_termination = []
    terminated = _record_terminations(
        monkeypatch,
        on_terminate=lambda _process: database_at_termination.append(database.exists()),
    )

    body, status = _post_start({"simulation_id": SIM_ID, "force": True})

    assert status == 200, body
    assert terminated == [(SIM_ID, 6000)]
    # The simulator was ended while its files were still in place, and its
    # monitor had exited, before force cleared them for the new run.
    assert database_at_termination == [True]
    assert monitor.joins and not monitor.is_alive()
    assert not database.exists()
    assert len(sim_env.spawned) == 1
    assert SimulationRunner._processes[SIM_ID] is sim_env.spawned[0]
    assert body["data"]["force_restarted"] is True


def test_api_start_without_force_refuses_a_finished_run_with_open_environment(
    sim_env, monkeypatch
):
    _write_prepared_simulation(sim_env.root, status=SimulationStatus.COMPLETED)
    _write_run_state(sim_env.root, RunnerStatus.COMPLETED, pid=6000)
    SimulationRunner._processes[SIM_ID] = _live_process(6000)
    SimulationRunner._monitor_threads[SIM_ID] = FakeMonitor()
    terminated = _record_terminations(monkeypatch)

    body, status = _post_start({"simulation_id": SIM_ID})

    assert status == 400
    assert "still open for interviews" in body["error"]
    assert terminated == []
    assert sim_env.spawned == []
    assert (sim_env.root / SIM_ID / "twitter" / "actions.jsonl").exists()


def test_api_force_start_waits_for_the_old_monitor_or_reports_pending(
    sim_env, monkeypatch
):
    _write_prepared_simulation(sim_env.root, status=SimulationStatus.COMPLETED)
    _write_run_state(sim_env.root, RunnerStatus.COMPLETED, pid=6000)
    SimulationRunner._processes[SIM_ID] = _live_process(6000)
    SimulationRunner._monitor_threads[SIM_ID] = FakeMonitor(exits_on_join=False)
    _record_terminations(monkeypatch)

    body, status = _post_start({"simulation_id": SIM_ID, "force": True})

    assert status == 409
    assert body["pending"] is True
    assert "still closing" in body["error"]
    assert (sim_env.root / SIM_ID / "twitter" / "actions.jsonl").exists()
    assert sim_env.spawned == []


def test_old_monitor_neither_finalizes_nor_unregisters_a_newer_run(sim_env):
    _write_prepared_simulation(sim_env.root, status=SimulationStatus.RUNNING)
    _write_run_state(sim_env.root, RunnerStatus.COMPLETED, pid=6000)
    SimulationRunner.get_run_state(SIM_ID)  # the old monitor's state object
    sim_dir = sim_env.root / SIM_ID
    old_log = open(sim_dir / "old.log", "w", encoding="utf-8")
    new_log = open(sim_dir / "new.log", "w", encoding="utf-8")
    new_state = SimulationRunState(
        simulation_id=SIM_ID,
        runner_status=RunnerStatus.RUNNING,
        total_rounds=336,
        process_pid=7000,
    )
    new_process = _live_process(7000)
    new_monitor = FakeMonitor()

    old_process = SimpleNamespace(pid=6000, returncode=None)

    def old_poll():
        if old_process.returncode is None:
            # A newer run takes the simulation over; then the old simulator
            # exits and the old monitor reaches its finally block.
            SimulationRunner._save_run_state(new_state)
            SimulationRunner._processes[SIM_ID] = new_process
            SimulationRunner._monitor_threads[SIM_ID] = new_monitor
            SimulationRunner._stdout_files[SIM_ID] = new_log
            old_process.returncode = 0
        return old_process.returncode

    old_process.poll = old_poll
    SimulationRunner._processes[SIM_ID] = old_process
    SimulationRunner._stdout_files[SIM_ID] = old_log

    try:
        SimulationRunner._monitor_simulation(SIM_ID, "en")

        assert _persisted_run_status(sim_env.root)["runner_status"] == "running"
        assert SimulationRunner.get_run_state(SIM_ID) is new_state
        assert SimulationRunner._processes[SIM_ID] is new_process
        assert SimulationRunner._monitor_threads[SIM_ID] is new_monitor
        assert SimulationRunner._stdout_files[SIM_ID] is new_log
        assert not new_log.closed
        assert old_log.closed
    finally:
        new_log.close()


def test_monitor_finalizes_and_unregisters_its_own_run(sim_env):
    _write_prepared_simulation(sim_env.root, status=SimulationStatus.RUNNING)
    _write_run_state(sim_env.root, RunnerStatus.RUNNING, pid=6000)
    log = open(sim_env.root / SIM_ID / "simulation.log", "w", encoding="utf-8")
    exited = _live_process(6000)
    exited.returncode = 0
    SimulationRunner._processes[SIM_ID] = exited
    SimulationRunner._monitor_threads[SIM_ID] = threading.current_thread()
    SimulationRunner._stdout_files[SIM_ID] = log

    SimulationRunner._monitor_simulation(SIM_ID, "en")

    assert _persisted_run_status(sim_env.root)["runner_status"] == "completed"
    assert SIM_ID not in SimulationRunner._processes
    assert SIM_ID not in SimulationRunner._monitor_threads
    assert SIM_ID not in SimulationRunner._stdout_files
    assert log.closed


def test_shutdown_ends_a_finished_runs_interview_environment(sim_env, monkeypatch):
    _write_prepared_simulation(sim_env.root, status=SimulationStatus.COMPLETED)
    _write_run_state(sim_env.root, RunnerStatus.COMPLETED, pid=6000)
    SimulationRunner._processes[SIM_ID] = _live_process(6000)
    SimulationRunner._monitor_threads[SIM_ID] = FakeMonitor()
    terminated = _record_terminations(monkeypatch)
    monkeypatch.setattr(SimulationRunner, "_cleanup_done", False)

    SimulationRunner.cleanup_all_simulations()

    # Without this the simulator (in its own session) outlives the backend
    # and blocks the next start of this simulation.
    assert terminated == [(SIM_ID, 6000)]
    assert SimulationRunner._cleanup_done is True  # nothing failed
    assert _persisted_run_status(sim_env.root)["runner_status"] == "completed"


# ------------------------------------------------- stop vs. start in progress


def test_stop_during_a_start_in_progress_waits_then_stops_the_started_run(
    sim_env, monkeypatch
):
    _write_prepared_simulation(sim_env.root)
    manager = runner_module.ZepGraphMemoryManager
    updaters, drained = {}, []
    monkeypatch.setattr(
        manager,
        "create_updater",
        classmethod(lambda _cls, sid, _gid, locale=None, accounts=None: updaters.setdefault(sid, object())),
    )
    monkeypatch.setattr(
        manager, "get_updater", classmethod(lambda _cls, sid: updaters.get(sid))
    )

    def stop_updater(_cls, sid):
        drained.append(_persisted_run_status(sim_env.root)["runner_status"])
        updaters.pop(sid, None)

    monkeypatch.setattr(manager, "stop_updater", classmethod(stop_updater))
    terminated = _record_terminations(monkeypatch)

    stop_outcome = {}

    def stop_request():
        try:
            stop_outcome["state"] = SimulationRunner.stop_simulation(SIM_ID)
        except Exception as error:  # pragma: no cover - reported below
            stop_outcome["error"] = error

    stopper = RealThread(target=stop_request, daemon=True)
    spawn = runner_module.subprocess.Popen

    def popen_while_a_stop_arrives(cmd, **kwargs):
        # e.g. Step 3's back button right after its automatic start.
        stopper.start()
        stopper.join(0.3)
        assert stopper.is_alive(), "stop did not wait for the start to publish"
        assert drained == []
        assert _persisted_run_status(sim_env.root)["runner_status"] == "starting"
        return spawn(cmd, **kwargs)

    monkeypatch.setattr(runner_module.subprocess, "Popen", popen_while_a_stop_arrives)

    run = SimulationRunner.start_simulation(
        SIM_ID,
        platform="parallel",
        enable_graph_memory_update=True,
        graph_id="graph_1",
    )
    assert run.runner_status == RunnerStatus.RUNNING
    stopper.join(5)

    assert not stopper.is_alive()
    assert "error" not in stop_outcome, stop_outcome.get("error")
    assert stop_outcome["state"].runner_status == RunnerStatus.STOPPED
    # The stop ended what the start launched, and drained graph memory only
    # after that (not while the run was still being launched).
    assert terminated == [(SIM_ID, sim_env.spawned[0].pid)]
    assert drained == ["stopping"]
    assert _persisted_run_status(sim_env.root)["runner_status"] == "stopped"
    assert SimulationRunner._graph_memory_enabled.get(SIM_ID) is None


def test_the_memory_updater_keeps_each_citizen_on_its_graph_node(sim_env, monkeypatch):
    # An English record shows 苏格拉底 as "Socrates": the updater is told his node.
    sim_dir = _write_prepared_simulation(sim_env.root)
    config = json.loads((sim_dir / "simulation_config.json").read_text(encoding="utf-8"))
    config["agent_configs"] = [
        {"agent_id": 0, "entity_uuid": "node-socrates", "entity_name": "Socrates"},
        {"agent_id": 1, "entity_uuid": "", "entity_name": "Crito"},
    ]
    (sim_dir / "simulation_config.json").write_text(json.dumps(config), encoding="utf-8")
    created = {}
    monkeypatch.setattr(
        runner_module.ZepGraphMemoryManager,
        "create_updater",
        classmethod(lambda _cls, sid, _gid, locale=None, accounts=None: created.setdefault(sid, accounts)),
    )

    run = SimulationRunner.start_simulation(
        SIM_ID, platform="parallel", enable_graph_memory_update=True, graph_id="graph_1"
    )

    assert run.runner_status == RunnerStatus.RUNNING
    assert created == {SIM_ID: {"Socrates": "node-socrates"}}


def test_stop_refuses_when_a_start_stays_in_progress(sim_env, monkeypatch):
    set_locale("en")
    monkeypatch.setattr(SimulationRunner, "START_CLAIM_WAIT_SECONDS", 0.2)
    _write_prepared_simulation(sim_env.root)
    _write_run_state(sim_env.root, RunnerStatus.STARTING, pid=None)
    SimulationRunner._start_claims.add(SIM_ID)

    with pytest.raises(ValueError, match=f"Simulation {SIM_ID} is still starting"):
        SimulationRunner.stop_simulation(SIM_ID)

    assert _persisted_run_status(sim_env.root)["runner_status"] == "starting"
    assert SIM_ID not in SimulationRunner._manual_stop_requests


# ---------------------------------------------- shutdown signal re-entrance


def test_a_repeated_shutdown_signal_does_not_abort_the_running_cleanup(
    sim_env, monkeypatch
):
    handlers = {}
    monkeypatch.setattr(runner_module, "_cleanup_registered", False)
    monkeypatch.delenv("WERKZEUG_RUN_MAIN", raising=False)
    monkeypatch.delenv("FLASK_DEBUG", raising=False)
    monkeypatch.setattr(runner_module.atexit, "register", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(runner_module.signal, "getsignal", lambda _signum: signal.SIG_DFL)
    monkeypatch.setattr(
        runner_module.signal,
        "signal",
        lambda signum, handler: handlers.__setitem__(signum, handler),
    )
    monkeypatch.setattr(SimulationRunner, "_cleanup_done", False)
    SimulationRunner.register_cleanup()

    _write_prepared_simulation(sim_env.root, status=SimulationStatus.RUNNING)
    _write_run_state(sim_env.root, RunnerStatus.RUNNING, pid=6000)
    SimulationRunner._processes[SIM_ID] = _live_process(6000)
    finished = []

    def stop(_cls, simulation_id):
        # Under `npm run dev` the same Ctrl+C arrives again from concurrently
        # while the first handler is still stopping and draining.
        handlers[signal.SIGINT](signal.SIGINT, None)
        handlers[signal.SIGTERM](signal.SIGTERM, None)
        state = SimulationRunner.get_run_state(simulation_id)
        state.runner_status = RunnerStatus.STOPPED
        SimulationRunner._save_run_state(state)
        finished.append(simulation_id)
        return state

    monkeypatch.setattr(SimulationRunner, "stop_simulation", classmethod(stop))

    # The first signal still ends the server once its cleanup is done.
    with pytest.raises(KeyboardInterrupt):
        handlers[signal.SIGTERM](signal.SIGTERM, None)

    assert finished == [SIM_ID]
    assert SimulationRunner._cleanup_in_progress is False
    assert _persisted_run_status(sim_env.root)["runner_status"] == "stopped"


# --------------------------------- STARTING without a pid, simulator alive


def test_pidless_starting_run_is_kept_while_its_simulator_runs(sim_env):
    # A backend that died between spawning the simulator and publishing
    # RUNNING never recorded the pid.
    set_locale("en")
    _write_prepared_simulation(sim_env.root)
    _write_run_state(sim_env.root, RunnerStatus.STARTING, pid=None)
    sim_env.live_commands[31337] = (
        "/usr/bin/python3 /app/backend/scripts/run_parallel_simulation.py "
        f"--config /app/backend/uploads/simulations/{SIM_ID}/simulation_config.json"
    )

    assert SimulationRunner.reconcile_orphaned_run(SIM_ID) is None
    with pytest.raises(ValueError, match="still being run by process 31337"):
        SimulationRunner.start_simulation(SIM_ID, platform="parallel")
    with pytest.raises(ValueError, match="still being run by process 31337"):
        SimulationRunner.stop_simulation(SIM_ID)

    assert sim_env.spawned == []
    assert _persisted_run_status(sim_env.root)["runner_status"] == "starting"

    # Once that simulator is gone the run is reconciled as usual.
    del sim_env.live_commands[31337]
    assert SimulationRunner.reconcile_orphaned_run(SIM_ID) is not None


def test_pidless_starting_run_fails_closed_when_processes_cannot_be_listed(
    sim_env, monkeypatch
):
    _write_prepared_simulation(sim_env.root)
    _write_run_state(sim_env.root, RunnerStatus.STARTING, pid=None)
    monkeypatch.setattr(runner_module, "_process_table", lambda: None)

    assert SimulationRunner.reconcile_orphaned_run(SIM_ID) is None
    with pytest.raises(ValueError):
        SimulationRunner.start_simulation(SIM_ID, platform="parallel")
    assert sim_env.spawned == []


def test_simulator_search_matches_only_this_simulations_simulator(monkeypatch):
    config = f"simulations{os.sep}{SIM_ID}{os.sep}simulation_config.json"
    table = [
        (101, f"python /b/scripts/run_parallel_simulation.py --config /d/{config}"),
        (
            102,
            "python /b/scripts/run_reddit_simulation.py --config "
            f"/d/simulations{os.sep}x{SIM_ID}{os.sep}simulation_config.json",
        ),
        (
            103,
            "python /b/scripts/run_twitter_simulation.py --config "
            f"/d/simulations/{SIM_ID}_2/simulation_config.json",
        ),
        (104, f"tail -f /d/simulations/{SIM_ID}/simulation.log"),
        (105, f"vim /d/{config}"),
        (os.getpid(), f"python run_parallel_simulation.py --config /d/{config}"),
    ]
    monkeypatch.setattr(runner_module, "_process_table", lambda: table)
    assert runner_module._find_simulator_pids(SIM_ID) == [101]

    monkeypatch.setattr(runner_module, "_process_table", lambda: None)
    assert runner_module._find_simulator_pids(SIM_ID) is None


# ------------------------------------------------------------------ startup


def test_startup_reconciles_only_runs_without_a_live_owner(sim_env, monkeypatch):
    from app import create_app

    sim_env.ids.update({"sim_dead", "sim_live", "sim_done", "sim_draining"})
    for simulation_id, runner_status in (
        ("sim_dead", RunnerStatus.STOPPING),
        ("sim_live", RunnerStatus.RUNNING),
        ("sim_done", RunnerStatus.COMPLETED),
        ("sim_draining", RunnerStatus.STOPPING),
    ):
        _write_prepared_simulation(sim_env.root, simulation_id=simulation_id)
        _write_run_state(sim_env.root, runner_status, simulation_id=simulation_id)
    SimulationRunner._processes["sim_live"] = SimpleNamespace(
        pid=DEAD_PID, poll=lambda: None
    )
    monkeypatch.setattr(
        runner_module.ZepGraphMemoryManager,
        "get_updater",
        classmethod(
            lambda _cls, simulation_id: object()
            if simulation_id == "sim_draining"
            else None
        ),
    )
    monkeypatch.setattr(Config, "DEBUG", False)
    monkeypatch.delenv("WERKZEUG_RUN_MAIN", raising=False)

    create_app()

    statuses = {
        simulation_id: _persisted_run_status(sim_env.root, simulation_id)["runner_status"]
        for simulation_id in ("sim_dead", "sim_live", "sim_done", "sim_draining")
    }
    assert statuses == {
        "sim_dead": "stopped",
        "sim_live": "running",
        "sim_done": "completed",
        "sim_draining": "stopping",
    }


# ------------------------------------------------------- process liveness


@pytest.mark.skipif(sys.platform == "win32", reason="uses ps")
def test_simulator_process_alive_reads_the_real_process_table():
    alive = runner_module._simulator_process_alive
    assert alive("pytest", os.getpid()) is True
    assert alive("sim_definitely_not_this_process", os.getpid()) is False
    assert alive("pytest", 2**31 - 1) is False
    for pid in (None, 0, -1, True, "123"):
        assert alive("pytest", pid) is False


def test_unreadable_process_table_fails_closed(monkeypatch):
    monkeypatch.setattr(runner_module, "_process_command_line", lambda _pid: None)
    assert runner_module._simulator_process_alive(SIM_ID, 1234) is True


@pytest.mark.skipif(sys.platform == "win32", reason="uses ps")
def test_process_table_reads_the_real_process_table():
    table = runner_module._process_table()
    assert table is not None
    commands = dict(table)
    assert "pytest" in commands[os.getpid()]
