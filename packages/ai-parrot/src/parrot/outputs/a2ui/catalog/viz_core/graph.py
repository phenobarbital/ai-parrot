"""The ``Graph`` viz-core catalog component (FEAT-529 Module 2).

Follows the ``Chart`` composite pattern exactly (``catalog/parrot/chart.py``):
``GRAPH_SCHEMA`` is derived from :class:`~parrot.outputs.a2ui.graph.models.
GraphSpec` (schema parity by construction, FEAT-473 G2) via
:func:`~parrot.outputs.a2ui.catalog.parrot._derive.derive_schema`, plus ONE
post-derivation merge: ``action`` is not a ``GraphSpec`` field (it's the
Component-level prop; the official ``common_types.json#/$defs/
ComponentCommon`` does not define it either — FEAT-754 spec, Overview), so it is
declared explicitly as a ``$ref`` to the vendored ``common_types.json#/
$defs/Action``. ``lower()`` never hand-edits ``GRAPH_SCHEMA`` further.

``Graph`` registers under :data:`~parrot.outputs.a2ui.catalog.viz_core.
VIZ_CORE_CATALOG_ID`, NOT the Parrot catalog — this is the first
component to actually populate the viz-core catalog (Module 0 only
carried its identity/instructions, no registration).
"""

from __future__ import annotations

from typing import Any, Final

from parrot.outputs.a2ui.catalog import register_component
from parrot.outputs.a2ui.catalog.base import BasicNode, BasicTree
from parrot.outputs.a2ui.catalog.parrot._derive import derive_schema
from parrot.outputs.a2ui.catalog.viz_core import VIZ_CORE_CATALOG_ID
from parrot.outputs.a2ui.graph import GraphEdge, GraphSpec, to_mermaid
from parrot.outputs.a2ui.models import Component

#: The official common types document's own ``$id`` (vendored,
#: ``catalog/basic/spec/common_types.json``) — ``ComponentCommon`` there
#: has no ``action`` property, so `Graph`'s own schema declares it.
_COMMON_TYPES_ID = "https://a2ui.org/specification/v1_0/common_types.json"

GRAPH_SCHEMA: dict[str, Any] = derive_schema(
    GraphSpec,
    binding_fields=("data",),
    required=("nodes", "edges"),
)
GRAPH_SCHEMA["properties"]["action"] = {"$ref": f"{_COMMON_TYPES_ID}#/$defs/Action"}

GRAPH_INSTRUCTIONS = (
    "Use Graph to render a workflow, state machine, dependency graph or call "
    "sequence as TYPED nodes/edges — never author a mermaid string. Set "
    "`kind` (flowchart/state/sequence/dag — dag rejects cycles), `direction` "
    "(TB/LR/BT/RL), `nodes[]` (id, label, shape, state, icon, meta) and "
    "`edges[]` (from, to, label, kind, condition). Always give "
    "`accessibleDescription`. Bind `data` for live per-node state updates "
    '(`{"path": "/pointer"}`), never inline positions. Never set `action` — '
    "only a deterministic tool producer may."
    ' For a software-architecture diagram set kind="c4" with level (context/container/component/dynamic), give every'
    " node a c4Type (person, system, container, component, *_ext, *_db, *_queue) plus description (technology only on"
    " containers/components), and model boundaries as groups (c4Type enterprise/system/container, nested via parent)."
)

GRAPH_C4_AUTHORING_NOTES: Final[str] = (
    "1. Model one element per real system or container; use *_ext types for external elements and list persons first.\n"
    "2. Label every relationship with a verb phrase and set technology only on containers or components.\n"
    "3. Keep each diagram to at most 15 elements and add a boundary only when it contains at least 2 members.\n"
    "4. Never provide positions or action."
)

GRAPH_C4_UTTERANCES: Final[tuple[str, ...]] = (
    "C4 context diagram of the platform",
    "draw a C4 container diagram of this system",
    "show the architecture as a C4 diagram",
    "component diagram of the API service",
    "system context diagram with external systems",
    "diagrama de contexto C4 de la plataforma",
    "diagrama de contenedores de la aplicación",
    "dibuja la arquitectura del sistema como C4",
    "diagrama de componentes del servicio",
    "diagrama de contexto con los sistemas externos",
)


def _edge_extensions(edge: GraphEdge) -> dict[str, Any]:
    extensions: dict[str, Any] = {"parrot_role": "edge"}
    if edge.kind:
        extensions["parrot_edge_kind"] = edge.kind
    if edge.condition:
        extensions["parrot_condition"] = edge.condition
    if edge.technology:
        extensions["parrot_technology"] = edge.technology
    return extensions


