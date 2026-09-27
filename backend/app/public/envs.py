"""
The squares left open after their arguments.

After its last round the simulator keeps its environment open so the
citizens can be questioned live ("the city is awake"). That process holds
about a gigabyte, and a finished run no longer counts as running, so on a
small server a second run started beside it could run the machine out of
memory and take both down.

On the public steps an open environment holds a seat of
PARTHENON_CONCURRENT_RUNS like a running argument does:

- before a new run starts, the least recently used open environments that
  nobody is using are closed until there is a seat (make_room); one that is
  in use (a question in flight, a Chronicle being written) is not, and the
  new run is told the city is full;
- a keeper thread closes an environment nobody has used for
  PARTHENON_IDLE_ENV_MINUTES (20 by default; 0 leaves them open).

A closed environment's citizens still answer, from the record (the
Symposium's memory answers). Nothing here runs on the owner's own machine.
"""

import logging
import threading
import time
from typing import Dict, List, Optional

from . import lineage


logger = logging.getLogger('mirofish.public')

REAPER_INTERVAL_SECONDS = 60.0

_lock = threading.Lock()
_last_used: Dict[str, float] = {}
_in_use: Dict[str, int] = {}
_reaper: Dict[str, object] = {'thread': None, 'idle_seconds': 0.0}


def _runner():
    from ..services.simulation_runner import ACTIVE_RUNNER_STATUSES, SimulationRunner

    return SimulationRunner, ACTIVE_RUNNER_STATUSES


# ------------------------------------------------------------------ use

def touch(simulation_id) -> None:
    """Note that a gathering's environment was just used (a question was put to it)."""

    if lineage.valid_id(simulation_id, 'sim'):
        with _lock:
            _last_used[simulation_id] = time.monotonic()


def enter(simulation_id) -> Optional[str]:
    """A request that may use this environment begins; returns the id to leave() with."""

    if not lineage.valid_id(simulation_id, 'sim'):
        return None
    with _lock:
        _in_use[simulation_id] = _in_use.get(simulation_id, 0) + 1
        _last_used[simulation_id] = time.monotonic()
    return simulation_id


def leave(simulation_id: Optional[str]) -> None:
    if not simulation_id:
        return
    with _lock:
        count = _in_use.get(simulation_id, 0) - 1
        if count > 0:
            _in_use[simulation_id] = count
        else:
            _in_use.pop(simulation_id, None)
        _last_used[simulation_id] = time.monotonic()


# ------------------------------------------------------------------ what is open

def open_environments(exclude: Optional[str] = None) -> List[str]:
    """Gatherings whose run has ended but whose simulator still holds its environment open."""

    runner, active = _runner()
    found = []
    for simulation_id, process in list(runner._processes.items()):
        if simulation_id == exclude:
            continue
        try:
            if process.poll() is not None:
                continue
            state = runner.get_run_state(simulation_id)
        except Exception:  # noqa: BLE001 - an unreadable run is left alone
            continue
        if state is not None and state.runner_status in active:
            continue  # still arguing: counted as a running run
        found.append(simulation_id)
    return found


def _chronicle_in_progress(simulation_id: str) -> bool:
    from ..models.task import TaskManager

    try:
        tasks = TaskManager().list_tasks('report_generate')
    except Exception:  # noqa: BLE001
        return False
    return any(
        task.get('status') in ('pending', 'processing')
        and (task.get('metadata') or {}).get('simulation_id') == simulation_id
        for task in tasks
    )


def busy(simulation_id: str) -> bool:
    """In use: a question in flight, or a Chronicle being written (its Scribe interviews the citizens)."""

    with _lock:
        if _in_use.get(simulation_id, 0) > 0:
            return True
    return _chronicle_in_progress(simulation_id)


def busy_environments(exclude: Optional[str] = None) -> int:
    return sum(1 for simulation_id in open_environments(exclude) if busy(simulation_id))


def _last_use(simulation_id: str) -> float:
    with _lock:
        seen = _last_used.get(simulation_id)
        if seen is None:
            # First seen now: its idle time counts from here.
            seen = _last_used[simulation_id] = time.monotonic()
        return seen


# ------------------------------------------------------------------ closing

def close(simulation_id: str) -> bool:
    """End the simulator of a finished run (its record and result are kept)."""

    runner, _active = _runner()
    try:
        runner.close_finished_run(simulation_id)
    except Exception as error:  # noqa: BLE001 - then the seat stays taken
        logger.warning('Could not close the open square of %s: type=%s', simulation_id, type(error).__name__)
        return False
    with _lock:
        _last_used.pop(simulation_id, None)
    logger.info('Closed the open square of %s (its citizens now answer from the record)', simulation_id)
    return True


def make_room(seats: int, exclude: Optional[str] = None) -> bool:
    """Close idle open environments until fewer than `seats` are open; False when that cannot be done."""

    if seats <= 0:
        return False
    open_now = open_environments(exclude)
    idle = sorted((sid for sid in open_now if not busy(sid)), key=_last_use)
    while len(open_now) >= seats:
        if not idle:
            return False
        simulation_id = idle.pop(0)
        if close(simulation_id):
            open_now.remove(simulation_id)
        else:
            return False
    return True


def close_idle(idle_seconds: float) -> List[str]:
    """Close every open environment nobody has used for idle_seconds; the ids closed."""

    closed = []
    now = time.monotonic()
    for simulation_id in open_environments():
        if busy(simulation_id) or now - _last_use(simulation_id) < idle_seconds:
            continue
        if close(simulation_id):
            closed.append(simulation_id)
    return closed


def start_reaper(idle_minutes: int) -> None:
    """Keep closing environments idle for idle_minutes (0: never). One thread per process."""

    with _lock:
        _reaper['idle_seconds'] = max(0, idle_minutes) * 60.0
        thread = _reaper['thread']
        if idle_minutes <= 0 or (thread is not None and thread.is_alive()):
            return
        thread = threading.Thread(target=_reap_forever, name='parthenon-idle-squares', daemon=True)
        _reaper['thread'] = thread
    thread.start()


def _reap_forever() -> None:
    while True:
        time.sleep(REAPER_INTERVAL_SECONDS)
        idle_seconds = _reaper['idle_seconds']
        if not idle_seconds:
            continue
        try:
            close_idle(idle_seconds)
        except Exception as error:  # noqa: BLE001 - try again next time
            logger.warning('Closing idle squares failed: type=%s', type(error).__name__)
