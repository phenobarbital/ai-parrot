"""FEAT-709 TASK-4520: runner-aware kernel datatypes."""

import dataclasses

import pytest

from parrot.flows.dev_loop.test_scope.datatypes import Invocation, RunReport, TestTarget, ValidationVerdict


def test_invocation_defaults_are_pytest() -> None:
    """Invocation defaults preserve existing pytest construction sites."""
    inv = Invocation(distribution="ai-parrot", argv=("pytest",), targets=())
    assert (inv.runner, inv.cwd, inv.report_format, inv.timeout_s) == ("pytest", ".", "junit", 0)


def test_target_runner_default() -> None:
    """Test targets default to the pytest runner."""
    assert TestTarget(path="x", distribution="d", reason="declared").runner == "pytest"


def test_run_report_failure_text_is_frozen() -> None:
    """Run-report failure text cannot mutate after construction."""
    report = RunReport(
        runner="pytest",
        suite="ai-parrot",
        tests=1,
        passed=0,
        failed=1,
        errors=0,
        skipped=0,
        duration_s=0.1,
        exit_code=1,
        status="failed",
        failure_text={"n": "t"},
    )
    with pytest.raises(TypeError):
        report.failure_text["n"] = "changed"  # type: ignore[index]


def test_verdict_is_frozen() -> None:
    """Validation verdicts are immutable payloads."""
    verdict = ValidationVerdict(schema=1, status="passed", tier="task", runners=(), failures=())
    with pytest.raises(dataclasses.FrozenInstanceError):
        verdict.status = "failed"  # type: ignore[misc]
