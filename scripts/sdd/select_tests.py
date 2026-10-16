"""``select_tests.py`` — tier-scoped pytest plans for SDD agents (FEAT-563).

Usage:
    python -m scripts.sdd.select_tests --tier {task,merge,feature} [--base origin/dev]
        [--task-file sdd/tasks/active/TASK-NNN-x.md ...] [--worktree .] [--run] [--json]
"""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
import time
from pathlib import Path
from types import ModuleType

_KERNEL_PARENT = Path(__file__).resolve().parents[2] / "packages/ai-parrot/src/parrot/flows/dev_loop"


def _load_kernel() -> ModuleType:
    """Import the stdlib kernel by path as top-level `test_scope` (never `import parrot`)."""
    if str(_KERNEL_PARENT) not in sys.path:
        sys.path.insert(0, str(_KERNEL_PARENT))
    import test_scope  # noqa: PLC0415 — path-dependent import

    return test_scope


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Plan (and optionally run) tier-scoped pytest invocations.")
    parser.add_argument("--tier", required=True, choices=("task", "merge", "feature"))
    parser.add_argument("--base", default="origin/dev")
    parser.add_argument("--task-file", action="append", default=[], type=Path)
    parser.add_argument("--worktree", type=Path, default=Path.cwd())
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--feature", default=None, help="FEAT-<NNN>: record structured results (FEAT-695)")
    parser.add_argument("--report-task", default=None, help="TASK-<NNN> or _rerun: record owner (FEAT-695)")
    parser.add_argument("--no-ledger", action="store_true", help="report-only: never touch the escalation ledger")
    parser.add_argument(
        "--timeout",
        type=int,
        default=None,
        metavar="SECONDS",
        help=(
            "Per-test timeout (pytest-timeout) applied to every planned invocation. "
            "FEAT-617: bounds a hung test so the sweep names it instead of stalling. "
            "Opt-in -- deliberately NOT a shared pytest config default, so slow suites "
            "do not flake for developers."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: 0 ok, 1 an invocation failed, 2 usage error / empty task-tier plan."""
    try:
        args = _build_parser().parse_args(argv)
    except SystemExit:
        return 2
    kernel = _load_kernel()
    worktree = args.worktree.resolve()

    declared: list[list[str]] = []
    for task_file in args.task_file:
        path = task_file if task_file.is_absolute() else worktree / task_file
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        declared.extend(kernel.contract.parse_validation_commands(text))

    plan = kernel.plan_tests(
        worktree=worktree,
        changed_files=kernel.changed_files(worktree, args.base),
        tier=args.tier,
        declared=declared,
    )

    if not plan.invocations and args.tier == "task":
        import test_scope.guard as guard_mod  # noqa: PLC0415 — path-dependent import

        print(guard_mod.BLOCK_MESSAGE)  # noqa: T201 - CLI output
        return 2

    if args.json:
        import test_scope.models as models_mod  # noqa: PLC0415 — the only kernel module importing pydantic

        print(models_mod.ScopePlanModel.from_plan(plan).model_dump_json(indent=2))  # noqa: T201 - CLI output
    else:
        for invocation in plan.invocations:
            print(shlex.join(invocation.argv))  # noqa: T201 - CLI output
        for note in plan.notes:
            print(f"# note: {note}")  # noqa: T201 - CLI output
        for dist in plan.escalated:
            print(f"# escalated: {dist}")  # noqa: T201 - CLI output
        for dist in plan.skipped_escalations:
            print(f"# skipped: {dist}")  # noqa: T201 - CLI output

    if not args.run:
        return 0

    recording = bool(args.feature and args.report_task)
    report_mod = None
    head_sha = ""
    if recording:
        import test_scope.report as report_mod  # noqa: PLC0415 — path-dependent import

        try:
            head_result = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=worktree, capture_output=True, text=True, check=False
            )
            head_sha = head_result.stdout.strip()
        except OSError:
            head_sha = ""

        if not plan.invocations:
            selection = report_mod.SuiteResult(
                suite="selection",
                tests=0,
                passed=0,
                failed=0,
                errors=0,
                skipped=0,
                duration_s=0.0,
                exit_code=0,
                argv=(),
                status="selection_error",
            )
            report_mod.append_suite(
                args.feature,
                args.report_task,
                selection,
                head_sha=head_sha,
                base_ref=args.base,
                tier=args.tier,
                source="select_tests",
                note="selection_error: no test invocations planned",
            )

    exit_code = 0
    for ordinal, invocation in enumerate(plan.invocations):
        # FEAT-617: bound each test so a hang fails loudly, named, instead of stalling
        # the whole merge gate. Build a local argv -- invocation.argv is read elsewhere
        # (the printed plan) and must stay unmodified.
        argv = list(invocation.argv)
        if args.timeout is not None:
            argv.append(f"--timeout={args.timeout}")
        junit = None
        if recording:
            try:
                junit = report_mod.junit_path_for(args.feature, args.report_task, invocation.distribution, ordinal)
                invocation_copy = type(invocation)(
                    distribution=invocation.distribution,
                    argv=tuple(argv),
                    targets=invocation.targets,
                )
                argv = list(report_mod.with_junit(invocation_copy, junit))
            except OSError:
                junit = None
        started = time.monotonic()
        result = subprocess.run(argv, cwd=worktree)
        if recording and junit is not None:
            suite = report_mod.parse_junit(
                junit,
                suite=invocation.distribution,
                argv=tuple(argv),
                exit_code=result.returncode,
                duration_s=time.monotonic() - started,
            )
            report_mod.append_suite(
                args.feature,
                args.report_task,
                suite,
                head_sha=head_sha,
                base_ref=args.base,
                tier=args.tier,
                source="select_tests",
            )
        is_core_escalation = any(target.reason == "core" for target in invocation.targets)
        is_cap_escalation = any(target.reason == "escalated" for target in invocation.targets)
        if result.returncode != 0:
            exit_code = 1
            if not args.no_ledger and (is_core_escalation or is_cap_escalation):
                # R14/AC9c: a red escalation run re-arms it, even when its driving file content is unchanged.
                kernel.context.record_red_run(worktree, [invocation.distribution])
            continue
        if not args.no_ledger and (is_core_escalation or is_cap_escalation):
            dist = invocation.distribution
            core_files = [hit.path for hit in plan.core_hits if dist in hit.distributions]
            impact_files = list(plan.cap_hits.get(dist, ()))
            impacted_hashes = {dist: plan.cap_impacted[dist]} if dist in plan.cap_impacted else {}
            if core_files or impact_files:
                kernel.context.record_green_escalation(
                    worktree, [dist], core_files, impact_files=impact_files, impacted_hashes=impacted_hashes
                )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
