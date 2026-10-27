"""FEAT-754 M2 — Mermaid C4 codec emission (TASK-4786 adds parser coverage)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from parrot.outputs.a2ui.graph.mermaid import to_mermaid
from parrot.outputs.a2ui.graph.mermaid_c4 import to_mermaid_c4
from parrot.outputs.a2ui.graph.models import GraphEdge, GraphGroup, GraphLayout, GraphNode, GraphSpec

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "c4_container_diagram.json"


def _spec() -> GraphSpec:
    return GraphSpec.model_validate(json.loads(FIXTURE.read_text()))


def _c4(**kwargs: object) -> GraphSpec:
    values = {"kind": "c4", "level": "container", "nodes": [], "edges": []}
    values.update(kwargs)
    return GraphSpec(**values)


def test_c4_fixture_emits_container_header() -> None:
    assert to_mermaid(_spec()).startswith("C4Container\n")


def test_c4_emission_exact_text() -> None:
    assert to_mermaid_c4(_spec()) == (
        "C4Container\n"
        "title Order platform — containers\n"
        "Person(customer, \"Customer\", \"Places orders\")\n"
        "System_Ext(payments, \"Payment Provider\", \"Card processing\")\n"
        "System_Boundary(platform, \"Order Platform\") {\n"
        "    Container(web, \"Web App\", \"SvelteKit\", \"Storefront UI\")\n"
        "    Container(api, \"Order API\", \"aiohttp\", \"Order lifecycle\")\n"
        "    ContainerDb(db, \"Orders DB\", \"PostgreSQL\")\n"
        "}\n"
        "Rel(customer, web, \"Uses\", \"HTTPS\")\n"
        "Rel(web, api, \"Calls\", \"JSON/HTTPS\")\n"
        "BiRel(api, db, \"Reads/writes\", \"asyncpg\")\n"
        "Rel(api, payments, \"Charges\", \"REST\")\n"
        "Rel_Back(payments, api, \"Webhook\", \"HTTPS\")\n"
    )


@pytest.mark.parametrize(
    ("level", "header"),
    [("context", "C4Context"), ("container", "C4Container"), ("component", "C4Component"), ("dynamic", "C4Dynamic")],
)
def test_c4_each_level_header_emits(level: str, header: str) -> None:
    spec = GraphSpec(kind="c4", level=level, nodes=[], edges=[])
    assert to_mermaid_c4(spec) == f"{header}\n"


def test_c4_all_twenty_element_macros_emit() -> None:
    element_types = (
        "person", "person_ext", "system", "system_ext", "system_db", "system_db_ext", "system_queue",
        "system_queue_ext", "container", "container_ext", "container_db", "container_db_ext", "container_queue",
        "container_queue_ext", "component", "component_ext", "component_db", "component_db_ext", "component_queue",
        "component_queue_ext",
    )
    nodes = [GraphNode(id=f"n{index}", c4Type=element_type) for index, element_type in enumerate(element_types)]
    emitted = to_mermaid_c4(_c4(nodes=nodes))
    assert [line.split("(", 1)[0] for line in emitted.splitlines()[1:]] == [
        "Person", "Person_Ext", "System", "System_Ext", "SystemDb", "SystemDb_Ext", "SystemQueue", "SystemQueue_Ext",
        "Container", "Container_Ext", "ContainerDb", "ContainerDb_Ext", "ContainerQueue", "ContainerQueue_Ext",
        "Component", "Component_Ext", "ComponentDb", "ComponentDb_Ext", "ComponentQueue", "ComponentQueue_Ext",
    ]


def test_c4_nested_boundaries_indent() -> None:
    spec = _c4(
        nodes=[GraphNode(id="service", c4Type="container")],
        groups=[
            GraphGroup(id="enterprise", c4Type="enterprise", nodes=[]),
            GraphGroup(id="system", parent="enterprise", c4Type="system", nodes=[]),
            GraphGroup(id="container", parent="system", c4Type="container", nodes=["service"]),
        ],
    )
    assert to_mermaid_c4(spec) == (
        "C4Container\n"
        "Enterprise_Boundary(enterprise, \"enterprise\") {\n"
        "    System_Boundary(system, \"system\") {\n"
        "        Container_Boundary(container, \"container\") {\n"
        "            Container(service, \"service\")\n"
        "        }\n"
        "    }\n"
        "}\n"
    )


@pytest.mark.parametrize(
    ("bidirectional", "hint", "macro"),
    [
        (True, None, "BiRel"),
        (False, None, "Rel"),
        (False, "back", "Rel_Back"),
        (False, "up", "Rel_U"),
        (False, "down", "Rel_D"),
        (False, "left", "Rel_L"),
        (False, "right", "Rel_R"),
    ],
)
def test_c4_rel_macros_emit(bidirectional: bool, hint: str | None, macro: str) -> None:
    edge = GraphEdge(**{"from": "a", "to": "b", "bidirectional": bidirectional or None, "hint": hint})
    spec = _c4(nodes=[GraphNode(id="a", c4Type="person"), GraphNode(id="b", c4Type="system")], edges=[edge])
    assert f"{macro}(a, b, \"\")" in to_mermaid_c4(spec)


def test_c4_dynamic_emits_relindex() -> None:
    spec = GraphSpec(
        kind="c4",
        level="dynamic",
        nodes=[GraphNode(id="a", c4Type="person"), GraphNode(id="b", c4Type="system")],
        edges=[GraphEdge(**{"from": "a", "to": "b", "label": "calls"})],
    )
    assert to_mermaid_c4(spec).endswith('RelIndex("1", a, b, "calls")\n')


def test_c4_update_layout_config_only_when_both_set() -> None:
    configured = _c4(layout=GraphLayout(shapeInRow=2, boundaryInRow=3))
    assert to_mermaid_c4(configured).endswith('UpdateLayoutConfig($c4ShapeInRow="2", $c4BoundaryInRow="3")\n')
    assert "UpdateLayoutConfig" not in to_mermaid_c4(_c4())


def test_c4_quotes_escape() -> None:
    spec = _c4(nodes=[GraphNode(id="person", label='A "person"', c4Type="person", description='Says "hi"')])
    assert 'Person(person, "A #quot;person#quot;", "Says #quot;hi#quot;")' in to_mermaid_c4(spec)


def test_to_mermaid_c4_rejects_non_c4() -> None:
    with pytest.raises(ValueError):
        to_mermaid_c4(GraphSpec(nodes=[], edges=[]))
