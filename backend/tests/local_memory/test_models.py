"""Row -> zep_cloud.types converters, raw responses and paging cursors."""

from __future__ import annotations

import base64
import json

import pytest
from zep_cloud.errors import BadRequestError
from zep_cloud.types import (
    BatchItemDetail,
    BatchSummary,
    EntityEdge,
    EntityNode,
    Episode,
    Graph,
    ProjectInfoResponse,
    SearchFilters,
)

from app.memory.models import (
    NEXT_CURSOR_HEADER,
    LocalHttpResponse,
    batch_item_from_row,
    batch_progress,
    batch_summary_from_row,
    decode_cursor,
    edge_from_row,
    encode_cursor,
    episode_from_row,
    filters_to_dict,
    graph_from_row,
    json_dumps,
    json_loads,
    node_from_row,
    normalize_offset_cursor,
    normalize_page_limit,
    project_info_response,
    string_list,
)


def test_node_and_edge_rows_become_sdk_models(local, seed):
    graph = seed.graph("g1")
    alice = seed.node(graph, "Alice Chen", "Person", summary="Leads the lab.", attributes={"role": "CEO"})
    acme = seed.node(graph, "Acme Corp")
    episode = seed.episode(graph, "Alice Chen works for Acme Corp.")
    edge = seed.edge(graph, alice, acme, "WORKS_FOR", "Alice Chen works for Acme Corp.", episodes=(episode,))
    with local.store.write() as conn:
        conn.execute("UPDATE edges SET valid_at = '2021-01-01T00:00:00.000000Z', attributes_json = ? "
                     "WHERE uuid = ?", (json_dumps({"position": "CEO"}), edge))
    with local.store.read() as conn:
        alice_row = conn.execute("SELECT * FROM nodes WHERE uuid = ?", (alice,)).fetchone()
        acme_row = conn.execute("SELECT * FROM nodes WHERE uuid = ?", (acme,)).fetchone()
        edge_row = conn.execute("SELECT * FROM edges WHERE uuid = ?", (edge,)).fetchone()
        graph_row = conn.execute("SELECT * FROM graphs").fetchone()

    node = node_from_row(alice_row)
    assert isinstance(node, EntityNode)
    assert node.uuid_ == alice
    assert node.labels == ["Entity", "Person"]
    assert node.summary == "Leads the lab."
    assert node.attributes == {"role": "CEO"}
    assert node.score is None
    assert node_from_row(acme_row).labels == ["Entity"]
    assert node_from_row(acme_row, score=0.5).score == 0.5

    entity_edge = edge_from_row(edge_row, [episode], score=1.0)
    assert isinstance(entity_edge, EntityEdge)
    assert entity_edge.uuid_ == edge
    assert (entity_edge.source_node_uuid, entity_edge.target_node_uuid) == (alice, acme)
    assert entity_edge.name == "WORKS_FOR"
    assert entity_edge.valid_at == "2021-01-01T00:00:00.000000Z"
    assert entity_edge.invalid_at is None and entity_edge.expired_at is None
    assert entity_edge.episodes == [episode]
    assert entity_edge.attributes == {"position": "CEO"}
    assert entity_edge.relevance == 1.0

    graph_model = graph_from_row(graph_row, project_uuid=local.store.project_uuid)
    assert isinstance(graph_model, Graph)
    assert graph_model.graph_id == "g1"
    assert graph_model.project_uuid == local.store.project_uuid
    assert graph_model.uuid_


def test_episode_row_uses_reference_time_and_terminal_status():
    row = {
        "uuid": "ep-1", "content": "text", "reference_time": "2026-05-10T09:00:00.000000Z",
        "created_at": "2026-09-25T00:00:00.000000Z", "processed": 0, "extraction_status": "degraded",
        "extraction_error": json.dumps({"code": "extraction_degraded", "message": "window failed"}),
        "metadata_json": json.dumps({"source": "mirofish_simulation", "round": 3}),
        "source": "text", "source_description": "MiroFish simulation activity batch",
    }
    episode = episode_from_row(row)
    assert isinstance(episode, Episode)
    assert episode.uuid_ == "ep-1"
    assert episode.created_at == "2026-05-10T09:00:00.000000Z"
    assert episode.processed is True
    assert episode.metadata == {"source": "mirofish_simulation", "round": 3}
    assert episode.extraction_status == "degraded"
    assert episode.extraction_error["code"] == "extraction_degraded"

    queued = episode_from_row({**row, "extraction_status": "queued", "extraction_error": None})
    assert queued.processed is False
    assert queued.extraction_error is None


