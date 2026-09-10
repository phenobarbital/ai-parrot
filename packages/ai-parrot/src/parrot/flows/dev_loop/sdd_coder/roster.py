"""Roster probe + distinct-seat chunk assigner (spec §3 M2; G2, G6, G8)."""
from __future__ import annotations

import asyncio
import logging
import shutil
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set

from parrot import conf  # verified: navconfig `config` at parrot/conf.py
from parrot.flows.dev_loop.task_scheduler import TaskRef  # verified: task_scheduler.py:25
from parrot.flows.dev_loop.sdd_coder.models import PlanChunk, PlannedTask, RosterConfig, RosterSeat, SeatProbeResult

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

    async def probe(self, roster: RosterConfig) -> List[SeatProbeResult]:
        """One result per seat, roster order. Rules: spec §7 'Probe rules'."""
        results: List[SeatProbeResult] = []
        for seat in roster.seats:
            try:
                results.append(await self._probe_one(seat))
            except Exception as exc:  # noqa: BLE001 — probe must never raise
                results.append(
                    SeatProbeResult(
                        label=seat.label, kind=seat.kind, backend=seat.backend,
                        available=False, reason=str(exc),
                    )
                )
        return results

    async def _probe_one(self, seat: RosterSeat) -> SeatProbeResult:
        if seat.kind == "native":
            return SeatProbeResult(label=seat.label, kind="native", available=True, model_used=seat.model)

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
            return SeatProbeResult(
                label=seat.label, kind=seat.kind, backend=backend,
                available=True, model_used=seat.model, reason=reason,
            )

        try:
            ok = await asyncio.wait_for(self._smoke(seat, seat.model), timeout=self._smoke_timeout_s)
        except Exception as exc:  # noqa: BLE001 — smoke failures are reported, not raised
            ok = False
            reason = str(exc)

        if ok:
            return SeatProbeResult(label=seat.label, kind=seat.kind, backend=backend, available=True, model_used=seat.model)

        if not seat.fallback_model:
            return SeatProbeResult(
                label=seat.label, kind=seat.kind, backend=backend, available=False,
                reason=reason or f"smoke call rejected model {seat.model!r}",
            )

        try:
            fallback_ok = await asyncio.wait_for(
                self._smoke(seat, seat.fallback_model), timeout=self._smoke_timeout_s
            )
        except Exception as exc:  # noqa: BLE001 — smoke failures are reported, not raised
            fallback_ok = False
            reason = str(exc)

        if fallback_ok:
            return SeatProbeResult(
                label=seat.label, kind=seat.kind, backend=backend, available=True,
                model_used=seat.fallback_model, fallback_used=True,
            )

        return SeatProbeResult(
            label=seat.label, kind=seat.kind, backend=backend, available=False,
            reason=reason or f"smoke call rejected both {seat.model!r} and fallback {seat.fallback_model!r}",
        )


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

    def assign(self, wave: List[TaskRef], task_files: Dict[str, str]) -> List[PlanChunk]:
        """Sort by id; chunk k = tasks[k*n:(k+1)*n]; task j ↦ seats[(start+j) % n]; start
        advances by one for each chunk produced, so consecutive chunks begin on a
        different seat even when every chunk is a full `n`-sized batch (a `+= len(chunk)`
        step would be a no-op mod `n` whenever the batch is full-sized)."""
        n = len(self._seats)
        ordered = sorted(wave, key=lambda t: t.id)  # design research S3
        chunks: List[PlanChunk] = []
        for k in range(0, len(ordered), n):
            batch = ordered[k : k + n]
            planned_tasks: List[PlannedTask] = []
            for j, task in enumerate(batch):
                seat = self._seats[(self._start + j) % n]
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
            chunks.append(PlanChunk(index=len(chunks), tasks=planned_tasks))
            self._start = (self._start + 1) % n
        return chunks

    def retry_seat(self, failed_label: str, exclude: Set[str]) -> Optional[RosterSeat]:
        """Next MCP seat after `failed_label` in roster order not in `exclude`; None when none left.

        Never returns a `kind="native"` seat: the retry ladder (`SddCoderEngine._run_task`)
        only ever calls this after an MCP-seat dispatch attempt failed, and re-dispatches via
        `dispatcher.dispatch()` — a native seat has no dispatcher (it is a Claude Code
        `Agent` call `sdd-worker` makes itself via `coder_prepare_native`), so returning one
        here would hit `_run_attempt`'s `assert seat.backend is not None` instead of
        performing a real retry (code review finding, FEAT-549).
        """
        n = len(self._seats)
        try:
            failed_index = next(i for i, seat in enumerate(self._seats) if seat.label == failed_label)
        except StopIteration:
            failed_index = -1
        excluded = exclude | {failed_label}
        for offset in range(1, n + 1):
            candidate = self._seats[(failed_index + offset) % n]
            if candidate.label not in excluded and candidate.kind != "native":
                return candidate
        return None
