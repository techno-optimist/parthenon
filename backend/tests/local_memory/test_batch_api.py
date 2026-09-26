"""``LocalZep.batch``: state machine, items, paging, progress (spec §2.6, §4.10)."""

from __future__ import annotations

import pytest
from zep_cloud import BatchAddItem
from zep_cloud.errors import BadRequestError, ConflictError, NotFoundError
from zep_cloud.types import BatchItemDetail, BatchItemListResponse, BatchListResponse, BatchSummary

from app.memory import LocalZep


def _items(texts, graph_id="g1", **extra):
    return [BatchAddItem(type="graph_episode", graph_id=graph_id, data=text, data_type="text", **extra)
            for text in texts]


def _texts(count, start=0):
    return [f"Person{i} works for Org{i}." for i in range(start, start + count)]


@pytest.fixture
def graph(local):
    local.graph.create(graph_id="g1")
    return "g1"


def test_full_state_machine(local, graph):
    batch = local.batch.create(metadata={"mirofish_operation_id": "op-1", "graph_id": graph, "chunk_count": 3})
    assert isinstance(batch, BatchSummary)
    assert batch.batch_id and batch.status == "draft"
    assert batch.metadata == {"mirofish_operation_id": "op-1", "graph_id": graph, "chunk_count": 3}
    assert batch.item_count == 0

    details = local.batch.add(batch_id=batch.batch_id, items=_items(_texts(3)))
    assert len(details) == 3
    assert all(isinstance(detail, BatchItemDetail) for detail in details)
    assert [d.sequence_index for d in details] == [0, 1, 2]
    assert all(d.status == "pending" and d.episode_uuid == d.source_uuid and d.graph_id == graph
               for d in details)
    assert all(d.kind == "graph_episode" for d in details)
    assert local.batch.get(batch.batch_id).item_count == 3

    queued = local.batch.process(batch_id=batch.batch_id)
    assert queued.status == "queued" and queued.processed_at
    assert queued.progress.queued_items == 3 and queued.progress.percent_complete == 0.0
    # The episodes exist right away but are not processed yet.
    episode = local.graph.episode.get(uuid_=details[0].episode_uuid)
    assert episode.processed is False

    stats = local.worker.drain()
    assert stats.windows == 1 and stats.batches_finalized == 1
    done = local.batch.get(batch.batch_id)
    assert done.status == "succeeded" and done.completed_at
    assert done.progress.succeeded_items == 3 and done.progress.percent_complete == 100.0
    items = local.batch.list_items(batch.batch_id).items
    assert {item.status for item in items} == {"succeeded"}
    assert all(item.error is None for item in items)
    assert local.graph.episode.get(uuid_=details[0].episode_uuid).processed is True


def test_sequence_index_is_global_across_add_calls(local, graph):
    batch = local.batch.create()
    first = local.batch.add(batch.batch_id, items=_items(_texts(2)))
    second = local.batch.add(batch.batch_id, items=_items(_texts(3, start=2)))
    assert [d.sequence_index for d in first + second] == [0, 1, 2, 3, 4]
    assert local.batch.get(batch.batch_id).item_count == 5


def test_add_after_process_is_a_conflict(local, graph):
    batch = local.batch.create()
    local.batch.add(batch.batch_id, items=_items(_texts(1)))
    local.batch.process(batch.batch_id)
    with pytest.raises(ConflictError):
        local.batch.add(batch.batch_id, items=_items(_texts(1)))


def test_empty_batch_becomes_invalid_and_cannot_be_processed_again(local, graph):
    batch = local.batch.create()
    assert local.batch.process(batch.batch_id).status == "invalid"
    with pytest.raises(ConflictError):
        local.batch.process(batch.batch_id)


def test_process_is_idempotent(local, graph):
    batch = local.batch.create()
    local.batch.add(batch.batch_id, items=_items(_texts(2)))
    first = local.batch.process(batch.batch_id)
    again = local.batch.process(batch.batch_id)
    assert first.status == again.status == "queued"
    local.worker.drain()
    assert local.batch.process(batch.batch_id).status == "succeeded"


def test_missing_batches_are_not_found(local):
    for call in (
        lambda: local.batch.get("missing"),
        lambda: local.batch.process("missing"),
        lambda: local.batch.list_items("missing"),
        lambda: local.batch.add("missing", items=_items(["x"])),
        lambda: local.batch.delete("missing"),
    ):
        with pytest.raises(NotFoundError):
            call()


@pytest.mark.parametrize(
    "items, error",
    [
        ([], BadRequestError),
        ("not a list", BadRequestError),
        ([{"type": "thread_message", "graph_id": "g1", "data": "x", "data_type": "text"}], BadRequestError),
        ([{"type": "graph_episode", "graph_id": "g1", "data": "", "data_type": "text"}], BadRequestError),
        ([{"type": "graph_episode", "graph_id": "g1", "data": "x" * 10_001, "data_type": "text"}], BadRequestError),
        ([{"type": "graph_episode", "graph_id": "g1", "data": "x", "data_type": "csv"}], BadRequestError),
        ([{"type": "graph_episode", "graph_id": "g1", "data": "x", "created_at": "soon"}], BadRequestError),
        ([{"type": "graph_episode", "graph_id": "g1", "data": "x", "metadata": {"a": [1]}}], BadRequestError),
        ([{"type": "graph_episode", "graph_id": "g1", "data": "x", "user_id": "u"}], BadRequestError),
        ([{"type": "graph_episode", "graph_id": "missing", "data": "x"}], NotFoundError),
    ],
)
def test_invalid_items_are_rejected_atomically(local, graph, items, error):
    batch = local.batch.create()
    local.batch.add(batch.batch_id, items=_items(["kept"]))
    with pytest.raises(error):
        local.batch.add(batch.batch_id, items=items)
    listed = local.batch.list_items(batch.batch_id).items
    assert [item.sequence_index for item in listed] == [0]
    assert local.batch.get(batch.batch_id).item_count == 1


