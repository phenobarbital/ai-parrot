"""Tests for the FEAT-709 pytest runner adapter."""

from __future__ import annotations

from pathlib import Path

import pytest

from parrot.flows.dev_loop.test_scope.datatypes import TestContract, TestTarget
from parrot.flows.dev_loop.test_scope.planner import build_plan
from parrot.flows.dev_loop.test_scope.policy import AGENT_FLAGS, AGENT_MARKER_EXPRESSION, ScopePolicy
from parrot.flows.dev_loop.test_scope.runners.pytest import ADAPTER


def _target(path: str, reason: str = "declared") -> TestTarget:
    """Build one pytest target in the root test distribution."""
    return TestTarget(path, "root", reason)


def _argv(worktree: Path, marker: str, *paths: str) -> tuple[str, ...]:
    """Return the historical pytest argv shape used by FEAT-699."""
    return ("pytest", *AGENT_FLAGS, "-m", marker, "--confcutdir", str(worktree), *paths)


def test_pytest_only_plans_preserve_historical_argv_tuples(tmp_path: Path) -> None:
    """Contract and contract-marker plans keep their argv; declared targets use the override marker.

    Declared targets are the task's own Validation Commands, so the agent marker no longer
    deselects them (issue:8c423c5612c2).
    """
    declared = build_plan([_target("tests/test_declared.py")], tier="task", worktree=tmp_path, policy=ScopePolicy())
    contract = TestContract(schema=1, tests=("tests/test_contract.py",), markers=(), digest="sha256:test")
    contract_plan = build_plan(
        [_target("tests/test_contract.py", "contract")],
        tier="merge",
        worktree=tmp_path,
        policy=ScopePolicy(),
        contract=contract,
    )
    marked = TestContract(schema=1, tests=("tests/test_contract.py",), markers=("integration",), digest="sha256:test")
    marked_plan = build_plan(
        [_target("tests/test_contract.py", "contract")],
        tier="feature",
        worktree=tmp_path,
        policy=ScopePolicy(),
        contract=marked,
    )

    assert [invocation.argv for invocation in declared.invocations] == [
        _argv(tmp_path, "not real_llm", "tests/test_declared.py")
    ]
    assert [invocation.argv for invocation in contract_plan.invocations] == [
        _argv(tmp_path, "not real_llm", "tests/test_contract.py")
    ]
    assert [invocation.argv for invocation in marked_plan.invocations] == [
        _argv(tmp_path, "not real_llm", "tests/test_contract.py"),
        _argv(tmp_path, "(integration) and not real_llm", "tests"),
    ]


def test_pytest_adapter_delegates_invocation_and_handles_missing_report(tmp_path: Path) -> None:
    """The adapter retains planner argv construction and missing-report semantics."""
    invocation = ADAPTER.invocation(
        [_target("tests/test_adapter.py")],
        distribution="root",
        worktree=tmp_path,
        settings={},
        policy=ScopePolicy(),
        report_path="reports/pytest.xml",
    )
    report = ADAPTER.parse_report(
        report_path=None,
        exit_code=1,
        stdout="",
        stderr="failure",
        duration_s=0.1,
        timed_out=False,
        suite="root",
    )

    assert invocation.argv == _argv(tmp_path, AGENT_MARKER_EXPRESSION, "tests/test_adapter.py")
    assert invocation.runner == "pytest"
    assert invocation.report_path == "reports/pytest.xml"
    assert report.status == "no_report"


@pytest.mark.parametrize("with_report", [True, False])
def test_exit_five_without_tests_is_no_tests(tmp_path: Path, with_report: bool) -> None:
    """pytest exit 5 ("no tests collected") is reported as no_tests, junit file or not."""
    report_path = None
    if with_report:
        report_path = tmp_path / "pytest.xml"
        report_path.write_text(
            '<?xml version="1.0" encoding="utf-8"?><testsuites>'
            '<testsuite name="pytest" errors="0" failures="0" skipped="0" tests="0" time="0.1"/>'
            "</testsuites>",
            encoding="utf-8",
        )
    report = ADAPTER.parse_report(
        report_path=report_path,
        exit_code=5,
        stdout="",
        stderr="",
        duration_s=0.1,
        timed_out=False,
        suite="root[contract]",
    )

    assert report.status == "no_tests"
    assert report.tests == 0
    assert report.exit_code == 5


def test_exit_five_with_executed_tests_keeps_failed(tmp_path: Path) -> None:
    """Exit 5 never masks a run that actually executed tests."""
    report_path = tmp_path / "pytest.xml"
    report_path.write_text(
        '<?xml version="1.0" encoding="utf-8"?><testsuites>'
        '<testsuite name="pytest" errors="0" failures="0" skipped="0" tests="1" time="0.1">'
        '<testcase classname="tests.test_a" name="test_ok" file="tests/test_a.py" time="0.01"/>'
        "</testsuite></testsuites>",
        encoding="utf-8",
    )
    report = ADAPTER.parse_report(
        report_path=report_path,
        exit_code=5,
        stdout="",
        stderr="",
        duration_s=0.1,
        timed_out=False,
        suite="root",
    )

    assert report.status == "failed"
    assert report.tests == 1
