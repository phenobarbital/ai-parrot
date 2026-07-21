"""
Unit tests for `AgentCrew._finalize_infographic` integration (FEAT-308).

TASK-1779: `AgentCrew._finalize_infographic` Integration

NOTE (Codebase Contract correction): the task's own Test Specification
patched `parrot.registry.agent_registry.get`, but `AgentRegistry` has no
`.get()` method (verified against `registry/registry.py:513-514`). The
implementation resolves agents via `agent_registry.get_metadata(name)`
(returns `Optional[BotMetadata]`, `.factory` holds the class). Tests below
patch the corrected symbol.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.bots.flows.crew.crew import AgentCrew


class TestFinalizeInfographicFlagOff:
    @pytest.mark.asyncio
    async def test_flag_off_is_noop(self):
        """generate_infographic=False -> infographic is None, no agent resolved."""
        crew = AgentCrew(name="test", generate_infographic=False)
        result = MagicMock()
        result.infographic = None
        await crew._finalize_infographic(result)
        assert result.infographic is None

    def test_flag_defaults_to_false(self):
        """generate_infographic defaults to False (non-breaking default)."""
        crew = AgentCrew(name="test")
        assert crew.generate_infographic is False
        assert crew.result_agent_name == "result-agent"


class TestFinalizeGracefulDegrade:
    @pytest.mark.asyncio
    async def test_render_exception_swallowed(self):
        """get_metadata raises -> logged, infographic=None, result.status unchanged."""
        crew = AgentCrew(name="test", generate_infographic=True)
        crew.execution_memory = MagicMock()
        result = MagicMock()
        result.infographic = None
        result.summary = "test summary"
        result.output = "test output"
        original_status = result.status
        with patch(
            "parrot.registry.agent_registry.get_metadata",
            side_effect=RuntimeError("boom"),
        ):
            await crew._finalize_infographic(result)
        assert result.infographic is None
        assert result.status == original_status

    @pytest.mark.asyncio
    async def test_generate_infographic_exception_swallowed(self):
        """ResultAgent.generate_infographic raising is swallowed and logged."""
        crew = AgentCrew(name="test", generate_infographic=True)
        crew.execution_memory = MagicMock()
        result = MagicMock()
        result.infographic = None
        result.summary = "test summary"
        result.output = "test output"

        fake_metadata = MagicMock()
        fake_agent_instance = MagicMock()
        fake_agent_instance.generate_infographic = AsyncMock(
            side_effect=RuntimeError("render failed")
        )
        fake_metadata.factory = MagicMock(return_value=fake_agent_instance)

        with patch(
            "parrot.registry.agent_registry.get_metadata",
            return_value=fake_metadata,
        ):
            await crew._finalize_infographic(result)

        assert result.infographic is None


class TestUnknownAgentName:
    @pytest.mark.asyncio
    async def test_unknown_result_agent_name_skips(self):
        """result_agent_name not in registry -> warn + skip, no raise."""
        crew = AgentCrew(name="test", generate_infographic=True, result_agent_name="nonexistent")
        crew.execution_memory = MagicMock()
        result = MagicMock()
        result.infographic = None
        result.summary = ""
        result.output = ""
        with patch(
            "parrot.registry.agent_registry.get_metadata",
            return_value=None,
        ):
            await crew._finalize_infographic(result)
        assert result.infographic is None


class TestFinalizeInfographicSuccess:
    @pytest.mark.asyncio
    async def test_populates_result_infographic(self):
        """Happy path: resolves agent, builds tabs, populates result.infographic."""
        crew = AgentCrew(name="test", generate_infographic=True)
        crew.execution_memory = MagicMock()
        crew.execution_memory.results = {}
        result = MagicMock()
        result.infographic = None
        result.summary = "All good."
        result.output = "Final output."

        fake_render_result = MagicMock()
        fake_agent_instance = MagicMock()
        fake_agent_instance.generate_infographic = AsyncMock(return_value=fake_render_result)
        fake_metadata = MagicMock()
        fake_metadata.factory = MagicMock(return_value=fake_agent_instance)

        with patch(
            "parrot.registry.agent_registry.get_metadata",
            return_value=fake_metadata,
        ):
            await crew._finalize_infographic(result)

        assert result.infographic is fake_render_result
        fake_agent_instance.generate_infographic.assert_called_once()
        _, call_kwargs = fake_agent_instance.generate_infographic.call_args
        assert call_kwargs["summary"] == "All good."
        assert call_kwargs["crew_name"] == "test"
