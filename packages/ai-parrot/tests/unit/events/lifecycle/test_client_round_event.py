"""Unit tests for ClientRoundEvent (FEAT-397)."""
import json
import dataclasses
import pytest
from navigator_eventbus.lifecycle.trace import TraceContext
from parrot.core.events.lifecycle.events import ClientRoundEvent


@pytest.fixture
def trace_root():
    """Shared TraceContext fixture."""
    return TraceContext.new_root()


def test_defaults_and_frozen(trace_root):
    e = ClientRoundEvent(
        trace_context=trace_root, client_name="anthropic", model="claude-x", round_number=1
    )
    assert e.input_tokens is None and e.raw_usage is None and e.tool_calls == ()
    with pytest.raises(dataclasses.FrozenInstanceError):
        e.round_number = 2


def test_to_dict_json_safe(trace_root):
    e = ClientRoundEvent(
        trace_context=trace_root,
        client_name="openai", model="gpt-x", round_number=2,
        input_tokens=100, output_tokens=20, total_tokens=120,
        tool_calls=("get_weather", "search"), raw_usage={"prompt_tokens": 100},
    )
    d = e.to_dict()
    json.dumps(d)  # must not raise
    assert d["tool_calls"] == ["get_weather", "search"]
    assert d["event_class"] == "ClientRoundEvent"


def test_none_usage_round(trace_root):
    e = ClientRoundEvent(
        trace_context=trace_root,
        client_name="grok", model="grok-x", round_number=3,
        input_tokens=None, output_tokens=None, total_tokens=None,
    )
    d = e.to_dict()
    json.dumps(d)
    assert d["input_tokens"] is None
    assert d["output_tokens"] is None
    assert d["total_tokens"] is None


def test_agent_name_field(trace_root):
    e = ClientRoundEvent(
        trace_context=trace_root, client_name="openai", model="gpt-x", agent_name="bot-a"
    )
    assert e.agent_name == "bot-a"
    assert e.to_dict()["agent_name"] == "bot-a"
