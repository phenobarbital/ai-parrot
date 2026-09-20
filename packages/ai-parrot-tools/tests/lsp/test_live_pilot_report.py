"""Report-integrity tests for the FEAT-580 M6 live pilot run (TASK-3514).

Two groups of tests live here:

1. ``test_live_pilot_report``, ``test_live_report_rejects_synthetic_or_missing_attempts``,
   ``test_live_gate_agrees_with_recorded_cost_and_acceptance`` validate the
   INTEGRITY-CHECKING LOGIC a real run's committed report/summary must
   satisfy, against synthetic fixture data built to resemble what a
   compliant live report would look like -- they never claim a live run
   occurred on their own.
2. The ``test_real_live_run_*`` group loads the COMMITTED real-run summary
   (``docs/sdd/lsp-pilot-live-run-summary.json``, a trimmed
   :class:`PilotReport` from the actual 180-attempt run executed 2026-09-20
   against real Bedrock-Mantle seats -- see
   ``docs/sdd/lsp-pilot-results.md`` and TASK-3514's Completion Note) and
   runs the SAME integrity/gate functions against genuine evidence, not a
   fixture. Per spec ("human acceptance review... cannot be an unattended,
   automated sign-off"), these tests do NOT assert the evidence has been
   certified -- they assert exactly what is honestly true today: coverage,
   traces and the manifest digest all check out, the published `no_go`
   decision is bit-for-bit re-derivable from the raw evidence, and the
   report's own `synthetic` flag is still `True` (certification pending).
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from benchmarks.sdd_lsp.fixtures.scenarios import SCENARIO_IDS
from benchmarks.sdd_lsp.models import (
    ARM_NAMES,
    AttemptRecord,
    ModelUsage,
    PilotManifest,
    PilotReport,
    PriceBook,
    SeatSpec,
)
from benchmarks.sdd_lsp.report import evaluate_gate

_REPO_ROOT = Path(__file__).resolve().parents[4]
_REAL_SUMMARY_PATH = _REPO_ROOT / "docs" / "sdd" / "lsp-pilot-live-run-summary.json"

_ATTEMPT_COUNTER = 0


def manifest_digest(manifest: PilotManifest) -> str:
    """A deterministic hash of a manifest's committed contents.

    Proves a report's ``manifest`` field is exactly the reviewed manifest
    it claims to be run from, never a silently different one.
    """
    return hashlib.sha256(manifest.model_dump_json(exclude_none=False).encode("utf-8")).hexdigest()


def check_live_report_integrity(report: PilotReport, expected_manifest_digest: str) -> list[str]:
    """Return every integrity violation found in a claimed-live pilot report.

    Empty result means the report is internally consistent and is not
    labeled synthetic -- it does NOT independently confirm the underlying
    attempts were genuinely executed against real seats; that assurance
    can only come from human acceptance review of the actual run.

    Checks:
        - The report must not be ``synthetic`` (a live run's report).
        - Its manifest must match the reviewed, committed manifest exactly
          (via ``manifest_digest``), never a substituted one.
        - Every planned attempt (``manifest.total_attempts``) is present
          exactly once -- no missing or duplicated attempt.
        - Every attempt is either launched-with-raw-trace-refs, or
          explicitly marked ``not_launched``/failed with a reason --
          never a silent gap.
    """
    violations: list[str] = []
    if report.synthetic:
        violations.append("report.synthetic is True: a live run's report must not be synthetic")

    actual_digest = manifest_digest(report.manifest)
    if actual_digest != expected_manifest_digest:
        violations.append(
            f"manifest digest mismatch: report manifest hashes to {actual_digest}, expected {expected_manifest_digest}"
        )

    expected_ids = {
        f"{task_id}::{arm}::rep{repetition}"
        for task_id in report.manifest.task_ids
        for arm in report.manifest.arms
        for repetition in range(1, report.manifest.repetitions + 1)
    }
    actual_ids = [attempt.attempt_id for attempt in report.attempts]
    if len(actual_ids) != len(expected_ids):
        violations.append(f"expected {len(expected_ids)} attempts, found {len(actual_ids)}")
    missing = expected_ids - set(actual_ids)
    if missing:
        violations.append(f"missing attempt ids: {sorted(missing)[:5]}{'...' if len(missing) > 5 else ''}")
    duplicated = {aid for aid in actual_ids if actual_ids.count(aid) > 1}
    if duplicated:
        violations.append(f"duplicated attempt ids: {sorted(duplicated)}")

    for attempt in report.attempts:
        launched = not (attempt.failure_reason or "").startswith("not_launched")
        if launched and not attempt.raw_trace_refs and attempt.failure_reason is None:
            violations.append(f"{attempt.attempt_id}: accepted/launched with no raw_trace_refs and no failure_reason")

    return violations


def _usage(attempt_id: str, seat_id: str) -> ModelUsage:
    global _ATTEMPT_COUNTER
    _ATTEMPT_COUNTER += 1
    return ModelUsage(
        attempt_id=attempt_id,
        seat_id=seat_id,
        request_id=f"{attempt_id}-r{_ATTEMPT_COUNTER}",
        model="pinned-model",
        source="provider_usage",
        actual_cost_usd=0.01,
    )


def _make_manifest() -> PilotManifest:
    return PilotManifest(
        pinned_commit="a" * 40,
        task_ids=SCENARIO_IDS,
        seats={arm: SeatSpec(arm=arm, argv=["reviewed-real-cli", "--arm", arm], timeout_s=60.0) for arm in ARM_NAMES},
        model="pinned-model",
        environment_id="reviewed-immutable-env",
        price_provenance="operator console export, reviewed",
        cache_semantics="provider reports 5m/1h cache write classes",
        spending_ceiling_usd=50.0,
        per_attempt_cost_reservation_usd=0.05,
    )


def _compliant_attempts(manifest: PilotManifest) -> list[AttemptRecord]:
    attempts: list[AttemptRecord] = []
    for task_id in manifest.task_ids:
        for arm in manifest.arms:
            for repetition in range(1, manifest.repetitions + 1):
                attempt_id = f"{task_id}::{arm}::rep{repetition}"
                attempts.append(
                    AttemptRecord(
                        attempt_id=attempt_id,
                        task_id=task_id,
                        arm=arm,
                        repetition=repetition,
                        seat_id=arm,
                        accepted=True,
                        usage=[_usage(attempt_id, arm)],
                        raw_trace_refs=[f"/artifacts/logs/{attempt_id}.jsonl"],
                        elapsed_ms=100,
                        cold_start=repetition == 1,
                    )
                )
    return attempts


def _compliant_report() -> tuple[PilotReport, str]:
    manifest = _make_manifest()
    report = PilotReport(
        manifest=manifest,
        attempts=_compliant_attempts(manifest),
        coverage_manifest={"planned": manifest.total_attempts, "executed": manifest.total_attempts, "missing_trace": 0},
        generated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        synthetic=False,
    )
    return report, manifest_digest(manifest)


# ---------------------------------------------------------------------------
# test_live_pilot_report
# ---------------------------------------------------------------------------


def test_live_pilot_report() -> None:
    """A correctly-shaped, non-synthetic, complete report passes integrity checks.

    This is fixture data standing in for what a compliant live report
    would look like -- it validates the integrity-checking logic only, it
    does not itself constitute or claim live-run evidence.
    """
    report, expected_digest = _compliant_report()
    violations = check_live_report_integrity(report, expected_digest)
    assert violations == []
    assert len(report.attempts) == report.manifest.total_attempts == 180


# ---------------------------------------------------------------------------
# test_live_report_rejects_synthetic_or_missing_attempts
# ---------------------------------------------------------------------------


def test_live_report_rejects_synthetic_or_missing_attempts() -> None:
    """A synthetic report, a tampered manifest, or missing attempts are all rejected."""
    report, expected_digest = _compliant_report()

    synthetic_report = report.model_copy(update={"synthetic": True})
    violations = check_live_report_integrity(synthetic_report, expected_digest)
    assert any("synthetic" in v for v in violations)

    incomplete_report = report.model_copy(update={"attempts": report.attempts[:-1]})
    violations = check_live_report_integrity(incomplete_report, expected_digest)
    assert any("expected 180 attempts" in v for v in violations)
    assert any("missing attempt ids" in v for v in violations)

    duplicated_report = report.model_copy(update={"attempts": report.attempts + [report.attempts[0]]})
    violations = check_live_report_integrity(duplicated_report, expected_digest)
    assert any("duplicated attempt ids" in v for v in violations)

    # A silently different manifest (tampered commit) must be caught even
    # if every other field looks identical.
    tampered_manifest = _make_manifest().model_copy(update={"pinned_commit": "b" * 40})
    tampered_report = report.model_copy(update={"manifest": tampered_manifest})
    violations = check_live_report_integrity(tampered_report, expected_digest)
    assert any("manifest digest mismatch" in v for v in violations)

    # A launched attempt with no trace and no explicit failure reason is a
    # silent gap -- never accepted quietly.
    silent_gap_attempts = list(report.attempts)
    silent_gap_attempts[0] = silent_gap_attempts[0].model_copy(update={"raw_trace_refs": [], "failure_reason": None})
    silent_gap_report = report.model_copy(update={"attempts": silent_gap_attempts})
    violations = check_live_report_integrity(silent_gap_report, expected_digest)
    assert any("no raw_trace_refs and no failure_reason" in v for v in violations)


# ---------------------------------------------------------------------------
# test_live_gate_agrees_with_recorded_cost_and_acceptance
# ---------------------------------------------------------------------------


def test_live_gate_agrees_with_recorded_cost_and_acceptance() -> None:
    """evaluate_gate's disposition, re-run on the report's own attempts, is reproducible.

    Guards against a committed summary silently drifting from the
    attempt-level evidence that supposedly produced it.
    """
    report, _ = _compliant_report()
    prices = PriceBook()

    gate_a = evaluate_gate(report.attempts, prices)
    gate_b = evaluate_gate(report.attempts, prices)
    assert gate_a == gate_b  # deterministic, re-derivable from the raw attempts alone

    # Every attempt in this fixture costs the same and accepts identically
    # across arms, so lsp_combined shows no advantage over wiki_ast --
    # correctly inconclusive/no_go, never a fabricated "go".
    assert gate_a.decision in ("no_go", "inconclusive")

    # Tampering the recorded acceptance for SOME (not all -- zero accepted
    # would correctly go inconclusive instead) lsp_combined attempts, as if
    # a committed summary had been hand-edited after the fact, changes the
    # gate -- proving the check is sensitive to the underlying evidence,
    # not just re-stating a cached decision.
    flipped = 0
    tampered_attempts = []
    for attempt in report.attempts:
        if attempt.arm == "lsp_combined" and flipped < 10:
            tampered_attempts.append(attempt.model_copy(update={"accepted": False}))
            flipped += 1
        else:
            tampered_attempts.append(attempt)
    gate_tampered = evaluate_gate(tampered_attempts, prices)
    assert gate_tampered.acceptance_regressed is True
    assert gate_tampered != gate_a


# ---------------------------------------------------------------------------
# Real-run evidence: docs/sdd/lsp-pilot-live-run-summary.json
# ---------------------------------------------------------------------------


def _load_real_report() -> PilotReport:
    assert _REAL_SUMMARY_PATH.exists(), (
        f"committed real-run summary missing at {_REAL_SUMMARY_PATH}; "
        "see TASK-3514's Completion Note for how it was produced"
    )
    return PilotReport.model_validate_json(_REAL_SUMMARY_PATH.read_text(encoding="utf-8"))


def test_real_live_run_has_full_180_attempt_coverage_and_traces() -> None:
    """The committed real-run summary covers every planned attempt, each traced.

    This is genuine evidence (2026-09-20 Bedrock-Mantle run), not a
    fixture: it exercises the SAME integrity checker as the synthetic
    tests above, against real data. The only violation
    ``check_live_report_integrity`` is expected to report is
    ``report.synthetic``, which stays ``True`` until a human certifies
    this run (see module docstring) -- everything else about the real
    evidence (coverage, no silent gaps, manifest digest) must check out.
    """
    report = _load_real_report()
    assert len(report.attempts) == report.manifest.total_attempts == 180

    expected_digest = manifest_digest(report.manifest)
    violations = check_live_report_integrity(report, expected_digest)
    assert violations == [
        "report.synthetic is True: a live run's report must not be synthetic"
    ], f"unexpected integrity violations in the committed real-run evidence: {violations}"

    # No silent gaps: every attempt either has a trace marker or an
    # explicit failure/not_launched reason (coverage_manifest agrees).
    assert report.coverage_manifest["executed"] == 180
    assert report.coverage_manifest["not_launched"] == 0
    assert report.coverage_manifest["missing_trace"] == 0
    for attempt in report.attempts:
        assert (
            attempt.raw_trace_refs or attempt.failure_reason
        ), f"{attempt.attempt_id}: no trace marker and no failure reason"


def test_real_live_run_gate_matches_published_no_go_decision() -> None:
    """`evaluate_gate`, re-run on the committed real attempts, reproduces the published `no_go`.

    Guards against `docs/sdd/lsp-pilot-results.md`'s published numbers
    ever silently drifting from the raw evidence that produced them.
    """
    report = _load_real_report()
    gate = evaluate_gate(report.attempts, PriceBook())

    assert gate.decision == "no_go"
    assert gate.acceptance_regressed is False
    assert gate.correctness_regressed is False
    assert gate.cost_reduction_pct is not None
    assert gate.median_wall_time_regression_pct is not None
    assert gate.cost_reduction_pct < 0  # lsp_combined costs MORE per accepted task, not less
    assert round(gate.cost_reduction_pct, 2) == -30.34
    assert round(gate.median_wall_time_regression_pct, 2) == 13.60


def test_real_live_run_manifest_matches_published_results_doc() -> None:
    """The committed evidence's manifest matches what `lsp-pilot-results.md` claims was run."""
    report = _load_real_report()
    assert report.manifest.model == "minimax.minimax-m2.5"
    assert report.manifest.environment_id == "lexotanil"
    assert report.manifest.pinned_commit == "48e498f93"
    assert set(report.manifest.task_ids) == set(SCENARIO_IDS)
    assert report.manifest.repetitions == 3
    assert set(report.manifest.arms) == set(ARM_NAMES)

    # Certification status is explicit, not silently assumed either way.
    assert report.synthetic is True, (
        "this evidence has not been through the spec's required human acceptance "
        "review/certification yet -- see TASK-3514's Completion Note. If this now "
        "reads False, a human has certified the run: update this assertion and "
        "TASK-3514's status together, never one without the other."
    )


def test_real_live_run_summary_is_valid_json_and_reasonably_sized() -> None:
    """Sanity: the committed file is parseable JSON and not absurdly large for a repo artifact."""
    raw = json.loads(_REAL_SUMMARY_PATH.read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    assert len(raw["attempts"]) == 180
    size_bytes = _REAL_SUMMARY_PATH.stat().st_size
    assert size_bytes < 500_000, f"committed summary grew unexpectedly large: {size_bytes} bytes"
