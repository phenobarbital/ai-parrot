"""Latency budget router + per-codec circuit breaker (G7, G9).

Decides, from a cheap size estimate taken BEFORE compressing, whether a
codec call runs inline, is offloaded to an executor (meaningful only when
the Rust extension releases the GIL via ``py.allow_threads()``), or is
skipped entirely (passthrough). A per-codec :class:`CircuitBreaker`
self-degrades a sustainedly over-budget codec to passthrough.

Without the Rust extension, ``run_in_executor`` buys no real parallelism —
the GIL is still held, so offloading is theater. Sending a fat payload
uncompressed beats stalling the event loop (G9): that is why the
"over threshold, no Rust" route is ``PASSTHROUGH``, not ``EXECUTOR``.

Default calibration (TASK-1959, 2026-07-28): the spec's original defaults
(``inline_budget_ms=1.0``, ``minimal_budget_ms=0.3``, ``row_threshold=5000``)
were explicit **proposals pending measurement** (spec Sec 3 Module 5:
"All values configurable; a benchmark task calibrates them against real
payloads"). Measured against pure-Python codecs (no Rust extension) on a
500-row x 12-col payload (Intel i7-9850H @ 2.60GHz, Python 3.11.15):
``json_compact`` MINIMAL p99 ~= 4.6ms, ``columnar`` NORMAL p99 ~= 2.8ms —
both well above the original budgets. The defaults below reflect that
measurement; see ``tests/tools/compression/test_benchmarks.py`` (opt-in,
``PARROT_RUN_BENCHMARKS=1``) and TASK-1959's Completion Note for the full
table and reasoning. ``executor_budget_ms`` is unchanged (15.0) — no Rust
extension exists yet to measure the off-loop path against (TASK-1955);
recalibrate once it lands.
"""
import logging
import sys
import threading
import time
from enum import Enum
from typing import Any, Callable, Optional

from parrot._imports import lazy_import

from .levels import FilterLevel

logger = logging.getLogger(__name__)


class Route(str, Enum):
    """Where a codec call should run, decided BEFORE compressing."""

    INLINE = "inline"
    """Run synchronously on the event loop, within a low-single-digit-
    millisecond budget (see :class:`BudgetRouter`'s `inline_budget_ms` /
    `minimal_budget_ms`, calibrated against measured pure-Python codec
    latency — TASK-1959)."""

    EXECUTOR = "executor"
    """Offload to `run_in_executor`; only meaningful with the Rust
    extension's `allow_threads()` GIL release."""

    PASSTHROUGH = "passthrough"
    """Skip compression entirely; return the original payload unchanged."""


def estimate_size(payload: Any) -> tuple[int, int]:
    """Cheap ``(bytes, rows)`` estimate of ``payload``'s size.

    Deliberately does NOT fully serialize or fully walk a large payload —
    doing so to decide whether to compress it would defeat the purpose. For
    lists, only the first element is sampled and its size multiplied by the
    row count. An over-estimate is safe (it only ever routes to a *more*
    conservative decision); an under-estimate is not, so this function
    favors over-estimating.

    QueryResult-shaped dicts (e.g. ``{"driver": ..., "rows": [...],
    "row_count": ...}`` — this feature's flagship use case, see
    ``columnar.py``'s ``_locate_rows()``) carry the bulk of their size in a
    single list-valued field. Those are sampled the SAME cheap way as a
    bare list: the dominant list's first element, multiplied by its length,
    plus a full (but normally tiny) walk of the remaining "shell" fields.
    Only a dict with no such dominant list falls back to a full recursive
    walk (code-review fix — previously ALL dict payloads, including
    QueryResult-shaped ones, took the expensive full-walk path).

    Args:
        payload: The unwrapped tool result to estimate.

    Returns:
        A ``(bytes, rows)`` tuple. ``rows`` is ``0`` for non-list payloads
        with no dominant list-valued field.
    """
    if isinstance(payload, list):
        n_rows = len(payload)
        if n_rows == 0:
            return 0, 0
        sample_bytes = _rough_bytes(payload[0])
        return sample_bytes * n_rows, n_rows
    if isinstance(payload, dict):
        dominant_key, dominant_list = _find_dominant_list(payload)
        if dominant_list is not None:
            shell_bytes = sum(
                _rough_bytes(k) + _rough_bytes(v)
                for k, v in payload.items()
                if k != dominant_key
            ) + 2
            n_rows = len(dominant_list)
            if n_rows == 0:
                return shell_bytes, 0
            sample_bytes = _rough_bytes(dominant_list[0])
            return shell_bytes + sample_bytes * n_rows, n_rows
    return _rough_bytes(payload), 0


