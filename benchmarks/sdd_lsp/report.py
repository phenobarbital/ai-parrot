"""Adoption-gate evaluation and deterministic reports (FEAT-580 M5, spec §3 Module 5).

``evaluate_gate`` never invents a price, never weakens the approved
threshold, and never lets an incomplete or zero-success cohort pass:
unknown cost, incomplete arm coverage, or zero accepted attempts in either
compared arm always resolve to ``"inconclusive"``, never ``"go"``.

Comparison is always ``lsp_combined`` against ``wiki_ast`` (spec §2:
"Compare B-combined against wiki_ast, not current").

**Correctness signal.** :class:`~benchmarks.sdd_lsp.models.AttemptRecord`
carries exactly one pass/fail signal (``accepted``); this module does not
invent a second, independent "correctness" channel. ``correctness_regressed``
therefore always mirrors ``acceptance_regressed`` here -- both observations
of the same underlying acceptance data, reported under the gate's two
named fields per spec §2's "no observed acceptance-rate/correctness
regression" phrasing.
"""

from __future__ import annotations

import json
import statistics
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

from benchmarks.sdd_lsp.models import (
    ARM_NAMES,
    REPETITIONS,
    TASK_COUNT,
    AttemptRecord,
    GateResult,
    PilotReport,
    PriceBook,
)
from benchmarks.sdd_lsp.runner import effective_attempt_cost_usd

__all__ = (
    "build_report_document",
    "cohort_cost_per_accepted_task",
    "evaluate_gate",
    "render_markdown",
    "write_reports",
)

#: The two arms the adoption gate compares (spec §2: "Compare B-combined
#: against wiki_ast, not current").
_GATE_COST_REDUCTION_THRESHOLD_PCT = 10.0
_GATE_WALL_TIME_REGRESSION_THRESHOLD_PCT = 10.0


def _is_launched(attempt: AttemptRecord) -> bool:
    return not (attempt.failure_reason or "").startswith("not_launched")


def cohort_cost_per_accepted_task(attempts: list[AttemptRecord], prices: PriceBook) -> Optional[float]:
    """Total cohort cost (charging every attempt) divided by its accepted count.

    Args:
        attempts: Every launched attempt in one arm's cohort.
        prices: The configured cache-aware price table.

    Returns:
        ``total_cost / accepted_count``, or ``None`` if zero attempts were
        accepted or any contributing attempt's cost is unknown (spec §2:
        "if zero accepted or any cost unknown, metric/gate is
        inconclusive").
    """
    accepted_count = sum(1 for attempt in attempts if attempt.accepted)
    if accepted_count == 0:
        return None
    total = Decimal("0")
    for attempt in attempts:
        cost = effective_attempt_cost_usd(attempt, prices)
        if cost is None:
            return None
        total += Decimal(str(cost))
    return float(total / accepted_count)


def _median(values: list[int]) -> Optional[float]:
    return float(statistics.median(values)) if values else None


