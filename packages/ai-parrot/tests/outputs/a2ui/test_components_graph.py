"""Golden + contract tests for the viz-core ``Graph`` component (FEAT-529 Module 2, TASK-2885)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from parrot.outputs.a2ui.catalog import ProducerOrigin, get_component, validate_envelope
from parrot.outputs.a2ui.catalog.base import CatalogValidationError, to_components
from parrot.outputs.a2ui.catalog.parrot import infographic as infographic_mod
from parrot.outputs.a2ui.catalog.viz_core import VIZ_CORE_CATALOG_ID
from parrot.outputs.a2ui.catalog.viz_core import graph as graph_mod
from parrot.outputs.a2ui.models import Action, Component, CreateSurface, EventAction

GOLDEN_DIR = Path(__file__).parent / "golden"


def _dump(tree) -> bytes:
    return json.dumps(tree.model_dump(mode="json", exclude_none=True), sort_keys=True, indent=2).encode() + b"\n"


def _graph_component(**extra) -> Component:
    base = dict(
        id="blk-000",
        component="Graph",
        catalogId=VIZ_CORE_CATALOG_ID,
        kind="flowchart",
        direction="TB",
        nodes=[{"id": "a", "label": "Start"}, {"id": "b", "label": "End"}],
        edges=[{"from": "a", "to": "b", "label": "go"}],
        accessibleDescription="A tiny two-node graph.",
    )
    base.update(extra)
    return Component(**base)


class TestGraphSchema:
    def test_graph_registered_under_viz_core(self):
        entry = get_component("Graph", VIZ_CORE_CATALOG_ID)
        assert entry.definition.catalog_id == VIZ_CORE_CATALOG_ID
        assert entry.definition.requires_actions is False
        assert entry.definition.tool_only is False
        assert entry.definition.allowed_parents is None

        # Unique bare-name lookup still resolves (no ambiguity introduced).
        assert get_component("Graph").definition.catalog_id == VIZ_CORE_CATALOG_ID


class TestGraphLowerGolden:
    def test_graph_lower_golden(self):
        comp = _graph_component()
        one = _dump(graph_mod.GraphComponent().lower(comp, {}))
        two = _dump(graph_mod.GraphComponent().lower(comp, {}))
        assert one == two
        assert one == (GOLDEN_DIR / "graph_lowered.json").read_bytes()

    def test_graph_lower_first_child_is_description(self):
        tree = graph_mod.GraphComponent().lower(_graph_component(), {})
        first_child = tree.child.children[0]
        assert first_child.component == "Text"
        assert first_child.metadata.extensions.root["parrot_role"] == "description"

    def test_graph_lower_generates_description_when_absent(self):
        comp = _graph_component(accessibleDescription=None)
        tree = graph_mod.GraphComponent().lower(comp, {})
        description_node = tree.child.children[0]
        assert description_node.text == "Graph of 2 nodes and 1 edges (flowchart)"

    def test_graph_lower_passes_data_binding_through(self):
        comp = _graph_component(data={"path": "/nodes"})
        tree = graph_mod.GraphComponent().lower(comp, {})
        edge_list = next(c for c in tree.child.children if c.metadata.extensions.root.get("parrot_role") == "edge-list")
        assert edge_list.metadata.extensions.root["parrot_graph_data"] == {"path": "/nodes"}

    def test_graph_lower_emits_only_basic_primitives(self):
        tree = graph_mod.GraphComponent().lower(_graph_component(), {})
        blob = json.dumps(tree.model_dump(mode="json"))
        assert '"option"' not in blob


class TestGraphActionGate:
    """The surface stays Parrot-default (so the Basic ``Column`` root
    resolves); ``Graph`` carries its OWN ``catalogId=VIZ_CORE_CATALOG_ID``
    (spec §7: "the surface default vs component catalog")."""

    def test_graph_llm_origin_rejects_action(self):
        comp = _graph_component(action=Action(event=EventAction(name="select")))
        root = Component(id="root", component="Column", children=[comp.id])
        surface = CreateSurface(surfaceId="s", catalogId="https://parrot.dev/catalogs/v1", components=[root, comp])
        with pytest.raises(CatalogValidationError) as exc:
            validate_envelope(surface, origin=ProducerOrigin.LLM)
        assert "Graph" in exc.value.action_components

    def test_graph_tool_origin_allows_action(self):
        comp = _graph_component(action=Action(event=EventAction(name="select")))
        root = Component(id="root", component="Column", children=[comp.id])
        surface = CreateSurface(surfaceId="s", catalogId="https://parrot.dev/catalogs/v1", components=[root, comp])
        validate_envelope(surface, origin=ProducerOrigin.TOOL)  # must not raise


class TestGraphEmitsV1Primitives:
    def test_graph_emits_v1_primitives(self):
        tree = graph_mod.GraphComponent().lower(_graph_component(), {})
        flat = to_components(tree)
        root = Component(id="root", component="Column", children=[c.id for c in flat])
        surface = CreateSurface(surfaceId="s", catalogId="https://parrot.dev/catalogs/v1", components=[root, *flat])
        validate_envelope(surface)  # must not raise


class TestGraphInInfographicSection:
    def test_graph_in_infographic_section_lowers(self):
        descriptor = {
            "component": "Graph",
            "properties": {
                "kind": "flowchart",
                "direction": "TB",
                "nodes": [{"id": "a"}, {"id": "b"}],
                "edges": [{"from": "a", "to": "b"}],
                "accessibleDescription": "Nested graph.",
            },
        }
        node = infographic_mod._lower_child(descriptor, {}, "child-0")
        assert node.component == "Card"
        assert node.metadata.extensions.root["parrot_variant"] == "graph"