def _find_dominant_list(payload: dict[Any, Any]) -> tuple[Any, list[Any] | None]:
    """Find the largest list-valued field in a dict payload, if any.

    Mirrors the row-oriented shape ``columnar.py``'s ``_locate_rows()``
    looks for (a dict wrapping a single row-bearing list, e.g. a
    ``QueryResult``'s ``rows`` field) so the size estimate stays cheap for
    exactly the payload shape this feature's flagship codec targets.

    Returns:
        ``(key, list_value)`` for the longest non-empty list-valued field,
        or ``(None, None)`` if the dict has no list-valued field.
    """
    dominant_key: Any = None
    dominant_list: list[Any] | None = None
    for key, value in payload.items():
        if isinstance(value, list) and (
            dominant_list is None or len(value) > len(dominant_list)
        ):
            dominant_key, dominant_list = key, value
    return dominant_key, dominant_list


def _rough_bytes(value: Any) -> int:
    """Recursive-but-cheap byte-size heuristic for a single value."""
    if isinstance(value, (str, bytes)):
        return len(value)
    if isinstance(value, dict):
        return sum(_rough_bytes(k) + _rough_bytes(v) for k, v in value.items()) + 2
    if isinstance(value, (list, tuple)):
        return sum(_rough_bytes(v) for v in value) + 2
    return sys.getsizeof(value)


_rust_available_cache: bool | None = None
_rust_absence_logged = False


def is_rust_available() -> bool:
    """Detect the optional ``parrot_codec`` Rust extension.

    Detected once per process and cached; absence is logged exactly once at
    ``debug`` level, never per call (the common case until the extension is
    compiled, TASK-1955).

    Returns:
        ``True`` if ``parrot_codec`` is importable, ``False`` otherwise.
    """
    global _rust_available_cache, _rust_absence_logged
    if _rust_available_cache is not None:
        return _rust_available_cache
    try:
        lazy_import("parrot_codec")
        _rust_available_cache = True
    except ImportError:
        _rust_available_cache = False
        if not _rust_absence_logged:
            # `debug`, not `warning`: the extension is a separate maturin
            # sub-project that never ships in the `ai-parrot` wheel, so its
            # absence is the DEFAULT state, not a misconfiguration. Level
            # matches this function's docstring and docs/tools/compression.md.
            logger.debug(
                "parrot_codec Rust extension not available; large payloads "
                "over the size threshold will pass through uncompressed (G9)."
            )
            _rust_absence_logged = True
    return _rust_available_cache


class _CodecState:
    """Mutable per-codec circuit-breaker state."""

    __slots__ = (
        "window_start",
        "window_calls",
        "consecutive_over",
        "open",
        "cooldown_until",
        "probing",
        "recent_durations",
    )

    def __init__(self, now: float) -> None:
        self.window_start = now
        self.window_calls: list[tuple[float, "Route", "FilterLevel | None"]] = []
        self.consecutive_over = 0
        self.open = False
        self.cooldown_until: float | None = None
        self.probing = False
        self.recent_durations: list[float] = []


