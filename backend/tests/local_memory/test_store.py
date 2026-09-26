"""MemoryStore: schema, pragmas, FTS sync, fallbacks, transactions, busy mapping."""

from __future__ import annotations

import os
import sqlite3
import threading
import time

import pytest
from zep_cloud.core.api_error import ApiError as ZepApiError
from zep_cloud.errors import BadRequestError, ConflictError, NotFoundError

from app.memory import MemoryStore, StoreCaps, bad_request, conflict, not_found, store_busy, unsupported
from app.memory import store as store_module
from app.memory.errors import translate_sqlite_errors
from app.utils.zep import call_zep_read_with_retry, is_retryable_zep_error


def _tables(store: MemoryStore) -> set[str]:
    with store.read() as conn:
        return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'view')")}


def _triggers(store: MemoryStore) -> set[str]:
    with store.read() as conn:
        return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'")}


def _match(store: MemoryStore, fts: str, query: str) -> list[int]:
    with store.read() as conn:
        return [row[0] for row in conn.execute(f"SELECT rowid FROM {fts} WHERE {fts} MATCH ?", (query,))]


def _fts_sql(store: MemoryStore, fts: str) -> str:
    with store.read() as conn:
        row = conn.execute("SELECT sql FROM sqlite_master WHERE name = ?", (fts,)).fetchone()
    return row[0] if row else ""


def _count(store: MemoryStore, table: str) -> int:
    with store.read() as conn:
        return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


# ---------------------------------------------------------------------------
# Schema, pragmas, files
# ---------------------------------------------------------------------------


def test_schema_creation_is_idempotent_across_reopen(memory_db_path):
    first = MemoryStore(memory_db_path)
    tables, triggers, meta = _tables(first), _triggers(first), dict(first.meta())
    first.close()

    second = MemoryStore(memory_db_path)
    try:
        assert _tables(second) == tables
        assert _triggers(second) == triggers
        assert dict(second.meta()) == meta
        assert second.schema_version() == 1
        assert second.project_uuid == meta["project_uuid"]
        assert second.created_at == meta["created_at"]
        second.migrate()  # running again changes nothing
        assert dict(second.meta()) == meta
    finally:
        second.close()

    expected = {
        "meta", "graphs", "default_ontology", "episodes", "nodes", "node_aliases", "edges",
        "edge_episodes", "node_episodes", "batches", "batch_items", "usage",
        "edges_fts", "nodes_fts", "episodes_fts",
    }
    assert expected <= tables
    assert {f"{t}_{s}" for t in ("edges", "nodes", "episodes") for s in ("ai", "ad", "au")} == triggers


def test_pragmas_are_set_on_every_pooled_connection(memory_store):
    connections = [memory_store._pool.acquire() for _ in range(3)]
    try:
        for conn in connections:
            assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
            assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
            assert conn.execute("PRAGMA synchronous").fetchone()[0] == 1  # NORMAL
            assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == memory_store.busy_timeout_ms
            assert conn.execute("PRAGMA temp_store").fetchone()[0] == 2  # MEMORY
            assert conn.execute("PRAGMA auto_vacuum").fetchone()[0] == 2  # INCREMENTAL
    finally:
        for conn in connections:
            memory_store._pool.release(conn)


@pytest.mark.skipif(os.name != "posix", reason="POSIX permissions")
def test_new_directory_and_file_are_private(tmp_path):
    path = tmp_path / "private" / "memory" / "db.sqlite3"
    store = MemoryStore(path)
    try:
        assert os.stat(path).st_mode & 0o777 == 0o600
        assert os.stat(path.parent).st_mode & 0o777 == 0o700
    finally:
        store.close()


def test_rejects_in_memory_database():
    with pytest.raises(ValueError):
        MemoryStore(":memory:")


def test_close_is_idempotent_and_blocks_further_use(memory_db_path):
    store = MemoryStore(memory_db_path)
    store.close()
    store.close()
    assert store.closed
    with pytest.raises(RuntimeError):
        with store.read():
            pass


