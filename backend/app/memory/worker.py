"""Background ingestion worker for the local memory backend (spec §4.3, §4.10, §5.3).

``IngestionWorker`` turns queued work in SQLite into graph facts:

- **document windows**: consecutive chunks of one batch (or standalone
  ``graph.add`` episodes) are claimed under a lease and extracted with one
  LLM call each, at most ``LOCAL_MEMORY_LLM_CONCURRENCY`` at a time
  (``extraction.claim_window`` / ``extraction.process_window``);
- **activity enrichment** (``LOCAL_MEMORY_ACTIVITY_MODE=llm``): queued
  simulation activity episodes are grouped and enriched on a single lane,
  within a per-simulation call budget and a pending deadline;
- **batch finalization**: once a batch has no pending, queued or processing
  items, the post passes (entity dedup) run and the batch ends ``succeeded``,
  ``failed`` or ``canceled``.

Everything is driven from the database, so work survives restarts: expired
leases are recovered (requeued, or failed after three claims), and the next
``LocalZep`` on the same file resumes queued, leased and finalizable work.

Threads (all daemon, so a hung LLM call never blocks interpreter exit):

- a **dispatcher** that wakes on :meth:`IngestionWorker.notify` or every
  second, recovers leases, runs the activity deadline sweep (even while the
  activity lane is busy), claims windows, and starts the activity lane and
  the finalizer when they have work;
- a **heartbeat** that renews the leases of in-flight work;
- one short-lived thread per in-flight window, plus at most one activity-lane
  thread and one finalizer thread.

:meth:`IngestionWorker.drain` runs the same steps synchronously in the calling
thread (tests and CLI use), ignoring activity group waits.
"""

from __future__ import annotations

import logging
import os
import socket
import threading
import time
import uuid
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Iterable, Mapping, Sequence

from .activity import (
    ERROR_DEADLINE,
    ActivityGroup,
    ActivityLane,
    ActivityPolicy,
    PromptFact,
    activity_failure_decision,
    activity_llm_calls_used,
    build_activity_messages,
    claim_activity_episodes,
    decide_activity_group,
    expired_activity_candidates,
    finish_activity_episodes,
    load_activity_candidates,
    plan_activity_groups,
    record_activity_llm_call,
    render_activity_window,
    sweep_expired_activity_episodes,
)
from .extraction import (
    FATAL_ERROR_CODES,
    ExtractionError,
    ExtractionLLM,
    Throttle,
    WindowResult,
    claim_window,
    default_llm_factory,
    parse_extraction,
    process_window,
    run_dedup_pass,
)
from .models import json_dumps, json_loads
from .ontology import load_ontology
from .resolution import EpisodeRef, resolve_existing, write_extraction
from .settings import LocalMemorySettings
from .store import MemoryStore
from .textnorm import epoch_to_iso, utcnow_iso

logger = logging.getLogger("mirofish.memory.worker")

__all__ = [
    "ACTIVE_ITEM_STATUSES",
    "ACTIVITY_IN_FLIGHT_GRACE_SECONDS",
    "POISON_PILL_ATTEMPTS",
    "DrainStats",
    "IngestionWorker",
    "RecoveryResult",
    "make_owner_id",
    "owner_is_dead",
]

# A leased episode whose lease expired this many times (counted as claims)
# is failed instead of requeued: it probably crashes the worker.
POISON_PILL_ATTEMPTS = 3
DISPATCH_INTERVAL_SECONDS = 1.0
# A batch whose finalization raised is retried after this many seconds.
FINALIZE_RETRY_SECONDS = 30.0
# Repeated dispatcher errors of one kind are logged at most this often.
ERROR_LOG_INTERVAL_SECONDS = 60.0
ACTIVE_ITEM_STATUSES = ("pending", "queued", "processing")
RUNNING_BATCH_STATUSES = ("queued", "processing")
_IN_CHUNK = 500

_ACTIVE_ITEMS_SQL = ", ".join(f"'{status}'" for status in ACTIVE_ITEM_STATUSES)
_RUNNING_BATCHES_SQL = ", ".join(f"'{status}'" for status in RUNNING_BATCH_STATUSES)

CRASHED_ERROR = {
    "code": "extraction_crashed",
    "message": f"Extraction was interrupted {POISON_PILL_ATTEMPTS} times; this chunk was skipped.",
}
DEGRADED_CODE = "extraction_degraded"

# An activity episode whose enrichment call is still running this many seconds
# after its pending deadline (ACTIVITY_MAX_PENDING_SECONDS, counted from
# queue time) is finished ``degraded``: its rules facts exist, and a hung LLM
# call must not keep ``processed`` false until the updater's deadline. With
# the defaults the hard cap is 300 + 300 s, well below the 1800 s wait.
ACTIVITY_IN_FLIGHT_GRACE_SECONDS = 300.0
IN_FLIGHT_DEADLINE_ERROR = {
    "code": ERROR_DEADLINE,
    "message": "Activity enrichment did not finish in time; rules facts only.",
}


def make_owner_id(start_ts: float | None = None) -> str:
    """Lease owner id ``host:pid:start_ts:nonce`` (unique per worker instance)."""

    started = int(start_ts if start_ts is not None else time.time())
    return f"{socket.gethostname()}:{os.getpid()}:{started}:{uuid.uuid4().hex[:6]}"


def owner_is_dead(owner: str | None) -> bool:
    """True when ``owner`` names a process on this host that no longer exists.

    Owners on other hosts, this process itself, malformed ids and every
    platform without POSIX ``kill(pid, 0)`` semantics answer False: those
    leases are only recovered once they expire.
    """

    if not owner or os.name != "posix":
        return False
    parts = owner.rsplit(":", 3)
    if len(parts) != 4 or parts[0] != socket.gethostname():
        return False
    try:
        pid = int(parts[1])
    except ValueError:
        return False
    if pid <= 0 or pid == os.getpid():
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except OSError:  # e.g. PermissionError: the process exists
        return False
    return False


