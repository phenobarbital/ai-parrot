"""Tests for the FEAT-580 M5 bounded CLI pilot runner (TASK-3511).

Every test drives ``run_pilot`` against a small, self-contained fake CLI
seat script (written to a temp file at test setup, never a live provider
or a real coding agent) so the full matrix expansion, budget/timeout
discipline, and trace-coverage bookkeeping are exercised deterministically
and without spending anything.
"""

from __future__ import annotations

import sys
import textwrap
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from benchmarks.sdd_lsp.fixtures.scenarios import SCENARIO_IDS
from benchmarks.sdd_lsp.models import ARM_NAMES, ArmName, PilotManifest, SeatSpec
from benchmarks.sdd_lsp.runner import ARM_TOOL_FILTER, build_attempt_matrix, run_pilot

_REPO_ROOT = str(Path(__file__).resolve().parents[4])
_TOOLS_SRC = str(Path(__file__).resolve().parents[2] / "src")

_FAKE_SEAT_SRC = textwrap.dedent(f"""
    import json
    import os
    import sys
    import time
    from pathlib import Path

    sys.path.insert(0, {_REPO_ROOT!r})
    sys.path.insert(0, {_TOOLS_SRC!r})

    from benchmarks.sdd_lsp.fixtures.acceptance import EXPECTED_DEFINITIONS
    from benchmarks.sdd_lsp.fixtures.scenarios import build_fixture


    def main() -> int:
        mode = sys.argv[1] if len(sys.argv) > 1 else "perfect"
        task_id = os.environ["PARROT_LSP_PILOT_TASK_ID"]
        attempt_id = os.environ["PARROT_LSP_PILOT_ATTEMPT_ID"]
        seat_id = os.environ["PARROT_LSP_PILOT_ARM"]
        cwd = Path.cwd()

        if mode == "hang":
            time.sleep(60.0)
            return 0
        if mode == "crash":
            return 1

        fixture = build_fixture(task_id)
        if fixture.entry_point is None:
            path, line = EXPECTED_DEFINITIONS[task_id]
            (cwd / "answer.json").write_text(json.dumps({{"path": path, "line": line}}))
        else:
            fixture.apply_variant(cwd, "expected_fix")

        if mode != "no_trace":
            usage = {{
                "attempt_id": attempt_id,
                "seat_id": seat_id,
                "request_id": attempt_id + "-r1",
                "model": "fake-model",
                "source": "fake_seat",
            }}
            if mode == "high_cost":
                usage["actual_cost_usd"] = 1000.0
            elif mode != "unknown_cost":
                usage["actual_cost_usd"] = 0.001
            (cwd / "trace.jsonl").write_text(json.dumps(usage) + "\\n")
        return 0


    sys.exit(main())
    """)


@pytest.fixture
def fake_seat(tmp_path: Path) -> Path:
    script = tmp_path / "fake_seat.py"
    script.write_text(_FAKE_SEAT_SRC, encoding="utf-8")
    return script


def _seats(fake_seat: Path, mode: str = "perfect", timeout_s: float = 5.0) -> dict[ArmName, SeatSpec]:
    return {
        arm: SeatSpec(arm=arm, argv=[sys.executable, str(fake_seat), mode], timeout_s=timeout_s) for arm in ARM_NAMES
    }


def _manifest(
    fake_seat: Path,
    *,
    mode: str = "perfect",
    timeout_s: float = 5.0,
    spending_ceiling_usd: float = 1000.0,
    per_attempt_cost_reservation_usd: float = 0.01,
    counterbalanced_order: tuple[str, ...] = (),
) -> PilotManifest:
    return PilotManifest(
        pinned_commit="0" * 40,
        task_ids=SCENARIO_IDS,
        seats=_seats(fake_seat, mode, timeout_s),
        model="fake-model",
        environment_id="pilot-runner-test",
        price_provenance="test-fixture, no real prices",
        cache_semantics="fake seat reports actual_cost_usd directly; no cache categories",
        counterbalanced_order=counterbalanced_order,
        spending_ceiling_usd=spending_ceiling_usd,
        per_attempt_cost_reservation_usd=per_attempt_cost_reservation_usd,
    )


