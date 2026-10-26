"""Capability-call lifecycle event (FEAT-746 M12).

Emitted on both sides of a Squawk call under the caller's trace_id.
"""
from dataclasses import dataclass

from navigator_eventbus.lifecycle.base import LifecycleEvent

from parrot.observability.recorders.models import CapabilityCallRecord


@dataclass(frozen=True)
class CapabilityCallEvent(LifecycleEvent):
    """Carries one CapabilityCallRecord.

    Forwarded to the bus by the FEAT-710 fan-out when subscribed with ``forward_to_bus=True``.
    """

    # LifecycleEvent declares defaulted fields, so a default is required; emitters always set it.
    record: CapabilityCallRecord = None  # type: ignore[assignment]
