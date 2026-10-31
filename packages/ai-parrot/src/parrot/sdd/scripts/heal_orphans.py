"""Self-healing sweep for stalled SDD task files (Python port of ``scripts/sdd/heal_orphans.sh``, FEAT-633).

Reaps an ``sdd/tasks/active/<TASK-ID>-*.md`` only when a per-spec index marks it "done" AND a completed/ twin
exists. Usage (identical to the shell script; ``--dry-run`` is honoured only as the FIRST argument):

    python -m parrot.sdd.scripts.heal_orphans [--dry-run] [feature-slug]

Exit codes: 0 swept · 128 not a git repository (git parity).
"""
from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path

ACTIVE_DIR = "sdd/tasks/active"
COMPLETED_DIR = "sdd/tasks/completed"
INDEX_DIR = "sdd/tasks/index"


def _out(line: str) -> None:
    sys.stdout.write(line + "\n")


def done_task_ids(indices: Iterable[Path]) -> list[str]:
    """H5: sorted unique ids with status "done" across ``indices``; unreadable/invalid files contribute nothing."""
    ids: set[str] = set()
    for path in indices:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        tasks = data.get("tasks") if isinstance(data, dict) else None
        if not isinstance(tasks, list):
            continue
        for task in tasks:
            if isinstance(task, dict) and task.get("status") == "done" and isinstance(task.get("id"), str):
                ids.add(task["id"])
    return sorted(ids)


def main(argv: Sequence[str] | None = None) -> int:
    """Port of heal_orphans.sh H1–H8."""
    args = list(sys.argv[1:] if argv is None else argv)
    dry_run = bool(args) and args[0] == "--dry-run"
    if dry_run:
        args = args[1:]
    feature_slug = args[0] if args else ""
    top = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=False)
    if top.returncode != 0:
        sys.stderr.write(top.stderr)
        return top.returncode
    repo_root = Path(top.stdout.strip()).resolve()
    active_dir = repo_root / ACTIVE_DIR
    completed_dir = repo_root / COMPLETED_DIR
    index_dir = repo_root / INDEX_DIR
    indices = [index_dir / f"{feature_slug}.json"] if feature_slug else sorted(index_dir.glob("*.json"))
    reaped = 0
    kept = 0
    for tid in done_task_ids(p for p in indices if p.is_file()):
        active = sorted(active_dir.glob(f"{tid}-*.md"))
        if not active:
            continue
        if not sorted(completed_dir.glob(f"{tid}-*.md")):
            _out(f"⚠️  {tid}: done but NO completed/ twin — leaving active file (manual review).")
            kept += 1
            continue
        for path in active:
            rel = f"{ACTIVE_DIR}/{path.name}"
            if dry_run:
                _out(f"would reap: {rel}")
            else:
                subprocess.run(
                    ["git", "rm", "-q", "--ignore-unmatch", rel], cwd=repo_root, capture_output=True, text=True, check=False
                )
                path.unlink(missing_ok=True)
                _out(f"reaped orphan: {rel}")
            reaped += 1
    verb = "would be reaped" if dry_run else "reaped"
    _out(f"── heal_orphans: {reaped} orphan(s) {verb}, {kept} kept for review.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