def _chunks(values: Sequence[Any], size: int = _IN_CHUNK) -> Iterable[Sequence[Any]]:
    for start in range(0, len(values), size):
        yield values[start:start + size]


def _marks(count: int) -> str:
    return ",".join("?" * count)


@dataclass
class RecoveryResult:
    """What one lease-recovery pass did."""

    requeued: list[str] = field(default_factory=list)
    poisoned: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.requeued) + len(self.poisoned)


@dataclass
class DrainStats:
    """Counters returned by :meth:`IngestionWorker.drain`."""

    windows: int = 0
    activity_groups: int = 0
    batches_finalized: int = 0
    recovered: int = 0
    poisoned: int = 0
    timed_out: bool = False
    window_results: list[WindowResult] = field(default_factory=list)


class IngestionWorker:
    """Durable, lease-based ingestion for one :class:`MemoryStore` (spec §4.3).

    ``llm_factory`` builds the OpenAI-compatible client on first use (never at
    construction), so search-only use needs no ``LLM_API_KEY``. ``clock``
    (epoch seconds) drives leases and activity deadlines; ``sleep`` is used
    for LLM retry backoff and throttling. Both are injectable for tests.
    """

    def __init__(
        self,
        store: MemoryStore,
        settings: LocalMemorySettings | None = None,
        llm_factory: Callable[[], Any] | None = None,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
        *,
        owner: str | None = None,
        dispatch_interval: float = DISPATCH_INTERVAL_SECONDS,
    ) -> None:
        self.store = store
        self.settings = settings or LocalMemorySettings()
        self._clock = clock
        self._sleep = sleep
        self.owner = owner or make_owner_id(clock())
        self.dispatch_interval = max(0.01, float(dispatch_interval))
        self.llm = ExtractionLLM(
            llm_factory or default_llm_factory(self.settings),
            self.settings,
            throttle=Throttle(self.settings.llm_min_interval_seconds, sleep=sleep),
            sleep=sleep,
            store=store,
        )
        self.activity_lane = ActivityLane()
        self.activity_policy = ActivityPolicy.from_settings(self.settings)

        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stopping = threading.Event()
        self._started = False
        self._dispatcher: threading.Thread | None = None
        self._heartbeat: threading.Thread | None = None
        self._tasks: set[threading.Thread] = set()
        self._windows_in_flight = 0
        self._activity_busy = False
        self._finalizer_busy = False
        self._leased_episodes: set[str] = set()
        self._finalizing: set[str] = set()
        self._finalize_backoff: dict[str, float] = {}
        self._last_error_log: dict[str, float] = {}

    # -- lifecycle ---------------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._started and not self._stopping.is_set()

    def start(self) -> None:
        """Start the dispatcher and heartbeat threads (idempotent)."""

        with self._lock:
            if self._started or self._stopping.is_set():
                return
            self._started = True
        self._dispatcher = threading.Thread(
            target=self._dispatch_loop, name="memory-dispatcher", daemon=True
        )
        self._heartbeat = threading.Thread(
            target=self._heartbeat_loop, name="memory-heartbeat", daemon=True
        )
        self._dispatcher.start()
        self._heartbeat.start()
        logger.info("Local memory worker started (owner=%s, concurrency=%d)",
                    self.owner, self.settings.llm_concurrency)

    def stop(self, timeout: float = 10.0) -> None:
        """Stop the threads and wait up to ``timeout`` seconds for in-flight work.

        Work still running afterwards finishes (or fails) on its own daemon
        thread; its leases expire and a later worker recovers it.
        """

        self._stopping.set()
        self._wake.set()
        deadline = time.monotonic() + max(0.0, float(timeout))
        threads = [t for t in (self._dispatcher, self._heartbeat) if t is not None]
        with self._lock:
            threads.extend(self._tasks)
        for thread in threads:
            if thread is threading.current_thread():
                continue
            thread.join(max(0.0, deadline - time.monotonic()))
        still = [thread.name for thread in threads if thread.is_alive()]
        if still:
            logger.warning("Local memory worker stopped with work still running: %s", ", ".join(still))
        elif self._started:
            logger.info("Local memory worker stopped (owner=%s)", self.owner)

    def notify(self) -> None:
        """Wake the dispatcher now (new work was queued)."""

        self._wake.set()

    # -- dispatcher --------------------------------------------------------------

    def _dispatch_loop(self) -> None:
        while not self._stopping.is_set():
            # Clear before the tick: a notify() during the tick wakes the next one at once.
            self._wake.clear()
            try:
                self.tick()
            except Exception as error:  # the loop must survive any single failure
                self._log_error("dispatch", error)
            self._wake.wait(self.dispatch_interval)

    def tick(self) -> None:
        """One dispatcher step: recover leases, sweep activity deadlines, claim windows, start lanes.

        The deadline sweep runs on every tick, independent of the activity
        lane: a long lane run or a hung enrichment call must not keep queued
        activity episodes unprocessed past ``ACTIVITY_MAX_PENDING_SECONDS``.
        """

        if self._stopping.is_set() or self.store.closed:
            return
        self.recover_leases()
        try:
            self.sweep_activity_deadlines()
        except Exception as error:  # never block window dispatch on the sweep
            self._log_error("activity deadline sweep", error)
        self._dispatch_windows()
        self._maybe_start_activity_lane()
        self._maybe_start_finalizer()

    def _dispatch_windows(self) -> None:
        while not self._stopping.is_set():
            with self._lock:
                if self._windows_in_flight >= self.settings.llm_concurrency:
                    return
            if not self._has_queued_documents():
                return
            window = claim_window(self.store, self.settings, owner=self.owner, clock=self._clock)
            if window is None:
                return
            self._track(window.episode_uuids)
            with self._lock:
                self._windows_in_flight += 1
            self._spawn(f"memory-window-{window.window_id[:8]}", self._run_window, window,
                        on_start_failure=lambda w=window: self._window_done(w))

    def _run_window(self, window: Any) -> None:
        try:
            result = process_window(self.store, window, self.llm, self.settings, owner=self.owner)
            if result.fatal:
                logger.error("Window %s hit a fatal LLM error (%s)", window.window_id,
                             (result.fatal_error or {}).get("code"))
        except Exception as error:
            self._log_task_error("window", error)
        finally:
            self._window_done(window)
            self.notify()

    def _window_done(self, window: Any) -> None:
        self._untrack(window.episode_uuids)
        with self._lock:
            self._windows_in_flight -= 1

    def _maybe_start_activity_lane(self) -> None:
        with self._lock:
            if self._activity_busy:
                return
        if not self._has_queued_activity():
            return
        with self._lock:
            if self._activity_busy:
                return
            self._activity_busy = True
        self._spawn("memory-activity-lane", self._run_activity_lane_task,
                    on_start_failure=self._activity_lane_done)

    def _run_activity_lane_task(self) -> None:
        try:
            self.run_activity_lane(force=False)
        except Exception as error:
            self._log_task_error("activity lane", error)
        finally:
            self._activity_lane_done()

    def _activity_lane_done(self) -> None:
        with self._lock:
            self._activity_busy = False

    def _maybe_start_finalizer(self) -> None:
        with self._lock:
            if self._finalizer_busy:
                return
        if not self._ready_batch_ids():
            return
        with self._lock:
            if self._finalizer_busy:
                return
            self._finalizer_busy = True
        self._spawn("memory-finalizer", self._run_finalizer_task, on_start_failure=self._finalizer_done)

    def _run_finalizer_task(self) -> None:
        try:
            self.finalize_ready_batches()
        except Exception as error:
            self._log_task_error("finalizer", error)
        finally:
            self._finalizer_done()

    def _finalizer_done(self) -> None:
        with self._lock:
            self._finalizer_busy = False

    def _spawn(self, name: str, target: Callable[..., None], *args: Any,
               on_start_failure: Callable[[], None] | None = None) -> None:
        """Run ``target(*args)`` on a daemon thread tracked for :meth:`stop`."""

        def run() -> None:
            try:
                target(*args)
            finally:
                with self._lock:
                    self._tasks.discard(threading.current_thread())

        thread = threading.Thread(target=run, name=name, daemon=True)
        with self._lock:
            self._tasks.add(thread)
        try:
            thread.start()
        except BaseException:
            # No thread: undo the bookkeeping; any lease just expires later.
            with self._lock:
                self._tasks.discard(thread)
            if on_start_failure is not None:
                on_start_failure()
            raise

    # -- heartbeat ---------------------------------------------------------------

    def _heartbeat_loop(self) -> None:
        interval = max(0.01, float(self.settings.heartbeat_seconds))
        while not self._stopping.wait(interval):
            try:
                self.renew_leases()
            except Exception as error:
                self._log_error("heartbeat", error)

    def renew_leases(self) -> int:
        """Extend the leases of this worker's in-flight episodes and finalizations."""

        with self._lock:
            episodes = sorted(self._leased_episodes)
            batches = sorted(self._finalizing)
        if not episodes and not batches:
            return 0
        lease_until = self._clock() + self.settings.lease_seconds
        renewed = 0
        with self.store.write() as conn:
            for part in _chunks(episodes):
                renewed += conn.execute(
                    f"UPDATE episodes SET lease_until = ? WHERE uuid IN ({_marks(len(part))}) "
                    "AND lease_owner = ? AND extraction_status = 'processing'",
                    (lease_until, *part, self.owner),
                ).rowcount
            for part in _chunks(batches):
                renewed += conn.execute(
                    f"UPDATE batches SET finalize_until = ? WHERE batch_id IN ({_marks(len(part))}) "
                    "AND finalize_owner = ?",
                    (lease_until, *part, self.owner),
                ).rowcount
        return renewed

    def _track(self, uuids: Iterable[str]) -> None:
        with self._lock:
            self._leased_episodes.update(uuids)

    def _untrack(self, uuids: Iterable[str]) -> None:
        with self._lock:
            self._leased_episodes.difference_update(uuids)

    # -- lease recovery ------------------------------------------------------------

    def recover_leases(self) -> RecoveryResult:
        """Requeue episodes whose lease expired; fail them after 3 claims (poison pill).

        A lease counts as expired when ``lease_until`` passed, or at once when
        its owner is a process on this host that no longer exists (for
        example the previous Werkzeug reloader child). Document episodes go
        back to ``queued`` (their batch items too), or become ``failed`` with
        ``extraction_crashed``. Activity episodes already have their rules
        facts, so a poison pill ends them ``degraded`` instead. Episodes this
        worker is still processing are never touched. Finalize leases of
        dead owners are released too.
        """

        result = RecoveryResult()
        now = self._clock()
        with self.store.read() as conn:
            rows = conn.execute(
                "SELECT uuid, lease_owner, lease_until FROM episodes WHERE kind IN ('document', 'activity') "
                "AND extraction_status = 'processing' ORDER BY id"
            ).fetchall()
            finalizers = [
                row["finalize_owner"] for row in conn.execute(
                    "SELECT DISTINCT finalize_owner FROM batches WHERE finalize_owner IS NOT NULL "
                    f"AND status IN ({_RUNNING_BATCHES_SQL})"
                )
            ]
        dead_finalizers = [owner for owner in finalizers if owner != self.owner and owner_is_dead(owner)]
        if dead_finalizers:
            with self.store.write() as conn:
                conn.execute(
                    "UPDATE batches SET finalize_owner = NULL, finalize_until = NULL "
                    f"WHERE finalize_owner IN ({_marks(len(dead_finalizers))})",
                    tuple(dead_finalizers),
                )
        if not rows:
            return result
        with self._lock:
            mine = set(self._leased_episodes)
        verdicts: dict[str | None, bool] = {}

        def expired(owner: str | None, lease_until: float | None) -> bool:
            if lease_until is None or lease_until < now:
                return True
            if owner == self.owner:
                return False
            if owner not in verdicts:
                verdicts[owner] = owner_is_dead(owner)
            return verdicts[owner]

        candidates = [
            row["uuid"] for row in rows
            if not (row["lease_owner"] == self.owner and row["uuid"] in mine)
            and expired(row["lease_owner"], row["lease_until"])
        ]
        if not candidates:
            return result

        now_iso = utcnow_iso()
        crashed = json_dumps(CRASHED_ERROR)
        with self.store.write() as conn:
            for part in _chunks(candidates):
                current = [
                    row for row in conn.execute(
                        f"SELECT uuid, kind, attempts, lease_owner, lease_until FROM episodes "
                        f"WHERE uuid IN ({_marks(len(part))}) AND extraction_status = 'processing'",
                        tuple(part),
                    ).fetchall()
                    if expired(row["lease_owner"], row["lease_until"])
                ]
                requeue = [r["uuid"] for r in current if int(r["attempts"] or 0) < POISON_PILL_ATTEMPTS]
                poisoned_docs = [r["uuid"] for r in current
                                 if int(r["attempts"] or 0) >= POISON_PILL_ATTEMPTS and r["kind"] == "document"]
                poisoned_acts = [r["uuid"] for r in current
                                 if int(r["attempts"] or 0) >= POISON_PILL_ATTEMPTS and r["kind"] == "activity"]
                if requeue:
                    marks = _marks(len(requeue))
                    conn.execute(
                        "UPDATE episodes SET extraction_status = 'queued', lease_owner = NULL, "
                        f"lease_until = NULL WHERE uuid IN ({marks})",
                        tuple(requeue),
                    )
                    conn.execute(
                        f"UPDATE batch_items SET status = 'queued', updated_at = ? WHERE episode_uuid IN ({marks}) "
                        "AND status = 'processing'",
                        (now_iso, *requeue),
                    )
                if poisoned_docs:
                    marks = _marks(len(poisoned_docs))
                    conn.execute(
                        "UPDATE episodes SET processed = 1, extraction_status = 'failed', extraction_error = ?, "
                        f"lease_owner = NULL, lease_until = NULL WHERE uuid IN ({marks})",
                        (crashed, *poisoned_docs),
                    )
                    conn.execute(
                        f"UPDATE batch_items SET status = 'failed', error_json = ?, updated_at = ? "
                        f"WHERE episode_uuid IN ({marks}) AND status IN ({_ACTIVE_ITEMS_SQL})",
                        (crashed, now_iso, *poisoned_docs),
                    )
                if poisoned_acts:
                    finish_activity_episodes(conn, poisoned_acts, status="degraded", error=CRASHED_ERROR)
                result.requeued.extend(requeue)
                result.poisoned.extend(poisoned_docs + poisoned_acts)
        if result.requeued:
            logger.warning("Recovered %d episode(s) whose extraction lease expired", len(result.requeued))
        if result.poisoned:
            logger.error("Gave up on %d episode(s) after %d interrupted extraction attempts",
                         len(result.poisoned), POISON_PILL_ATTEMPTS)
        if result.total:
            self.notify()
        return result

    # -- cheap work probes -----------------------------------------------------------

    def _has_queued_documents(self) -> bool:
        with self.store.read() as conn:
            return conn.execute(
                "SELECT 1 FROM episodes WHERE kind = 'document' AND extraction_status = 'queued' LIMIT 1"
            ).fetchone() is not None

    def _has_queued_activity(self) -> bool:
        with self.store.read() as conn:
            return conn.execute(
                "SELECT 1 FROM episodes WHERE kind = 'activity' AND extraction_status = 'queued' LIMIT 1"
            ).fetchone() is not None

    def _ready_batch_ids(self) -> list[str]:
        now = self._clock()
        with self.store.read() as conn:
            rows = conn.execute(
                f"SELECT batch_id FROM batches b WHERE status IN ({_RUNNING_BATCHES_SQL}) "
                "AND NOT EXISTS (SELECT 1 FROM batch_items i WHERE i.batch_id = b.batch_id "
                f"AND i.status IN ({_ACTIVE_ITEMS_SQL})) "
                "AND (finalize_owner IS NULL OR finalize_until IS NULL OR finalize_until < ? "
                "OR finalize_owner = ?) ORDER BY id",
                (now, self.owner),
            ).fetchall()
        with self._lock:
            busy = set(self._finalizing)
            backoff = dict(self._finalize_backoff)
        return [row["batch_id"] for row in rows
                if row["batch_id"] not in busy and backoff.get(row["batch_id"], 0.0) <= now]

    # -- batch finalization (spec §4.3) ------------------------------------------------

    def finalize_ready_batches(self) -> list[str]:
        """Finalize every batch with no pending, queued or processing items.

        Each batch is claimed with a ``finalize_owner``/``finalize_until``
        lease. Returns the ids of the batches that reached a terminal status.
        """

        finished: list[str] = []
        for batch_id in self._ready_batch_ids():
            if self._stopping.is_set():
                break
            if not self._claim_finalize(batch_id):
                continue
            try:
                status = self.finalize_batch(batch_id)
            except Exception as error:
                with self._lock:
                    self._finalize_backoff[batch_id] = self._clock() + FINALIZE_RETRY_SECONDS
                self._log_task_error(f"finalize batch {batch_id}", error)
                continue
            finally:
                with self._lock:
                    self._finalizing.discard(batch_id)
            if status is not None:
                finished.append(batch_id)
        if finished:
            try:
                self.store.optimize_fts()
            except Exception as error:  # maintenance only
                logger.debug("FTS optimize failed: %s", type(error).__name__)
        return finished

    def _claim_finalize(self, batch_id: str) -> bool:
        now = self._clock()
        with self._lock:
            if batch_id in self._finalizing:
                return False
            self._finalizing.add(batch_id)
        try:
            with self.store.write() as conn:
                claimed = conn.execute(
                    "UPDATE batches SET finalize_owner = ?, finalize_until = ? WHERE batch_id = ? "
                    f"AND status IN ({_RUNNING_BATCHES_SQL}) "
                    "AND (finalize_owner IS NULL OR finalize_until IS NULL OR finalize_until < ? "
                    "OR finalize_owner = ?) "
                    "AND NOT EXISTS (SELECT 1 FROM batch_items i WHERE i.batch_id = batches.batch_id "
                    f"AND i.status IN ({_ACTIVE_ITEMS_SQL}))",
                    (self.owner, now + self.settings.lease_seconds, batch_id, now, self.owner),
                ).rowcount == 1
        except BaseException:
            with self._lock:
                self._finalizing.discard(batch_id)
            raise
        if not claimed:
            with self._lock:
                self._finalizing.discard(batch_id)
        return claimed

    def finalize_batch(self, batch_id: str) -> str | None:
        """Decide the final status of a claimed batch; ``None`` if it is not finished.

        1. Every item canceled: ``canceled``.
        2. A fatal abort recorded on the batch: ``failed``.
        3. More than ``max_failed_fraction`` of the live items failed, or none
           succeeded: ``failed`` (failed items keep their error).
        4. Otherwise the post passes run once, failed items flip to
           ``succeeded`` with ``extraction_degraded`` and the batch succeeds.

        Windows are counted by their items, because succeeded items carry
        no window id.
        """

        with self.store.read(snapshot=True) as conn:
            batch = conn.execute("SELECT * FROM batches WHERE batch_id = ?", (batch_id,)).fetchone()
            counts = _item_counts(conn, batch_id)
            first_failed = conn.execute(
                "SELECT error_json FROM batch_items WHERE batch_id = ? AND status = 'failed' "
                "ORDER BY sequence_index LIMIT 1",
                (batch_id,),
            ).fetchone()
        if batch is None or batch["status"] not in RUNNING_BATCH_STATUSES:
            self._release_finalize(batch_id)
            return None
        if any(counts.get(status, 0) for status in ACTIVE_ITEM_STATUSES):
            self._release_finalize(batch_id)
            return None

        total = sum(counts.values())
        canceled = counts.get("canceled", 0)
        live = total - canceled
        failed = counts.get("failed", 0)
        succeeded = counts.get("succeeded", 0) + counts.get("skipped", 0)
        if live <= 0:
            return self._close_batch(batch_id, "canceled", counts=counts)

        batch_error = json_loads(batch["error_json"], None)
        if isinstance(batch_error, Mapping) and batch_error.get("code") in FATAL_ERROR_CODES:
            return self._close_batch(batch_id, "failed", counts=counts, error=dict(batch_error))

        fraction = failed / live
        if fraction > self.settings.max_failed_fraction or succeeded == 0:
            item_error = json_loads(first_failed["error_json"], None) if first_failed else None
            code = (item_error or {}).get("code") if isinstance(item_error, Mapping) else None
            error = {
                "code": str(code or "extraction_failed"),
                "message": f"{failed} of {live} chunks failed extraction.",
            }
            return self._close_batch(batch_id, "failed", counts=counts, error=error)

        if not batch["post_pass_done"]:
            self._run_post_passes(batch_id)
        return self._close_batch(batch_id, "succeeded", counts=counts)

    def _run_post_passes(self, batch_id: str) -> None:
        try:
            run_dedup_pass(self.store, batch_id, self.llm, self.settings)
        except Exception as error:  # post passes never fail a batch
            logger.warning("Dedup pass for batch %s failed: %s", batch_id, type(error).__name__)

    def _release_finalize(self, batch_id: str) -> None:
        with self.store.write() as conn:
            conn.execute(
                "UPDATE batches SET finalize_owner = NULL, finalize_until = NULL "
                "WHERE batch_id = ? AND finalize_owner = ?",
                (batch_id, self.owner),
            )

    def _close_batch(self, batch_id: str, status: str, *, counts: Mapping[str, int],
                     error: Mapping[str, Any] | None = None) -> str | None:
        now_iso = utcnow_iso()
        degraded = 0
        with self.store.write() as conn:
            row = conn.execute(
                "SELECT status, finalize_owner FROM batches WHERE batch_id = ?", (batch_id,)
            ).fetchone()
            if row is None or row["status"] not in RUNNING_BATCH_STATUSES or row["finalize_owner"] != self.owner:
                return None
            if status == "succeeded":
                degraded = _degrade_failed_items(conn, batch_id, now_iso)
            conn.execute(
                "UPDATE batches SET status = ?, completed_at = ?, updated_at = ?, finalize_owner = NULL, "
                "finalize_until = NULL, post_pass_done = CASE WHEN ? THEN 1 ELSE post_pass_done END, "
                "error_json = COALESCE(error_json, ?) WHERE batch_id = ?",
                (status, now_iso, now_iso, 1 if status == "succeeded" else 0,
                 json_dumps(dict(error)) if error else None, batch_id),
            )
        summary = ", ".join(f"{name}={count}" for name, count in sorted(counts.items()) if count)
        if status == "succeeded" and degraded:
            logger.warning("Batch %s succeeded with %d degraded chunk(s) (%s)", batch_id, degraded, summary)
        elif status == "succeeded":
            logger.info("Batch %s succeeded (%s)", batch_id, summary)
        elif status == "failed":
            logger.error("Batch %s failed (%s; %s)", batch_id, (error or {}).get("code"), summary)
        else:
            logger.info("Batch %s %s (%s)", batch_id, status, summary)
        return status

    # -- activity enrichment lane (spec §5.3) --------------------------------------------

    def sweep_activity_deadlines(self, now: float | None = None) -> list[str]:
        """Finish activity episodes that waited too long (spec §5.3 deadline sweep).

        - ``queued`` episodes older than ``max_pending_seconds`` (since
          ``queued_at``) become ``skipped`` with ``{"code": "deadline"}``;
        - ``processing`` episodes older than ``max_pending_seconds +``
          :data:`ACTIVITY_IN_FLIGHT_GRACE_SECONDS` become ``degraded`` with the
          same code: their enrichment call hangs, and the lane discards its
          result when it returns (the episodes are no longer leased).

        A cheap read probe comes first, so the dispatcher can call this on
        every tick without taking the write lock. Returns the finished uuids.
        """

        now = self._clock() if now is None else float(now)
        max_pending = self.activity_policy.max_pending_seconds
        queued_cutoff = epoch_to_iso(now - max_pending)
        in_flight_cutoff = epoch_to_iso(now - max_pending - ACTIVITY_IN_FLIGHT_GRACE_SECONDS)
        with self.store.read() as conn:
            due = conn.execute(
                "SELECT EXISTS (SELECT 1 FROM episodes WHERE kind = 'activity' AND extraction_status = 'queued' "
                "AND COALESCE(queued_at, created_at) < ?) OR EXISTS (SELECT 1 FROM episodes "
                "WHERE kind = 'activity' AND extraction_status = 'processing' "
                "AND COALESCE(queued_at, created_at) < ?)",
                (queued_cutoff, in_flight_cutoff),
            ).fetchone()[0]
        if not due:
            return []
        with self.store.write() as conn:
            swept = sweep_expired_activity_episodes(conn, now=now, max_pending_seconds=max_pending)
            abandoned = [
                row[0] for row in conn.execute(
                    "SELECT uuid FROM episodes WHERE kind = 'activity' AND extraction_status = 'processing' "
                    "AND COALESCE(queued_at, created_at) < ? ORDER BY id",
                    (in_flight_cutoff,),
                )
            ]
            if abandoned:
                finish_activity_episodes(conn, abandoned, status="degraded", error=IN_FLIGHT_DEADLINE_ERROR)
        if abandoned:
            logger.warning("Activity enrichment still running after the deadline for %d episode(s); "
                           "they keep rules-only facts", len(abandoned))
        return [*swept, *abandoned]

    def run_activity_lane(self, *, force: bool = False) -> int:
        """Sweep expired activity episodes and enrich every ready group, in lane order.

        ``force`` also dispatches partial groups that have not waited
        ``group_wait_seconds`` yet (``drain()``). Returns the number of groups
        handled (including groups finished without an LLM call). Each group
        re-checks the deadline against the clock before its LLM call, so a
        long run cannot enrich episodes that expired while it was busy.
        """

        now = self._clock()
        self.sweep_activity_deadlines(now)
        with self.store.read() as conn:
            candidates = load_activity_candidates(conn)
        if not candidates:
            return 0
        handled = 0
        for group in plan_activity_groups(candidates, self.activity_policy, now=now, force=force):
            if self._stopping.is_set():
                break
            self.process_activity_group(group)
            handled += 1
        return handled

    def process_activity_group(self, group: ActivityGroup) -> str | None:
        """Decide, claim, enrich and finish one group; returns the final episode status.

        Episodes past ``max_pending_seconds`` at this moment are finished
        ``skipped`` (deadline) without an LLM call; the rest of the group
        goes on. Never raises for LLM problems: a failed call ends the group
        ``degraded`` (its rules facts already exist) and a fatal one also
        switches the lane to rules-only.
        """

        now = self._clock()
        expired = {c.uuid for c in expired_activity_candidates(group.episodes, self.activity_policy, now)}
        if expired:
            self.sweep_activity_deadlines(now)
            remaining = tuple(c for c in group.episodes if c.uuid not in expired)
            if not remaining:
                return "skipped"
            group = replace(group, episodes=remaining)

        with self.store.read() as conn:
            used = activity_llm_calls_used(conn, group.simulation_key)
        decision = decide_activity_group(group, lane=self.activity_lane, calls_used=used,
                                         policy=self.activity_policy)
        if not decision.call:
            with self.store.write() as conn:
                finish_activity_episodes(conn, group.uuids, status=decision.status or "skipped",
                                         error=decision.error)
            return decision.status

        lease_until = self._clock() + self.settings.lease_seconds
        with self.store.write() as conn:
            claimed = claim_activity_episodes(conn, group.uuids, owner=self.owner, lease_until=lease_until)
        if not claimed:
            return None
        self._track(claimed)
        try:
            return self._enrich_activity(group, claimed)
        finally:
            self._untrack(claimed)

    def _enrich_activity(self, group: ActivityGroup, claimed: Sequence[str]) -> str | None:
        graph_id = group.graph_id
        with self.store.read(snapshot=True) as conn:
            rows = conn.execute(
                "SELECT uuid, content, reference_time, reference_time_explicit FROM episodes "
                f"WHERE uuid IN ({_marks(len(claimed))}) ORDER BY created_at, id",
                tuple(claimed),
            ).fetchall()
            if not rows:
                return None  # graph deleted: the episodes are gone
            window = render_activity_window(rows)
            ontology = load_ontology(conn, graph_id)
            known: list[tuple[str, str | None]] = []
            account_uuids: list[str] = []
            for name in window.accounts:
                node = resolve_existing(conn, graph_id, name)
                if node is not None and node["uuid"] not in account_uuids:
                    account_uuids.append(node["uuid"])
                    known.append((node["name"], node["entity_type"]))
            known = known[: max(0, self.settings.prompt_known_entities)]
            offered = _activity_existing_facts(conn, graph_id, account_uuids,
                                               limit=self.settings.prompt_existing_facts)
        if not window.has_signal:
            with self.store.write() as conn:
                finish_activity_episodes(conn, self._still_leased(conn, claimed), status="skipped",
                                         error={"code": "no_signal", "message": "no_signal"})
            return "skipped"

        messages = build_activity_messages(
            window, ontology=ontology, known_entities=known, existing_facts=[fact for fact, _ in offered],
            max_entities=self.settings.max_entities_per_window,
            max_relations=self.settings.max_relations_per_window,
        )
        prompt_chars = sum(len(message["content"]) for message in messages)
        try:
            raw = self.llm.chat_json(messages, temperature=0.1, max_tokens=self.settings.llm_max_tokens,
                                     max_attempts=2)
            try:
                extraction = parse_extraction(raw, max_entities=self.settings.max_entities_per_window,
                                              max_relations=self.settings.max_relations_per_window)
            except ValueError as error:  # LLMResponseError
                raise ExtractionError("llm_bad_output", str(error) or "LLM returned unusable JSON") from None
        except Exception as error:
            info = error.error if isinstance(error, ExtractionError) else {
                "code": "extraction_error", "message": type(error).__name__,
            }
            failure = activity_failure_decision(info, lane=self.activity_lane)
            with self.store.write() as conn:
                record_activity_llm_call(conn, sim_key=group.simulation_key, graph_id=graph_id,
                                         prompt_chars=prompt_chars, failed=True)
                finish_activity_episodes(conn, self._still_leased(conn, claimed),
                                         status=failure.status or "degraded", error=failure.error)
            logger.warning("Activity enrichment failed for %d episode(s) of graph %s (%s)",
                           len(claimed), graph_id, info.get("code"))
            return failure.status

        output_chars = len(json_dumps(raw)) if isinstance(raw, (dict, list)) else 0
        chunk_of = {episode_uuid: number for number, episode_uuid in window.markers.items()}
        fact_map = {fact.short_id: edge_uuid for fact, edge_uuid in offered}
        now_iso = utcnow_iso()
        try:
            with self.store.write() as conn:
                record_activity_llm_call(conn, sim_key=group.simulation_key, graph_id=graph_id,
                                         prompt_chars=prompt_chars, output_chars=output_chars)
                owned = set(self._still_leased(conn, claimed))
                if not owned:
                    return None
                episodes = [
                    EpisodeRef(
                        uuid=row["uuid"],
                        content=row["content"],
                        reference_time=row["reference_time"],
                        reference_time_explicit=bool(row["reference_time_explicit"]),
                        chunk=chunk_of.get(row["uuid"]),
                    )
                    for row in rows if row["uuid"] in owned
                ]
                stats = write_extraction(
                    conn, graph_id,
                    entities=extraction.entities,
                    relations=extraction.relations,
                    invalidated_facts=extraction.invalidated_facts,
                    episodes=episodes,
                    ontology=ontology,
                    fact_map=fact_map,
                    strict=False,
                    summary_cap=self.settings.summary_max_chars,
                    now=now_iso,
                )
                finish_activity_episodes(conn, sorted(owned), status="succeeded")
        except Exception as error:
            if getattr(error, "status_code", None) == 503:
                raise  # busy store: lease recovery requeues the group
            logger.warning("Activity enrichment commit failed for graph %s: %s", graph_id,
                           type(error).__name__)
            with self.store.write() as conn:
                finish_activity_episodes(conn, self._still_leased(conn, claimed), status="degraded",
                                         error={"code": "extraction_error", "message": type(error).__name__})
            return "degraded"
        logger.info(
            "Activity enrichment for graph %s: %d episode(s); nodes +%d/~%d, edges +%d/~%d, invalidated %d",
            graph_id, len(owned), stats.nodes_created, stats.nodes_updated, stats.edges_created,
            stats.edges_merged, stats.edges_invalidated,
        )
        return "succeeded"

    def _still_leased(self, conn: Any, uuids: Sequence[str]) -> list[str]:
        """The episodes of ``uuids`` still ``processing`` under this worker's lease."""

        if not uuids:
            return []
        found = {
            row["uuid"] for row in conn.execute(
                f"SELECT uuid FROM episodes WHERE uuid IN ({_marks(len(uuids))}) "
                "AND extraction_status = 'processing' AND lease_owner = ?",
                (*uuids, self.owner),
            )
        }
        return [uuid_ for uuid_ in uuids if uuid_ in found]

    # -- synchronous helpers -------------------------------------------------------------

    def drain(self, max_seconds: float | None = None) -> DrainStats:
        """Process all eligible work synchronously in the calling thread.

        Runs lease recovery, document windows (one at a time), every activity
        group (ignoring group waits) and batch finalization until nothing is
        left to do, or ``max_seconds`` of wall time passed. Work leased by
        another live owner is left alone.
        """

        stats = DrainStats()
        started = time.monotonic()
        while True:
            if max_seconds is not None and time.monotonic() - started > max_seconds:
                stats.timed_out = True
                break
            progressed = False
            recovery = self.recover_leases()
            stats.recovered += len(recovery.requeued)
            stats.poisoned += len(recovery.poisoned)
            progressed |= recovery.total > 0

            window = claim_window(self.store, self.settings, owner=self.owner, clock=self._clock)
            if window is not None:
                self._track(window.episode_uuids)
                try:
                    stats.window_results.append(
                        process_window(self.store, window, self.llm, self.settings, owner=self.owner)
                    )
                finally:
                    self._untrack(window.episode_uuids)
                stats.windows += 1
                continue

            groups = self.run_activity_lane(force=True)
            stats.activity_groups += groups
            progressed |= groups > 0

            finalized = self.finalize_ready_batches()
            stats.batches_finalized += len(finalized)
            progressed |= bool(finalized)
            if not progressed:
                break
        return stats

    def snapshot(self) -> dict[str, Any]:
        """Counts for diagnostics: non-terminal episodes, running batches, lanes."""

        with self.store.read(snapshot=True) as conn:
            episodes = {
                f"{row['kind']}:{row['extraction_status']}": int(row["n"])
                for row in conn.execute(
                    "SELECT kind, extraction_status, count(*) AS n FROM episodes "
                    "WHERE extraction_status IN ('pending', 'queued', 'processing') "
                    "GROUP BY kind, extraction_status"
                )
            }
            batches = {
                row["status"]: int(row["n"])
                for row in conn.execute(
                    "SELECT status, count(*) AS n FROM batches WHERE status IN ('draft', 'queued', 'processing') "
                    "GROUP BY status"
                )
            }
        with self._lock:
            return {
                "owner": self.owner,
                "running": self.running,
                "windows_in_flight": self._windows_in_flight,
                "activity_lane_busy": self._activity_busy,
                "finalizer_busy": self._finalizer_busy,
                "activity_lane_enabled": self.activity_lane.enabled,
                "leased_episodes": len(self._leased_episodes),
                "episodes": episodes,
                "batches": batches,
                "llm_calls": self.llm.calls,
                "llm_failures": self.llm.failures,
            }

    # -- logging -------------------------------------------------------------------------

    def _log_error(self, where: str, error: BaseException) -> None:
        if self.store.closed or self._stopping.is_set():
            logger.debug("Local memory %s stopped: %s", where, type(error).__name__)
            return
        key = f"{where}:{type(error).__name__}"
        now = time.monotonic()
        with self._lock:
            last = self._last_error_log.get(key)
            if last is not None and now - last < ERROR_LOG_INTERVAL_SECONDS:
                return
            self._last_error_log[key] = now
        logger.warning("Local memory %s error: %s", where, type(error).__name__,
                       exc_info=logger.isEnabledFor(logging.DEBUG))

    def _log_task_error(self, what: str, error: BaseException) -> None:
        if self.store.closed or self._stopping.is_set():
            logger.debug("Local memory %s ended during shutdown: %s", what, type(error).__name__)
            return
        logger.warning("Local memory %s failed: %s", what, type(error).__name__,
                       exc_info=logger.isEnabledFor(logging.DEBUG))


