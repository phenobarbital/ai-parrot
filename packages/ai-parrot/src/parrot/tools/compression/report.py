"""Compression savings report — the ``rtk gain`` functional equivalent
(spec Sec 3 Module 8).

"Measure, don't assume" (spec Sec 7): ``MINIMAL`` looks like a big byte win,
but BPE tokenizers merge whitespace runs, so the real *token* saving is much
smaller. Without a report nobody would ever find that out. Every saving
travels alongside its cost (milliseconds spent) — a saving that cannot be
checked against its cost is not evaluable.

``CompressionReport`` aggregates :class:`AfterToolCallEvent` instances
in-process (O(1) per event, no event storage) into a per-tool and
per-session breakdown, including below-``min_rows``/skipped "no gain" cases
— knowing which tools never benefit is how the default manifest gets tuned.
"""
import logging
from collections import deque
from typing import Any, Optional

from pydantic import BaseModel, Field

from .budget import _percentile

logger = logging.getLogger(__name__)

_DEFAULT_MAX_RETAINED_DURATIONS = 500

_CAVEAT = (
    "token figures are bytes/4 estimates — percentages reliable, "
    "absolutes approximate (no tokenizer available to the pipeline)"
)


class ToolSavings(BaseModel):
    """Aggregated compression savings for a single tool.

    Attributes:
        tool_name: Name of the tool this breakdown covers.
        calls: Total tool calls observed (compressed AND skipped).
        compressed_calls: Calls where the compression stage actually ran
            (i.e. not skipped) — may include zero-gain outcomes.
        skipped: ``compression_skipped`` reason -> count. Below-``min_rows``
            passthroughs and every other skip reason are recorded here
            rather than dropped.
        bytes_before: Sum of pre-compression sizes, across compressed calls.
        bytes_after: Sum of post-compression sizes, across compressed calls.
        est_tokens_saved: Sum of ``bytes/4``-estimated tokens saved.
        compression_ms_total: Sum of time spent in the compression codec.
        p50_compression_ms: Rolling-window median codec duration.
        p99_compression_ms: Rolling-window p99 codec duration.
    """

    tool_name: str
    calls: int = 0
    compressed_calls: int = 0
    skipped: dict[str, int] = Field(default_factory=dict)
    bytes_before: int = 0
    bytes_after: int = 0
    est_tokens_saved: int = 0
    compression_ms_total: float = 0.0
    p50_compression_ms: float = 0.0
    p99_compression_ms: float = 0.0

    @property
    def pct_saved(self) -> float:
        """Percentage of bytes saved, or ``0.0`` when nothing was
        compressed yet (never divides by zero)."""
        return 0.0 if not self.bytes_before else (
            100.0 * (self.bytes_before - self.bytes_after) / self.bytes_before
        )


class SessionSavings(BaseModel):
    """Session-wide totals, same shape as :class:`ToolSavings` minus the
    per-tool ``skipped``/``tool_name`` fields."""

    calls: int = 0
    compressed_calls: int = 0
    bytes_before: int = 0
    bytes_after: int = 0
    est_tokens_saved: int = 0
    compression_ms_total: float = 0.0

    @property
    def pct_saved(self) -> float:
        """Percentage of bytes saved, or ``0.0`` when nothing was
        compressed yet (never divides by zero)."""
        return 0.0 if not self.bytes_before else (
            100.0 * (self.bytes_before - self.bytes_after) / self.bytes_before
        )


class CompressionSummary(BaseModel):
    """Structured savings report: per-tool breakdown + session total."""

    tools: dict[str, ToolSavings] = Field(default_factory=dict)
    session: SessionSavings = Field(default_factory=SessionSavings)


