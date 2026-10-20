"""parrot-e2e runner adapter: reads e2e-verdict.json, never imports parrot.e2e (FEAT-709 M4). Stdlib only."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from ..datatypes import Invocation, RunReport, TestTarget
from ..policy import ScopePolicy

_VERDICT_NAME = "e2e-verdict.json"
_POINTER_NAME = "latest.json"
_NODE_STATUS: Mapping[str, str] = {
    "passed": "passed",
    "xpassed": "passed",
    "failed": "failed",
    "skipped": "skipped",
    "xfailed": "skipped",
    "blocked": "error",
    "missing": "error",
}


def parse_e2e_verdict(
    path: Path | None, *, exit_code: int, suite: str, duration_s: float, timed_out: bool
) -> RunReport:
    """Parse an ``e2e-verdict.json`` into a RunReport.

    Args:
        path: Verdict file, or None when none could be located.
        exit_code: Exit code of the runner process.
        suite: Suite name recorded on the report.
        duration_s: Wall-clock duration of the run.
        timed_out: Whether the run hit its timeout.

    Returns:
        The normalized report; a missing/unreadable file yields status ``no_report``
        (or ``timed_out``), which callers treat as red.
    """
    runner = "parrot-e2e"
    unavailable = "timed_out" if timed_out else "no_report"
    if path is None or not path.is_file():
        return RunReport(runner, suite, 0, 0, 0, 0, 0, duration_s, exit_code, unavailable)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        raw_results = payload.get("results") or []
        nodes: list[tuple[str, str]] = []
        failure_text: dict[str, str] = {}
        for item in raw_results:
            node_id = str(item["node_id"])
            outcome = str(item.get("outcome", item.get("status", "")))
            status = _NODE_STATUS.get(outcome, "error")
            nodes.append((node_id, status))
            if status in {"failed", "error"}:
                text = item.get("detail") or item.get("message") or item.get("reason_code") or outcome
                failure_text[node_id] = str(text)
        counts = payload.get("counts") or {}
        verdict_exit = int(payload.get("exit_code", exit_code))
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return RunReport(runner, suite, 0, 0, 0, 0, 0, duration_s, exit_code, unavailable)

    passed = sum(1 for _, status in nodes if status == "passed")
    failed = sum(1 for _, status in nodes if status == "failed")
    errors = sum(1 for _, status in nodes if status == "error")
    skipped = sum(1 for _, status in nodes if status == "skipped")
    if not nodes and isinstance(counts, dict):
        passed = int(counts.get("passed", 0)) + int(counts.get("xpassed", 0))
        failed = int(counts.get("failed", 0))
        errors = int(counts.get("blocked", 0)) + int(counts.get("missing", 0))
        skipped = int(counts.get("skipped", 0)) + int(counts.get("xfailed", 0))
    tests = passed + failed + errors + skipped
    final_exit = exit_code if exit_code != 0 else verdict_exit
    if timed_out:
        status = "timed_out"
    else:
        status = "failed" if final_exit != 0 or failed or errors else "ok"
    return RunReport(
        runner=runner,
        suite=suite,
        tests=tests,
        passed=passed,
        failed=failed,
        errors=errors,
        skipped=skipped,
        duration_s=duration_s,
        exit_code=final_exit,
        status=status,
        nodes=tuple(sorted(nodes)),
        failure_text=failure_text,
    )


def _resolve_via_pointer(report_path: Path) -> Path | None:
    """Locate the verdict through the CLI's ``latest.json`` pointer near ``report_path``."""
    directory = report_path.parent
    for candidate_dir in (directory, *list(directory.parents)[:3]):
        pointer = candidate_dir / _POINTER_NAME
        if not pointer.is_file():
            continue
        try:
            run_id = str(json.loads(pointer.read_text(encoding="utf-8"))["run_id"])
        except (OSError, ValueError, KeyError, TypeError):
            continue
        resolved = candidate_dir / "runs" / run_id / _VERDICT_NAME
        if resolved.is_file():
            return resolved
    return None


class ParrotE2EAdapter:
    """Adapter for ``parrot e2e run`` reading ``e2e-verdict.json`` from disk."""

    kind = "parrot-e2e"
    binaries = ("parrot",)
    default_tiers = frozenset({"merge", "feature"})
    report_format = "e2e-verdict"

    def matches(self, argv: Sequence[str]) -> bool:
        """Return True for ``parrot e2e run|verify`` argv."""
        return len(argv) >= 3 and Path(argv[0]).name == "parrot" and argv[1] == "e2e" and argv[2] in {"run", "verify"}

    def operands(self, argv: Sequence[str]) -> list[str] | None:
        """Return no operands for a matching argv, None otherwise."""
        return [] if self.matches(argv) else None

    def is_broad(self, argv: Sequence[str], *, worktree: Path | None) -> bool:
        """E2E runs are never classed as broad."""
        return False

    def mirror_targets(self, changed: Sequence[str], *, worktree: Path, settings: Mapping[str, str]) -> list[str]:
        """E2E has no mirror targets."""
        return []

    def distribution_of(self, target: str, *, settings: Mapping[str, str]) -> str:
        """Name the distribution after the plan's parent directory."""
        return Path(settings["plan"]).parent.name or "e2e"

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
        """Build the ``parrot e2e run`` invocation."""
        owner = settings.get("owner_id", "sdd-coder")
        argv = ("parrot", "e2e", "run", "--plan", settings["plan"], "--owner-id", owner)
        return Invocation(
            distribution=distribution,
            argv=argv,
            targets=tuple(targets),
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
        """Parse the verdict, falling back to the ``latest.json`` pointer when the file is absent."""
        resolved = report_path
        if report_path is not None and not report_path.is_file():
            resolved = _resolve_via_pointer(report_path)
        return parse_e2e_verdict(
            resolved, exit_code=exit_code, suite=suite, duration_s=duration_s, timed_out=timed_out
        )

    def validate_settings(self, settings: Mapping[str, str], *, worktree: Path) -> list[str]:
        """Return diagnostics: ``plan`` required and existing; the task tier is forbidden."""
        problems: list[str] = []
        plan = settings.get("plan", "").strip()
        if not plan:
            problems.append("parrot-e2e: 'plan' setting is required")
        elif not (worktree / plan).is_file():
            problems.append(f"parrot-e2e: plan not found: {plan}")
        tiers = {tier.strip() for tier in settings.get("tiers", "").split(",")}
        if "task" in tiers:
            problems.append("parrot-e2e: task tier forbidden")
        return problems


ADAPTER = ParrotE2EAdapter()