class CircuitBreaker:
    """Per-codec rolling-window circuit breaker (G7).

    A codec that sustainedly busts its latency budget self-degrades to
    ``Route.PASSTHROUGH``. Rolling windows close on ``window_calls`` calls
    OR ``window_seconds`` elapsed, whichever comes first. A window with zero
    calls does not advance the consecutive-over-budget count.
    ``consecutive_windows`` consecutive over-budget windows open the
    breaker; after ``cooldown_seconds`` it enters a half-open state that
    allows exactly one probe call through — success re-arms (closes) the
    breaker, failure reopens it and restarts the cooldown.

    The breaker is keyed **per codec**: degrading one codec never affects
    another's routing.
    """

    def __init__(
        self,
        *,
        window_calls: int = 100,
        window_seconds: float = 60.0,
        consecutive_windows: int = 3,
        cooldown_seconds: float = 300.0,
        inline_budget_ms: float = 3.0,
        minimal_budget_ms: float = 5.0,
        executor_budget_ms: float = 15.0,
        time_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        self._window_calls = window_calls
        self._window_seconds = window_seconds
        self._consecutive_windows = consecutive_windows
        self._cooldown_seconds = cooldown_seconds
        self._inline_budget_ms = inline_budget_ms
        self._minimal_budget_ms = minimal_budget_ms
        self._executor_budget_ms = executor_budget_ms
        self._time_fn = time_fn
        self._lock = threading.Lock()
        self._states: dict[str, _CodecState] = {}

    def _state(self, codec_name: str) -> _CodecState:
        state = self._states.get(codec_name)
        if state is None:
            state = _CodecState(self._time_fn())
            self._states[codec_name] = state
        return state

    def _budget_for(self, route: "Route", level: "FilterLevel | None" = None) -> float:
        """Budget (ms) for a call that took ``route`` at ``level``.

        MINIMAL-level calls always route INLINE (see ``BudgetRouter.route``)
        but are judged against ``minimal_budget_ms``, not the coarser
        ``inline_budget_ms`` — the two were calibrated against different
        measured p99s (TASK-1959: ``json_compact`` MINIMAL ~4.6ms vs.
        ``columnar`` NORMAL ~2.8ms). Previously ``minimal_budget_ms`` was
        accepted as a constructor kwarg but never consulted anywhere
        (code-review fix).
        """
        if route is Route.EXECUTOR:
            return self._executor_budget_ms
        if level is FilterLevel.MINIMAL:
            return self._minimal_budget_ms
        return self._inline_budget_ms

    def is_open(self, codec_name: str) -> bool:
        """Return ``True`` if the breaker currently blocks calls for
        ``codec_name`` (fully open, cooldown not yet elapsed, OR a probe is
        already in flight).

        When the cooldown has elapsed, transitions the breaker to
        half-open (allows exactly one probe call) and returns ``False``.
        Also lazily expires a stale, zero-call window purely on elapsed
        time (a window is only ever advanced/closed on a `record()` call
        otherwise, which would never observe a truly empty window).
        """
        with self._lock:
            state = self._state(codec_name)
            now = self._time_fn()
            if not state.open:
                self._expire_if_stale(codec_name, state, now)
                return False
            if state.probing:
                # A probe call is already in flight and hasn't resolved via
                # `record()` yet — block any OTHER concurrent caller from
                # also being treated as "the" probe (code-review fix: this
                # check previously did not exist, so two callers landing in
                # the same post-cooldown window could both slip through).
                return True
            if state.cooldown_until is not None and now >= state.cooldown_until:
                state.probing = True
                return False
            return True

    def record(
        self,
        codec_name: str,
        duration_ms: float,
        route: "Route",
        level: "FilterLevel | None" = None,
    ) -> None:
        """Feed a completed call's duration into the breaker.

        Args:
            codec_name: Name of the codec that ran.
            duration_ms: Wall-clock duration of the call, in milliseconds.
            route: The :class:`Route` the call actually took.
            level: The effective :class:`FilterLevel` for this call, used
                to pick the right budget (see :meth:`_budget_for`).
        """
        with self._lock:
            state = self._state(codec_name)
            now = self._time_fn()

            state.recent_durations.append(duration_ms)
            if len(state.recent_durations) > 1000:
                state.recent_durations = state.recent_durations[-1000:]

            if state.probing:
                self._resolve_probe(codec_name, state, duration_ms, route, level, now)
                return

            # Close out a stale window (possibly empty) before starting to
            # accumulate this call into a fresh one.
            self._expire_if_stale(codec_name, state, now)

            state.window_calls.append((duration_ms, route, level))
            if len(state.window_calls) >= self._window_calls:
                self._close_window(codec_name, state, now)

    def _expire_if_stale(self, codec_name: str, state: _CodecState, now: float) -> None:
        """Close the current window purely on elapsed time, even with zero
        calls accumulated. A zero-call window is a no-op for the
        consecutive-over-budget count (see `_close_window`)."""
        if (now - state.window_start) >= self._window_seconds:
            self._close_window(codec_name, state, now)

    def _resolve_probe(
        self,
        codec_name: str,
        state: _CodecState,
        duration_ms: float,
        route: "Route",
        level: "FilterLevel | None",
        now: float,
    ) -> None:
        state.probing = False
        if duration_ms > self._budget_for(route, level):
            state.cooldown_until = now + self._cooldown_seconds
            logger.warning(
                "Circuit breaker probe for codec '%s' failed (%.3fms over "
                "budget); reopening, cooldown restarted.",
                codec_name, duration_ms,
            )
            return
        state.open = False
        state.consecutive_over = 0
        state.cooldown_until = None
        state.window_calls = []
        state.window_start = now
        logger.info(
            "Circuit breaker probe for codec '%s' succeeded; re-armed.",
            codec_name,
        )

    def _close_window(self, codec_name: str, state: _CodecState, now: float) -> None:
        calls = state.window_calls
        state.window_calls = []
        state.window_start = now
        if not calls:
            # An empty window is not "over budget" — does not advance the
            # consecutive count.
            return

        over_count = sum(
            1
            for duration_ms, route, level in calls
            if duration_ms > self._budget_for(route, level)
        )
        over_budget = over_count > len(calls) / 2

        state.consecutive_over = state.consecutive_over + 1 if over_budget else 0

        if state.consecutive_over >= self._consecutive_windows and not state.open:
            state.open = True
            state.cooldown_until = now + self._cooldown_seconds
            logger.warning(
                "Circuit breaker opened for codec '%s' after %d consecutive "
                "over-budget windows; degrading to passthrough for %.0fs.",
                codec_name, state.consecutive_over, self._cooldown_seconds,
            )

    def p99(self, codec_name: str) -> float | None:
        """Rolling p99 duration (ms) for ``codec_name``, or ``None`` if no
        calls have been recorded yet. Exposed for the savings report
        (TASK-1957)."""
        with self._lock:
            state = self._states.get(codec_name)
            if state is None or not state.recent_durations:
                return None
            return _percentile(state.recent_durations, 99)


def _percentile(values: list[float], pct: float) -> float:
    """Nearest-rank percentile, deterministic given the same input."""
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(round(pct / 100 * (len(ordered) - 1))))
    return ordered[idx]


