"""Unit tests for intent router models (TASK-489).

Tests all enums and Pydantic models defined in
parrot.registry.capabilities.models.
"""
import pytest

from parrot.registry.capabilities.models import (
    CapabilityEntry,
    IntentRouterConfig,
    ResourceType,
    RoutingDecision,
    RoutingTrace,
    RoutingType,
    TraceEntry,
)


class TestResourceType:
    """Tests for ResourceType enum."""

    def test_has_five_members(self):
        """ResourceType must have exactly 5 members."""
        assert len(ResourceType) == 5

    def test_values(self):
        """ResourceType values must match spec."""
        expected = {"dataset", "tool", "graph_node", "pageindex", "vector_collection"}
        assert {e.value for e in ResourceType} == expected


class TestRoutingType:
    """Tests for RoutingType enum."""

    def test_has_eight_members(self):
        """RoutingType must have exactly 8 members."""
        assert len(RoutingType) == 8

    def test_values(self):
        """RoutingType values must match spec."""
        expected = {
            "graph_pageindex",
            "dataset",
            "vector_search",
            "tool_call",
            "free_llm",
            "multi_hop",
            "fallback",
            "hitl",
        }
        assert {e.value for e in RoutingType} == expected


class TestCapabilityEntry:
    """Tests for CapabilityEntry model."""

    def test_minimal(self):
        """CapabilityEntry instantiates with minimal required fields."""
        entry = CapabilityEntry(
            name="sales_data",
            description="Monthly sales dataset",
            resource_type=ResourceType.DATASET,
        )
        assert entry.embedding is None
        assert entry.not_for == []
        assert entry.metadata == {}

    def test_with_embedding(self):
        """CapabilityEntry stores embedding list correctly."""
        entry = CapabilityEntry(
            name="weather_tool",
            description="Get weather",
            resource_type=ResourceType.TOOL,
            embedding=[0.1, 0.2, 0.3],
        )
        assert len(entry.embedding) == 3

    def test_with_not_for(self):
        """CapabilityEntry stores not_for exclusion list."""
        entry = CapabilityEntry(
            name="hr_data",
            description="HR records",
            resource_type=ResourceType.DATASET,
            not_for=["warehouse", "inventory"],
        )
        assert len(entry.not_for) == 2
        assert "warehouse" in entry.not_for

    def test_with_metadata(self):
        """CapabilityEntry accepts arbitrary metadata dict."""
        entry = CapabilityEntry(
            name="product_graph",
            description="Product graph",
            resource_type=ResourceType.GRAPH_NODE,
            metadata={"owner": "data-team", "priority": 1},
        )
        assert entry.metadata["owner"] == "data-team"


class TestRoutingDecision:
    """Tests for RoutingDecision model."""

    def test_defaults(self):
        """RoutingDecision defaults are correct."""
        decision = RoutingDecision(routing_type=RoutingType.DATASET)
        assert decision.candidates == []
        assert decision.cascades == []
        assert decision.confidence == 0.0
        assert decision.reasoning == ""

    def test_with_cascades(self):
        """RoutingDecision accepts cascades list."""
        decision = RoutingDecision(
            routing_type=RoutingType.GRAPH_PAGEINDEX,
            cascades=[RoutingType.VECTOR_SEARCH, RoutingType.FALLBACK],
            confidence=0.85,
        )
        assert len(decision.cascades) == 2

    def test_serialization_roundtrip(self):
        """RoutingDecision serializes and deserializes correctly."""
        decision = RoutingDecision(
            routing_type=RoutingType.TOOL_CALL,
            confidence=0.9,
            reasoning="User asked to call a tool",
        )
        data = decision.model_dump()
        restored = RoutingDecision.model_validate(data)
        assert restored.routing_type == decision.routing_type
        assert restored.confidence == decision.confidence
        assert restored.reasoning == decision.reasoning

    def test_with_cascades_serialization(self):
        """RoutingDecision with cascades serializes correctly."""
        decision = RoutingDecision(
            routing_type=RoutingType.DATASET,
            cascades=[RoutingType.VECTOR_SEARCH, RoutingType.FREE_LLM],
            confidence=0.75,
        )
        data = decision.model_dump()
        restored = RoutingDecision.model_validate(data)
        assert len(restored.cascades) == 2


class TestRoutingTrace:
    """Tests for RoutingTrace model."""

    def test_mode_literal_normal(self):
        """RoutingTrace accepts 'normal' mode."""
        trace = RoutingTrace(mode="normal")
        assert trace.mode == "normal"

    def test_mode_literal_exhaustive(self):
        """RoutingTrace accepts 'exhaustive' mode."""
        trace = RoutingTrace(mode="exhaustive")
        assert trace.mode == "exhaustive"

    def test_invalid_mode_rejected(self):
        """RoutingTrace rejects invalid mode values."""
        with pytest.raises(Exception):
            RoutingTrace(mode="invalid")

    def test_defaults(self):
        """RoutingTrace defaults are correct."""
        trace = RoutingTrace()
        assert trace.mode == "normal"
        assert trace.entries == []
        assert trace.elapsed_ms == 0.0


class TestTraceEntry:
    """Tests for TraceEntry model."""

    def test_produced_context_default_false(self):
        """TraceEntry.produced_context defaults to False."""
        entry = TraceEntry(routing_type=RoutingType.VECTOR_SEARCH)
        assert entry.produced_context is False

    def test_with_error(self):
        """TraceEntry stores error message."""
        entry = TraceEntry(
            routing_type=RoutingType.DATASET,
            error="Connection refused",
            elapsed_ms=150.0,
        )
        assert entry.error == "Connection refused"
        assert entry.elapsed_ms == 150.0

    def test_produced_context_true(self):
        """TraceEntry.produced_context flag works."""
        entry = TraceEntry(
            routing_type=RoutingType.GRAPH_PAGEINDEX,
            produced_context=True,
            context_snippet="Found 5 results",
        )
        assert entry.produced_context is True
        assert entry.context_snippet == "Found 5 results"


class TestIntentRouterConfig:
    """Tests for IntentRouterConfig model."""

    def test_defaults(self):
        """IntentRouterConfig has correct defaults."""
        config = IntentRouterConfig()
        assert config.confidence_threshold == 0.7
        assert config.hitl_threshold == 0.3
        assert config.strategy_timeout_s == 30.0
        assert config.exhaustive_mode is False
        assert config.max_cascades == 3

    def test_invalid_confidence_threshold_rejected(self):
        """Confidence threshold above 1.0 is rejected."""
        with pytest.raises(Exception):
            IntentRouterConfig(confidence_threshold=1.5)

    def test_invalid_negative_confidence_rejected(self):
        """Negative confidence threshold is rejected."""
        with pytest.raises(Exception):
            IntentRouterConfig(confidence_threshold=-0.1)

    def test_invalid_timeout_rejected(self):
        """Zero or negative strategy_timeout_s is rejected."""
        with pytest.raises(Exception):
            IntentRouterConfig(strategy_timeout_s=-1)

    def test_invalid_max_cascades_rejected(self):
        """max_cascades above 10 is rejected."""
        with pytest.raises(Exception):
            IntentRouterConfig(max_cascades=11)

    def test_custom_config(self):
        """IntentRouterConfig accepts valid custom values."""
        config = IntentRouterConfig(
            confidence_threshold=0.8,
            hitl_threshold=0.2,
            strategy_timeout_s=10.0,
            exhaustive_mode=True,
            max_cascades=5,
        )
        assert config.confidence_threshold == 0.8
        assert config.hitl_threshold == 0.2
        assert config.exhaustive_mode is True
        assert config.max_cascades == 5