# ---------------------------------------------------------------------------
# SQL helpers
# ---------------------------------------------------------------------------


def _item_counts(conn: Any, batch_id: str) -> dict[str, int]:
    return {
        row["status"]: int(row["n"])
        for row in conn.execute(
            "SELECT status, count(*) AS n FROM batch_items WHERE batch_id = ? GROUP BY status",
            (batch_id,),
        )
    }


def _degrade_failed_items(conn: Any, batch_id: str, now_iso: str) -> int:
    """Flip a succeeding batch's failed items to ``succeeded`` + ``extraction_degraded``."""

    rows = conn.execute(
        "SELECT item_id, episode_uuid, error_json FROM batch_items WHERE batch_id = ? AND status = 'failed'",
        (batch_id,),
    ).fetchall()
    for row in rows:
        original = json_loads(row["error_json"], None)
        message = original.get("message") if isinstance(original, Mapping) else None
        payload = {"code": DEGRADED_CODE, "message": str(message or "Extraction failed for this chunk.")}
        conn.execute(
            "UPDATE batch_items SET status = 'succeeded', error_json = ?, updated_at = ? WHERE item_id = ?",
            (json_dumps(payload), now_iso, row["item_id"]),
        )
        conn.execute(
            "UPDATE episodes SET extraction_status = 'degraded', processed = 1 "
            "WHERE uuid = ? AND extraction_status = 'failed'",
            (row["episode_uuid"],),
        )
    return len(rows)


