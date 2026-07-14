"""
Unit tests for deterministic tool nodes in AgentCrew.from_definition().

Verifies that:
- ToolNodeDefinition entries become ToolNode crew members (registered in
  both crew.agents and crew.workflow_graph).
- args/kwargs/description are passed through to the node.
- Flow relations may reference tool nodes by node_id as source or target.
- An unresolvable tool raises ValueError (structural DAG member).
- tool_nodes without a tool_resolver raises ValueError.
"""
from unittest.mock import create_autospec

import pytest

from parrot.models.crew_definition import (
    CrewDefinition,
    AgentDefinition,
    ToolNodeDefinition,
    FlowRelation,
    ExecutionMode,
)
from parrot.bots.flows.crew import AgentCrew, ToolNode
from parrot.bots.agent import BasicAgent
from parrot.tools.abstract import AbstractTool


def make_crew_def(**overrides):
    """Build a minimal valid CrewDefinition with a tool node."""
    defaults = dict(
        name="test-crew",
        agents=[
            AgentDefinition(agent_id="agent-1", name="Agent One"),
        ],
        tool_nodes=[
            ToolNodeDefinition(
                node_id="fetch",
                tool="yfinance",
                description="Fetch prices deterministically",
                kwargs={"symbol": "{input}", "period": "1mo"},
                args=["positional"],
            ),
        ],
    )
    defaults.update(overrides)
    return CrewDefinition(**defaults)


def dummy_resolver(class_name: str):
    """Always resolves to BasicAgent regardless of class_name."""
    return BasicAgent


class TestFromDefinitionToolNodes:
    """Tests for tool_nodes wiring in AgentCrew.from_definition()."""

    def test_tool_node_registered_in_crew(self):
        """The tool node appears in crew.agents and crew.workflow_graph."""
        mock_tool = create_autospec(AbstractTool, instance=True)
        mock_tool.name = "yfinance"
        crew = AgentCrew.from_definition(
            make_crew_def(),
            class_resolver=dummy_resolver,
            tool_resolver=lambda name: mock_tool if name == "yfinance" else None,
        )
        node = crew.agents["fetch"]
        assert isinstance(node, ToolNode)
        assert crew.workflow_graph["fetch"] is node
        assert node.tool is mock_tool
        assert node.args == ["positional"]
        assert node.kwargs == {"symbol": "{input}", "period": "1mo"}
        assert node.description == "Fetch prices deterministically"

    def test_flow_relation_references_tool_node(self):
        """Tool nodes can be flow-relation sources/targets by node_id."""
        mock_tool = create_autospec(AbstractTool, instance=True)
        mock_tool.name = "yfinance"
        crew_def = make_crew_def(
            execution_mode=ExecutionMode.FLOW,
            flow_relations=[
                FlowRelation(source="fetch", target="Agent One"),
            ],
        )
        crew = AgentCrew.from_definition(
            crew_def,
            class_resolver=dummy_resolver,
            tool_resolver=lambda name: mock_tool,
        )
        assert "fetch" in crew.workflow_graph["Agent One"].dependencies
        assert "Agent One" in crew.workflow_graph["fetch"].successors

    def test_unresolvable_tool_raises(self):
        """A tool the resolver cannot find must raise (not silently skip)."""
        with pytest.raises(ValueError) as excinfo:
            AgentCrew.from_definition(
                make_crew_def(),
                class_resolver=dummy_resolver,
                tool_resolver=lambda name: None,
            )
        assert "yfinance" in str(excinfo.value)
        assert "fetch" in str(excinfo.value)

    def test_tool_nodes_without_resolver_raises(self):
        """tool_nodes present but no tool_resolver must raise."""
        with pytest.raises(ValueError):
            AgentCrew.from_definition(
                make_crew_def(),
                class_resolver=dummy_resolver,
            )

    def test_no_tool_nodes_backward_compatible(self):
        """Definitions without tool_nodes build exactly as before."""
        crew_def = make_crew_def(tool_nodes=[])
        crew = AgentCrew.from_definition(
            crew_def,
            class_resolver=dummy_resolver,
        )
        assert "Agent One" in crew.agents
        assert not any(
            isinstance(member, ToolNode) for member in crew.agents.values()
        )
