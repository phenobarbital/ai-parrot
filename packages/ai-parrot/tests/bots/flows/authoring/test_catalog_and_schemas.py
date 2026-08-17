"""The component catalog and the schemas derived from it.

These tests use the *real* registries, not the fixture catalog: the catalog's
whole purpose is to reflect what is actually installed, so a test that mocked
the registries would verify nothing worth verifying.
"""
from __future__ import annotations

import pytest

from parrot.bots.flows.authoring.catalog import build_catalog
from parrot.bots.flows.authoring.schemas import (
    blueprint_json_schema,
    node_config_json_schema,
    node_json_schema,
    skeleton_json_schema,
    transitions_json_schema,
    validate_against_schema,
)


@pytest.fixture(scope="module")
def live_catalog():
    return build_catalog()


# ── catalog ──────────────────────────────────────────────────────────────────

def test_catalog_reflects_the_live_node_registry(live_catalog):
    from parrot.bots.flows.flow.flow import NODE_REGISTRY

    assert set(NODE_REGISTRY) <= live_catalog.node_type_names()


def test_catalog_reflects_the_declarative_tool_registry(live_catalog):
    from parrot.tools.discovery import discover_from_registry

    declared = set(discover_from_registry())
    assert declared <= live_catalog.tool_names()
    assert len(declared) > 50, "the registry should be substantial, not a stub"


def test_tool_kind_is_available_to_both_engines(live_catalog):
    """A crew compiles it to ToolNodeDefinition; a flow to a 'tool' node."""
    assert "tool" in live_catalog.kinds_for("crew")
    assert "tool" in live_catalog.kinds_for("flow")


def test_decision_kinds_are_flow_only(live_catalog):
    assert "decision" not in live_catalog.kinds_for("crew")
    assert "decision" in live_catalog.kinds_for("flow")


def test_sentinels_are_never_declarable(live_catalog):
    """__start__/__end__ are emitted by the compiler, never by a model."""
    for engine in ("crew", "flow"):
        assert "start" not in live_catalog.kinds_for(engine)
        assert "end" not in live_catalog.kinds_for(engine)


def test_decision_node_publishes_a_config_schema(live_catalog):
    entry = live_catalog.node_type("decision")
    assert entry is not None and entry.config_schema
    assert "mode" in entry.config_schema.get("properties", {})


def test_allowed_tools_restricts_the_catalog():
    catalog = build_catalog(allowed_tools=["google_search"])
    assert catalog.tool_names() == {"google_search"}


def test_the_plain_catalog_is_cached():
    """It is built per bare GET; three registry walks each time is waste."""
    first = build_catalog()
    assert build_catalog() is first


def test_restricted_catalogs_are_never_cached():
    """An allowlist is request-specific and must not leak into the cache."""
    restricted = build_catalog(allowed_tools=["google_search"])
    assert build_catalog() is not restricted
    assert build_catalog().tool_names() != {"google_search"}


def test_cache_can_be_bypassed():
    assert build_catalog(use_cache=False) is not build_catalog()


def test_render_for_agent_includes_tools_but_decision_does_not(live_catalog):
    agent_slice = live_catalog.render_for("agent", engine="crew")
    decision_slice = live_catalog.render_for("decision", engine="flow")
    assert "google_search" in agent_slice
    assert "google_search" not in decision_slice


def test_render_tools_states_how_many_were_dropped(live_catalog):
    rendered = live_catalog.render_tools(limit=5)
    assert "and" in rendered and "more not shown" in rendered


# ── schemas ──────────────────────────────────────────────────────────────────

def test_node_schema_pins_kind_when_asked(live_catalog):
    schema = node_json_schema(live_catalog, engine="crew", kind="tool")
    assert schema["properties"]["kind"]["enum"] == ["tool"]


def test_node_schema_constrains_tools_to_the_catalog(live_catalog):
    schema = node_json_schema(live_catalog, engine="crew")
    enum = schema["properties"]["tool"]["enum"]
    assert "google_search" in enum
    assert "wordpress_publish" not in enum


def test_skeleton_schema_constrains_kinds_per_engine(live_catalog):
    schema = skeleton_json_schema(live_catalog, engine="crew")
    enums = [
        defs["properties"]["kind"]["enum"]
        for defs in (schema.get("$defs") or {}).values()
        if isinstance(defs, dict) and "kind" in defs.get("properties", {})
    ]
    assert enums and all("decision" not in enum for enum in enums)


def test_transitions_schema_pins_endpoints_to_declared_nodes():
    schema = transitions_json_schema(["a", "b"])
    source = schema["properties"]["transitions"]["items"]["properties"]["source"]
    assert source["anyOf"][0]["enum"] == ["a", "b"]


def test_schema_validation_rejects_an_unknown_node_reference():
    schema = transitions_json_schema(["a", "b"])
    errors = validate_against_schema(
        {"transitions": [{"source": "ghost", "target": "b"}]}, schema
    )
    assert errors and "ghost" in errors[0]


def test_schema_validation_accepts_a_conforming_document():
    schema = transitions_json_schema(["a", "b"])
    assert validate_against_schema({"transitions": [{"source": "a", "target": "b"}]}, schema) == []


def test_blueprint_schema_builds(live_catalog):
    schema = blueprint_json_schema(live_catalog, engine="crew")
    assert schema["properties"]["nodes"]


def test_node_config_schema_matches_the_registered_model():
    assert node_config_json_schema("decision") is not None
    assert node_config_json_schema("agent") is None
    assert node_config_json_schema("not_a_type") is None
