"""Roster probe + distinct-seat chunk assigner (spec §3 M2; G2, G6, G8)."""

from __future__ import annotations

import asyncio
import logging
import shutil
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set

from parrot import conf  # verified: navconfig `config` at parrot/conf.py
from parrot.flows.dev_loop.task_scheduler import TaskRef  # verified: task_scheduler.py:25
from parrot.flows.dev_loop.sdd_coder.models import PlanChunk, PlannedTask, RosterConfig, RosterSeat, SeatProbeResult
from parrot.flows.dev_loop.sdd_coder.complexity_models import ComplexityAssessment, ComplexityPolicy
from parrot.knowledge.wiki.ledger.coder_suspensions import ModelKey

SmokeFn = Callable[[RosterSeat, str], Awaitable[bool]]
_KEY_RULES: Dict[str, tuple[str, ...]] = {
    "nova": ("BEDROCK_MANTLE_API_KEY", "AWS_NOVA_API_KEY"),  # verified: mantle.py:110
    "google-compat": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
}
_CLI_RULES: Dict[str, str] = {"codex": "codex", "google_coding": "agy"}


class RosterProbe:
    """Decides which configured seats are usable right now. Never raises."""

    def __init__(
        self,
        *,
        config_getter: Callable[..., Any] = conf.config.get,
        which: Callable[[str], Optional[str]] = shutil.which,
        smoke: Optional[SmokeFn] = None,
        smoke_timeout_s: int = 60,
    ) -> None:
        self.logger = logging.getLogger(__name__)
        self._get, self._which, self._smoke, self._smoke_timeout_s = config_getter, which, smoke, smoke_timeout_s

    async def probe(self, roster: RosterConfig, *, excluded: Optional[Set[ModelKey]] = None) -> List[SeatProbeResult]:
        """One result per seat, roster order. Rules: spec §7 'Probe rules'.

        Args:
            roster: The roster configuration to probe.
            excluded: Set of ModelKey (backend, model) to skip for probing.
        """
        excluded = excluded or set()
        results: List[SeatProbeResult] = []
        for seat in roster.seats:
            try:
                results.append(await self._probe_one(seat, excluded))
            except Exception as exc:  # noqa: BLE001 — probe must never raise
                results.append(
                    SeatProbeResult(
                        label=seat.label,
                        kind=seat.kind,
                        backend=seat.backend,
                        available=False,
                        reason=str(exc),
                    )
                )
        return results

    def _is_excluded(self, backend: str, model: str, excluded: Set[ModelKey]) -> bool:
        """Check if a model is excluded. Normalizes native default to native/haiku."""
        if not model:
            return True  # Empty model ID is excluded (model_identity_required)
        # Normalize native default
        effective_backend = backend if backend else "native"
        effective_model = model if model else "haiku"
        key = ModelKey(backend=effective_backend, model=effective_model)
        return key in excluded

    async def _probe_one(self, seat: RosterSeat, excluded: Set[ModelKey]) -> SeatProbeResult:
        if seat.kind == "native":
            # Normalize native default identity
            model = seat.model if seat.model else "haiku"
            if self._is_excluded("native", model, excluded):
                return SeatProbeResult(
                    label=seat.label,
                    kind="native",
                    available=False,
                    reason="model excluded",
                )
            return SeatProbeResult(label=seat.label, kind="native", available=True, model_used=model)

        backend = seat.backend or ""
        static_available = True
        reason = ""

        if backend in _KEY_RULES:
            keys = _KEY_RULES[backend]
            if not any(self._get(key) for key in keys):
                static_available = False
                reason = f"none of {', '.join(keys)} is configured"
        elif backend in _CLI_RULES:
            binary = _CLI_RULES[backend]
            if self._which(binary) is None:
                static_available = False
                reason = f"'{binary}' CLI not found on PATH"
        else:
            reason = "no probe rule; assumed available"

        if not static_available:
            return SeatProbeResult(label=seat.label, kind=seat.kind, backend=backend, available=False, reason=reason)

        if self._smoke is None:
            # No smoke check; still verify model is not excluded
            if self._is_excluded(backend, seat.model, excluded):
                return SeatProbeResult(
                    label=seat.label,
                    kind=seat.kind,
                    backend=backend,
                    available=False,
                    reason="model excluded",
                )
            return SeatProbeResult(
                label=seat.label,
                kind=seat.kind,
                backend=backend,
                available=True,
                model_used=seat.model,
                reason=reason,
            )

        # Check if primary model is excluded before making smoke call
        primary_excluded = self._is_excluded(backend, seat.model, excluded)

        if primary_excluded:
            # Primary is excluded; skip it and check fallback independently
            primary_probe_uid = ""
            primary_observed_at = ""
            primary_duration_s = 0.0
            primary_exception_class = ""
            primary_reason = "model excluded"
        else:
            # Primary is not excluded; probe it. `primary_reason`/`primary_exception_class`
            # are initialized here (not only inside `except`) because a smoke call that
            # simply *returns* False (no exception) must not leave them referenced-before-
            # assignment below -- that previously surfaced as an opaque UnboundLocalError
            # wrapped by `probe()`'s catch-all, masking every ordinary probe failure.
            primary_uid = str(uuid.uuid4())
            primary_start = time.monotonic()
            primary_observed_at = datetime.now(timezone.utc).isoformat()
            primary_reason = ""
            primary_exception_class = ""
            try:
                ok = await asyncio.wait_for(self._smoke(seat, seat.model), timeout=self._smoke_timeout_s)
            except Exception as exc:  # noqa: BLE001 — smoke failures are reported, not raised
                ok = False
                primary_exception_class = type(exc).__name__
                detail = str(exc)
                # Some exceptions (notably a bare `asyncio.TimeoutError`) stringify to "" --
                # always fall back to the exception's class name so the reason is never
                # silently empty (e.g. still surfaces "TimeoutError" for a smoke timeout).
                primary_reason = f"{primary_exception_class}: {detail}" if detail else primary_exception_class
            primary_duration_s = time.monotonic() - primary_start
            primary_probe_uid = primary_uid

            if ok:
                return SeatProbeResult(
                    label=seat.label,
                    kind=seat.kind,
                    backend=backend,
                    available=True,
                    model_used=seat.model,
                    probe_uid=primary_uid,
                    probe_observed_at=primary_observed_at,
                    probe_duration_s=primary_duration_s,
                    probe_exception_class=primary_exception_class,
                )

        # Primary failed or was excluded; try fallback if configured
        if not seat.fallback_model:
            # No fallback; report primary failure (even if excluded, for tracking)
            return SeatProbeResult(
                label=seat.label,
                kind=seat.kind,
                backend=backend,
                available=False,
                reason=primary_reason or f"smoke call rejected model {seat.model!r}",
                probe_uid=primary_probe_uid,
                probe_observed_at=primary_observed_at,
                probe_duration_s=primary_duration_s,
                probe_exception_class=primary_exception_class,
            )

        # Check if fallback model is excluded
        fallback_excluded = self._is_excluded(backend, seat.fallback_model, excluded)

        if fallback_excluded:
            # Fallback is excluded; report primary failure
            return SeatProbeResult(
                label=seat.label,
                kind=seat.kind,
                backend=backend,
                available=False,
                reason=primary_reason or f"smoke call rejected model {seat.model!r}; fallback excluded",
                probe_uid=primary_probe_uid,
                probe_observed_at=primary_observed_at,
                probe_duration_s=primary_duration_s,
                probe_exception_class=primary_exception_class,
            )

        # Probe the fallback
        try:
            fallback_ok = await asyncio.wait_for(self._smoke(seat, seat.fallback_model), timeout=self._smoke_timeout_s)
        except Exception:  # noqa: BLE001 — smoke failures are reported, not raised
            fallback_ok = False

        if fallback_ok:
            # Fallback succeeded; report primary failure metadata alongside success
            return SeatProbeResult(
                label=seat.label,
                kind=seat.kind,
                backend=backend,
                available=True,
                model_used=seat.fallback_model,
                fallback_used=True,
                probe_uid=primary_probe_uid,
                probe_observed_at=primary_observed_at,
                probe_duration_s=primary_duration_s,
                probe_exception_class=primary_exception_class,
            )

        # Both failed; report primary failure (more useful for debugging)
        return SeatProbeResult(
            label=seat.label,
            kind=seat.kind,
            backend=backend,
            available=False,
            reason=primary_reason or f"smoke call rejected both {seat.model!r} and fallback {seat.fallback_model!r}",
            probe_uid=primary_probe_uid,
            probe_observed_at=primary_observed_at,
            probe_duration_s=primary_duration_s,
            probe_exception_class=primary_exception_class,
        )


