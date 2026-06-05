"""Unit tests for UsageRecord (pluggable usage-logging layer)."""

from __future__ import annotations

from datetime import timezone

from parrot.observability.recorders.models import UsageRecord


def test_total_tokens_computed() -> None:
    """total_tokens is the sum of input and output tokens."""
    rec = UsageRecord(provider="openai", model="gpt-4o", input_tokens=100, output_tokens=50)
    assert rec.total_tokens == 150


def test_defaults_are_pii_free_and_safe() -> None:
    """Defaults: no cost, tz-aware timestamp, and no PII fields on the model."""
    rec = UsageRecord(provider="anthropic")
    assert rec.cost_usd is None
    assert rec.cumulative_cost_usd is None
    assert rec.input_tokens == 0 and rec.output_tokens == 0
    assert rec.timestamp.tzinfo is not None
    assert rec.timestamp.utcoffset() == timezone.utc.utcoffset(None)
    # PII contract: these fields must NOT exist on the record.
    forbidden = {"user_id", "session_id", "prompt", "completion", "question"}
    assert forbidden.isdisjoint(UsageRecord.model_fields.keys())


def test_total_tokens_serialized() -> None:
    """computed total_tokens is included in model_dump output."""
    rec = UsageRecord(provider="groq", model="x", input_tokens=3, output_tokens=4)
    assert rec.model_dump()["total_tokens"] == 7
