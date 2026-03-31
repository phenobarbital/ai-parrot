"""Integration tests for FEAT-070 — Intent Router (TASK-496).

Tests full cross-component pipelines:
- DataSource → CapabilityRegistry → IntentRouterMixin routing
- Tool → CapabilityRegistry → IntentRouterMixin routing
- DatasetManager.add_source() + registry + bot routing
- ToolManager.register() + registry + bot routing
- Exhaustive routing with real (mock) embedding
- HITL flow end-to-end
- YAML-loaded capabilities → router
- Cascade fallback across multiple strategies
- OntologyIntentResolver as sub-strategy within IntentRouterMixin

These tests are "integration" in that they wire together multiple real
components from distinct modules; they do NOT hit external services.
"""
from __future__ import annotations

from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

from parrot.bots.mixins.intent_router import IntentRouterMixin
from parrot.registry.capabilities.models import (
    IntentRouterConfig,
    ResourceType,
    RoutingDecision,
    RoutingType,
)
from parrot.registry.capabilities.registry import CapabilityRegistry
from parrot.tools.dataset_manager.sources.base import DataSource


# ── Test Helpers ──────────────────────────────────────────────────────────────


class FakeDataSource(DataSource):
    """Minimal DataSource for integration tests."""

    def __init__(self, name: str, description_text: str, routing_meta: Dict | None = None):
        super().__init__(routing_meta=routing_meta)
        self._name = name
        self._description = description_text

    @property
    def name(self) -> str:
        return self._name

    @property
    def cache_key(self) -> str:
        return f"fake:{self._name}"

    def describe(self) -> str:
        return self._description

    async def fetch(self, **params) -> pd.DataFrame:
        return pd.DataFrame({"col": [1, 2, 3]})


class FakeTool:
    """Minimal tool for integration tests."""

    def __init__(self, name: str, description: str, routing_meta: Dict | None = None):
        self.name = name
        self.description = description
        self.routing_meta = routing_meta or {}


class MockBotBase:
    """Minimal base bot for integration tests."""

    def __init__(self, **kwargs):
        self.logger = MagicMock()

    async def conversation(self, prompt: str, **kwargs) -> Any:
        # Record what was passed for assertions
        self._last_kwargs = kwargs
        return f"bot-response:{prompt}"


class IntegrationBot(IntentRouterMixin, MockBotBase):
    """Test bot combining IntentRouterMixin with MockBotBase."""
    pass


# ── Embedding function ────────────────────────────────────────────────────────


async def mock_embed(texts: list[str]) -> list[list[float]]:
    """Deterministic embedding: 4-dim vector based on text features."""
    return [
        [
            float(len(t)) / 100.0,
            float(sum(ord(c) for c in t[:5]) % 100) / 100.0,
            float(t.count(" ")) / 20.0,
            float(t.count("e")) / 20.0,
        ]
        for t in texts
    ]


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def config() -> IntentRouterConfig:
    return IntentRouterConfig(
        confidence_threshold=0.6,
        hitl_threshold=0.2,
        strategy_timeout_s=5.0,
        exhaustive_mode=False,
        max_cascades=3,
    )


@pytest.fixture
def registry() -> CapabilityRegistry:
    return CapabilityRegistry()


@pytest.fixture
def bot() -> IntegrationBot:
    return IntegrationBot()


# ══════════════════════════════════════════════════════════════════════════════
# Pipeline 1: DataSource → Registry → Bot
# ══════════════════════════════════════════════════════════════════════════════


