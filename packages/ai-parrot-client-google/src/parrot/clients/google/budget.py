"""Shared generation budget primitive for the deterministic E2E gate (FEAT-581, M6).

Frozen by the TASK-3519 research spike (``sdd/state/FEAT-581/research/google-budget.md``):
a per-run, in-process guard that the (not-yet-created) live E2E actor and an
optional ``GoogleGenAIClient`` hook use to cap nonstreaming Google generation
calls without any provider SDK access of its own. This module has no
dependency on ``ai-parrot-server`` or the provider SDK — it is a plain
counting/locking primitive.

Call sites this budget is frozen to cover once a client hook is wired
(``client.py``, not modified by this task):

- ``client.py:3401`` initial ``chat.send_message``
- ``client.py:2207`` tool-continuation ``chat.send_message`` (loop body)
- ``client.py:2374`` forced-synthesis ``chat.send_message`` (iteration-cap tail)
- ``client.py:3657`` inline structured-repair ``generate_content``
- ``client.py:1137`` ``_reformat_to_structured`` ``generate_content``
- ``client.py:5537`` ``resume()`` initial ``chat.send_message``

Each wrapper-level retry (parrot's own ``while retry_count < max_retries``
loops) consumes another reservation — a budget exception is non-retryable
and no fallback executes.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

__all__ = ["GenerationBudget", "GenerationBudgetExceeded"]


class GenerationBudgetExceeded(Exception):
    """Non-retryable: raised by :meth:`GenerationBudget.reserve` on exhaustion.

    Lives in ``ai-parrot-client-google``, which does NOT depend on
    ``ai-parrot-server`` (verified in the TASK-3519 research: no
    ``ai-parrot-server`` entry in ``packages/ai-parrot-client-google/pyproject.toml``
    ``dependencies``). It therefore CANNOT subclass
    ``parrot.e2e.errors.E2EBudgetError`` — that class lives in the opposite
    direction package. The live E2E actor (``parrot/e2e/live.py``, M6, not
    created by this task) must catch ``GenerationBudgetExceeded`` by type
    and re-raise/wrap it as ``E2EBudgetError`` at the harness boundary — a
    plain except+re-raise adapter, not a shared exception hierarchy.

    No fallback executes after this error, and no further network call may
    be attempted for the exhausted budget scope.

    Attributes:
        reason_code: Machine-readable reason the reservation was refused —
            one of ``"max_calls"``, ``"deadline"``, ``"request_bytes"`` or
            ``"output_tokens"``. Mirrors the ``reason_code`` shape used by
            ``parrot.e2e.errors.E2EError`` so a catch-and-wrap adapter can
            forward it verbatim.
    """

    def __init__(self, message: str, *, reason_code: Optional[str] = None) -> None:
        """Initialize the exception.

        Args:
            message: Human-readable description of why the reservation failed.
            reason_code: Optional machine-readable reason code (see class docstring).
        """
        super().__init__(message)
        self.reason_code = reason_code


class GenerationBudget:
    """Per-run nonstreaming Google generation budget; reserves before network attempts.

    One instance is meant to be constructed once per E2E run and shared
    across every scenario and every ``GoogleGenAIClient`` instance that
    participates in that run — "the server owns the shared per-run
    counter/lock; sequential live scenarios reuse it and cannot create
    fresh allowances per test" (spec "Live Provider Budget"). Sharing a
    single instance is sufficient to satisfy that requirement: all state
    lives on ``self`` and every mutation happens under ``self._lock``.

    The wall-clock deadline starts at construction time (session start),
    not at the first reservation, matching the spec's "60-second live
    session deadline" framing.

    Exact token billing is intentionally NOT inferred from
    ``request_bytes`` — byte counts only approximate the request-size
    ceiling. Record a provider's actual reported usage via
    :meth:`record_usage_tokens` when available; never present the byte
    ceiling as an exact token count.

    Attributes:
        max_calls: Maximum generation attempts across initial/continuation/
            repair/retry sends.
        max_output_tokens: Output token ceiling; growth on ``MAX_TOKENS``
            must be clamped to this value by the caller before requesting
            a reservation.
        max_request_bytes: Serialized request byte ceiling (rendered
            history + system instruction + tool definitions/results + new
            prompt).
        timeout_s: Maximum wall-clock seconds for the whole live session.
    """

    def __init__(
        self,
        *,
        max_calls: int,
        max_output_tokens: int,
        max_request_bytes: int,
        timeout_s: float,
    ) -> None:
        """Initialize the budget and start its wall-clock deadline.

        Args:
            max_calls: Maximum generation attempts allowed for this run.
            max_output_tokens: Output token ceiling per attempt.
            max_request_bytes: Serialized request byte ceiling per attempt.
            timeout_s: Maximum wall-clock seconds for the whole session.

        Raises:
            ValueError: If any ceiling is not a finite positive value.
        """
        for name, value in (
            ("max_calls", max_calls),
            ("max_output_tokens", max_output_tokens),
            ("max_request_bytes", max_request_bytes),
            ("timeout_s", timeout_s),
        ):
            if not (value > 0) or value in (float("inf"), float("-inf")):
                raise ValueError(f"{name} must be a finite positive value, got {value!r}")

        self.max_calls = max_calls
        self.max_output_tokens = max_output_tokens
        self.max_request_bytes = max_request_bytes
        self.timeout_s = float(timeout_s)

        self.logger = logging.getLogger(__name__)
        self._lock = asyncio.Lock()
        self._start_monotonic = time.monotonic()
        self._calls_used = 0
        self._bytes_used = 0
        self._usage_tokens_used = 0

    @property
    def calls_used(self) -> int:
        """Number of attempts successfully reserved so far (retained after failure)."""
        return self._calls_used

    @property
    def bytes_used(self) -> int:
        """Cumulative ``request_bytes`` across every successful reservation."""
        return self._bytes_used

    @property
    def usage_tokens_used(self) -> int:
        """Cumulative provider-reported token usage recorded via :meth:`record_usage_tokens`."""
        return self._usage_tokens_used

    @property
    def elapsed_s(self) -> float:
        """Wall-clock seconds elapsed since this budget was constructed."""
        return time.monotonic() - self._start_monotonic

    async def reserve(self, *, request_bytes: int, output_tokens: int) -> None:
        """Atomically reserve one generation attempt or raise :class:`GenerationBudgetExceeded`.

        Must be called before every nonstreaming send this budget covers,
        with the fully serialized request size (rendered history + system
        instruction + tool definitions/results + new prompt) and the
        (already caller-clamped) requested output token ceiling for the
        attempt about to be dispatched. Checks and the resulting counter
        update happen under a single lock so concurrent callers cannot both
        observe capacity for what is really the run's last remaining
        attempt.

        Checked in order — call-count ceiling, deadline, request-byte
        ceiling, output-token ceiling — so the ``reason_code`` on a raised
        :class:`GenerationBudgetExceeded` identifies the first exhausted
        dimension. A refused reservation never increments any usage
        counter (no attempt is issued), but every counter accumulated by
        prior successful reservations is retained unchanged.

        Args:
            request_bytes: Byte length of the fully serialized outgoing
                request for this attempt.
            output_tokens: Requested output token ceiling for this attempt
                (already clamped by the caller to this budget's
                ``max_output_tokens`` where applicable).

        Raises:
            ValueError: If ``request_bytes`` or ``output_tokens`` is negative.
            GenerationBudgetExceeded: If the run has exhausted its call
                count, wall-clock deadline, per-request byte ceiling or
                output-token ceiling. Non-retryable — no fallback executes.
        """
        if request_bytes < 0:
            raise ValueError(f"request_bytes must be >= 0, got {request_bytes!r}")
        if output_tokens < 0:
            raise ValueError(f"output_tokens must be >= 0, got {output_tokens!r}")

        async with self._lock:
            if self._calls_used >= self.max_calls:
                message = f"generation budget exhausted: {self._calls_used}/{self.max_calls} calls already reserved"
                self.logger.warning(message)
                raise GenerationBudgetExceeded(message, reason_code="max_calls")

            elapsed = self.elapsed_s
            if elapsed >= self.timeout_s:
                message = f"generation budget deadline exceeded: {elapsed:.3f}s elapsed of {self.timeout_s}s"
                self.logger.warning(message)
                raise GenerationBudgetExceeded(message, reason_code="deadline")

            if request_bytes > self.max_request_bytes:
                message = f"request_bytes {request_bytes} exceeds ceiling {self.max_request_bytes}"
                self.logger.warning(message)
                raise GenerationBudgetExceeded(message, reason_code="request_bytes")

            if output_tokens > self.max_output_tokens:
                message = f"output_tokens {output_tokens} exceeds ceiling {self.max_output_tokens}"
                self.logger.warning(message)
                raise GenerationBudgetExceeded(message, reason_code="output_tokens")

            self._calls_used += 1
            self._bytes_used += request_bytes
            self.logger.debug(
                "generation budget reserved attempt %d/%d (request_bytes=%d, output_tokens=%d)",
                self._calls_used,
                self.max_calls,
                request_bytes,
                output_tokens,
            )

    async def record_usage_tokens(self, tokens: int) -> None:
        """Record a provider's actual reported token usage for evidence purposes.

        This is a purely additive counter kept separate from
        ``bytes_used`` — it is never derived from ``request_bytes``, only
        from what the provider response itself reports, so evidence never
        presents an estimated byte-derived figure as an exact token count.

        Args:
            tokens: Number of tokens the provider reported for one completed
                generation call (e.g. ``usage_metadata.total_token_count``).

        Raises:
            ValueError: If ``tokens`` is negative.
        """
        if tokens < 0:
            raise ValueError(f"tokens must be >= 0, got {tokens!r}")
        async with self._lock:
            self._usage_tokens_used += tokens
