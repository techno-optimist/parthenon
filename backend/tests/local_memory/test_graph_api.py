"""``LocalZep.graph`` surface: graphs, episodes, nodes, edges, errors (spec §2.1-§2.5, §2.7)."""

from __future__ import annotations

import pytest
import zep_cloud
from zep_cloud import BatchAddItem
from zep_cloud.core.api_error import ApiError
from zep_cloud.errors import BadRequestError, ConflictError, NotFoundError
from zep_cloud.types import Episode, EpisodeMentions, EpisodeResponse, Graph, ProjectInfoResponse, SuccessResponse

from app.api import graph as graph_api
from app.utils.zep import call_zep_read_with_retry, is_retryable_zep_error


ACTIVITY_METADATA = {"source": "mirofish_simulation", "simulation_id": "sim-1", "platform": "twitter"}
ACTIVITY_TEXT = "[2026-05-10T09:00:00+00:00] [twitter round 1] Alice Chen: 发布了一条帖子：「智巡平台今天上线」"


def _items(graph_id: str, texts: list[str]) -> list[BatchAddItem]:
    return [BatchAddItem(type="graph_episode", graph_id=graph_id, data=text, data_type="text") for text in texts]


# ---------------------------------------------------------------------------
# Graphs
# ---------------------------------------------------------------------------


def test_create_get_and_delete_a_graph(local):
    created = local.graph.create(graph_id="mirofish_0123456789abcdef", name="Arrivals",
                                 description="MiroFish Social Simulation Graph")
    assert isinstance(created, Graph)
    assert created.graph_id == "mirofish_0123456789abcdef"
    assert created.name == "Arrivals"
    assert created.uuid_ and created.project_uuid == local.store.project_uuid
    assert created.created_at.endswith("Z")

    fetched = local.graph.get("mirofish_0123456789abcdef")  # positional, as the builder's reconcile does
    assert fetched.uuid_ == created.uuid_

    assert isinstance(local.graph.delete(graph_id="mirofish_0123456789abcdef"), SuccessResponse)
    with pytest.raises(NotFoundError):
        local.graph.get("mirofish_0123456789abcdef")


def test_delete_accepts_a_positional_graph_id(local):
    local.graph.create(graph_id="g-positional")
    local.graph.delete("g-positional")
    with pytest.raises(NotFoundError):
        local.graph.delete("g-positional")


def test_duplicate_graph_is_a_conflict(local):
    local.graph.create(graph_id="g1")
    with pytest.raises(ConflictError) as caught:
        local.graph.create(graph_id="g1")
    assert caught.value.status_code == 409
    assert not is_retryable_zep_error(caught.value)


@pytest.mark.parametrize("graph_id", ["", "has space", "x" * 256, None, 7])
def test_invalid_graph_ids_are_bad_requests(local, graph_id):
    with pytest.raises(BadRequestError):
        local.graph.create(graph_id=graph_id)


def test_missing_graph_errors_look_like_the_sdk(local):
    with pytest.raises(NotFoundError) as caught:
        local.graph.get("nope")
    error = caught.value
    assert isinstance(error, zep_cloud.NotFoundError)
    assert isinstance(error, ApiError)
    assert error.status_code == 404
    assert type(error).__module__.startswith("zep_cloud")
    assert graph_api._zep_status(error) == 404

    message = graph_api._public_build_error(error)
    assert message.startswith("Local memory request failed (HTTP 404)")
    assert "headers" not in message and "body" not in message and "nope" not in message

    # Missing resources are not retried by the shared read policy.
    calls = []

    def read():
        calls.append(1)
        return local.graph.get("nope")

    with pytest.raises(NotFoundError):
        call_zep_read_with_retry(read, operation_name="probe", sleep=lambda _s: None)
    assert calls == [1]


