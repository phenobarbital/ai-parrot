"""Converters from legacy event shapes to :class:`EventEnvelope` (FEAT-310).

Three legacy shapes exist in ai-parrot:

- ``parrot.core.events.evb.Event`` — mutable dataclass, NAIVE
  ``datetime.now()`` timestamps.
- ``LifecycleEvent`` (FEAT-176) — frozen dataclass, tz-aware UTC; converted
  from its **dict form** (``to_dict()`` output) to avoid importing the
  lifecycle ABC into the bus package.
- ``parrot.core.hooks.models.HookEvent`` — Pydantic model, NAIVE
  ``datetime.now()`` timestamps.

Naive timestamps from legacy sources are COERCED to UTC here (documented
behaviour) — only direct :class:`EventEnvelope` construction rejects naive
datetimes.
"""
from datetime import datetime, timezone
from typing import Any
import uuid

from parrot.core.events.evb import Event, EventPriority
from parrot.core.hooks.models import HookEvent

from parrot.core.events.bus.envelope import EventEnvelope, Severity


def _ensure_aware_utc(ts: datetime) -> datetime:
    """Coerce a possibly-naive datetime to a tz-aware UTC datetime.

    Args:
        ts: Timestamp from a legacy source (may be naive).

    Returns:
        The same instant tz-aware; naive input is assumed to be UTC.
    """
    if ts.tzinfo is None or ts.tzinfo.utcoffset(ts) is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts


def from_legacy_event(
    event: Event,
    *,
    severity: Severity = Severity.INFO,
) -> EventEnvelope:
    """Convert a legacy ``evb.Event`` to an :class:`EventEnvelope`.

    The legacy ``event_type`` becomes the envelope ``topic``; the naive
    ``datetime.now()`` timestamp is coerced to UTC.

    Args:
        event: Legacy mutable event instance.
        severity: Severity to stamp on the envelope (legacy events carry
            none; defaults to ``INFO``).

    Returns:
        The equivalent frozen envelope.
    """
    return EventEnvelope(
        topic=event.event_type,
        payload=event.payload,
        event_id=event.event_id,
        timestamp=_ensure_aware_utc(event.timestamp),
        source=event.source,
        severity=severity,
        priority=event.priority,
        correlation_id=event.correlation_id,
        metadata=dict(event.metadata),
    )


def from_lifecycle_dict(
    data: dict[str, Any],
    *,
    severity: Severity = Severity.INFO,
) -> EventEnvelope:
    """Convert a ``LifecycleEvent.to_dict()`` payload to an envelope.

    The lifecycle dict contains ``event_class`` (deserialization hint),
    ``trace_context`` (dict form), ``event_id``, ISO ``timestamp``,
    ``source_type`` and ``source_name``. The topic is derived as
    ``lifecycle.<event_class>``; the full dict is preserved as payload.

    Args:
        data: Output of ``LifecycleEvent.to_dict()``.
        severity: Severity to stamp on the envelope (defaults to ``INFO``).

    Returns:
        The equivalent frozen envelope.
    """
    event_class = data.get("event_class", "unknown")
    raw_ts = data.get("timestamp")
    if isinstance(raw_ts, str):
        ts = _ensure_aware_utc(datetime.fromisoformat(raw_ts))
    elif isinstance(raw_ts, datetime):
        ts = _ensure_aware_utc(raw_ts)
    else:
        ts = datetime.now(timezone.utc)

    source_type = data.get("source_type") or ""
    source_name = data.get("source_name") or ""
    source = ":".join(p for p in (source_type, source_name) if p) or None

    payload = {
        k: v
        for k, v in data.items()
        if k not in ("event_id", "timestamp", "trace_context")
    }

    return EventEnvelope(
        topic=f"lifecycle.{event_class}",
        payload=payload,
        event_id=data.get("event_id", str(uuid.uuid4())),
        timestamp=ts,
        source=source,
        severity=severity,
        priority=EventPriority.NORMAL,
        trace_context=data.get("trace_context"),
        metadata={"event_class": event_class},
    )


def from_hook_event(
    event: HookEvent,
    *,
    severity: Severity = Severity.INFO,
) -> EventEnvelope:
    """Convert a ``HookEvent`` (Pydantic) to an :class:`EventEnvelope`.

    Topic follows the hook-routing convention
    ``hooks.<hook_type>.<event_type>`` (same shape the existing
    ``HookManager.set_event_bus`` dual-emit uses). The naive
    ``datetime.now()`` timestamp is coerced to UTC.

    Args:
        event: Hook event emitted by any ingestion hook.
        severity: Severity to stamp on the envelope (defaults to ``INFO``).

    Returns:
        The equivalent frozen envelope.
    """
    metadata: dict[str, Any] = dict(event.metadata)
    metadata.setdefault("hook_id", event.hook_id)
    if event.target_type is not None:
        metadata.setdefault("target_type", event.target_type)
    if event.target_id is not None:
        metadata.setdefault("target_id", event.target_id)
    if event.task is not None:
        metadata.setdefault("task", event.task)

    return EventEnvelope(
        topic=f"hooks.{event.hook_type.value}.{event.event_type}",
        payload=event.payload,
        timestamp=_ensure_aware_utc(event.timestamp),
        source=event.hook_id,
        severity=severity,
        priority=EventPriority.NORMAL,
        metadata=metadata,
    )
