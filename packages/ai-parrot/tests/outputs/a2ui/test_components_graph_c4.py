"""FEAT-754 M4 — C4 lowering of the viz-core Graph component."""

from __future__ import annotations

import json
from pathlib import Path

from parrot.outputs.a2ui.catalog import catalog_instructions
from parrot.outputs.a2ui.catalog.base import BasicNode, to_components
from parrot.outputs.a2ui.catalog.viz_core import VIZ_CORE_CATALOG_ID
from parrot.outputs.a2ui.catalog.viz_core import graph as graph_mod
from parrot.outputs.a2ui.models import Component

HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "fixtures" / "c4_container_diagram.json"
GOLDEN = HERE / "golden" / "graph_c4_lowered.json"


def _dump(tree: BasicNode) -> bytes:
    return json.dumps(tree.model_dump(mode="json", exclude_none=True), sort_keys=True, indent=2).encode() + b"\n"


def _component() -> Component:
    properties = json.loads(FIXTURE.read_text())
    return Component(id="c4-graph", component="Graph", catalogId=VIZ_CORE_CATALOG_ID, **properties)


def test_graph_c4_lower_golden() -> None:
    first = _dump(graph_mod.GraphComponent().lower(_component(), {}))
    second = _dump(graph_mod.GraphComponent().lower(_component(), {}))
    assert first == second
    assert first == GOLDEN.read_bytes()


def test_graph_c4_lower_roles_and_order() -> None:
    tree = graph_mod.GraphComponent().lower(_component(), {})
    roles = [child.metadata.extensions.root["parrot_role"] for child in tree.child.children]
    assert roles == [
        "description",
        "title",
        "caption",
        "boundary-list",
        "element-list",
        "edge-list",
        "graph-source",
    ]
    assert tree.metadata.extensions.root == {"parrot_variant": "graph", "parrot_c4_level": "container"}

    boundary = tree.child.children[3].children[0]
    assert boundary.text == "Order Platform (system boundary)"
    assert boundary.metadata.extensions.root == {
        "parrot_role": "boundary",
        "parrot_c4_type": "system",
        "parrot_depth": 0,
    }

    elements = tree.child.children[4].children
    assert elements[2].text == "Web App [container] · SvelteKit — Storefront UI"
    assert elements[2].metadata.extensions.root["parrot_group"] == "platform"
    assert elements[0].metadata.extensions.root.get("parrot_group") is None

    edges = tree.child.children[5].children
    assert edges[0].text == "customer → web (Uses) via HTTPS"
    assert edges[0].metadata.extensions.root["parrot_technology"] == "HTTPS"

    assert all(component.component in {"Card", "Column", "Text"} for component in to_components(tree))


def test_graph_c4_lower_source_is_c4_mermaid() -> None:
    tree = graph_mod.GraphComponent().lower(_component(), {})
    source = tree.child.children[-1]
    assert source.metadata.extensions.root["parrot_role"] == "graph-source"
    assert source.text.startswith("C4Container\n")


def test_graph_c4_authoring_notes_and_utterances() -> None:
    notes = graph_mod.GRAPH_C4_AUTHORING_NOTES
    utterances = graph_mod.GRAPH_C4_UTTERANCES
    assert notes
    assert len(utterances) == 10
    assert any("C4" in utterance for utterance in utterances)
    assert any("diagrama" in utterance for utterance in utterances)

    text = f"{notes} {' '.join(utterances)}".lower()
    assert all(word not in text for word in ("color", "colour", "palette", "font"))


def test_graph_instructions_mention_c4() -> None:
    assert 'kind="c4"' in graph_mod.GRAPH_INSTRUCTIONS
    assert 'kind="c4"' in catalog_instructions([VIZ_CORE_CATALOG_ID])
