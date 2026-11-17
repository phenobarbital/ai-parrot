"""Tests for FEAT-796 usage component attribution."""

from __future__ import annotations

import pytest
from navigator_eventbus.lifecycle.registry import EventRegistry
from navigator_eventbus.lifecycle.trace import TraceContext
from parrot.core.events.lifecycle.events import AfterClientCallEvent, ClientCallFailedEvent
from parrot.observability.context import current_component, usage_component
from parrot.observability.recorders.models import UsageRecord
from parrot.observability.recorders.subscriber import UsageRecordingSubscriber


class _CapturingSink:
    """Minimal recorder that retains emitted records for assertions."""

    def __init__(self) -> None:
        self.records: list[UsageRecord] = []

    async def record(self, record: UsageRecord) -> None:
        """Capture one usage record."""
        self.records.append(record)

    async def aclose(self) -> None:
        """Close the recorder without additional work."""


@pytest.fixture
def isolated_registry() -> EventRegistry:
    """Return an event registry isolated from the process-wide singleton."""
    return EventRegistry(forward_to_global=False)


def test_usage_component_cm_sets_and_resets() -> None:
    """The context manager binds a component only for its scope."""
    assert current_component.get() is None

    with usage_component("CREW"):
        assert current_component.get() == "CREW"

    assert current_component.get() is None


def test_nested_innermost_wins() -> None:
    """Nested component scopes restore the outer component on exit."""
    with usage_component("CREW"):
        with usage_component("EXPERT_JUDGMENT"):
            assert current_component.get() == "EXPERT_JUDGMENT"
        assert current_component.get() == "CREW"

    assert current_component.get() is None


def test_usage_record_component_default_none() -> None:
    """Minimal record construction remains backward compatible."""
    assert UsageRecord(provider="openai").component is None


async def test_subscriber_tags_component(isolated_registry: EventRegistry) -> None:
    """Successful and failed client calls inherit the scoped component tag."""
    sink = _CapturingSink()
    isolated_registry.add_provider(UsageRecordingSubscriber(recorders=[sink], cost_calculator=None))

    with usage_component("AGENT"):
        await isolated_registry.emit(
            AfterClientCallEvent(
                trace_context=TraceContext.new_root(),
                client_name="openai",
                model="gpt-4o",
                duration_ms=100.0,
                input_tokens=10,
                output_tokens=5,
            )
        )
        await isolated_registry.emit(
            ClientCallFailedEvent(
                trace_context=TraceContext.new_root(),
                client_name="openai",
                model="gpt-4o",
                duration_ms=50.0,
                error_type="TimeoutError",
                error_message="not retained",
            )
        )

    assert [record.component for record in sink.records] == ["AGENT", "AGENT"]


async def test_subscriber_leaves_unattributed_component_none(isolated_registry: EventRegistry) -> None:
    """Calls outside a component scope remain unattributed."""
    sink = _CapturingSink()
    isolated_registry.add_provider(UsageRecordingSubscriber(recorders=[sink], cost_calculator=None))

    await isolated_registry.emit(
        AfterClientCallEvent(
            trace_context=TraceContext.new_root(),
            client_name="openai",
            model="gpt-4o",
            duration_ms=100.0,
            input_tokens=10,
            output_tokens=5,
        )
    )

    assert sink.records[0].component is None
