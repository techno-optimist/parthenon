"""The real services on the local backend, from graph build to report tools (spec §2.8, §10.2).

``GraphBuilderService``, ``ZepEntityReader``, ``ZepToolsService`` and
``OasisProfileGenerator`` are constructed **without** a Zep key; the worker
runs on its real background threads with ``FakeLLM``.
"""

from __future__ import annotations

import re
import time
from dataclasses import replace

import pytest

from app.config import Config
from app.memory import LocalZep, clear_local_memory_clients, register_local_memory_client
from app.services.graph_builder import GraphBuilderService
from app.services.oasis_profile_generator import OasisProfileGenerator
from app.services.zep_entity_reader import ZepEntityReader
from app.services.zep_tools import ZepToolsService
from app.utils.zep import MAX_ZEP_SEARCH_QUERY_CHARS

from conftest import text_block, works_for_extractor  # tests/local_memory/conftest.py

ONTOLOGY = {
    "entity_types": [
        {"name": "Person", "description": "A person involved in the story.",
         "attributes": [{"name": "role", "type": "text", "description": "Role or title"}]},
        {"name": "Organization", "description": "A company or institution.",
         "attributes": [{"name": "org_type", "type": "text", "description": "Kind of organization"}]},
    ],
    "edge_types": [
        {"name": "WORKS_FOR", "description": "A person works for an organization.",
         "attributes": [{"name": "position", "description": "Job title"}],
         "source_targets": [{"source": "Person", "target": "Organization"}]},
    ],
}

FIRST_CHUNKS = [
    "Alice Chen works for Acme Corp. She leads the wind turbine inspection program.",
    "Bob Stone works for Globex. He reviews every contract Acme Corp signs.",
    "Carla Diaz works for Acme Corp. She is its chief engineer.",
]
SECOND_CHUNKS = ["Alice Chen left Acme Corp in March 2026 to start her own company."]
_FACT_LINE = re.compile(r"^(F\d+): Alice Chen -WORKS_FOR-> Acme Corp", re.M)


def _extractor(messages):
    """Default "works for" extraction, plus an invalidation when Alice Chen leaves."""

    text = text_block(messages)
    if "left Acme Corp" in text:
        match = _FACT_LINE.search(messages[-1]["content"])
        return {
            "entities": [{"name": "Alice Chen", "type": "Person"}, {"name": "Acme Corp", "type": "Organization"}],
            "relations": [],
            "invalidated_facts": [{"id": match.group(1), "invalid_at": "2026-03"}] if match else [],
        }
    return works_for_extractor(messages)


