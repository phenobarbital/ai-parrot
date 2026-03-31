"""Unit tests for IntentRouterMixin (TASK-491).

Tests routing pass-through, configure_router, strategy discovery,
cascade execution, exhaustive mode, HITL, timeouts, and MRO.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from parrot.registry.capabilities.models import (
    CapabilityEntry,
    IntentRouterConfig,
    ResourceType,
    RoutingDecision,
    RoutingTrace,
    RoutingType,
    RouterCandidate,
    TraceEntry,
)
from parrot.bots.mixins.intent_router import IntentRouterMixin


# ── Test Infrastructure ───────────────────────────────────────────────────────


class MockBot:
    """Minimal base bot to serve as the super() target for MRO tests."""

    def __init__(self, **kwargs):
        self.logger = MagicMock()

    async def conversation(self, prompt: str, **kwargs) -> str:
        return f"base response: {prompt}"

    async def ask(self, prompt: str, **kwargs) -> str:
        return f"ask response: {prompt}"

    async def invoke(self, prompt: str, **kwargs):
        return MagicMock(output=None)


class RouterBot(IntentRouterMixin, MockBot):
    """Concrete test class combining mixin with mock bot."""
    pass


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def bot() -> RouterBot:
    return RouterBot()


@pytest.fixture
def config() -> IntentRouterConfig:
    return IntentRouterConfig(
        confidence_threshold=0.7,
        hitl_threshold=0.3,
        strategy_timeout_s=5.0,
    )


@pytest.fixture
def mock_registry():
    registry = MagicMock()
    registry.search = AsyncMock(return_value=[])
    return registry


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestRouterInactive:
    """Tests when router is not configured."""

    @pytest.mark.asyncio
    async def test_passthrough_when_inactive(self, bot: RouterBot) -> None:
        """conversation() delegates to super() when router inactive."""
        result = await bot.conversation("hello")
        assert result == "base response: hello"
        assert bot._router_active is False

    @pytest.mark.asyncio
    async def test_kwargs_forwarded_when_inactive(self, bot: RouterBot) -> None:
        """kwargs are forwarded to super().conversation() when inactive."""
        result = await bot.conversation("test", extra_kwarg="value")
        assert "base response" in result


class TestConfigureRouter:
    """Tests for configure_router()."""

    def test_activates_router(
        self, bot: RouterBot, config: IntentRouterConfig, mock_registry
    ) -> None:
        """configure_router sets _router_active=True and stores config."""
        bot.configure_router(config, mock_registry)
        assert bot._router_active is True
        assert bot._router_config is config
        assert bot._capability_registry is mock_registry

    def test_logger_called(
        self, bot: RouterBot, config: IntentRouterConfig, mock_registry
    ) -> None:
        """configure_router logs a message."""
        bot.configure_router(config, mock_registry)
        # logger.info should have been called
        bot.logger.info.assert_called()


class TestDiscoverStrategies:
    """Tests for _discover_strategies()."""

    def test_detects_vector_store(
        self, bot: RouterBot, config: IntentRouterConfig, mock_registry
    ) -> None:
        """VECTOR_SEARCH is discovered when vector_store attribute exists."""
        bot.configure_router(config, mock_registry)
        bot.vector_store = MagicMock()
        strategies = bot._discover_strategies("test query")
        assert RoutingType.VECTOR_SEARCH in strategies

    def test_detects_dataset_manager(
        self, bot: RouterBot, config: IntentRouterConfig, mock_registry
    ) -> None:
        """DATASET is discovered when dataset_manager attribute exists."""
        bot.configure_router(config, mock_registry)
        bot.dataset_manager = MagicMock()
        strategies = bot._discover_strategies("test query")
        assert RoutingType.DATASET in strategies

    def test_detects_graph_store(
        self, bot: RouterBot, config: IntentRouterConfig, mock_registry
    ) -> None:
        """GRAPH_PAGEINDEX is discovered when graph_store attribute exists."""
        bot.configure_router(config, mock_registry)
        bot.graph_store = MagicMock()
        strategies = bot._discover_strategies("test query")
        assert RoutingType.GRAPH_PAGEINDEX in strategies

    def test_detects_tool_manager(
        self, bot: RouterBot, config: IntentRouterConfig, mock_registry
    ) -> None:
        """TOOL_CALL is discovered when tool_manager has tools."""
        bot.configure_router(config, mock_registry)
        bot.tool_manager = MagicMock()
        bot.tool_manager.tool_count.return_value = 2
        strategies = bot._discover_strategies("test query")
        assert RoutingType.TOOL_CALL in strategies

    def test_free_llm_always_available(
        self, bot: RouterBot, config: IntentRouterConfig, mock_registry
    ) -> None:
        """FREE_LLM is always in available strategies."""
        bot.configure_router(config, mock_registry)
        strategies = bot._discover_strategies("test query")
        assert RoutingType.FREE_LLM in strategies

    def test_fallback_always_available(
        self, bot: RouterBot, config: IntentRouterConfig, mock_registry
    ) -> None:
        """FALLBACK is always in available strategies."""
        bot.configure_router(config, mock_registry)
        strategies = bot._discover_strategies("test query")
        assert RoutingType.FALLBACK in strategies


class TestFastPath:
    """Tests for _fast_path()."""

    def test_keyword_match_vector_search(
        self, bot: RouterBot, config: IntentRouterConfig, mock_registry
    ) -> None:
        """'search for' keyword triggers VECTOR_SEARCH fast path."""
        bot.configure_router(config, mock_registry)
        strategies = [RoutingType.VECTOR_SEARCH, RoutingType.FREE_LLM]
        decision = bot._fast_path("search for documents about sales", strategies, [])
        assert decision is not None
        assert decision.routing_type == RoutingType.VECTOR_SEARCH
        assert decision.confidence > 0.8

    def test_keyword_match_dataset(
        self, bot: RouterBot, config: IntentRouterConfig, mock_registry
    ) -> None:
        """'show data' keyword triggers DATASET fast path."""
        bot.configure_router(config, mock_registry)
        strategies = [RoutingType.DATASET, RoutingType.FREE_LLM]
        decision = bot._fast_path("show data for Q1", strategies, [])
        assert decision is not None
        assert decision.routing_type == RoutingType.DATASET

    def test_no_keyword_returns_none(
        self, bot: RouterBot, config: IntentRouterConfig, mock_registry
    ) -> None:
        """No keyword → fast path returns None."""
        bot.configure_router(config, mock_registry)
        strategies = [RoutingType.VECTOR_SEARCH, RoutingType.FREE_LLM]
        decision = bot._fast_path("what is the meaning of life", strategies, [])
        assert decision is None

    def test_keyword_strategy_not_available(
        self, bot: RouterBot, config: IntentRouterConfig, mock_registry
    ) -> None:
        """Keyword match is ignored if strategy not in available list."""
        bot.configure_router(config, mock_registry)
        # DATASET is not in available strategies
        strategies = [RoutingType.FREE_LLM]
        decision = bot._fast_path("show data", strategies, [])
        assert decision is None


class TestExecuteWithCascade:
    """Tests for _execute_with_cascade()."""

    @pytest.mark.asyncio
    async def test_primary_succeeds(
        self, bot: RouterBot, config: IntentRouterConfig, mock_registry
    ) -> None:
        """Cascade stops at primary when primary produces context."""
        bot.configure_router(config, mock_registry)
        decision = RoutingDecision(
            routing_type=RoutingType.VECTOR_SEARCH,
            confidence=0.9,
        )
        bot._execute_strategy = AsyncMock(return_value="found context")
        context, trace = await bot._execute_with_cascade(decision, "test query")
        assert context == "found context"
        assert len(trace.entries) >= 1
        assert trace.entries[0].produced_context is True

    @pytest.mark.asyncio
    async def test_cascade_on_primary_failure(
        self, bot: RouterBot, config: IntentRouterConfig, mock_registry
    ) -> None:
        """Primary fails → cascade to next strategy."""
        bot.configure_router(config, mock_registry)
        decision = RoutingDecision(
            routing_type=RoutingType.VECTOR_SEARCH,
            cascades=[RoutingType.DATASET, RoutingType.FREE_LLM],
            confidence=0.8,
        )
        bot._execute_strategy = AsyncMock(side_effect=[None, "cascade context"])
        context, trace = await bot._execute_with_cascade(decision, "test query")
        assert context == "cascade context"
        assert bot._execute_strategy.call_count == 2

    @pytest.mark.asyncio
    async def test_all_strategies_fail(
        self, bot: RouterBot, config: IntentRouterConfig, mock_registry
    ) -> None:
        """All strategies fail → returns None context."""
        bot.configure_router(config, mock_registry)
        decision = RoutingDecision(
            routing_type=RoutingType.GRAPH_PAGEINDEX,
            cascades=[RoutingType.DATASET],
            confidence=0.8,
        )
        bot._execute_strategy = AsyncMock(return_value=None)
        context, trace = await bot._execute_with_cascade(decision, "test")
        assert context is None
        assert len(trace.entries) == 2  # primary + 1 cascade


class TestExecuteExhaustive:
    """Tests for _execute_exhaustive()."""

    @pytest.mark.asyncio
    async def test_concatenates_successful_results(
        self, bot: RouterBot, config: IntentRouterConfig, mock_registry
    ) -> None:
        """Exhaustive mode concatenates all non-empty strategy results."""
        bot.configure_router(config, mock_registry)
        bot._execute_strategy = AsyncMock(
            side_effect=["graph result", None, "vector result"]
        )
        strategies = [
            RoutingType.GRAPH_PAGEINDEX,
            RoutingType.DATASET,
            RoutingType.VECTOR_SEARCH,
        ]
        context, trace = await bot._execute_exhaustive(strategies, "test", [])
        assert "graph result" in context
        assert "vector result" in context
        assert len(trace.entries) == 3

    @pytest.mark.asyncio
    async def test_all_fail_returns_empty(
        self, bot: RouterBot, config: IntentRouterConfig, mock_registry
    ) -> None:
        """All strategies fail → empty context string."""
        bot.configure_router(config, mock_registry)
        bot._execute_strategy = AsyncMock(return_value=None)
        strategies = [RoutingType.DATASET, RoutingType.VECTOR_SEARCH]
        context, trace = await bot._execute_exhaustive(strategies, "test", [])
        assert not context or context.strip() == ""

    @pytest.mark.asyncio
    async def test_labels_are_included(
        self, bot: RouterBot, config: IntentRouterConfig, mock_registry
    ) -> None:
        """Strategy labels appear in concatenated exhaustive context."""
        bot.configure_router(config, mock_registry)
        bot._execute_strategy = AsyncMock(return_value="some data")
        strategies = [RoutingType.DATASET]
        context, _ = await bot._execute_exhaustive(strategies, "test", [])
        assert "Dataset context" in context


class TestHITL:
    """Tests for HITL (Human-In-The-Loop) threshold behavior."""

    @pytest.mark.asyncio
    async def test_hitl_on_low_confidence(
        self, bot: RouterBot, config: IntentRouterConfig, mock_registry
    ) -> None:
        """Low confidence → HITL clarifying question is returned."""
        bot.configure_router(config, mock_registry)
        bot._fast_path = MagicMock(
            return_value=RoutingDecision(
                routing_type=RoutingType.DATASET,
                confidence=0.1,  # Below hitl_threshold of 0.3
            )
        )
        bot._llm_route = AsyncMock(return_value=None)
        result = await bot.conversation("ambiguous query")
        assert isinstance(result, str)
        assert "context" in result.lower() or "?" in result

    @pytest.mark.asyncio
    async def test_hitl_returns_string(
        self, bot: RouterBot, config: IntentRouterConfig, mock_registry
    ) -> None:
        """HITL always returns a non-empty string."""
        bot.configure_router(config, mock_registry)
        question = bot._build_hitl_question("vague question", [])
        assert isinstance(question, str)
        assert len(question) > 0

    @pytest.mark.asyncio
    async def test_hitl_includes_candidates_in_question(
        self, bot: RouterBot, config: IntentRouterConfig, mock_registry
    ) -> None:
        """HITL question mentions candidate names when available."""
        bot.configure_router(config, mock_registry)
        entry = CapabilityEntry(
            name="sales_data",
            description="Sales dataset",
            resource_type=ResourceType.DATASET,
        )
        candidate = RouterCandidate(
            entry=entry, score=0.8, resource_type=ResourceType.DATASET
        )
        question = bot._build_hitl_question("data", [candidate])
        assert "sales_data" in question


class TestTimeout:
    """Tests for strategy timeout handling."""

    @pytest.mark.asyncio
    async def test_strategy_timeout_returns_none(
        self, bot: RouterBot, config: IntentRouterConfig, mock_registry
    ) -> None:
        """Timed-out strategy returns None (does not raise)."""
        import asyncio as _asyncio

        config.strategy_timeout_s = 0.01  # Very short
        bot.configure_router(config, mock_registry)

        async def slow_fn(*args, **kwargs):
            await _asyncio.sleep(10)
            return "too slow"

        bot._run_vector_search = slow_fn
        result = await bot._execute_strategy(RoutingType.VECTOR_SEARCH, "test", [])
        assert result is None


class TestFallbackPrompt:
    """Tests for fallback prompt construction."""

    @pytest.mark.asyncio
    async def test_fallback_prompt_includes_tried_strategies(
        self, bot: RouterBot, config: IntentRouterConfig, mock_registry
    ) -> None:
        """Fallback prompt lists strategies that produced no context."""
        bot.configure_router(config, mock_registry)
        trace = RoutingTrace(
            entries=[
                TraceEntry(
                    routing_type=RoutingType.DATASET,
                    produced_context=False,
                ),
                TraceEntry(
                    routing_type=RoutingType.VECTOR_SEARCH,
                    produced_context=False,
                ),
            ]
        )
        prompt = await bot._build_fallback_prompt("original question", trace)
        assert "dataset" in prompt.lower() or "vector_search" in prompt.lower()
        assert "original question" in prompt


class TestMROCorrectness:
    """Tests that IntentRouterMixin cooperates correctly with Python MRO."""

    def test_mro_mixin_before_mock_bot(self) -> None:
        """IntentRouterMixin appears before MockBot in MRO."""
        mro = RouterBot.__mro__
        mixin_idx = next(i for i, cls in enumerate(mro) if cls is IntentRouterMixin)
        bot_idx = next(i for i, cls in enumerate(mro) if cls is MockBot)
        assert mixin_idx < bot_idx

    @pytest.mark.asyncio
    async def test_super_conversation_reachable(
        self, bot: RouterBot, config: IntentRouterConfig, mock_registry
    ) -> None:
        """super().conversation() reaches MockBot when router is active."""
        bot.configure_router(config, mock_registry)
        bot._route = AsyncMock(return_value=(None, None, None))
        result = await bot.conversation("test prompt")
        assert "base response" in result
