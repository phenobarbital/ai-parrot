"""Deterministically close a single SDD task (Python port of ``scripts/sdd/close_task.sh``, FEAT-633).

Moves ``sdd/tasks/active/<TASK-ID>-*.md`` to ``sdd/tasks/completed/``, marks it "done" in its per-spec index,
stages the change, then HARD-VERIFIES that no active copy survives. Usage (identical to the shell script):

    python -m parrot.sdd.scripts.close_task <TASK-ID> <feature-slug> [verified|partial|forced]

Exit codes: 0 closed (idempotent) · 1 usage · 2 nothing to close · 3 post-condition failed ·
5 index not valid JSON / no task list (jq parity) · 128 not a git repository (git parity).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

ACTIVE_DIR = "sdd/tasks/active"
COMPLETED_DIR = "sdd/tasks/completed"
INDEX_DIR = "sdd/tasks/index"
USAGE = "usage: {prog} <TASK-ID> <feature-slug> [verified|partial|forced]\n"


def _git(args: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run git in ``cwd`` inheriting os.environ (GIT_INDEX_FILE must flow through); output captured (= discarded)."""
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)


def _out(line: str) -> None:
    sys.stdout.write(line + "\n")


def _err(line: str) -> None:
    sys.stderr.write(line + "\n")


def _now() -> str:
    """C5: ``date -u +%Y-%m-%dT%H:%M:%S+00:00``."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def update_index(index: Path, task_id: str, verification: str, completed_file: str, now: str) -> None:
    """C10: mark ``task_id`` done in the per-spec index; stamp top-level completed_at when every task is done.

    Raises:
        ValueError: when the index is not valid JSON or ``tasks`` is not a list (caller returns 5, jq parity).
    """
    try:
        data = json.loads(index.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise ValueError(f"invalid index JSON: {exc}") from exc
    tasks = data.get("tasks") if isinstance(data, dict) else None
    if not isinstance(tasks, list) or not all(isinstance(t, dict) for t in tasks):
        raise ValueError("index has no iterable task list")
    for task in tasks:
        if task.get("id") == task_id:
            task["status"] = "done"
            task["completed_at"] = now
            task["verification"] = verification
            task["file"] = completed_file
    if all(t.get("status") == "done" for t in tasks):
        data["completed_at"] = now
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=index.parent, prefix=index.name + ".", suffix=".tmp", delete=False
    ) as handle:
        handle.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        tmp_name = handle.name
    os.replace(tmp_name, index)


def _emit_task_closed(start_dir: Path, task_id: str, feature_slug: str, verification: str) -> None:
    """C14: best-effort ``task.closed`` ledger event; never raises, never changes the exit code."""
    try:
        from parrot.knowledge.wiki.ledger.events import LedgerEvent  # lazy: navconfig chdirs on import
        from parrot.knowledge.wiki.ledger.log import LedgerLog
        from parrot.knowledge.wiki.project import find_shared_root

        shared_root = find_shared_root(start_dir) or start_dir
        ledger_dir = shared_root / ".parrot" / "ledger"
        ledger_dir.mkdir(parents=True, exist_ok=True)
        event = LedgerEvent(
            kind="task.closed",
            subject=f"task:{task_id}",
            actor="agent:close_task.sh",
            payload={"feature": feature_slug, "verification": verification},
        )
        LedgerLog(str(ledger_dir / "events.jsonl")).append(event)
    except Exception as exc:  # noqa: BLE001 — ledger emission never blocks closure
        _err(f"⚠️  task.closed ledger emission skipped: {exc}")


def main(argv: Sequence[str] | None = None) -> int:
    """Port of close_task.sh C1–C14 (positional args only; extra args ignored, verification not validated)."""
    args = list(sys.argv[1:] if argv is None else argv)
    task_id = args[0] if len(args) > 0 else ""
    feature_slug = args[1] if len(args) > 1 else ""
    verification = args[2] if len(args) > 2 and args[2] else "verified"
    if not task_id or not feature_slug:
        sys.stderr.write(USAGE.format(prog="python -m parrot.sdd.scripts.close_task"))
        return 1
    top = _git(["rev-parse", "--show-toplevel"], Path.cwd())
    if top.returncode != 0:
        sys.stderr.write(top.stderr)
        return top.returncode
    repo_root = Path(top.stdout.strip()).resolve()
    now = _now()
    active_dir = repo_root / ACTIVE_DIR
    completed_dir = repo_root / COMPLETED_DIR
    index_rel = f"{INDEX_DIR}/{feature_slug}.json"
    index = repo_root / index_rel
    completed_dir.mkdir(parents=True, exist_ok=True)

    active_matches = sorted(active_dir.glob(f"{task_id}-*.md"))
    completed_matches = sorted(completed_dir.glob(f"{task_id}-*.md"))
    if not active_matches and completed_matches:
        _out(f"ℹ️  {task_id}: already in completed/ (no active copy) — nothing to move.")
    elif not active_matches:
        _err(f"✗ {task_id}: no file in active/ and no twin in completed/.")
        return 2

    basename_md = ""
    for src in active_matches:
        basename_md = src.name
        dest = completed_dir / basename_md
        src_rel = f"{ACTIVE_DIR}/{basename_md}"
        if dest.exists():
            _git(["rm", "-q", "--ignore-unmatch", src_rel], repo_root)
            src.unlink(missing_ok=True)
            _out(f"✓ {task_id}: removed orphan active copy (twin already in completed/).")
        else:
            moved = _git(["mv", src_rel, f"{COMPLETED_DIR}/{basename_md}"], repo_root)
            if moved.returncode != 0:
                shutil.move(str(src), str(dest))
            _out(f"✓ {task_id}: moved active → completed/{basename_md}")

    if not basename_md and completed_matches:
        basename_md = completed_matches[0].name

    if index.is_file() and basename_md:
        try:
            update_index(index, task_id, verification, f"{COMPLETED_DIR}/{basename_md}", now)
        except ValueError as exc:
            _err(f"jq: error: {exc}")
            return 5
        added = _git(["add", index_rel], repo_root)
        if added.returncode != 0:
            sys.stderr.write(added.stderr)
            return added.returncode

    _git(["add", f"{COMPLETED_DIR}/{basename_md}"], repo_root)
    _git(["add", "-u", ACTIVE_DIR], repo_root)

    survivors = sorted(active_dir.glob(f"{task_id}-*.md"))
    if survivors:
        joined = " ".join(f"{ACTIVE_DIR}/{p.name}" for p in survivors)
        _err(f"✗ {task_id}: active copy STILL present after close: {joined}")
        return 3

    _out(f"✅ {task_id} closed (verification={verification}). active/ is clean.")
    _emit_task_closed(repo_root, task_id, feature_slug, verification)  # C14 — after the ✅ line
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
