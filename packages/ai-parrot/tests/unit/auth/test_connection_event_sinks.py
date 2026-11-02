"""Tests for channel-independent connection event sinks (FEAT-777 M1)."""

from __future__ import annotations

import logging
import time
from typing import Any, Iterator

import pytest

from parrot.auth.oauth2.events import (
    ChannelNotifierRegistry,
    ConnectionEvent,
    ConnectionEventPublisher,
    ConnectionEventSink,
)


@pytest.fixture(autouse=True)
def _fresh_registry() -> Iterator[None]:
    """Reset the process-wide registry around every test."""
    ChannelNotifierRegistry._reset()
    yield
    ChannelNotifierRegistry._reset()


def _event(channel: str = "telegram") -> ConnectionEvent:
    """Build a representative connection event for ``channel``."""
    return ConnectionEvent(
        kind="connection.completed",
        user_id="1042",
        provider="jira",
        channel=channel,
        occurred_at=time.time(),
    )


class _RecordingSink:
    """Collect delivered events for assertions."""

    def __init__(self) -> None:
        self.events: list[ConnectionEvent] = []

    async def deliver(self, event: ConnectionEvent) -> None:
        """Record the delivered event."""
        self.events.append(event)


class _RaisingSink:
    """Raise from delivery to exercise publisher isolation."""

    async def deliver(self, event: ConnectionEvent) -> None:
        """Raise a delivery error."""
        raise RuntimeError("boom")


@pytest.mark.asyncio
async def test_publisher_calls_sinks_for_every_channel() -> None:
    """An event for a channel with no web notifier still reaches the sink."""
    sink = _RecordingSink()
    publisher = ConnectionEventPublisher()
    publisher.add_sink(sink)
    event = _event()

    await publisher.publish(event)

    assert sink.events == [event]


@pytest.mark.asyncio
async def test_raising_sink_is_isolated(caplog: pytest.LogCaptureFixture) -> None:
    """A raising sink is logged, later sinks still run, publish does not raise."""
    sink = _RecordingSink()
    publisher = ConnectionEventPublisher()
    publisher.add_sink(_RaisingSink())
    publisher.add_sink(sink)
    event = _event()

    with caplog.at_level(logging.ERROR):
        await publisher.publish(event)

    assert sink.events == [event]
    assert "Connection event sink _RaisingSink failed for provider jira" in caplog.text


@pytest.mark.asyncio
async def test_sink_order_after_notifier_before_audit() -> None:
    """Order is notifier → sinks → audit."""
    calls: list[str] = []

    class Notifier:
        """Record channel-notifier delivery."""

        channel = "telegram"

        async def notify(self, event: ConnectionEvent, state_payload: dict[str, Any]) -> None:
            """Record notifier delivery."""
            calls.append("notifier")

    class Sink:
        """Record sink delivery."""

        async def deliver(self, event: ConnectionEvent) -> None:
            """Record sink delivery."""
            calls.append("sink")

    class Ledger:
        """Record audit delivery."""

        async def append(self, **kwargs: Any) -> None:
            """Record audit delivery."""
            calls.append("audit")

    registry = ChannelNotifierRegistry()
    registry.register(Notifier())
    publisher = ConnectionEventPublisher(notifiers=registry, audit_ledger=Ledger())  # type: ignore[arg-type]
    publisher.add_sink(Sink())

    await publisher.publish(_event())

    assert calls == ["notifier", "sink", "audit"]


def test_add_sink_idempotent_and_protocol() -> None:
    """Same instance registers once and the recording sink satisfies the Protocol."""
    sink = _RecordingSink()
    publisher = ConnectionEventPublisher()

    publisher.add_sink(sink)
    publisher.add_sink(sink)

    assert len(publisher._sinks) == 1
    assert isinstance(sink, ConnectionEventSink)
