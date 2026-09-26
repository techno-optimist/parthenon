"""Keyset paging of nodes and edges through ``zep_paging`` (spec §2.4)."""

from __future__ import annotations

import pytest
from zep_cloud.errors import BadRequestError, NotFoundError
from zep_cloud.types import SearchFilters

from app.memory import LocalHttpResponse, encode_cursor
from app.utils.zep_paging import fetch_all_edges, fetch_all_nodes

NODE_COUNT = 7
EDGE_COUNT = 5


@pytest.fixture
def graph(local, seed):
    seed.graph("g1")
    nodes = [seed.node("g1", f"Node {i}", "Person" if i % 2 else None) for i in range(NODE_COUNT)]
    edges = [
        seed.edge("g1", nodes[i], nodes[i + 1], "KNOWS" if i % 2 else "WORKS_WITH", f"Node {i} knows Node {i + 1}.")
        for i in range(EDGE_COUNT)
    ]
    # A second graph must never leak into the listing.
    seed.graph("g2")
    other = seed.node("g2", "Elsewhere")
    seed.edge("g2", other, seed.node("g2", "Far"), "KNOWS", "Elsewhere knows Far.")
    return {"nodes": nodes, "edges": edges}


@pytest.mark.parametrize("page_size", [1, 2, 100])
def test_fetch_all_returns_every_row_once(local, graph, page_size):
    nodes = fetch_all_nodes(local, "g1", page_size=page_size)
    edges = fetch_all_edges(local, "g1", page_size=page_size)
    assert [node.uuid_ for node in nodes] == graph["nodes"]
    assert [edge.uuid_ for edge in edges] == graph["edges"]


def test_header_is_the_lowercase_zep_cursor_and_absent_on_the_last_page(local, graph):
    raw = local.graph.node.with_raw_response
    first = raw.get_by_graph_id("g1", limit=3)
    assert isinstance(first, LocalHttpResponse)
    assert list(first.headers) == ["zep-next-cursor"]
    second = raw.get_by_graph_id("g1", limit=3, cursor=first.headers["zep-next-cursor"])
    third = raw.get_by_graph_id("g1", limit=3, cursor=second.headers["zep-next-cursor"])
    assert len(third.data) == 1 and third.headers == {}
    assert second.headers["zep-next-cursor"] != first.headers["zep-next-cursor"]
    exact = raw.get_by_graph_id("g1", limit=NODE_COUNT)
    assert len(exact.data) == NODE_COUNT and exact.headers == {}


def test_descending_direction_and_its_cursor(local, graph):
    raw = local.graph.edge.with_raw_response
    first = raw.get_by_graph_id("g1", limit=2, direction="desc")
    assert [e.uuid_ for e in first.data] == graph["edges"][::-1][:2]
    # _fetch_all passes only the cursor on later pages; the cursor keeps the direction.
    rest = raw.get_by_graph_id("g1", limit=10, cursor=first.headers["zep-next-cursor"])
    assert [e.uuid_ for e in rest.data] == graph["edges"][::-1][2:]
    with pytest.raises(BadRequestError):
        raw.get_by_graph_id("g1", cursor=first.headers["zep-next-cursor"], direction="asc")


@pytest.mark.parametrize("cursor", ["garbage", "", "e30", encode_cursor("edge", "g1", 1),
                                    encode_cursor("node", "g2", 1)])
def test_bad_cursors_are_bad_requests(local, graph, cursor):
    with pytest.raises(BadRequestError):
        local.graph.node.with_raw_response.get_by_graph_id("g1", cursor=cursor)


def test_limit_rules(local, graph):
    with pytest.raises(BadRequestError):
        local.graph.node.get_by_graph_id("g1", limit=0)
    assert len(local.graph.node.get_by_graph_id("g1", limit=5000)) == NODE_COUNT
    assert len(local.graph.node.get_by_graph_id("g1")) == NODE_COUNT


def test_non_raw_methods_return_lists(local, graph):
    nodes = local.graph.node.get_by_graph_id("g1", limit=2)
    edges = local.graph.edge.get_by_graph_id("g1", limit=2)
    assert isinstance(nodes, list) and isinstance(edges, list)
    assert len(nodes) == len(edges) == 2
    assert edges[0].source_node_uuid == graph["nodes"][0]


def test_order_by_and_uuid_cursor(local, graph):
    by_uuid = local.graph.node.get_by_graph_id("g1", order_by="uuid")
    assert [n.uuid_ for n in by_uuid] == graph["nodes"]  # documented: id order
    after = local.graph.node.get_by_graph_id("g1", uuid_cursor=graph["nodes"][2])
    assert [n.uuid_ for n in after] == graph["nodes"][3:]
    with pytest.raises(BadRequestError):
        local.graph.node.get_by_graph_id("g1", order_by="name")
    with pytest.raises(BadRequestError):
        local.graph.node.get_by_graph_id("g1", uuid_cursor="missing")


def test_filters(local, graph):
    people = local.graph.node.get_by_graph_id("g1", filters=SearchFilters(node_labels=["Person"]))
    assert {n.uuid_ for n in people} == {graph["nodes"][i] for i in range(NODE_COUNT) if i % 2}
    generic = local.graph.node.get_by_graph_id("g1", filters={"exclude_node_labels": ["Person"]})
    assert {n.uuid_ for n in generic} == {graph["nodes"][i] for i in range(NODE_COUNT) if not i % 2}
    knows = local.graph.edge.get_by_graph_id("g1", filters=SearchFilters(edge_types=["KNOWS"]))
    assert {e.name for e in knows} == {"KNOWS"} and len(knows) == 2
    others = local.graph.edge.get_by_graph_id("g1", filters={"exclude_edge_types": ["KNOWS"]})
    assert {e.name for e in others} == {"WORKS_WITH"}


def test_edge_listing_includes_invalidated_edges(local, graph):
    with local.store.write() as conn:
        conn.execute("UPDATE edges SET invalid_at = ?, expired_at = ? WHERE uuid = ?",
                     ("2026-01-01T00:00:00.000000Z", "2026-02-01T00:00:00.000000Z", graph["edges"][0]))
    edges = {edge.uuid_: edge for edge in fetch_all_edges(local, "g1")}
    assert len(edges) == EDGE_COUNT
    assert edges[graph["edges"][0]].invalid_at == "2026-01-01T00:00:00.000000Z"
    assert edges[graph["edges"][0]].expired_at == "2026-02-01T00:00:00.000000Z"


def test_missing_graph_is_not_found(local):
    with pytest.raises(NotFoundError):
        fetch_all_nodes(local, "missing", retry_delay=0)
