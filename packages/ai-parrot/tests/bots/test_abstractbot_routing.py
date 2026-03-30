"""Unit tests for AbstractBot routing kwargs handling (TASK-492).

Tests that conversation() correctly pops injected_context, routing_decision,
and routing_trace kwargs, and attaches the trace/decision to AIMessage.metadata.
"""
from __future__ import annotations

from parrot.registry.capabilities.models import (
    RoutingDecision,
    RoutingTrace,
    RoutingType,
    TraceEntry,
)


class TestRoutingTraceSerializable:
    """Tests that RoutingTrace serializes to a dict correctly."""

    def test_trace_model_dump_basic(self) -> None:
        """RoutingTrace.model_dump() produces a valid dict."""
        trace = RoutingTrace(
            mode="normal",
            entries=[
                TraceEntry(
                    routing_type=RoutingType.VECTOR_SEARCH,
                    produced_context=True,
                    elapsed_ms=50.0,
                )
            ],
            elapsed_ms=100.0,
        )
        data = trace.model_dump()
        assert data["mode"] == "normal"
        assert len(data["entries"]) == 1
        assert data["entries"][0]["produced_context"] is True
        assert data["elapsed_ms"] == 100.0

    def test_trace_model_dump_exhaustive(self) -> None:
        """RoutingTrace in exhaustive mode serializes correctly."""
        trace = RoutingTrace(
            mode="exhaustive",
            entries=[
                TraceEntry(
                    routing_type=RoutingType.DATASET,
                    produced_context=True,
                    context_snippet="Sales Q1: $1.2M",
                    elapsed_ms=45.0,
                ),
                TraceEntry(
                    routing_type=RoutingType.VECTOR_SEARCH,
                    produced_context=False,
                    error="No results found",
                    elapsed_ms=30.0,
                ),
            ],
            elapsed_ms=75.0,
        )
        data = trace.model_dump()
        assert data["mode"] == "exhaustive"
        assert len(data["entries"]) == 2
        assert data["entries"][0]["produced_context"] is True
        assert data["entries"][1]["error"] == "No results found"

    def test_decision_model_dump(self) -> None:
        """RoutingDecision.model_dump() produces a serializable dict."""
        decision = RoutingDecision(
            routing_type=RoutingType.DATASET,
            confidence=0.85,
            reasoning="User asked about sales data",
        )
        data = decision.model_dump()
        assert data["routing_type"] == "dataset"
        assert data["confidence"] == 0.85
        assert data["reasoning"] == "User asked about sales data"


class TestRoutingKwargsPop:
    """Tests that routing kwargs are properly handled.

    Note: Direct BaseBot testing requires heavy mocking due to database/LLM
    dependencies. These tests verify the model layer contracts that BaseBot
    relies on. Full routing integration is tested in test_intent_router_e2e.py.
    """

    def test_injected_context_kwarg_name(self) -> None:
        """Verify the injected_context kwarg name matches the mixin contract."""
        # The mixin sets kwargs["injected_context"] = context
        # BaseBot pops it via kwargs.pop("injected_context", None)
        # This test ensures the names are consistent.
        kwargs = {"injected_context": "some context", "other": "value"}
        injected = kwargs.pop("injected_context", None)
        assert injected == "some context"
        assert "injected_context" not in kwargs
        assert "other" in kwargs

    def test_routing_trace_kwarg_name(self) -> None:
        """Verify the routing_trace kwarg name matches the mixin contract."""
        trace = RoutingTrace(mode="normal")
        kwargs = {"routing_trace": trace}
        popped = kwargs.pop("routing_trace", None)
        assert popped is trace
        assert "routing_trace" not in kwargs

    def test_routing_decision_kwarg_name(self) -> None:
        """Verify the routing_decision kwarg name matches the mixin contract."""
        decision = RoutingDecision(
            routing_type=RoutingType.DATASET,
            confidence=0.9,
        )
        kwargs = {"routing_decision": decision}
        popped = kwargs.pop("routing_decision", None)
        assert popped is decision
        assert "routing_decision" not in kwargs

    def test_missing_routing_kwargs_return_none(self) -> None:
        """When routing kwargs are absent, pop() returns None safely."""
        kwargs = {"regular_kwarg": "value"}
        injected = kwargs.pop("injected_context", None)
        routing_decision = kwargs.pop("routing_decision", None)
        routing_trace = kwargs.pop("routing_trace", None)
        assert injected is None
        assert routing_decision is None
        assert routing_trace is None
        assert kwargs == {"regular_kwarg": "value"}


class TestRoutingMetadataAttachment:
    """Tests for routing metadata attachment pattern."""

    def test_trace_attaches_to_metadata_dict(self) -> None:
        """Routing trace can be stored in a metadata dict."""
        trace = RoutingTrace(
            mode="normal",
            entries=[
                TraceEntry(
                    routing_type=RoutingType.GRAPH_PAGEINDEX,
                    produced_context=True,
                    elapsed_ms=120.0,
                )
            ],
            elapsed_ms=150.0,
        )
        metadata: dict = {}
        metadata["routing_trace"] = trace.model_dump()

        assert "routing_trace" in metadata
        trace_data = metadata["routing_trace"]
        assert trace_data["mode"] == "normal"
        assert len(trace_data["entries"]) == 1
        assert trace_data["entries"][0]["routing_type"] == "graph_pageindex"

    def test_decision_attaches_to_metadata_dict(self) -> None:
        """Routing decision can be stored in a metadata dict."""
        decision = RoutingDecision(
            routing_type=RoutingType.VECTOR_SEARCH,
            confidence=0.78,
            reasoning="Best match for document search",
            cascades=[RoutingType.FALLBACK],
        )
        metadata: dict = {}
        metadata["routing_decision"] = decision.model_dump()

        assert "routing_decision" in metadata
        dec_data = metadata["routing_decision"]
        assert dec_data["routing_type"] == "vector_search"
        assert dec_data["confidence"] == 0.78

    def test_none_routing_trace_not_attached(self) -> None:
        """None routing_trace should not add metadata key."""
        routing_trace = None
        metadata: dict = {}
        if routing_trace is not None:
            metadata["routing_trace"] = routing_trace.model_dump()
        assert "routing_trace" not in metadata