def test_capabilities_detected_and_recorded(memory_store):
    assert memory_store.caps == StoreCaps(fts5=True, trigram=True)
    assert memory_store.caps.tokenizer == "trigram"
    assert memory_store.meta_get("fts_tokenizer") == "trigram"
    assert "trigram" in _fts_sql(memory_store, "edges_fts")


def test_migrations_apply_in_order_and_only_once(memory_db_path, monkeypatch):
    MemoryStore(memory_db_path).close()
    applied: list[int] = []

    def v2(conn, caps):
        applied.append(2)
        conn.execute("CREATE TABLE IF NOT EXISTS extra_v2 (id INTEGER PRIMARY KEY)")

    monkeypatch.setitem(store_module.MIGRATIONS, 2, v2)
    monkeypatch.setitem(store_module.MIGRATIONS, 3, ["CREATE TABLE IF NOT EXISTS extra_v3 (id INTEGER)"])

    store = MemoryStore(memory_db_path)
    try:
        assert store.schema_version() == 3
        assert {"extra_v2", "extra_v3"} <= _tables(store)
        store.migrate()
        assert applied == [2]
    finally:
        store.close()


# ---------------------------------------------------------------------------
# FTS triggers
# ---------------------------------------------------------------------------


def test_fts_triggers_follow_insert_update_and_delete(local, seed):
    store = local.store
    graph = seed.graph("g1")
    alice = seed.node(graph, "Alice Chen", "Person", summary="Alice leads the lab.", aliases=("Dr. Chen",))
    acme = seed.node(graph, "Acme Corp", "Organization")
    edge = seed.edge(graph, alice, acme, "WORKS_FOR", "Alice Chen works for Acme Corp.")
    episode = seed.episode(graph, "Alice Chen joined Acme Corp in 2021.", source_description="press")

    with store.read() as conn:
        edge_id = conn.execute("SELECT id FROM edges WHERE uuid = ?", (edge,)).fetchone()[0]
        alice_id = conn.execute("SELECT id FROM nodes WHERE uuid = ?", (alice,)).fetchone()[0]
        episode_id = conn.execute("SELECT id FROM episodes WHERE uuid = ?", (episode,)).fetchone()[0]

    assert _match(store, "edges_fts", '"acme"') == [edge_id]
    assert alice_id in _match(store, "nodes_fts", '"lab"')
    assert _match(store, "nodes_fts", 'aliases_text : "chen"') == [alice_id]
    assert _match(store, "episodes_fts", '"joined"') == [episode_id]

    with store.write() as conn:
        conn.execute("UPDATE edges SET fact = ? WHERE uuid = ?", ("Alice Chen left Globex.", edge))
        conn.execute("UPDATE nodes SET summary = ? WHERE uuid = ?", ("Alice sails.", alice))
        conn.execute("UPDATE episodes SET source_description = ? WHERE uuid = ?", ("newswire", episode))
        # Columns outside the FTS index do not touch it.
        conn.execute("UPDATE nodes SET mention_count = 5 WHERE uuid = ?", (alice,))

    assert _match(store, "edges_fts", '"acme"') == []
    assert _match(store, "edges_fts", '"globex"') == [edge_id]
    assert _match(store, "nodes_fts", '"lab"') == []
    assert _match(store, "nodes_fts", '"sails"') == [alice_id]
    assert _match(store, "episodes_fts", '"press"') == []
    assert _match(store, "episodes_fts", '"newswire"') == [episode_id]

    with store.write() as conn:
        conn.execute("DELETE FROM edges WHERE uuid = ?", (edge,))
    assert _match(store, "edges_fts", '"globex"') == []
    assert store.fts_integrity_check() == []


def test_trigram_index_matches_chinese_substrings(local, seed):
    graph = seed.graph("g-cn")
    a = seed.node(graph, "张伟", "Person")
    b = seed.node(graph, "北京大学", "University")
    seed.edge(graph, a, b, "STUDIED_AT", "张伟毕业于北京大学计算机系")

    assert len(_match(local.store, "edges_fts", '"北京大"')) == 1
    assert len(_match(local.store, "edges_fts", '"计算机"')) == 1
    assert len(_match(local.store, "nodes_fts", '"北京大"')) == 1