def test_too_many_items_in_one_add(local, graph):
    batch = local.batch.create()
    with pytest.raises(BadRequestError):
        local.batch.add(batch.batch_id, items=_items(["x"] * 1001))


def test_plain_dict_items_and_created_at_are_accepted(local, graph):
    batch = local.batch.create()
    details = local.batch.add(batch.batch_id, items=[{
        "type": "graph_episode", "graph_id": "g1", "data": "Alice works for Acme.",
        "data_type": "text", "created_at": "2026-01-05T09:00:00Z", "metadata": {"chunk_index": 0},
        "source_description": "MiroFish source document chunk",
    }])
    episode = local.graph.episode.get(uuid_=details[0].episode_uuid)
    assert episode.created_at == "2026-01-05T09:00:00.000000Z"
    assert episode.metadata == {"chunk_index": 0}
    assert episode.source_description == "MiroFish source document chunk"


def test_list_uses_integer_offset_cursors_newest_first(local, graph):
    ids = [local.batch.create(metadata={"n": i}).batch_id for i in range(5)]
    seen, cursor, cursors = [], None, []
    while True:
        page = local.batch.list(limit=2, cursor=cursor)
        assert isinstance(page, BatchListResponse)
        seen.extend(batch.batch_id for batch in page.batches)
        if page.next_cursor is None:
            break
        assert page.next_cursor not in cursors and page.next_cursor != cursor
        cursors.append(page.next_cursor)
        cursor = page.next_cursor
    assert seen == list(reversed(ids))
    assert cursors == [2, 4]
    assert [b.batch_id for b in local.batch.list(cursor=0).batches] == list(reversed(ids))
    assert local.batch.list(limit=100).next_cursor is None
    with pytest.raises(BadRequestError):
        local.batch.list(limit=0)
    with pytest.raises(BadRequestError):
        local.batch.list(cursor=-1)


def test_list_filters_by_status(local, graph):
    empty = local.batch.create()
    local.batch.process(empty.batch_id)
    draft = local.batch.create()
    assert [b.batch_id for b in local.batch.list(status="invalid").batches] == [empty.batch_id]
    assert [b.batch_id for b in local.batch.list(status="draft").batches] == [draft.batch_id]


def test_list_items_paging_and_status_filter(local, graph):
    batch = local.batch.create()
    local.batch.add(batch.batch_id, items=_items(_texts(5)))
    indexes, cursor = [], 0
    while cursor is not None:
        page = local.batch.list_items(batch.batch_id, limit=2, cursor=cursor)
        assert isinstance(page, BatchItemListResponse)
        indexes.extend(item.sequence_index for item in page.items)
        cursor = page.next_cursor
    assert indexes == [0, 1, 2, 3, 4]
    assert len(local.batch.list_items(batch.batch_id, status="pending").items) == 5
    assert local.batch.list_items(batch.batch_id, status="succeeded").items == []


def test_progress_is_capped_at_99_until_the_batch_is_finalized(local, graph):
    batch = local.batch.create()
    local.batch.add(batch.batch_id, items=_items(_texts(2)))
    local.batch.process(batch.batch_id)
    # Run the window but not the finalizer.
    window_owner = local.worker.owner
    from app.memory.extraction import claim_window, process_window

    window = claim_window(local.store, local.settings, owner=window_owner)
    processing = local.batch.get(batch.batch_id)
    assert processing.status == "processing" and processing.progress.processing_items == 2
    process_window(local.store, window, local.worker.llm, local.settings)

    summary = local.batch.get(batch.batch_id)
    assert summary.status == "processing"
    assert summary.progress.succeeded_items == 2
    assert summary.progress.percent_complete == 99.0

    local.worker.finalize_ready_batches()
    final = local.batch.get(batch.batch_id)
    assert final.status == "succeeded" and final.progress.percent_complete == 100.0


def test_delete_only_drafts(local, graph):
    batch = local.batch.create()
    details = local.batch.add(batch.batch_id, items=_items(_texts(2)))
    local.batch.delete(batch.batch_id)
    with pytest.raises(NotFoundError):
        local.batch.get(batch.batch_id)
    with pytest.raises(NotFoundError):
        local.graph.episode.get(uuid_=details[0].episode_uuid)

    running = local.batch.create()
    local.batch.add(running.batch_id, items=_items(_texts(1)))
    local.batch.process(running.batch_id)
    with pytest.raises(ConflictError):
        local.batch.delete(running.batch_id)


def test_batches_persist_across_a_new_client_on_the_same_file(local, graph, memory_db_path, memory_settings,
                                                               fake_llm):
    batch = local.batch.create(metadata={"graph_id": graph})
    local.batch.add(batch.batch_id, items=_items(_texts(2)))
    local.batch.process(batch.batch_id)
    local.close()

    reopened = LocalZep(db_path=memory_db_path, settings=memory_settings, llm_client_factory=lambda: fake_llm,
                        autostart_worker=False, sleep=lambda _s: None)
    try:
        summary = reopened.batch.get(batch.batch_id)
        assert summary.status == "queued" and summary.item_count == 2
        assert summary.metadata == {"graph_id": graph}
        reopened.worker.drain()
        assert reopened.batch.get(batch.batch_id).status == "succeeded"
    finally:
        reopened.close()