# ---------------------------------------------------------------------------
# test_pilot_manifest_and_matrix
# ---------------------------------------------------------------------------


def test_pilot_manifest_and_matrix(fake_seat: Path) -> None:
    """The full matrix is exactly 180 deterministic attempts; malformed order is rejected."""
    manifest = _manifest(fake_seat)

    matrix = build_attempt_matrix(manifest)
    assert len(matrix) == manifest.total_attempts == 180

    # Deterministic: the same manifest always plans the same attempt ids.
    matrix_again = build_attempt_matrix(manifest)
    assert [spec.attempt_id for spec in matrix] == [spec.attempt_id for spec in matrix_again]
    assert len({spec.attempt_id for spec in matrix}) == 180  # every id unique

    # Every (task_id, arm, repetition) combination appears exactly once.
    combos = {(spec.task_id, spec.arm, spec.repetition) for spec in matrix}
    assert len(combos) == 180
    for task_id in manifest.task_ids:
        for arm in manifest.arms:
            for repetition in range(1, manifest.repetitions + 1):
                assert (task_id, arm, repetition) in combos

    # An explicit counterbalanced_order is honored verbatim, repeated per repetition.
    explicit_order = tuple(f"{task_id}|{arm}" for task_id in manifest.task_ids for arm in reversed(ARM_NAMES))
    ordered_manifest = _manifest(fake_seat, counterbalanced_order=explicit_order)
    ordered_matrix = build_attempt_matrix(ordered_manifest)
    first_pass = [(spec.task_id, spec.arm) for spec in ordered_matrix[:60]]
    assert first_pass == [(task_id, arm) for task_id in manifest.task_ids for arm in reversed(ARM_NAMES)]
    # The declared order repeats unrotated for every subsequent repetition.
    second_pass = [(spec.task_id, spec.arm) for spec in ordered_matrix[60:120]]
    assert second_pass == first_pass

    # Adversarial: a malformed token is rejected explicitly, never silently ignored.
    with pytest.raises(ValueError, match="invalid counterbalanced_order token"):
        build_attempt_matrix(_manifest(fake_seat, counterbalanced_order=("not-a-valid-token",)))

    # Adversarial: an order missing coverage is rejected explicitly.
    incomplete_order = explicit_order[:-1]
    with pytest.raises(ValueError, match="exactly once"):
        build_attempt_matrix(_manifest(fake_seat, counterbalanced_order=incomplete_order))


# ---------------------------------------------------------------------------
# test_arm_filters_and_isolated_working_states
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_arm_filters_and_isolated_working_states(fake_seat: Path, tmp_path: Path) -> None:
    """Arm-specific tool filters are explicit; every attempt starts from an isolated state."""
    assert ARM_TOOL_FILTER["current"] == ()
    assert ARM_TOOL_FILTER["wiki_ast"] == ()
    assert ARM_TOOL_FILTER["lsp_navigation"] == ("lsp_definition", "lsp_references")
    assert ARM_TOOL_FILTER["lsp_diagnostics"] == ("lsp_diagnostics", "lsp_diagnostic_delta")
    assert ARM_TOOL_FILTER["lsp_combined"] == (
        "lsp_definition",
        "lsp_references",
        "lsp_diagnostics",
        "lsp_diagnostic_delta",
    )
    # Every arm has an explicit entry -- no silently-defaulted arm.
    assert set(ARM_TOOL_FILTER) == set(ARM_NAMES)

    manifest = _manifest(fake_seat, mode="perfect")
    report = await run_pilot(manifest, tmp_path / "out")

    assert len(report.attempts) == 180
    assert all(attempt.accepted for attempt in report.attempts), [
        (a.attempt_id, a.failure_reason) for a in report.attempts if not a.accepted
    ]

    # Isolated starting states: every attempt's collected usage is scoped to
    # exactly its own attempt_id/seat_id -- no cross-attempt bleed, and the
    # perfect seat always resolved the correct pre-computed answer/edit
    # independently for each of the 180 isolated working directories (a
    # cross-contaminated fixture would fail the acceptance check for at
    # least one of the 15 attempts sharing a task_id across arms/reps).
    for attempt in report.attempts:
        assert len(attempt.usage) == 1
        assert attempt.usage[0].attempt_id == attempt.attempt_id
        assert attempt.usage[0].seat_id == attempt.arm


