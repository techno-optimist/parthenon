"""Ontology capture (graph.set_ontology) and OntologyView lookups."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, Optional

import pytest
from pydantic import Field
from zep_cloud import EntityEdgeSourceTarget
from zep_cloud.errors import BadRequestError, NotFoundError
from zep_cloud.external_clients.ontology import (
    EdgeModel,
    EntityModel,
    EntityText,
    edge_model_to_api_schema,
    entity_model_to_api_schema,
)
from zep_cloud.types import SuccessResponse

from app.memory import OntologyView, apply_set_ontology, capture_ontology, load_ontology
from app.services.graph_builder import GraphBuilderService
from app.utils.ontology import MAX_ONTOLOGY_SOURCE_TARGETS


class RecordingGraph:
    """``client.graph`` stand-in: records the SDK arguments, stores via the local backend."""

    def __init__(self, store) -> None:
        self.store = store
        self.calls: list[dict[str, Any]] = []

    def set_ontology(self, entities, edges=None, user_ids=None, graph_ids=None, request_options=None):
        self.calls.append({"entities": entities, "edges": edges, "graph_ids": graph_ids})
        return apply_set_ontology(self.store, entities, edges, user_ids=user_ids, graph_ids=graph_ids)

    set_entity_types = set_ontology


def _builder(store) -> tuple[GraphBuilderService, RecordingGraph]:
    graph = RecordingGraph(store)
    builder = object.__new__(GraphBuilderService)
    builder.client = SimpleNamespace(graph=graph)
    return builder, graph


def _stored(store, graph_id: str) -> dict[str, Any]:
    with store.read() as conn:
        row = conn.execute(
            "SELECT ontology_json, ontology_updated_at FROM graphs WHERE graph_id = ?", (graph_id,)
        ).fetchone()
    assert row["ontology_updated_at"]
    return json.loads(row["ontology_json"])


def _expected_from_call(call: dict[str, Any]) -> dict[str, Any]:
    """What Zep Cloud would receive, built with the SDK's own converters."""

    edge_types = []
    for name, (model, targets) in (call["edges"] or {}).items():
        schema = edge_model_to_api_schema(model, name)
        schema["source_targets"] = [{"source": t.source, "target": t.target} for t in targets]
        edge_types.append(schema)
    return {
        "entity_types": [entity_model_to_api_schema(cls, name) for name, cls in call["entities"].items()],
        "edge_types": edge_types,
    }


GENERATED_ONTOLOGY = {
    "entity_types": [
        {
            "name": "Person",
            "description": "A person involved in the story.",
            "attributes": [
                {"name": "full_name", "type": "text", "description": "Full name"},
                {"name": "summary", "type": "text", "description": "Short bio"},
                "role",
            ],
        },
        {
            "name": "Organization",
            "description": "A company or institution.",
            "attributes": [{"name": "graph_id", "description": "Reserved name"}, "org_type"],
        },
        {"name": "Topic", "description": "A discussion topic.", "attributes": []},
    ],
    "edge_types": [
        {
            "name": "WORKS_FOR",
            "description": "A person works for an organization.",
            "attributes": [{"name": "position", "description": "Job title"}],
            "source_targets": [{"source": "Person", "target": "Organization"}],
        },
        {
            "name": "MENTIONS",
            "description": "Something mentions something else.",
            "attributes": [],
            "source_targets": [{"source": "Entity", "target": "Entity"}],
        },
    ],
}


# ---------------------------------------------------------------------------
# Capture through the real GraphBuilderService.set_ontology
# ---------------------------------------------------------------------------


