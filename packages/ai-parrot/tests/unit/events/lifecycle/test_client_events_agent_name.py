"""Unit tests for the agent_name field on client lifecycle events.

FEAT-228 TASK-1500.  Verifies the new optional field on the three client
event dataclasses: BeforeClientCallEvent, AfterClientCallEvent,
ClientCallFailedEvent.
"""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError

import pytest

from parrot.core.events.lifecycle.events.client import (
    AfterClientCallEvent,
    BeforeClientCallEvent,
    ClientCallFailedEvent,
)
from navigator_eventbus.lifecycle.trace import TraceContext


@pytest.fixture
def tc() -> TraceContext:
    """Return a fresh root TraceContext."""
    return TraceContext.new_root()


# ---------------------------------------------------------------------------
# BeforeClientCallEvent
# ---------------------------------------------------------------------------


def test_before_client_agent_name_defaults_none(tc: TraceContext) -> None:
    """agent_name defaults to None for backward-compat construction."""
    ev = BeforeClientCallEvent(trace_context=tc, client_name="openai", model="gpt-4o")
    assert ev.agent_name is None


def test_before_client_agent_name_set(tc: TraceContext) -> None:
    """agent_name is stored when passed explicitly."""
    ev = BeforeClientCallEvent(
        trace_context=tc, client_name="openai", model="gpt-4o", agent_name="porygon"
    )
    assert ev.agent_name == "porygon"


def test_before_client_frozen_mutation_raises(tc: TraceContext) -> None:
    """Dataclass remains frozen after adding agent_name."""
    ev = BeforeClientCallEvent(trace_context=tc)
    with pytest.raises(FrozenInstanceError):
        ev.agent_name = "mutate"  # type: ignore[misc]


def test_before_client_to_dict_serializable_with_agent(tc: TraceContext) -> None:
    """to_dict() + json.dumps still works when agent_name is set."""
    ev = BeforeClientCallEvent(
        trace_context=tc, client_name="anthropic", model="claude-3-5-sonnet",
        agent_name="porygon",
    )
    d = ev.to_dict()
    # Must be JSON-serializable
    serialized = json.dumps(d)
    assert "porygon" in serialized


def test_before_client_to_dict_serializable_without_agent(tc: TraceContext) -> None:
    """to_dict() + json.dumps works when agent_name is None (omitted or None)."""
    ev = BeforeClientCallEvent(trace_context=tc, client_name="openai", model="gpt-4o")
    d = ev.to_dict()
    json.dumps(d)  # must not raise


# ---------------------------------------------------------------------------
# AfterClientCallEvent
# ---------------------------------------------------------------------------


def test_after_client_agent_name_defaults_none(tc: TraceContext) -> None:
    """agent_name defaults to None for backward-compat construction."""
    ev = AfterClientCallEvent(trace_context=tc, client_name="openai", model="gpt-4o")
    assert ev.agent_name is None


def test_after_client_agent_name_set_and_serializable(tc: TraceContext) -> None:
    """agent_name is stored and survives to_dict() serialization."""
    ev = AfterClientCallEvent(
        trace_context=tc,
        client_name="openai",
        model="gpt-4o",
        agent_name="porygon",
    )
    assert ev.agent_name == "porygon"
    serialized = json.dumps(ev.to_dict())
    assert "porygon" in serialized


def test_after_client_frozen_mutation_raises(tc: TraceContext) -> None:
    """AfterClientCallEvent remains frozen after adding agent_name."""
    ev = AfterClientCallEvent(trace_context=tc)
    with pytest.raises(FrozenInstanceError):
        ev.agent_name = "mutate"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# ClientCallFailedEvent
# ---------------------------------------------------------------------------


def test_failed_client_agent_name_defaults_none(tc: TraceContext) -> None:
    """agent_name defaults to None for backward-compat construction."""
    ev = ClientCallFailedEvent(
        trace_context=tc,
        client_name="openai",
        model="gpt-4o",
        error_type="TimeoutError",
        error_message="timed out",
    )
    assert ev.agent_name is None


def test_failed_client_agent_name_set(tc: TraceContext) -> None:
    """agent_name is stored when passed explicitly."""
    ev = ClientCallFailedEvent(
        trace_context=tc,
        client_name="openai",
        model="gpt-4o",
        error_type="TimeoutError",
        error_message="timed out",
        agent_name="porygon",
    )
    assert ev.agent_name == "porygon"
    serialized = json.dumps(ev.to_dict())
    assert "porygon" in serialized


def test_failed_client_frozen_mutation_raises(tc: TraceContext) -> None:
    """ClientCallFailedEvent remains frozen after adding agent_name."""
    ev = ClientCallFailedEvent(trace_context=tc)
    with pytest.raises(FrozenInstanceError):
        ev.agent_name = "mutate"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# PII guard
# ---------------------------------------------------------------------------


def test_agent_name_is_not_pii_field(tc: TraceContext) -> None:
    """agent_name stores AbstractBot.name only (not user_id/session_id/prompt).

    This is a documentation/contract test: the field name is 'agent_name'
    and its value is a short bot identifier, not user-sourced PII.
    We verify the field exists and has the right name (not user_id etc.).
    """
    ev = AfterClientCallEvent(
        trace_context=tc, client_name="openai", model="gpt-4o", agent_name="my-bot"
    )
    # Confirm no PII field names leaked in
    d = ev.to_dict()
    for key in d:
        assert key not in {"user_id", "session_id"}, f"PII field found: {key}"
    assert d.get("agent_name") == "my-bot"
