"""Unit tests for FEAT-462 GenAI SemConv attribute additions.

Covers ``gen_ai.operation.name`` on ``build_before_client_attrs()`` and the
dual ``gen_ai.usage.cost`` / ``parrot.cost.usd`` attributes on
``build_after_client_attrs()``.

Spec: sdd/specs/unified-telemetry-bus.spec.md §3 Module 3.
Task: TASK-2472.
"""

from __future__ import annotations

from navigator_eventbus.lifecycle.trace import TraceContext
from parrot.core.events.lifecycle.events import (
    AfterClientCallEvent,
    BeforeClientCallEvent,
)
from parrot.observability.attributes import (
    build_after_client_attrs,
    build_before_client_attrs,
)


class TestGenAiOperationName:
    def test_present_in_before_attrs(self) -> None:
        e = BeforeClientCallEvent(
            trace_context=TraceContext.new_root(),
            client_name="openai",
            model="gpt-4o",
        )
        attrs = build_before_client_attrs(e)
        assert attrs.get("gen_ai.operation.name") == "chat"

    def test_present_regardless_of_provider(self) -> None:
        e = BeforeClientCallEvent(
            trace_context=TraceContext.new_root(),
            client_name="anthropic",
            model="claude-3-5-sonnet",
        )
        attrs = build_before_client_attrs(e)
        assert attrs["gen_ai.operation.name"] == "chat"


class TestDualCostAttributes:
    def test_both_cost_attrs_present(self) -> None:
        e = AfterClientCallEvent(
            trace_context=TraceContext.new_root(),
            client_name="openai",
            model="gpt-4o",
            input_tokens=100,
            output_tokens=50,
            finish_reason="stop",
        )
        attrs = build_after_client_attrs(e, cost_usd=0.005)
        assert attrs["gen_ai.usage.cost"] == 0.005
        assert attrs["parrot.cost.usd"] == 0.005

    def test_no_cost_when_none(self) -> None:
        e = AfterClientCallEvent(
            trace_context=TraceContext.new_root(),
            client_name="openai",
            model="gpt-4o",
            input_tokens=100,
            output_tokens=50,
            finish_reason="stop",
        )
        attrs = build_after_client_attrs(e, cost_usd=None)
        assert "gen_ai.usage.cost" not in attrs
        assert "parrot.cost.usd" not in attrs

    def test_cost_values_match(self) -> None:
        """gen_ai.usage.cost and parrot.cost.usd must always agree."""
        e = AfterClientCallEvent(
            trace_context=TraceContext.new_root(),
            client_name="anthropic",
            model="claude-3-5-sonnet",
        )
        attrs = build_after_client_attrs(e, cost_usd=1.23456)
        assert attrs["gen_ai.usage.cost"] == attrs["parrot.cost.usd"] == 1.23456
