#!/usr/bin/env python3
"""Render FEAT-695 test evidence for the ``/sdd-done`` closeout.

Usage:
    python -m parrot.sdd.scripts.test_report decide-rerun --index sdd/tasks/index/<slug>.json
    python -m parrot.sdd.scripts.test_report render --index <idx> [--worktree <wt>] [--out <file>]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

_KERNEL_PARENT = Path(__file__).resolve().parents[2] / "flows" / "dev_loop"


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


NO_DATA_HEADING = "## Tests \u2014 no data"


def _no_data_markdown(index_path: Path) -> str:
    """Render the placeholder section emitted when the feature index is unusable."""
    return "\n".join(
        [
            NO_DATA_HEADING,
            "",
            f"_No test evidence: the feature index at `{index_path}` is missing or unreadable._",
            "_Reported, not fatal \u2014 this step never blocks closeout (`/sdd-done` \u00a74.7)._",
        ]
    )


def _emit(markdown: str, out: Path | None) -> None:
    """Write the section to ``out``, falling back to stdout when the write fails."""
    if out is not None:
        try:
            out.write_text(markdown, encoding="utf-8")
        except OSError as exc:
            print(f"test_report: could not write {out}: {exc}", file=sys.stderr)  # noqa: T201 - CLI output
        else:
            return
    print(markdown)  # noqa: T201 - CLI output


def main(argv: list[str] | None = None) -> int:
    """Return 0 for every report, no-data ones included, and 2 only for argument usage errors."""
    try:
        args = _build_parser().parse_args(argv)
    except SystemExit:
        return 2

    index = _read_index(args.index)
    if index is None:
        if args.command == "decide-rerun":
            print("skip (no data)")  # noqa: T201 - CLI output
        else:
            _emit(_no_data_markdown(args.index), args.out)
        return 0
    feature_id, task_ids = index
    try:
        report_mod = _load_report()
    except ImportError as exc:
        print(  # noqa: T201 - CLI output
            f"error: the FEAT-699 test_scope kernel could not be loaded ({exc}); "
            "set `test_command` in sdd/config.json to run your own test command instead",
            file=sys.stderr,
        )
        return 2
    task_count = len(task_ids)

    if args.command == "decide-rerun":
        if report_mod.should_rerun(task_count):
            print("rerun")  # noqa: T201 - CLI output
        else:
            print("skip (no tasks)")  # noqa: T201 - CLI output
        return 0

    records, notes = report_mod.load_records(feature_id)
    rerun = records.pop(report_mod.RERUN_RECORD, None)
    rerun_skip_reason = None if rerun is not None or report_mod.should_rerun(task_count) else "no tasks"
    markdown = report_mod.render_markdown(
        records,
        task_ids,
        final_head=_final_head(args.worktree),
        rerun=rerun,
        rerun_skip_reason=rerun_skip_reason,
        notes=tuple(notes),
    )
    _emit(markdown, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