def _activity_existing_facts(conn: Any, graph_id: str, node_uuids: Sequence[str], *,
                             limit: int) -> list[tuple[PromptFact, str]]:
    """Active, LLM-extracted facts of the accounts, newest first, with their edge uuids.

    Rules edges (likes, follows, ...) are events, not opinions, so they are
    not offered for invalidation.
    """

    if limit <= 0 or not node_uuids:
        return []
    nodes = list(dict.fromkeys(node_uuids))[:_IN_CHUNK]
    marks = _marks(len(nodes))
    rows = conn.execute(
        "SELECT e.uuid, e.name, e.fact, e.valid_at, s.name AS source_name, t.name AS target_name "
        "FROM edges e JOIN nodes s ON s.uuid = e.source_node_uuid "
        "JOIN nodes t ON t.uuid = e.target_node_uuid "
        "WHERE e.graph_id = ? AND e.origin != 'rules' AND e.invalid_at IS NULL AND e.expired_at IS NULL "
        f"AND (e.source_node_uuid IN ({marks}) OR e.target_node_uuid IN ({marks})) "
        "ORDER BY e.created_at DESC, e.id DESC LIMIT ?",
        (graph_id, *nodes, *nodes, int(limit)),
    ).fetchall()
    return [
        (PromptFact(f"F{index}", row["source_name"], row["name"], row["target_name"], row["fact"],
                    row["valid_at"]), row["uuid"])
        for index, row in enumerate(rows, start=1)
    ]
