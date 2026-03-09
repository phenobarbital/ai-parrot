"""Tests for WebSearchAgent contrastive_search and synthesize features."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from parrot.bots.search import (
    WebSearchAgent,
    DEFAULT_CONTRASTIVE_PROMPT,
    DEFAULT_SYNTHESIZE_PROMPT,
)
from parrot.models.responses import AIMessage
from parrot.models.basic import CompletionUsage


def _make_response(text: str) -> AIMessage:
    """Create a minimal AIMessage for testing."""
    return AIMessage(
        input="test",
        output=text,
        response=text,
        model="test-model",
        provider="test",
        usage=CompletionUsage(),
        metadata={},
    )


def _create_agent(**overrides):
    """Instantiate WebSearchAgent with mocked parent init."""
    with patch(
        "parrot.bots.search.BasicAgent.__init__",
        return_value=None,
    ):
        defaults = {
            "name": "TestSearch",
            "agent_id": "test_search",
            "use_llm": "google",
            "llm": "google:gemini-3-flash",
            "tools": [],
            "use_builtin_search": False,
            "contrastive_search": False,
            "synthesize": False,
        }
        defaults.update(overrides)
        agent = WebSearchAgent(**defaults)
    # Provide minimal attributes expected by the code
    agent.logger = MagicMock()
    return agent


class TestNormalAsk:
    """Verify default behavior when both flags are False."""

    @pytest.mark.asyncio
    async def test_normal_ask(self):
        agent = _create_agent()
        expected = _make_response("search result")
        agent._do_search = AsyncMock(return_value=expected)

        result = await agent.ask("what is Python?")

        assert result is expected
        agent._do_search.assert_awaited_once_with("what is Python?")

    @pytest.mark.asyncio
    async def test_normal_ask_passes_kwargs(self):
        agent = _create_agent()
        expected = _make_response("search result")
        agent._do_search = AsyncMock(return_value=expected)

        await agent.ask("query", session_id="s1", user_id="u1")

        agent._do_search.assert_awaited_once_with(
            "query", session_id="s1", user_id="u1"
        )


class TestContrastiveSearch:
    """Verify two-step search when contrastive_search=True."""

    @pytest.mark.asyncio
    async def test_calls_search_then_contrastive(self):
        agent = _create_agent(contrastive_search=True)
        initial = _make_response("initial results")
        contrastive = _make_response("contrastive analysis")
        agent._do_search = AsyncMock(return_value=initial)
        agent._do_contrastive = AsyncMock(return_value=contrastive)

        result = await agent.ask("iPhone 16")

        agent._do_search.assert_awaited_once()
        agent._do_contrastive.assert_awaited_once_with(
            "iPhone 16", "initial results"
        )
        assert result is contrastive
        assert result.metadata["initial_search_results"] == "initial results"

    @pytest.mark.asyncio
    async def test_contrastive_prompt_substitution(self):
        """_do_contrastive should substitute $query and $search_results."""
        agent = _create_agent(contrastive_search=True)
        # Call _do_contrastive directly to verify prompt construction
        with patch(
            "parrot.bots.search.BasicAgent.ask",
            create=True,
            new_callable=AsyncMock,
        ) as mock_super_ask:
            mock_super_ask.return_value = _make_response("analysis")
            await agent._do_contrastive(
                "iPhone 16", "competitor A, competitor B"
            )
            prompt_sent = mock_super_ask.call_args[0][0]
            assert "iPhone 16" in prompt_sent
            assert "competitor A, competitor B" in prompt_sent

    @pytest.mark.asyncio
    async def test_custom_contrastive_prompt(self):
        custom_prompt = "Compare $query vs: $search_results"
        agent = _create_agent(
            contrastive_search=True,
            contrastive_prompt=custom_prompt,
        )
        with patch(
            "parrot.bots.search.BasicAgent.ask",
            create=True,
            new_callable=AsyncMock,
        ) as mock_super_ask:
            mock_super_ask.return_value = _make_response("custom result")
            await agent._do_contrastive("Galaxy S25", "data")
            prompt_sent = mock_super_ask.call_args[0][0]
            assert prompt_sent == "Compare Galaxy S25 vs: data"


class TestSynthesize:
    """Verify synthesis step when synthesize=True."""

    @pytest.mark.asyncio
    async def test_synthesis_adds_call(self):
        agent = _create_agent(synthesize=True)
        search_result = _make_response("raw search data")
        synthesized = _make_response("synthesized output")
        agent._do_search = AsyncMock(return_value=search_result)
        agent._do_synthesize = AsyncMock(return_value=synthesized)

        result = await agent.ask("best laptops 2026")

        agent._do_search.assert_awaited_once()
        agent._do_synthesize.assert_awaited_once_with(
            "best laptops 2026", "raw search data"
        )
        assert result is synthesized
        assert result.metadata["pre_synthesis_results"] == "raw search data"

    @pytest.mark.asyncio
    async def test_synthesis_uses_no_tools(self):
        """_do_synthesize should call super().ask with use_tools=False."""
        agent = _create_agent(synthesize=True)
        with patch(
            "parrot.bots.search.BasicAgent.ask",
            create=True,
            new_callable=AsyncMock,
        ) as mock_super_ask:
            mock_super_ask.return_value = _make_response("synthesis")
            await agent._do_synthesize("query", "data")
            call_kwargs = mock_super_ask.call_args[1]
            assert call_kwargs["use_tools"] is False

    @pytest.mark.asyncio
    async def test_custom_synthesize_prompt(self):
        custom_prompt = "Summarize for $query: $search_results"
        agent = _create_agent(
            synthesize=True,
            synthesize_prompt=custom_prompt,
        )
        with patch(
            "parrot.bots.search.BasicAgent.ask",
            create=True,
            new_callable=AsyncMock,
        ) as mock_super_ask:
            mock_super_ask.return_value = _make_response("summary")
            await agent._do_synthesize("AI trends", "data points")
            prompt_sent = mock_super_ask.call_args[0][0]
            assert prompt_sent == "Summarize for AI trends: data points"


class TestContrastiveAndSynthesize:
    """Verify combined contrastive_search + synthesize."""

    @pytest.mark.asyncio
    async def test_all_three_steps(self):
        agent = _create_agent(contrastive_search=True, synthesize=True)
        initial = _make_response("initial")
        contrastive = _make_response("contrastive")
        synthesized = _make_response("final synthesis")
        agent._do_search = AsyncMock(return_value=initial)
        agent._do_contrastive = AsyncMock(return_value=contrastive)
        agent._do_synthesize = AsyncMock(return_value=synthesized)

        result = await agent.ask("Tesla Model 3")

        agent._do_search.assert_awaited_once()
        agent._do_contrastive.assert_awaited_once()
        agent._do_synthesize.assert_awaited_once_with(
            "Tesla Model 3", "contrastive"
        )
        assert result is synthesized
        assert result.metadata["pre_synthesis_results"] == "contrastive"


class TestBuiltinSearchFallback:
    """Verify builtin search flag interacts correctly with new features."""

    @pytest.mark.asyncio
    async def test_builtin_passes_tool_type(self):
        agent = _create_agent(use_builtin_search=True)
        with patch(
            "parrot.bots.search.BasicAgent.ask",
            create=True,
            new_callable=AsyncMock,
        ) as mock_super_ask:
            mock_super_ask.return_value = _make_response("builtin result")
            await agent._do_search("Pixel 9")
            call_kwargs = mock_super_ask.call_args[1]
            assert call_kwargs.get("tool_type") == "builtin_tools"

    @pytest.mark.asyncio
    async def test_fallback_on_tool_failure(self):
        """When tools fail, _do_search should fallback to builtin_tools."""
        agent = _create_agent(use_builtin_search=False)
        fallback = _make_response("fallback result")
        with patch(
            "parrot.bots.search.BasicAgent.ask",
            create=True,
            new_callable=AsyncMock,
        ) as mock_super_ask:
            mock_super_ask.side_effect = [
                RuntimeError("tool failed"),
                fallback,
            ]
            result = await agent._do_search("test query")
            assert result is fallback
            assert mock_super_ask.await_count == 2
            second_kwargs = mock_super_ask.call_args_list[1][1]
            assert second_kwargs.get("tool_type") == "builtin_tools"


class TestDefaultPrompts:
    """Verify default prompt constants."""

    def test_default_contrastive_prompt_has_placeholders(self):
        assert "$query" in DEFAULT_CONTRASTIVE_PROMPT
        assert "$search_results" in DEFAULT_CONTRASTIVE_PROMPT

    def test_default_synthesize_prompt_has_placeholders(self):
        assert "$query" in DEFAULT_SYNTHESIZE_PROMPT
        assert "$search_results" in DEFAULT_SYNTHESIZE_PROMPT

    def test_agent_uses_defaults_when_no_custom_prompt(self):
        agent = _create_agent()
        assert agent.contrastive_prompt == DEFAULT_CONTRASTIVE_PROMPT
        assert agent.synthesize_prompt == DEFAULT_SYNTHESIZE_PROMPT