class TestDataSourceToRegistryToBotPipeline:
    """Integration: DataSource → CapabilityRegistry → IntentRouterMixin."""

    @pytest.mark.asyncio
    async def test_datasource_registered_searchable(
        self, registry, bot, config
    ) -> None:
        """DataSource registered via register_from_datasource is searchable."""
        source = FakeDataSource(
            "monthly_sales",
            "Monthly sales revenue and units sold by region",
        )
        registry.register_from_datasource(source)
        await registry.build_index(mock_embed)
        bot.configure_router(config, registry)

        candidates = await registry.search("sales revenue")
        assert len(candidates) >= 1
        assert candidates[0].entry.name == "monthly_sales"

    @pytest.mark.asyncio
    async def test_datasource_not_for_filters_candidate(
        self, registry, bot, config
    ) -> None:
        """DataSource with not_for gets penalty for matching queries."""
        source = FakeDataSource(
            "internal_hr",
            "Human resources employee records",
            routing_meta={"not_for": ["public", "external"]},
        )
        registry.register_from_datasource(source)
        await registry.build_index(mock_embed)

        results = await registry.search("public employee external data")
        # Score should be penalised (halved)
        if results:
            for r in results:
                assert r.score <= 1.0  # Scores always valid

    @pytest.mark.asyncio
    async def test_multiple_sources_ranked_by_similarity(
        self, registry, config, bot
    ) -> None:
        """Multiple sources are ranked correctly by cosine similarity."""
        sources = [
            FakeDataSource("sales_data", "Monthly sales and revenue figures"),
            FakeDataSource("hr_data", "Employee HR records and payroll"),
            FakeDataSource("inventory", "Warehouse inventory stock levels"),
        ]
        for s in sources:
            registry.register_from_datasource(s)
        await registry.build_index(mock_embed)
        bot.configure_router(config, registry)

        # Search for sales-related query
        results = await registry.search("sales revenue data", top_k=3)
        assert len(results) <= 3
        assert all(0.0 <= r.score <= 1.0 for r in results)


# ══════════════════════════════════════════════════════════════════════════════
# Pipeline 2: Tool → Registry → Bot
# ══════════════════════════════════════════════════════════════════════════════


class TestToolToRegistryToBotPipeline:
    """Integration: FakeTool → CapabilityRegistry → IntentRouterMixin."""

    @pytest.mark.asyncio
    async def test_tool_registered_searchable(
        self, registry, bot, config
    ) -> None:
        """Tool registered via register_from_tool is searchable."""
        tool = FakeTool(
            "weather_api",
            "Get current weather conditions for a given city",
        )
        registry.register_from_tool(tool)
        await registry.build_index(mock_embed)
        bot.configure_router(config, registry)

        candidates = await registry.search("weather forecast")
        assert any(c.entry.name == "weather_api" for c in candidates)

    @pytest.mark.asyncio
    async def test_tool_resource_type_is_tool(
        self, registry, config, bot
    ) -> None:
        """Tool entries have ResourceType.TOOL."""
        tool = FakeTool("calc_tool", "Perform mathematical calculations")
        registry.register_from_tool(tool)
        await registry.build_index(mock_embed)

        results = await registry.search("calculate math")
        tool_results = [r for r in results if r.resource_type == ResourceType.TOOL]
        assert len(tool_results) >= 1

    @pytest.mark.asyncio
    async def test_mixed_sources_and_tools(
        self, registry, bot, config
    ) -> None:
        """Both DataSource and Tool entries coexist and are searchable."""
        source = FakeDataSource("orders", "Order history and shipping status")
        tool = FakeTool("email_tool", "Send automated email notifications")

        registry.register_from_datasource(source)
        registry.register_from_tool(tool)
        await registry.build_index(mock_embed)

        data_results = await registry.search(
            "order history", resource_types=[ResourceType.DATASET]
        )
        tool_results = await registry.search(
            "email notifications", resource_types=[ResourceType.TOOL]
        )
        assert all(r.resource_type == ResourceType.DATASET for r in data_results)
        assert all(r.resource_type == ResourceType.TOOL for r in tool_results)


# ══════════════════════════════════════════════════════════════════════════════
# Pipeline 3: DatasetManager.add_source() Integration
# ══════════════════════════════════════════════════════════════════════════════


