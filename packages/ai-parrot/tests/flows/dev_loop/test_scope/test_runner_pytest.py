"""Tests for the FEAT-709 pytest runner adapter."""

from __future__ import annotations

from pathlib import Path

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
    """Declared-only, contract, and contract-marker plans remain byte-identical."""
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
        _argv(tmp_path, AGENT_MARKER_EXPRESSION, "tests/test_declared.py")
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
