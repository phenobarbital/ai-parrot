"""Tests for served-side telemetry."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel

from parrot.core.events.lifecycle import EventRegistry, TraceContext
from parrot.core.events.lifecycle.events import CapabilityCallEvent
from parrot.interagent import CallCost, SquawkCapability
from parrot.interagent.contract import PolicyAnnotations, ReturnsSpec
from parrot.observability.recorders import AbstractLogger
from parrot.observability.recorders.models import CapabilityCallRecord
from parrot.squawk.telemetry import ServedTelemetry, record_from_call


class FakeRecorder(AbstractLogger):
    def __init__(self):
        self.records = []
        self.name = "fake"

    async def record(self, record):
        pass  # Not used in these tests

    async def record_capability(self, record: CapabilityCallRecord) -> None:
        self.records.append(record)


class FakeRegistry:
    def __init__(self):
        self.events = []

    async def emit(self, event):
        self.events.append(event)


@pytest.fixture
def llm_capability():
    return SquawkCapability(
        cap_id="test.category.action",
        category="test.category",
        description="Test capability",
        input_schema={},
        returns=ReturnsSpec(kind="inline", schema={}),
        backing="llm_backed",
        policy=PolicyAnnotations(),
    )


@pytest.fixture
def deterministic_capability():
    return SquawkCapability(
        cap_id="test.category.action",
        category="test.category",
        description="Test capability",
        input_schema={},
        returns=ReturnsSpec(kind="inline", schema={}),
        backing="deterministic",
        policy=PolicyAnnotations(),
    )


@pytest.fixture
def cost():
    return CallCost(
        tokens_in=100,
        tokens_out=200,
        duration_ms=500,
        rows=None,
        bytes=None,
        cost_usd=0.001,
    )


def test_record_from_call_llm_backed(llm_capability, cost):
    """Test record_from_call with llm_backed capability includes tokens."""
    record = record_from_call(
        side="served",
        agent="test-agent",
        peer="peer-agent",
        cap=llm_capability,
        status="OK",
        cost=cost,
        trace_id="test-trace-id",
        correlation_id="test-correlation-id",
        policy_applied=("policy1", "policy2"),
    )

    assert record.side == "served"
    assert record.agent == "test-agent"
    assert record.peer_agent == "peer-agent"
    assert record.cap_id == "test.category.action"
    assert record.category == "test.category"
    assert record.backing == "llm_backed"
    assert record.status == "OK"
    assert record.duration_ms == 500.0
    assert record.tokens_in == 100
    assert record.tokens_out == 200
    assert record.cost_usd == 0.001
    assert record.trace_id == "test-trace-id"
    assert record.correlation_id == "test-correlation-id"
    assert record.policy_applied == ("policy1", "policy2")


def test_record_from_call_deterministic(deterministic_capability, cost):
    """Test record_from_call with deterministic capability zeros tokens."""
    # Even though cost has tokens, deterministic capabilities should have 0 tokens
    record = record_from_call(
        side="received",
        agent="test-agent",
        peer="peer-agent",
        cap=deterministic_capability,
        status="OK",
        cost=cost,
        trace_id="test-trace-id",
    )

    assert record.side == "received"
    assert record.backing == "deterministic"
    assert record.tokens_in == 0  # Should be zero for deterministic
    assert record.tokens_out == 0  # Should be zero for deterministic
    assert record.cost_usd == 0.001  # Cost should still be preserved


@pytest.mark.asyncio
async def test_served_telemetry_emit_success():
    """Test that ServedTelemetry.emit publishes event and records successfully."""
    fake_registry = FakeRegistry()
    fake_recorder = FakeRecorder()
    
    telemetry = ServedTelemetry(registry=fake_registry, recorder=fake_recorder)
    
    # Create a simple test record
    record = CapabilityCallRecord(
        side="served",
        agent="test-agent",
        peer_agent="peer-agent",
        cap_id="test.cap",
        category="test",
        backing="deterministic",
        status="OK",
        trace_id="test-trace",
    )
    
    await telemetry.emit(record)
    
    # Check that event was published
    assert len(fake_registry.events) == 1
    event = fake_registry.events[0]
    assert isinstance(event, CapabilityCallEvent)
    assert event.record == record
    
    # Check that record was stored
    assert len(fake_recorder.records) == 1
    assert fake_recorder.records[0] == record


@pytest.mark.asyncio
async def test_served_telemetry_emit_registry_failure(caplog):
    """Test that ServedTelemetry.emit handles registry failure gracefully."""
    failing_registry = AsyncMock()
    failing_registry.emit.side_effect = RuntimeError("Registry failure")
    
    fake_recorder = FakeRecorder()
    telemetry = ServedTelemetry(registry=failing_registry, recorder=fake_recorder)
    
    record = CapabilityCallRecord(
        side="served",
        agent="test-agent",
        peer_agent="peer-agent",
        cap_id="test.cap",
        category="test",
        backing="deterministic",
        status="OK",
        trace_id="test-trace",
    )
    
    # Should not raise despite registry failure
    await telemetry.emit(record)
    
    # Recorder should still work
    assert len(fake_recorder.records) == 1
    assert fake_recorder.records[0] == record
    
    # Should log the exception
    assert "ServedTelemetry: event publish failed" in caplog.text


@pytest.mark.asyncio
async def test_served_telemetry_emit_recorder_failure(caplog):
    """Test that ServedTelemetry.emit handles recorder failure gracefully."""
    fake_registry = FakeRegistry()
    failing_recorder = AsyncMock()
    failing_recorder.record_capability.side_effect = RuntimeError("Recorder failure")
    
    telemetry = ServedTelemetry(registry=fake_registry, recorder=failing_recorder)
    
    record = CapabilityCallRecord(
        side="served",
        agent="test-agent",
        peer_agent="peer-agent",
        cap_id="test.cap",
        category="test",
        backing="deterministic",
        status="OK",
        trace_id="test-trace",
    )
    
    # Should not raise despite recorder failure
    await telemetry.emit(record)
    
    # Event should still be published
    assert len(fake_registry.events) == 1
    event = fake_registry.events[0]
    assert isinstance(event, CapabilityCallEvent)
    assert event.record == record
    
    # Should log the exception
    assert "ServedTelemetry: recorder failed" in caplog.text


@pytest.mark.asyncio
async def test_served_telemetry_emit_no_recorder():
    """Test that ServedTelemetry.emit works without a recorder."""
    fake_registry = FakeRegistry()
    telemetry = ServedTelemetry(registry=fake_registry, recorder=None)
    
    record = CapabilityCallRecord(
        side="served",
        agent="test-agent",
        peer_agent="peer-agent",
        cap_id="test.cap",
        category="test",
        backing="deterministic",
        status="OK",
        trace_id="test-trace",
    )
    
    await telemetry.emit(record)
    
    # Event should be published
    assert len(fake_registry.events) == 1
    event = fake_registry.events[0]
    assert isinstance(event, CapabilityCallEvent)
    assert event.record == record


@pytest.mark.asyncio
async def test_served_telemetry_uses_global_registry():
    """Test that ServedTelemetry uses global registry when none provided."""
    fake_recorder = FakeRecorder()
    telemetry = ServedTelemetry(recorder=fake_recorder)  # No registry provided
    
    record = CapabilityCallRecord(
        side="served",
        agent="test-agent",
        peer_agent="peer-agent",
        cap_id="test.cap",
        category="test",
        backing="deterministic",
        status="OK",
        trace_id="test-trace",
    )
    
    # This should not raise - it will use the global registry
    await telemetry.emit(record)
    
    # Recorder should still work
    assert len(fake_recorder.records) == 1