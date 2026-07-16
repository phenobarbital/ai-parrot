"""Pydantic boundary model for external event ingress (FEAT-310).

Pydantic validation is used ONLY at ingress boundaries (WebSocket, gRPC,
HTTP adapters). Validated external input is converted to the frozen
:class:`~parrot.core.events.bus.envelope.EventEnvelope` dataclass via
:meth:`IngressEnvelope.to_envelope` before entering the bus hot path.
"""
from datetime import datetime, timezone
from typing import Any, Optional
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator

from parrot.core.events.evb import EventPriority
from parrot.core.events.bus.envelope import EventEnvelope, Severity


class IngressEnvelope(BaseModel):
    """Strict validation model for externally-submitted events.

    Rejects unknown fields (``extra="forbid"``) and is immutable
    (``frozen=True``). Naive timestamps from external clients are coerced
    to UTC during validation, so :meth:`to_envelope` always produces a
    tz-aware envelope.

    Attributes:
        topic: Hierarchical topic string.
        payload: JSON-safe event payload.
        event_id: UUID4 string (generated when absent).
        timestamp: Event creation time (naive input coerced to UTC).
        source: Optional emitter identifier.
        severity: Filtering/alerting severity (default ``INFO``).
        priority: Dispatch scheduling priority (default ``NORMAL``).
        correlation_id: Optional chain-tracking identifier.
        trace_context: Optional trace-context dict.
        metadata: Free-form JSON-safe metadata.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    topic: str = Field(..., min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    source: Optional[str] = None
    severity: Severity = Severity.INFO
    priority: EventPriority = EventPriority.NORMAL
    correlation_id: Optional[str] = None
    trace_context: Optional[dict[str, Any]] = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("timestamp")
    @classmethod
    def _coerce_naive_to_utc(cls, value: datetime) -> datetime:
        """Coerce naive external timestamps to UTC.

        Args:
            value: Parsed timestamp from external input.

        Returns:
            A timezone-aware datetime (UTC assumed for naive input).
        """
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            return value.replace(tzinfo=timezone.utc)
        return value

    def to_envelope(self) -> EventEnvelope:
        """Convert the validated boundary model to the core envelope.

        Returns:
            The equivalent frozen :class:`EventEnvelope`.
        """
        return EventEnvelope(
            topic=self.topic,
            payload=self.payload,
            event_id=self.event_id,
            timestamp=self.timestamp,
            source=self.source,
            severity=self.severity,
            priority=self.priority,
            correlation_id=self.correlation_id,
            trace_context=self.trace_context,
            metadata=self.metadata,
        )
