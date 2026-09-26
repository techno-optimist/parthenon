"""``IngestionWorker``: windows, retries, failures, leases, finalization, activity lane (spec §4.3, §4.9, §5.3)."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import time
from dataclasses import replace

import pytest
from zep_cloud import BatchAddItem

from app.config import Config
from app.memory import LocalZep, clear_local_memory_clients, register_local_memory_client
from app.memory.extraction import DEDUP_SYSTEM_PROMPT, claim_window
from app.memory.models import json_loads
from app.memory.worker import POISON_PILL_ATTEMPTS, owner_is_dead
from app.services.graph_builder import BatchSubmission, GraphBuilderService
from app.utils.llm_client import LLMResponseError

from conftest import text_block, works_for_extractor  # tests/local_memory/conftest.py


T0 = 1_800_000_000.0
ACTIVITY_METADATA = {"source": "mirofish_simulation", "simulation_id": "sim-1", "platform": "twitter"}


def _post(text: str, agent: str = "Alice Chen", minute: int = 0) -> str:
    return f"[2026-05-10T09:{minute:02d}:00+00:00] [twitter round 1] {agent}: 发布了一条帖子：「{text}」"


class FakeClock:
    def __init__(self, start: float = T0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def sleeps() -> list[float]:
    return []


@pytest.fixture
def worker_settings(memory_settings):
    # One chunk per window: every test text is ~25-35 characters.
    return replace(memory_settings, window_chars=40)


@pytest.fixture
def zep(memory_db_path, monkeypatch, fake_llm, worker_settings, clock, sleeps):
    monkeypatch.setattr(Config, "MEMORY_BACKEND", "local", raising=False)
    monkeypatch.setattr(Config, "LOCAL_MEMORY_DB_PATH", str(memory_db_path), raising=False)
    client = LocalZep(db_path=memory_db_path, settings=worker_settings, llm_client_factory=lambda: fake_llm,
                      autostart_worker=False, clock=clock, sleep=sleeps.append)
    register_local_memory_client(client)
    yield client
    clear_local_memory_clients()


def _make(memory_db_path, settings, factory, **kwargs) -> LocalZep:
    return LocalZep(db_path=memory_db_path, settings=settings, llm_client_factory=factory,
                    autostart_worker=kwargs.pop("autostart_worker", False),
                    sleep=kwargs.pop("sleep", lambda _s: None), **kwargs)


def _batch(zep: LocalZep, texts: list[str], graph_id: str = "g1") -> tuple[str, list]:
    try:
        zep.graph.get(graph_id)
    except Exception:
        zep.graph.create(graph_id=graph_id)
    batch = zep.batch.create(metadata={"graph_id": graph_id})
    details = zep.batch.add(batch.batch_id, items=[
        BatchAddItem(type="graph_episode", graph_id=graph_id, data=text, data_type="text") for text in texts
    ])
    zep.batch.process(batch.batch_id)
    return batch.batch_id, details


PEOPLE = ["Alice", "Bruno", "Chandra", "Dmitri", "Esther", "Farouk"]
ORGS = ["Acme", "Globex", "Initech", "Umbrella", "Hooli", "Vandelay"]


def _texts(count: int) -> list[str]:
    """Distinct names, so the dedup pass finds no candidates (and makes no LLM call)."""

    return [f"{PEOPLE[i]} works for {ORGS[i]}." for i in range(count)]


def _items(zep: LocalZep, batch_id: str) -> list:
    return zep.batch.list_items(batch_id).items


def _episode_row(zep: LocalZep, episode_uuid: str):
    with zep.store.read() as conn:
        return conn.execute("SELECT * FROM episodes WHERE uuid = ?", (episode_uuid,)).fetchone()


def _fail_chunks(*numbers: int):
    """FakeLLM script: bad output for the given [chunk N] windows, else the default extractor."""

    def script(messages):
        text = text_block(messages)
        if any(f"[chunk {n}]" in text for n in numbers):
            return LLMResponseError("LLM returned invalid JSON")
        return works_for_extractor(messages)

    return script


def _builder_wait(zep: LocalZep, batch_id: str, count: int) -> list[str]:
    builder = GraphBuilderService()
    assert builder.client is zep
    return builder._wait_for_batch(BatchSubmission(batch_id, "op", [], count), timeout=5)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_drain_completes_a_batch(zep, fake_llm):
    batch_id, details = _batch(zep, _texts(4))
    stats = zep.worker.drain()
    assert stats.windows == 4 and stats.batches_finalized == 1 and not stats.timed_out
    assert fake_llm.call_count == 4
    summary = zep.batch.get(batch_id)
    assert summary.status == "succeeded" and summary.progress.percent_complete == 100.0
    assert _builder_wait(zep, batch_id, 4) == [d.episode_uuid for d in details]
    assert len(zep.graph.edge.get_by_graph_id("g1")) == 4
    with zep.store.read() as conn:
        usage = conn.execute("SELECT llm_calls FROM usage WHERE scope_kind = 'graph' AND scope_id = 'g1'").fetchone()
    assert usage["llm_calls"] == 4


def test_windows_pack_consecutive_chunks_up_to_the_character_cap(zep, fake_llm, worker_settings, monkeypatch):
    monkeypatch.setattr(zep.worker, "settings", replace(worker_settings, window_chars=60))
    batch_id, _ = _batch(zep, _texts(5))
    stats = zep.worker.drain()
    assert stats.windows == 3  # 2 + 2 + 1 chunks of ~23 characters
    assert "[chunk 0]" in text_block(fake_llm.calls[0]["messages"])
    assert "[chunk 1]" in text_block(fake_llm.calls[0]["messages"])
    assert zep.batch.get(batch_id).status == "succeeded"


# ---------------------------------------------------------------------------
# LLM retry policy (§4.9)
# ---------------------------------------------------------------------------


def test_rate_limit_retry_after_is_honoured(zep, fake_llm, openai_error, sleeps):
    fake_llm.script = [openai_error(429, headers={"Retry-After": "7"})]
    batch_id, _ = _batch(zep, _texts(1))
    zep.worker.drain()
    assert sleeps == [7.0]
    assert zep.batch.get(batch_id).status == "succeeded"


def test_rate_limit_without_header_backs_off_exponentially(zep, fake_llm, openai_error, sleeps):
    fake_llm.script = [openai_error(429), openai_error(429)]
    batch_id, _ = _batch(zep, _texts(1))
    zep.worker.drain()
    assert sleeps == [10.0, 20.0]
    assert zep.batch.get(batch_id).status == "succeeded"


def test_server_errors_back_off_5_then_15(zep, fake_llm, openai_error, sleeps):
    fake_llm.script = [openai_error(502), openai_error(503)]
    batch_id, _ = _batch(zep, _texts(1))
    zep.worker.drain()
    assert sleeps == [5.0, 15.0]
    assert zep.batch.get(batch_id).status == "succeeded"


def test_exhausted_retries_fail_the_window(zep, fake_llm, openai_error):
    fake_llm.script = [openai_error(500)] * 3
    batch_id, _ = _batch(zep, _texts(1))
    zep.worker.drain()
    assert zep.batch.get(batch_id).status == "failed"
    error = _items(zep, batch_id)[0].error
    assert error["code"] == "llm_unavailable"
    assert "window_id" not in error


def test_bad_output_splits_the_window_and_then_succeeds(zep, fake_llm, worker_settings, monkeypatch):
    monkeypatch.setattr(zep.worker, "settings", replace(worker_settings, window_chars=4000))
    fake_llm.script = [LLMResponseError("truncated JSON")]
    batch_id, _ = _batch(zep, _texts(2))
    stats = zep.worker.drain()
    assert stats.windows == 1 and stats.window_results[0].splits == 1
    assert fake_llm.call_count == 3
    assert zep.batch.get(batch_id).status == "succeeded"
    assert {item.status for item in _items(zep, batch_id)} == {"succeeded"}


# ---------------------------------------------------------------------------
# Failed windows and finalization (§4.3, D7)
# ---------------------------------------------------------------------------


def test_one_failed_window_of_four_degrades_but_succeeds(zep, fake_llm):
    fake_llm.script = _fail_chunks(1)
    batch_id, details = _batch(zep, _texts(4))
    zep.worker.drain()
    summary = zep.batch.get(batch_id)
    assert summary.status == "succeeded"
    items = _items(zep, batch_id)
    assert [item.status for item in items] == ["succeeded"] * 4
    assert items[1].error == {"code": "extraction_degraded", "message": "LLM returned invalid JSON"}
    assert all(item.error is None for i, item in enumerate(items) if i != 1)
    assert _episode_row(zep, details[1].episode_uuid)["extraction_status"] == "degraded"
    # The builder's validation accepts the degraded batch.
    assert len(_builder_wait(zep, batch_id, 4)) == 4


def test_three_failed_windows_of_four_fail_the_batch(zep, fake_llm):
    fake_llm.script = _fail_chunks(0, 1, 2)
    batch_id, _ = _batch(zep, _texts(4))
    zep.worker.drain()
    assert zep.batch.get(batch_id).status == "failed"
    with pytest.raises(RuntimeError) as caught:
        _builder_wait(zep, batch_id, 4)
    message = str(caught.value)
    assert f"batch {batch_id} ended as failed" in message
    assert "failed_items=3" in message and "llm_bad_output" in message
    assert "window_id" not in message


def test_a_batch_where_nothing_succeeded_fails_even_under_the_threshold(zep, fake_llm, worker_settings,
                                                                          monkeypatch):
    monkeypatch.setattr(zep.worker, "settings", replace(worker_settings, max_failed_fraction=1.0))
    fake_llm.script = _fail_chunks(0)
    batch_id, _ = _batch(zep, _texts(1))
    zep.worker.drain()
    assert zep.batch.get(batch_id).status == "failed"


@pytest.mark.parametrize(
    "status, body, code",
    [
        (401, None, "llm_auth"),
        (403, None, "llm_auth"),
        (429, {"error": {"code": "openrouter_daily_limit", "message": "quota"}}, "llm_quota_exhausted"),
        (503, {"error": {"code": "grok_not_signed_in", "message": "sign in"}}, "llm_auth"),
    ],
)
def test_fatal_llm_errors_abort_the_batch_at_once(zep, fake_llm, openai_error, status, body, code):
    fake_llm.script = [openai_error(status, body=body)]
    batch_id, _ = _batch(zep, _texts(4))
    zep.worker.drain()
    assert fake_llm.call_count == 1
    summary = zep.batch.get(batch_id)
    assert summary.status == "failed"
    items = _items(zep, batch_id)
    assert [item.status for item in items] == ["failed"] * 4
    assert {item.error["code"] for item in items} == {code}
    with pytest.raises(RuntimeError) as caught:
        _builder_wait(zep, batch_id, 4)
    assert code in str(caught.value) and "failed_items=4" in str(caught.value)


def test_missing_llm_key_is_fatal(memory_db_path, worker_settings):
    def factory():
        raise ValueError("LLM_API_KEY 未配置")

    zep = _make(memory_db_path, worker_settings, factory)
    try:
        batch_id, _ = _batch(zep, _texts(2))
        zep.worker.drain()
        assert zep.batch.get(batch_id).status == "failed"
        items = _items(zep, batch_id)
        assert {item.error["code"] for item in items} == {"llm_not_configured"}
        assert items[0].error["message"] == "LLM_API_KEY is not configured."
    finally:
        zep.close()


def test_graph_deleted_mid_window_discards_the_result_and_cancels(zep, fake_llm, worker_settings, monkeypatch):
    monkeypatch.setattr(zep.worker, "settings", replace(worker_settings, window_chars=4000))

    def delete_during_call(messages):
        zep.graph.delete("g1")
        return works_for_extractor(messages)

    fake_llm.script = [delete_during_call]
    batch_id, _ = _batch(zep, _texts(2))
    stats = zep.worker.drain()
    assert stats.window_results[0].status == "canceled"
    assert zep.batch.get(batch_id).status == "canceled"
    assert {item.status for item in _items(zep, batch_id)} == {"canceled"}
    with zep.store.read() as conn:
        assert conn.execute("SELECT count(*) FROM nodes").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM edges").fetchone()[0] == 0


def test_standalone_episode_with_fatal_error_is_processed_as_failed(zep, fake_llm, openai_error):
    zep.graph.create(graph_id="g1")
    fake_llm.script = [openai_error(401)]
    episode = zep.graph.add(graph_id="g1", type="text", data="Alice works for Acme.")
    zep.worker.drain()
    done = zep.graph.episode.get(episode.uuid_)
    assert done.processed is True and done.extraction_status == "failed"
    assert done.extraction_error["code"] == "llm_auth"


# ---------------------------------------------------------------------------
# Leases (§4.3)
# ---------------------------------------------------------------------------


def test_expired_lease_is_requeued_and_then_completes(zep, clock, worker_settings):
    batch_id, details = _batch(zep, _texts(1))
    window = claim_window(zep.store, worker_settings, owner="crashed-host:1:1", clock=clock)
    assert window is not None
    assert zep.batch.get(batch_id).status == "processing"

    # Not expired yet: nothing is recovered and drain leaves the leased window alone.
    assert zep.worker.recover_leases().total == 0
    assert zep.worker.drain().windows == 0
    assert _items(zep, batch_id)[0].status == "processing"

    clock.advance(worker_settings.lease_seconds + 1)
    recovery = zep.worker.recover_leases()
    assert recovery.requeued == [details[0].episode_uuid]
    assert _items(zep, batch_id)[0].status == "queued"
    row = _episode_row(zep, details[0].episode_uuid)
    assert row["extraction_status"] == "queued" and row["lease_owner"] is None and row["attempts"] == 1

    zep.worker.drain()
    assert zep.batch.get(batch_id).status == "succeeded"


def _dead_pid() -> int:
    process = subprocess.Popen([sys.executable, "-c", "pass"])
    process.wait()
    return process.pid


@pytest.mark.skipif(os.name != "posix", reason="POSIX process probing")
def test_leases_of_dead_local_processes_are_recovered_at_once(zep, clock, worker_settings):
    batch_id, details = _batch(zep, _texts(3))
    host = socket.gethostname()
    owners = {
        "dead": f"{host}:{_dead_pid()}:1:dead00",
        "alive": f"{host}:{os.getppid()}:1:live00",
        "remote": f"another-host.example:{_dead_pid()}:1:far000",
    }
    with zep.store.write() as conn:
        for (label, owner), detail in zip(owners.items(), details):
            conn.execute(
                "UPDATE episodes SET extraction_status = 'processing', lease_owner = ?, lease_until = ?, "
                "attempts = 1 WHERE uuid = ?",
                (owner, clock() + 600, detail.episode_uuid),
            )
            conn.execute("UPDATE batch_items SET status = 'processing' WHERE episode_uuid = ?",
                         (detail.episode_uuid,))
        conn.execute("UPDATE batches SET finalize_owner = ?, finalize_until = ? WHERE batch_id = ?",
                     (owners["dead"], clock() + 600, batch_id))
    assert owner_is_dead(owners["dead"]) and not owner_is_dead(owners["alive"])
    assert not owner_is_dead(owners["remote"]) and not owner_is_dead(zep.worker.owner)
    assert not owner_is_dead("garbage") and not owner_is_dead(None)

    recovery = zep.worker.recover_leases()
    assert recovery.requeued == [details[0].episode_uuid]
    with zep.store.read() as conn:
        row = conn.execute("SELECT finalize_owner FROM batches WHERE batch_id = ?", (batch_id,)).fetchone()
    assert row["finalize_owner"] is None
    assert [item.status for item in _items(zep, batch_id)] == ["queued", "processing", "processing"]


def test_poison_pill_after_three_interrupted_claims(zep, clock, worker_settings):
    batch_id, details = _batch(zep, _texts(1))
    for attempt in range(1, POISON_PILL_ATTEMPTS + 1):
        assert claim_window(zep.store, worker_settings, owner=f"crashed:{attempt}", clock=clock) is not None
        clock.advance(worker_settings.lease_seconds + 1)
        recovery = zep.worker.recover_leases()
        if attempt < POISON_PILL_ATTEMPTS:
            assert recovery.requeued == [details[0].episode_uuid]
        else:
            assert recovery.poisoned == [details[0].episode_uuid]

    row = _episode_row(zep, details[0].episode_uuid)
    assert row["extraction_status"] == "failed" and row["processed"] == 1
    assert json_loads(row["extraction_error"])["code"] == "extraction_crashed"
    zep.worker.drain()
    assert zep.batch.get(batch_id).status == "failed"
    assert _items(zep, batch_id)[0].error["code"] == "extraction_crashed"


def test_expired_finalize_lease_is_taken_over(zep, clock, worker_settings):
    batch_id, _ = _batch(zep, _texts(1))
    window = claim_window(zep.store, worker_settings, owner=zep.worker.owner, clock=clock)
    from app.memory.extraction import process_window

    process_window(zep.store, window, zep.worker.llm, worker_settings)
    with zep.store.write() as conn:
        conn.execute("UPDATE batches SET finalize_owner = 'crashed', finalize_until = ? WHERE batch_id = ?",
                     (clock() + 60, batch_id))
    assert zep.worker.finalize_ready_batches() == []
    clock.advance(61)
    assert zep.worker.finalize_ready_batches() == [batch_id]
    assert zep.batch.get(batch_id).status == "succeeded"


# ---------------------------------------------------------------------------
# Dedup post pass (§4.8)
# ---------------------------------------------------------------------------


def _dedup_script(answer):
    def script(messages):
        if messages[0]["content"] == DEDUP_SYSTEM_PROMPT:
            return answer
        return works_for_extractor(messages)

    return script


def test_dedup_pass_merges_confirmed_names_and_repoints_edges(zep, fake_llm):
    fake_llm.script = _dedup_script({"decisions": [{"pair": "P1", "same_entity": True}]})
    batch_id, _ = _batch(zep, ["Alice works for Acme.", "Alice Chen works for Beta."])
    zep.worker.drain()
    assert zep.batch.get(batch_id).status == "succeeded"
    dedup_calls = [c for c in fake_llm.calls if c["messages"][0]["content"] == DEDUP_SYSTEM_PROMPT]
    assert len(dedup_calls) == 1
    assert '"Alice"' in dedup_calls[0]["messages"][1]["content"]
    names = {node.name: node.uuid_ for node in zep.graph.node.get_by_graph_id("g1")}
    alices = [name for name in names if name.startswith("Alice")]
    assert len(alices) == 1
    survivor = names[alices[0]]
    edges = zep.graph.edge.get_by_graph_id("g1")
    assert len(edges) == 2 and {edge.source_node_uuid for edge in edges} == {survivor}
    with zep.store.read() as conn:
        assert conn.execute("SELECT post_pass_done FROM batches WHERE batch_id = ?",
                            (batch_id,)).fetchone()[0] == 1


def test_dedup_pass_failure_is_not_fatal(zep, fake_llm, openai_error, sleeps):
    fake_llm.script = _dedup_script(openai_error(500))
    batch_id, _ = _batch(zep, ["Alice works for Acme.", "Alice Chen works for Beta."])
    zep.worker.drain()
    assert zep.batch.get(batch_id).status == "succeeded"
    assert {"Alice", "Alice Chen"} <= {node.name for node in zep.graph.node.get_by_graph_id("g1")}


def test_dedup_pass_can_be_turned_off(zep, fake_llm, worker_settings, monkeypatch):
    monkeypatch.setattr(zep.worker, "settings", replace(worker_settings, dedup_pass="off"))
    batch_id, _ = _batch(zep, ["Alice works for Acme.", "Alice Chen works for Beta."])
    zep.worker.drain()
    assert zep.batch.get(batch_id).status == "succeeded"
    assert fake_llm.call_count == 2


# ---------------------------------------------------------------------------
# Activity enrichment lane (§5.3)
# ---------------------------------------------------------------------------


@pytest.fixture
def llm_mode(zep, worker_settings, monkeypatch):
    settings = replace(worker_settings, activity_mode="llm", activity_group_size=2,
                       activity_group_wait_seconds=15.0, activity_max_pending_seconds=300.0)
    monkeypatch.setattr(zep, "settings", settings)
    monkeypatch.setattr(zep.worker, "settings", settings)
    from app.memory.activity import ActivityPolicy

    monkeypatch.setattr(zep.worker, "activity_policy", ActivityPolicy.from_settings(settings))
    zep.graph.create(graph_id="g1")
    return zep


def _add_activity(zep, text, **metadata):
    return zep.graph.add(graph_id="g1", type="text", data=text, created_at="2026-05-10T09:00:00+00:00",
                         metadata={**ACTIVITY_METADATA, **metadata},
                         source_description="MiroFish simulation activity batch")


STANCE = {
    "entities": [{"name": "Alice Chen", "type": "Entity"}, {"name": "智巡平台", "type": "Entity"}],
    "relations": [{"source": "Alice Chen", "target": "智巡平台", "type": "SUPPORTS",
                   "fact": "Alice Chen支持智巡平台。", "chunks": [1]}],
}


def test_llm_mode_enriches_activity_on_the_lane(llm_mode, fake_llm):
    zep = llm_mode
    episode = _add_activity(zep, _post("智巡平台今天上线，我很支持"))
    assert episode.processed is False and episode.extraction_status == "queued"
    fake_llm.script = [STANCE]
    stats = zep.worker.drain()
    assert stats.activity_groups == 1 and fake_llm.call_count == 1
    system = fake_llm.calls[0]["messages"][0]["content"]
    assert "social-media actions by simulated accounts" in system
    assert "Alice Chen" in fake_llm.calls[0]["messages"][1]["content"]  # known account
    done = zep.graph.episode.get(episode.uuid_)
    assert done.processed is True and done.extraction_status == "succeeded"
    names = {edge.name: edge for edge in zep.graph.edge.get_by_graph_id("g1")}
    assert set(names) == {"POSTED", "SUPPORTS"}
    assert names["SUPPORTS"].episodes == [episode.uuid_]
    with zep.store.read() as conn:
        used = conn.execute("SELECT llm_calls FROM usage WHERE scope_kind = 'simulation' AND scope_id = 'sim-1'")
        assert used.fetchone()[0] == 1


def test_activity_groups_wait_unless_full_or_old(llm_mode, fake_llm, clock):
    zep = llm_mode
    _add_activity(zep, _post("第一条"))
    assert zep.worker.run_activity_lane() == 0  # partial group, not waited long enough
    clock.advance(16)
    fake_llm.script = [{"entities": [], "relations": []}]
    assert zep.worker.run_activity_lane() == 1
    assert fake_llm.call_count == 1


def test_activity_budget_exhaustion_skips_without_calling(llm_mode, fake_llm, worker_settings, monkeypatch):
    zep = llm_mode
    from app.memory.activity import ActivityPolicy

    monkeypatch.setattr(zep.worker, "activity_policy",
                        ActivityPolicy.from_settings(replace(zep.settings, activity_max_llm_calls=0)))
    episode = _add_activity(zep, _post("预算"))
    zep.worker.drain()
    assert fake_llm.call_count == 0
    done = zep.graph.episode.get(episode.uuid_)
    assert done.processed is True and done.extraction_status == "skipped"
    assert done.extraction_error["code"] == "budget_exhausted"


def test_activity_deadline_sweep(llm_mode, fake_llm, clock):
    zep = llm_mode
    episode = _add_activity(zep, _post("超时"))
    clock.advance(301)
    zep.worker.run_activity_lane()
    done = zep.graph.episode.get(episode.uuid_)
    assert done.processed is True and done.extraction_status == "skipped"
    assert done.extraction_error["code"] == "deadline"
    assert fake_llm.call_count == 0


def test_activity_llm_failure_degrades_and_fatal_switches_the_lane_off(llm_mode, fake_llm, openai_error):
    zep = llm_mode
    first = _add_activity(zep, _post("智巡平台今天在海城市上线"))
    fake_llm.script = [openai_error(401)]
    zep.worker.drain()
    done = zep.graph.episode.get(first.uuid_)
    assert done.processed is True and done.extraction_status == "degraded"
    assert done.extraction_error["code"] == "llm_auth"
    assert not zep.worker.activity_lane.enabled

    second = _add_activity(zep, _post("海岳能源宣布终止联合部署协议", minute=1))
    zep.worker.drain()
    assert fake_llm.call_count == 1
    later = zep.graph.episode.get(second.uuid_)
    assert later.extraction_status == "skipped" and later.extraction_error["code"] == "llm_unavailable"
    # Rules facts exist regardless.
    assert [edge.name for edge in zep.graph.edge.get_by_graph_id("g1")] == ["POSTED", "POSTED"]


def test_activity_bad_output_degrades(llm_mode, fake_llm):
    zep = llm_mode
    episode = _add_activity(zep, _post("坏输出"))
    fake_llm.script = [LLMResponseError("invalid JSON")]
    zep.worker.drain()
    done = zep.graph.episode.get(episode.uuid_)
    assert done.extraction_status == "degraded" and done.extraction_error["code"] == "llm_bad_output"
    assert zep.worker.activity_lane.enabled


def test_crashed_activity_episode_is_degraded_after_three_claims(llm_mode, clock, worker_settings):
    zep = llm_mode
    episode = _add_activity(zep, _post("崩溃"))
    from app.memory.activity import claim_activity_episodes

    for attempt in range(POISON_PILL_ATTEMPTS):
        with zep.store.write() as conn:
            assert claim_activity_episodes(conn, [episode.uuid_], owner="crashed",
                                           lease_until=clock() + 10) == [episode.uuid_]
        clock.advance(11)
        zep.worker.recover_leases()
    done = zep.graph.episode.get(episode.uuid_)
    assert done.processed is True and done.extraction_status == "degraded"
    assert done.extraction_error["code"] == "extraction_crashed"


# ---------------------------------------------------------------------------
# Real threads
# ---------------------------------------------------------------------------


def _wait_for(predicate, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_background_worker_completes_a_batch_and_heartbeats_leases(memory_db_path, worker_settings, fake_llm):
    release = threading.Event()
    entered = threading.Event()

    def slow(messages):
        entered.set()
        release.wait(10)
        return works_for_extractor(messages)

    fake_llm.script = slow
    zep = _make(memory_db_path, replace(worker_settings, heartbeat_seconds=0.02, window_chars=4000),
                lambda: fake_llm, autostart_worker=True)
    try:
        batch_id, details = _batch(zep, _texts(2))
        assert entered.wait(10)
        first = _episode_row(zep, details[0].episode_uuid)["lease_until"]
        assert _wait_for(lambda: _episode_row(zep, details[0].episode_uuid)["lease_until"] > first, 5)
        assert zep.worker.snapshot()["windows_in_flight"] == 1
        release.set()
        assert _wait_for(lambda: zep.batch.get(batch_id).status == "succeeded")
        snapshot = zep.worker.snapshot()
        assert snapshot["running"] is True and snapshot["episodes"] == {} and snapshot["batches"] == {}
    finally:
        release.set()
        zep.close()
    assert zep.worker.running is False


def test_background_worker_runs_windows_concurrently(memory_db_path, worker_settings, fake_llm):
    barrier = threading.Barrier(2, timeout=10)

    def together(messages):
        barrier.wait()
        return works_for_extractor(messages)

    fake_llm.script = together
    zep = _make(memory_db_path, replace(worker_settings, llm_concurrency=2, dedup_pass="off"),
                lambda: fake_llm, autostart_worker=True)
    try:
        batch_id, _ = _batch(zep, _texts(2))
        assert _wait_for(lambda: zep.batch.get(batch_id).status == "succeeded")
    finally:
        zep.close()


def test_stop_is_idempotent_and_never_started_workers_stop_quietly(memory_db_path, worker_settings, fake_llm):
    zep = _make(memory_db_path, worker_settings, lambda: fake_llm)
    zep.worker.stop()
    zep.close()
    zep.close()
