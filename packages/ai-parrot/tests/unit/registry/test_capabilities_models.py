"""Unit tests for TraceEntry store_rankings field (TASK-791)."""
import pytest
from parrot.registry.capabilities.models import TraceEntry, RoutingType
from parrot.registry.routing.models import StoreScore
from parrot.tools.multistoresearch import StoreType


def test_default_store_rankings_is_none():
    t = TraceEntry(routing_type=RoutingType.VECTOR_SEARCH)
    assert t.store_rankings is None


def test_trace_entry_without_store_rankings_still_validates():
    t = TraceEntry(
        routing_type=RoutingType.VECTOR_SEARCH,
        produced_context=True,
        elapsed_ms=12.5,
    )
    assert t.produced_context is True
    assert t.store_rankings is None


def test_store_rankings_populated():
    score = StoreScore(store=StoreType.PGVECTOR, confidence=0.9, reason="keyword")
    t = TraceEntry(
        routing_type=RoutingType.VECTOR_SEARCH,
        produced_context=True,
        store_rankings=[score],
    )
    assert t.store_rankings is not None
    assert len(t.store_rankings) == 1
    assert t.store_rankings[0].store == StoreType.PGVECTOR


def test_store_rankings_roundtrip():
    t = TraceEntry(
        routing_type=RoutingType.VECTOR_SEARCH,
        produced_context=True,
        store_rankings=[StoreScore(store=StoreType.PGVECTOR, confidence=0.9)],
    )
    restored = TraceEntry.model_validate(t.model_dump())
    # After roundtrip via model_dump(), store_rankings entries are plain dicts
    # unless we rebuild with StoreScore. Check it round-tripped at dict level.
    assert restored.store_rankings is not None
    assert len(restored.store_rankings) == 1


def test_no_import_cycle():
    """Smoke test — fails at import time if there's a cycle."""
    from parrot.registry.capabilities.models import TraceEntry  # noqa: F401
    from parrot.registry.routing.models import StoreScore  # noqa: F401


def test_existing_trace_entry_without_store_rankings_serializes_cleanly():
    """Existing code that never sets store_rankings is not broken."""
    t = TraceEntry(
        routing_type=RoutingType.FREE_LLM,
        produced_context=False,
        error="test error",
    )
    dumped = t.model_dump()
    # store_rankings should serialize as None (not absent) or absent.
    # Either behaviour is acceptable; we just check it doesn't raise.
    assert "routing_type" in dumped
    assert dumped.get("store_rankings") is None
