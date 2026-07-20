"""Unit tests for all concrete lifecycle event classes (TASK-1184, FEAT-176)."""
import json
import pytest
from dataclasses import FrozenInstanceError

from navigator_eventbus.lifecycle.trace import TraceContext
from parrot.core.events.lifecycle.events import (
    AgentInitializedEvent,
    AgentConfiguredEvent,
    ToolManagerReadyEvent,
    AgentStatusChangedEvent,
    BeforeInvokeEvent,
    AfterInvokeEvent,
    InvokeFailedEvent,
    BeforeClientCallEvent,
    AfterClientCallEvent,
    ClientCallFailedEvent,
    ClientStreamChunkEvent,
    BeforeToolCallEvent,
    AfterToolCallEvent,
    ToolCallFailedEvent,
    MessageAddedEvent,
)
from navigator_eventbus.lifecycle.meta import SubscriberErrorEvent


ALL_CLASSES = [
    AgentInitializedEvent,
    AgentConfiguredEvent,
    ToolManagerReadyEvent,
    AgentStatusChangedEvent,
    BeforeInvokeEvent,
    AfterInvokeEvent,
    InvokeFailedEvent,
    BeforeClientCallEvent,
    AfterClientCallEvent,
    ClientCallFailedEvent,
    ClientStreamChunkEvent,
    BeforeToolCallEvent,
    AfterToolCallEvent,
    ToolCallFailedEvent,
    MessageAddedEvent,
    SubscriberErrorEvent,
]


@pytest.fixture
def trace_root():
    """Shared TraceContext fixture."""
    return TraceContext.new_root()


@pytest.mark.parametrize("cls", ALL_CLASSES)
def test_instantiate_with_defaults(cls, trace_root):
    """Every event class instantiates with just trace_context=... (all other fields have defaults)."""
    evt = cls(trace_context=trace_root)
    assert evt.trace_context is trace_root


@pytest.mark.parametrize("cls", ALL_CLASSES)
def test_frozen(cls, trace_root):
    """Every event class is frozen — mutating source_name raises."""
    evt = cls(trace_context=trace_root)
    with pytest.raises((FrozenInstanceError, TypeError)):
        evt.source_name = "x"   # type: ignore[misc]


@pytest.mark.parametrize("cls", ALL_CLASSES)
def test_to_dict_json_serializable(cls, trace_root):
    """Every event class produces a JSON-serializable dict from to_dict()."""
    evt = cls(trace_context=trace_root)
    d = evt.to_dict()
    assert json.dumps(d)   # must not raise


@pytest.mark.parametrize("cls", ALL_CLASSES)
def test_event_class_name_in_dict(cls, trace_root):
    """to_dict() includes the 'event_class' key with the concrete class name."""
    evt = cls(trace_context=trace_root)
    assert evt.to_dict()["event_class"] == cls.__name__


def test_tool_manager_ready_tuple_field(trace_root):
    """ToolManagerReadyEvent.tool_names is a tuple that serializes to list."""
    evt = ToolManagerReadyEvent(
        trace_context=trace_root,
        tool_count=2,
        tool_names=("tool_a", "tool_b"),
    )
    assert evt.tool_names == ("tool_a", "tool_b")
    d = evt.to_dict()
    # to_dict() converts tuple → list for JSON round-trip
    assert json.dumps(d)
    assert isinstance(d["tool_names"], list)
    assert d["tool_names"] == ["tool_a", "tool_b"]
    assert d["tool_count"] == 2


def test_before_tool_call_args_summary(trace_root):
    """BeforeToolCallEvent.args_summary is a dict with default_factory=dict."""
    evt = BeforeToolCallEvent(trace_context=trace_root, tool_name="my_tool")
    assert isinstance(evt.args_summary, dict)
    assert evt.to_dict()["args_summary"] == {}

    # With populated args_summary
    evt2 = BeforeToolCallEvent(
        trace_context=trace_root,
        tool_name="my_tool",
        args_summary={"query": "hello"},
    )
    assert evt2.args_summary == {"query": "hello"}
    assert json.dumps(evt2.to_dict())


def test_client_stream_chunk_no_text(trace_root):
    """ClientStreamChunkEvent only carries metadata, not chunk text."""
    evt = ClientStreamChunkEvent(
        trace_context=trace_root,
        client_name="claude",
        model="claude-3",
        chunk_index=5,
        chunk_size_bytes=128,
    )
    d = evt.to_dict()
    # Verify metadata fields are present
    assert d["chunk_index"] == 5
    assert d["chunk_size_bytes"] == 128
    # No text field
    assert "chunk_text" not in d
    assert "content" not in d


def test_subscriber_error_event_fields(trace_root):
    """SubscriberErrorEvent has all required diagnostic fields."""
    evt = SubscriberErrorEvent(
        trace_context=trace_root,
        failed_subscriber="<cb at 0x1234>",
        original_event_class="BeforeInvokeEvent",
        error_type="RuntimeError",
        error_message="boom",
        traceback="Traceback ...",
    )
    d = evt.to_dict()
    assert d["failed_subscriber"] == "<cb at 0x1234>"
    assert d["original_event_class"] == "BeforeInvokeEvent"
    assert d["error_type"] == "RuntimeError"


def test_agent_status_changed_name_strings(trace_root):
    """AgentStatusChangedEvent stores status names as strings."""
    evt = AgentStatusChangedEvent(
        trace_context=trace_root,
        agent_name="my_agent",
        old_status="IDLE",
        new_status="WORKING",
    )
    assert evt.old_status == "IDLE"
    assert evt.new_status == "WORKING"
