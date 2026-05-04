"""Final regression tests for FEAT-137 AgentCrew Primitives Migration.

Tests verify backward-compatible imports, CrewResult structure,
absence of circular imports, and that dead local definitions have
been removed from crew.py.
"""
from __future__ import annotations

import inspect
import subprocess
import sys
from typing import Any

import pytest

from _crew_test_helpers import DummyAgent  # shared test infrastructure


# ---------------------------------------------------------------------------
# Backward-compatible import tests
# ---------------------------------------------------------------------------


class TestBackwardCompatImports:
    """Verify that public imports from crew.py still work."""

    def test_import_agentnode_from_crew(self) -> None:
        from parrot.bots.orchestration.crew import AgentNode
        assert AgentNode is not None

    def test_import_flowcontext_from_crew(self) -> None:
        from parrot.bots.orchestration.crew import FlowContext
        assert FlowContext is not None

    def test_import_crewresult_from_models(self) -> None:
        from parrot.models.crew import CrewResult
        assert CrewResult is not None

    def test_agentnode_is_crewagentnode(self) -> None:
        from parrot.bots.orchestration.crew import AgentNode, _CrewAgentNode
        assert AgentNode is _CrewAgentNode

    def test_flowcontext_is_core_flowcontext(self) -> None:
        """FlowContext re-exported from crew.py is the core one."""
        from parrot.bots.orchestration.crew import FlowContext
        from parrot.bots.flows.core.context import FlowContext as CoreFlowContext
        assert FlowContext is CoreFlowContext

    def test_import_agentref_from_crew(self) -> None:
        from parrot.bots.orchestration.crew import AgentRef
        assert AgentRef is not None

    def test_import_agentcrew(self) -> None:
        from parrot.bots.orchestration.crew import AgentCrew
        assert AgentCrew is not None


# ---------------------------------------------------------------------------
# Verify dead definitions are removed
# ---------------------------------------------------------------------------


class TestDeadCodeRemoved:
    """Verify that local definitions replaced by core primitives are gone."""

    def test_no_local_flowcontext_class(self) -> None:
        """crew.py should not define its own FlowContext class."""
        from parrot.bots.orchestration import crew
        source = inspect.getsource(crew)
        # The source should not contain 'class FlowContext:' (local def)
        # It SHOULD have 'FlowContext' as an import though
        import re
        local_class = re.findall(r'^class FlowContext\b', source, re.MULTILINE)
        assert len(local_class) == 0, "Local FlowContext class should be removed"


# ---------------------------------------------------------------------------
# No circular imports
# ---------------------------------------------------------------------------


class TestNoCircularImports:
    """Verify flows.core does NOT import from orchestration.crew."""

    def test_flows_core_does_not_import_crew(self) -> None:
        """flows.core must not have actual import statements referencing crew."""
        import parrot.bots.flows.core as core
        source_dir = inspect.getfile(core).rsplit("/", 1)[0]
        # Look for actual import statements, not docstring mentions
        result = subprocess.run(
            ["grep", "-rn", r"^\(from\|import\).*orchestration\.crew", source_dir],
            capture_output=True,
            text=True,
        )
        assert result.stdout.strip() == "", (
            f"Circular import detected in flows.core: {result.stdout}"
        )


# ---------------------------------------------------------------------------
# __all__ export list
# ---------------------------------------------------------------------------


class TestModuleExports:
    """Verify crew.py has __all__ listing public re-exports."""

    def test_crew_has_dunder_all(self) -> None:
        from parrot.bots.orchestration import crew
        assert hasattr(crew, "__all__"), "crew.py should define __all__"

    def test_dunder_all_contains_public_names(self) -> None:
        from parrot.bots.orchestration import crew
        expected = {"AgentCrew", "AgentNode", "FlowContext", "AgentRef"}
        assert expected.issubset(set(crew.__all__))


# ---------------------------------------------------------------------------
# CrewResult structure tests
# ---------------------------------------------------------------------------


class TestCrewResultStructure:
    """Verify CrewResult fields and method outputs are intact."""

    async def test_result_has_expected_fields(self) -> None:
        from parrot.bots.orchestration.crew import AgentCrew

        a = DummyAgent("a")
        crew = AgentCrew(
            name="TestFinal",
            agents=[a],
            auto_configure=False,
        )
        result = await crew.run_sequential("test", generate_summary=False)
        assert hasattr(result, "output")
        assert hasattr(result, "status")
        assert hasattr(result, "agents")
        assert hasattr(result, "errors")
        assert hasattr(result, "total_time")
        assert hasattr(result, "metadata")
        assert hasattr(result, "execution_log")

    async def test_result_to_dict(self) -> None:
        from parrot.bots.orchestration.crew import AgentCrew

        a = DummyAgent("a")
        crew = AgentCrew(
            name="TestFinal",
            agents=[a],
            auto_configure=False,
        )
        result = await crew.run_sequential("test", generate_summary=False)
        d = result.to_dict()
        assert isinstance(d, dict)
        assert "output" in d
        assert "status" in d
