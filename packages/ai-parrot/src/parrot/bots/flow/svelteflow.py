"""SvelteFlow Adapter — bidirectional conversion for visual flow builders.

Converts between ``FlowDefinition`` Pydantic models and the node/edge
format used by SvelteFlow / ReactFlow, enabling browser-based visual
editing of agent workflows.

Field mapping
-------------
=================  ==========================
FlowDefinition     SvelteFlow
=================  ==========================
node.id            node.id
node.label         node.data.label
node.type          node.type
node.position.x/y  node.position.x/y
node.agent_ref     node.data.agent_ref
node.config        node.data.config
edge.from_         edge.source
edge.to            edge.target
edge.condition     edge.data.condition
edge.predicate     edge.data.predicate
=================  ==========================
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List

from .definition import (
    ActionDefinition,
    EdgeDefinition,
    FlowDefinition,
    NodeDefinition,
    NodePosition,
)


def to_svelteflow(definition: FlowDefinition) -> Dict[str, Any]:
    """Convert a ``FlowDefinition`` to SvelteFlow node/edge format.

    Returns a dict with ``nodes`` and ``edges`` arrays suitable for
    direct consumption by SvelteFlow's ``<SvelteFlow>`` component.

    Fan-out edges (one source → multiple targets) are expanded into
    individual SvelteFlow edges.
    """
    nodes: List[Dict[str, Any]] = []
    for n in definition.nodes:
        nodes.append({
            "id": n.id,
            "type": n.type,
            "position": {"x": n.position.x, "y": n.position.y},
            "data": {
                "label": n.label or n.id,
                "agent_ref": n.agent_ref,
                "instruction": n.instruction,
                "config": n.config,
                "pre_actions": [
                    a.model_dump(by_alias=True) for a in n.pre_actions
                ],
                "post_actions": [
                    a.model_dump(by_alias=True) for a in n.post_actions
                ],
                "metadata": n.metadata,
                "max_retries": n.max_retries,
            },
        })

    edges: List[Dict[str, Any]] = []
    for e in definition.edges:
        targets = [e.to] if isinstance(e.to, str) else e.to
        for target in targets:
            edges.append({
                "id": e.id or f"{e.from_}->{target}",
                "source": e.from_,
                "target": target,
                "label": e.label or e.condition,
                "data": {
                    "condition": e.condition,
                    "predicate": e.predicate,
                    "instruction": e.instruction,
                    "priority": e.priority,
                },
            })

    return {"nodes": nodes, "edges": edges}


def from_svelteflow(
    sf_data: Dict[str, Any],
    flow_name: str,
) -> FlowDefinition:
    """Convert SvelteFlow node/edge data into a ``FlowDefinition``.

    Args:
        sf_data: Dict with ``nodes`` and ``edges`` from SvelteFlow.
        flow_name: Name for the resulting flow.

    Returns:
        ``FlowDefinition`` ready for persistence or materialisation.

    Notes:
        Multiple SvelteFlow edges sharing the same source are collapsed
        back into a single ``EdgeDefinition`` with ``to`` as a list
        (fan-in grouping) only when they share the same condition and
        predicate.  Otherwise they stay as individual edges.
    """
    # --- Nodes ---
    nodes: List[NodeDefinition] = []
    for sf_node in sf_data.get("nodes", []):
        data: Dict[str, Any] = sf_node.get("data", {})
        position = sf_node.get("position", {})

        # Rebuild pre/post actions from serialised dicts
        pre_actions = _parse_actions(data.get("pre_actions", []))
        post_actions = _parse_actions(data.get("post_actions", []))

        nodes.append(
            NodeDefinition(
                id=sf_node["id"],
                type=sf_node.get("type", "agent"),
                label=data.get("label"),
                agent_ref=data.get("agent_ref"),
                instruction=data.get("instruction"),
                max_retries=data.get("max_retries", 3),
                config=data.get("config", {}),
                pre_actions=pre_actions,
                post_actions=post_actions,
                metadata=data.get("metadata", {}),
                position=NodePosition(
                    x=position.get("x", 0.0),
                    y=position.get("y", 0.0),
                ),
            )
        )

    # --- Edges ---
    # Group SvelteFlow edges by (source, condition, predicate) to detect
    # fan-out that should be collapsed back into a single EdgeDefinition
    # with ``to`` as a list.
    EdgeKey = tuple  # (source, condition, predicate, instruction, priority)
    grouped: Dict[EdgeKey, List[str]] = defaultdict(list)
    edge_meta: Dict[EdgeKey, Dict[str, Any]] = {}

    for sf_edge in sf_data.get("edges", []):
        edata = sf_edge.get("data", {})
        condition = edata.get("condition", "on_success")
        predicate = edata.get("predicate")
        instruction = edata.get("instruction")
        priority = edata.get("priority", 0)
        source = sf_edge["source"]

        key: EdgeKey = (source, condition, predicate, instruction, priority)
        grouped[key].append(sf_edge["target"])
        if key not in edge_meta:
            edge_meta[key] = {
                "id": sf_edge.get("id"),
                "label": sf_edge.get("label"),
            }

    edges: List[EdgeDefinition] = []
    for key, targets in grouped.items():
        source, condition, predicate, instruction, priority = key
        meta = edge_meta[key]
        to_value = targets[0] if len(targets) == 1 else targets
        edges.append(
            EdgeDefinition(
                **{
                    "id": meta.get("id"),
                    "from": source,
                    "to": to_value,
                    "condition": condition,
                    "predicate": predicate,
                    "instruction": instruction,
                    "priority": priority,
                    "label": meta.get("label"),
                }
            )
        )

    return FlowDefinition(flow=flow_name, nodes=nodes, edges=edges)


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------

def _parse_actions(raw: List[Dict[str, Any]]) -> List[ActionDefinition]:
    """Re-hydrate action dicts into their typed Pydantic models."""
    from pydantic import TypeAdapter

    adapter = TypeAdapter(ActionDefinition)
    return [adapter.validate_python(d) for d in raw]
