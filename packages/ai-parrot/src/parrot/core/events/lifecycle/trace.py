"""W3C Trace Context dataclass for lifecycle event propagation.

FEAT-176 — Lifecycle Events System.

This module implements the W3C Trace Context specification
(https://www.w3.org/TR/trace-context/) for distributed tracing across
agent, client, tool, and sub-agent (A2A) boundaries.
"""
from dataclasses import dataclass
from typing import Optional
import secrets


@dataclass(frozen=True)
class TraceContext:
    """W3C Trace Context for OpenTelemetry-compatible distributed tracing.

    Carries trace identity across agent → client → tool → sub-agent (A2A)
    boundaries. All fields are immutable (frozen=True); mutation raises
    FrozenInstanceError.

    Attributes:
        trace_id: 32 hex chars (16 bytes) uniquely identifying the trace.
        span_id: 16 hex chars (8 bytes) identifying this span.
        trace_flags: Bit field. Bit 0 = sampled (default 1 = sampled).
        trace_state: Vendor extension string (W3C tracestate header value).
        parent_span_id: span_id of the parent span, or None for root spans.

    Example:
        >>> root = TraceContext.new_root()
        >>> child = root.child()
        >>> child.trace_id == root.trace_id
        True
        >>> child.parent_span_id == root.span_id
        True
    """

    trace_id: str                        # 32 hex chars (16 bytes)
    span_id: str                         # 16 hex chars (8 bytes)
    trace_flags: int = 1                 # bit 0 = sampled; default = sampled
    trace_state: str = ""               # vendor extension list
    parent_span_id: Optional[str] = None  # for span tree reconstruction

    @classmethod
    def new_root(cls) -> "TraceContext":
        """Create a new root TraceContext (no parent).

        Generates cryptographically random trace_id and span_id.
        Sets trace_flags=1 (sampled by default).

        Returns:
            A new root TraceContext instance.
        """
        return cls(
            trace_id=secrets.token_hex(16),   # 32 hex chars
            span_id=secrets.token_hex(8),      # 16 hex chars
            trace_flags=1,                     # sampled=true by default
            trace_state="",
            parent_span_id=None,
        )

    def child(self) -> "TraceContext":
        """Return a new child context derived from this span.

        The child shares the same trace_id, trace_flags, and trace_state.
        A fresh span_id is generated, and parent_span_id is set to this
        context's span_id.

        Returns:
            A new TraceContext representing a child span.

        Example:
            >>> root = TraceContext.new_root()
            >>> child = root.child()
            >>> child.trace_id == root.trace_id
            True
            >>> child.span_id != root.span_id
            True
            >>> child.parent_span_id == root.span_id
            True
        """
        return TraceContext(
            trace_id=self.trace_id,
            span_id=secrets.token_hex(8),     # fresh span_id
            trace_flags=self.trace_flags,
            trace_state=self.trace_state,
            parent_span_id=self.span_id,       # wire to this span
        )

    @classmethod
    def from_traceparent_header(cls, header: str) -> "TraceContext":
        """Parse a W3C traceparent header string into a TraceContext.

        Format: ``00-<trace_id:32hex>-<span_id:16hex>-<trace_flags:2hex>``

        Args:
            header: The traceparent header value to parse.

        Returns:
            A TraceContext constructed from the header fields.

        Raises:
            ValueError: If the header is not a valid traceparent header
                (wrong version, wrong field lengths, non-hex characters,
                or malformed structure).

        Example:
            >>> ctx = TraceContext.new_root()
            >>> restored = TraceContext.from_traceparent_header(ctx.to_traceparent_header())
            >>> restored.trace_id == ctx.trace_id
            True
        """
        if not header:
            raise ValueError(f"Invalid traceparent header: empty string")

        parts = header.split("-")
        if len(parts) != 4:
            raise ValueError(
                f"Invalid traceparent header {header!r}: "
                f"expected 4 dash-separated fields, got {len(parts)}"
            )

        version, trace_id, span_id, flags_hex = parts

        # Version must be "00"
        if version != "00":
            raise ValueError(
                f"Invalid traceparent header {header!r}: "
                f"unsupported version {version!r} (only '00' is supported)"
            )

        # Validate trace_id: exactly 32 lowercase hex chars
        if len(trace_id) != 32 or not _is_hex(trace_id):
            raise ValueError(
                f"Invalid traceparent header {header!r}: "
                f"trace_id must be 32 lowercase hex chars, got {trace_id!r}"
            )

        # Validate span_id: exactly 16 lowercase hex chars
        if len(span_id) != 16 or not _is_hex(span_id):
            raise ValueError(
                f"Invalid traceparent header {header!r}: "
                f"span_id must be 16 lowercase hex chars, got {span_id!r}"
            )

        # Validate flags: exactly 2 lowercase hex chars
        if len(flags_hex) != 2 or not _is_hex(flags_hex):
            raise ValueError(
                f"Invalid traceparent header {header!r}: "
                f"trace-flags must be 2 lowercase hex chars, got {flags_hex!r}"
            )

        return cls(
            trace_id=trace_id,
            span_id=span_id,
            trace_flags=int(flags_hex, 16),
            trace_state="",
            parent_span_id=None,
        )

    def to_traceparent_header(self) -> str:
        """Serialize to a W3C traceparent header string.

        Format: ``00-<trace_id>-<span_id>-<trace_flags:02x>``

        Returns:
            A valid traceparent header string.

        Example:
            >>> ctx = TraceContext.new_root()
            >>> header = ctx.to_traceparent_header()
            >>> header.startswith("00-")
            True
        """
        return f"00-{self.trace_id}-{self.span_id}-{self.trace_flags:02x}"

    def to_dict(self) -> dict:
        """Serialize all fields to a JSON-compatible dict.

        Returns:
            A dict containing trace_id, span_id, trace_flags, trace_state,
            and parent_span_id. All values are JSON-serializable primitives.

        Example:
            >>> import json
            >>> ctx = TraceContext.new_root()
            >>> json.dumps(ctx.to_dict())  # does not raise
        """
        return {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "trace_flags": self.trace_flags,
            "trace_state": self.trace_state,
            "parent_span_id": self.parent_span_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TraceContext":
        """Reconstruct a TraceContext from a dict (e.g., from ``to_dict()``).

        Args:
            data: Dict with keys: trace_id, span_id, trace_flags,
                trace_state, parent_span_id.

        Returns:
            A TraceContext instance with the dict's field values.
        """
        return cls(
            trace_id=data["trace_id"],
            span_id=data["span_id"],
            trace_flags=data.get("trace_flags", 1),
            trace_state=data.get("trace_state", ""),
            parent_span_id=data.get("parent_span_id"),
        )


def _is_hex(s: str) -> bool:
    """Return True if s contains only lowercase hexadecimal characters."""
    return all(c in "0123456789abcdef" for c in s)