def test_graph_delete_cascades_and_clears_fts(local, seed):
    store = local.store
    graph = seed.graph("g-del")
    other = seed.graph("g-keep")
    episode = seed.episode(graph, "Alice Chen works for Acme Corp.")
    alice = seed.node(graph, "Alice Chen", "Person", aliases=("Alice",))
    acme = seed.node(graph, "Acme Corp", "Organization")
    seed.edge(graph, alice, acme, "WORKS_FOR", "Alice Chen works for Acme Corp.", episodes=(episode,))
    kept = seed.node(other, "Acme Corp", "Organization")
    with store.write() as conn:
        conn.execute("INSERT INTO node_episodes(node_uuid, episode_uuid) VALUES (?, ?)", (alice, episode))
        conn.execute(
            "INSERT INTO batches(batch_id, status, created_at, updated_at) VALUES ('b1', 'queued', 'x', 'x')"
        )
        conn.execute(
            "INSERT INTO batch_items(item_id, batch_id, sequence_index, graph_id, episode_uuid, status, "
            "created_at, updated_at) VALUES ('i1', 'b1', 0, ?, ?, 'queued', 'x', 'x')",
            (graph, episode),
        )

    with store.write() as conn:
        conn.execute("DELETE FROM graphs WHERE graph_id = ?", (graph,))

    for table in ("episodes", "edges", "edge_episodes", "node_episodes"):
        assert _count(store, table) == 0, table
    with store.read() as conn:
        assert [r[0] for r in conn.execute("SELECT uuid FROM nodes")] == [kept]
        assert {r[0] for r in conn.execute("SELECT DISTINCT graph_id FROM node_aliases")} == {other}
    # batch_items have no FK to graphs: they outlive the delete (to be marked canceled).
    assert _count(store, "batch_items") == 1
    assert _match(store, "edges_fts", '"works"') == []
    assert _match(store, "episodes_fts", '"works"') == []
    assert len(_match(store, "nodes_fts", '"acme"')) == 1
    assert store.fts_integrity_check() == []
    store.incremental_vacuum(2000)
    store.optimize_fts()
    assert store.fts_integrity_check() == []


def test_incremental_vacuum_returns_free_pages(local, seed):
    store = local.store
    graph = seed.graph("g-big")
    with store.write() as conn:
        conn.executemany(
            "INSERT INTO episodes(uuid, graph_id, kind, content, source, reference_time, created_at) "
            "VALUES (?, ?, 'document', ?, 'text', 'x', 'x')",
            [(f"ep-{i}", graph, f"chunk {i} " + "x" * 2000) for i in range(300)],
        )
    with store.write() as conn:
        conn.execute("DELETE FROM graphs WHERE graph_id = ?", (graph,))

    def free_and_total() -> tuple[int, int]:
        with store.read() as conn:
            return (conn.execute("PRAGMA freelist_count").fetchone()[0],
                    conn.execute("PRAGMA page_count").fetchone()[0])

    free_before, pages_before = free_and_total()
    assert free_before > 50
    store.incremental_vacuum(20)
    free_after, pages_after = free_and_total()
    assert free_after == free_before - 20
    assert pages_after == pages_before - 20
    store.incremental_vacuum()
    assert free_and_total()[0] == 0

    with store.write():
        with pytest.raises(RuntimeError):
            store.incremental_vacuum()


# ---------------------------------------------------------------------------
# Capability fallbacks
# ---------------------------------------------------------------------------


