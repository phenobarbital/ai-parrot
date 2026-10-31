"""Connection lifecycle events (FEAT-773 M4): notifier registry + audit + optional bus."""

from __future__ import annotations

import logging
from typing import Any, ClassVar, Dict, List, Literal, Optional, Protocol, runtime_checkable

from pydantic import BaseModel

from parrot.security.audit_ledger import AuditLedger

logger = logging.getLogger(__name__)

ConnectionEventKind = Literal["connection.completed", "connection.revoked", "connection.refresh_failed"]


class ConnectionEvent(BaseModel):
    """A connection state change. Never carries token material."""

    kind: ConnectionEventKind
    user_id: str
    canonical_identity: Optional[str] = None
    tenant_id: Optional[str] = None
    provider: str
    account_id: str = ""
    display_name: str = ""
    channel: str
    occurred_at: float
    reason: Optional[str] = None


@runtime_checkable
class ChannelNotifier(Protocol):
    """Delivers a connection event to the user on one channel (may raise; the publisher logs)."""

    channel: str

    async def notify(self, event: ConnectionEvent, state_payload: Dict[str, Any]) -> None: ...


@runtime_checkable
class ConnectionEventSink(Protocol):
    """Receives every connection event regardless of ``event.channel`` (FEAT-777 M1).

    May raise; the publisher logs the failure and continues with the next stage.
    """

    async def deliver(self, event: ConnectionEvent) -> None: ...


class ChannelNotifierRegistry:
    """Process-wide singleton: one notifier per channel."""

    _instance: ClassVar[Optional["ChannelNotifierRegistry"]] = None
    _notifiers: Dict[str, ChannelNotifier]

    def __new__(cls) -> "ChannelNotifierRegistry":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._notifiers = {}
        return cls._instance

    @classmethod
    def _reset(cls) -> None:
        cls._instance = None

    def register(self, notifier: ChannelNotifier) -> None:
        """Register (or replace) the notifier for ``notifier.channel``."""
        self._notifiers[notifier.channel] = notifier

    def get(self, channel: str) -> Optional[ChannelNotifier]:
        """Return the notifier registered for ``channel``, if any."""
        return self._notifiers.get(channel)

    def all(self) -> List[ChannelNotifier]:
        """Return all registered notifiers in insertion order."""
        return list(self._notifiers.values())


class ConnectionEventPublisher:
    """notifier (load-bearing) → audit ledger → publish-only bus (additive). Never raises."""

    def __init__(
        self,
        *,
        notifiers: Optional[ChannelNotifierRegistry] = None,
        audit_ledger: Optional[AuditLedger] = None,
        bus: Any = None,
    ) -> None:
        self._notifiers = notifiers if notifiers is not None else ChannelNotifierRegistry()
        self._audit = audit_ledger
        self._bus = bus
        self.logger = logger
        self._sinks: List[ConnectionEventSink] = []

    def add_sink(self, sink: ConnectionEventSink) -> None:
        """Register a channel-independent sink, called for every published event.

        Order inside :meth:`publish`: notifier → sinks → audit → bus. Adding the same
        instance twice registers it once.
        """
        if not any(existing_sink is sink for existing_sink in self._sinks):
            self._sinks.append(sink)

    def attach_bus(self, bus: Any) -> None:
        """Attach a validated publish-only Streams bus."""
        _validate_connection_bus(bus)
        self._bus = bus

    async def publish(self, event: ConnectionEvent, state_payload: Optional[Dict[str, Any]] = None) -> None:
        """Deliver ``event``; every stage's failure is logged and swallowed."""
        notifier = self._notifiers.get(event.channel)
        if notifier is None:
            self.logger.warning("No connection notifier registered for channel %s", event.channel)
        else:
            try:
                await notifier.notify(event, state_payload or {})
            except Exception:  # noqa: BLE001 — a notifier must never fail the callback
                self.logger.exception("Connection notifier failed for channel %s", event.channel)

        for sink in list(self._sinks):
            try:
                await sink.deliver(event)
            except Exception:  # noqa: BLE001 — a sink must never fail the callback
                self.logger.exception(
                    "Connection event sink %s failed for provider %s", type(sink).__name__, event.provider
                )

        if self._audit is not None:
            try:
                await self._audit.append(
                    user_id=event.user_id,
                    channel=event.channel,
                    tool="connections",
                    provider=event.provider,
                    credential_material=f"{event.kind}:{event.account_id}",
                )
            except Exception:  # noqa: BLE001 — audit failure must not block completion delivery
                self.logger.exception("Connection event audit failed for provider %s", event.provider)

        if self._bus is not None:
            try:
                await self._bus.emit(event.kind, event.model_dump(mode="json"))
            except Exception:  # noqa: BLE001 — additive fan-out must not fail the callback
                self.logger.exception("Connection event fan-out failed for provider %s", event.provider)

    async def shutdown(self) -> None:
        """Close the attached bus defensively, then detach it."""
        bus = self._bus
        if bus is None:
            return
        try:
            await bus.close()
        except Exception:  # noqa: BLE001 — shutdown remains defensive
            self.logger.debug("Failed to close connection event bus", exc_info=True)
        finally:
            self._bus = None


def _validate_connection_bus(bus: Any) -> None:
    """Require the same publish-only Streams configuration as observability fan-out."""
    from parrot.observability.fanout import _validate_bus

    _validate_bus(bus)


def setup_connection_fanout(bus: Any, publisher: Optional[ConnectionEventPublisher] = None) -> None:
    """Validate ``bus`` and optionally attach it to ``publisher``."""
    _validate_connection_bus(bus)
    if publisher is not None:
        publisher.attach_bus(bus)
