"""FEAT-710 TASK-4546 — new usage-event fields."""

from navigator_eventbus.lifecycle.trace import TraceContext

from parrot.core.events.lifecycle.events import (
    AfterClientCallEvent,
    AfterInvokeEvent,
    ClientCallFailedEvent,
    InvokeFailedEvent,
)


def test_defaults_are_none() -> None:
    """Usage attribution and cost fields default to unknown."""
    trace_context = TraceContext.new_root()
    after_invoke = AfterInvokeEvent(trace_context=trace_context)
    invoke_failed = InvokeFailedEvent(trace_context=trace_context)
    after_client_call = AfterClientCallEvent(trace_context=trace_context)
    client_call_failed = ClientCallFailedEvent(trace_context=trace_context)

    assert after_invoke.tenant is None
    assert after_invoke.user_id is None
    assert after_invoke.session_id is None
    assert invoke_failed.tenant is None
    assert invoke_failed.user_id is None
    assert invoke_failed.session_id is None
    assert after_client_call.tenant is None
    assert after_client_call.cost_usd is None
    assert client_call_failed.tenant is None


def test_to_dict_carries_new_fields() -> None:
    """Lifecycle serialization includes every new usage-event field."""
    trace_context = TraceContext.new_root()
    after_invoke = AfterInvokeEvent(
        trace_context=trace_context,
        tenant="tenant-1",
        user_id="user-1",
        session_id="session-1",
    ).to_dict()
    invoke_failed = InvokeFailedEvent(
        trace_context=trace_context,
        tenant="tenant-2",
        user_id="user-2",
        session_id="session-2",
    ).to_dict()
    after_client_call = AfterClientCallEvent(
        trace_context=trace_context,
        tenant="tenant-3",
        cost_usd=0.125,
    ).to_dict()
    client_call_failed = ClientCallFailedEvent(trace_context=trace_context, tenant="tenant-4").to_dict()

    assert after_invoke["tenant"] == "tenant-1"
    assert after_invoke["user_id"] == "user-1"
    assert after_invoke["session_id"] == "session-1"
    assert invoke_failed["tenant"] == "tenant-2"
    assert invoke_failed["user_id"] == "user-2"
    assert invoke_failed["session_id"] == "session-2"
    assert after_client_call["tenant"] == "tenant-3"
    assert after_client_call["cost_usd"] == 0.125
    assert client_call_failed["tenant"] == "tenant-4"