def test_builder_ontology_is_stored_exactly_as_the_sdk_converts_it(local, seed):
    graph_id = seed.graph("mirofish_0123456789abcdef")
    builder, recorder = _builder(local.store)

    builder.set_ontology(graph_id, GENERATED_ONTOLOGY)

    assert len(recorder.calls) == 1
    assert recorder.calls[0]["graph_ids"] == [graph_id]
    stored = _stored(local.store, graph_id)
    assert stored == _expected_from_call(recorder.calls[0])

    person, organization, topic = stored["entity_types"]
    assert person["name"] == "Person"
    assert person["description"] == "A person involved in the story."
    assert [p["name"] for p in person["properties"]] == ["full_name", "entity_summary", "role"]
    assert all(p["type"] == "Text" for p in person["properties"])
    # Reserved attribute names get the entity_ prefix.
    assert [p["name"] for p in organization["properties"]] == ["entity_graph_id", "org_type"]
    # Types without attributes get the fallback property.
    assert topic["properties"] == [{
        "name": "details",
        "type": "Text",
        "description": "Additional details about this ontology type.",
    }]

    works_for, mentions = stored["edge_types"]
    assert works_for["source_targets"] == [{"source": "Person", "target": "Organization"}]
    assert works_for["properties"] == [{"name": "position", "type": "Text", "description": "Job title"}]
    assert mentions["source_targets"] == [{"source": "Entity", "target": "Entity"}]
    assert mentions["properties"][0]["name"] == "details"


def test_edge_only_ontology_stores_no_entity_types(local, seed):
    graph_id = seed.graph("g-edges")
    builder, recorder = _builder(local.store)
    builder.set_ontology(graph_id, {
        "entity_types": [],
        "edge_types": [{
            "name": "RELATED_TO",
            "attributes": ["reason"],
            "source_targets": [{"source": "Entity", "target": "Entity"}],
        }],
    })

    assert recorder.calls[0]["entities"] == {}
    stored = _stored(local.store, graph_id)
    assert stored["entity_types"] == []
    assert [edge["name"] for edge in stored["edge_types"]] == ["RELATED_TO"]


def test_source_targets_are_capped_and_deduplicated(local, seed):
    graph_id = seed.graph("g-cap")
    targets = [{"source": f"Source{i}", "target": f"Target{i}"} for i in range(MAX_ONTOLOGY_SOURCE_TARGETS + 3)]
    targets.insert(1, dict(targets[0]))
    builder, _ = _builder(local.store)
    builder.set_ontology(graph_id, {
        "entity_types": [],
        "edge_types": [{"name": "RELATED_TO", "attributes": [], "source_targets": targets}],
    })

    pairs = _stored(local.store, graph_id)["edge_types"][0]["source_targets"]
    assert len(pairs) == MAX_ONTOLOGY_SOURCE_TARGETS
    assert pairs == [{"source": f"Source{i}", "target": f"Target{i}"} for i in range(MAX_ONTOLOGY_SOURCE_TARGETS)]


def test_set_ontology_replaces_the_previous_ontology(local, seed):
    graph_id = seed.graph("g-replace")
    builder, _ = _builder(local.store)
    builder.set_ontology(graph_id, GENERATED_ONTOLOGY)
    builder.set_ontology(graph_id, {
        "entity_types": [{"name": "Company", "description": "A company.", "attributes": ["sector"]}],
        "edge_types": [],
    })

    stored = _stored(local.store, graph_id)
    assert [item["name"] for item in stored["entity_types"]] == ["Company"]
    assert stored["edge_types"] == []


# ---------------------------------------------------------------------------
# apply_set_ontology directly (graph.set_ontology semantics)
# ---------------------------------------------------------------------------


class Person(EntityModel):
    """A person."""

    full_name: EntityText = Field(description="Full name", default=None)


class Organization(EntityModel):
    """An organization."""

    org_type: EntityText = Field(description="Kind of organization", default=None)


class WorksFor(EdgeModel):
    """Employment."""

    position: Optional[str] = Field(description="Job title", default=None)


def test_project_default_applies_to_graphs_without_their_own(local, seed):
    own = seed.graph("g-own")
    plain = seed.graph("g-plain")

    result = apply_set_ontology(local.store, entities={"Person": Person}, edges={"WORKS_FOR": WorksFor})
    assert isinstance(result, SuccessResponse)
    apply_set_ontology(local.store, entities={"Organization": Organization}, graph_ids=[own])

    with local.store.read() as conn:
        default_row = conn.execute("SELECT ontology_json FROM default_ontology WHERE id = 1").fetchone()
        assert json.loads(default_row[0])["edge_types"][0]["source_targets"] == []  # bare model: any pair
        assert load_ontology(conn, plain).entity_type_names == ["Person"]
        assert load_ontology(conn, own).entity_type_names == ["Organization"]
        assert load_ontology(conn, "g-missing").entity_type_names == ["Person"]