def eligible_seats(
    assessment: ComplexityAssessment, seats: List[RosterSeat], policy: ComplexityPolicy
) -> List[RosterSeat]:
    """Filter `seats` to those permitted for `assessment`'s classification (spec §2).

    `standard` tasks may use any of the supplied seats, unchanged and in order
    ("Standard tasks retain the configured roster rotation behavior"). `complex`
    and `unknown` tasks are restricted to seats whose exact `(backend, model)`
    pair -- `backend="native"` for `kind="native"` seats -- matches one of
    `policy.strong_models`'s configured identities. Never matches a seat
    nickname or an inferred alias, and never overrides seat availability or
    suspension: `seats` is expected to already be the caller's
    available/unsuspended subset.
    """
    if assessment.classification == "standard":
        return list(seats)

    strong_keys = {(sm.backend, sm.model) for sm in policy.strong_models}
    out: List[RosterSeat] = []
    for seat in seats:
        backend = "native" if seat.kind == "native" else (seat.backend or "")
        if (backend, seat.model or "") in strong_keys:
            out.append(seat)
    return out


def available_seats(roster: RosterConfig, results: List[SeatProbeResult]) -> List[RosterSeat]:
    """Seats with available=True, roster order, `model` replaced by `model_used`."""
    by_label = {r.label: r for r in results}
    out: List[RosterSeat] = []
    for seat in roster.seats:
        result = by_label.get(seat.label)
        if result is not None and result.available:
            out.append(seat.model_copy(update={"model": result.model_used}))
    return out


