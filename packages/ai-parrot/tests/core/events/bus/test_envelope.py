"""Unit tests for the EventEnvelope contract (FEAT-310, TASK-1783)."""
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

import pytest

from parrot.core.events.bus import EventEnvelope, IngressEnvelope, Severity
from parrot.core.events.bus.converters import (
    from_hook_event,
    from_legacy_event,
    from_lifecycle_dict,
)
from parrot.core.events.evb import Event, EventPriority
from parrot.core.hooks.models import HookEvent, HookType


def test_envelope_rejects_naive_timestamp():
    with pytest.raises(ValueError, match="tz-aware"):
        EventEnvelope(topic="a.b", payload={}, timestamp=datetime.now())


def test_envelope_frozen_and_slots():
    env = EventEnvelope(
        topic="a.b", payload={}, timestamp=datetime.now(timezone.utc)
    )
    with pytest.raises(FrozenInstanceError):
        env.topic = "other"
    assert not hasattr(env, "__dict__")


def test_envelope_defaults_are_tz_aware_utc():
    env = EventEnvelope(topic="a.b", payload={})
    assert env.timestamp.tzinfo is not None
    assert env.timestamp.utcoffset().total_seconds() == 0
    assert env.severity == Severity.INFO
    assert env.priority == EventPriority.NORMAL
    assert env.event_id


def test_severity_distinct_from_priority():
    assert Severity.CRITICAL != EventPriority.CRITICAL
    assert [s.value for s in Severity] == [10, 20, 30, 40, 50]


def test_to_dict_from_dict_round_trip():
    env = EventEnvelope(
        topic="order.created",
        payload={"k": 1},
        timestamp=datetime.now(timezone.utc),
        source="unit-test",
        severity=Severity.WARNING,
        priority=EventPriority.HIGH,
        correlation_id="corr-1",
        trace_context={"traceparent": "00-abc-def-01"},
        metadata={"m": "v"},
    )
    data = env.to_dict()
    assert data["severity"] == Severity.WARNING.value
    assert data["priority"] == EventPriority.HIGH.value
    assert isinstance(data["timestamp"], str)

    restored = EventEnvelope.from_dict(data)
    assert restored == env


def test_converters_lifecycle_hookevent_legacy():
    legacy = Event(event_type="x.y", payload={"k": 1})
    hook = HookEvent(
        hook_id="h1",
        hook_type=HookType.JIRA_WEBHOOK,
        event_type="jira.issue",
        payload={},
    )
    for env in (from_legacy_event(legacy), from_hook_event(hook)):
        assert env.timestamp.tzinfo is not None
        assert env.severity == Severity.INFO

    lifecycle_dict = {
        "trace_context": {"traceparent": "00-abc-def-01"},
        "event_id": "evt-1",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source_type": "agent",
        "source_name": "my-agent",
        "event_class": "AgentStartEvent",
    }
    env = from_lifecycle_dict(lifecycle_dict)
    assert env.topic == "lifecycle.AgentStartEvent"
    assert env.event_id == "evt-1"
    assert env.timestamp.tzinfo is not None
    assert env.severity == Severity.INFO
    assert env.trace_context == {"traceparent": "00-abc-def-01"}
    assert env.source == "agent:my-agent"


def test_converters_coerce_naive_timestamps_to_utc():
    legacy = Event(event_type="x.y", payload={})  # naive datetime.now()
    hook = HookEvent(
        hook_id="h1",
        hook_type=HookType.SCHEDULER,
        event_type="tick",
        payload={},
    )  # naive datetime.now()
    assert legacy.timestamp.tzinfo is None
    assert hook.timestamp.tzinfo is None

    for env in (from_legacy_event(legacy), from_hook_event(hook)):
        assert env.timestamp.tzinfo is not None
        assert env.timestamp.utcoffset().total_seconds() == 0


def test_converter_semantics_equivalent_inputs():
    ts = datetime.now(timezone.utc)
    legacy = Event(
        event_type="hooks.scheduler.tick",
        payload={"a": 1},
        timestamp=ts,
        source="h1",
    )
    hook = HookEvent(
        hook_id="h1",
        hook_type=HookType.SCHEDULER,
        event_type="tick",
        payload={"a": 1},
        timestamp=ts,
    )
    env_a = from_legacy_event(legacy)
    env_b = from_hook_event(hook)
    assert env_a.topic == env_b.topic == "hooks.scheduler.tick"
    assert env_a.payload == env_b.payload
    assert env_a.timestamp == env_b.timestamp
    assert env_a.source == env_b.source == "h1"
    assert env_a.severity == env_b.severity == Severity.INFO
    assert env_a.priority == env_b.priority == EventPriority.NORMAL


def test_ingress_envelope_forbids_extra_and_converts():
    with pytest.raises(Exception):
        IngressEnvelope(topic="a.b", nope="x")

    ing = IngressEnvelope(topic="a.b", payload={"k": 1})
    env = ing.to_envelope()
    assert isinstance(env, EventEnvelope)
    assert env.topic == "a.b"
    assert env.timestamp.tzinfo is not None


def test_ingress_envelope_coerces_naive_timestamp():
    ing = IngressEnvelope(topic="a.b", timestamp=datetime.now())
    assert ing.timestamp.tzinfo is not None
    env = ing.to_envelope()
    assert env.timestamp.tzinfo is not None


def test_ingress_envelope_frozen():
    ing = IngressEnvelope(topic="a.b")
    with pytest.raises(Exception):
        ing.topic = "other"