def test_no_ontology_at_all_gives_an_empty_view(local, seed):
    graph_id = seed.graph("g-none")
    with local.store.read() as conn:
        view = load_ontology(conn, graph_id)
    assert view.is_empty
    assert view.match_entity_type("Person") is None


def test_source_target_objects_default_to_entity(local, seed):
    graph_id = seed.graph("g-st")
    apply_set_ontology(
        local.store,
        entities={"Person": Person},
        edges={"WORKS_FOR": (WorksFor, [
            EntityEdgeSourceTarget(source="Person", target="Organization"),
            EntityEdgeSourceTarget(source="Person"),
            {"target": "Organization"},
        ])},
        graph_ids=[graph_id],
    )
    pairs = _stored(local.store, graph_id)["edge_types"][0]["source_targets"]
    assert pairs == [
        {"source": "Person", "target": "Organization"},
        {"source": "Person", "target": "Entity"},
        {"source": "Entity", "target": "Organization"},
    ]


def test_dict_schemas_are_accepted_as_is(local, seed):
    graph_id = seed.graph("g-dict")
    entity_schema = {"name": "Person", "description": "A person.",
                     "properties": [{"name": "role", "type": "Text", "description": "Role"}]}
    edge_schema = {"name": "KNOWS", "description": "Acquaintance.", "properties": [],
                   "source_targets": [{"source": "Person", "target": "Person"}]}
    apply_set_ontology(local.store, entities={"Person": entity_schema}, edges={"KNOWS": edge_schema},
                       graph_ids=[graph_id])
    stored = _stored(local.store, graph_id)
    assert stored["entity_types"] == [entity_schema]
    assert stored["edge_types"] == [edge_schema]


@pytest.mark.parametrize("kwargs, error", [
    ({"entities": None}, BadRequestError),
    ({"entities": ["Person"]}, BadRequestError),
    ({"entities": {"Person": object()}}, BadRequestError),
    ({"entities": {"Person": Person}, "edges": ["WORKS_FOR"]}, BadRequestError),
    ({"entities": {}, "edges": {"WORKS_FOR": (WorksFor,)}}, BadRequestError),
    ({"entities": {}, "edges": {"WORKS_FOR": (WorksFor, "Person->Org")}}, BadRequestError),
    ({"entities": {}, "edges": {"WORKS_FOR": Person}}, BadRequestError),
    ({"entities": {"": Person}}, BadRequestError),
    ({"entities": {"Person": Person}, "user_ids": ["u1"]}, BadRequestError),
    ({"entities": {"Person": Person}, "graph_ids": "g1"}, BadRequestError),
    ({"entities": {"Person": Person}, "graph_ids": ["g-missing"]}, NotFoundError),
])
def test_invalid_arguments_raise_sdk_errors(local, seed, kwargs, error):
    seed.graph("g1")
    with pytest.raises(error):
        apply_set_ontology(local.store, **kwargs)
    with local.store.read() as conn:
        assert conn.execute("SELECT ontology_json FROM graphs WHERE graph_id = 'g1'").fetchone()[0] is None
        assert conn.execute("SELECT count(*) FROM default_ontology").fetchone()[0] == 0


def test_missing_graph_among_several_changes_nothing(local, seed):
    seed.graph("g1")
    with pytest.raises(NotFoundError):
        apply_set_ontology(local.store, entities={"Person": Person}, graph_ids=["g1", "g-missing"])
    with local.store.read() as conn:
        assert conn.execute("SELECT ontology_json FROM graphs WHERE graph_id = 'g1'").fetchone()[0] is None


# ---------------------------------------------------------------------------
# OntologyView
# ---------------------------------------------------------------------------


@pytest.fixture
def view() -> OntologyView:
    canonical = capture_ontology(
        {"Person": Person, "Organization": Organization, "NewsOutlet": {"name": "NewsOutlet", "properties": []}},
        {
            "WORKS_FOR": (WorksFor, [EntityEdgeSourceTarget(source="Person", target="Organization")]),
            "MENTIONS": (WorksFor, [EntityEdgeSourceTarget(source="Entity", target="Entity")]),
            "REPORTS_ON": (WorksFor, [EntityEdgeSourceTarget(source="NewsOutlet", target="Entity")]),
            "RELATED": WorksFor,
        },
    )
    return OntologyView(canonical)


