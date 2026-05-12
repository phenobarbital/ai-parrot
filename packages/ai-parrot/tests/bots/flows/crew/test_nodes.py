"""Unit tests for CrewAgentNode — FEAT-163 Pydantic shape migration.

Tests verify:
- CrewAgentNode is a Pydantic BaseModel subclass (not a dataclass).
- Pydantic keyword construction works.
- _build_prompt produces output identical to the legacy _format_prompt.
- execute_in_context no longer exists.
- Frozen model: field reassignment raises.
- FSM is auto-created.
"""
import pytest
from pydantic import BaseModel, ValidationError

from parrot.bots.flows.crew.nodes import CrewAgentNode
from parrot.bots.flows.core.fsm import AgentTaskMachine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeAgent:
    """Minimal AgentLike implementation for testing."""

    @property
    def name(self) -> str:
        return "researcher"

    async def invoke(self, prompt: str, **kwargs: object) -> object:
        return f"invoke: {prompt}"

    async def ask(self, question: str = "", **kwargs: object) -> object:
        return {"content": f"echo: {question}"}


class StubCtxNoDeps:
    """Context stub with no dependency results."""

    def get_input_for_agent(self, name: str, deps: object) -> dict:
        return {"task": "Research X"}


class StubCtxWithDeps:
    """Context stub with dependency results."""

    def get_input_for_agent(self, name: str, deps: object) -> dict:
        return {
            "task": "Summarize",
            "dependencies": {"analyst": "data points"},
        }


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestCrewAgentNodeConstruction:
    def test_pydantic_construction(self) -> None:
        node = CrewAgentNode(
            agent=FakeAgent(),
            node_id="researcher-1",
            dependencies={"analyst"},
            successors={"writer"},
        )
        assert node.node_id == "researcher-1"
        assert node.dependencies == {"analyst"}
        assert node.successors == {"writer"}

    def test_is_pydantic_basemodel(self) -> None:
        assert issubclass(CrewAgentNode, BaseModel)

    def test_fsm_auto_created(self) -> None:
        node = CrewAgentNode(agent=FakeAgent(), node_id="r1")
        assert node.fsm is not None
        assert isinstance(node.fsm, AgentTaskMachine)

    def test_frozen_blocks_field_reassignment(self) -> None:
        node = CrewAgentNode(agent=FakeAgent(), node_id="r1")
        with pytest.raises((ValidationError, TypeError, AttributeError)):
            node.node_id = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# _build_prompt parity with legacy _format_prompt
# ---------------------------------------------------------------------------


class TestCrewAgentNodeBuildPrompt:
    def test_build_prompt_no_deps_returns_task(self) -> None:
        """_build_prompt with no dependencies returns the task verbatim."""
        node = CrewAgentNode(agent=FakeAgent(), node_id="r1")
        result = node._build_prompt(StubCtxNoDeps(), {})
        assert result == "Research X"

    def test_build_prompt_with_deps_includes_task(self) -> None:
        node = CrewAgentNode(agent=FakeAgent(), node_id="r1")
        result = node._build_prompt(StubCtxWithDeps(), {})
        assert "Task: Summarize" in result

    def test_build_prompt_with_deps_includes_dependency_header(self) -> None:
        node = CrewAgentNode(agent=FakeAgent(), node_id="r1")
        result = node._build_prompt(StubCtxWithDeps(), {})
        assert "--- From analyst ---" in result

    def test_build_prompt_with_deps_includes_result(self) -> None:
        node = CrewAgentNode(agent=FakeAgent(), node_id="r1")
        result = node._build_prompt(StubCtxWithDeps(), {})
        assert "data points" in result

    def test_format_static_parity_no_deps(self) -> None:
        """_format() with empty dependencies returns task only."""
        result = CrewAgentNode._format({"task": "Do thing", "dependencies": {}})
        assert result == "Do thing"

    def test_format_static_parity_with_deps(self) -> None:
        """_format() output matches legacy _format_prompt logic."""
        result = CrewAgentNode._format(
            {"task": "T", "dependencies": {"A": "result_A"}}
        )
        assert "Task: T" in result
        assert "--- From A ---" in result
        assert "result_A" in result

    def test_format_static_empty_dict(self) -> None:
        """_format() with empty dict returns empty string."""
        result = CrewAgentNode._format({})
        assert result == ""


# ---------------------------------------------------------------------------
# execute_in_context removed
# ---------------------------------------------------------------------------


class TestExecuteInContextRemoved:
    def test_no_execute_in_context_attribute(self) -> None:
        node = CrewAgentNode(agent=FakeAgent(), node_id="r1")
        assert not hasattr(node, "execute_in_context")

    def test_has_execute_method(self) -> None:
        """The inherited execute() method must be present."""
        node = CrewAgentNode(agent=FakeAgent(), node_id="r1")
        assert hasattr(node, "execute")
        assert callable(node.execute)