class BudgetRouter:
    """Pre-compression latency-budget router + circuit breaker (G7, G9).

    Combines the route decision table from spec Sec 3 Module 5 with a
    per-codec :class:`CircuitBreaker`. All thresholds are configurable via
    constructor kwargs; defaults match the spec.
    """

    def __init__(
        self,
        *,
        size_threshold_bytes: int = 256 * 1024,
        row_threshold: int = 1500,
        window_calls: int = 100,
        window_seconds: float = 60.0,
        consecutive_windows: int = 3,
        cooldown_seconds: float = 300.0,
        inline_budget_ms: float = 3.0,
        minimal_budget_ms: float = 5.0,
        executor_budget_ms: float = 15.0,
        time_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        self.size_threshold_bytes = size_threshold_bytes
        self.row_threshold = row_threshold
        self.inline_budget_ms = inline_budget_ms
        self.minimal_budget_ms = minimal_budget_ms
        self.executor_budget_ms = executor_budget_ms
        self._breaker = CircuitBreaker(
            window_calls=window_calls,
            window_seconds=window_seconds,
            consecutive_windows=consecutive_windows,
            cooldown_seconds=cooldown_seconds,
            inline_budget_ms=inline_budget_ms,
            minimal_budget_ms=minimal_budget_ms,
            executor_budget_ms=executor_budget_ms,
            time_fn=time_fn,
        )

    def route(
        self,
        payload: Any,
        *,
        level: FilterLevel,
        codec_name: str,
        rust_available: bool,
    ) -> Route:
        """Decide where a codec call should run, from a size estimate taken
        BEFORE compressing. The codec itself is never constructed or
        invoked to make this decision — synchronous, no I/O, no `await`.

        Args:
            payload: The unwrapped tool result that would be compressed.
            level: Effective :class:`FilterLevel` for this call.
            codec_name: Name of the codec that would run (breaker key).
            rust_available: Whether the ``parrot_codec`` Rust extension is
                available (see :func:`is_rust_available`).

        Returns:
            The :class:`Route` to take.
        """
        if self._breaker.is_open(codec_name):
            return Route.PASSTHROUGH
        if level is FilterLevel.NONE:
            return Route.PASSTHROUGH
        if level is FilterLevel.MINIMAL:
            return Route.INLINE
        n_bytes, n_rows = estimate_size(payload)
        if n_bytes < self.size_threshold_bytes and n_rows < self.row_threshold:
            return Route.INLINE
        return Route.EXECUTOR if rust_available else Route.PASSTHROUGH

    def record(
        self,
        codec_name: str,
        duration_ms: float,
        route: Route,
        level: Optional[FilterLevel] = None,
    ) -> None:
        """Feed a completed call's duration into the circuit breaker.

        Args:
            codec_name: Name of the codec that ran.
            duration_ms: Wall-clock duration of the call, in milliseconds.
            route: The :class:`Route` the call actually took.
            level: The effective :class:`FilterLevel` for this call. Needed
                to judge MINIMAL-level (always-INLINE) calls against
                ``minimal_budget_ms`` instead of the coarser
                ``inline_budget_ms`` (code-review fix). ``None`` preserves
                the pre-fix behavior (judged as a generic inline call).
        """
        self._breaker.record(codec_name, duration_ms, route, level)

    def p99(self, codec_name: str) -> float | None:
        """Rolling p99 duration (ms) for ``codec_name``. See
        :meth:`CircuitBreaker.p99`; exposed for TASK-1957's savings report."""
        return self._breaker.p99(codec_name)
