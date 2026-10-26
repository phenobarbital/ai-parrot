"""Tests for the FEAT-746 capability-call telemetry seam."""
import pytest
from navigator_eventbus.lifecycle.trace import TraceContext

from parrot.core.events.lifecycle.events import CapabilityCallEvent
from parrot.observability.recorders import AbstractLogger, CapabilityCallRecord


class _Rec(AbstractLogger):
    async def record(self, record):
        pass


def _rec() -> CapabilityCallRecord:
    return CapabilityCallRecord(
        side="served",
        agent="hr",
        peer_agent="ext",
        cap_id="hr.reports.x",
        category="hr.reports",
        backing="deterministic",
        status="OK",
        trace_id="t" * 32,
    )


@pytest.mark.asyncio
async def test_default_hook_is_noop():
    assert await _Rec().record_capability(_rec()) is None


def test_no_provider_fields():
    assert not {"provider", "model", "user_id", "session_id"} & set(CapabilityCallRecord.model_fields)
    assert CapabilityCallEvent(trace_context=TraceContext.new_root(), record=_rec()).record.cap_id == "hr.reports.x"
