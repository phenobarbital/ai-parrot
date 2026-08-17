"""Deterministic assembly and compilation to both engines.

This is the load-bearing half of the design: whatever the model produces,
these functions decide what the workflow actually *is*. The compiled output
is asserted to pass the target model's own validators, because a definition
that only round-trips through our code is worthless.
"""
from __future__ import annotations

import pytest

from parrot.bots.flows.authoring.assembler import (
    AssemblyError,
    assemble,
    to_crew_definition,
    to_flow_definition,
)
from parrot.bots.flows.authoring.blueprint import (
    BlueprintNode,
    BlueprintSkeleton,
    BlueprintTransition,
    NodeStub,
)


def _skeleton(engine: str = "crew", **overrides) -> BlueprintSkeleton:
    payload = {
        "name": "Blog Pipeline",
        "description": "research, write, publish",
        "engine": engine,
        "nodes": [
            NodeStub(id="researcher", kind="agent", purpose="Research the topic"),
            NodeStub(id="writer", kind="agent", purpose="Write the post"),
            NodeStub(id="publisher", kind="tool", purpose="Publish it"),
        ],
    }
    payload.update(overrides)
    return BlueprintSkeleton(**payload)


def _nodes():
    return [
        BlueprintNode(
            id="researcher", kind="agent", system_prompt="You research.",
            tools=["google_search"],
        ),
        BlueprintNode(id="writer", kind="agent", system_prompt="You write."),
        BlueprintNode(
            id="publisher", kind="tool", tool="rest_api",
            kwargs={"url": "https://blog/wp-json/wp/v2/posts"},
        ),
    ]


def _chain():
    return [
        BlueprintTransition(source="researcher", target="writer"),
        BlueprintTransition(source="writer", target="publisher"),
    ]


# ── assembly ─────────────────────────────────────────────────────────────────

def test_assemble_orders_nodes_by_the_skeleton_not_arrival():
    """Nodes are authored concurrently; order must stay reproducible."""
    shuffled = list(reversed(_nodes()))
    blueprint = assemble(_skeleton(), shuffled, _chain())
    assert blueprint.node_ids() == ["researcher", "writer", "publisher"]


def test_assemble_drops_transitions_referencing_an_unauthored_node():
    nodes = [node for node in _nodes() if node.id != "publisher"]
    blueprint = assemble(_skeleton(), nodes, _chain())
    assert blueprint.node_ids() == ["researcher", "writer"]
    assert [(t.source, t.target) for t in blueprint.transitions] == [
        ("researcher", "writer")
    ]


def test_assemble_rejects_a_node_absent_from_the_skeleton():
    extra = _nodes() + [BlueprintNode(id="stowaway", kind="agent")]
    with pytest.raises(AssemblyError, match="not present in the skeleton"):
        assemble(_skeleton(), extra, _chain())


def test_assemble_rejects_an_empty_node_set():
    with pytest.raises(AssemblyError, match="No node survived"):
        assemble(_skeleton(), [], [])


@pytest.mark.parametrize(
    "transitions,expected",
    [
        ([], "parallel"),
        ("chain", "sequential"),
        ("fanout", "flow"),
    ],
)
def test_execution_mode_follows_the_graph_shape(transitions, expected):
    if transitions == "chain":
        transitions = _chain()
    elif transitions == "fanout":
        transitions = [
            BlueprintTransition(source="researcher", target="writer"),
            BlueprintTransition(source="researcher", target="publisher"),
        ]
    blueprint = assemble(_skeleton(), _nodes(), transitions)
    assert blueprint.execution_mode == expected


# ── crew compilation ─────────────────────────────────────────────────────────

def test_to_crew_definition_splits_agents_and_tool_nodes():
    definition = to_crew_definition(assemble(_skeleton(), _nodes(), _chain()))
    assert [a.agent_id for a in definition.agents] == ["researcher", "writer"]
    assert [t.node_id for t in definition.tool_nodes] == ["publisher"]
    assert definition.tool_nodes[0].tool == "rest_api"


