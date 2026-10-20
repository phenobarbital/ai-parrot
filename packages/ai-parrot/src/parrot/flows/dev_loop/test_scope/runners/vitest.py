"""Vitest runner adapter (FEAT-709 M4). Stdlib only."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from ..datatypes import Invocation, RunReport, TestTarget
from ..policy import TIERS, ScopePolicy
from ..report import parse_junit_report

_TEST_SUFFIXES = (".test.ts", ".spec.ts", ".test.js", ".spec.js")
_SOURCE_SUFFIXES = (".svelte.ts", ".svelte", ".ts")


class VitestAdapter:
    """Build scoped Vitest invocations and normalize their JUnit reports."""

    kind = "vitest"
    binaries = ("pnpm", "vitest")
    default_tiers = frozenset(TIERS)
    report_format = "junit"

    def matches(self, argv: Sequence[str]) -> bool:
        """Return whether normalized ``argv`` names Vitest."""
        return bool(argv) and Path(argv[0]).name == "vitest"

    def operands(self, argv: Sequence[str]) -> list[str] | None:
        """Return positional operands after the optional ``run`` command."""
        if not self.matches(argv):
            return None
        arguments = list(argv[1:])
        if arguments and arguments[0] == "run":
            arguments = arguments[1:]
        return [argument for argument in arguments if not argument.startswith("--")]

    def is_broad(self, argv: Sequence[str], *, worktree: Path | None) -> bool:
        """Return whether a Vitest command has no file operand."""
        ops = self.operands(argv)
        return ops is not None and not ops

    def mirror_targets(self, changed: Sequence[str], *, worktree: Path, settings: Mapping[str, str]) -> list[str]:
        """Return existing sibling Vitest files for changed UI source files."""
        cwd = (worktree / settings["cwd"]).resolve()
        targets: set[str] = set()
        for changed_path in changed:
            try:
                relative = (worktree / changed_path).resolve().relative_to(cwd)
            except ValueError:
                continue
            if relative.name.endswith(_TEST_SUFFIXES):
                continue

            source_suffix = next((suffix for suffix in _SOURCE_SUFFIXES if relative.name.endswith(suffix)), None)
            if source_suffix is None:
                continue
            stem = relative.name[: -len(source_suffix)]
            for test_suffix in _TEST_SUFFIXES:
                candidate = relative.with_name(f"{stem}{test_suffix}")
                if (cwd / candidate).is_file():
                    targets.add(candidate.as_posix())
        return sorted(targets)

    def distribution_of(self, target: str, *, settings: Mapping[str, str]) -> str:
        """Return the configured distribution name for a Vitest target."""
        return settings.get("distribution", "admin-ui")

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
        """Build the deterministic scoped Vitest invocation."""
        paths = sorted({target.path for target in targets})
        argv = ("pnpm", "exec", "vitest", "run", "--reporter=junit", f"--outputFile={report_path}", *paths)
        return Invocation(
            distribution=distribution,
            argv=argv,
            targets=tuple(targets),
            runner=self.kind,
            cwd=settings["cwd"],
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
        """Parse a Vitest JUnit report, failing red when no report is available."""
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
        """Validate that the configured UI directory contains ``package.json``."""
        cwd = settings.get("cwd")
        if not cwd:
            return ["vitest: cwd is required"]
        if not (worktree / cwd / "package.json").is_file():
            return [f"vitest: package.json not found in cwd {cwd!r}"]
        return []


ADAPTER = VitestAdapter()
