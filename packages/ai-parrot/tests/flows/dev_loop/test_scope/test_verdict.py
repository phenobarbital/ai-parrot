"""Tests for the language-agnostic validation verdict builder."""

from __future__ import annotations

from parrot.flows.dev_loop.test_scope.datatypes import BaselineVerdict, RunReport
from parrot.flows.dev_loop.test_scope.verdict import (
    build_verdict,
    excerpt_of,
    render_for_prompt,
    verdict_from_json,
    verdict_to_json,
)


def _failed_report(*, runner: str = "pytest", status: str = "failed") -> RunReport:
    """Return one normalized failed report for builder tests."""
    nodeid = "packages/ai-parrot/tests/test_example.py::test_failure"
    return RunReport(
        runner=runner,
        suite="ai-parrot",
        tests=1,
        passed=0,
        failed=1,
        errors=0,
        skipped=0,
        duration_s=0.25,
        exit_code=1,
        status=status,
        nodes=((nodeid, "failed"),),
        failure_text={nodeid: "\n".join(f"line {number}" for number in range(40))},
    )


def test_excerpt_of_is_bounded_to_thirty_lines() -> None:
    """Only the assertion-bearing tail is retained in a failure excerpt."""
    excerpt = excerpt_of("\n".join(f"line {number}" for number in range(40)))

    assert excerpt.splitlines() == [f"line {number}" for number in range(10, 40)]


def test_build_verdict_status_rules_and_baseline_red_pass() -> None:
    """Timeouts dominate and a fully classified baseline-red report passes."""
    report = _failed_report()
    nodeid = report.nodes[0][0]

    baseline_red = build_verdict(
        tier="task",
        reports=(report,),
        baseline=(BaselineVerdict(nodeid=nodeid, status="baseline_red"),),
    )
    new_red = build_verdict(
        tier="task",
        reports=(report,),
        baseline=(BaselineVerdict(nodeid=nodeid, status="new_red"),),
    )
    timed_out = build_verdict(
        tier="task",
        reports=(
            RunReport("pytest", "ai-parrot", 0, 0, 0, 0, 0, 1.0, 124, "timed_out"),
            report,
        ),
        baseline=(BaselineVerdict(nodeid=nodeid, status="baseline_red"),),
    )

    assert baseline_red.status == "passed"
    assert new_red.status == "failed"
    assert timed_out.status == "timed_out"
    assert len(baseline_red.failures[0].excerpt.splitlines()) == 30


def test_non_pytest_failure_is_unknown_and_noted() -> None:
    """Runners without baseline support stay red and explain the limitation."""
    verdict = build_verdict(tier="merge", reports=(_failed_report(runner="vitest"),))

    assert verdict.status == "failed"
    assert verdict.failures[0].verdict == "unknown"
    assert verdict.notes == ("no baseline for vitest",)


def test_verdict_json_roundtrip_and_prompt_rendering() -> None:
    """The JSON codec is lossless and prompt rendering has its fixed heading."""
    verdict = build_verdict(
        tier="task",
        reports=(_failed_report(),),
        cached=("packages/ai-parrot/tests/test_cached.py",),
        notes=("repair the assertion",),
        evidence=("artifacts/logs/validation/00-pytest.xml",),
    )

    restored = verdict_from_json(verdict_to_json(verdict))

    assert restored == verdict
    assert restored.runners[0].cached == 1
    assert render_for_prompt(restored).startswith("## Validation verdict\n")
