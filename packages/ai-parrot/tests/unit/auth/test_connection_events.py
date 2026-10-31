"""Tests for connection event notification, auditing, and fan-out."""

import logging
import time
from typing import Any, Dict, Iterator

import pytest

from parrot.auth.oauth2.events import (
    ChannelNotifierRegistry,
    ConnectionEvent,
    ConnectionEventPublisher,
    setup_connection_fanout,
)


@pytest.fixture
def notifier_registry() -> Iterator[ChannelNotifierRegistry]:
    """Provide an isolated notifier registry."""
    ChannelNotifierRegistry._reset()
    yield ChannelNotifierRegistry()
    ChannelNotifierRegistry._reset()


def _event(**kwargs: Any) -> ConnectionEvent:
    """Build a representative token-free connection event."""
    return ConnectionEvent(
        kind="connection.completed",
        user_id="1042",
        provider="jira",
        account_id="acc-1",
        channel="telegram",
        occurred_at=time.time(),
        **kwargs,
    )


@pytest.mark.asyncio
async def test_event_publisher_order_and_isolation(
    notifier_registry: ChannelNotifierRegistry,
) -> None:
    """A notifier failure is isolated and later stages preserve their order."""
    calls: list[str] = []

    class Boom:
        channel = "telegram"

        async def notify(self, event: ConnectionEvent, state: Dict[str, Any]) -> None:
            calls.append("notifier")
            raise RuntimeError("down")

    class Ledger:
        async def append(self, **kwargs: Any) -> None:
            calls.append("audit")
            assert kwargs["credential_material"] == "connection.completed:acc-1"
            assert "token" not in kwargs["credential_material"]

    class Bus:
        async def emit(self, kind: str, payload: Dict[str, Any]) -> None:
            calls.append("bus")
            assert kind == "connection.completed"
            assert "access_token" not in payload
            assert "refresh_token" not in payload

    notifier_registry.register(Boom())
    publisher = ConnectionEventPublisher(notifiers=notifier_registry, audit_ledger=Ledger(), bus=Bus())  # type: ignore[arg-type]

    await publisher.publish(_event(), {"return_origin": "chat"})

    assert calls == ["notifier", "audit", "bus"]


@pytest.mark.asyncio
async def test_missing_notifier_warns_and_continues(
    notifier_registry: ChannelNotifierRegistry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Missing in-process delivery still permits audit and bus fan-out."""
    calls: list[str] = []

    class Ledger:
        async def append(self, **kwargs: Any) -> None:
            calls.append("audit")

    class Bus:
        async def emit(self, kind: str, payload: Dict[str, Any]) -> None:
            calls.append("bus")

    publisher = ConnectionEventPublisher(notifiers=notifier_registry, audit_ledger=Ledger(), bus=Bus())  # type: ignore[arg-type]

    with caplog.at_level(logging.WARNING):
        await publisher.publish(_event())

    assert calls == ["audit", "bus"]
    assert "No connection notifier registered for channel telegram" in caplog.text


def test_setup_connection_fanout_requires_publish_only_streams() -> None:
    """Fan-out rejects any bus that is not Streams and publish-only."""

    class Bad:
        transport = "pubsub"
        publish_only = False

    with pytest.raises(RuntimeError, match="transport='streams'"):
        setup_connection_fanout(Bad())


@pytest.mark.asyncio
async def test_setup_and_shutdown_connection_fanout() -> None:
    """A valid bus can be attached and is detached even when close fails."""

    class Bus:
        transport = "streams"
        publish_only = True

        async def close(self) -> None:
            raise RuntimeError("close failed")

    bus = Bus()
    publisher = ConnectionEventPublisher()
    setup_connection_fanout(bus, publisher)

    assert publisher._bus is bus
    await publisher.shutdown()
    assert publisher._bus is None
