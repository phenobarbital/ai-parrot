"""Unified EventBus v2 package (FEAT-310).

Exposes the core event contract — the :class:`Severity` enum, the frozen
:class:`EventEnvelope` dataclass, the Pydantic :class:`IngressEnvelope`
boundary model — and the :class:`BusCore` queued dispatcher.
"""
from parrot.core.events.bus.envelope import EventEnvelope, Severity
from parrot.core.events.bus.ingress_models import IngressEnvelope
from parrot.core.events.bus.core import (
    BackpressureError,
    BusClosedError,
    BusCore,
)
from parrot.core.events.bus.dlq import DLQHandler

__all__ = (
    "BackpressureError",
    "BusClosedError",
    "BusCore",
    "DLQHandler",
    "EventEnvelope",
    "IngressEnvelope",
    "Severity",
)
