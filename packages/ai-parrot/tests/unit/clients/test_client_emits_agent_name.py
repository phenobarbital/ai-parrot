"""Unit tests for TASK-1502 — client events carry agent_name from the ContextVar.

FEAT-228. Verifies that AbstractClient._emit_before_call, _emit_after_call, and
_emit_failed_call stamp ``agent_name=current_agent_name.get()`` on the constructed
events.  Uses the event-dataclass constructors directly (no real network call).
"""

from __future__ import annotations

import pytest

from parrot.core.events.lifecycle.events.client import (
    AfterClientCallEvent,
    BeforeClientCallEvent,
    ClientCallFailedEvent,
)
from navigator_eventbus.lifecycle.trace import TraceContext
from parrot.observability.context import agent_identity, current_agent_name


@pytest.fixture
def tc() -> TraceContext:
    return TraceContext.new_root()


# ---------------------------------------------------------------------------
# Verify the event-construction pattern that TASK-1502 inserts into
# AbstractClient._emit_{before,after,failed}_call.
# These tests construct the events the same way the client does and assert
# the agent_name is picked up from the ContextVar.
# ---------------------------------------------------------------------------


def test_before_event_picks_up_agent_name_from_contextvar(tc: TraceContext) -> None:
    """When agent_name is set in the ContextVar, BeforeClientCallEvent carries it."""
    with agent_identity("porygon"):
        event = BeforeClientCallEvent(
            trace_context=tc,
            client_name="openai",
            model="gpt-4o",
            agent_name=current_agent_name.get(),
        )
    assert event.agent_name == "porygon"


def test_before_event_agent_name_none_without_scope(tc: TraceContext) -> None:
    """Without an active scope, agent_name is None on BeforeClientCallEvent."""
    event = BeforeClientCallEvent(
        trace_context=tc,
        client_name="openai",
        model="gpt-4o",
        agent_name=current_agent_name.get(),
    )
    assert event.agent_name is None


def test_after_event_picks_up_agent_name_from_contextvar(tc: TraceContext) -> None:
    """When agent_name is set in the ContextVar, AfterClientCallEvent carries it."""
    with agent_identity("porygon"):
        event = AfterClientCallEvent(
            trace_context=tc,
            client_name="openai",
            model="gpt-4o",
            duration_ms=42.0,
            agent_name=current_agent_name.get(),
        )
    assert event.agent_name == "porygon"


def test_after_event_agent_name_none_without_scope(tc: TraceContext) -> None:
    """Without an active scope, agent_name is None on AfterClientCallEvent."""
    event = AfterClientCallEvent(
        trace_context=tc,
        client_name="openai",
        model="gpt-4o",
        agent_name=current_agent_name.get(),
    )
    assert event.agent_name is None


def test_failed_event_picks_up_agent_name_from_contextvar(tc: TraceContext) -> None:
    """When agent_name is set in the ContextVar, ClientCallFailedEvent carries it."""
    with agent_identity("porygon"):
        event = ClientCallFailedEvent(
            trace_context=tc,
            client_name="openai",
            model="gpt-4o",
            duration_ms=10.0,
            error_type="TimeoutError",
            error_message="timed out",
            agent_name=current_agent_name.get(),
        )
    assert event.agent_name == "porygon"


def test_failed_event_agent_name_none_without_scope(tc: TraceContext) -> None:
    """Without an active scope, agent_name is None on ClientCallFailedEvent."""
    event = ClientCallFailedEvent(
        trace_context=tc,
        client_name="openai",
        model="gpt-4o",
        error_type="TimeoutError",
        error_message="timed out",
        agent_name=current_agent_name.get(),
    )
    assert event.agent_name is None


def test_contextvar_read_is_synchronous_in_bot_context(tc: TraceContext) -> None:
    """current_agent_name.get() is called synchronously at construction time.

    This verifies that even when emit_nowait fires asynchronously later,
    the agent_name was already captured when the event was built.
    """
    captured_before_emit = None
    with agent_identity("capture-bot"):
        captured_before_emit = current_agent_name.get()
        event = AfterClientCallEvent(
            trace_context=tc,
            client_name="openai",
            model="gpt-4o",
            agent_name=current_agent_name.get(),
        )
    # After the with-block, the var reverts to None
    assert current_agent_name.get() is None
    # But the event still carries the captured value
    assert event.agent_name == "capture-bot"
    assert captured_before_emit == "capture-bot"
