"""Deterministic assembly: nodes + transitions → blueprint → a real definition.

No LLM runs here. The authoring stages produce fragments — a skeleton, one
node per call, a transition list — and this module joins them and compiles
the result into whichever engine's definition was asked for.

Keeping the join deterministic is the point of the whole design. A model that
had to emit a complete, internally-consistent ``CrewDefinition`` in one shot
would have to hold every node, every name and both engines' conventions in
context at once. Here it only ever has to get one node right at a time, and
the parts that are pure bookkeeping — sentinel nodes, edge direction, which
name an edge refers to — are done in code that cannot drift.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence

from .blueprint import (
    BlueprintNode,
    BlueprintSkeleton,
    BlueprintTransition,
    WorkflowBlueprint,
)

__all__ = (
    "AssemblyError",
    "assemble",
    "to_crew_definition",
    "to_flow_definition",
)

logger = logging.getLogger(__name__)

START_NODE_ID = "__start__"
END_NODE_ID = "__end__"


class AssemblyError(RuntimeError):
    """Raised when fragments cannot be joined into a coherent blueprint."""


def assemble(
    skeleton: BlueprintSkeleton,
    nodes: Sequence[BlueprintNode],
    transitions: Sequence[BlueprintTransition],
    *,
    shared_tools: Optional[Sequence[str]] = None,
) -> WorkflowBlueprint:
    """Join authored fragments into one :class:`WorkflowBlueprint`.

    Nodes are ordered to match the skeleton rather than the order they
    finished authoring in, because they are authored concurrently and a
    workflow whose node order changed between runs would be needlessly
    non-reproducible.

    Transitions that reference a node which failed to author are dropped —
    keeping them would produce a blueprint that fails referential validation
    for a reason the model cannot act on. The caller learns which nodes went
    missing by diffing against the skeleton.

    Args:
        skeleton: The stage-1 skeleton, which fixes name, engine and order.
        nodes: Authored nodes. May be shorter than the skeleton if some
            failed.
        transitions: Authored transitions.
        shared_tools: Tools granted to every agent in the workflow.

    Returns:
        The assembled blueprint.

    Raises:
        AssemblyError: If no node survived, or a node is not in the skeleton.
    """
    by_id: Dict[str, BlueprintNode] = {node.id: node for node in nodes}

    stub_ids = [stub.id for stub in skeleton.nodes]
    unexpected = sorted(set(by_id) - set(stub_ids))
    if unexpected:
        raise AssemblyError(
            f"Authored nodes not present in the skeleton: {unexpected}. "
            f"Skeleton declares: {stub_ids}."
        )

    ordered = [by_id[stub_id] for stub_id in stub_ids if stub_id in by_id]
    if not ordered:
        raise AssemblyError(
            "No node survived authoring; there is no workflow to assemble."
        )

    surviving = {node.id for node in ordered}
    dropped = [stub_id for stub_id in stub_ids if stub_id not in surviving]

    kept_transitions: List[BlueprintTransition] = []
    for transition in transitions:
        refs = transition.source_ids() + transition.target_ids()
        missing = [ref for ref in refs if ref not in surviving]
        if missing:
            logger.warning(
                "Dropping transition %s -> %s: references unauthored node(s) %s",
                transition.source, transition.target, missing,
            )
            continue
        kept_transitions.append(transition)

    if dropped:
        logger.warning("Nodes missing from the assembled workflow: %s", dropped)

    return WorkflowBlueprint(
        name=skeleton.name,
        description=skeleton.description,
        engine=skeleton.engine,
        execution_mode=_infer_execution_mode(ordered, kept_transitions),
        nodes=ordered,
        transitions=kept_transitions,
        shared_tools=list(shared_tools or []),
    )


def _infer_execution_mode(
    nodes: Sequence[BlueprintNode],
    transitions: Sequence[BlueprintTransition],
) -> str:
    """Pick the crew execution mode implied by the graph shape.

    Only meaningful for ``engine="crew"`` (a flow's DAG is its own schedule),
    but computed unconditionally so the blueprint is fully specified either
    way.

    Args:
        nodes: The surviving nodes.
        transitions: The surviving transitions.

    Returns:
        ``"parallel"`` when nothing depends on anything, ``"sequential"``
        for an unbranched chain, otherwise ``"flow"``.
    """
    if not transitions:
        return "parallel" if len(nodes) > 1 else "sequential"

    out_degree: Dict[str, int] = {}
    in_degree: Dict[str, int] = {}
    for transition in transitions:
        for source in transition.source_ids():
            out_degree[source] = out_degree.get(source, 0) + len(transition.target_ids())
        for target in transition.target_ids():
            in_degree[target] = in_degree.get(target, 0) + len(transition.source_ids())

    branching = any(count > 1 for count in out_degree.values()) or any(
        count > 1 for count in in_degree.values()
    )
    return "flow" if branching else "sequential"


# ─── compilation ─────────────────────────────────────────────────────────────


def to_crew_definition(blueprint: WorkflowBlueprint, *, tenant: str = "global") -> Any:
    """Compile a blueprint into a :class:`CrewDefinition`.

    Agents are built inline from ``agent_class``/``system_prompt``/``tools``;
    ``kind="tool"`` nodes become ``ToolNodeDefinition``s.

    Transitions become ``FlowRelation``s keyed by the **effective display
    name** — ``AgentDefinition.name or agent_id`` — because that is what
    ``AgentCrew.from_definition`` keys ``crew.agents`` by and therefore what
    relations resolve against. Getting this wrong does not raise: the
    relation silently resolves to nothing and the edge disappears. Here the
    blueprint id is used as *both* ``agent_id`` and ``name``, which makes the
    two identical and the trap unreachable.

    Args:
        blueprint: A validated blueprint with ``engine="crew"``.
        tenant: Tenant for crew isolation.

    Returns:
        A ``CrewDefinition``.

    Raises:
        AssemblyError: If the blueprint targets a different engine or holds a
            node kind a crew cannot express.
    """
    from parrot.models.crew_definition import (  # noqa: PLC0415
        AgentDefinition,
        CrewDefinition,
        FlowRelation,
        ToolNodeDefinition,
    )

    if blueprint.engine != "crew":
        raise AssemblyError(
            f"to_crew_definition requires engine='crew', got {blueprint.engine!r}."
        )

    agents: List[Any] = []
    tool_nodes: List[Any] = []

    for node in blueprint.nodes:
        if node.kind == "agent":
            config: Dict[str, Any] = {}
            if node.model:
                config["llm"] = node.model
            agents.append(
                AgentDefinition(
                    agent_id=node.id,
                    # Identical on purpose — see the docstring: relations key
                    # off `name or agent_id`, so equal values make the
                    # display-name trap structurally impossible.
                    name=node.id,
                    agent_class=node.agent_class or "BasicAgent",
                    config=config,
                    tools=list(node.tools),
                    system_prompt=node.system_prompt,
                )
            )
        elif node.kind == "tool":
            tool_nodes.append(
                ToolNodeDefinition(
                    node_id=node.id,
                    tool=node.tool,
                    name=node.title or node.id,
                    description=node.purpose or None,
                    args=list(node.args),
                    kwargs=dict(node.kwargs),
                )
            )
        else:
            raise AssemblyError(
                f"Node {node.id!r} of kind {node.kind!r} cannot be expressed "
                "in a crew; compile this blueprint with engine='flow'."
            )

    relations = [
        FlowRelation(source=transition.source, target=transition.target)
        for transition in blueprint.transitions
    ]

    return CrewDefinition(
        tenant=tenant,
        name=blueprint.name,
        description=blueprint.description or None,
        execution_mode=(
            "flow" if relations else blueprint.execution_mode
        ),
        agents=agents,
        tool_nodes=tool_nodes,
        flow_relations=relations,
        shared_tools=list(blueprint.shared_tools),
    )


def to_flow_definition(blueprint: WorkflowBlueprint) -> Any:
    """Compile a blueprint into a :class:`FlowDefinition`.

    Adds the ``__start__``/``__end__`` sentinels and wires them to the graph's
    roots and leaves, exactly as ``parrot.bots.flows.plan.compile`` does — a
    model never has to reason about entry and exit.

    Args:
        blueprint: A validated blueprint with ``engine="flow"``.

    Returns:
        A ``FlowDefinition``.

    Raises:
        AssemblyError: If the blueprint targets a different engine.
    """
    from parrot.bots.flows.flow.definition import (  # noqa: PLC0415
        EdgeDefinition,
        FlowDefinition,
        NodeDefinition,
    )

    if blueprint.engine != "flow":
        raise AssemblyError(
            f"to_flow_definition requires engine='flow', got {blueprint.engine!r}."
        )

    nodes: List[Any] = [
        NodeDefinition(id=START_NODE_ID, type="start", label="start"),
        NodeDefinition(id=END_NODE_ID, type="end", label="end"),
    ]
    for node in blueprint.nodes:
        nodes.append(
            NodeDefinition(
                id=node.id,
                type=node.kind,
                label=node.title or node.id,
                agent_ref=node.agent_ref,
                instruction=node.system_prompt,
                config=_flow_node_config(node),
                metadata={"purpose": node.purpose} if node.purpose else {},
            )
        )

    edges: List[Any] = []
    for transition in blueprint.transitions:
        for source in transition.source_ids():
            edges.append(
                EdgeDefinition(
                    **{"from": source},
                    to=(
                        transition.target
                        if isinstance(transition.target, str)
                        else list(transition.target)
                    ),
                    condition=transition.condition,
                    predicate=transition.predicate,
                    instruction=transition.instruction,
                )
            )

    targets = {
        target
        for transition in blueprint.transitions
        for target in transition.target_ids()
    }
    sources = {
        source
        for transition in blueprint.transitions
        for source in transition.source_ids()
    }
    node_ids = blueprint.node_ids()
    roots = [node_id for node_id in node_ids if node_id not in targets]
    leaves = [node_id for node_id in node_ids if node_id not in sources]

    edges.extend(
        EdgeDefinition(**{"from": START_NODE_ID}, to=root, condition="always")
        for root in roots
    )
    edges.extend(
        EdgeDefinition(**{"from": leaf}, to=END_NODE_ID, condition="on_success")
        for leaf in leaves
    )

    return FlowDefinition(
        flow=blueprint.name,
        description=blueprint.description,
        nodes=nodes,
        edges=edges,
    )


def _flow_node_config(node: BlueprintNode) -> Dict[str, Any]:
    """Build a flow node's ``config`` block from the blueprint node.

    Args:
        node: The blueprint node.

    Returns:
        The ``NodeDefinition.config`` payload for this node's type.
    """
    if node.kind == "tool":
        # Mirrors the crew ToolNode contract; the flow-side "tool" node type
        # reads its tool and arguments from config.
        return {"tool": node.tool, "args": list(node.args), "kwargs": dict(node.kwargs)}
    return dict(node.config)