def test_batch_progress_math_and_running_cap():
    running = batch_progress({"succeeded": 4, "processing": 0}, "processing", total=4)
    assert running.percent_complete == 99.0
    assert running.succeeded_items == 4

    partial = batch_progress({"pending": 1, "queued": 1, "processing": 2, "succeeded": 4, "failed": 1,
                              "skipped": 1}, "processing", total=10)
    assert partial.queued_items == 2
    assert partial.processing_items == 2
    assert partial.percent_complete == 60.0

    done = batch_progress({"succeeded": 3, "canceled": 1}, "succeeded", total=4)
    assert done.percent_complete == 100.0
    assert batch_progress({}, "invalid", total=0).percent_complete == 0.0


def test_batch_summary_and_item_rows():
    summary = batch_summary_from_row({
        "batch_id": "b1", "status": "queued", "item_count": 2, "metadata_json": '{"op": "x"}',
        "ignore_roles_json": None, "created_at": "c", "updated_at": "u", "processed_at": "p",
        "completed_at": None, "error_json": None,
    }, {"queued": 2})
    assert isinstance(summary, BatchSummary)
    assert summary.batch_id == "b1"
    assert summary.metadata == {"op": "x"}
    assert summary.progress.total_items == 2
    assert summary.progress.queued_items == 2
    assert summary.progress.percent_complete == 0.0

    item = batch_item_from_row({
        "item_id": "i1", "sequence_index": 7, "status": "succeeded", "episode_uuid": "ep-1",
        "graph_id": "g1", "error_json": '{"code": "extraction_degraded", "message": "m"}',
        "created_at": "c", "updated_at": "u",
    })
    assert isinstance(item, BatchItemDetail)
    assert item.episode_uuid == item.source_uuid == "ep-1"
    assert item.kind == "graph_episode"
    assert item.sequence_index == 7
    assert item.error == {"code": "extraction_degraded", "message": "m"}


def test_project_info_response():
    response = project_info_response("p-uuid", "2026-01-01T00:00:00.000000Z", "local_memory.sqlite3")
    assert isinstance(response, ProjectInfoResponse)
    assert response.project.uuid_ == "p-uuid"
    assert response.project.name == "Parthenon local memory"
    assert response.project.description.endswith("local_memory.sqlite3")


def test_local_http_response_shape():
    response = LocalHttpResponse(data=[1, 2], headers={NEXT_CURSOR_HEADER: "abc"})
    assert response.data == [1, 2]
    assert response.headers.get("zep-next-cursor") == "abc"
    assert LocalHttpResponse(data=[]).headers == {}
    with pytest.raises(Exception):
        response.data = []  # type: ignore[misc]


def test_cursor_round_trip_and_validation():
    cursor = encode_cursor("node", "mirofish_abc", 42, "desc")
    assert "=" not in cursor
    decoded = decode_cursor(cursor, kind="node", graph_id="mirofish_abc")
    assert (decoded.after, decoded.direction) == (42, "desc")
    assert decode_cursor(encode_cursor("edge", "g", 0), kind="edge", graph_id="g").direction == "asc"

    with pytest.raises(BadRequestError):
        decode_cursor(cursor, kind="edge", graph_id="mirofish_abc")
    with pytest.raises(BadRequestError):
        decode_cursor(cursor, kind="node", graph_id="other")
    forged = base64.urlsafe_b64encode(json.dumps({"v": 1, "k": "node", "g": "g", "after": -1}).encode()).decode()
    for bad in ("", "not base64 !!", "e30", forged, None, 17):
        with pytest.raises(BadRequestError):
            decode_cursor(bad, kind="node", graph_id="g")
    with pytest.raises(BadRequestError):
        encode_cursor("node", "g", 1, "sideways")


def test_limit_and_offset_normalization():
    assert normalize_page_limit(None) == 100
    assert normalize_page_limit(5) == 5
    assert normalize_page_limit(5000) == 1000
    assert normalize_page_limit("3") == 3
    for bad in (0, -1, "x", True):
        with pytest.raises(BadRequestError):
            normalize_page_limit(bad)
    assert normalize_offset_cursor(None) == 0
    assert normalize_offset_cursor(0) == 0
    assert normalize_offset_cursor(25) == 25
    for bad in (-1, "x", False):
        with pytest.raises(BadRequestError):
            normalize_offset_cursor(bad)


def test_filters_and_json_helpers():
    filters = SearchFilters(node_labels=["Person"], exclude_edge_types=["MENTIONS"])
    assert filters_to_dict(filters) == {"node_labels": ["Person"], "exclude_edge_types": ["MENTIONS"]}
    assert filters_to_dict({"edge_types": ["WORKS_FOR"], "node_labels": None}) == {"edge_types": ["WORKS_FOR"]}
    assert filters_to_dict(None) == {}
    with pytest.raises(BadRequestError):
        filters_to_dict(["Person"])
    assert string_list("Person") == ["Person"]
    assert string_list(["Person", "", 3]) == ["Person"]
    assert json_loads("{broken", {}) == {}
    assert json_loads(None, []) == []
    assert json_dumps({"b": 1, "a": "北京"}) == '{"a":"北京","b":1}'
