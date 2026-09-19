"""Bounded CLI pilot attempt runner (FEAT-580 M5, spec §3 Module 5).

``run_pilot`` never chooses a host/provider adapter or a price, never
spends money itself, and never invents a provider SDK integration: it only
launches the exact, operator-provided CLI ``argv`` from each arm's
:class:`~benchmarks.sdd_lsp.models.SeatSpec`, in a fresh isolated directory
per attempt, and normalizes whatever that seat reports back.

Seat contract (a seat is any operator-configured CLI, real or a test
double — this module defines the contract, never a live seat):

- The seat is launched via ``asyncio.create_subprocess_exec`` (never a
  shell) with ``cwd`` set to the attempt's isolated directory, and five
  environment variables layered on top of the current process's
  environment: ``PARROT_LSP_PILOT_ATTEMPT_ID``, ``_TASK_ID``, ``_ARM``,
  ``_REPETITION``, and ``_TOOLS`` (a comma-separated allowlist of the LSP
  tool names visible to this arm — see :data:`ARM_TOOL_FILTER`; empty for
  arms that expose no LSP tools). For the one task whose fixture requires
  a simulated unavailable semantic server
  (``fix-unavailable-server``, per spec §2 "the unavailable-server arm
  uses fallback, not automatic exclusion"), ``PARROT_LSP_PILOT_FORCE_UNAVAILABLE=1``
  is set regardless of arm.
- On exit, an investigation task's answer is read from
  ``answer.json`` (``{"path": str, "line": int}``) in the attempt
  directory; a change/fix task's edit is checked in place via
  :func:`benchmarks.sdd_lsp.fixtures.acceptance.run_behavior_check`.
- Normalized usage is read from ``trace.jsonl`` in the attempt directory,
  one JSON object per line, each parseable as a
  :class:`~benchmarks.sdd_lsp.models.ModelUsage`. A missing trace file is
  recorded honestly in the report's ``coverage_manifest`` — never silently
  dropped, and never a reason to fabricate zero-cost usage.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import time
from pathlib import Path

from pydantic import ValidationError

from benchmarks.sdd_lsp.accounting import attempt_cost_usd
from benchmarks.sdd_lsp.fixtures.acceptance import check_definition_answer, run_behavior_check
from benchmarks.sdd_lsp.fixtures.scenarios import ScenarioFixture, build_fixture
from benchmarks.sdd_lsp.models import (
    ARM_NAMES,
    ArmName,
    AttemptRecord,
    ModelUsage,
    PilotManifest,
    PilotReport,
    PriceBook,
    SeatSpec,
)

__all__ = ("ARM_TOOL_FILTER", "AttemptSpec", "build_attempt_matrix", "run_pilot")

#: The one fixed task that simulates its semantic server being entirely
#: unavailable, regardless of which arm runs it (spec §2: "The
#: unavailable-server arm uses fallback, not automatic exclusion from
#: results"; tasks.yaml: "the runner (TASK-3511) is responsible for
#: forcing that condition per arm, not this manifest").
_FORCE_UNAVAILABLE_TASK_ID = "fix-unavailable-server"

#: Which of the four LSP tools each arm may see. `current`/`wiki_ast`
#: expose none (they measure the non-LSP baselines); `lsp_combined` sees
#: all four. Communicated to the seat via `PARROT_LSP_PILOT_TOOLS` since
#: the seat's own MCP wiring is entirely operator-owned (out of this
#: task's scope, spec §3 M5 "NOT in scope: choosing host/provider
#: adapters").
ARM_TOOL_FILTER: dict[ArmName, tuple[str, ...]] = {
    "current": (),
    "wiki_ast": (),
    "lsp_navigation": ("lsp_definition", "lsp_references"),
    "lsp_diagnostics": ("lsp_diagnostics", "lsp_diagnostic_delta"),
    "lsp_combined": ("lsp_definition", "lsp_references", "lsp_diagnostics", "lsp_diagnostic_delta"),
}

_TRACE_FILENAME = "trace.jsonl"
_ANSWER_FILENAME = "answer.json"


class AttemptSpec:
    """One planned (not yet run) task/arm/repetition combination.

    Attributes:
        attempt_id: Deterministic id, stable across identical manifests.
        task_id: The fixed pilot task identifier.
        arm: The arm this attempt measures.
        repetition: The 1-based repetition index.
        seat: The arm's configured CLI seat.
    """

    __slots__ = ("attempt_id", "task_id", "arm", "repetition", "seat")

    def __init__(self, attempt_id: str, task_id: str, arm: ArmName, repetition: int, seat: SeatSpec) -> None:
        self.attempt_id = attempt_id
        self.task_id = task_id
        self.arm = arm
        self.repetition = repetition
        self.seat = seat

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"AttemptSpec({self.attempt_id!r}, task={self.task_id!r}, arm={self.arm!r}, rep={self.repetition})"


def _parse_counterbalanced_order(manifest: PilotManifest) -> list[tuple[str, ArmName]]:
    """Parse and validate ``manifest.counterbalanced_order`` into ``(task_id, arm)`` pairs.

    Each token must be ``"{task_id}|{arm}"``; the full sequence must cover
    every ``(task_id, arm)`` pair in the matrix exactly once.
    """
    parsed: list[tuple[str, ArmName]] = []
    for token in manifest.counterbalanced_order:
        task_id, sep, arm = token.partition("|")
        if not sep or arm not in ARM_NAMES or task_id not in manifest.task_ids:
            raise ValueError(f"invalid counterbalanced_order token: {token!r}")
        parsed.append((task_id, arm))  # type: ignore[arg-type]
    expected_pairs = {(task_id, arm) for task_id in manifest.task_ids for arm in manifest.arms}
    if set(parsed) != expected_pairs or len(parsed) != len(expected_pairs):
        raise ValueError("counterbalanced_order must cover every (task_id, arm) pair exactly once")
    return parsed


def _ordered_pairs(manifest: PilotManifest) -> list[tuple[str, ArmName, int]]:
    """Expand the manifest into ``(task_id, arm, repetition)`` in launch order.

    When ``manifest.counterbalanced_order`` is supplied, its declared
    ``(task_id, arm)`` order is honored verbatim and repeated, unrotated,
    once per repetition. An empty ``counterbalanced_order`` falls back to a
    deterministic default that rotates the arm order per repetition
    instead (spec: "counterbalance arm order").
    """
    if manifest.counterbalanced_order:
        base = _parse_counterbalanced_order(manifest)
        return [
            (task_id, arm, repetition) for repetition in range(1, manifest.repetitions + 1) for task_id, arm in base
        ]

    result: list[tuple[str, ArmName, int]] = []
    arms = list(manifest.arms)
    for repetition in range(manifest.repetitions):
        rotated = arms[repetition % len(arms) :] + arms[: repetition % len(arms)]
        for task_id in manifest.task_ids:
            for arm in rotated:
                result.append((task_id, arm, repetition + 1))
    return result


def build_attempt_matrix(manifest: PilotManifest) -> list[AttemptSpec]:
    """Expand a validated manifest into the full, deterministic attempt matrix.

    Args:
        manifest: A validated :class:`PilotManifest`.

    Returns:
        Exactly ``manifest.total_attempts`` (180 for the fixed defaults)
        :class:`AttemptSpec` entries, in launch order. Attempt ids are
        deterministic (a stable hash of task/arm/repetition), so the same
        manifest always plans the same matrix.
    """
    pairs = _ordered_pairs(manifest)
    if len(pairs) != manifest.total_attempts:
        raise ValueError(f"expected {manifest.total_attempts} planned attempts, computed {len(pairs)}")
    matrix: list[AttemptSpec] = []
    for task_id, arm, repetition in pairs:
        attempt_id = f"{task_id}::{arm}::rep{repetition}"
        matrix.append(AttemptSpec(attempt_id, task_id, arm, repetition, manifest.seats[arm]))
    return matrix


def _read_trace(attempt_dir: Path, attempt_id: str, seat_id: str) -> tuple[list[ModelUsage], bool]:
    """Read and validate ``trace.jsonl``; never silently drop a missing file.

    Returns:
        ``(usage_records, trace_present)``. A present-but-malformed line
        is skipped (not fatal to the attempt) but the trace still counts
        as present, since the seat did produce output.
    """
    trace_path = attempt_dir / _TRACE_FILENAME
    if not trace_path.is_file():
        return [], False
    records: list[ModelUsage] = []
    for line in trace_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        payload.setdefault("attempt_id", attempt_id)
        payload.setdefault("seat_id", seat_id)
        try:
            records.append(ModelUsage(**payload))
        except ValidationError:
            continue
    return records, True


def _prepare_attempt_dir(fixture: ScenarioFixture, attempt_dir: Path) -> None:
    """Blocking setup for one attempt: fresh isolated directory + materialized fixture."""
    if attempt_dir.exists():
        shutil.rmtree(attempt_dir)
    attempt_dir.mkdir(parents=True)
    fixture.materialize(attempt_dir)


def _check_acceptance(
    fixture: ScenarioFixture, task_id: str, attempt_dir: Path, timeout_s: float
) -> tuple[bool, str | None]:
    """Blocking acceptance check: read the answer file, or run the behavior check."""
    if fixture.entry_point is None:
        answer_path = attempt_dir / _ANSWER_FILENAME
        if not answer_path.is_file():
            return False, "missing_answer"
        try:
            answer = json.loads(answer_path.read_text(encoding="utf-8"))
            result = check_definition_answer(task_id, answer["path"], int(answer["line"]))
        except (json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
            return False, f"malformed answer.json: {exc}"
        if result.passed:
            return True, None
        return False, "; ".join(result.reasons) or "acceptance_check_failed"

    result = run_behavior_check(fixture, attempt_dir, timeout_s=timeout_s)
    if result.passed:
        return True, None
    return False, "; ".join(result.reasons) or "acceptance_check_failed"


async def _run_one_attempt(
    spec: AttemptSpec,
    output_dir: Path,
    *,
    keep_failed: bool = True,
) -> AttemptRecord:
    """Materialize, launch, collect, and (usually) clean up one attempt."""
    fixture = build_fixture(spec.task_id)
    attempt_dir = output_dir / "attempts" / spec.attempt_id
    await asyncio.to_thread(_prepare_attempt_dir, fixture, attempt_dir)

    tools = ARM_TOOL_FILTER[spec.arm]
    env = {
        **os.environ,
        "PARROT_LSP_PILOT_ATTEMPT_ID": spec.attempt_id,
        "PARROT_LSP_PILOT_TASK_ID": spec.task_id,
        "PARROT_LSP_PILOT_ARM": spec.arm,
        "PARROT_LSP_PILOT_REPETITION": str(spec.repetition),
        "PARROT_LSP_PILOT_TOOLS": ",".join(tools),
    }
    if spec.task_id == _FORCE_UNAVAILABLE_TASK_ID:
        env["PARROT_LSP_PILOT_FORCE_UNAVAILABLE"] = "1"

    started_at = time.monotonic()
    failure_reason: str | None = None
    try:
        process = await asyncio.create_subprocess_exec(
            *spec.seat.argv,
            cwd=str(attempt_dir),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _stdout, _stderr = await asyncio.wait_for(process.communicate(), timeout=spec.seat.timeout_s)
            if process.returncode != 0:
                failure_reason = f"seat exited with code {process.returncode}"
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            failure_reason = f"seat exceeded its {spec.seat.timeout_s:g}s timeout"
    except (OSError, FileNotFoundError) as exc:
        failure_reason = f"seat launch failed: {exc}"
    elapsed_ms = int((time.monotonic() - started_at) * 1000)

    usage, trace_present = await asyncio.to_thread(_read_trace, attempt_dir, spec.attempt_id, spec.seat.arm)
    raw_trace_refs = [str(attempt_dir / _TRACE_FILENAME)] if trace_present else []

    accepted = False
    if failure_reason is None:
        accepted, failure_reason = await asyncio.to_thread(
            _check_acceptance, fixture, spec.task_id, attempt_dir, spec.seat.timeout_s
        )

    record = AttemptRecord(
        attempt_id=spec.attempt_id,
        task_id=spec.task_id,
        arm=spec.arm,
        repetition=spec.repetition,
        seat_id=spec.arm,
        accepted=accepted,
        failure_reason=failure_reason,
        usage=usage,
        raw_trace_refs=raw_trace_refs,
        cold_start=spec.repetition == 1,
        elapsed_ms=elapsed_ms,
    )

    if accepted or not keep_failed:
        await asyncio.to_thread(shutil.rmtree, attempt_dir, ignore_errors=True)

    return record


async def run_pilot(manifest: PilotManifest, output_dir: Path) -> PilotReport:
    """Run every planned attempt in a validated manifest's matrix.

    Never invents a provider SDK integration: every attempt launches
    exactly the seat's configured ``argv`` via ``asyncio.create_subprocess_exec``
    (no shell), in a freshly materialized, isolated directory. Every
    attempted task -- accepted or not -- is retained in the returned
    report; nothing is silently dropped.

    Budget discipline (spec §2/§5): before each launch, the per-attempt
    cost reservation is checked against the tracked remaining budget; once
    remaining budget can no longer cover the reservation, or any executed
    attempt's cost comes back unknown (no ``actual_cost_usd`` on one or
    more of its usage records), no further attempts are launched. Every
    attempt already run stays in the report; every attempt that was never
    launched due to the budget/unknown-cost stop is still recorded, with
    an explicit ``failure_reason``, so incomplete coverage is never hidden.

    Args:
        manifest: A validated :class:`PilotManifest`.
        output_dir: Where per-attempt working directories are materialized.

    Returns:
        A :class:`PilotReport`. ``synthetic`` stays ``True`` (this runner
        never asserts it produced a live, audited run — that judgment
        belongs to the caller, per spec §3 M5).
    """
    await asyncio.to_thread(output_dir.mkdir, parents=True, exist_ok=True)
    matrix = build_attempt_matrix(manifest)

    attempts: list[AttemptRecord] = []
    remaining_budget = manifest.spending_ceiling_usd
    stopped_reason: str | None = None
    prices = PriceBook()  # empty on purpose: only actual_cost_usd is trusted here (see module docstring)

    for spec in matrix:
        if stopped_reason is not None:
            attempts.append(
                AttemptRecord(
                    attempt_id=spec.attempt_id,
                    task_id=spec.task_id,
                    arm=spec.arm,
                    repetition=spec.repetition,
                    seat_id=spec.arm,
                    accepted=False,
                    failure_reason=f"not_launched: {stopped_reason}",
                )
            )
            continue

        if remaining_budget < manifest.per_attempt_cost_reservation_usd:
            stopped_reason = "budget exhausted: remaining balance below the per-attempt reservation"
            attempts.append(
                AttemptRecord(
                    attempt_id=spec.attempt_id,
                    task_id=spec.task_id,
                    arm=spec.arm,
                    repetition=spec.repetition,
                    seat_id=spec.arm,
                    accepted=False,
                    failure_reason=f"not_launched: {stopped_reason}",
                )
            )
            continue

        record = await _run_one_attempt(spec, output_dir)
        attempts.append(record)

        cost = attempt_cost_usd(record, prices)
        if cost is None:
            stopped_reason = f"unknown cost after attempt {spec.attempt_id!r}: refusing to launch further attempts"
            continue
        remaining_budget -= cost

    coverage_manifest = {
        "planned": len(matrix),
        "executed": sum(1 for a in attempts if not (a.failure_reason or "").startswith("not_launched")),
        "not_launched": sum(1 for a in attempts if (a.failure_reason or "").startswith("not_launched")),
        "missing_trace": sum(
            1 for a in attempts if not a.raw_trace_refs and not (a.failure_reason or "").startswith("not_launched")
        ),
        "accepted": sum(1 for a in attempts if a.accepted),
    }

    return PilotReport(manifest=manifest, attempts=attempts, coverage_manifest=coverage_manifest, synthetic=True)
