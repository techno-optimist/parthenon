"""
Thread pools and the process's end, on the public steps.

Python's exit joins every ThreadPoolExecutor worker, daemon or not
(concurrent.futures.thread._python_exit), and a worker runs whatever is still
queued before it looks for the end. A preparation's profile pool, with a
crowd queued behind five model calls, held the backend for minutes after a
SIGTERM, past the platform's grace, until it was killed; a film or a
painting could do the same.

In public mode (enable(), from public.configure) a stop instead:
- cancels the queued work of the pools that asked for it (cancel_on_exit:
  the preparation's profiles, whose loop over them, pools.as_completed,
  stops with Interrupted); what they had begun dies with the process, and
  the next start marks that gathering interrupted
  (SimulationManager.reconcile_interrupted_preparations);
- no longer waits at exit for daemon pool workers: their work ends with the
  process, as it would under the platform's SIGKILL, and each kind of work
  (portraits, films, questions) already notices an interruption when it is
  next read.

release() runs from the SIGTERM/SIGINT cleanup (simulation_runner) and again
at interpreter exit, just before concurrent.futures' own join. On the
owner's own machine (local mode) enable() is never called and nothing here
changes anything.
"""

from __future__ import annotations

import concurrent.futures.thread as _futures_thread  # registers _python_exit first
import logging
import threading
import weakref
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor
from concurrent.futures import as_completed as _as_completed, wait as _wait
from typing import Iterable, Iterator, TypeVar


logger = logging.getLogger('mirofish.pools')

Pool = TypeVar('Pool', bound=ThreadPoolExecutor)

_lock = threading.Lock()
_enabled = False
_registered = False
_stopping = threading.Event()
_cancel_on_exit: 'weakref.WeakSet[ThreadPoolExecutor]' = weakref.WeakSet()


class Interrupted(RuntimeError):
    """Work stopped because the process is stopping (its queued part was cancelled)."""


def enable() -> None:
    """Public mode: a stop cancels the marked pools and exit stops waiting for pool workers."""

    global _enabled, _registered
    with _lock:
        _enabled = True
        if _registered:
            return
        register = getattr(threading, '_register_atexit', None)
        if register is None:
            return
        try:
            # threading's exit callbacks run in reverse: this one before _python_exit.
            register(release)
        except RuntimeError:
            return  # the interpreter is already stopping
        _registered = True


def enabled() -> bool:
    return _enabled


def stopping() -> bool:
    """Whether release() has run: the process is stopping."""

    return _stopping.is_set()


def cancel_on_exit(pool: Pool) -> Pool:
    """Mark a pool whose queued work is cancelled when the process stops; returns it.

    Raises Interrupted, with the pool shut, when the process is already stopping.
    """

    if _enabled and _stopping.is_set():
        pool.shutdown(wait=False, cancel_futures=True)
        raise Interrupted('The process is stopping.')
    _cancel_on_exit.add(pool)
    return pool


def as_completed(futures: Iterable[Future], poll_seconds: float = 0.5) -> Iterator[Future]:
    """concurrent.futures.as_completed for a cancel_on_exit pool: raises Interrupted once the process stops.

    A pool shut with cancel_futures never tells as_completed (or wait) about
    the futures it cancelled, so a loop over them would wait forever. In local
    mode this is as_completed itself.
    """

    if not _enabled:
        yield from _as_completed(futures)
        return
    pending = set(futures)
    while pending:
        if _stopping.is_set():
            raise Interrupted('The process is stopping.')
        done, pending = _wait(pending, timeout=poll_seconds, return_when=FIRST_COMPLETED)
        yield from done


def release() -> int:
    """Stop the marked pools' queued work and let exit leave the pool workers; a no-op in local mode.

    Returns how many worker threads exit will no longer wait for. Safe to call
    more than once (from the signal and again at exit).
    """

    if not _enabled:
        return 0
    _stopping.set()
    for pool in list(_cancel_on_exit):
        try:
            pool.shutdown(wait=False, cancel_futures=True)
        except Exception as error:  # noqa: BLE001 - a stop never fails on one pool
            logger.warning('Could not cancel a pool at stop: %s', error)
    return _leave_daemon_workers()


def _leave_daemon_workers() -> int:
    registry = getattr(_futures_thread, '_threads_queues', None)
    if registry is None:
        return 0
    # submit() registers workers under this lock; a stuck holder is not waited for long.
    guard = getattr(_futures_thread, '_global_shutdown_lock', None)
    held = guard.acquire(timeout=1.0) if guard is not None else False
    try:
        # A non-daemon worker stays: threading joins it anyway, and it needs
        # _python_exit's wake-up to leave an empty queue.
        leaving = [worker for worker in list(registry.keys()) if worker.daemon]
        for worker in leaving:
            registry.pop(worker, None)
    except RuntimeError:
        return 0  # the registry changed under an unheld lock; exit joins as before
    finally:
        if held:
            guard.release()
    if leaving:
        logger.info('Stopping: %d pool worker(s) are not waited for', len(leaving))
    return len(leaving)
