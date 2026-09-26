"""Document extraction, entity resolution and the LLM call policy (spec §4.2-§4.9).

Every LLM call goes through ``FakeLLM``; sleeps are recorded, never slept.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import openai
import pytest

from app.memory import LocalMemorySettings, apply_set_ontology, load_ontology, new_id, utcnow_iso
from app.memory.extraction import (
    DOCUMENT_SYSTEM_PROMPT,
    RETURN_SHAPE,
    BadOutputError,
    ExtractionLLM,
    FatalLLMError,
    Throttle,
    WindowFailedError,
    build_document_messages,
    claim_window,
    classify_llm_error,
    extract_next_window,
    find_known_entities,
    gather_prompt_context,
    parse_dedup_decisions,
    parse_extraction,
    process_window,
    run_dedup_pass,
    select_window_rows,
    strip_overlap,
)
from app.memory.models import json_loads
from app.memory.resolution import (
    EpisodeRef,
    find_dedup_candidates,
    group_confirmed_pairs,
    load_dedup_nodes,
    merge_summary,
    write_extraction,
)
from app.utils.file_parser import split_text_into_chunks
from app.utils.llm_client import LLMResponseError

GRAPH = "g1"

PERSON = {"name": "Person", "description": "A person.", "properties": [
    {"name": "full_name", "type": "Text", "description": "Full name"},
    {"name": "role", "type": "Text", "description": "Role or title"},
    {"name": "entity_summary", "type": "Text", "description": "Reserved name, prefixed"},
]}
ORGANIZATION = {"name": "Organization", "description": "A company or group.", "properties": [
    {"name": "org_type", "type": "Text", "description": "Kind of organization"},
]}
PRODUCT = {"name": "Product", "description": "A product.", "properties": []}
WORKS_FOR = ({"name": "WORKS_FOR", "description": "A person works for an organization.", "properties": [
    {"name": "position", "type": "Text", "description": "Position held"},
]}, [{"source": "Person", "target": "Organization"}])
MENTIONS = ({"name": "MENTIONS", "description": "Any entity mentions another.", "properties": []}, [])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def store(local):
    return local.store


@pytest.fixture
def graph(seed) -> str:
    return seed.graph(GRAPH)


@pytest.fixture
def ontology_graph(store, graph) -> str:
    apply_set_ontology(store, {"Person": PERSON, "Organization": ORGANIZATION, "Product": PRODUCT},
                       {"WORKS_FOR": WORKS_FOR, "MENTIONS": MENTIONS}, graph_ids=[graph])
    return graph


@pytest.fixture
def sleeps() -> list[float]:
    return []


@pytest.fixture
def llm(local, fake_llm, sleeps) -> ExtractionLLM:
    return ExtractionLLM(lambda: fake_llm, local.settings, sleep=sleeps.append, store=local.store)


def insert_batch(store, graph_id: str, texts: list[str], *, reference_times: list[str | None] | None = None,
                 batch_id: str | None = None, start: int = 0, status: str = "queued",
                 strict: bool = False) -> tuple[str, list[str]]:
    """A processed batch: queued episodes plus their queued items."""

    now = utcnow_iso()
    batch_id = batch_id or new_id()
    uuids: list[str] = []
    with store.write() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO batches(batch_id, status, item_count, created_at, updated_at) "
            "VALUES (?, 'queued', 0, ?, ?)",
            (batch_id, now, now),
        )
        for offset, text in enumerate(texts):
            index = start + offset
            explicit = reference_times[offset] if reference_times else None
            episode_uuid = new_id()
            conn.execute(
                "INSERT INTO episodes(uuid, graph_id, kind, content, source, reference_time, "
                "reference_time_explicit, created_at, queued_at, extraction_status, batch_id, sequence_index, "
                "strict_ontology) VALUES (?, ?, 'document', ?, 'text', ?, ?, ?, ?, ?, ?, ?, ?)",
                (episode_uuid, graph_id, text, explicit or now, int(explicit is not None), now, now, status,
                 batch_id, index, int(strict)),
            )
            conn.execute(
                "INSERT INTO batch_items(item_id, batch_id, sequence_index, graph_id, episode_uuid, status, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (new_id(), batch_id, index, graph_id, episode_uuid, status, now, now),
            )
            uuids.append(episode_uuid)
        conn.execute("UPDATE batches SET item_count = item_count + ? WHERE batch_id = ?", (len(texts), batch_id))
    return batch_id, uuids


def insert_standalone(store, graph_id: str, text: str, *, reference_time: str | None = None) -> str:
    now = utcnow_iso()
    episode_uuid = new_id()
    with store.write() as conn:
        conn.execute(
            "INSERT INTO episodes(uuid, graph_id, kind, content, source, reference_time, "
            "reference_time_explicit, created_at, queued_at, extraction_status) "
            "VALUES (?, ?, 'document', ?, 'text', ?, ?, ?, ?, 'queued')",
            (episode_uuid, graph_id, text, reference_time or now, int(reference_time is not None), now, now),
        )
    return episode_uuid


def episode_refs(seed, graph_id: str, *contents: str, explicit: list[str | None] | None = None) -> list[EpisodeRef]:
    refs = []
    for index, content in enumerate(contents):
        uuid = seed.episode(graph_id, content)
        time = explicit[index] if explicit else None
        refs.append(EpisodeRef(uuid, content, time or utcnow_iso(), time is not None, index))
    return refs


def apply(store, graph_id: str, payload: dict[str, Any], episodes: list[EpisodeRef], *,
          fact_map: dict[str, str] | None = None, strict: bool = False):
    result = parse_extraction(payload)
    with store.write() as conn:
        return write_extraction(
            conn, graph_id, entities=result.entities, relations=result.relations,
            invalidated_facts=result.invalidated_facts, episodes=episodes,
            ontology=load_ontology(conn, graph_id), fact_map=fact_map or {}, strict=strict, summary_cap=800,
        )


def rows(store, sql: str, *params: Any) -> list[dict[str, Any]]:
    with store.read() as conn:
        return [dict(row) for row in conn.execute(sql, params)]


def nodes(store, graph_id: str = GRAPH) -> dict[str, dict[str, Any]]:
    return {row["name"]: row for row in rows(store, "SELECT * FROM nodes WHERE graph_id = ? ORDER BY id", graph_id)}


def edges(store, graph_id: str = GRAPH) -> list[dict[str, Any]]:
    return rows(store, "SELECT * FROM edges WHERE graph_id = ? ORDER BY id", graph_id)


def edge_episodes(store, edge_uuid: str) -> list[str]:
    return [r["episode_uuid"] for r in rows(
        store, "SELECT episode_uuid FROM edge_episodes WHERE edge_uuid = ? ORDER BY rowid", edge_uuid)]


def items(store, batch_id: str) -> list[dict[str, Any]]:
    return rows(store, "SELECT * FROM batch_items WHERE batch_id = ? ORDER BY sequence_index", batch_id)


def entity(name: str, type_: str = "Entity", **extra: Any) -> dict[str, Any]:
    return {"name": name, "type": type_, **extra}


def relation(source: str, target: str, type_: str, fact: str, **extra: Any) -> dict[str, Any]:
    return {"source": source, "target": target, "type": type_, "fact": fact, **extra}


def response(entities=(), relations=(), invalidated=()) -> dict[str, Any]:
    return {"entities": list(entities), "relations": list(relations), "invalidated_facts": list(invalidated)}


# ---------------------------------------------------------------------------
# Window packing (§4.2)
# ---------------------------------------------------------------------------


def test_select_window_rows_caps_chars_and_requires_consecutive_sequence():
    def row(seq, n, batch="b1", graph="g"):
        return {"id": seq + 1, "uuid": f"e{seq}", "graph_id": graph, "batch_id": batch, "sequence_index": seq, "n": n}

    assert [r["uuid"] for r in select_window_rows([row(0, 1500), row(1, 1500), row(2, 1500)], 4000)] == ["e0", "e1"]
    # A gap in sequence_index stops the window.
    assert [r["uuid"] for r in select_window_rows([row(0, 10), row(2, 10)], 4000)] == ["e0"]
    # Another batch never joins the window.
    assert [r["uuid"] for r in select_window_rows([row(0, 10), row(1, 10, batch="b2")], 4000)] == ["e0"]
    # One oversized chunk is still taken on its own.
    assert [r["uuid"] for r in select_window_rows([row(0, 9000), row(1, 10)], 4000)] == ["e0"]
    assert select_window_rows([], 4000) == []


def test_claim_window_leases_episodes_and_marks_items_and_batch(store, graph, local):
    batch_id, uuids = insert_batch(store, graph, ["a" * 1500, "b" * 1500, "c" * 1500])
    window = claim_window(store, local.settings, owner="host:1:0", clock=lambda: 1000.0)

    assert window is not None
    assert window.episode_uuids == uuids[:2]
    assert window.batch_id == batch_id and window.graph_id == graph
    assert [e.chunk for e in window.episodes] == [0, 1]
    claimed = rows(store, "SELECT uuid, extraction_status, lease_owner, lease_until, attempts FROM episodes "
                          "WHERE batch_id = ? ORDER BY sequence_index", batch_id)
    assert [r["extraction_status"] for r in claimed] == ["processing", "processing", "queued"]
    assert claimed[0]["lease_owner"] == "host:1:0"
    assert claimed[0]["lease_until"] == 1000.0 + local.settings.lease_seconds
    assert claimed[0]["attempts"] == 1
    assert [i["status"] for i in items(store, batch_id)] == ["processing", "processing", "queued"]
    assert rows(store, "SELECT status FROM batches WHERE batch_id = ?", batch_id)[0]["status"] == "processing"

    second = claim_window(store, local.settings, owner="host:1:0")
    assert second.episode_uuids == uuids[2:]
    assert claim_window(store, local.settings, owner="host:1:0") is None


def test_claim_window_never_mixes_batches(store, graph, local):
    first_batch, first = insert_batch(store, graph, ["one", "two"])
    second_batch, second = insert_batch(store, graph, ["three"])
    windows = [claim_window(store, local.settings, owner="w"), claim_window(store, local.settings, owner="w")]
    assert sorted(len(w.episodes) for w in windows) == [1, 2]
    for window in windows:
        assert {e.batch_id for e in window.episodes} == {window.batch_id}
    assert {tuple(w.episode_uuids) for w in windows} == {tuple(first), tuple(second)}


def test_standalone_episodes_use_episode_markers_with_explicit_time(store, graph, local):
    insert_standalone(store, graph, "Dana works for Initech.", reference_time="2026-05-10T09:00:00.000000Z")
    insert_standalone(store, graph, "Eve works for Hooli.")
    window = claim_window(store, local.settings, owner="w")
    assert len(window.episodes) == 2
    assert window.text.splitlines() == [
        "[episode 1 | time 2026-05-10T09:00:00Z]", "Dana works for Initech.",
        "[episode 2]", "Eve works for Hooli.",
    ]
    assert window.reference_time == "2026-05-10T09:00:00.000000Z"


def test_overlap_between_consecutive_chunks_is_stripped(store, graph, local):
    text = " ".join(f"Sentence number {i} talks about the local memory backend." for i in range(40))
    chunks = split_text_into_chunks(text, chunk_size=500, overlap=50)
    assert len(chunks) >= 3
    stripped = strip_overlap(chunks[0], chunks[1])
    assert len(stripped) < len(chunks[1]) and chunks[1].endswith(stripped)
    assert (chunks[0] + " " + stripped).count(stripped) == 1
    # Overlaps shorter than 20 characters are left alone.
    assert strip_overlap("abc the end", "the end continues") == "the end continues"

    insert_batch(store, graph, chunks[:3])
    window = claim_window(store, local.settings, owner="w")
    rendered = window.text
    assert rendered.startswith("[chunk 0]\n")
    assert "[chunk 1]" in rendered and "[chunk 2]" in rendered
    # Every sentence appears exactly once although the chunks overlap.
    for i in range(3, 10):
        assert rendered.count(f"Sentence number {i} ") <= 1
    assert len(rendered) < sum(len(c) for c in chunks[:3]) + 40


# ---------------------------------------------------------------------------
# Prompt (§4.4)
# ---------------------------------------------------------------------------


def test_prompt_contains_ontology_known_entities_and_existing_facts(store, ontology_graph, seed, local):
    alice = seed.node(GRAPH, "Alice Chen", "Person", aliases=("Alice",))
    acme = seed.node(GRAPH, "Acme Corp", "Organization")
    zed = seed.node(GRAPH, "Zed", None)
    with store.write() as conn:
        conn.execute("UPDATE nodes SET mention_count = 50 WHERE uuid = ?", (zed,))
    fact = seed.edge(GRAPH, alice, acme, "WORKS_FOR", "Alice Chen is the CEO of Acme Corp.")
    seed.edge(GRAPH, zed, acme, "MENTIONS", "Zed mentions Acme Corp.")  # Zed is not in the text
    with store.write() as conn:
        conn.execute("UPDATE edges SET valid_at = '2021-01-01T00:00:00.000000Z' WHERE uuid = ?", (fact,))
    insert_batch(store, GRAPH, ["Alice was replaced as CEO last year."])
    window = claim_window(store, local.settings, owner="w")

    with store.read(snapshot=True) as conn:
        context = gather_prompt_context(conn, window, local.settings)
    system, user = build_document_messages(window, context, local.settings)

    assert system["content"] == DOCUMENT_SYSTEM_PROMPT.format(max_entities=30, max_relations=50)
    prompt = user["content"]
    assert "ENTITY TYPES:\n- Person: A person. Attributes: full_name (Full name), role (Role or title)" in prompt
    assert "- Organization: A company or group. Attributes: org_type (Kind of organization)" in prompt
    assert "- WORKS_FOR: A person works for an organization. Allowed: Person -> Organization." in prompt
    assert "- MENTIONS: Any entity mentions another. Allowed: Entity -> Entity." in prompt
    # Mentioned entities first (Alice via her alias), then the most mentioned ones.
    assert "KNOWN ENTITIES (reuse these exact names): Alice Chen [Person]; Zed [Entity]; Acme Corp [Organization]" in prompt
    # Only facts touching mentioned nodes are offered.
    assert 'F1: Alice Chen -WORKS_FOR-> Acme Corp: "Alice Chen is the CEO of Acme Corp." (valid_at 2021-01-01)' in prompt
    assert "Zed mentions" not in prompt
    assert context.fact_map == {"F1": fact}
    assert prompt.index("TEXT:\n<<<\n[chunk 0]\nAlice was replaced") > prompt.index("EXISTING FACTS:")
    # The return shape is a concrete one-item example so models use "source"/"target" keys.
    assert prompt.rstrip().endswith(RETURN_SHAPE)
    assert '"source":"<entity name>","target":"<entity name>"' in RETURN_SHAPE


def test_prompt_without_ontology_uses_generic_types(store, graph, local):
    insert_batch(store, graph, ["Nothing known yet."])
    window = claim_window(store, local.settings, owner="w")
    with store.read() as conn:
        context = gather_prompt_context(conn, window, local.settings)
    prompt = build_document_messages(window, context, local.settings)[1]["content"]
    assert 'ENTITY TYPES: (none, use "Entity")' in prompt
    assert "RELATION TYPES: (none, use free-form)" in prompt
    assert "KNOWN ENTITIES (reuse these exact names): (none)" in prompt
    assert "EXISTING FACTS:\n(none)" in prompt


def test_short_latin_keys_must_match_as_words(store, graph, seed):
    ai = seed.node(GRAPH, "AI", None)
    with store.read() as conn:
        _, mentioned = find_known_entities(conn, GRAPH, "She said nothing.", limit=10)
        assert ai not in mentioned
        _, mentioned = find_known_entities(conn, GRAPH, "AI labs grew.", limit=10)
        assert mentioned == [ai]


# ---------------------------------------------------------------------------
# Output validation (§4.5)
# ---------------------------------------------------------------------------


def test_parse_extraction_accepts_synonyms_and_drops_bad_entries():
    result = parse_extraction({
        "nodes": [{"name": "Alice", "entity_type": "Person"}, {"type": "Person"}, "Bob", 42],
        "relationships": [
            {"from": "Alice", "to": "Bob", "relation_type": "knows", "fact": "Alice knows Bob.", "chunks": ["chunk 3", 4]},
            {"source": "Alice", "target": "Bob", "label": "MET", "fact": "Alice met Bob."},
            {"source": "Alice", "target": "Bob"},  # no fact
            "not a relation",
        ],
        "invalidated_facts": ["F2", {"id": "f3", "invalid_at": "2024"}, 5, {"id": "nope"}],
    })
    assert [(e.name, e.type) for e in result.entities] == [("Alice", "Person"), ("Bob", None)]
    assert [(r.source, r.target, r.type, r.chunks) for r in result.relations] == [
        ("Alice", "Bob", "knows", [3, 4]), ("Alice", "Bob", "MET", []),
    ]
    assert [(i.id, i.invalid_at) for i in result.invalidated_facts] == [("F2", None), ("F3", "2024"), ("F5", None)]
    assert result.dropped == 4


def test_parse_extraction_truncates_and_coerces_values():
    result = parse_extraction({
        "entities": [{
            "name": "N" * 250,
            "aliases": ["a1", "a2", "a3", "a4", "a5", "a6", "N" * 250],
            "summary": "s" * 700,
            "attributes": {"role": "CEO", "age": 41, "empty": "", "x": None, "u": "Unknown", "cn": "未知",
                           "na": "N/A", "long": "v" * 400, "tags": ["a", "b"]},
        }] + [{"name": f"E{i}"} for i in range(40)],
        "relations": [{"source": "A", "target": "B", "fact": "f" * 1200, "valid_at": 2021}] * 60,
    }, max_entities=30, max_relations=50)
    first = result.entities[0]
    assert len(first.name) == 200
    assert first.aliases == ["a1", "a2", "a3", "a4", "a5"]
    assert len(first.summary) == 600
    assert first.attributes == {"role": "CEO", "age": "41", "long": "v" * 300, "tags": "a, b"}
    assert len(result.entities) == 30 and len(result.relations) == 50
    assert len(result.relations[0].fact) == 1000
    assert result.relations[0].valid_at == "2021"


def test_parse_extraction_without_entities_or_relations_is_bad_output():
    with pytest.raises(LLMResponseError, match="missing entities/relations"):
        parse_extraction({"facts": []})
    with pytest.raises(LLMResponseError):
        parse_extraction({"entities": None, "relations": "nope"})
    assert parse_extraction({"relations": []}).entities == []


# ---------------------------------------------------------------------------
# Entity resolution (§4.6)
# ---------------------------------------------------------------------------


def test_entity_types_map_to_ontology_or_fall_back_to_generic(store, ontology_graph, seed):
    episodes = episode_refs(seed, GRAPH, "Alice, Acme and Initech appear.")
    apply(store, GRAPH, response([
        entity("Alice", "person"), entity("Acme", "organization"), entity("Initech", "Company"),
        entity("Hooli", "Entity"), entity("Pied Piper", ""),
    ]), episodes)
    found = nodes(store)
    assert json.loads(found["Alice"]["labels_json"]) == ["Entity", "Person"]
    assert found["Acme"]["entity_type"] == "Organization"
    for name in ("Initech", "Hooli", "Pied Piper"):
        assert json.loads(found[name]["labels_json"]) == ["Entity"]
        assert found[name]["entity_type"] is None


def test_attributes_are_filtered_to_the_ontology_safe_names(store, ontology_graph, seed):
    episodes = episode_refs(seed, GRAPH, "Alice Chen is the CEO.")
    apply(store, GRAPH, response([
        entity("Alice Chen", "Person", attributes={
            "Full Name": "Alice Chen", "role": "CEO", "entity_summary": "x", "summary": "dropped", "bogus": "z"}),
        entity("Hooli", "Entity", attributes={"role": "dropped for generic"}),
    ]), episodes)
    found = nodes(store)
    assert json.loads(found["Alice Chen"]["attributes_json"]) == {
        "entity_summary": "x", "full_name": "Alice Chen", "role": "CEO"}
    assert "role: CEO" in found["Alice Chen"]["attributes_text"]
    assert json.loads(found["Hooli"]["attributes_json"]) == {}


def test_alias_and_honorific_forms_resolve_to_the_existing_node(store, ontology_graph, seed):
    wang = seed.node(GRAPH, "Wang Wei", "Person")
    wang_cn = seed.node(GRAPH, "王伟", "Person")
    episodes = episode_refs(seed, GRAPH, "Mr. Wang Wei met 王伟先生.")
    apply(store, GRAPH, response([entity("Mr. Wang Wei", "Person"), entity("王伟先生", "Person")]), episodes)
    found = nodes(store)
    assert set(found) == {"Wang Wei", "王伟"}
    assert found["Wang Wei"]["uuid"] == wang and found["Wang Wei"]["mention_count"] == 2
    assert "Mr. Wang Wei" in found["Wang Wei"]["aliases_text"]
    assert found["王伟"]["uuid"] == wang_cn and found["王伟"]["mention_count"] == 2
    # The new surface forms are registered as alias keys for next time.
    keys = {r["alias_key"] for r in rows(store, "SELECT alias_key FROM node_aliases WHERE node_uuid = ?", wang)}
    assert {"wangwei", "mrwangwei"} <= keys


def test_generic_node_is_upgraded_to_the_typed_entity(store, ontology_graph, seed):
    acme = seed.node(GRAPH, "Acme Corp", None)
    episodes = episode_refs(seed, GRAPH, "Acme Corp is a company.")
    apply(store, GRAPH, response([entity("Acme Corp", "Organization", summary="Acme Corp is a company.")]), episodes)
    found = nodes(store)["Acme Corp"]
    assert found["uuid"] == acme
    assert json.loads(found["labels_json"]) == ["Entity", "Organization"]
    assert found["summary"] == "Acme Corp is a company."


def test_homonyms_of_different_types_stay_separate(store, ontology_graph, seed):
    apple_org = seed.node(GRAPH, "Apple", "Organization")
    episodes = episode_refs(seed, GRAPH, "Apple the fruit.")
    apply(store, GRAPH, response([entity("Apple", "Product")]), episodes)
    found = rows(store, "SELECT uuid, entity_type FROM nodes WHERE name = 'Apple' ORDER BY id")
    assert [r["entity_type"] for r in found] == ["Organization", "Product"]
    assert found[0]["uuid"] == apple_org
    # A generic mention reuses the most mentioned candidate instead of creating a third node.
    apply(store, GRAPH, response([entity("Apple")]), episodes)
    assert len(rows(store, "SELECT 1 FROM nodes WHERE name = 'Apple'")) == 2


def test_node_name_grows_to_a_longer_containing_name(store, graph, seed):
    alice = seed.node(GRAPH, "Alice", None)
    episodes = episode_refs(seed, GRAPH, "Alice Chen spoke.")
    apply(store, GRAPH, response([entity("Alice Chen", aliases=["Alice"])]), episodes)
    found = nodes(store)
    assert list(found) == ["Alice Chen"] and found["Alice Chen"]["uuid"] == alice
    assert found["Alice Chen"]["name_key"] == "alicechen"
    assert "Alice" in found["Alice Chen"]["aliases_text"].split(" | ")


def test_same_window_entities_sharing_an_alias_merge(store, graph, seed):
    episodes = episode_refs(seed, GRAPH, "IBM, also International Business Machines.")
    apply(store, GRAPH, response([
        entity("International Business Machines", aliases=["IBM"], summary="A computer company."),
        entity("IBM", summary="It makes mainframes."),
    ]), episodes)
    found = nodes(store)
    assert list(found) == ["International Business Machines"]
    assert found["International Business Machines"]["summary"] == "A computer company. It makes mainframes."


def test_merge_summary_dedups_and_respects_the_cap():
    assert merge_summary("", "Alice is a CEO. She lives in Paris.", 800) == "Alice is a CEO. She lives in Paris."
    assert merge_summary("Alice is a CEO.", "Alice is a CEO. Alice is a CEO!", 800) == "Alice is a CEO."
    assert merge_summary("Alice is the CEO of Acme.", "Alice is the CEO of Acme Inc.", 800) == "Alice is the CEO of Acme."
    assert merge_summary("Alice is a CEO.", "She founded Acme.", 800) == "Alice is a CEO. She founded Acme."
    capped = merge_summary("A" * 30 + ".", "Second sentence here. Third one.", 50)
    assert capped == "A" * 30 + "." and len(capped) <= 50
    assert merge_summary("", "x" * 100, 40) == "x" * 40
    assert merge_summary("爱丽丝是首席执行官。", "她住在巴黎。", 800) == "爱丽丝是首席执行官。她住在巴黎。"


# ---------------------------------------------------------------------------
# Edges (§4.7)
# ---------------------------------------------------------------------------


def test_edge_types_allowed_swapped_relates_to_and_free_form(store, ontology_graph, seed):
    episodes = episode_refs(seed, GRAPH, "Alice, Bob, Acme and Zeta.")
    apply(store, GRAPH, response(
        [entity("Alice", "Person"), entity("Bob", "Person"), entity("Acme", "Organization"),
         entity("Zeta", "Organization")],
        [
            relation("Alice", "Acme", "works for", "Alice works for Acme.", attributes={"position": "CEO", "x": "y"}),
            relation("Acme", "Bob", "WORKS_FOR", "Bob works for Acme."),
            relation("Acme", "Zeta", "WORKS_FOR", "Acme works for Zeta."),
            relation("Alice", "Zeta", "criticizes", "Alice criticizes Zeta."),
        ],
    ), episodes)
    by_fact = {e["fact"]: e for e in edges(store)}
    ids = {name: row["uuid"] for name, row in nodes(store).items()}

    allowed = by_fact["Alice works for Acme."]
    assert (allowed["name"], allowed["source_node_uuid"], allowed["target_node_uuid"]) == (
        "WORKS_FOR", ids["Alice"], ids["Acme"])
    assert json.loads(allowed["attributes_json"]) == {"position": "CEO"}
    swapped = by_fact["Bob works for Acme."]
    assert (swapped["source_node_uuid"], swapped["target_node_uuid"]) == (ids["Bob"], ids["Acme"])
    assert by_fact["Acme works for Zeta."]["name"] == "RELATES_TO"
    free = by_fact["Alice criticizes Zeta."]
    assert free["name"] == "CRITICIZES" and json.loads(free["attributes_json"]) == {}


def test_strict_ontology_drops_untyped_entities_and_free_form_relations(store, ontology_graph, seed):
    episodes = episode_refs(seed, GRAPH, "Alice, Acme and a gadget.")
    stats = apply(store, GRAPH, response(
        [entity("Alice", "Person"), entity("Acme", "Organization"), entity("Gadget", "Thing")],
        [
            relation("Alice", "Acme", "WORKS_FOR", "Alice works for Acme."),
            relation("Alice", "Acme", "LIKES", "Alice likes Acme."),
            relation("Alice", "Gadget", "MENTIONS", "Alice mentions the gadget."),
            relation("Alice", "Nobody", "MENTIONS", "Alice mentions Nobody."),
        ],
    ), episodes, strict=True)
    assert set(nodes(store)) == {"Alice", "Acme"}
    assert [e["fact"] for e in edges(store)] == ["Alice works for Acme."]
    assert stats.entities_dropped == 1 and stats.relations_dropped == 3


def test_self_loops_are_dropped_and_unknown_endpoints_become_generic_nodes(store, graph, seed):
    episodes = episode_refs(seed, GRAPH, "Alice praised herself and met Carol.")
    stats = apply(store, GRAPH, response(
        [entity("Alice Chen", aliases=["Alice"])],
        [
            relation("Alice", "Alice Chen", "PRAISES", "Alice praised herself."),
            relation("Alice Chen", "Carol", "MET", "Alice met Carol."),
        ],
    ), episodes)
    found = nodes(store)
    assert set(found) == {"Alice Chen", "Carol"}
    assert found["Carol"]["entity_type"] is None and found["Carol"]["summary"] == ""
    assert [e["fact"] for e in edges(store)] == ["Alice met Carol."]
    assert stats.relations_dropped == 1 and stats.nodes_created == 2


def test_duplicate_facts_link_episodes_instead_of_new_edges(store, graph, seed):
    first = episode_refs(seed, GRAPH, "Alice works for Acme.")
    second = episode_refs(seed, GRAPH, "Again: Alice works for Acme!")
    payload = response([entity("Alice"), entity("Acme")],
                       [relation("Alice", "Acme", "WORKS_FOR", "Alice works for Acme.")])
    apply(store, GRAPH, payload, first)
    stats = apply(store, GRAPH, response(
        [entity("Alice"), entity("Acme")],
        [relation("Acme", "Alice", "WORKS_FOR", "Alice works for Acme", attributes={"a": "b"})],
    ), second)
    assert stats.edges_merged == 1 and stats.edges_created == 0
    [edge] = edges(store)
    assert edge_episodes(store, edge["uuid"]) == [first[0].uuid, second[0].uuid]
    # A different fact on the same pair is a new edge.
    apply(store, GRAPH, response([], [relation("Alice", "Acme", "WORKS_FOR", "Alice leads the Acme lab in Paris.")]),
          second)
    assert len(edges(store)) == 2


def test_valid_at_from_the_relation_or_the_explicit_reference_time(store, graph, seed):
    episodes = episode_refs(seed, GRAPH, "Alice met Bob.", "Carol met Dan.", "Eve met Fay.",
                            explicit=[None, "2026-05-10T09:00:00.000000Z", None])
    apply(store, GRAPH, response([], [
        relation("Alice", "Bob", "MET", "Alice met Bob.", valid_at="2021", invalid_at="2023-06-01", chunks=[0]),
        relation("Carol", "Dan", "MET", "Carol met Dan.", chunks=[1]),
        relation("Eve", "Fay", "MET", "Eve met Fay.", chunks=[2]),
        relation("Alice", "Fay", "MET", "Alice met Fay.", valid_at="sometime", chunks=[0]),
    ]), episodes)
    by_fact = {e["fact"]: e for e in edges(store)}
    assert by_fact["Alice met Bob."]["valid_at"] == "2021-01-01T00:00:00.000000Z"
    assert by_fact["Alice met Bob."]["invalid_at"] == "2023-06-01T00:00:00.000000Z"
    assert by_fact["Alice met Bob."]["expired_at"] is None
    assert by_fact["Carol met Dan."]["valid_at"] == "2026-05-10T09:00:00.000000Z"
    assert by_fact["Eve met Fay."]["valid_at"] is None
    assert by_fact["Alice met Fay."]["valid_at"] is None


def test_invalidated_facts_set_invalid_and_expired_and_ignore_unknown_ids(store, graph, seed):
    alice = seed.node(GRAPH, "Alice", None)
    acme = seed.node(GRAPH, "Acme", None)
    old = seed.edge(GRAPH, alice, acme, "WORKS_FOR", "Alice works for Acme.")
    other = seed.edge(GRAPH, acme, alice, "PAYS", "Acme pays Alice.")
    untouched = seed.edge(GRAPH, alice, acme, "LIKES", "Alice likes Acme.")
    episodes = episode_refs(seed, GRAPH, "Alice left Acme in March 2024.", explicit=["2026-01-01T00:00:00.000000Z"])
    stats = apply(store, GRAPH, response(
        [], [], [{"id": "F1", "invalid_at": "2024-03"}, "F2", "F9"],
    ), episodes, fact_map={"F1": old, "F2": other})
    by_uuid = {e["uuid"]: e for e in edges(store)}
    assert by_uuid[old]["invalid_at"] == "2024-03-01T00:00:00.000000Z" and by_uuid[old]["expired_at"]
    # Without a date in the text, the window's explicit reference time is used.
    assert by_uuid[other]["invalid_at"] == "2026-01-01T00:00:00.000000Z" and by_uuid[other]["expired_at"]
    assert by_uuid[untouched]["invalid_at"] is None and by_uuid[untouched]["expired_at"] is None
    assert stats.edges_invalidated == 2


def test_invalidated_fact_that_is_restated_stays_active(store, graph, seed):
    alice = seed.node(GRAPH, "Alice", None)
    acme = seed.node(GRAPH, "Acme", None)
    old = seed.edge(GRAPH, alice, acme, "WORKS_FOR", "Alice works for Acme.")
    episodes = episode_refs(seed, GRAPH, "Alice works for Acme.")
    apply(store, GRAPH, response([], [relation("Alice", "Acme", "WORKS_FOR", "Alice works for Acme.")], ["F1"]),
          episodes, fact_map={"F1": old})
    [edge] = edges(store)
    assert edge["invalid_at"] is None and edge["expired_at"] is None


def test_chunks_evidence_maps_edge_episodes(store, graph, seed):
    episodes = episode_refs(seed, GRAPH, "Alice met Bob here.", "Carol met Dan there.", "Nobody here.")
    apply(store, GRAPH, response([], [
        relation("Alice", "Bob", "MET", "Alice met Bob.", chunks=[0, 0, 7]),
        relation("Carol", "Dan", "MET", "Carol met Dan."),         # evidence by names
        relation("Gus", "Hal", "MET", "Gus met Hal."),              # no evidence: all episodes
    ]), episodes)
    by_fact = {e["fact"]: e for e in edges(store)}
    assert edge_episodes(store, by_fact["Alice met Bob."]["uuid"]) == [episodes[0].uuid]
    assert edge_episodes(store, by_fact["Carol met Dan."]["uuid"]) == [episodes[1].uuid]
    assert sorted(edge_episodes(store, by_fact["Gus met Hal."]["uuid"])) == sorted(e.uuid for e in episodes)
    carol = nodes(store)["Carol"]["uuid"]
    linked = [r["episode_uuid"] for r in rows(store, "SELECT episode_uuid FROM node_episodes WHERE node_uuid = ?", carol)]
    assert linked == [episodes[1].uuid]


# ---------------------------------------------------------------------------
# LLM call policy (§4.9)
# ---------------------------------------------------------------------------

MESSAGES = [{"role": "user", "content": "hi"}]


def test_rate_limit_honours_retry_after(llm, fake_llm, sleeps, openai_error):
    fake_llm.script = [openai_error(429, headers={"Retry-After": "7"}), {"entities": []}]
    assert llm.chat_json(MESSAGES) == {"entities": []}
    assert sleeps == [7.0]
    assert fake_llm.calls[0]["max_tokens"] == 4096 and fake_llm.calls[0]["max_attempts"] == 2


def test_rate_limit_backoff_without_header_and_cap(llm, fake_llm, sleeps, openai_error):
    fake_llm.script = [openai_error(429, body={"error": {"code": "bridge_throttled"}}), openai_error(429), {"ok": 1}]
    assert llm.chat_json(MESSAGES) == {"ok": 1}
    assert sleeps == [10.0, 20.0]
    sleeps.clear()
    fake_llm.script = [openai_error(429, headers={"retry-after": "500"}), {"ok": 1}]
    llm.chat_json(MESSAGES)
    assert sleeps == [120.0]


def test_server_and_transport_errors_back_off(llm, fake_llm, sleeps, openai_error):
    connection_error = openai.APIConnectionError(request=httpx.Request("POST", "http://bridge"))
    fake_llm.script = [openai_error(500), connection_error, {"ok": 1}]
    assert llm.chat_json(MESSAGES) == {"ok": 1}
    assert sleeps == [5.0, 15.0]


@pytest.mark.parametrize("status, code", [(429, "llm_rate_limited"), (503, "llm_unavailable")])
def test_exhausted_retries_fail_the_window(llm, fake_llm, sleeps, openai_error, status, code):
    fake_llm.script = [openai_error(status)] * 3
    with pytest.raises(WindowFailedError) as caught:
        llm.chat_json(MESSAGES)
    assert caught.value.code == code
    assert "3 attempts" in caught.value.message
    assert fake_llm.call_count == 3 and len(sleeps) == 2


@pytest.mark.parametrize("status, body, code", [
    (401, None, "llm_auth"),
    (403, None, "llm_auth"),
    (503, {"error": {"code": "grok_not_signed_in", "message": "secret provider text"}}, "llm_auth"),
    (500, {"code": "openrouter_key_missing"}, "llm_auth"),
    (429, {"error": {"code": "openrouter_daily_limit"}}, "llm_quota_exhausted"),
])
def test_fatal_conditions_are_not_retried(llm, fake_llm, sleeps, openai_error, status, body, code):
    fake_llm.script = [openai_error(status, body=body), {"ok": 1}]
    with pytest.raises(FatalLLMError) as caught:
        llm.chat_json(MESSAGES)
    assert caught.value.code == code
    assert "secret" not in caught.value.message
    assert fake_llm.call_count == 1 and sleeps == []
    if code == "llm_quota_exhausted":
        assert caught.value.message == "The LLM's daily free quota is used up (resets 00:00 UTC)."
    else:
        assert caught.value.message == f"The LLM provider rejected the request (HTTP {status})."


def test_missing_llm_key_is_fatal(local, sleeps):
    def factory():
        raise ValueError("LLM_API_KEY 未配置")

    llm = ExtractionLLM(factory, local.settings, sleep=sleeps.append)
    with pytest.raises(FatalLLMError) as caught:
        llm.chat_json(MESSAGES)
    assert caught.value.error == {"code": "llm_not_configured", "message": "LLM_API_KEY is not configured."}


def test_bad_output_and_rejected_requests_are_not_retried(llm, fake_llm, sleeps, openai_error):
    fake_llm.script = [LLMResponseError("LLM returned invalid JSON (line 1, column 2)")]
    with pytest.raises(BadOutputError) as caught:
        llm.chat_json(MESSAGES)
    assert caught.value.error == {"code": "llm_bad_output", "message": "LLM returned invalid JSON (line 1, column 2)"}
    for status in (400, 413, 422):
        fake_llm.script = [openai_error(status)]
        with pytest.raises(BadOutputError):
            llm.chat_json(MESSAGES)
    assert fake_llm.call_count == 4 and sleeps == []


def test_unexpected_errors_fail_with_the_type_name(llm, fake_llm):
    fake_llm.script = [KeyError("secret")]
    with pytest.raises(WindowFailedError) as caught:
        llm.chat_json(MESSAGES)
    assert caught.value.error == {"code": "extraction_error", "message": "KeyError"}
    assert classify_llm_error(RuntimeError("x")).kind == "other"


def test_throttle_spaces_call_starts():
    now = [100.0]
    waits: list[float] = []

    def sleep(seconds: float) -> None:
        waits.append(seconds)
        now[0] += seconds

    throttle = Throttle(3.5, clock=lambda: now[0], sleep=sleep)
    assert throttle.acquire() == 0.0
    now[0] += 1.0
    assert throttle.acquire() == pytest.approx(2.5)
    now[0] += 10.0
    assert throttle.acquire() == 0.0
    assert waits == [pytest.approx(2.5)]
    assert Throttle(0).acquire() == 0.0


def test_usage_rows_count_calls_failures_and_chars(llm, fake_llm, store, openai_error):
    fake_llm.script = [openai_error(503), {"entities": []}]
    llm.chat_json(MESSAGES, scope=("graph", GRAPH))
    [usage] = rows(store, "SELECT * FROM usage")
    assert (usage["scope_kind"], usage["scope_id"]) == ("graph", GRAPH)
    assert usage["llm_calls"] == 2 and usage["llm_failures"] == 1
    assert usage["prompt_chars"] == 4 and usage["output_chars"] == len('{"entities":[]}')


# ---------------------------------------------------------------------------
# Whole windows: commit, split, failure, fatal abort, cancel (§4.3, §4.9)
# ---------------------------------------------------------------------------


def test_window_commit_marks_episodes_and_items_succeeded(store, graph, llm, local):
    batch_id, uuids = insert_batch(store, graph, ["Alice Chen works for Acme Corp.", "Bob works for Acme Corp."])
    result = extract_next_window(store, llm, local.settings, owner="w")
    assert result.status == "succeeded" and result.succeeded == uuids
    assert [i["status"] for i in items(store, batch_id)] == ["succeeded", "succeeded"]
    episodes = rows(store, "SELECT processed, extraction_status, lease_owner FROM episodes WHERE batch_id = ?", batch_id)
    assert all(e["processed"] == 1 and e["extraction_status"] == "succeeded" and e["lease_owner"] is None
               for e in episodes)
    assert set(nodes(store)) == {"Alice Chen", "Acme Corp", "Bob"}
    by_fact = {e["fact"]: e for e in edges(store)}
    assert edge_episodes(store, by_fact["Bob works for Acme Corp."]["uuid"]) == [uuids[1]]
    assert rows(store, "SELECT version FROM graphs WHERE graph_id = ?", graph)[0]["version"] >= 1
    assert extract_next_window(store, llm, local.settings, owner="w") is None


def test_bad_output_splits_the_window_then_succeeds(store, graph, llm, fake_llm, local):
    batch_id, uuids = insert_batch(store, graph, ["Alice works for Acme.", "Bob works for Initech.", "Carol works for Hooli."])
    fake_llm.script = [LLMResponseError("LLM JSON output was truncated at the token limit")]
    result = extract_next_window(store, llm, local.settings, owner="w")
    assert result.status == "succeeded" and result.splits == 1
    assert sorted(result.succeeded) == sorted(uuids)
    assert fake_llm.call_count == 3  # the whole window, then halves of 2 and 1
    assert [i["status"] for i in items(store, batch_id)] == ["succeeded"] * 3
    assert {"Alice", "Bob", "Carol"} <= set(nodes(store))


def test_single_episode_bad_output_fails_with_llm_bad_output(store, graph, llm, fake_llm, local):
    batch_id, uuids = insert_batch(store, graph, ["Alice works for Acme."])
    fake_llm.script = [{"facts": ["no entities key"]}]
    result = extract_next_window(store, llm, local.settings, owner="w")
    assert result.status == "failed" and result.failed == uuids
    [item] = items(store, batch_id)
    error = json_loads(item["error_json"])
    assert item["status"] == "failed"
    assert error["code"] == "llm_bad_output" and error["window_id"] == result.window_id
    assert "missing entities/relations" in error["message"]
    episode = rows(store, "SELECT processed, extraction_status, extraction_error FROM episodes WHERE uuid = ?", uuids[0])[0]
    assert episode["processed"] == 1 and episode["extraction_status"] == "failed"
    assert json_loads(episode["extraction_error"])["code"] == "llm_bad_output"


def test_retry_exhaustion_fails_the_window_with_its_id(store, graph, llm, fake_llm, local, openai_error, sleeps):
    batch_id, _ = insert_batch(store, graph, ["Alice works for Acme."])
    fake_llm.script = [openai_error(502)] * 3
    result = extract_next_window(store, llm, local.settings, owner="w")
    assert result.status == "failed" and not result.fatal
    error = json_loads(items(store, batch_id)[0]["error_json"])
    assert error["code"] == "llm_unavailable" and error["window_id"] == result.window_id
    assert sleeps == [5.0, 15.0]


def test_fatal_error_aborts_the_batch(store, graph, llm, fake_llm, openai_error):
    settings = LocalMemorySettings(window_chars=30)
    batch_id, uuids = insert_batch(store, graph, ["Alice works for Acme.", "Bob works for Initech.", "Carol too."])
    fake_llm.script = [openai_error(401)]
    result = extract_next_window(store, llm, settings, owner="w")
    assert result.fatal and result.fatal_error["code"] == "llm_auth"
    assert result.failed == uuids[:1]
    batch = rows(store, "SELECT error_json FROM batches WHERE batch_id = ?", batch_id)[0]
    assert json_loads(batch["error_json"]) == {"code": "llm_auth", "message": "The LLM provider rejected the request (HTTP 401)."}
    statuses = items(store, batch_id)
    assert [i["status"] for i in statuses] == ["failed"] * 3
    assert all(json_loads(i["error_json"])["code"] == "llm_auth" for i in statuses)
    episodes = rows(store, "SELECT processed, extraction_status FROM episodes WHERE batch_id = ?", batch_id)
    assert all(e["processed"] == 1 and e["extraction_status"] == "failed" for e in episodes)
    assert extract_next_window(store, llm, settings, owner="w") is None
    assert fake_llm.call_count == 1


def test_in_flight_window_of_an_aborted_batch_fails_without_calling_the_llm(store, graph, llm, fake_llm, local):
    batch_id, uuids = insert_batch(store, graph, ["Alice works for Acme."])
    window = claim_window(store, local.settings, owner="w")
    with store.write() as conn:
        conn.execute("UPDATE batches SET error_json = ? WHERE batch_id = ?",
                     ('{"code":"llm_quota_exhausted","message":"quota"}', batch_id))
    result = process_window(store, window, llm, local.settings)
    assert result.failed == uuids and fake_llm.call_count == 0
    assert json_loads(items(store, batch_id)[0]["error_json"])["code"] == "llm_quota_exhausted"


def test_window_returning_after_a_fatal_abort_fails_instead_of_committing(store, graph, llm, fake_llm, local):
    batch_id, uuids = insert_batch(store, graph, ["Alice works for Acme."])
    window = claim_window(store, local.settings, owner="w")
    default = fake_llm.default

    def other_window_hits_the_quota(messages):
        with store.write() as conn:
            conn.execute("UPDATE batches SET error_json = ? WHERE batch_id = ?",
                         ('{"code":"llm_quota_exhausted","message":"quota"}', batch_id))
        return default(messages)

    fake_llm.script = [other_window_hits_the_quota]
    result = process_window(store, window, llm, local.settings)
    assert result.status == "failed" and result.failed == uuids
    error = json_loads(items(store, batch_id)[0]["error_json"])
    assert error == {"code": "llm_quota_exhausted", "message": "quota", "window_id": window.window_id}
    assert nodes(store) == {}


def test_busy_commit_is_retried_then_left_to_lease_recovery(store, graph, llm, local, sleeps, monkeypatch):
    from zep_cloud.core.api_error import ApiError as ZepApiError

    from app.memory import extraction as extraction_module
    from app.memory.errors import store_busy

    real_commit = extraction_module.commit_window
    calls = {"n": 0}

    def flaky_commit(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise store_busy()
        return real_commit(*args, **kwargs)

    monkeypatch.setattr(extraction_module, "commit_window", flaky_commit)
    batch_id, uuids = insert_batch(store, graph, ["Alice works for Acme."])
    assert extract_next_window(store, llm, local.settings, owner="w").succeeded == uuids
    assert sleeps == [1.0]

    def always_busy(*args, **kwargs):
        raise store_busy()

    monkeypatch.setattr(extraction_module, "commit_window", always_busy)
    batch_id, uuids = insert_batch(store, graph, ["Bob works for Initech."])
    with pytest.raises(ZepApiError) as caught:
        extract_next_window(store, llm, local.settings, owner="w")
    assert caught.value.status_code == 503
    # The episode stays leased (processing) so lease recovery can requeue it.
    assert rows(store, "SELECT extraction_status FROM episodes WHERE uuid = ?", uuids[0])[0]["extraction_status"] == "processing"


def test_graph_deleted_mid_window_discards_results_and_cancels_items(store, graph, llm, fake_llm, local):
    batch_id, uuids = insert_batch(store, graph, ["Alice works for Acme."])
    default = fake_llm.default

    def delete_graph_during_call(messages):
        # What graph.delete does while the LLM call is in flight (no lock is held then).
        with store.write() as conn:
            conn.execute("UPDATE batch_items SET status = 'canceled' WHERE graph_id = ? "
                         "AND status IN ('pending', 'queued', 'processing')", (graph,))
            conn.execute("DELETE FROM graphs WHERE graph_id = ?", (graph,))
        return default(messages)

    fake_llm.script = [delete_graph_during_call]
    result = extract_next_window(store, llm, local.settings, owner="w")
    assert result.status == "canceled" and result.canceled == uuids
    assert rows(store, "SELECT count(*) AS n FROM nodes")[0]["n"] == 0
    assert rows(store, "SELECT count(*) AS n FROM edges")[0]["n"] == 0
    assert [i["status"] for i in items(store, batch_id)] == ["canceled"]
    # A window claimed for a graph that is already gone makes no LLM call.
    graph_two = "g2"
    with store.write() as conn:
        conn.execute("INSERT INTO graphs(graph_id, uuid, created_at) VALUES (?, ?, ?)", (graph_two, new_id(), utcnow_iso()))
    insert_batch(store, graph_two, ["Bob works for Initech."])
    window = claim_window(store, local.settings, owner="w")
    with store.write() as conn:
        conn.execute("DELETE FROM graphs WHERE graph_id = ?", (graph_two,))
    calls = fake_llm.call_count
    assert process_window(store, window, llm, local.settings).status == "canceled"
    assert fake_llm.call_count == calls


def test_lost_lease_discards_the_result(store, graph, llm, fake_llm, local):
    batch_id, uuids = insert_batch(store, graph, ["Alice works for Acme."])
    window = claim_window(store, local.settings, owner="w1")
    default = fake_llm.default

    def steal(messages):
        with store.write() as conn:
            conn.execute("UPDATE episodes SET lease_owner = 'w2'")
        return default(messages)

    fake_llm.script = [steal]
    result = process_window(store, window, llm, local.settings)
    assert result.status == "discarded" and result.discarded == uuids
    assert nodes(store) == {} and edges(store) == []
    assert items(store, batch_id)[0]["status"] == "processing"


# ---------------------------------------------------------------------------
# Post-batch entity dedup pass (§4.8)
# ---------------------------------------------------------------------------


def test_dedup_candidates_follow_the_name_rules(store, ontology_graph, seed):
    ids = {name: seed.node(GRAPH, name, type_) for name, type_ in [
        ("Alice", "Person"), ("Alice Chen", "Person"), ("Acme Corporation", "Organization"),
        ("Acme Corporatoin", None), ("IBM", "Organization"), ("International Business Machines", None),
        ("Apple", "Organization"), ("Apple Watch", "Product"), ("Zeta", None), ("王伟", "Person"),
        ("王伟明", "Person"),
    ]}
    with store.read() as conn:
        all_nodes = load_dedup_nodes(conn, GRAPH)
    pairs = find_dedup_candidates(all_nodes, ids.values())
    found = {frozenset((p.a.name, p.b.name)) for p in pairs}
    assert frozenset(("Alice", "Alice Chen")) in found
    assert frozenset(("Acme Corporation", "Acme Corporatoin")) in found
    assert frozenset(("IBM", "International Business Machines")) in found
    assert frozenset(("王伟", "王伟明")) in found
    assert frozenset(("Apple", "Apple Watch")) not in found  # Organization vs Product
    assert not any("Zeta" in pair for pair in found)
    assert [p.similarity for p in pairs] == sorted((p.similarity for p in pairs), reverse=True)
    assert len(find_dedup_candidates(all_nodes, ids.values(), max_pairs=2)) == 2


def test_confirmed_pairs_do_not_merge_transitively_across_different_names(store, graph, seed):
    for name in ("Alice", "Alice Chen", "Alice Smith"):
        seed.node(GRAPH, name, "Person")
    with store.read() as conn:
        all_nodes = load_dedup_nodes(conn, GRAPH)
    pairs = [p for p in find_dedup_candidates(all_nodes, [n.uuid for n in all_nodes])
             if {p.a.name, p.b.name} in ({"Alice", "Alice Chen"}, {"Alice", "Alice Smith"})]
    groups = group_confirmed_pairs(pairs)
    assert len(groups) == 1 and len(groups[0]) == 2


def _batch_with_alias_split(store, seed) -> tuple[str, dict[str, str], list[str]]:
    """A batch whose windows created "Alice" and "Alice Chen" separately, both linked to Acme."""

    batch_id, episodes = insert_batch(store, GRAPH, ["Alice praised Acme.", "Alice Chen praised Acme!"],
                                      status="succeeded")
    refs = [EpisodeRef(episodes[0], "Alice praised Acme.", utcnow_iso(), False, 0),
            EpisodeRef(episodes[1], "Alice Chen praised Acme!", utcnow_iso(), False, 1)]
    apply(store, GRAPH, response([entity("Alice", "Person", summary="Alice is an engineer."),
                                  entity("Acme", "Organization")],
                                 [relation("Alice", "Acme", "MENTIONS", "Alice praised Acme.", chunks=[0])]),
          refs[:1])
    apply(store, GRAPH, response([entity("Alice Chen", summary="Alice Chen lives in Paris."),
                                  entity("Acme", "Organization")],
                                 [relation("Alice Chen", "Acme", "MENTIONS", "Alice praised Acme!", chunks=[1]),
                                  relation("Acme", "Alice Chen", "PAYS", "Acme pays Alice Chen.", chunks=[1])]),
          refs[1:])
    return batch_id, {name: row["uuid"] for name, row in nodes(store).items()}, episodes


def test_dedup_pass_merges_confirmed_pairs_and_repoints_edges(store, ontology_graph, seed, llm, fake_llm, local):
    batch_id, ids, episodes = _batch_with_alias_split(store, seed)
    assert set(ids) == {"Alice", "Alice Chen", "Acme"}
    assert len(edges(store)) == 3  # different endpoints, so no dedup at insert time

    def decide(messages):
        prompt = messages[-1]["content"]
        assert ('P1: "Alice" [Person]: Alice is an engineer. || "Alice Chen" [Entity]: Alice Chen lives in Paris.'
                in prompt)
        return {"decisions": [{"pair": "P1", "same_entity": True}]}

    fake_llm.script = [decide]
    result = run_dedup_pass(store, batch_id, llm, local.settings)
    assert (result.candidates, result.confirmed, result.merged_nodes, result.errors) == (1, 1, 1, 0)

    found = nodes(store)
    assert set(found) == {"Alice Chen", "Acme"}
    survivor = found["Alice Chen"]
    assert survivor["uuid"] == ids["Alice"]  # the typed node survives, renamed to the longer name
    assert json.loads(survivor["labels_json"]) == ["Entity", "Person"]
    assert survivor["mention_count"] == 2
    assert survivor["summary"] == "Alice is an engineer. Alice Chen lives in Paris."
    assert "Alice" in survivor["aliases_text"].split(" | ")
    keys = {r["alias_key"] for r in rows(store, "SELECT alias_key FROM node_aliases WHERE node_uuid = ?", survivor["uuid"])}
    assert {"alice", "alicechen"} <= keys
    remaining = edges(store)
    assert sorted(e["name"] for e in remaining) == ["MENTIONS", "PAYS"]
    assert all(survivor["uuid"] in (e["source_node_uuid"], e["target_node_uuid"]) for e in remaining)
    # The duplicate MENTIONS facts were folded into the older edge, keeping both episodes.
    [mentions] = [e for e in remaining if e["name"] == "MENTIONS"]
    assert mentions["fact"] == "Alice praised Acme."
    assert edge_episodes(store, mentions["uuid"]) == episodes
    linked = rows(store, "SELECT episode_uuid FROM node_episodes WHERE node_uuid = ?", survivor["uuid"])
    assert len(linked) == 2


def test_dedup_pass_llm_failure_is_not_fatal(store, ontology_graph, seed, llm, fake_llm, local, openai_error):
    batch_id, ids, _ = _batch_with_alias_split(store, seed)
    fake_llm.script = [openai_error(500)] * 3
    result = run_dedup_pass(store, batch_id, llm, local.settings)
    assert result.errors == 1 and result.merged_nodes == 0
    assert set(nodes(store)) == set(ids)
    fake_llm.script = [openai_error(401)]
    assert run_dedup_pass(store, batch_id, llm, local.settings).errors == 1


def test_dedup_pass_off_or_without_candidates_makes_no_call(store, ontology_graph, seed, llm, fake_llm, local):
    batch_id, _, _ = _batch_with_alias_split(store, seed)
    off = LocalMemorySettings(dedup_pass="off")
    assert run_dedup_pass(store, batch_id, llm, off).skipped
    empty_batch, _ = insert_batch(store, GRAPH, ["nothing"], status="succeeded")
    assert run_dedup_pass(store, empty_batch, llm, local.settings).candidates == 0
    assert fake_llm.call_count == 0


def test_parse_dedup_decisions_is_lenient_but_needs_explicit_true():
    raw = {"decisions": [
        {"pair": "P1", "same_entity": True}, {"pair": "p2", "same_entity": "yes"},
        {"pair": 3, "same_entity": False}, {"pair": "P4", "same_entity": "maybe"},
        {"pair": "P9", "same_entity": True}, {"id": "5", "same_entity": True},
    ]}
    assert parse_dedup_decisions(raw, 5) == {0, 1, 4}
    assert parse_dedup_decisions({"P1": True, "P2": False}, 2) == {0}
    assert parse_dedup_decisions(["nope"], 2) == set()