@pytest.mark.parametrize("raw, expected", [
    ("Person", "Person"),
    ("person", "Person"),
    ("PERSON", "Person"),
    ("news outlet", "NewsOutlet"),
    ("news_outlet", "NewsOutlet"),
    ("News-Outlet", "NewsOutlet"),
    ("Entity", None),
    ("entity", None),
    ("", None),
    (None, None),
    ("Spaceship", None),
])
def test_match_entity_type(view, raw, expected):
    assert view.match_entity_type(raw) == expected


def test_attribute_names(view):
    assert view.entity_attribute_names("Person") == ["full_name"]
    assert view.entity_attribute_names("organization") == ["org_type"]
    assert view.entity_attribute_names(None) == []
    assert view.edge_attribute_names("WORKS_FOR") == ["position"]
    assert view.edge_attribute_names("works for") == ["position"]
    assert view.edge_attribute_names("UNKNOWN") == []


def test_match_edge_type_allowed_swapped_fallback_and_free_form(view):
    allowed = view.match_edge_type("works_for", "Person", "Organization")
    assert (allowed.name, allowed.swap) == ("WORKS_FOR", False)
    assert allowed.definition["name"] == "WORKS_FOR"

    camel = view.match_edge_type("worksFor", "Person", "Organization")
    assert camel.name == "WORKS_FOR"

    swapped = view.match_edge_type("WORKS_FOR", "Organization", "Person")
    assert (swapped.name, swapped.swap) == ("WORKS_FOR", True)

    fallback = view.match_edge_type("WORKS_FOR", "Person", "Person")
    assert (fallback.name, fallback.definition, fallback.swap) == ("RELATES_TO", None, False)

    # A generic node matches only "Entity" in source/target pairs.
    assert view.match_edge_type("WORKS_FOR", None, "Organization").name == "RELATES_TO"
    assert view.match_edge_type("MENTIONS", None, None).name == "MENTIONS"
    assert view.match_edge_type("REPORTS_ON", "NewsOutlet", None).name == "REPORTS_ON"
    # A bare edge model (no source targets) allows any pair.
    assert view.match_edge_type("RELATED", "Person", None).name == "RELATED"

    free = view.match_edge_type("criticizes publicly", "Person", "Organization")
    assert (free.name, free.definition) == ("CRITICIZES_PUBLICLY", None)
    assert view.match_edge_type("关注", "Person", "Person").name == "RELATES_TO"


def test_strict_ontology_drops_free_form_and_disallowed_relations(view):
    assert view.match_edge_type("CRITICIZES", "Person", "Organization", strict=True) is None
    assert view.match_edge_type("WORKS_FOR", "Person", "Person", strict=True) is None
    assert view.match_edge_type("WORKS_FOR", "Person", "Organization", strict=True).name == "WORKS_FOR"
    assert view.match_edge_type("WORKS_FOR", "Organization", "Person", strict=True).swap is True


def test_prompt_rendering(view):
    entities = view.render_entity_types()
    assert entities.splitlines()[0] == "ENTITY TYPES:"
    assert "- Person: A person. Attributes: full_name (Full name)" in entities
    assert "- NewsOutlet:" in entities

    relations = view.render_relation_types()
    assert relations.splitlines()[0] == "RELATION TYPES:"
    assert "- WORKS_FOR: Employment. Allowed: Person -> Organization. Attributes: position (Job title)" in relations
    assert "- RELATED: Employment. Allowed: Entity -> Entity." in relations

    empty = OntologyView(None)
    assert empty.render_entity_types() == 'ENTITY TYPES: (none, use "Entity")'
    assert empty.render_relation_types() == "RELATION TYPES: (none, use free-form)"


def test_prompt_rendering_caps_the_number_of_types():
    canonical = {"entity_types": [{"name": f"Type{i}", "description": "", "properties": []} for i in range(15)],
                 "edge_types": []}
    rendered = OntologyView(canonical).render_entity_types()
    assert len(rendered.splitlines()) == 1 + 10


def test_view_round_trips_and_tolerates_corrupt_json(view):
    again = OntologyView.from_json(json.dumps(view.to_dict()))
    assert again.to_dict() == view.to_dict()
    assert OntologyView.from_json("{not json").is_empty
    assert OntologyView.from_json(None).is_empty
    assert OntologyView.from_json("[1, 2]").is_empty
