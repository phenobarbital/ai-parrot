"""Pytest runner adapter (FEAT-709 M3). Stdlib only."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path

from ..contract import _pytest_operands, is_broad_pytest
from ..datatypes import Invocation, RunReport, TestTarget
from ..mirror import distribution_of, pytest_file_targets
from ..policy import TIERS, ScopePolicy
from ..report import parse_junit_report


class PytestAdapter:
    """Build and parse scoped pytest invocations using existing planner helpers."""

    kind = "pytest"
    binaries = ("pytest", "python", "python3")
    default_tiers = frozenset(TIERS)
    report_format = "junit"

    def matches(self, argv: Sequence[str]) -> bool:
        """Return whether normalized argv names pytest."""
        return bool(argv) and Path(argv[0]).name == "pytest"

    def operands(self, argv: Sequence[str]) -> list[str] | None:
        """Return pytest path operands, if argv is a pytest command."""
        return _pytest_operands(argv)

    def is_broad(self, argv: Sequence[str], *, worktree: Path | None) -> bool:
        """Return whether pytest would run an unbounded test suite."""
        return is_broad_pytest(argv, worktree=worktree)

    def mirror_targets(self, changed: Sequence[str], *, worktree: Path, settings: Mapping[str, str]) -> list[str]:
        """Return pytest files mirrored from the changed paths."""
        return pytest_file_targets(list(changed), str(worktree))

    def distribution_of(self, target: str, *, settings: Mapping[str, str]) -> str:
        """Return the distribution owning a pytest target."""
        return distribution_of(target)

    def invocation(
        self,
        targets: Sequence[TestTarget],
        *,
        distribution: str,
        worktree: Path,
        settings: Mapping[str, str],
        policy: ScopePolicy,
        report_path: str,
    ) -> Invocation:
        """Build a byte-identical pytest invocation with runner metadata."""
        from ..planner import _invocation

        invocation = _invocation(distribution, targets, worktree=worktree, policy=policy)
        return replace(
            invocation,
            runner=self.kind,
            report_path=report_path,
            report_format=self.report_format,
        )

    def parse_report(
        self,
        *,
        report_path: Path | None,
        exit_code: int,
        stdout: str,
        stderr: str,
        duration_s: float,
        timed_out: bool,
        suite: str,
    ) -> RunReport:
        """Parse a pytest JUnit report or return a missing-report outcome."""
        if report_path is None:
            status = "timed_out" if timed_out else "no_report"
            return RunReport(self.kind, suite, 0, 0, 0, 0, 0, duration_s, exit_code, status)
        return parse_junit_report(
            report_path,
            runner=self.kind,
            suite=suite,
            exit_code=exit_code,
            duration_s=duration_s,
            timed_out=timed_out,
        )

    def validate_settings(self, settings: Mapping[str, str], *, worktree: Path) -> list[str]:
        """Return diagnostics for settings pytest does not understand."""
        return [f"pytest: unknown setting {key!r}" for key in settings if key not in {"markers", "timeout_s", "tiers"}]


ADAPTER = PytestAdapter()
