"""Map a ``FlowDefinition``-shaped mapping to a ``GraphSpec`` (FEAT-529 Module 5).

One-way import rule (G8): this module accepts ``definition`` as a plain
``Mapping[str, Any]`` — the caller's own
``FlowDefinition.model_dump(by_alias=True)`` output (or an equivalent
already-materialized dict, e.g. loaded from Redis/disk) — and NEVER imports
``parrot.bots`` (not even under ``TYPE_CHECKING``: the adapters import-rule
guard is line-text based, so a guarded import still fails it). Callers keep
their own ``FlowDefinition`` instance; nothing here needs its class.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from parrot.outputs.a2ui.graph import Direction, GraphEdge, GraphKind, GraphNode, GraphSpec

__all__ = ["flow_definition_to_graph"]

#: ``NodeDefinition.type`` -> ``GraphNode.shape`` (spec §2 Overview). Any
#: type not listed here (``agent``, ``dev_loop.*``, and anything a package
#: registers via ``@register_node`` that this mapping predates) renders
#: ``rounded`` — the generic "an agent/step ran here" shape.
_SHAPE_BY_NODE_TYPE: dict[str, str] = {
    "start": "circle",
    "end": "circle",
    "decision": "diamond",
    "interactive_decision": "diamond",
    "synthesis": "hexagon",
    "tool": "subroutine",
}
_DEFAULT_NODE_SHAPE = "rounded"

#: ``EdgeDefinition.condition`` values that render a dashed edge (spec §2 Overview).
_DASHED_CONDITIONS = frozenset({"on_error", "on_timeout"})


def _shape_for_node_type(node_type: str) -> str:
    return _SHAPE_BY_NODE_TYPE.get(node_type, _DEFAULT_NODE_SHAPE)


def _edge_label(edge_def: Mapping[str, Any]) -> str | None:
    """The edge's display label: an explicit ``label`` wins; otherwise the
    ``on_condition`` predicate text; otherwise no label (spec §2 Overview:
    "`on_condition` → the CEL `predicate` text")."""
    explicit_label = edge_def.get("label")
    if explicit_label:
        return explicit_label
    if edge_def.get("condition") == "on_condition":
        return edge_def.get("predicate")
    return None


def _edge_kind(edge_def: Mapping[str, Any]) -> str | None:
    """``on_error``/``on_timeout`` -> ``"dashed"``; every other condition
    renders the renderer's default (``solid``, i.e. ``None`` here)."""
    if edge_def.get("condition") in _DASHED_CONDITIONS:
        return "dashed"
    return None


def flow_definition_to_graph(
    definition: Mapping[str, Any],
    *,
    kind: GraphKind = "flowchart",
    direction: Direction = "TB",
    data_binding: str | None = None,
) -> GraphSpec:
    """Map a ``FlowDefinition``-shaped mapping to a ``GraphSpec``.

    Args:
        definition: ``FlowDefinition.model_dump(by_alias=True)``-shaped
            mapping — top-level ``flow``, ``nodes[]`` (``id``, ``type``,
            ``label``), ``edges[]`` (``from``, ``to``, ``condition``,
            ``predicate``, ``label``). Any extra keys (``metadata``,
            ``version``, ...) are ignored.
        kind: The output ``GraphSpec.kind``. Defaults to ``"flowchart"``
            (a flow's nodes/edges are exactly a flowchart's).
        direction: The output ``GraphSpec.direction``.
        data_binding: Reserved for a future live-state binding (spec's
            ``a2ui-live-workflow-surface`` sibling). ``GraphSpec.data`` is
            typed as the RESOLVED per-node overlay shape
            (``dict[node_id, {...}]``), never the wire-only ``{"path":
            ...}`` binding descriptor — so this adapter, which returns a
            plain ``GraphSpec`` (not a baked wire envelope), has nothing
            safe to do with a bare pointer string yet. Wire it through
            ``build_graph(data_binding=...)`` instead once you have a
            ``CreateSurface`` to build.

    Returns:
        A :class:`~parrot.outputs.a2ui.graph.GraphSpec` with a generated
        ``accessible_description`` (``"<flow> workflow: N steps, M
        transitions"``).
    """
    del data_binding  # see docstring — reserved, not yet actionable here.

    node_defs: Sequence[Mapping[str, Any]] = definition.get("nodes") or []
    edge_defs: Sequence[Mapping[str, Any]] = definition.get("edges") or []

    nodes = [
        GraphNode(
            id=node_def["id"],
            label=node_def.get("label") or node_def["id"],
            shape=_shape_for_node_type(node_def.get("type", "")),
        )
        for node_def in node_defs
    ]

    edges: list[GraphEdge] = []
    for edge_def in edge_defs:
        from_id = edge_def.get("from", edge_def.get("from_"))
        targets = edge_def.get("to")
        target_ids = targets if isinstance(targets, list) else [targets]
        label = _edge_label(edge_def)
        edge_kind = _edge_kind(edge_def)
        for target_id in target_ids:
            edges.append(GraphEdge(**{"from": from_id, "to": target_id, "label": label, "kind": edge_kind}))

    flow_name = definition.get("flow", "flow")
    accessible_description = f"{flow_name} workflow: {len(nodes)} steps, {len(edges)} transitions"

    return GraphSpec(
        kind=kind,
        direction=direction,
        nodes=nodes,
        edges=edges,
        accessible_description=accessible_description,
    )
