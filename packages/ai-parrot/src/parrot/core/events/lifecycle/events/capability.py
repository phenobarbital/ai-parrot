"""Capability-call lifecycle event (FEAT-746 M12).

Emitted on both sides of a Squawk call under the caller's trace_id.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from navigator_eventbus.lifecycle.base import LifecycleEvent

if TYPE_CHECKING:  # pragma: no cover - import-time only
    # Deferred on purpose (FEAT-725 AC7): importing parrot.observability here
    # would make `import parrot.core.events.lifecycle` drag in the whole
    # observability package and re-arm the circular-import failure.
    from parrot.observability.recorders.models import CapabilityCallRecord


@dataclass(frozen=True)
class CapabilityCallEvent(LifecycleEvent):
    """Carries one CapabilityCallRecord.

    Forwarded to the bus by the FEAT-710 fan-out when subscribed with ``forward_to_bus=True``.
    """

    # LifecycleEvent declares defaulted fields, so a default is required; emitters always set it.
    record: CapabilityCallRecord = None  # type: ignore[assignment]
