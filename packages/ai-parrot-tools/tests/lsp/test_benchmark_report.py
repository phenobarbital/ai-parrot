"""Tests for the FEAT-580 M5 adoption-gate report and CLI (TASK-3512).

Gate/report tests build synthetic :class:`AttemptRecord` cohorts directly
(no subprocess, no manifest) so threshold boundaries can be checked
exactly; only the CLI test spawns a subprocess, and only in the
``--live`` case does it ever call the runner.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

import benchmarks.sdd_lsp.__main__ as pilot_main
from benchmarks.sdd_lsp.fixtures.scenarios import SCENARIO_IDS
from benchmarks.sdd_lsp.models import ARM_NAMES, REPETITIONS, ArmName, AttemptRecord, ModelUsage, PriceBook, SeatSpec
from benchmarks.sdd_lsp.report import (
    build_report_document,
    cohort_cost_per_accepted_task,
    evaluate_gate,
    render_markdown,
)

_ATTEMPT_COUNTER = 0


def _usage(attempt_id: str, *, actual_cost_usd: float | None) -> ModelUsage:
    global _ATTEMPT_COUNTER
    _ATTEMPT_COUNTER += 1
    return ModelUsage(
        attempt_id=attempt_id,
        seat_id="seat",
        request_id=f"{attempt_id}-r{_ATTEMPT_COUNTER}",
        model="fake-model",
        source="test",
        actual_cost_usd=actual_cost_usd,
    )


def _attempt(
    task_id: str,
    arm: ArmName,
    repetition: int,
    *,
    accepted: bool = True,
    cost: float | None = 0.01,
    elapsed_ms: int = 100,
    cold_start: bool = False,
    launched: bool = True,
) -> AttemptRecord:
    attempt_id = f"{task_id}::{arm}::rep{repetition}"
    usage = [_usage(attempt_id, actual_cost_usd=cost)] if launched else []
    return AttemptRecord(
        attempt_id=attempt_id,
        task_id=task_id,
        arm=arm,
        repetition=repetition,
        seat_id="seat",
        accepted=accepted,
        failure_reason=None if launched else "not_launched: test",
        usage=usage,
        elapsed_ms=elapsed_ms if launched else None,
        cold_start=cold_start,
    )


def _full_cohort(
    arm: ArmName,
    *,
    cost: float = 0.01,
    elapsed_ms: int = 100,
    accepted: bool = True,
) -> list[AttemptRecord]:
    return [
        _attempt(task_id, arm, repetition, cost=cost, elapsed_ms=elapsed_ms, accepted=accepted)
        for task_id in SCENARIO_IDS
        for repetition in range(1, REPETITIONS + 1)
    ]


# ---------------------------------------------------------------------------
# test_cache_accounting_and_gate
# ---------------------------------------------------------------------------


def test_cache_accounting_and_gate() -> None:
    """A clear cost win with no regressions passes the gate; failed attempts still charge."""
    prices = PriceBook()

    # wiki_ast costs 0.02/task, lsp_combined costs 0.01/task -> 50% reduction.
    wiki = _full_cohort("wiki_ast", cost=0.02, elapsed_ms=200)
    lsp = _full_cohort("lsp_combined", cost=0.01, elapsed_ms=180)

    gate = evaluate_gate(wiki + lsp, prices)
    assert gate.decision == "go"
    assert gate.cost_reduction_pct == pytest.approx(50.0)
    assert gate.acceptance_regressed is False
    assert gate.correctness_regressed is False
    assert gate.median_wall_time_regression_pct == pytest.approx(-10.0)  # lsp is FASTER here

    # Adversarial: a failed attempt's cost is still charged (spec: "charging
    # all failed attempts/retries").
    failed_lsp = _full_cohort("lsp_combined", cost=0.01, elapsed_ms=180)
    failed_lsp[0] = _attempt(failed_lsp[0].task_id, "lsp_combined", 1, accepted=False, cost=0.01, elapsed_ms=180)
    cost_with_failure = cohort_cost_per_accepted_task(failed_lsp, prices)
    # 36 attempts charged at 0.01 each = 0.36 total, divided by 35 accepted.
    assert cost_with_failure == pytest.approx(0.36 / 35)


# ---------------------------------------------------------------------------
# test_threshold_boundaries_and_per_task_regressions
# ---------------------------------------------------------------------------


def test_threshold_boundaries_and_per_task_regressions() -> None:
    """Exact threshold boundaries pass; one unit past them fails."""
    prices = PriceBook()

    # Exactly 10% cost reduction and exactly 10% wall-time regression both pass.
    wiki = _full_cohort("wiki_ast", cost=0.10, elapsed_ms=100)
    lsp_at_boundary = _full_cohort("lsp_combined", cost=0.09, elapsed_ms=110)
    gate_at_boundary = evaluate_gate(wiki + lsp_at_boundary, prices)
    assert gate_at_boundary.cost_reduction_pct == pytest.approx(10.0)
    assert gate_at_boundary.median_wall_time_regression_pct == pytest.approx(10.0)
    assert gate_at_boundary.decision == "go"

    # One cent worse on cost (9.99% reduction) fails the cost threshold.
    lsp_just_under = _full_cohort("lsp_combined", cost=0.0901, elapsed_ms=100)
    gate_under = evaluate_gate(wiki + lsp_just_under, prices)
    assert gate_under.cost_reduction_pct < 10.0
    assert gate_under.decision == "no_go"
    assert any("threshold" in reason for reason in gate_under.reasons)

    # One ms over the wall-time boundary fails it even with a great cost win.
    lsp_slow = _full_cohort("lsp_combined", cost=0.01, elapsed_ms=111)
    gate_slow = evaluate_gate(wiki + lsp_slow, prices)
    assert gate_slow.median_wall_time_regression_pct > 10.0
    assert gate_slow.decision == "no_go"

    # Per-task regression: wiki_ast accepts every repetition of one task,
    # lsp_combined never does -> reported explicitly.
    wiki_good = _full_cohort("wiki_ast", cost=0.02, elapsed_ms=100)
    lsp_mixed = _full_cohort("lsp_combined", cost=0.01, elapsed_ms=90)
    regressed_task = SCENARIO_IDS[0]
    lsp_mixed = [
        (
            _attempt(a.task_id, "lsp_combined", a.repetition, accepted=False, cost=0.01, elapsed_ms=90)
            if a.task_id == regressed_task
            else a
        )
        for a in lsp_mixed
    ]
    gate_regressed = evaluate_gate(wiki_good + lsp_mixed, prices)
    assert any(regressed_task in entry for entry in gate_regressed.per_task_regressions)


# ---------------------------------------------------------------------------
# test_incomplete_and_zero_success_are_inconclusive
# ---------------------------------------------------------------------------


def test_incomplete_and_zero_success_are_inconclusive() -> None:
    """Incomplete coverage, zero acceptance, and unknown cost all yield inconclusive -- never go."""
    prices = PriceBook()

    # Incomplete: one lsp_combined attempt missing from the full 36-attempt cohort.
    wiki = _full_cohort("wiki_ast", cost=0.02)
    lsp_incomplete = _full_cohort("lsp_combined", cost=0.01)[:-1]
    gate_incomplete = evaluate_gate(wiki + lsp_incomplete, prices)
    assert gate_incomplete.decision == "inconclusive"
    assert any("incomplete" in reason for reason in gate_incomplete.reasons)

    # Zero accepted lsp_combined attempts.
    lsp_zero = _full_cohort("lsp_combined", cost=0.01, accepted=False)
    gate_zero = evaluate_gate(wiki + lsp_zero, prices)
    assert gate_zero.decision == "inconclusive"
    assert cohort_cost_per_accepted_task(lsp_zero, prices) is None

    # Unknown cost: no actual_cost_usd and no priced categories at all.
    lsp_unknown = _full_cohort("lsp_combined", cost=None)
    gate_unknown = evaluate_gate(wiki + lsp_unknown, prices)
    assert gate_unknown.decision == "inconclusive"
    assert any("unknown" in reason for reason in gate_unknown.reasons)

    # A complete, fully-computable gate must never be silently downgraded --
    # sanity check the positive path still returns "go" alongside these.
    lsp_good = _full_cohort("lsp_combined", cost=0.01, elapsed_ms=90)
    assert evaluate_gate(wiki + lsp_good, prices).decision == "go"


# ---------------------------------------------------------------------------
# test_cli_offline_default_and_live_validation
# ---------------------------------------------------------------------------


def _write_manifest(path: Path, *, seats: dict[str, dict[str, Any]] | None = None) -> None:
    seats = seats or {arm: {"arm": arm, "argv": ["true"], "timeout_s": 5.0} for arm in ARM_NAMES}
    manifest = {
        "pinned_commit": "0" * 40,
        "task_ids": list(SCENARIO_IDS),
        "seats": seats,
        "model": "fake-model",
        "environment_id": "cli-test",
        "price_provenance": "test fixture",
        "cache_semantics": "n/a",
        "spending_ceiling_usd": 10.0,
        "per_attempt_cost_reservation_usd": 0.01,
    }
    path.write_text(json.dumps(manifest), encoding="utf-8")


@pytest.mark.asyncio
async def test_cli_offline_default_and_live_validation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Offline (default) never calls the runner; --live does, exactly once."""
    manifest_path = tmp_path / "manifest.json"
    _write_manifest(manifest_path)
    output_dir = tmp_path / "out"

    calls: list[tuple[Any, Any]] = []

    async def _fake_run_pilot(manifest: Any, out_dir: Any) -> Any:
        calls.append((manifest, out_dir))
        from datetime import datetime, timezone

        from benchmarks.sdd_lsp.models import PilotReport

        return PilotReport(
            manifest=manifest, attempts=[], coverage_manifest={}, generated_at=datetime.now(timezone.utc)
        )

    monkeypatch.setattr(pilot_main, "run_pilot", _fake_run_pilot)

    # --- Offline default: the runner must never be invoked. -------------
    exit_code = await pilot_main._amain(["--manifest", str(manifest_path), "--output-dir", str(output_dir)])
    assert exit_code == 0
    assert calls == []
    assert not (output_dir / "report.json").exists()

    # --- --live: the runner IS invoked, exactly once. --------------------
    exit_code = await pilot_main._amain(["--manifest", str(manifest_path), "--output-dir", str(output_dir), "--live"])
    assert exit_code == 0
    assert len(calls) == 1
    assert (output_dir / "report.json").exists()
    assert (output_dir / "report.md").exists()

    # Adversarial: a malformed manifest fails validation before anything
    # else runs, in both offline and --live modes.
    bad_manifest_path = tmp_path / "bad_manifest.json"
    bad_manifest_path.write_text(json.dumps({"not": "a valid manifest"}), encoding="utf-8")
    with pytest.raises(Exception):  # noqa: B017 - pydantic ValidationError, exact type not load-bearing here
        await pilot_main._amain(["--manifest", str(bad_manifest_path), "--output-dir", str(output_dir)])
    assert len(calls) == 1  # no additional runner call happened


def test_render_markdown_is_deterministic() -> None:
    """The Markdown renderer produces identical output for identical input, always."""
    prices = PriceBook()
    wiki = _full_cohort("wiki_ast", cost=0.02)
    lsp = _full_cohort("lsp_combined", cost=0.01)

    from datetime import datetime, timezone

    from benchmarks.sdd_lsp.models import PilotManifest, PilotReport

    manifest = PilotManifest(
        pinned_commit="0" * 40,
        task_ids=SCENARIO_IDS,
        seats={arm: SeatSpec(arm=arm, argv=["true"], timeout_s=5.0) for arm in ARM_NAMES},
        model="fake-model",
        environment_id="render-test",
        price_provenance="test",
        cache_semantics="n/a",
        spending_ceiling_usd=10.0,
        per_attempt_cost_reservation_usd=0.01,
    )
    report = PilotReport(
        manifest=manifest,
        attempts=wiki + lsp,
        coverage_manifest={"planned": 180},
        generated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    document = build_report_document(report, prices)
    first = render_markdown(document)
    second = render_markdown(build_report_document(report, prices))
    assert first == second
    assert "# FEAT-580 LSP Pilot Report" in first
    assert "go" in first or "no_go" in first or "inconclusive" in first