def _c4_children(spec: GraphSpec) -> list[BasicNode]:
    """Boundary-list and element-list Columns for a kind="c4" spec (order and roles per the FEAT-754 spec data models)."""
    children: list[BasicNode] = []
    groups = spec.groups or []

    if groups:
        groups_by_id = {group.id: group for group in groups}

        def boundary_depth(group_id: str) -> int:
            """Return the zero-based depth of a boundary in its parent chain."""
            depth = 0
            parent_id = groups_by_id[group_id].parent
            while parent_id is not None:
                depth += 1
                parent_id = groups_by_id[parent_id].parent
            return depth

        boundary_children = []
        for group in groups:
            c4_type = group.c4_type or "generic"
            boundary_children.append(
                BasicNode(
                    component="Text",
                    text=f"{group.label or group.id} ({c4_type} boundary)",
                    metadata={
                        "extensions": {
                            "parrot_role": "boundary",
                            "parrot_c4_type": c4_type,
                            "parrot_depth": boundary_depth(group.id),
                        }
                    },
                )
            )
        children.append(
            BasicNode(
                component="Column",
                children=boundary_children,
                metadata={"extensions": {"parrot_role": "boundary-list"}},
            )
        )

    node_groups = {node_id: group.id for group in groups for node_id in group.nodes}
    element_children = []
    for node in spec.nodes:
        text = f"{node.label or node.id} [{node.c4_type}]"
        if node.technology:
            text += f" · {node.technology}"
        if node.description:
            text += f" — {node.description}"
        extensions: dict[str, Any] = {
            "parrot_role": "element",
            "parrot_c4_type": node.c4_type,
        }
        if node.id in node_groups:
            extensions["parrot_group"] = node_groups[node.id]
        element_children.append(
            BasicNode(
                component="Text",
                text=text,
                metadata={"extensions": extensions},
            )
        )
    children.append(
        BasicNode(
            component="Column",
            children=element_children,
            metadata={"extensions": {"parrot_role": "element-list"}},
        )
    )
    return children


@register_component("Graph", catalog_id=VIZ_CORE_CATALOG_ID)
class GraphComponent:
    """The ``Graph`` viz-core catalog component.

    Display-only by default (``requires_actions=False``) — a component-level
    ``action`` MAY be attached by a deterministic TOOL producer (rejected for
    ``ProducerOrigin.LLM`` by the existing ``ACTION_NOT_ALLOWED_FOR_LLM``
    gate, spec G3 — no new gate is introduced here).
    """

    SCHEMA = GRAPH_SCHEMA
    INSTRUCTIONS = GRAPH_INSTRUCTIONS

    def lower(self, component: Component, data_model: dict[str, Any]) -> BasicTree:
        """Lower a ``Graph`` to a Basic Catalog ``Card{Column[...]}`` tree.

        A graph without a native drawing surface degrades to its
        accessible description, a caption, an edge list, and its mermaid
        source (FEAT-754 spec, "Lowered tree") — every renderer
        without viz-core support (or without a graph engine) still shows
        something readable and copyable. Any ``data`` binding passes
        through UNRESOLVED under ``metadata.extensions.parrot_graph_data``
        (same convention as ``Chart``'s ``parrot_series_data``) —
        resolution happens in the bake pass, never here.
        """
        props = component.model_extra or {}
        # `data` is a binding descriptor ({"path": ...}) when unresolved —
        # never a literal GraphSpec.data mapping at this point (the bake
        # pass hasn't run yet); excluding it lets a real GraphSpec model
        # re-validate the rest of the wire payload (a genuine safety net
        # `derive_schema`'s JSON-Schema alone cannot express, e.g. dangling
        # edges) without choking on the binding shape.
        graph_props = {key: value for key, value in props.items() if key != "data"}
        spec = GraphSpec.model_validate(graph_props)

        if spec.kind == "c4":
            description = spec.accessible_description or (
                f"C4 {spec.level} diagram of {len(spec.nodes)} elements and {len(spec.edges)} relationships"
            )
        else:
            description = spec.accessible_description or (
                f"Graph of {len(spec.nodes)} nodes and {len(spec.edges)} edges ({spec.kind})"
            )

        children: list[BasicNode] = [
            BasicNode(
                component="Text",
                text=description,
                metadata={"extensions": {"parrot_role": "description"}},
            )
        ]
        if spec.title:
            children.append(
                BasicNode(component="Text", text=spec.title, metadata={"extensions": {"parrot_role": "title"}})
            )
        children.append(
            BasicNode(
                component="Text",
                text=f"C4 {spec.level} diagram" if spec.kind == "c4" else f"Graph ({spec.kind}, {spec.direction})",
                metadata={"extensions": {"parrot_role": "caption"}},
            )
        )

        if spec.kind == "c4":
            children.extend(_c4_children(spec))

        edge_children = [
            BasicNode(
                component="Text",
                text=(
                    f"{edge.from_} → {edge.to}"
                    + (f" ({edge.label})" if edge.label else "")
                    + (f" via {edge.technology}" if spec.kind == "c4" and edge.technology else "")
                ),
                metadata={"extensions": _edge_extensions(edge)},
            )
            for edge in spec.edges
        ]
        edge_list_extensions: dict[str, Any] = {"parrot_role": "edge-list"}
        if "data" in props:
            edge_list_extensions["parrot_graph_data"] = props["data"]
        children.append(
            BasicNode(
                component="Column",
                children=edge_children,
                metadata={"extensions": edge_list_extensions},
            )
        )

        children.append(
            BasicNode(
                component="Text",
                text=to_mermaid(spec),
                metadata={"extensions": {"parrot_role": "graph-source"}},
            )
        )

        card_extensions: dict[str, Any] = {"parrot_variant": "graph"}
        if spec.kind == "c4":
            card_extensions["parrot_c4_level"] = spec.level

        return BasicNode(
            id=component.id,
            component="Card",
            child=BasicNode(component="Column", children=children),
            metadata={"extensions": card_extensions},
        )