def _p95(values: list[int]) -> Optional[float]:
    if not values:
        return None
    if len(values) == 1:
        return float(values[0])
    ordered = sorted(values)
    # Nearest-rank method: the smallest value at or above the 95th
    # percentile rank, 1-based (deterministic, no interpolation surprises).
    rank = max(1, -(-95 * len(ordered) // 100))  # ceil(95 * n / 100)
    return float(ordered[rank - 1])


def evaluate_gate(attempts: list[AttemptRecord], prices: PriceBook) -> GateResult:
    """Return the FEAT-580 adoption-gate disposition for one pilot's attempts.

    Args:
        attempts: Every :class:`AttemptRecord` from a :class:`PilotReport`
            (any arm; only ``lsp_combined``/``wiki_ast`` are compared).
        prices: The configured cache-aware price table.

    Returns:
        A :class:`GateResult`. ``"go"`` only when every required metric is
        computable AND meets its approved threshold; incomplete coverage,
        unknown cost, or zero accepted attempts in either compared arm
        always yield ``"inconclusive"``, never a passing ``"go"``.
    """
    reasons: list[str] = []
    per_task_regressions: list[str] = []

    lsp = [a for a in attempts if a.arm == "lsp_combined" and _is_launched(a)]
    wiki = [a for a in attempts if a.arm == "wiki_ast" and _is_launched(a)]

    expected_per_arm = TASK_COUNT * REPETITIONS
    if len(lsp) < expected_per_arm or len(wiki) < expected_per_arm:
        reasons.append(
            f"incomplete arm coverage: lsp_combined has {len(lsp)}/{expected_per_arm}, "
            f"wiki_ast has {len(wiki)}/{expected_per_arm} launched attempts"
        )
        return GateResult(decision="inconclusive", reasons=reasons)

    lsp_cost = cohort_cost_per_accepted_task(lsp, prices)
    wiki_cost = cohort_cost_per_accepted_task(wiki, prices)
    if lsp_cost is None or wiki_cost is None:
        reasons.append(
            "cost per accepted task is unknown for lsp_combined or wiki_ast (zero accepted, or unknown usage)"
        )
        return GateResult(decision="inconclusive", reasons=reasons)
    if wiki_cost == 0:
        reasons.append("wiki_ast cost per accepted task is zero; a cost-reduction percentage is undefined")
        return GateResult(decision="inconclusive", reasons=reasons)

    lsp_times = [a.elapsed_ms for a in lsp if a.elapsed_ms is not None]
    wiki_times = [a.elapsed_ms for a in wiki if a.elapsed_ms is not None]
    if not lsp_times or not wiki_times:
        reasons.append("wall-time is unknown for lsp_combined or wiki_ast")
        return GateResult(decision="inconclusive", reasons=reasons)

    cost_reduction_pct = (wiki_cost - lsp_cost) / wiki_cost * 100.0

    lsp_accept_rate = sum(1 for a in lsp if a.accepted) / len(lsp)
    wiki_accept_rate = sum(1 for a in wiki if a.accepted) / len(wiki)
    acceptance_regressed = lsp_accept_rate < wiki_accept_rate
    correctness_regressed = acceptance_regressed  # same underlying signal, see module docstring

    lsp_median = statistics.median(lsp_times)
    wiki_median = statistics.median(wiki_times)
    median_wall_time_regression_pct = 0.0 if wiki_median == 0 else (lsp_median - wiki_median) / wiki_median * 100.0

    for task_id in sorted({a.task_id for a in wiki}):
        wiki_task_accepted = all(a.accepted for a in wiki if a.task_id == task_id)
        lsp_task_attempts = [a for a in lsp if a.task_id == task_id]
        lsp_task_accepted = bool(lsp_task_attempts) and all(a.accepted for a in lsp_task_attempts)
        if wiki_task_accepted and not lsp_task_accepted:
            per_task_regressions.append(f"{task_id}: accepted under wiki_ast but not under lsp_combined")

    meets_cost = cost_reduction_pct >= _GATE_COST_REDUCTION_THRESHOLD_PCT
    meets_wall_time = median_wall_time_regression_pct <= _GATE_WALL_TIME_REGRESSION_THRESHOLD_PCT
    meets_acceptance = not acceptance_regressed
    meets_correctness = not correctness_regressed

    if meets_cost and meets_wall_time and meets_acceptance and meets_correctness:
        decision = "go"
        reasons.append(
            f"cost_reduction_pct={cost_reduction_pct:.2f} >= {_GATE_COST_REDUCTION_THRESHOLD_PCT:g}%, "
            "no acceptance/correctness regression, "
            f"median_wall_time_regression_pct={median_wall_time_regression_pct:.2f} "
            f"<= {_GATE_WALL_TIME_REGRESSION_THRESHOLD_PCT:g}%"
        )
    else:
        decision = "no_go"
        if not meets_cost:
            reasons.append(
                f"cost_reduction_pct={cost_reduction_pct:.2f} below the "
                f"{_GATE_COST_REDUCTION_THRESHOLD_PCT:g}% threshold"
            )
        if not meets_wall_time:
            reasons.append(
                f"median_wall_time_regression_pct={median_wall_time_regression_pct:.2f} exceeds the "
                f"{_GATE_WALL_TIME_REGRESSION_THRESHOLD_PCT:g}% threshold"
            )
        if acceptance_regressed:
            reasons.append(
                f"acceptance-rate regression observed: lsp_combined={lsp_accept_rate:.2%} "
                f"< wiki_ast={wiki_accept_rate:.2%}"
            )
        if correctness_regressed:
            reasons.append("correctness regression observed (same underlying signal as acceptance)")

    return GateResult(
        decision=decision,
        cost_reduction_pct=cost_reduction_pct,
        acceptance_regressed=acceptance_regressed,
        correctness_regressed=correctness_regressed,
        median_wall_time_regression_pct=median_wall_time_regression_pct,
        reasons=reasons,
        per_task_regressions=per_task_regressions,
    )


def _arm_summary(attempts: list[AttemptRecord], prices: PriceBook) -> dict[str, Any]:
    launched = [a for a in attempts if _is_launched(a)]
    accepted = [a for a in launched if a.accepted]
    times = [a.elapsed_ms for a in launched if a.elapsed_ms is not None]
    cold_times = [a.elapsed_ms for a in launched if a.cold_start and a.elapsed_ms is not None]
    warm_times = [a.elapsed_ms for a in launched if not a.cold_start and a.elapsed_ms is not None]
    return {
        "planned": len(attempts),
        "launched": len(launched),
        "accepted": len(accepted),
        "acceptance_rate": (len(accepted) / len(launched)) if launched else None,
        "cost_per_accepted_task_usd": cohort_cost_per_accepted_task(launched, prices),
        "median_elapsed_ms": _median(times),
        "p95_elapsed_ms": _p95(times),
        "median_cold_elapsed_ms": _median(cold_times),
        "median_warm_elapsed_ms": _median(warm_times),
        "correction_cycles_total": sum(a.correction_cycles for a in launched),
        "retries_total": sum(a.retries for a in launched),
    }


def build_report_document(report: PilotReport, prices: PriceBook) -> dict[str, Any]:
    """Build the deterministic, JSON-serializable pilot report document.

    Args:
        report: A :class:`PilotReport` from :func:`benchmarks.sdd_lsp.runner.run_pilot`.
        prices: The configured cache-aware price table.

    Returns:
        A dict containing the gate disposition, per-arm pooled totals
        (medians/p95, correction cycles, cold/warm timings), and per-task
        paired outcomes across every arm -- never dropping a missing
        trace or an unsuccessful attempt (spec §2: "Store deterministic
        summary JSON/Markdown plus a coverage manifest; missing traces
        must not be silently dropped").
    """
    gate = evaluate_gate(report.attempts, prices)
    by_arm: dict[str, list[AttemptRecord]] = {arm: [a for a in report.attempts if a.arm == arm] for arm in ARM_NAMES}
    arm_summaries = {arm: _arm_summary(attempts, prices) for arm, attempts in by_arm.items()}

    per_task: dict[str, dict[str, Optional[bool]]] = {}
    for task_id in report.manifest.task_ids:
        row: dict[str, Optional[bool]] = {}
        for arm in ARM_NAMES:
            task_attempts = [a for a in by_arm[arm] if a.task_id == task_id and _is_launched(a)]
            row[arm] = all(a.accepted for a in task_attempts) if task_attempts else None
        per_task[task_id] = row

    return {
        "generated_at": report.generated_at.isoformat(),
        "synthetic": report.synthetic,
        "pinned_commit": report.manifest.pinned_commit,
        "coverage_manifest": report.coverage_manifest,
        "gate": gate.model_dump(mode="json"),
        "arms": arm_summaries,
        "per_task_paired_outcomes": per_task,
    }


def render_markdown(document: dict[str, Any]) -> str:
    """Render :func:`build_report_document`'s output as a deterministic Markdown report."""
    gate = document["gate"]
    lines: list[str] = [
        "# FEAT-580 LSP Pilot Report",
        "",
        f"- Generated at: {document['generated_at']}",
        f"- Synthetic (offline/fixture-produced): {document['synthetic']}",
        f"- Pinned commit: {document['pinned_commit']}",
        "",
        "## Adoption Gate",
        "",
        f"- **Decision**: `{gate['decision']}`",
        f"- Cost reduction (lsp_combined vs wiki_ast): {gate['cost_reduction_pct']!r}%",
        f"- Acceptance regressed: {gate['acceptance_regressed']!r}",
        f"- Correctness regressed: {gate['correctness_regressed']!r}",
        f"- Median wall-time regression: {gate['median_wall_time_regression_pct']!r}%",
        "",
        "### Reasons",
        "",
    ]
    if gate["reasons"]:
        lines.extend(f"- {reason}" for reason in gate["reasons"])
    else:
        lines.append("- (none)")
    lines.append("")
    lines.append("### Per-task regressions")
    lines.append("")
    if gate["per_task_regressions"]:
        lines.extend(f"- {entry}" for entry in gate["per_task_regressions"])
    else:
        lines.append("- (none)")
    lines.append("")
    lines.append("## Per-arm summary")
    lines.append("")
    lines.append(
        "| Arm | Planned | Launched | Accepted | Acceptance rate | Cost/accepted task (USD) | Median ms | p95 ms |"
    )
    lines.append("|---|---|---|---|---|---|---|---|")
    for arm in ARM_NAMES:
        summary = document["arms"][arm]
        lines.append(
            f"| {arm} | {summary['planned']} | {summary['launched']} | {summary['accepted']} | "
            f"{summary['acceptance_rate']!r} | {summary['cost_per_accepted_task_usd']!r} | "
            f"{summary['median_elapsed_ms']!r} | {summary['p95_elapsed_ms']!r} |"
        )
    lines.append("")
    lines.append("## Per-task paired outcomes")
    lines.append("")
    header = "| Task | " + " | ".join(ARM_NAMES) + " |"
    lines.append(header)
    lines.append("|---|" + "---|" * len(ARM_NAMES))
    for task_id, row in document["per_task_paired_outcomes"].items():
        lines.append(f"| {task_id} | " + " | ".join(repr(row[arm]) for arm in ARM_NAMES) + " |")
    lines.append("")
    return "\n".join(lines)


def write_reports(document: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    """Write ``report.json`` and ``report.md`` deterministically under ``output_dir``.

    Args:
        document: The output of :func:`build_report_document`.
        output_dir: Directory the two report files are written into.

    Returns:
        ``(json_path, md_path)``.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "report.json"
    md_path = output_dir / "report.md"
    json_path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(document), encoding="utf-8")
    return json_path, md_path