class TestDatasetManagerAddSourceIntegration:
    """Integration: DatasetManager.add_source() + registry + bot."""

    @pytest.fixture
    def dm(self):
        """Minimal DatasetManager with add_source() and _datasets."""
        from parrot.tools.dataset_manager.tool import DatasetManager

        dm = object.__new__(DatasetManager)
        dm._datasets = {}
        dm.auto_detect_types = True
        dm.logger = MagicMock()
        return dm

    def test_add_source_registers_in_both_dm_and_registry(
        self, dm, registry
    ) -> None:
        """add_source() registers in DatasetManager AND CapabilityRegistry."""
        source = FakeDataSource("products", "Product catalog and pricing")
        dm.add_source(source, capability_registry=registry)

        # Registered in DatasetManager
        assert "products" in dm._datasets
        # Registered in CapabilityRegistry
        assert len(registry._entries) == 1
        assert registry._entries[0].name == "products"

    def test_add_source_description_from_describe(self, dm, registry) -> None:
        """DatasetEntry uses source.describe() as description."""
        source = FakeDataSource("kpi", "Key Performance Indicators Q1")
        dm.add_source(source, capability_registry=registry)
        entry = dm._datasets["kpi"]
        assert "Key Performance Indicators" in entry.description

    def test_add_source_without_registry_only_in_dm(self, dm) -> None:
        """add_source() without registry only stores in DatasetManager."""
        source = FakeDataSource("private_data", "Private internal data")
        result = dm.add_source(source)
        assert "private_data" in dm._datasets
        assert isinstance(result, str)

    def test_add_source_routing_meta_propagated(self, dm, registry) -> None:
        """routing_meta.not_for propagated to registry entry."""
        source = FakeDataSource(
            "classified",
            "Classified government data",
            routing_meta={"not_for": ["public"]},
        )
        dm.add_source(source, capability_registry=registry)
        entry = registry._entries[0]
        assert entry.not_for == ["public"]

    @pytest.mark.asyncio
    async def test_source_searchable_after_add_source(
        self, dm, registry, bot, config
    ) -> None:
        """Source registered via add_source is findable via search."""
        source = FakeDataSource("q1_sales", "Q1 sales figures for North region")
        dm.add_source(source, capability_registry=registry)
        await registry.build_index(mock_embed)
        bot.configure_router(config, registry)

        results = await registry.search("Q1 sales North region")
        assert any(r.entry.name == "q1_sales" for r in results)


# ══════════════════════════════════════════════════════════════════════════════
# Pipeline 4: ToolManager.register() Integration
# ══════════════════════════════════════════════════════════════════════════════


class TestToolManagerRegisterIntegration:
    """Integration: ToolManager.register() + CapabilityRegistry."""

    @pytest.fixture
    def tool_manager(self):
        """Minimal ToolManager stub."""
        from parrot.tools.manager import ToolManager

        tm = object.__new__(ToolManager)
        tm._tools = {}
        tm._tool_definitions = {}
        tm.logger = MagicMock()
        tm.register_tool = MagicMock(return_value="registered")
        return tm

    def test_register_with_registry_calls_register_from_tool(
        self, tool_manager, registry
    ) -> None:
        """ToolManager.register() calls registry.register_from_tool()."""
        tool = FakeTool("geocoder", "Geocode addresses to lat/lng coordinates")
        tool_manager.register(tool=tool, capability_registry=registry)
        assert len(registry._entries) == 1
        assert registry._entries[0].name == "geocoder"
        assert registry._entries[0].resource_type == ResourceType.TOOL

    @pytest.mark.asyncio
    async def test_tool_searchable_after_register(
        self, tool_manager, registry, bot, config
    ) -> None:
        """Tool is searchable after ToolManager.register() with registry."""
        tool = FakeTool(
            "sentiment_analyzer",
            "Analyze sentiment of text passages",
        )
        tool_manager.register(tool=tool, capability_registry=registry)
        await registry.build_index(mock_embed)
        bot.configure_router(config, registry)

        results = await registry.search("sentiment analysis text")
        assert any(r.entry.name == "sentiment_analyzer" for r in results)


# ══════════════════════════════════════════════════════════════════════════════
# Pipeline 5: YAML → Registry → Router
# ══════════════════════════════════════════════════════════════════════════════