class ChunkAssigner:
    """Distinct-seat chunking with a rotating start index (spec G2)."""

    def __init__(self, seats: List[RosterSeat]) -> None:
        if not seats:
            raise ValueError("ChunkAssigner needs at least one seat")
        self._seats, self._start = list(seats), 0

    def assign(
        self,
        wave: List[TaskRef],
        task_files: Dict[str, str],
        *,
        eligible_labels: Optional[Dict[str, Set[str]]] = None,
    ) -> List[PlanChunk]:
        """Sort by id; each exclusive task alone first, then shared chunk k = shared[k*n:(k+1)*n];
        task j ↦ seats[(start+j) % n]; start
        advances by one for each chunk produced, so consecutive chunks begin on a
        different seat even when every chunk is a full `n`-sized batch (a `+= len(chunk)`
        step would be a no-op mod `n` whenever the batch is full-sized).

        `eligible_labels`, when given, maps each wave task's ID to the set of seat
        labels it may be dispatched to (spec "Models and dispatch rules"): every
        task in `wave` must have a non-empty entry, or this raises `ValueError`.
        Seats are still assigned by the same rotating cyclic order and
        one-seat-per-chunk rule, restricted to each task's eligible set. When the
        next task's only eligible seats are already used in the current chunk,
        that chunk is closed early and a new one (on the next rotation) continues
        with that task, rather than ever dispatching it to an ineligible seat.
        """
        if eligible_labels is not None:
            for task in wave:
                if not eligible_labels.get(task.id):
                    raise ValueError(f"task {task.id!r} has no eligible seat labels")

        n = len(self._seats)
        ordered = sorted(wave, key=lambda t: t.id)  # design research S3
        # Exclusive tasks (`parallel: false` under the index's exclusive semantics) get a
        # chunk of their own and come first: the orchestrator dispatches only chunks[0]
        # per round, so an exclusive task queued behind shared batches could starve while
        # new shared tasks keep unblocking.
        exclusive = [t for t in ordered if not t.parallel]
        shared = [t for t in ordered if t.parallel]
        batches = [[t] for t in exclusive] + [shared[k : k + n] for k in range(0, len(shared), n)]
        chunks: List[PlanChunk] = []
        for batch in batches:
            planned_tasks: List[PlannedTask] = []
            used_labels: Set[str] = set()
            for task in batch:
                allowed = eligible_labels.get(task.id) if eligible_labels is not None else None
                seat = self._next_seat(used_labels, allowed)
                if seat is None and planned_tasks:
                    # No unused eligible seat left in this chunk: close it and
                    # retry this task against a freshly-rotated, empty chunk
                    # instead of ever dispatching it to an ineligible seat.
                    chunks.append(PlanChunk(index=len(chunks), tasks=planned_tasks))
                    self._start = (self._start + 1) % n
                    planned_tasks = []
                    used_labels = set()
                    seat = self._next_seat(used_labels, allowed)
                if seat is None:
                    raise ValueError(f"no eligible seat available for task {task.id!r}")
                planned_tasks.append(
                    PlannedTask(
                        task_id=task.id,
                        task_file=task_files.get(task.id, task.file),
                        title=task.title,
                        seat_label=seat.label,
                        native=(seat.kind == "native"),
                        backend=seat.backend,
                        model=seat.model,
                    )
                )
                used_labels.add(seat.label)
            if planned_tasks:
                chunks.append(PlanChunk(index=len(chunks), tasks=planned_tasks))
                self._start = (self._start + 1) % n
        return chunks

    def _next_seat(self, used_labels: Set[str], allowed: Optional[Set[str]]) -> Optional[RosterSeat]:
        """First seat, in current rotation order, not in `used_labels` and (when
        `allowed` is given) within that eligible set."""
        n = len(self._seats)
        for offset in range(n):
            candidate = self._seats[(self._start + offset) % n]
            if candidate.label in used_labels:
                continue
            if allowed is not None and candidate.label not in allowed:
                continue
            return candidate
        return None

    def retry_seat(
        self, failed_label: str, exclude: Set[str], *, eligible_labels: Optional[Set[str]] = None
    ) -> Optional[RosterSeat]:
        """Next MCP seat after `failed_label` in roster order not in `exclude`; None when none left.

        Never returns a `kind="native"` seat: the retry ladder (`SddCoderEngine._run_task`)
        only ever calls this after an MCP-seat dispatch attempt failed, and re-dispatches via
        `dispatcher.dispatch()` — a native seat has no dispatcher (it is a Claude Code
        `Agent` call `sdd-worker` makes itself via `coder_prepare_native`), so returning one
        here would hit `_run_attempt`'s `assert seat.backend is not None` instead of
        performing a real retry (code review finding, FEAT-549).

        `eligible_labels`, when given, restricts the candidate to that set (spec:
        "Probe fallbacks, retry_seat and native preparation apply the same model
        restriction" -- a failed strong-model attempt cannot retry through a
        weak seat).
        """
        n = len(self._seats)
        try:
            failed_index = next(i for i, seat in enumerate(self._seats) if seat.label == failed_label)
        except StopIteration:
            failed_index = -1
        excluded = exclude | {failed_label}
        for offset in range(1, n + 1):
            candidate = self._seats[(failed_index + offset) % n]
            if candidate.label in excluded or candidate.kind == "native":
                continue
            if eligible_labels is not None and candidate.label not in eligible_labels:
                continue
            return candidate
        return None
