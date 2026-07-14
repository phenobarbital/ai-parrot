"""
Unit tests for `ResultAgent` (FEAT-308).

TASK-1778: `ResultAgent` — Registered Agent for Infographic Rendering

NOTE (Codebase Contract correction): the task's own Test Specification used
`agent_registry.get("result-agent")`, but `AgentRegistry` has no `.get()`
method. Verified against `registry/registry.py:513-514`, the lookup API is
`get_metadata(name) -> Optional[BotMetadata]` (whose `.factory` holds the
registered class). Tests below use the corrected API.
"""
from unittest.mock import AsyncMock, patch

import pytest

from parrot.registry import agent_registry


class TestResultAgentRegistration:
    def test_result_agent_registered(self):
        """result-agent is registered in the agent registry."""
        from parrot.bots.flows.result_agent import ResultAgent  # noqa: F401
        metadata = agent_registry.get_metadata("result-agent")
        assert metadata is not None
        assert metadata.factory is ResultAgent

    def test_agent_tools_returns_infographic_toolkit(self):
        """agent_tools() yields InfographicToolkit tools."""
        from parrot.bots.flows.result_agent import ResultAgent
        agent = ResultAgent(name="test-result-agent")
        tools = agent.agent_tools()
        assert len(tools) > 0
        tool_names = [t.name if hasattr(t, "name") else str(t) for t in tools]
        assert any("render" in n.lower() or "infographic" in n.lower() for n in tool_names)


class TestResultAgentDefaultLLM:
    def test_default_llm_when_none_supplied(self):
        """With no crew LLM, ResultAgent falls back to a default (GoogleGenAIClient)."""
        from parrot.bots.flows.result_agent import ResultAgent
        agent = ResultAgent(name="test-result-agent")
        # Should not raise — default LLM is configured internally by BasicAgent
        assert agent is not None
        assert agent._llm is not None


class TestGenerateInfographic:
    @pytest.mark.asyncio
    async def test_generate_infographic_renders_via_toolkit(self):
        """generate_infographic() authors Tab 1 and renders via the toolkit."""
        from parrot.bots.flows.result_agent import ResultAgent
        from parrot.tools.infographic_toolkit import InfographicRenderResult

        agent = ResultAgent(name="test-result-agent")
        fake_result = InfographicRenderResult(
            artifact_id="artifact-1",
            html_url="https://example.com/artifact-1.html",
            template_name="crew_report",
            theme="light",
            data_variables=[],
            enhanced=False,
        )
        agent._toolkit.render = AsyncMock(return_value=fake_result)

        class _FakeMessage:
            response = "Executive Summary: all good."
            output = "Executive Summary: all good."

        with patch.object(agent, "ask", AsyncMock(return_value=_FakeMessage())):
            det_blocks = [
                {"type": "title", "title": "Report"},
                {
                    "type": "tab_view",
                    "tabs": [
                        {"id": "final-result", "label": "Final Result", "blocks": []},
                    ],
                },
            ]
            result = await agent.generate_infographic(
                summary="All agents completed successfully.",
                deterministic_blocks=det_blocks,
                crew_name="test-crew",
            )

        assert result is fake_result
        agent._toolkit.render.assert_called_once()
        _, call_kwargs = agent._toolkit.render.call_args
        assert call_kwargs["template_name"] == "crew_report"
        # Tab 1 should have been merged as the first tab.
        merged_blocks = call_kwargs["blocks"]
        tab_view = next(b for b in merged_blocks if b["type"] == "tab_view")
        assert tab_view["tabs"][0]["label"] == "Executive Summary"

    @pytest.mark.asyncio
    async def test_generate_infographic_falls_back_on_llm_failure(self):
        """LLM failure during Tab 1 authoring falls back to the raw summary text."""
        from parrot.bots.flows.result_agent import ResultAgent
        from parrot.tools.infographic_toolkit import InfographicRenderResult

        agent = ResultAgent(name="test-result-agent")
        fake_result = InfographicRenderResult(
            artifact_id="artifact-2",
            html_url="https://example.com/artifact-2.html",
            template_name="crew_report",
            theme="light",
            data_variables=[],
            enhanced=False,
        )
        agent._toolkit.render = AsyncMock(return_value=fake_result)

        with patch.object(agent, "ask", AsyncMock(side_effect=RuntimeError("LLM down"))):
            det_blocks = [
                {"type": "title", "title": "Report"},
                {
                    "type": "tab_view",
                    "tabs": [
                        {"id": "final-result", "label": "Final Result", "blocks": []},
                    ],
                },
            ]
            result = await agent.generate_infographic(
                summary="Fallback summary text.",
                deterministic_blocks=det_blocks,
            )

        assert result is fake_result
        _, call_kwargs = agent._toolkit.render.call_args
        merged_blocks = call_kwargs["blocks"]
        tab_view = next(b for b in merged_blocks if b["type"] == "tab_view")
        tab1_content = tab_view["tabs"][0]["blocks"][0]["content"]
        assert "Fallback summary text." in tab1_content
