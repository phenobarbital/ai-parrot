"""
Unit tests for AgentCrew.from_definition() classmethod (TASK-1061).

Verifies that:
- A crew can be created from a CrewDefinition with a class_resolver.
- Agent names, system_prompt, and config are applied correctly.
- Shared tools are added when a tool_resolver is provided.
- Missing tools (resolver returns None) are skipped.
- Flow relations are wired when execution_mode == FLOW.
- Falls back to BasicAgent when class_resolver returns None.
- Extra **kwargs are forwarded to AgentCrew.__init__.
- _resolve_agents_by_ids helper works correctly.
"""
import pytest
from unittest.mock import MagicMock, create_autospec
from parrot.models.crew_definition import (
    CrewDefinition,
    AgentDefinition,
    FlowRelation,
    ExecutionMode,
)
from parrot.bots.orchestration.crew import AgentCrew
from parrot.bots.agent import BasicAgent
from parrot.tools.abstract import AbstractTool


def make_crew_def(**overrides):
    """Build a minimal valid CrewDefinition with sensible defaults.

    Args:
        **overrides: Fields to override on the default CrewDefinition.

    Returns:
        A CrewDefinition instance.
    """
    defaults = dict(
        name="test-crew",
        agents=[
            AgentDefinition(agent_id="agent-1", name="Agent One"),
            AgentDefinition(agent_id="agent-2", name="Agent Two"),
        ],
    )
    defaults.update(overrides)
    return CrewDefinition(**defaults)


def dummy_resolver(class_name: str):
    """Always resolves to BasicAgent regardless of class_name.

    Args:
        class_name: The requested class name string.

    Returns:
        The BasicAgent class.
    """
    return BasicAgent


class TestFromDefinition:
    """Tests for AgentCrew.from_definition() classmethod."""

    def test_basic_creation(self):
        """from_definition returns a valid AgentCrew with the correct name."""
        crew_def = make_crew_def()
        crew = AgentCrew.from_definition(crew_def, class_resolver=dummy_resolver)
        assert crew.name == "test-crew"
        assert len(crew.agents) == 2

    def test_agent_names(self):
        """Agents are keyed by their name (from AgentDefinition.name)."""
        crew_def = make_crew_def()
        crew = AgentCrew.from_definition(crew_def, class_resolver=dummy_resolver)
        assert "Agent One" in crew.agents
        assert "Agent Two" in crew.agents

    def test_fallback_to_basic_agent(self):
        """When class_resolver returns None, BasicAgent is used as fallback."""
        crew_def = make_crew_def()
        crew = AgentCrew.from_definition(
            crew_def,
            class_resolver=lambda _: None,
        )
        assert len(crew.agents) == 2
        for agent in crew.agents.values():
            assert isinstance(agent, BasicAgent)

    def test_system_prompt_set(self):
        """system_prompt from AgentDefinition is applied to the agent."""
        crew_def = make_crew_def(
            agents=[AgentDefinition(
                agent_id="a1",
                name="A1",
                system_prompt="You are helpful.",
            )]
        )
        crew = AgentCrew.from_definition(crew_def, class_resolver=dummy_resolver)
        agent = crew.agents["A1"]
        assert agent.system_prompt == "You are helpful."

    def test_shared_tools_resolved(self):
        """Shared tools are added to the crew when tool_resolver is provided."""
        # Use create_autospec so isinstance(mock, AbstractTool) passes
        mock_tool = create_autospec(AbstractTool, instance=True)
        mock_tool.name = "search"
        crew_def = make_crew_def(shared_tools=["search"])
        crew = AgentCrew.from_definition(
            crew_def,
            class_resolver=dummy_resolver,
            tool_resolver=lambda name: mock_tool if name == "search" else None,
        )
        assert crew.shared_tool_manager.get_tool("search") is not None

    def test_no_tool_resolver_skips_shared_tools(self):
        """Shared tools are skipped when no tool_resolver is provided."""
        crew_def = make_crew_def(shared_tools=["search"])
        crew = AgentCrew.from_definition(crew_def, class_resolver=dummy_resolver)
        assert crew.shared_tool_manager.get_tool("search") is None

    def test_kwargs_forwarded(self):
        """Extra **kwargs (including max_parallel_tasks) are forwarded to AgentCrew.__init__."""
        crew_def = make_crew_def()
        # Passing max_parallel_tasks as kwarg should override crew_def value.
        crew = AgentCrew.from_definition(
            crew_def,
            class_resolver=dummy_resolver,
            max_parallel_tasks=5,
        )
        assert crew is not None
        assert crew.max_parallel_tasks == 5

    def test_flow_relations(self):
        """Flow relations are wired in workflow_graph when execution_mode == FLOW."""
        crew_def = make_crew_def(
            execution_mode=ExecutionMode.FLOW,
            flow_relations=[
                FlowRelation(source="Agent One", target="Agent Two")
            ],
        )
        crew = AgentCrew.from_definition(crew_def, class_resolver=dummy_resolver)
        assert "Agent One" in crew.workflow_graph

    def test_resolve_agents_by_ids(self):
        """_resolve_agents_by_ids returns all agents for given IDs."""
        agents = {"a1": MagicMock(), "a2": MagicMock()}
        result = AgentCrew._resolve_agents_by_ids(agents, ["a1", "a2"])
        assert len(result) == 2

    def test_resolve_agents_by_ids_missing(self):
        """_resolve_agents_by_ids silently skips unknown agent IDs."""
        agents = {"a1": MagicMock()}
        result = AgentCrew._resolve_agents_by_ids(agents, ["a1", "missing"])
        assert len(result) == 1

    def test_agent_id_used_when_name_is_none(self):
        """When AgentDefinition.name is None, agent_id is used as agent name."""
        crew_def = make_crew_def(
            agents=[AgentDefinition(agent_id="my-agent-id")]  # no name
        )
        crew = AgentCrew.from_definition(crew_def, class_resolver=dummy_resolver)
        assert "my-agent-id" in crew.agents
