"""Cargo runner adapter: stable libtest text output (FEAT-709 M4). Stdlib only."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from pathlib import Path

from ..datatypes import Invocation, RunReport, TestTarget
from ..policy import TIERS, ScopePolicy

_RESULT_RE = re.compile(r"^test (?P<name>\S+) \.\.\. (?P<status>ok|FAILED|ignored)\s*$", re.M)
_FAILURE_BLOCK_RE = re.compile(r"^---- (?P<name>\S+) stdout ----$", re.M)
_FAILURES_LIST_RE = re.compile(r"^failures:\s*$", re.M)
_STATUS_MAP = {"ok": "passed", "FAILED": "failed", "ignored": "skipped"}


def _failure_blocks(stdout: str) -> dict[str, str]:
    """Extract ``---- name stdout ----`` excerpts, each ending at the next header or ``failures:`` list."""
    headers = list(_FAILURE_BLOCK_RE.finditer(stdout))
    blocks: dict[str, str] = {}
    for idx, match in enumerate(headers):
        start = match.end()
        end = headers[idx + 1].start() if idx + 1 < len(headers) else len(stdout)
        tail = _FAILURES_LIST_RE.search(stdout, start, end)
        if tail is not None:
            end = tail.start()
        blocks[match.group("name")] = stdout[start:end].strip()
    return blocks


def parse_libtest(
    stdout: str, *, crate: str, exit_code: int, suite: str, duration_s: float, timed_out: bool
) -> RunReport:
    """libtest text ⇒ RunReport. Non-zero exit with no result lines ⇒ status "unavailable".

    Args:
        stdout: Captured ``cargo test`` stdout.
        crate: Crate name used in node ids (``cargo:<crate>::<name>``).
        exit_code: Process exit code.
        suite: Suite label for the report.
        duration_s: Wall-clock duration.
        timed_out: Whether the run hit its timeout.

    Returns:
        The normalized RunReport.
    """
    nodes: list[tuple[str, str]] = []
    seen: dict[str, str] = {}
    for match in _RESULT_RE.finditer(stdout):
        name = match.group("name")
        status = _STATUS_MAP[match.group("status")]
        nodeid = f"cargo:{crate}::{name}"
        seen[name] = nodeid
        nodes.append((nodeid, status))
    failure_text: dict[str, str] = {}
    for name, text in _failure_blocks(stdout).items():
        failure_text[seen.get(name, f"cargo:{crate}::{name}")] = text
    passed = sum(1 for _, s in nodes if s == "passed")
    failed = sum(1 for _, s in nodes if s == "failed")
    skipped = sum(1 for _, s in nodes if s == "skipped")
    if timed_out:
        status = "timed_out"
    elif not nodes and exit_code != 0:
        status = "unavailable"
    elif failed or exit_code != 0:
        status = "failed"
    else:
        status = "passed"
    return RunReport(
        runner="cargo",
        suite=suite,
        tests=len(nodes),
        passed=passed,
        failed=failed,
        errors=0,
        skipped=skipped,
        duration_s=duration_s,
        exit_code=exit_code,
        status=status,
        nodes=tuple(nodes),
        failure_text=failure_text,
    )


class CargoAdapter:
    """Runner adapter for ``cargo test`` with stable libtest text output."""

    kind = "cargo"
    binaries = ("cargo",)
    default_tiers = frozenset(TIERS)
    report_format = "libtest"

    def matches(self, argv: Sequence[str]) -> bool:
        """Return True for ``cargo test ...`` argv."""
        return len(argv) >= 2 and Path(argv[0]).name == "cargo" and argv[1] == "test"

    def operands(self, argv: Sequence[str]) -> list[str] | None:
        """Positional filters after ``test`` and before ``--``, skipping ``-p/--package <crate>``."""
        if not self.matches(argv):
            return None
        out: list[str] = []
        args = list(argv[2:])
        i = 0
        while i < len(args):
            arg = args[i]
            if arg == "--":
                break
            if arg in ("-p", "--package"):
                i += 2
                continue
            if not arg.startswith("-"):
                out.append(arg)
            i += 1
        return out

    def is_broad(self, argv: Sequence[str], *, worktree: Path | None) -> bool:
        """A crate is the unit; never broad."""
        return False

    def mirror_targets(self, changed: Sequence[str], *, worktree: Path, settings: Mapping[str, str]) -> list[str]:
        """No file mapping for Rust in v1."""
        return []

    def distribution_of(self, target: str, *, settings: Mapping[str, str]) -> str:
        """The configured crate owns every target."""
        return settings["crate"]

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
        """Build the ``cargo test -p <crate> [filters] -- --test-threads=1`` invocation."""
        filters = sorted({t.path for t in targets if t.path})
        argv = ("cargo", "test", "-p", settings["crate"], *filters, "--", "--test-threads=1")
        return Invocation(
            distribution=distribution,
            argv=argv,
            targets=tuple(targets),
            runner=self.kind,
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
        """Parse stdout libtest text."""
        return parse_libtest(
            stdout,
            crate=suite.split(":", 1)[-1],
            exit_code=exit_code,
            suite=suite,
            duration_s=duration_s,
            timed_out=timed_out,
        )

    def validate_settings(self, settings: Mapping[str, str], *, worktree: Path) -> list[str]:
        """``crate`` is required; a path-like crate must contain a ``Cargo.toml``."""
        crate = settings.get("crate", "")
        if not crate:
            return ["cargo: setting 'crate' is required"]
        if "/" in crate or crate.startswith("."):
            if not (worktree / crate / "Cargo.toml").is_file():
                return [f"cargo: no Cargo.toml under {crate!r}"]
        return []


ADAPTER = CargoAdapter()
