"""Unified EventBus v2 package (FEAT-310).

Exposes the core event contract: the :class:`Severity` enum, the frozen
:class:`EventEnvelope` dataclass, and the Pydantic
:class:`IngressEnvelope` boundary model.
"""
from parrot.core.events.bus.envelope import EventEnvelope, Severity
from parrot.core.events.bus.ingress_models import IngressEnvelope

__all__ = (
    "EventEnvelope",
    "IngressEnvelope",
    "Severity",
)
