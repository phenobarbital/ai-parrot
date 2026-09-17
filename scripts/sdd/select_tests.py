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

    exit_code = 0
    for invocation in plan.invocations:
        result = subprocess.run(list(invocation.argv), cwd=worktree)
        if result.returncode != 0:
            exit_code = 1
            continue
        if any(target.reason == "core" for target in invocation.targets):
            core_files = [hit.path for hit in plan.core_hits if invocation.distribution in hit.distributions]
            if core_files:
                kernel.context.record_green_escalation(worktree, [invocation.distribution], core_files)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
