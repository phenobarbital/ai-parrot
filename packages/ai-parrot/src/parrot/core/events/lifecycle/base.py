"""Abstract base class for all lifecycle events.

FEAT-176 — Lifecycle Events System.

Every concrete lifecycle event must inherit from LifecycleEvent and be
decorated with ``@dataclass(frozen=True)``. Frozen dataclasses are ~5x
faster to instantiate than Pydantic models (spec §7 Pattern constraints)
and provide immutability guarantees at the Python level.
"""
from abc import ABC
from dataclasses import dataclass, field, fields
from datetime import datetime, timezone
from typing import Any
import json
import uuid

from parrot.core.events.lifecycle.trace import TraceContext


@dataclass(frozen=True)
class LifecycleEvent(ABC):
    """Read-only base class for every lifecycle event.

    Subclasses MUST be ``@dataclass(frozen=True)``. Attempts to mutate
    instances raise ``FrozenInstanceError``.

    All fields must be JSON-serializable (str, int, float, bool, None,
    list, dict). Non-serializable values (e.g., live database connections)
    must be excluded or referenced by ID — ``to_dict()`` enforces this
    via a strict ``json.dumps`` validation pass.

    Attributes:
        trace_context: W3C Trace Context for distributed trace identity.
            Required for every event — no default (callers must supply).
        event_id: Auto-generated UUID4 string uniquely identifying this
            event instance.
        timestamp: UTC datetime of event creation.
        source_type: String tag for the emitter type (``"agent"``,
            ``"client"``, ``"tool"``).
        source_name: Name of the specific emitter (agent name, client
            name, tool name).
    """

    trace_context: TraceContext
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    source_type: str = ""    # "agent" | "client" | "tool"
    source_name: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict with strict validation.

        Converts special types:
        - ``TraceContext`` → ``dict`` via ``.to_dict()``.
        - ``datetime`` → ISO 8601 string via ``.isoformat()``.
        - ``tuple`` → ``list`` (for JSON round-trip cleanliness).

        Appends ``"event_class": type(self).__name__`` to the output
        to support cross-process deserialization hints.

        Returns:
            A dict where every value is JSON-serializable.

        Raises:
            TypeError: If any field value is not JSON-serializable,
                with a message identifying the offending field name.

        Example:
            >>> import json
            >>> evt = _DummyEvent(trace_context=TraceContext.new_root())
            >>> json.dumps(evt.to_dict())  # does not raise
        """
        out: dict[str, Any] = {}
        for f in fields(self):
            value = getattr(self, f.name)
            if isinstance(value, TraceContext):
                value = value.to_dict()
            elif isinstance(value, datetime):
                value = value.isoformat()
            elif isinstance(value, tuple):
                value = list(value)
            out[f.name] = value

        # Deserialization hint — the concrete class name for cross-process use
        out["event_class"] = type(self).__name__

        # Strict JSON validation — catch non-serializable values early
        try:
            json.dumps(out)
        except TypeError as exc:
            raise TypeError(
                f"{type(self).__name__}.to_dict() produced a "
                f"non-JSON-serializable value: {exc}"
            ) from exc

        return out
