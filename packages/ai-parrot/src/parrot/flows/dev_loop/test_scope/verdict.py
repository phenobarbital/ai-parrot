"""Validation verdict: the only test payload a coder seat sees (FEAT-709 M5). Stdlib only."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from .datatypes import BaselineVerdict, Failure, RunReport, RunnerSummary, ValidationVerdict
from .runners.base import EXCERPT_MAX_LINES

VERDICT_SCHEMA: int = 1


def excerpt_of(text: str, *, max_lines: int = EXCERPT_MAX_LINES) -> str:
    """Return the last ``max_lines`` lines (the traceback tail carries the assertion)."""
    lines = text.rstrip().splitlines()
    return "\n".join(lines[-max_lines:])


def _cached_count(report: RunReport, cached: Sequence[str]) -> int:
    """Count cached pytest targets owned by the report's distribution."""
    if report.runner != "pytest":
        return 0
    suite = report.suite.split("[", 1)[0].split(":", 1)[-1]
    if suite == "root":
        return sum(not target.startswith("packages/") for target in cached)
    prefix = f"packages/{suite}/"
    return sum(target.startswith(prefix) for target in cached)


def build_verdict(
    *,
    tier: str,
    reports: Sequence[RunReport],
    baseline: Sequence[BaselineVerdict] = (),
    cached: Sequence[str] = (),
    notes: Sequence[str] = (),
    evidence: Sequence[str] = (),
) -> ValidationVerdict:
    """Build a verdict with status precedence timed_out > failed > passed.

    Pytest failures classified entirely as baseline-red are allowed to pass.
    Other runner failures are always unknown because no baseline applies.
    """
    baseline_by_node = {item.nodeid: item.status for item in baseline}
    summaries: list[RunnerSummary] = []
    failures: list[Failure] = []
    verdict_notes = list(notes)
    runners_without_baseline: set[str] = set()
    has_unclassified_failure = False

    for report in reports:
        summaries.append(
            RunnerSummary(
                runner=report.runner,
                suite=report.suite,
                tests=report.tests,
                passed=report.passed,
                failed=report.failed,
                errors=report.errors,
                skipped=report.skipped,
                cached=_cached_count(report, cached),
                duration_s=report.duration_s,
                exit_code=report.exit_code,
                status=report.status,
            )
        )

        failed_nodes = [(nodeid, status) for nodeid, status in report.nodes if status in {"failed", "error"}]
        for nodeid, _node_status in failed_nodes:
            classification = "unknown"
            if report.runner == "pytest":
                candidate = baseline_by_node.get(nodeid, "unknown")
                if candidate in {"new_red", "baseline_red", "unknown"}:
                    classification = candidate
            else:
                runners_without_baseline.add(report.runner)
            failures.append(
                Failure(
                    runner=report.runner,
                    nodeid=nodeid,
                    verdict=classification,
                    excerpt=excerpt_of(report.failure_text.get(nodeid, "")),
                )
            )

        reported_failures = report.failed + report.errors
        if report.unmapped or reported_failures > len(failed_nodes):
            has_unclassified_failure = True
        if report.status in {"unavailable", "no_report"} and report.exit_code != 0:
            has_unclassified_failure = True
        if report.status == "failed" and not failed_nodes:
            has_unclassified_failure = True
        if report.exit_code != 0 and not failed_nodes and report.status != "timed_out":
            has_unclassified_failure = True

    for runner in sorted(runners_without_baseline):
        verdict_notes.append(f"no baseline for {runner}")

    if any(report.status == "timed_out" for report in reports):
        status = "timed_out"
    elif has_unclassified_failure or any(failure.verdict != "baseline_red" for failure in failures):
        status = "failed"
    else:
        status = "passed"

    return ValidationVerdict(
        schema=VERDICT_SCHEMA,
        status=status,
        tier=tier,
        runners=tuple(summaries),
        failures=tuple(failures),
        cached=tuple(cached),
        notes=tuple(verdict_notes),
        evidence=tuple(evidence),
    )