def test_delete_cancels_active_batch_items_and_the_batch(local):
    local.graph.create(graph_id="g1")
    batch = local.batch.create(metadata={"graph_id": "g1"})
    local.batch.add(batch.batch_id, items=_items("g1", ["Alice works for Acme.", "Bob works for Beta."]))
    local.batch.process(batch.batch_id)

    local.graph.delete(graph_id="g1")

    summary = local.batch.get(batch.batch_id)
    assert summary.status == "canceled"
    assert summary.progress.canceled_items == 2
    assert summary.progress.percent_complete == 100.0
    items = local.batch.list_items(batch.batch_id).items
    assert {item.status for item in items} == {"canceled"}
    # Nothing is left for the worker.
    stats = local.worker.drain()
    assert stats.windows == 0 and local.store.fts_integrity_check() == []
    with local.store.read() as conn:
        assert conn.execute("SELECT count(*) FROM episodes").fetchone()[0] == 0


def test_delete_leaves_other_graphs_alone(local):
    for graph_id in ("g1", "g2"):
        local.graph.create(graph_id=graph_id)
        local.graph.add(graph_id=graph_id, type="text", data=f"Alice works for Acme {graph_id}.")
    local.worker.drain()
    local.graph.delete("g1")
    assert [n.name for n in local.graph.node.get_by_graph_id("g2")]
    assert local.graph.search(query="Alice", graph_id="g2").edges


# ---------------------------------------------------------------------------
# graph.add and episodes
# ---------------------------------------------------------------------------


def test_document_add_is_queued_then_processed_by_the_worker(local, fake_llm):
    local.graph.create(graph_id="g1")
    episode = local.graph.add(graph_id="g1", type="text", data="Alice works for Acme.",
                              source_description="note", metadata={"origin": "test", "n": 1})
    assert isinstance(episode, Episode)
    assert episode.uuid_ and episode.processed is False
    assert episode.extraction_status == "queued"
    assert episode.content == "Alice works for Acme."
    assert episode.metadata == {"origin": "test", "n": 1}
    assert episode.source == "text" and episode.source_description == "note"

    local.worker.drain()

    done = local.graph.episode.get(uuid_=episode.uuid_)
    assert done.processed is True and done.extraction_status == "succeeded"
    assert fake_llm.call_count == 1
    assert "[episode 1]" in fake_llm.calls[0]["messages"][-1]["content"]
    names = sorted(node.name for node in local.graph.node.get_by_graph_id("g1"))
    assert names == ["Acme", "Alice"]


def test_add_created_at_is_normalized_and_becomes_the_episode_time(local):
    local.graph.create(graph_id="g1")
    episode = local.graph.add(graph_id="g1", type="message", data="Alice works for Acme.",
                              created_at="2026-05-10T17:00:00+08:00")
    assert episode.created_at == "2026-05-10T09:00:00.000000Z"
    with local.store.read() as conn:
        row = conn.execute("SELECT reference_time_explicit, created_at FROM episodes WHERE uuid = ?",
                           (episode.uuid_,)).fetchone()
    assert row["reference_time_explicit"] == 1
    assert row["created_at"] != episode.created_at  # ingestion time is stored separately


@pytest.mark.parametrize(
    "kwargs, error",
    [
        ({"user_id": "u1"}, BadRequestError),
        ({"graph_id": None}, BadRequestError),
        ({"graph_id": "missing"}, NotFoundError),
        ({"type": "fact_triple"}, BadRequestError),
        ({"data": ""}, BadRequestError),
        ({"data": "   "}, BadRequestError),
        ({"data": "x" * 10_001}, BadRequestError),
        ({"data": 42}, BadRequestError),
        ({"created_at": "yesterday"}, BadRequestError),
        ({"created_at": "2026-05-10T09:00:00"}, BadRequestError),  # no timezone
        ({"metadata": {"nested": {"a": 1}}}, BadRequestError),
        ({"metadata": ["not", "a", "dict"]}, BadRequestError),
        ({"strict_ontology": "yes"}, BadRequestError),
    ],
)
def test_add_validation(local, kwargs, error):
    local.graph.create(graph_id="g1")
    arguments = {"graph_id": "g1", "type": "text", "data": "Alice works for Acme."}
    arguments.update(kwargs)
    with pytest.raises(error):
        local.graph.add(**arguments)
    with local.store.read() as conn:
        assert conn.execute("SELECT count(*) FROM episodes").fetchone()[0] == 0