def test_without_trigram_fts_uses_unicode61(tmp_path):
    store = MemoryStore(tmp_path / "u61.sqlite3", caps=StoreCaps(fts5=True, trigram=False))
    try:
        assert store.meta_get("fts_tokenizer") == "unicode61 remove_diacritics 2"
        assert "unicode61" in _fts_sql(store, "edges_fts")
        _insert_edge(store, "Alice Chen works for Acme Corp. 张伟在北京大学")
        assert len(_match(store, "edges_fts", '"acme"')) == 1
        # CJK needs the LIKE channel without trigram.
        with store.read() as conn:
            hits = conn.execute("SELECT count(*) FROM edges WHERE fact LIKE ?", ("%北京%",)).fetchone()[0]
        assert hits == 1
    finally:
        store.close()


def test_without_fts5_no_fts_tables_and_like_still_works(tmp_path):
    store = MemoryStore(tmp_path / "nofts.sqlite3", caps=StoreCaps(fts5=False, trigram=False))
    try:
        assert store.meta_get("fts_tokenizer") == "none"
        assert not {"edges_fts", "nodes_fts", "episodes_fts"} & _tables(store)
        assert _triggers(store) == set()
        _insert_edge(store, "张伟毕业于北京大学")
        with store.read() as conn:
            hits = conn.execute("SELECT count(*) FROM edges WHERE fact LIKE ?", ("%北京%",)).fetchone()[0]
        assert hits == 1
        assert store.fts_integrity_check() == []
        store.optimize_fts()  # no-op without FTS
    finally:
        store.close()


def test_tokenizer_change_rebuilds_fts_indexes(memory_db_path):
    store = MemoryStore(memory_db_path)
    _insert_edge(store, "Alice Chen works for Acme Corp.")
    store.close()

    store = MemoryStore(memory_db_path, caps=StoreCaps(fts5=True, trigram=False))
    try:
        assert store.meta_get("fts_tokenizer") == "unicode61 remove_diacritics 2"
        assert "unicode61" in _fts_sql(store, "edges_fts")
        assert len(_match(store, "edges_fts", '"acme"')) == 1  # rebuilt from content
        assert store.fts_integrity_check() == []
    finally:
        store.close()

    store = MemoryStore(memory_db_path, caps=StoreCaps(fts5=False, trigram=False))
    try:
        assert not {"edges_fts", "nodes_fts", "episodes_fts"} & _tables(store)
        assert _triggers(store) == set()
        _insert_edge(store, "Bob works for Globex.")
    finally:
        store.close()

    store = MemoryStore(memory_db_path)
    try:
        assert store.meta_get("fts_tokenizer") == "trigram"
        assert len(_match(store, "edges_fts", '"acme"')) == 1
        assert len(_match(store, "edges_fts", '"globex"')) == 1  # written while FTS was off
        assert store.fts_integrity_check() == []
    finally:
        store.close()


def _insert_edge(store: MemoryStore, fact: str) -> None:
    """Insert a graph (once), two nodes and one edge carrying ``fact``."""

    from app.memory import new_id

    with store.write() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO graphs(graph_id, uuid, created_at) VALUES ('g', ?, 'x')", (new_id(),)
        )
        ends = []
        for name in ("source", "target"):
            node_uuid = new_id()
            conn.execute(
                "INSERT INTO nodes(uuid, graph_id, name, name_key, labels_json, created_at, updated_at) "
                "VALUES (?, 'g', ?, ?, '[\"Entity\"]', 'x', 'x')",
                (node_uuid, name, name),
            )
            ends.append(node_uuid)
        conn.execute(
            "INSERT INTO edges(uuid, graph_id, name, fact, fact_key, source_node_uuid, target_node_uuid, "
            "created_at) VALUES (?, 'g', 'RELATES_TO', ?, ?, ?, ?, 'x')",
            (new_id(), fact, fact.lower(), ends[0], ends[1]),
        )


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------


def test_write_commits_or_rolls_back(local, seed):
    graph = seed.graph("g1")
    with pytest.raises(RuntimeError):
        with local.store.write() as conn:
            conn.execute("UPDATE graphs SET name = 'changed' WHERE graph_id = ?", (graph,))
            raise RuntimeError("boom")
    with local.store.read() as conn:
        assert conn.execute("SELECT name FROM graphs").fetchone()[0] == "g1"

    with local.store.write() as conn:
        conn.execute("UPDATE graphs SET name = 'changed' WHERE graph_id = ?", (graph,))
    with local.store.read() as conn:
        assert conn.execute("SELECT name FROM graphs").fetchone()[0] == "changed"


