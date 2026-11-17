"""Shared fixtures for Roost tests (FEAT-747)."""

import pytest

from parrot.core.events.lifecycle import TraceContext
from parrot.roost.messages import LocalEnvelope


@pytest.fixture
def envelope() -> LocalEnvelope:
    """An EnvelopeLike that needs no FEAT-746 satellite."""
    return LocalEnvelope(
        envelope_id="env-1",
        correlation_id="corr-1",
        trace=TraceContext(trace_id="t" * 32, span_id="s" * 16),
        budget_ms=5_000,
        token_budget=2_000,
        caller="agent-a",
    )