def test_add_accepts_exactly_ten_thousand_characters(local):
    local.graph.create(graph_id="g1")
    assert local.graph.add(graph_id="g1", type="json", data="x" * 10_000).uuid_


def test_activity_add_in_rules_mode_is_processed_immediately_without_llm(local, fake_llm):
    local.graph.create(graph_id="g1")
    episode = local.graph.add(graph_id="g1", type="text", data=ACTIVITY_TEXT,
                              created_at="2026-05-10T09:00:00+00:00", metadata=ACTIVITY_METADATA,
                              source_description="MiroFish simulation activity batch")
    assert episode.processed is True
    assert episode.extraction_status == "succeeded"
    assert fake_llm.call_count == 0
    edges = local.graph.edge.get_by_graph_id("g1")
    assert [edge.name for edge in edges] == ["POSTED"]
    assert edges[0].episodes == [episode.uuid_]


def test_activity_add_in_off_mode_is_skipped(local, monkeypatch):
    monkeypatch.setattr(local, "settings", local.settings.__class__(**{**local.settings.as_dict(),
                                                                      "activity_mode": "off"}))
    local.graph.create(graph_id="g1")
    episode = local.graph.add(graph_id="g1", type="text", data=ACTIVITY_TEXT, metadata=ACTIVITY_METADATA)
    assert episode.processed is True and episode.extraction_status == "skipped"
    assert local.graph.edge.get_by_graph_id("g1") == []
    # Still searchable in the episode scope.
    assert local.graph.search(query="智巡平台", graph_id="g1", scope="episodes").episodes


def test_episode_listing_and_mentions(local):
    local.graph.create(graph_id="g1")
    uuids = [local.graph.add(graph_id="g1", type="text", data=f"Person{i} works for Acme.").uuid_
             for i in range(3)]
    local.worker.drain()

    everything = local.graph.episode.get_by_graph_id("g1")
    assert isinstance(everything, EpisodeResponse)
    assert [e.uuid_ for e in everything.episodes] == uuids
    last_two = local.graph.episode.get_by_graph_id("g1", lastn=2)
    assert [e.uuid_ for e in last_two.episodes] == uuids[1:]
    with pytest.raises(BadRequestError):
        local.graph.episode.get_by_graph_id("g1", lastn=0)
    with pytest.raises(NotFoundError):
        local.graph.episode.get_by_graph_id("missing")

    mentions = local.graph.episode.mentions(uuids[0])
    assert isinstance(mentions, EpisodeMentions)
    assert {node.name for node in mentions.nodes} >= {"Person0", "Acme"}
    assert [edge.fact for edge in mentions.edges] == ["Person0 works for Acme."]
    assert local.graph.episode.get_nodes_and_edges(uuids[0]).edges[0].uuid_ == mentions.edges[0].uuid_
    with pytest.raises(NotFoundError):
        local.graph.episode.get(uuid_="missing")


# ---------------------------------------------------------------------------
# Nodes and edges
# ---------------------------------------------------------------------------


def _alice_graph(local) -> dict[str, str]:
    local.graph.create(graph_id="g1")
    local.graph.add(graph_id="g1", type="text", data="Alice works for Acme.")
    local.graph.add(graph_id="g1", type="text", data="Bob works for Alice.")
    local.worker.drain()
    return {node.name: node.uuid_ for node in local.graph.node.get_by_graph_id("g1")}


TYPES = {
    "Person": {"name": "Person", "description": "A person.", "properties": []},
    "Organization": {"name": "Organization", "description": "An organization.", "properties": []},
}


def test_node_get_is_global_and_shaped_like_the_sdk(local):
    local.graph.create(graph_id="g1")
    local.graph.set_ontology(entities=TYPES, graph_ids=["g1"])
    local.graph.add(graph_id="g1", type="text", data="Alice works for Acme.")
    local.worker.drain()
    nodes = {node.name: node.uuid_ for node in local.graph.node.get_by_graph_id("g1")}
    node = local.graph.node.get(uuid_=nodes["Alice"])
    assert node.name == "Alice"
    assert node.labels == ["Entity", "Person"]
    assert local.graph.node.get(nodes["Acme"]).labels == ["Entity", "Organization"]
    assert isinstance(node.summary, str) and isinstance(node.attributes, dict)
    assert node.created_at
    with pytest.raises(NotFoundError):
        local.graph.node.get(uuid_="missing")


