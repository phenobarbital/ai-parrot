"""Unit tests for LoggingUsageRecorder."""

from __future__ import annotations

import logging

import pytest

from parrot.observability.recorders.logging_recorder import LoggingUsageRecorder
from parrot.observability.recorders.models import UsageRecord


@pytest.mark.asyncio
async def test_logs_one_line_with_cost(caplog) -> None:
    """A recorded call emits one line carrying provider, model, tokens, cost."""
    recorder = LoggingUsageRecorder(level=logging.INFO, logger_name="parrot.usage")
    rec = UsageRecord(
        provider="openai", model="gpt-4o", input_tokens=100, output_tokens=50,
        cost_usd=0.001234, cumulative_cost_usd=0.001234, duration_ms=42.0,
        finish_reason="stop",
    )
    with caplog.at_level(logging.INFO, logger="parrot.usage"):
        await recorder.record(rec)

    records = [r for r in caplog.records if r.name == "parrot.usage"]
    assert len(records) == 1
    msg = records[0].getMessage()
    assert "provider=openai" in msg
    assert "model=gpt-4o" in msg
    assert "input_tokens=100" in msg
    assert "output_tokens=50" in msg
    assert "total_tokens=150" in msg
    assert "cost_usd=0.001234" in msg
    assert "cumulative_cost_usd=0.001234" in msg


@pytest.mark.asyncio
async def test_unknown_cost_renders_na(caplog) -> None:
    """cost_usd=None renders as 'n/a' (no crash)."""
    recorder = LoggingUsageRecorder(level=logging.INFO)
    rec = UsageRecord(provider="x", model="y", cost_usd=None, cumulative_cost_usd=None)
    with caplog.at_level(logging.INFO, logger="parrot.usage"):
        await recorder.record(rec)
    msg = caplog.records[-1].getMessage()
    assert "cost_usd=n/a" in msg
    assert "cumulative_cost_usd=n/a" in msg


@pytest.mark.asyncio
async def test_level_below_threshold_suppresses_line(caplog) -> None:
    """A DEBUG-level recorder emits nothing when only INFO is captured."""
    recorder = LoggingUsageRecorder(level=logging.DEBUG, logger_name="parrot.usage")
    rec = UsageRecord(provider="openai", model="gpt-4o")
    with caplog.at_level(logging.INFO, logger="parrot.usage"):
        await recorder.record(rec)
    assert [r for r in caplog.records if r.name == "parrot.usage"] == []