def test_nested_write_joins_outer_transaction_with_savepoints(local, seed):
    store = local.store
    seed.graph("g1")
    with store.write() as outer:
        outer.execute("UPDATE graphs SET name = 'outer'")
        with store.write() as inner:
            assert inner is outer
            inner.execute("UPDATE graphs SET description = 'inner ok'")
        with pytest.raises(ValueError):
            with store.write() as inner:
                inner.execute("UPDATE graphs SET time_zone = 'inner failed'")
                raise ValueError("inner")
        assert store.in_write
    assert not store.in_write
    with store.read() as conn:
        row = conn.execute("SELECT name, description, time_zone FROM graphs").fetchone()
    assert tuple(row) == ("outer", "inner ok", None)


def test_outer_failure_discards_nested_changes(local, seed):
    seed.graph("g1")
    with pytest.raises(KeyError):
        with local.store.write():
            with local.store.write() as inner:
                inner.execute("UPDATE graphs SET name = 'nested'")
            raise KeyError("outer")
    assert not local.store.in_write
    with local.store.read() as conn:
        assert conn.execute("SELECT name FROM graphs").fetchone()[0] == "g1"


def test_read_inside_write_sees_uncommitted_rows(local, seed):
    seed.graph("g1")
    with local.store.write() as conn:
        conn.execute("UPDATE graphs SET name = 'pending'")
        with local.store.read() as reader:
            assert reader.execute("SELECT name FROM graphs").fetchone()[0] == "pending"
        seen_elsewhere: list[str] = []
        thread = threading.Thread(target=lambda: seen_elsewhere.append(_graph_name(local.store)))
        thread.start()
        thread.join(5)
        assert seen_elsewhere == ["g1"]  # other threads keep reading the committed snapshot


def _graph_name(store: MemoryStore) -> str:
    with store.read() as conn:
        return conn.execute("SELECT name FROM graphs").fetchone()[0]


def test_snapshot_read_wraps_statements_in_one_transaction(local, seed):
    seed.graph("g1")
    with local.store.read(snapshot=True) as conn:
        assert conn.in_transaction
        conn.execute("SELECT count(*) FROM graphs").fetchone()
    with local.store.read() as conn:
        assert not conn.in_transaction


def test_programming_errors_propagate_unwrapped(local):
    with pytest.raises(sqlite3.OperationalError, match="no such table"):
        with local.store.write() as conn:
            conn.execute("SELECT * FROM missing_table")
    with pytest.raises(sqlite3.OperationalError, match="no such table"):
        with local.store.read() as conn:
            conn.execute("SELECT * FROM missing_table")


# ---------------------------------------------------------------------------
# Busy database -> retryable 503
# ---------------------------------------------------------------------------


def test_busy_database_maps_to_retryable_503(memory_db_path):
    store = MemoryStore(memory_db_path, busy_timeout_ms=50)
    blocker = sqlite3.connect(str(memory_db_path), isolation_level=None)
    try:
        blocker.execute("BEGIN IMMEDIATE")
        with pytest.raises(ZepApiError) as caught:
            with store.write() as conn:
                conn.execute("UPDATE meta SET value = value")
        error = caught.value
        assert error.status_code == 503
        assert error.headers == {"Retry-After": "1"}
        assert error.body == {"message": "local memory store is busy"}
        assert type(error).__module__.startswith("zep_cloud")
        assert is_retryable_zep_error(error)
        assert "status_code: 503" in str(error)
        assert isinstance(error.__cause__, sqlite3.OperationalError)
    finally:
        blocker.execute("ROLLBACK")
        blocker.close()
        store.close()


