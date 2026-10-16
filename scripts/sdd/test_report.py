#!/usr/bin/env python3
"""Render FEAT-695 test evidence for the ``/sdd-done`` closeout.

Usage:
    python -m scripts.sdd.test_report decide-rerun --index sdd/tasks/index/<slug>.json
    python -m scripts.sdd.test_report render --index <idx> [--worktree <wt>] [--out <file>]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

_KERNEL_PARENT = Path(__file__).resolve().parents[2] / "packages/ai-parrot/src/parrot/flows/dev_loop"


def _load_report() -> ModuleType:
    """Import ``test_scope.report`` by path without importing ``parrot``."""
    if str(_KERNEL_PARENT) not in sys.path:
        sys.path.insert(0, str(_KERNEL_PARENT))
    import test_scope.report as report_mod  # noqa: PLC0415 -- path-dependent import

    return report_mod


def _build_parser() -> argparse.ArgumentParser:
    """Build the deterministic test-report command parser."""
    parser = argparse.ArgumentParser(description="Render FEAT-695 SDD test evidence.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    decide_rerun = subparsers.add_parser("decide-rerun")
    decide_rerun.add_argument("--index", required=True, type=Path)

    render = subparsers.add_parser("render")
    render.add_argument("--index", required=True, type=Path)
    render.add_argument("--worktree", default=Path.cwd(), type=Path)
    render.add_argument("--out", type=Path)
    return parser


def _read_index(path: Path) -> tuple[str, list[str]] | None:
    """Read a feature id and task ids, returning ``None`` for an unusable index."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        feature_id = payload["feature_id"]
        tasks = payload["tasks"]
        task_ids = [task["id"] for task in tasks]
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        return None
    if not isinstance(feature_id, str) or not all(isinstance(task_id, str) for task_id in task_ids):
        return None
    return feature_id, task_ids


def _final_head(worktree: Path) -> str:
    """Return the worktree HEAD, retaining a deterministic fallback on git errors."""
    try:
        result = subprocess.run(
            ["git", "-C", str(worktree), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return "unknown"
    return result.stdout.strip() or "unknown"


def main(argv: list[str] | None = None) -> int:
    """Return 0 for reports and 2 for usage errors or unreadable indexes."""
    try:
        args = _build_parser().parse_args(argv)
    except SystemExit:
        return 2

    index = _read_index(args.index)
    if index is None:
        return 2
    feature_id, task_ids = index
    report_mod = _load_report()
    task_count = len(task_ids)

    if args.command == "decide-rerun":
        if report_mod.should_rerun(task_count):
            print("rerun")  # noqa: T201 - CLI output
        else:
            print(f"skip ({task_count} tasks > {report_mod.RERUN_TASK_THRESHOLD})")  # noqa: T201 - CLI output
        return 0

    records, _notes = report_mod.load_records(feature_id)
    rerun = records.pop(report_mod.RERUN_RECORD, None)
    rerun_skip_reason = (
        None if rerun is not None or report_mod.should_rerun(task_count) else f"{task_count} tasks > {report_mod.RERUN_TASK_THRESHOLD}"
    )
    markdown = report_mod.render_markdown(
        records,
        task_ids,
        final_head=_final_head(args.worktree),
        rerun=rerun,
        rerun_skip_reason=rerun_skip_reason,
    )
    if args.out is None:
        print(markdown)  # noqa: T201 - CLI output
    else:
        args.out.write_text(markdown, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