def test_node_get_edges_returns_incoming_and_outgoing(local):
    nodes = _alice_graph(local)
    edges = local.graph.node.get_edges(node_uuid=nodes["Alice"])
    pairs = {(edge.source_node_uuid, edge.target_node_uuid) for edge in edges}
    assert pairs == {(nodes["Alice"], nodes["Acme"]), (nodes["Bob"], nodes["Alice"])}
    assert all(edge.episodes for edge in edges)
    with pytest.raises(NotFoundError):
        local.graph.node.get_edges(node_uuid="missing")
    episodes = local.graph.node.get_episodes(nodes["Alice"]).episodes
    assert len(episodes) == 2


def test_edge_get_and_temporal_fields(local):
    nodes = _alice_graph(local)
    edge = local.graph.node.get_edges(node_uuid=nodes["Acme"])[0]
    fetched = local.graph.edge.get(edge.uuid_)
    assert fetched.fact == "Alice works for Acme."
    assert fetched.name == "WORKS_FOR"
    assert fetched.invalid_at is None and fetched.expired_at is None
    assert fetched.episodes == edge.episodes
    with pytest.raises(NotFoundError):
        local.graph.edge.get("missing")


def test_node_and_edge_delete(local):
    nodes = _alice_graph(local)
    edge = local.graph.node.get_edges(node_uuid=nodes["Acme"])[0]
    local.graph.edge.delete(edge.uuid_)
    with pytest.raises(NotFoundError):
        local.graph.edge.get(edge.uuid_)
    local.graph.node.delete(nodes["Bob"])
    assert {n.name for n in local.graph.node.get_by_graph_id("g1")} == {"Alice", "Acme"}
    assert local.graph.edge.get_by_graph_id("g1") == []
    with pytest.raises(NotFoundError):
        local.graph.node.delete(nodes["Bob"])


def test_user_scoped_calls_are_unsupported(local):
    with pytest.raises(BadRequestError):
        local.graph.node.get_by_user_id("u1")
    with pytest.raises(BadRequestError):
        local.graph.edge.get_by_user_id("u1")


# ---------------------------------------------------------------------------
# Unsupported namespaces, project, search wiring
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("namespace", ["thread", "user", "context", "task"])
def test_unsupported_namespaces_raise_non_retryable_bad_requests(local, namespace):
    with pytest.raises(BadRequestError) as caught:
        getattr(local, namespace).list_all(page_size=1)
    assert caught.value.status_code == 400
    assert f"{namespace} is not supported by the local memory backend" in str(caught.value.body)
    assert not is_retryable_zep_error(caught.value)


def test_project_get_never_needs_the_network(local):
    info = local.project.get()
    assert isinstance(info, ProjectInfoResponse)
    assert info.project.uuid_ == local.store.project_uuid
    assert info.project.name == "Parthenon local memory"
    assert "mem.sqlite3" in info.project.description


def test_search_is_wired_to_the_searcher(local):
    _alice_graph(local)
    results = local.graph.search(query="Alice", graph_id="g1", scope="edges", reranker="rrf", limit=5)
    assert {edge.fact for edge in results.edges} == {"Alice works for Acme.", "Bob works for Alice."}
    with pytest.raises(NotFoundError):
        local.graph.search(query="Alice", graph_id="missing")
    with pytest.raises(BadRequestError):
        local.graph.search(query="Alice", graph_id="g1", reranker="bogus")


def test_the_client_advertises_its_ingestion_deadline(local):
    assert local.backend == "local"
    assert local.ingestion_wait_timeout_seconds == local.settings.ingestion_timeout_seconds


def test_closed_client_is_idempotent(local):
    local.close()
    local.close()
    assert local.closed and local.store.closed