# ---------------------------------------------------------------------------
# test_budget_unknown_cost_and_timeout_stop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_budget_unknown_cost_and_timeout_stop(fake_seat: Path, tmp_path: Path) -> None:
    """Unknown cost stops further launches; a hung seat is bounded by its own timeout."""
    # --- Unknown cost stops launching further attempts -----------------
    unknown_manifest = _manifest(fake_seat, mode="unknown_cost", spending_ceiling_usd=1000.0)
    report = await run_pilot(unknown_manifest, tmp_path / "unknown")

    assert len(report.attempts) == 180  # every planned attempt still retained, none dropped
    executed = [a for a in report.attempts if not (a.failure_reason or "").startswith("not_launched")]
    not_launched = [a for a in report.attempts if (a.failure_reason or "").startswith("not_launched")]
    assert len(executed) == 1, "expected exactly one attempt to run before the unknown-cost stop"
    assert len(not_launched) == 179
    assert all("unknown cost" in a.failure_reason for a in not_launched)
    assert report.coverage_manifest["executed"] == 1
    assert report.coverage_manifest["not_launched"] == 179

    # --- Budget exhaustion stops launching further attempts ------------
    # A ceiling that cannot cover even two reservations: at most one
    # attempt may launch regardless of the seat's actual behavior.
    budget_manifest = _manifest(
        fake_seat,
        mode="perfect",
        spending_ceiling_usd=0.0015,
        per_attempt_cost_reservation_usd=0.001,
    )
    budget_report = await run_pilot(budget_manifest, tmp_path / "budget")
    budget_executed = [a for a in budget_report.attempts if not (a.failure_reason or "").startswith("not_launched")]
    assert 1 <= len(budget_executed) <= 2
    assert any("budget exhausted" in (a.failure_reason or "") for a in budget_report.attempts)

    # --- A hung seat is bounded by its own per-seat timeout -------------
    # A tiny timeout keeps this bounded even across the full 180-attempt
    # matrix: each hang is killed almost immediately, never once actually
    # waiting out the real 60s sleep in the fake seat.
    hang_manifest = _manifest(fake_seat, mode="hang", timeout_s=0.05)
    started = time.monotonic()
    hang_report = await run_pilot(hang_manifest, tmp_path / "hang")
    elapsed = time.monotonic() - started

    assert elapsed < 60.0, f"a per-seat timeout must bound each attempt, took {elapsed:.1f}s for the full matrix"
    assert all(not a.accepted for a in hang_report.attempts)
    assert all("timeout" in (a.failure_reason or "") for a in hang_report.attempts if a.elapsed_ms is not None)


# ---------------------------------------------------------------------------
# test_trace_coverage_and_failed_attempts_retained
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trace_coverage_and_failed_attempts_retained(fake_seat: Path, tmp_path: Path) -> None:
    """A missing trace is recorded as coverage, never dropped; failures are retained too."""
    # --- Missing trace: acceptance still succeeds, coverage records the gap.
    no_trace_manifest = _manifest(fake_seat, mode="no_trace")
    no_trace_report = await run_pilot(no_trace_manifest, tmp_path / "no_trace")

    assert len(no_trace_report.attempts) == 180
    assert all(attempt.accepted for attempt in no_trace_report.attempts)
    assert all(attempt.usage == [] for attempt in no_trace_report.attempts)
    assert all(attempt.raw_trace_refs == [] for attempt in no_trace_report.attempts)
    assert no_trace_report.coverage_manifest["missing_trace"] == 180

    # --- A seat that crashes outright still yields a retained, unaccepted
    # AttemptRecord for every planned attempt -- never silently dropped.
    crash_manifest = _manifest(fake_seat, mode="crash")
    crash_report = await run_pilot(crash_manifest, tmp_path / "crash")

    assert len(crash_report.attempts) == 180
    assert all(not attempt.accepted for attempt in crash_report.attempts)
    assert all(attempt.failure_reason for attempt in crash_report.attempts)
    assert crash_report.coverage_manifest["accepted"] == 0
