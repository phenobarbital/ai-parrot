"""Unit tests for ParrotTelemetryProvider.

FEAT-177 TASK-1233.
"""

from __future__ import annotations

from unittest.mock import MagicMock


from navigator_eventbus.lifecycle.provider import EventProvider
from navigator_eventbus.lifecycle.registry import EventRegistry
from parrot.observability import ParrotTelemetryProvider


def test_protocol_conformance() -> None:
    """ParrotTelemetryProvider() must be an instance of EventProvider Protocol."""
    assert isinstance(ParrotTelemetryProvider(), EventProvider)


def test_register_invokes_each_subscriber() -> None:
    """register() calls register(registry) on each non-None subscriber exactly once."""
    trace = MagicMock()
    metrics = MagicMock()
    p = ParrotTelemetryProvider(trace_subscriber=trace, metrics_subscriber=metrics)
    reg = EventRegistry(forward_to_global=False)
    p.register(reg)
    trace.register.assert_called_once_with(reg)
    metrics.register.assert_called_once_with(reg)


def test_no_op_when_both_none() -> None:
    """ParrotTelemetryProvider() with both None is a no-op — must not raise."""
    p = ParrotTelemetryProvider()
    reg = EventRegistry(forward_to_global=False)
    p.register(reg)   # must not raise


def test_only_trace_subscriber() -> None:
    """When only trace subscriber is provided, metrics register is not called."""
    trace = MagicMock()
    p = ParrotTelemetryProvider(trace_subscriber=trace)
    reg = EventRegistry(forward_to_global=False)
    p.register(reg)
    trace.register.assert_called_once_with(reg)


def test_only_metrics_subscriber() -> None:
    """When only metrics subscriber is provided, trace register is not called."""
    metrics = MagicMock()
    p = ParrotTelemetryProvider(metrics_subscriber=metrics)
    reg = EventRegistry(forward_to_global=False)
    p.register(reg)
    metrics.register.assert_called_once_with(reg)
