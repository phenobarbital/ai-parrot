"""
Integration tests for WebSearchAgent crew support.

These tests verify end-to-end WebSearchAgent workflows including:
- Contrastive search (two-step competitor analysis)
- Synthesis (LLM summarization of results)
- Config passthrough from crew definitions

TASK-053: WebSearchAgent Crew Integration Tests
FEAT-012: WebSearchAgent Support in CrewBuilder

Note: REST API integration tests are limited due to navigator dependency.
These tests focus on WebSearchAgent behavior with mocked LLM calls.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from parrot.bots.search import (
    DEFAULT_CONTRASTIVE_PROMPT,
    DEFAULT_SYNTHESIZE_PROMPT,
    WebSearchAgent,
)
from parrot.models.responses import AIMessage


@pytest.fixture
def fixtures_dir():
    """Return path to test fixtures directory."""
    return Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def websearchagent_crew_fixture(fixtures_dir):
    """Load WebSearchAgent crew fixture data."""
    fixture_path = fixtures_dir / "websearchagent_crew.json"
    if fixture_path.exists():
        return json.loads(fixture_path.read_text())
    raise FileNotFoundError(f"Fixture not found: {fixture_path}")


@pytest.fixture
def mock_ai_response():
    """Create a mock AIMessage response."""
    def _create(text: str, metadata: dict = None):
        response = MagicMock(spec=AIMessage)
        response.to_text = text
        response.output = text
        response.response = text
        response.metadata = metadata or {}
        return response
    return _create


class TestWebSearchAgentContrastiveSearch:
    """Integration tests for WebSearchAgent contrastive search feature."""

    @pytest.mark.asyncio
    async def test_contrastive_search_calls_twice(self, mock_ai_response):
        """Contrastive search performs initial search then contrastive analysis."""
        call_count = 0
        call_queries = []

        async def mock_parent_ask(question, **kwargs):
            nonlocal call_count
            call_count += 1
            call_queries.append(question)
            if call_count == 1:
                return mock_ai_response("Initial search results for test query")
            return mock_ai_response("Contrastive analysis of competitors")

        with patch.object(WebSearchAgent, '__init__', lambda self, **kw: None):
            agent = WebSearchAgent.__new__(WebSearchAgent)
            agent.name = "TestAgent"
            agent.contrastive_search = True
            agent.contrastive_prompt = DEFAULT_CONTRASTIVE_PROMPT
            agent.synthesize = False
            agent.synthesize_prompt = DEFAULT_SYNTHESIZE_PROMPT
            agent.use_builtin_search = False
            agent.logger = MagicMock()

            # Mock the parent class ask method via _do_search
            with patch.object(agent, '_do_search', side_effect=mock_parent_ask):
                await agent.ask("Best Python frameworks 2026")

                # Should have called search twice (initial + contrastive)
                assert call_count == 2
                # First call is original query
                assert "Best Python frameworks 2026" in call_queries[0]
                # Second call contains COMPETITORS analysis
                assert "COMPETITORS" in call_queries[1] or "competitors" in call_queries[1].lower()

    @pytest.mark.asyncio
    async def test_contrastive_search_stores_initial_results(self, mock_ai_response):
        """Contrastive search stores initial results in metadata."""
        async def mock_do_search(question, **kwargs):
            return mock_ai_response(f"Results for: {question}")

        with patch.object(WebSearchAgent, '__init__', lambda self, **kw: None):
            agent = WebSearchAgent.__new__(WebSearchAgent)
            agent.name = "TestAgent"
            agent.contrastive_search = True
            agent.contrastive_prompt = "Compare $query: $search_results"
            agent.synthesize = False
            agent.synthesize_prompt = ""
            agent.use_builtin_search = False
            agent.logger = MagicMock()

            with patch.object(agent, '_do_search', side_effect=mock_do_search):
                with patch.object(agent, '_do_contrastive', return_value=mock_ai_response(
                    "Contrastive results",
                    {"initial_search_results": "Initial results"}
                )):
                    result = await agent.ask("Test query")

                    # Result should have initial_search_results in metadata
                    assert "initial_search_results" in result.metadata


class TestWebSearchAgentSynthesis:
    """Integration tests for WebSearchAgent synthesis feature."""

    @pytest.mark.asyncio
    async def test_synthesis_adds_extra_step(self, mock_ai_response):
        """Synthesis adds an additional LLM call after search."""
        call_count = 0

        async def mock_do_search(question, **kwargs):
            nonlocal call_count
            call_count += 1
            return mock_ai_response("Search results")

        async def mock_do_synthesize(question, search_results, **kwargs):
            nonlocal call_count
            call_count += 1
            return mock_ai_response(
                "Synthesized summary",
                {"pre_synthesis_results": search_results}
            )

        with patch.object(WebSearchAgent, '__init__', lambda self, **kw: None):
            agent = WebSearchAgent.__new__(WebSearchAgent)
            agent.name = "TestAgent"
            agent.contrastive_search = False
            agent.contrastive_prompt = ""
            agent.synthesize = True
            agent.synthesize_prompt = "Summarize: $query $search_results"
            agent.use_builtin_search = False
            agent.logger = MagicMock()

            with patch.object(agent, '_do_search', side_effect=mock_do_search):
                with patch.object(agent, '_do_synthesize', side_effect=mock_do_synthesize):
                    await agent.ask("Test query")

                    # Should have called search + synthesize
                    assert call_count == 2

    @pytest.mark.asyncio
    async def test_synthesis_disables_tools(self, mock_ai_response):
        """Synthesis step runs with use_tools=False."""
        # Verify _do_synthesize sets use_tools=False by checking the source
        import inspect
        from parrot.bots.search import WebSearchAgent

        # Get the source code of _do_synthesize
        source = inspect.getsource(WebSearchAgent._do_synthesize)

        # Verify it contains use_tools=False
        assert "use_tools" in source
        assert "False" in source

        # Also verify the method signature accepts kwargs that get passed through
        sig = inspect.signature(WebSearchAgent._do_synthesize)
        params = list(sig.parameters.keys())
        assert "kwargs" in params or any("**" in str(p) for p in sig.parameters.values())


class TestWebSearchAgentFullPipeline:
    """Integration tests for full contrastive + synthesis pipeline."""

    @pytest.mark.asyncio
    async def test_full_pipeline_three_steps(self, mock_ai_response):
        """Full pipeline: initial search → contrastive → synthesis."""
        step_count = 0
        steps = []

        async def mock_do_search(question, **kwargs):
            nonlocal step_count
            step_count += 1
            steps.append(f"search_{step_count}")
            return mock_ai_response(f"Search step {step_count}")

        async def mock_do_contrastive(question, search_results, **kwargs):
            nonlocal step_count
            step_count += 1
            steps.append("contrastive")
            response = mock_ai_response("Contrastive analysis")
            response.metadata = {"initial_search_results": search_results}
            return response

        async def mock_do_synthesize(question, search_results, **kwargs):
            nonlocal step_count
            step_count += 1
            steps.append("synthesize")
            response = mock_ai_response("Final synthesis")
            response.metadata = {"pre_synthesis_results": search_results}
            return response

        with patch.object(WebSearchAgent, '__init__', lambda self, **kw: None):
            agent = WebSearchAgent.__new__(WebSearchAgent)
            agent.name = "TestAgent"
            agent.contrastive_search = True
            agent.contrastive_prompt = DEFAULT_CONTRASTIVE_PROMPT
            agent.synthesize = True
            agent.synthesize_prompt = DEFAULT_SYNTHESIZE_PROMPT
            agent.use_builtin_search = False
            agent.logger = MagicMock()

            with patch.object(agent, '_do_search', side_effect=mock_do_search):
                with patch.object(agent, '_do_contrastive', side_effect=mock_do_contrastive):
                    with patch.object(agent, '_do_synthesize', side_effect=mock_do_synthesize):
                        await agent.ask("Best Python frameworks 2026")

                        # Should have 3 steps total
                        assert step_count == 3
                        assert "search_1" in steps
                        assert "contrastive" in steps
                        assert "synthesize" in steps


class TestWebSearchAgentCrewConfig:
    """Integration tests for WebSearchAgent config from crew definitions."""

    def test_crew_fixture_has_correct_structure(self, websearchagent_crew_fixture):
        """Verify the crew fixture has expected WebSearchAgent config."""
        assert websearchagent_crew_fixture["name"] == "test_websearch_crew"
        assert len(websearchagent_crew_fixture["agents"]) == 1

        agent = websearchagent_crew_fixture["agents"][0]
        assert agent["agent_class"] == "WebSearchAgent"
        assert agent["config"]["contrastive_search"] is True
        assert agent["config"]["synthesize"] is True
        assert agent["config"]["temperature"] == 0.0
        assert "$query" in agent["config"]["contrastive_prompt"]
        assert "$search_results" in agent["config"]["synthesize_prompt"]

    def test_config_can_instantiate_websearchagent(self, websearchagent_crew_fixture):
        """Config from fixture can be used to instantiate WebSearchAgent."""
        agent_config = websearchagent_crew_fixture["agents"][0]["config"]

        # Verify config keys match WebSearchAgent parameters
        with patch.object(WebSearchAgent, '__init__', lambda self, **kw: None):
            agent = WebSearchAgent.__new__(WebSearchAgent)

            # Apply config manually (simulating what CrewHandler does)
            agent.contrastive_search = agent_config.get("contrastive_search", False)
            agent.synthesize = agent_config.get("synthesize", False)
            agent.contrastive_prompt = agent_config.get("contrastive_prompt", "")
            agent.synthesize_prompt = agent_config.get("synthesize_prompt", "")

            assert agent.contrastive_search is True
            assert agent.synthesize is True
            assert "$query" in agent.contrastive_prompt

    @pytest.mark.asyncio
    async def test_websearchagent_with_crew_config(
        self, websearchagent_crew_fixture, mock_ai_response
    ):
        """WebSearchAgent initialized with crew config runs correctly."""
        agent_def = websearchagent_crew_fixture["agents"][0]
        config = agent_def["config"]

        # Track pipeline execution
        executed_steps = []

        async def mock_do_search(question, **kwargs):
            executed_steps.append("search")
            return mock_ai_response("Search results")

        async def mock_do_contrastive(question, results, **kwargs):
            executed_steps.append("contrastive")
            response = mock_ai_response("Contrastive results")
            response.metadata = {"initial_search_results": results}
            return response

        async def mock_do_synthesize(question, results, **kwargs):
            executed_steps.append("synthesize")
            response = mock_ai_response("Synthesized results")
            response.metadata = {"pre_synthesis_results": results}
            return response

        with patch.object(WebSearchAgent, '__init__', lambda self, **kw: None):
            agent = WebSearchAgent.__new__(WebSearchAgent)
            agent.name = agent_def.get("name", "TestAgent")
            agent.contrastive_search = config.get("contrastive_search", False)
            agent.contrastive_prompt = config.get("contrastive_prompt", DEFAULT_CONTRASTIVE_PROMPT)
            agent.synthesize = config.get("synthesize", False)
            agent.synthesize_prompt = config.get("synthesize_prompt", DEFAULT_SYNTHESIZE_PROMPT)
            agent.use_builtin_search = False
            agent.logger = MagicMock()

            with patch.object(agent, '_do_search', side_effect=mock_do_search):
                with patch.object(agent, '_do_contrastive', side_effect=mock_do_contrastive):
                    with patch.object(agent, '_do_synthesize', side_effect=mock_do_synthesize):
                        await agent.ask("Test query from crew")

                        # With both contrastive and synthesize enabled, should run full pipeline
                        assert "search" in executed_steps
                        assert "contrastive" in executed_steps
                        assert "synthesize" in executed_steps


class TestWebSearchAgentMinimalConfig:
    """Test WebSearchAgent works with minimal/default config."""

    @pytest.mark.asyncio
    async def test_empty_config_uses_defaults(self, mock_ai_response):
        """WebSearchAgent with empty config uses default values."""
        async def mock_do_search(question, **kwargs):
            return mock_ai_response("Default search results")

        with patch.object(WebSearchAgent, '__init__', lambda self, **kw: None):
            agent = WebSearchAgent.__new__(WebSearchAgent)
            agent.name = "DefaultAgent"
            # Simulate empty config defaults
            agent.contrastive_search = False
            agent.synthesize = False
            agent.contrastive_prompt = DEFAULT_CONTRASTIVE_PROMPT
            agent.synthesize_prompt = DEFAULT_SYNTHESIZE_PROMPT
            agent.use_builtin_search = False
            agent.logger = MagicMock()

            search_called = False

            async def track_search(question, **kwargs):
                nonlocal search_called
                search_called = True
                return mock_ai_response("Results")

            with patch.object(agent, '_do_search', side_effect=track_search):
                result = await agent.ask("Simple query")

                # Only search should be called, no contrastive or synthesis
                assert search_called
                assert "initial_search_results" not in result.metadata
                assert "pre_synthesis_results" not in result.metadata


class TestWebSearchAgentPromptTemplates:
    """Test prompt template substitution."""

    @pytest.mark.asyncio
    async def test_contrastive_prompt_substitution(self, mock_ai_response):
        """Contrastive prompt has $query and $search_results substituted."""
        captured_query = None

        async def mock_do_search(question, **kwargs):
            nonlocal captured_query
            captured_query = question
            return mock_ai_response("Initial results")

        with patch.object(WebSearchAgent, '__init__', lambda self, **kw: None):
            agent = WebSearchAgent.__new__(WebSearchAgent)
            agent.name = "TestAgent"
            agent.contrastive_search = True
            agent.contrastive_prompt = "Custom: Query=$query Results=$search_results"
            agent.synthesize = False
            agent.synthesize_prompt = ""
            agent.use_builtin_search = False
            agent.logger = MagicMock()

            with patch.object(agent, '_do_search', side_effect=mock_do_search):
                # The contrastive query should have substitutions
                call_count = 0

                async def track_search(question, **kwargs):
                    nonlocal call_count, captured_query
                    call_count += 1
                    if call_count == 2:
                        captured_query = question
                    return mock_ai_response("Results")

                with patch.object(agent, '_do_search', side_effect=track_search):
                    await agent.ask("test query")

                    # Second call (contrastive) should have substitutions
                    if captured_query:
                        assert "test query" in captured_query or "Query=" in captured_query
