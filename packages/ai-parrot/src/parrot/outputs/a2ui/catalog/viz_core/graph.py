"""The ``Graph`` viz-core catalog component (FEAT-529 Module 2).

Follows the ``Chart`` composite pattern exactly (``catalog/parrot/chart.py``):
``GRAPH_SCHEMA`` is derived from :class:`~parrot.outputs.a2ui.graph.models.
GraphSpec` (schema parity by construction, FEAT-473 G2) via
:func:`~parrot.outputs.a2ui.catalog.parrot._derive.derive_schema`, plus ONE
post-derivation merge: ``action`` is not a ``GraphSpec`` field (it's the
Component-level prop; the official ``common_types.json#/$defs/
ComponentCommon`` does not define it either — spec §2 Overview), so it is
declared explicitly as a ``$ref`` to the vendored ``common_types.json#/
$defs/Action``. ``lower()`` never hand-edits ``GRAPH_SCHEMA`` further.

``Graph`` registers under :data:`~parrot.outputs.a2ui.catalog.viz_core.
VIZ_CORE_CATALOG_ID`, NOT the Parrot catalog — this is the first
component to actually populate the viz-core catalog (Module 0 only
carried its identity/instructions, no registration).
"""

from __future__ import annotations

from typing import Any

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
)


def _edge_extensions(edge: GraphEdge) -> dict[str, Any]:
    extensions: dict[str, Any] = {"parrot_role": "edge"}
    if edge.kind:
        extensions["parrot_edge_kind"] = edge.kind
    if edge.condition:
        extensions["parrot_condition"] = edge.condition
    return extensions


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
        source (spec §2 Data Models "Lowered tree") — every renderer
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
                text=f"Graph ({spec.kind}, {spec.direction})",
                metadata={"extensions": {"parrot_role": "caption"}},
            )
        )

        edge_children = [
            BasicNode(
                component="Text",
                text=f"{edge.from_} → {edge.to}" + (f" ({edge.label})" if edge.label else ""),
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

        return BasicNode(
            id=component.id,
            component="Card",
            child=BasicNode(component="Column", children=children),
            metadata={"extensions": {"parrot_variant": "graph"}},
        )