def test_busy_error_is_retried_honoring_retry_after():
    sleeps: list[float] = []
    attempts = {"n": 0}

    @translate_sqlite_errors
    def flaky_read() -> str:
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise sqlite3.OperationalError("database is locked")
        return "ok"

    result = call_zep_read_with_retry(flaky_read, operation_name="local read", sleep=sleeps.append)
    assert result == "ok"
    assert sleeps == [1.0]


def test_translate_sqlite_errors_leaves_other_errors_alone():
    @translate_sqlite_errors
    def broken() -> None:
        raise sqlite3.OperationalError("no such column: x")

    with pytest.raises(sqlite3.OperationalError):
        broken()

    @translate_sqlite_errors
    def disk() -> None:
        raise sqlite3.OperationalError("disk I/O error")

    with pytest.raises(ZepApiError) as caught:
        disk()
    assert caught.value.status_code == 503


def test_error_helpers_use_sdk_classes():
    for error, cls, status in (
        (not_found("graph not found: g1"), NotFoundError, 404),
        (bad_request("bad"), BadRequestError, 400),
        (conflict("graph already exists"), ConflictError, 409),
        (unsupported("thread"), BadRequestError, 400),
        (store_busy(), ZepApiError, 503),
    ):
        assert isinstance(error, cls)
        assert isinstance(error, ZepApiError)
        assert error.status_code == status
        assert type(error).__module__.startswith("zep_cloud")
    assert unsupported("thread").body.message == "thread is not supported by the local memory backend"
    assert not is_retryable_zep_error(not_found("x"))
    assert not is_retryable_zep_error(bad_request("x"))
    assert not is_retryable_zep_error(conflict("x"))


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------

CONCURRENCY_SECONDS = 2.0


def test_readers_and_writer_run_concurrently_without_errors(local, seed):
    store = local.store
    graph = seed.graph("g-load")
    hub = seed.node(graph, "Hub", "Organization")
    errors: list[BaseException] = []
    deadline = time.monotonic() + CONCURRENCY_SECONDS
    written = {"n": 0}
    reads = {"n": 0}
    reads_lock = threading.Lock()

    def writer() -> None:
        try:
            while time.monotonic() < deadline:
                index = written["n"]
                with store.write() as conn:
                    node_uuid = f"n-{index}"
                    conn.execute(
                        "INSERT INTO nodes(uuid, graph_id, name, name_key, labels_json, created_at, updated_at) "
                        "VALUES (?, ?, ?, ?, '[\"Entity\"]', 'x', 'x')",
                        (node_uuid, graph, f"Person {index}", f"person{index}"),
                    )
                    conn.execute(
                        "INSERT INTO edges(uuid, graph_id, name, fact, fact_key, source_node_uuid, "
                        "target_node_uuid, created_at) VALUES (?, ?, 'KNOWS', ?, ?, ?, ?, 'x')",
                        (f"e-{index}", graph, f"Person {index} knows the hub", f"k{index}", node_uuid, hub),
                    )
                written["n"] = index + 1
        except BaseException as error:  # pragma: no cover - reported below
            errors.append(error)

    def reader() -> None:
        try:
            while time.monotonic() < deadline:
                with store.read(snapshot=True) as conn:
                    nodes = conn.execute("SELECT count(*) FROM nodes").fetchone()[0]
                    edges = conn.execute("SELECT count(*) FROM edges").fetchone()[0]
                    conn.execute("SELECT rowid FROM edges_fts WHERE edges_fts MATCH '\"knows\"' LIMIT 20").fetchall()
                # One snapshot: every edge's source node is visible (+1 for the hub).
                assert nodes == edges + 1
                with reads_lock:
                    reads["n"] += 1
        except BaseException as error:  # pragma: no cover - reported below
            errors.append(error)

    threads = [threading.Thread(target=writer)] + [threading.Thread(target=reader) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(CONCURRENCY_SECONDS + 30)

    assert errors == []
    assert written["n"] > 0 and reads["n"] > 0
    assert _count(store, "edges") == written["n"]
    assert store.fts_integrity_check() == []
