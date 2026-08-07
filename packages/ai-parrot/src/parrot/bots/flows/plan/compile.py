"""Compile an ExecutionPlan into a runnable ``FlowDefinition``.

An :class:`~models.ExecutionPlan` is the planner-facing surface: flat, small,
and easy for a model to emit correctly. ``FlowDefinition`` is the executor's
surface: nodes plus explicit edges, with ``start``/``end`` sentinels and the
checkpointing metadata block. This module is the (deterministic) bridge.

Every plan node becomes a ``NodeDefinition`` of type ``"tool"`` whose
``config`` carries the plan node verbatim. The live ``ToolManager`` and
``WorkingMemoryToolkit`` are *not* serialised into config — they reach the
node through the ``node_factories`` closure that ``AgentsFlow.from_definition``
invokes per run.

Note:
    ``"tool"`` must be present in ``NODE_REGISTRY`` before
    ``AgentsFlow.from_definition`` will accept these definitions; see
    :func:`ensure_tool_node_registered`.
"""
from __future__ import annotations

from typing import Any, Dict, List

from .models import ExecutionPlan

__all__ = (
    "PLAN_NODE_TYPE",
    "END_NODE_ID",
    "START_NODE_ID",
    "ensure_tool_node_registered",
    "to_flow_definition",
)

PLAN_NODE_TYPE = "tool"
START_NODE_ID = "__start__"
END_NODE_ID = "__end__"


def to_flow_definition(plan: ExecutionPlan) -> Any:
    """Build a ``FlowDefinition`` from ``plan``.

    Edges are derived from ``depends_on`` with ``condition="always"`` rather
    than the default ``on_success``: a guarded node that skips must not block
    its dependents, and per-node failure policy is expressed by
    ``PlanNode.retry`` / ``ForEach.on_item_error``, not by edge conditions.

    Args:
        plan: A validated execution plan.

    Returns:
        A ``FlowDefinition`` ready for ``AgentsFlow.from_definition``.

    Raises:
        ImportError: If the flow package is unavailable.
    """
    from parrot.bots.flows.flow.definition import (  # noqa: PLC0415
        EdgeDefinition,
        FlowDefinition,
        FlowMetadata,
        NodeDefinition,
    )

    nodes: List[Any] = [
        NodeDefinition(id=START_NODE_ID, type="start", label="start"),
        NodeDefinition(id=END_NODE_ID, type="end", label="end"),
    ]
    edges: List[Any] = []

    roots = [n.id for n in plan.nodes if not n.depends_on]
    leaves = _leaf_ids(plan)

    for plan_node in plan.nodes:
        nodes.append(
            NodeDefinition(
                id=plan_node.id,
                type=PLAN_NODE_TYPE,
                label=plan_node.description or plan_node.tool,
                max_retries=max(0, plan_node.retry.max_attempts - 1),
                config=node_config(plan_node),
                metadata={"plan": plan.name, "tool": plan_node.tool},
            )
        )
        for dep in plan_node.depends_on:
            edges.append(
                EdgeDefinition(**{"from": dep, "to": plan_node.id, "condition": "always"})
            )

    for root in roots:
        edges.append(
            EdgeDefinition(**{"from": START_NODE_ID, "to": root, "condition": "always"})
        )
    for leaf in leaves:
        edges.append(
            EdgeDefinition(**{"from": leaf, "to": END_NODE_ID, "condition": "always"})
        )

    return FlowDefinition(
        flow=plan.name,
        nodes=nodes,
        edges=edges,
        metadata=FlowMetadata(
            max_parallel_tasks=plan.metadata.max_parallel_tasks,
            execution_timeout=plan.metadata.execution_timeout,
            checkpoint=plan.metadata.checkpoint,
            durable=plan.metadata.durable,
            # Node outputs are ArtifactRefs, already small — truncating them
            # would corrupt the manifest rather than save anything.
            truncation_length=None,
        ),
    )


def node_config(plan_node: Any) -> Dict[str, Any]:
    """Serialise a :class:`~models.PlanNode` into ``NodeDefinition.config``.

    Kept as a plain dict (not the model) so a ``FlowDefinition`` stays JSON
    round-trippable for checkpointing and UI editors.

    Args:
        plan_node: The plan node to serialise.

    Returns:
        A JSON-safe config dict consumed by the ``tool`` node factory.
    """
    return plan_node.model_dump(mode="json", exclude_none=False)


def _leaf_ids(plan: ExecutionPlan) -> List[str]:
    """Return ids of nodes nothing depends on."""
    depended_on = {dep for node in plan.nodes for dep in node.depends_on}
    return [node.id for node in plan.nodes if node.id not in depended_on]


def ensure_tool_node_registered(node_cls: Any) -> None:
    """Register ``node_cls`` under ``"tool"`` in ``NODE_REGISTRY``, once.

    ``ToolNode`` ships as an ``AgentCrew`` concept and is absent from
    ``AgentsFlow``'s ``NODE_REGISTRY``; ``from_definition`` rejects unknown
    node types, so registration must happen before the first compile.
    Idempotent, because ``register_node`` raises on a duplicate name.

    Args:
        node_cls: The ``Node`` subclass to register (a ``ToolNode`` subclass
            that stores payloads to working memory).
    """
    from parrot.bots.flows.flow.flow import NODE_REGISTRY, register_node  # noqa: PLC0415

    if NODE_REGISTRY.get(PLAN_NODE_TYPE) is node_cls:
        return
    if PLAN_NODE_TYPE in NODE_REGISTRY:
        raise ValueError(
            f"NODE_REGISTRY[{PLAN_NODE_TYPE!r}] is already "
            f"{NODE_REGISTRY[PLAN_NODE_TYPE].__name__}, not {node_cls.__name__}"
        )
    register_node(PLAN_NODE_TYPE)(node_cls)
