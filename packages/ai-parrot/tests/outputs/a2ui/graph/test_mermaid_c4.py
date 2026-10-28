"""FEAT-754 M2 — Mermaid C4 codec emission (TASK-4786 adds parser coverage)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from parrot.outputs.a2ui.catalog.base import CatalogValidationError
from parrot.outputs.a2ui.graph.mermaid import MermaidCodecError, from_mermaid, to_mermaid
from parrot.outputs.a2ui.graph.mermaid_c4 import C4_LOSSY_FIELDS, from_mermaid_c4, to_mermaid_c4
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
        'Person(customer, "Customer", "Places orders")\n'
        'System_Ext(payments, "Payment Provider", "Card processing")\n'
        'System_Boundary(platform, "Order Platform") {\n'
        '    Container(web, "Web App", "SvelteKit", "Storefront UI")\n'
        '    Container(api, "Order API", "aiohttp", "Order lifecycle")\n'
        '    ContainerDb(db, "Orders DB", "PostgreSQL")\n'
        "}\n"
        'Rel(customer, web, "Uses", "HTTPS")\n'
        'Rel(web, api, "Calls", "JSON/HTTPS")\n'
        'BiRel(api, db, "Reads/writes", "asyncpg")\n'
        'Rel(api, payments, "Charges", "REST")\n'
        'Rel_Back(payments, api, "Webhook", "HTTPS")\n'
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
        "person",
        "person_ext",
        "system",
        "system_ext",
        "system_db",
        "system_db_ext",
        "system_queue",
        "system_queue_ext",
        "container",
        "container_ext",
        "container_db",
        "container_db_ext",
        "container_queue",
        "container_queue_ext",
        "component",
        "component_ext",
        "component_db",
        "component_db_ext",
        "component_queue",
        "component_queue_ext",
    )
    nodes = [GraphNode(id=f"n{index}", c4Type=element_type) for index, element_type in enumerate(element_types)]
    emitted = to_mermaid_c4(_c4(nodes=nodes))
    assert [line.split("(", 1)[0] for line in emitted.splitlines()[1:]] == [
        "Person",
        "Person_Ext",
        "System",
        "System_Ext",
        "SystemDb",
        "SystemDb_Ext",
        "SystemQueue",
        "SystemQueue_Ext",
        "Container",
        "Container_Ext",
        "ContainerDb",
        "ContainerDb_Ext",
        "ContainerQueue",
        "ContainerQueue_Ext",
        "Component",
        "Component_Ext",
        "ComponentDb",
        "ComponentDb_Ext",
        "ComponentQueue",
        "ComponentQueue_Ext",
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
        'Enterprise_Boundary(enterprise, "enterprise") {\n'
        '    System_Boundary(system, "system") {\n'
        '        Container_Boundary(container, "container") {\n'
        '            Container(service, "service")\n'
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
    assert f'{macro}(a, b, "")' in to_mermaid_c4(spec)


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


def _normalize(spec: GraphSpec) -> dict[str, object]:
    """Apply the C4 round-trip comparison normalization from spec §3 M2."""
    data = spec.model_dump(by_alias=True)
    aliases = {
        "accessible_description": "accessibleDescription",
        "rank_sep": "rankSep",
        "node_sep": "nodeSep",
    }
    for field in C4_LOSSY_FIELDS:
        head, *tail = field.split(".")
        head = aliases.get(head, head)
        if not tail:
            data.pop(head, None)
        elif head == "nodes":
            for node in data[head]:
                node.pop(tail[0], None)
        elif head == "edges":
            for edge in data[head]:
                edge.pop(tail[0], None)
        elif head == "layout" and data[head] is not None:
            data[head].pop(aliases.get(tail[0], tail[0]), None)

    data["title"] = (data["title"] or "").rstrip() or None
    original_groups = data["groups"] or []
    ordered_groups: list[dict[str, object]] = []

    def visit(parent: str | None) -> None:
        for group in original_groups:
            if group["parent"] == parent:
                group["label"] = None if group["label"] in (None, "", group["id"]) else group["label"]
                group["c4Type"] = group["c4Type"] or "generic"
                ordered_groups.append(group)
                visit(group["id"])

    visit(None)
    ordered_nodes: list[dict[str, object]] = []
    node_by_id = {node["id"]: node for node in data["nodes"]}
    grouped = {node_id for group in ordered_groups for node_id in group["nodes"]}
    for node in data["nodes"]:
        if node["id"] not in grouped:
            ordered_nodes.append(node)
    for group in ordered_groups:
        ordered_nodes.extend(node_by_id[node_id] for node_id in group["nodes"])
    for node in ordered_nodes:
        node["label"] = None if node["label"] in (None, "", node["id"]) else node["label"]
        node["technology"] = node["technology"] or None
        node["description"] = node["description"] or None
    for edge in data["edges"]:
        edge["label"] = edge["label"] or None
        edge["technology"] = edge["technology"] or None
        edge["bidirectional"] = edge["bidirectional"] or None
    data["groups"] = ordered_groups or None
    data["nodes"] = ordered_nodes
    if data["layout"] is not None and not data["layout"]:
        data["layout"] = None
    return data


def test_c4_roundtrip_container_level_byte_stable() -> None:
    emitted = to_mermaid_c4(_spec())
    parsed = from_mermaid_c4(emitted)
    assert to_mermaid_c4(parsed) == emitted
    assert _normalize(parsed) == _normalize(_spec())


def test_c4_roundtrip_each_level_header() -> None:
    for level, header in (
        ("context", "C4Context"),
        ("container", "C4Container"),
        ("component", "C4Component"),
        ("dynamic", "C4Dynamic"),
    ):
        spec = _c4(level=level)
        assert from_mermaid_c4(f"{header}\n").level == level
        assert to_mermaid_c4(spec) == f"{header}\n"


def test_c4_all_twenty_element_macros() -> None:
    spec = _c4(
        nodes=[
            GraphNode(id=f"n{index}", c4Type=element_type) for index, element_type in enumerate(_ELEMENT_MACRO_TYPES)
        ]
    )
    assert [node.c4_type for node in from_mermaid_c4(to_mermaid_c4(spec)).nodes] == list(_ELEMENT_MACRO_TYPES)


_ELEMENT_MACRO_TYPES = (
    "person",
    "person_ext",
    "system",
    "system_ext",
    "system_db",
    "system_db_ext",
    "system_queue",
    "system_queue_ext",
    "container",
    "container_ext",
    "container_db",
    "container_db_ext",
    "container_queue",
    "container_queue_ext",
    "component",
    "component_ext",
    "component_db",
    "component_db_ext",
    "component_queue",
    "component_queue_ext",
)


def test_c4_roundtrip_normalization() -> None:
    spec = _c4(
        title="Architecture   ",
        nodes=[
            GraphNode(id="inner", label="", c4Type="container"),
            GraphNode(id="outside", label="outside", c4Type="person"),
        ],
        groups=[
            GraphGroup(id="child", parent="parent", c4Type="generic", nodes=["inner"]),
            GraphGroup(id="parent", nodes=[]),
        ],
    )
    parsed = from_mermaid_c4(to_mermaid_c4(spec))
    assert to_mermaid_c4(parsed) == to_mermaid_c4(spec)
    assert _normalize(parsed) == _normalize(spec)


@pytest.mark.parametrize("macro", ["Rel_Neighbor", "Rel_Back_Neighbor"])
def test_c4_rejects_neighbor_macros(macro: str) -> None:
    with pytest.raises(MermaidCodecError, match="line 2"):
        from_mermaid_c4(f'C4Context\n{macro}(a, b, "calls")\n')


def test_c4_nested_boundaries() -> None:
    text = 'C4Container\nEnterprise_Boundary(ent, "ent") {\n  System_Boundary(sys, "sys") {\n    Container(app, "app")\n  }\n}\n'
    parsed = from_mermaid_c4(text)
    assert [(group.id, group.parent, group.nodes) for group in parsed.groups or []] == [
        ("ent", None, []),
        ("sys", "ent", ["app"]),
    ]


def test_c4_rel_macros_and_birel() -> None:
    text = 'C4Context\nPerson(a, "a")\nSystem(b, "b")\nRel_Up(a, b, "up")\nRel_Down(a, b, "down")\nRel_Left(a, b, "left")\nRel_Right(a, b, "right")\nRel_Back(a, b, "back")\nBiRel(a, b, "both")\n'
    edges = from_mermaid_c4(text).edges
    assert [edge.hint for edge in edges] == ["up", "down", "left", "right", "back", None]
    assert edges[-1].bidirectional is True


def test_c4_dynamic_relindex_ordering() -> None:
    text = 'C4Dynamic\nPerson(a, "a")\nSystem(b, "b")\nRelIndex("2", a, b, "second")\nRelIndex("1", a, b, "first")\nRel(a, b, "plain")\n'
    assert [edge.label for edge in from_mermaid_c4(text).edges] == ["first", "second", "plain"]
    for invalid in ('RelIndex("1", a, b, "one")\nRelIndex("1", a, b, "two")', 'RelIndex("2", a, b, "two")'):
        with pytest.raises(MermaidCodecError):
            from_mermaid_c4(f'C4Dynamic\nPerson(a, "a")\nSystem(b, "b")\n{invalid}\n')


def test_c4_update_layout_config() -> None:
    parsed = from_mermaid_c4('C4Context\nUpdateLayoutConfig($c4ShapeInRow="2", $c4BoundaryInRow="3")\n')
    assert parsed.layout == GraphLayout(shapeInRow=2, boundaryInRow=3)


@pytest.mark.parametrize(
    "line",
    [
        'UpdateElementStyle(a, $bgColor="red")',
        'UpdateRelStyle(a, b, $textColor="red")',
        'Person(a, "a", $sprite="x")',
        'Deployment_Node(a, "a")',
    ],
)
def test_c4_rejects_styling_sprites_and_deployment(line: str) -> None:
    with pytest.raises(MermaidCodecError, match="line 2"):
        from_mermaid_c4(f"C4Context\n{line}\n")


def test_c4_quotes_and_unescapes_labels() -> None:
    parsed = from_mermaid_c4('C4Context\nPerson(a, "A #quot;person#quot;, inc", "Says #quot;hi#quot;")\n')
    assert parsed.nodes[0].label == 'A "person", inc'
    assert parsed.nodes[0].description == 'Says "hi"'


def test_c4_error_is_catalog_validation_error() -> None:
    assert isinstance(MermaidCodecError(1, "bad", "reason"), CatalogValidationError)


def test_generic_dispatch_to_c4() -> None:
    emitted = to_mermaid(_spec())
    assert from_mermaid(emitted).kind == "c4"