def _wait_for(predicate, timeout=20.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def backend(memory_db_path, monkeypatch, fake_llm, memory_settings):
    monkeypatch.setattr(Config, "MEMORY_BACKEND", "local", raising=False)
    monkeypatch.setattr(Config, "ZEP_API_KEY", None)
    monkeypatch.setattr(Config, "LOCAL_MEMORY_DB_PATH", str(memory_db_path), raising=False)
    fake_llm.script = _extractor
    client = LocalZep(
        db_path=memory_db_path,
        settings=replace(memory_settings, window_chars=120, llm_concurrency=2, dedup_pass="off"),
        llm_client_factory=lambda: fake_llm,
        autostart_worker=True,
    )
    register_local_memory_client(client)
    yield client
    clear_local_memory_clients()


def test_build_read_search_and_report_without_a_zep_key(backend, fake_llm, monkeypatch):
    # -- build ---------------------------------------------------------------------
    builder = GraphBuilderService()
    assert builder.client is backend
    remembered = []
    graph_id = builder.create_graph("Arrivals", graph_id_callback=remembered.append)
    assert remembered == [graph_id] and graph_id.startswith("mirofish_")
    builder.set_ontology(graph_id, ONTOLOGY)

    journal = []
    submission = builder.add_text_batches(
        graph_id, FIRST_CHUNKS, batch_size=2,
        batch_created_callback=lambda batch_id, operation_id: journal.append((batch_id, operation_id)),
    )
    assert journal == [(None, submission.operation_id), (submission.batch_id, submission.operation_id)]
    assert len(submission.episode_uuids) == 3

    progress = []
    episode_uuids = builder._wait_for_batch(submission, lambda _msg, ratio: progress.append(ratio))
    assert episode_uuids == submission.episode_uuids
    assert progress[-1] == 1.0 and all(0.0 <= ratio <= 1.0 for ratio in progress)

    data = builder.get_graph_data(graph_id)
    assert data["node_count"] == len(data["nodes"]) >= 4
    nodes = {node["name"]: node for node in data["nodes"]}
    assert nodes["Alice Chen"]["labels"] == ["Entity", "Person"]
    assert nodes["Acme Corp"]["labels"] == ["Entity", "Organization"]
    works_for = [edge for edge in data["edges"] if edge["name"] == "WORKS_FOR"]
    assert len(works_for) == 3
    edge = next(e for e in works_for if e["source_node_name"] == "Alice Chen")
    assert edge["fact_type"] == "WORKS_FOR" and edge["target_node_name"] == "Acme Corp"
    assert edge["episodes"] == [submission.episode_uuids[0]]
    assert edge["created_at"] and edge["invalid_at"] is None

    # -- entity reader -----------------------------------------------------------------
    reader = ZepEntityReader()
    filtered = reader.filter_defined_entities(graph_id=graph_id, enrich_with_edges=True)
    assert {entity.name for entity in filtered.entities} >= {"Alice Chen", "Acme Corp", "Globex"}
    assert filtered.entity_types == {"Person", "Organization"}
    acme = reader.get_entity_with_context(graph_id, nodes["Acme Corp"]["uuid"])
    assert {e["direction"] for e in acme.related_edges} == {"incoming"}
    assert len(acme.related_edges) == 2
    alice = reader.get_entity_with_context(graph_id, nodes["Alice Chen"]["uuid"])
    assert [e["direction"] for e in alice.related_edges] == ["outgoing"]
    assert {n["name"] for n in alice.related_nodes} == {"Acme Corp"}
    assert reader.get_entity_with_context(graph_id, "missing-node") is None
    # Without a graph_id the local node.get_edges already returns both directions.
    assert len(reader.get_node_edges(nodes["Acme Corp"]["uuid"])) == 2

    # -- profile generation context ------------------------------------------------------
    generator = OasisProfileGenerator(api_key="test-llm-key", base_url="http://127.0.0.1:9/v1",
                                      graph_id=graph_id)
    assert generator.zep_client is backend
    alice_entity = next(e for e in filtered.entities if e.name == "Alice Chen")
    context = generator._search_zep_for_entity(alice_entity)
    assert any("Alice Chen" in fact for fact in context["facts"])

    # -- report tools ------------------------------------------------------------------
    tools = ZepToolsService()
    result = tools.search_graph(graph_id, "Who does Alice Chen work for?", limit=5)
    assert any("Alice Chen works for Acme Corp" in fact for fact in result.facts)
    assert tools.get_node_detail("missing-node") is None
    assert tools.get_node_detail(nodes["Alice Chen"]["uuid"]).name == "Alice Chen"

    queries = []
    original = backend.graph.search

    def recording_search(**kwargs):
        queries.append(kwargs["query"])
        return original(**kwargs)

    monkeypatch.setattr(backend.graph, "search", recording_search)
    tools.search_graph(graph_id, "Alice Chen " + "x" * 1000, limit=5)
    assert len(queries[-1]) == MAX_ZEP_SEARCH_QUERY_CHARS

    # -- a later batch invalidates a fact: panorama shows it as history ------------------
    second = builder.add_text_batches(graph_id, SECOND_CHUNKS, batch_size=2)
    assert _wait_for(lambda: backend.batch.get(second.batch_id).status == "succeeded")
    builder._wait_for_batch(second)
    invalidation_prompt = fake_llm.calls[-1]["messages"][-1]["content"]
    assert "EXISTING FACTS:" in invalidation_prompt and "Alice Chen -WORKS_FOR-> Acme Corp" in invalidation_prompt

    panorama = tools.panorama_search(graph_id, "Alice Chen Acme Corp")
    assert any("Alice Chen works for Acme Corp" in fact for fact in panorama.historical_facts)
    assert not any("Alice Chen works for Acme Corp" in fact for fact in panorama.active_facts)
    assert any("Carla Diaz works for Acme Corp" in fact for fact in panorama.active_facts)
    historical = next(f for f in panorama.historical_facts if "Alice Chen" in f)
    assert "2026-03-01" in historical

    # -- delete ----------------------------------------------------------------------------
    builder.delete_graph(graph_id)
    with pytest.raises(Exception) as caught:
        builder.get_graph_data(graph_id)
    assert getattr(caught.value, "status_code", None) == 404