def test_crew_relations_use_the_effective_display_name():
    """AgentCrew keys crew.agents by `name or agent_id`, and relations resolve
    against that mapping — a mismatch silently deletes the edge."""
    definition = to_crew_definition(assemble(_skeleton(), _nodes(), _chain()))
    effective = {a.name or a.agent_id for a in definition.agents}
    effective |= {t.node_id for t in definition.tool_nodes}
    for relation in definition.flow_relations:
        assert relation.source in effective
        assert relation.target in effective


def test_crew_definition_passes_its_own_validators():
    """The compiled crew must satisfy the referential + acyclicity checks."""
    from parrot.models.crew_definition import CrewDefinition

    definition = to_crew_definition(assemble(_skeleton(), _nodes(), _chain()))
    # Round-trip through JSON: this is how it reaches a job record.
    CrewDefinition.model_validate(definition.model_dump(mode="json"))


def test_crew_switches_to_flow_mode_when_it_has_relations():
    definition = to_crew_definition(assemble(_skeleton(), _nodes(), _chain()))
    assert definition.execution_mode.value == "flow"


def test_crew_rejects_a_flow_only_node_kind():
    skeleton = _skeleton(
        nodes=[NodeStub(id="vote", kind="decision", purpose="decide")]
    )
    blueprint = assemble(
        skeleton,
        [BlueprintNode(id="vote", kind="decision", config={"mode": "ballot"})],
        [],
    )
    with pytest.raises(AssemblyError, match="cannot be expressed in a crew"):
        to_crew_definition(blueprint)


def test_to_crew_definition_rejects_a_flow_blueprint():
    blueprint = assemble(_skeleton(engine="flow"), _nodes(), _chain())
    with pytest.raises(AssemblyError, match="requires engine='crew'"):
        to_crew_definition(blueprint)


# ── flow compilation ─────────────────────────────────────────────────────────

def _flow_blueprint():
    skeleton = _skeleton(
        engine="flow",
        nodes=[
            NodeStub(id="researcher", kind="agent", purpose="Research"),
            NodeStub(id="writer", kind="agent", purpose="Write"),
        ],
    )
    nodes = [
        BlueprintNode(id="researcher", kind="agent", agent_ref="researcher_agent"),
        BlueprintNode(id="writer", kind="agent", agent_ref="writer_agent"),
    ]
    return assemble(
        skeleton, nodes, [BlueprintTransition(source="researcher", target="writer")]
    )


def test_flow_definition_gets_start_and_end_sentinels():
    definition = to_flow_definition(_flow_blueprint())
    ids = [node.id for node in definition.nodes]
    assert "__start__" in ids and "__end__" in ids


def test_flow_sentinels_wire_to_roots_and_leaves():
    definition = to_flow_definition(_flow_blueprint())
    edges = {(edge.from_, edge.to) for edge in definition.edges}
    assert ("__start__", "researcher") in edges
    assert ("writer", "__end__") in edges


def test_flow_definition_passes_its_own_validators():
    """Referential integrity and acyclicity are enforced by FlowDefinition."""
    from parrot.bots.flows.flow.definition import FlowDefinition

    definition = to_flow_definition(_flow_blueprint())
    FlowDefinition.model_validate(definition.model_dump(mode="json", by_alias=True))


def test_flow_tool_node_carries_its_tool_in_config():
    skeleton = _skeleton(
        engine="flow", nodes=[NodeStub(id="pub", kind="tool", purpose="publish")]
    )
    blueprint = assemble(
        skeleton,
        [BlueprintNode(id="pub", kind="tool", tool="rest_api", kwargs={"url": "u"})],
        [],
    )
    definition = to_flow_definition(blueprint)
    node = next(n for n in definition.nodes if n.id == "pub")
    assert node.config["tool"] == "rest_api"
    assert node.config["kwargs"] == {"url": "u"}


def test_to_flow_definition_rejects_a_crew_blueprint():
    blueprint = assemble(_skeleton(), _nodes(), _chain())
    with pytest.raises(AssemblyError, match="requires engine='flow'"):
        to_flow_definition(blueprint)