def verdict_to_json(verdict: ValidationVerdict) -> dict[str, object]:
    """Convert a verdict to a JSON-compatible dictionary."""
    return {
        "schema": verdict.schema,
        "status": verdict.status,
        "tier": verdict.tier,
        "runners": [
            {
                "runner": runner.runner,
                "suite": runner.suite,
                "tests": runner.tests,
                "passed": runner.passed,
                "failed": runner.failed,
                "errors": runner.errors,
                "skipped": runner.skipped,
                "cached": runner.cached,
                "duration_s": runner.duration_s,
                "exit_code": runner.exit_code,
                "status": runner.status,
            }
            for runner in verdict.runners
        ],
        "failures": [
            {
                "runner": failure.runner,
                "nodeid": failure.nodeid,
                "verdict": failure.verdict,
                "excerpt": failure.excerpt,
            }
            for failure in verdict.failures
        ],
        "cached": list(verdict.cached),
        "notes": list(verdict.notes),
        "evidence": list(verdict.evidence),
    }


def _mapping_list(payload: Mapping[str, object], key: str) -> tuple[Mapping[str, object], ...]:
    """Read a sequence of mappings from a verdict payload."""
    value = payload.get(key, ())
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"verdict field {key!r} must be a list")
    if not all(isinstance(item, Mapping) for item in value):
        raise ValueError(f"verdict field {key!r} must contain objects")
    return tuple(value)


def _string_list(payload: Mapping[str, object], key: str) -> tuple[str, ...]:
    """Read a sequence of strings from a verdict payload."""
    value = payload.get(key, ())
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or not all(
        isinstance(item, str) for item in value
    ):
        raise ValueError(f"verdict field {key!r} must be a list of strings")
    return tuple(value)


def verdict_from_json(payload: Mapping[str, object]) -> ValidationVerdict:
    """Restore a validation verdict from its JSON-compatible dictionary."""
    runners = tuple(
        RunnerSummary(
            runner=str(item["runner"]),
            suite=str(item["suite"]),
            tests=int(item["tests"]),
            passed=int(item["passed"]),
            failed=int(item["failed"]),
            errors=int(item["errors"]),
            skipped=int(item["skipped"]),
            cached=int(item["cached"]),
            duration_s=float(item["duration_s"]),
            exit_code=int(item["exit_code"]),
            status=str(item["status"]),
        )
        for item in _mapping_list(payload, "runners")
    )
    failures = tuple(
        Failure(
            runner=str(item["runner"]),
            nodeid=str(item["nodeid"]),
            verdict=str(item["verdict"]),
            excerpt=str(item["excerpt"]),
        )
        for item in _mapping_list(payload, "failures")
    )
    return ValidationVerdict(
        schema=int(payload["schema"]),
        status=str(payload["status"]),
        tier=str(payload["tier"]),
        runners=runners,
        failures=failures,
        cached=_string_list(payload, "cached"),
        notes=_string_list(payload, "notes"),
        evidence=_string_list(payload, "evidence"),
    )


def render_for_prompt(verdict: ValidationVerdict) -> str:
    """Render a deterministic markdown verdict block for a repair prompt."""
    lines = [
        "## Validation verdict",
        "",
        f"Status: `{verdict.status}`",
        f"Tier: `{verdict.tier}`",
        "",
        "### Runners",
    ]
    if verdict.runners:
        for runner in verdict.runners:
            lines.append(
                f"- `{runner.runner}:{runner.suite}`: {runner.passed} passed, "
                f"{runner.failed} failed, {runner.errors} errors, {runner.skipped} skipped, "
                f"{runner.cached} cached ({runner.status}, exit {runner.exit_code})"
            )
    else:
        lines.append("- none")

    if verdict.failures:
        lines.extend(("", "### Failures"))
        for failure in verdict.failures:
            lines.append(f"- `{failure.verdict}` `{failure.runner}` `{failure.nodeid}`")
            if failure.excerpt:
                lines.extend(("", "```text", failure.excerpt, "```"))
    if verdict.notes:
        lines.extend(("", "### Notes", *(f"- {note}" for note in verdict.notes)))
    if verdict.evidence:
        lines.extend(("", "### Evidence", *(f"- `{path}`" for path in verdict.evidence)))
    return "\n".join(lines)
