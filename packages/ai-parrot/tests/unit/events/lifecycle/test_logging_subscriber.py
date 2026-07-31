"""Unit tests for LoggingSubscriber.

FEAT-176 — Lifecycle Events System (TASK-1190).
"""
from __future__ import annotations

import logging
import pytest

from navigator_eventbus.lifecycle.provider import EventProvider
from navigator_eventbus.lifecycle.registry import EventRegistry
from navigator_eventbus.lifecycle.subscribers.logging import LoggingSubscriber
from parrot.core.events.lifecycle.events import AfterToolCallEvent, BeforeInvokeEvent
from navigator_eventbus.lifecycle.trace import TraceContext


class TestLoggingSubscriber:
    def test_protocol_conformance(self) -> None:
        """LoggingSubscriber conforms to the EventProvider Protocol."""
        assert isinstance(LoggingSubscriber(), EventProvider)

    def test_add_provider_returns_one_id(self) -> None:
        """add_provider(LoggingSubscriber()) returns exactly one subscription ID."""
        reg = EventRegistry(forward_to_global=False)
        ids = reg.add_provider(LoggingSubscriber())
        assert len(ids) == 1

    @pytest.mark.asyncio
    async def test_logs_every_event(self, caplog: pytest.LogCaptureFixture) -> None:
        """LoggingSubscriber logs a record for every lifecycle event."""
        reg = EventRegistry(forward_to_global=False)
        reg.add_provider(LoggingSubscriber(level=logging.INFO))
        with caplog.at_level(logging.INFO, logger="parrot.lifecycle"):
            await reg.emit(BeforeInvokeEvent(trace_context=TraceContext.new_root()))
            await reg.emit(AfterToolCallEvent(trace_context=TraceContext.new_root()))
        events = [r for r in caplog.records if r.name == "parrot.lifecycle"]
        assert len(events) == 2
        assert "BeforeInvokeEvent" in events[0].message
        assert "AfterToolCallEvent" in events[1].message

    @pytest.mark.asyncio
    async def test_custom_level(self, caplog: pytest.LogCaptureFixture) -> None:
        """Custom level is honored in log records."""
        reg = EventRegistry(forward_to_global=False)
        reg.add_provider(LoggingSubscriber(level=logging.DEBUG))
        with caplog.at_level(logging.DEBUG, logger="parrot.lifecycle"):
            await reg.emit(BeforeInvokeEvent(trace_context=TraceContext.new_root()))
        lifecycle_records = [r for r in caplog.records if r.name == "parrot.lifecycle"]
        assert len(lifecycle_records) == 1
        assert lifecycle_records[0].levelno == logging.DEBUG

    @pytest.mark.asyncio
    async def test_includes_trace_id(self, caplog: pytest.LogCaptureFixture) -> None:
        """Log message includes the trace_id from the event's TraceContext."""
        ctx = TraceContext.new_root()
        reg = EventRegistry(forward_to_global=False)
        reg.add_provider(LoggingSubscriber())
        with caplog.at_level(logging.INFO, logger="parrot.lifecycle"):
            await reg.emit(BeforeInvokeEvent(trace_context=ctx))
        lifecycle_records = [r for r in caplog.records if r.name == "parrot.lifecycle"]
        assert len(lifecycle_records) == 1
        assert ctx.trace_id in lifecycle_records[0].message

    @pytest.mark.asyncio
    async def test_custom_logger_name(self, caplog: pytest.LogCaptureFixture) -> None:
        """Custom logger_name is used for the log record."""
        reg = EventRegistry(forward_to_global=False)
        reg.add_provider(LoggingSubscriber(logger_name="custom.lifecycle"))
        with caplog.at_level(logging.INFO, logger="custom.lifecycle"):
            await reg.emit(BeforeInvokeEvent(trace_context=TraceContext.new_root()))
        custom_records = [r for r in caplog.records if r.name == "custom.lifecycle"]
        assert len(custom_records) == 1

    @pytest.mark.asyncio
    async def test_includes_event_class_name(self, caplog: pytest.LogCaptureFixture) -> None:
        """Log message always includes the event class name."""
        reg = EventRegistry(forward_to_global=False)
        reg.add_provider(LoggingSubscriber())
        with caplog.at_level(logging.INFO, logger="parrot.lifecycle"):
            await reg.emit(AfterToolCallEvent(trace_context=TraceContext.new_root()))
        lifecycle_records = [r for r in caplog.records if r.name == "parrot.lifecycle"]
        assert "AfterToolCallEvent" in lifecycle_records[0].message