class CompressionReport:
    """Per-tool/per-session compression savings aggregator.

    Feed it :class:`AfterToolCallEvent` instances via :meth:`handle` (e.g.
    from an event-bus subscription — wiring a live listener onto
    ``ToolManager`` is future work, out of this module's scope). Never
    raises: a malformed event is logged and swallowed, never propagated to
    the caller/event bus.

    Aggregation is O(1) per event (running sums, not stored events). p50/p99
    codec durations use a bounded per-tool rolling window and the same
    nearest-rank percentile function as
    :mod:`parrot.tools.compression.budget`'s ``CircuitBreaker`` — reused
    directly (``_percentile``) rather than duplicated. ``CircuitBreaker``
    itself is NOT reused: it is a routing/degrade state machine coupled to
    the latency-budget router, not a plain aggregator, so wrapping it here
    would pull in unrelated breaker semantics for no benefit.

    Instances hold purely per-instance state (no shared/class-level mutable
    state) — safe for per-session ownership, mirroring how
    ``ToolManager.clone()`` already gives each session its own
    ``BudgetRouter``/``CompressionTee`` (TASK-1952/1953) rather than a
    process-wide singleton.
    """

    def __init__(self, *, max_retained_durations: int = _DEFAULT_MAX_RETAINED_DURATIONS) -> None:
        """Initialize an empty report.

        Args:
            max_retained_durations: Size of the per-tool rolling window of
                recent ``compression_duration_ms`` values used for p50/p99.
        """
        self._tools: dict[str, ToolSavings] = {}
        self._durations: dict[str, deque[float]] = {}
        self._session = SessionSavings()
        self._max_retained = max_retained_durations
        self.logger = logging.getLogger(__name__)

    def handle(self, event: Any, skipped_reason: Optional[str] = None) -> None:
        """Record one tool call's outcome. Never raises.

        Args:
            event: An :class:`AfterToolCallEvent` (duck-typed — any object
                exposing the same attributes works). ``None``/malformed
                input is logged and ignored.
            skipped_reason: The ``compression_skipped`` reason, when
                compression did not run for this call (the event itself
                carries no such field — it lives in ``ToolResult.metadata``,
                so the caller passes it explicitly). ``None`` means
                compression ran (possibly with zero gain).
        """
        try:
            self._handle(event, skipped_reason)
        except Exception as exc:  # noqa: BLE001 — a listener must never break the event bus
            self.logger.warning(
                "CompressionReport failed to record an event: %s", exc, exc_info=True,
            )

    def _handle(self, event: Any, skipped_reason: Optional[str]) -> None:
        if event is None:
            return
        tool_name = getattr(event, "tool_name", None)
        if not tool_name:
            return

        savings = self._tools.get(tool_name)
        if savings is None:
            savings = ToolSavings(tool_name=tool_name)
            self._tools[tool_name] = savings

        savings.calls += 1
        self._session.calls += 1

        if skipped_reason:
            savings.skipped[skipped_reason] = savings.skipped.get(skipped_reason, 0) + 1
            return

        before = int(getattr(event, "result_size_bytes_original", 0) or 0)
        after = int(getattr(event, "result_size_bytes", 0) or 0)
        ms = float(getattr(event, "compression_duration_ms", 0.0) or 0.0)
        tokens = max(0, before - after) // 4

        savings.compressed_calls += 1
        savings.bytes_before += before
        savings.bytes_after += after
        savings.est_tokens_saved += tokens
        savings.compression_ms_total += ms

        self._session.compressed_calls += 1
        self._session.bytes_before += before
        self._session.bytes_after += after
        self._session.est_tokens_saved += tokens
        self._session.compression_ms_total += ms

        durations = self._durations.get(tool_name)
        if durations is None:
            durations = deque(maxlen=self._max_retained)
            self._durations[tool_name] = durations
        durations.append(ms)

    def summary(self) -> CompressionSummary:
        """Build a structured, independent snapshot of the current totals.

        Returns:
            A :class:`CompressionSummary` — mutating it never affects this
            report's internal state.
        """
        tools: dict[str, ToolSavings] = {}
        for name, savings in self._tools.items():
            copy = savings.model_copy(deep=True)
            recent = list(self._durations.get(name, ()))
            copy.p50_compression_ms = _percentile(recent, 50)
            copy.p99_compression_ms = _percentile(recent, 99)
            tools[name] = copy
        return CompressionSummary(
            tools=tools, session=self._session.model_copy(deep=True),
        )

    def render(self) -> str:
        """Render a compact, human-readable text table for logs/CLI.

        Returns:
            A multi-line string, always including the token-estimate
            caveat and milliseconds spent alongside every saving.
        """
        summary = self.summary()
        lines: list[str] = [
            "Compression Savings Report",
            "=" * 27,
            f"({_CAVEAT})",
            f"{'tool':<28} {'calls':>6} {'comp.':>6} {'%saved':>7} "
            f"{'tokens':>8} {'ms total':>9} {'p50 ms':>7} {'p99 ms':>7}",
        ]
        for name in sorted(summary.tools):
            s = summary.tools[name]
            lines.append(
                f"{name:<28} {s.calls:>6} {s.compressed_calls:>6} "
                f"{s.pct_saved:>6.1f}% {s.est_tokens_saved:>8} "
                f"{s.compression_ms_total:>8.2f}ms {s.p50_compression_ms:>6.2f}ms "
                f"{s.p99_compression_ms:>6.2f}ms"
            )
            for reason in sorted(s.skipped):
                lines.append(f"    skipped[{reason}]: {s.skipped[reason]}")

        sess = summary.session
        lines.append("-" * 27)
        lines.append(
            f"SESSION TOTAL: calls={sess.calls} compressed={sess.compressed_calls} "
            f"pct_saved={sess.pct_saved:.1f}% tokens_saved={sess.est_tokens_saved} "
            f"ms_total={sess.compression_ms_total:.2f}ms"
        )
        return "\n".join(lines)