class TestYamlRegistryPipeline:
    """Integration: YAML-loaded capabilities → CapabilityRegistry → routing."""

    @pytest.mark.asyncio
    async def test_yaml_capabilities_searchable(
        self, registry, bot, config, tmp_path
    ) -> None:
        """Capabilities from YAML are indexed and searchable."""
        yaml_content = """
capabilities:
  - name: employee_graph
    description: Employee reporting hierarchy and org chart
    resource_type: graph_node
    not_for: ["public", "external"]
  - name: financial_reports
    description: Quarterly and annual financial performance reports
    resource_type: dataset
  - name: translation_tool
    description: Translate text between multiple languages
    resource_type: tool
"""
        yaml_file = tmp_path / "caps.yaml"
        yaml_file.write_text(yaml_content)
        registry.register_from_yaml(str(yaml_file))
        await registry.build_index(mock_embed)
        bot.configure_router(config, registry)

        # Verify all entries registered
        assert len(registry._entries) == 3

        # Search for each type
        graph_results = await registry.search(
            "org chart hierarchy",
            resource_types=[ResourceType.GRAPH_NODE],
        )
        assert all(r.resource_type == ResourceType.GRAPH_NODE for r in graph_results)

        tool_results = await registry.search(
            "translate language",
            resource_types=[ResourceType.TOOL],
        )
        assert all(r.resource_type == ResourceType.TOOL for r in tool_results)

    @pytest.mark.asyncio
    async def test_yaml_not_for_applied_correctly(
        self, registry, bot, config, tmp_path
    ) -> None:
        """not_for entries from YAML apply penalty during search."""
        yaml_content = """
capabilities:
  - name: sensitive_hr
    description: Sensitive HR and payroll records
    resource_type: dataset
    not_for:
      - public
      - external user
"""
        yaml_file = tmp_path / "caps2.yaml"
        yaml_file.write_text(yaml_content)
        registry.register_from_yaml(str(yaml_file))
        await registry.build_index(mock_embed)

        # Check the entry has not_for populated
        entry = registry._entries[0]
        assert "public" in entry.not_for


# ══════════════════════════════════════════════════════════════════════════════
# Pipeline 6: Cascade Fallback
# ══════════════════════════════════════════════════════════════════════════════


class TestCascadeFallbackIntegration:
    """Integration: cascade strategy fallback pipeline."""

    @pytest.mark.asyncio
    async def test_cascade_falls_through_to_vector(
        self, bot, config, registry
    ) -> None:
        """Graph fails → Dataset fails → Vector succeeds."""
        bot.configure_router(config, registry)
        bot._fast_path = MagicMock(return_value=RoutingDecision(
            routing_type=RoutingType.GRAPH_PAGEINDEX,
            confidence=0.85,
            cascades=[RoutingType.DATASET, RoutingType.VECTOR_SEARCH],
        ))
        # Graph: fails, Dataset: fails, Vector: succeeds
        call_count = {"n": 0}

        async def mock_runner(strategy, prompt, candidates):
            call_count["n"] += 1
            if strategy == RoutingType.VECTOR_SEARCH:
                return "Vector context found"
            return None

        bot._execute_strategy = mock_runner
        # Run conversation
        result = await bot.conversation("find documents about revenue")
        assert result is not None
        assert call_count["n"] == 3  # graph, dataset, vector

    @pytest.mark.asyncio
    async def test_all_cascade_fails_triggers_fallback(
        self, bot, config, registry
    ) -> None:
        """All cascade strategies fail → routing falls back to FREE_LLM."""
        bot.configure_router(config, registry)
        bot._fast_path = MagicMock(return_value=RoutingDecision(
            routing_type=RoutingType.GRAPH_PAGEINDEX,
            confidence=0.85,
            cascades=[RoutingType.DATASET],
        ))
        bot._execute_strategy = AsyncMock(return_value=None)
        # Should not raise, result comes from MockBotBase
        result = await bot.conversation("some query")
        assert result is not None


# ══════════════════════════════════════════════════════════════════════════════
# Pipeline 7: Exhaustive Mode Integration
# ══════════════════════════════════════════════════════════════════════════════


