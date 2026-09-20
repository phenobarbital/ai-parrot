"""Report-integrity tests for the FEAT-580 M6 live pilot run (TASK-3514).

No live, audited 180-attempt run has been executed in this implementation
session: M6 is explicitly not delegation-eligible (spec §3 Module
Breakdown: "Requires provisioned CLI seats, actual usage/pricing, and
human acceptance review; results cannot be manufactured"), and no
operator-reviewed manifest, real CLI seats, real prices, or spending
ceiling were available. Every test here validates the INTEGRITY-CHECKING
LOGIC a real run's committed report/summary must satisfy, against
synthetic fixture data built to resemble what a compliant live report
would look like -- it never claims a live run occurred (see
``docs/sdd/lsp-pilot-results.md`` for the honest, unfinished status).
"""

from __future__ import annotations

import hashlib
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