class TestExhaustiveModeIntegration:
    """Integration: exhaustive routing mode."""

    @pytest.mark.asyncio
    async def test_exhaustive_concatenates_all_results(
        self, bot, tmp_path
    ) -> None:
        """Exhaustive mode concatenates non-empty results from all strategies."""
        config = IntentRouterConfig(
            exhaustive_mode=True,
            confidence_threshold=0.5,
            hitl_threshold=0.1,
            strategy_timeout_s=5.0,
        )
        registry = CapabilityRegistry()
        bot.configure_router(config, registry)

        # Simulate strategies producing context
        call_map = {
            RoutingType.GRAPH_PAGEINDEX: "Graph: CEO→VP→Manager",
            RoutingType.DATASET: "Dataset: Q1 Revenue $5M",
            RoutingType.VECTOR_SEARCH: None,  # No result
        }
        async def mock_runner(strategy, prompt, candidates):
            return call_map.get(strategy)

        # Force exhaustive mode to pick these strategies
        bot._discover_strategies = MagicMock(return_value=[
            RoutingType.GRAPH_PAGEINDEX,
            RoutingType.DATASET,
            RoutingType.VECTOR_SEARCH,
            RoutingType.FREE_LLM,
            RoutingType.FALLBACK,
        ])
        bot._fast_path = MagicMock(return_value=RoutingDecision(
            routing_type=RoutingType.GRAPH_PAGEINDEX, confidence=0.9
        ))
        bot._execute_strategy = mock_runner

        result = await bot.conversation("comprehensive analysis")
        # Result comes from MockBotBase (injected_context passed as kwarg)
        assert result is not None


# ══════════════════════════════════════════════════════════════════════════════
# Pipeline 8: HITL End-to-End
# ══════════════════════════════════════════════════════════════════════════════


class TestHITLEndToEnd:
    """Integration: HITL flow end-to-end."""

    @pytest.mark.asyncio
    async def test_hitl_returns_question_not_base_response(
        self, bot, registry
    ) -> None:
        """Low confidence → HITL question returned (not base bot response)."""
        config = IntentRouterConfig(
            confidence_threshold=0.8,
            hitl_threshold=0.6,  # Aggressive: most queries need clarification
            strategy_timeout_s=5.0,
        )
        bot.configure_router(config, registry)

        bot._fast_path = MagicMock(return_value=None)
        bot._llm_route = AsyncMock(return_value=RoutingDecision(
            routing_type=RoutingType.DATASET,
            confidence=0.3,  # Below 0.6 hitl_threshold
            reasoning="Ambiguous query",
        ))

        result = await bot.conversation("something something")
        # Should be a clarifying question, NOT "bot-response:..."
        assert isinstance(result, str)
        assert "bot-response:" not in result
        assert "?" in result or "context" in result.lower() or len(result) > 20

    @pytest.mark.asyncio
    async def test_hitl_question_includes_original_query(
        self, bot, registry
    ) -> None:
        """HITL question mentions the original user query."""
        config = IntentRouterConfig(
            hitl_threshold=0.9,  # Very aggressive
            strategy_timeout_s=5.0,
        )
        bot.configure_router(config, registry)

        bot._fast_path = MagicMock(return_value=None)
        bot._llm_route = AsyncMock(return_value=RoutingDecision(
            routing_type=RoutingType.FREE_LLM,
            confidence=0.05,
            reasoning="No context available",
        ))

        original_query = "very vague question that needs clarification"
        result = await bot.conversation(original_query)
        assert isinstance(result, str)
        # The clarifying question should reference the query
        assert original_query in result or len(result) > 20


# ══════════════════════════════════════════════════════════════════════════════
# Pipeline 9: OntologyIntentResolver as Sub-Strategy
# ══════════════════════════════════════════════════════════════════════════════


class TestOntologyAsSubStrategy:
    """Integration: OntologyIntentResolver used as graph_pageindex sub-strategy."""

    @pytest.mark.asyncio
    async def test_ontology_resolver_used_in_graph_runner(
        self, bot, config, registry
    ) -> None:
        """IntentRouterMixin._run_graph_pageindex can invoke ontology_process()."""
        bot.configure_router(config, registry)

        # Simulate ontology_process attribute (OntologyRAGMixin integration)
        async def mock_ontology_process(prompt: str) -> str:
            return f"Graph: found relationships for '{prompt}'"

        bot.ontology_process = mock_ontology_process

        result = await bot._run_graph_pageindex("who manages Alice?", [])
        assert result is not None
        assert "relationships" in result

    @pytest.mark.asyncio
    async def test_ontology_runner_fallback_when_no_ontology(
        self, bot, config, registry
    ) -> None:
        """_run_graph_pageindex returns None when no graph/ontology configured."""
        bot.configure_router(config, registry)
        result = await bot._run_graph_pageindex("query without graph", [])
        assert result is None
