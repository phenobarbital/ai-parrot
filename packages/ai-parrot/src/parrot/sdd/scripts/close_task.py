"""Deterministically close a single SDD task (Python port of ``scripts/sdd/close_task.sh``, FEAT-633).

Moves ``sdd/tasks/active/<TASK-ID>-*.md`` to ``sdd/tasks/completed/``, marks it "done" in its per-spec index,
stages the change, then HARD-VERIFIES that no active copy survives. Usage (identical to the shell script):

    python -m parrot.sdd.scripts.close_task <TASK-ID> <feature-slug> [verified|partial|forced]

A slug with ``sdd/briefs/<slug>.index.json`` and no per-spec index is a ``/sdd-brief``: its task is closed IN
PLACE (header, per-brief index entry, staging) and never moved. There, exit 2 also covers an id absent from the
brief index and a missing task file.

Exit codes: 0 closed (idempotent) · 1 usage · 2 nothing to close · 3 post-condition failed ·
5 index not valid JSON / no task list (jq parity) · 128 not a git repository (git parity).
"""
from __future__ import annotations

import json
import os
import re
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
BRIEFS_DIR = "sdd/briefs"
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


_STATUS_HEADER_RE = re.compile(r"^\*\*Status\*\*: *(?:pending|in-progress)\b.*$", re.MULTILINE)


def sync_status_header(task_file: Path) -> bool:
    """Rewrite the first ``**Status**: pending|in-progress`` line of ``task_file`` to ``**Status**: done``.

    Returns:
        True when the header was rewritten, False when there was nothing to change.
    """
    text = task_file.read_text(encoding="utf-8")
    updated, count = _STATUS_HEADER_RE.subn("**Status**: done", text, count=1)
    if not count:
        return False
    task_file.write_text(updated, encoding="utf-8")
    return True


def update_index(index: Path, task_id: str, verification: str, completed_file: str, now: str) -> None:
    """C10: mark ``task_id`` done in the per-spec index; stamp top-level completed_at when every task is done.

    ``completed_at`` and ``verification`` are write-once (dev f9e08bee3, issue:732f350600d1): a re-run on an
    already-closed task — the idempotent path — re-asserts status/file but never moves recorded history to now.

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
            task["completed_at"] = task.get("completed_at") or now
            task["verification"] = task.get("verification") or verification
            task["file"] = completed_file
    if all(t.get("status") == "done" for t in tasks):
        data["completed_at"] = data.get("completed_at") or now
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=index.parent, prefix=index.name + ".", suffix=".tmp", delete=False
    ) as handle:
        handle.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        tmp_name = handle.name
    os.replace(tmp_name, index)


def _emit_task_closed(start_dir: Path, task_id: str, feature_slug: str, verification: str) -> None:
    """C14: best-effort ``task.closed`` ledger event; never raises, never changes the exit code.

    An executable ``$SDD_LEDGER_PYTHON`` (operator override, FEAT-718) runs the emission in that interpreter; a
    non-executable one is ignored. Its failure is reported but never undoes the closure.
    """
    override = os.environ.get("SDD_LEDGER_PYTHON", "")
    if override and os.access(override, os.X_OK) and Path(override).resolve() != Path(sys.executable).resolve():
        code = (
            "import sys; from pathlib import Path; "
            "from parrot.sdd.scripts.close_task import _emit_task_closed_inprocess as e; "
            "e(Path(sys.argv[1]), *sys.argv[2:5])"
        )
        try:
            proc = subprocess.run(
                [override, "-c", code, str(start_dir), task_id, feature_slug, verification],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as exc:
            _err(f"⚠️  task.closed ledger emission skipped ({override}): {exc}")
            return
        if proc.returncode != 0:
            _err(f"⚠️  task.closed ledger emission skipped ({override} exited {proc.returncode}): {proc.stderr.strip()}")
        return
    try:
        _emit_task_closed_inprocess(start_dir, task_id, feature_slug, verification)
    except Exception as exc:  # noqa: BLE001 — ledger emission never blocks closure
        _err(f"⚠️  task.closed ledger emission skipped: {exc}")


def _emit_task_closed_inprocess(start_dir: Path, task_id: str, feature_slug: str, verification: str) -> None:
    """Append the ``task.closed`` event in this interpreter (raises on any failure)."""
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


def _close_brief_task(
    repo_root: Path, index_rel: str, task_id: str, feature_slug: str, verification: str, now: str
) -> int:
    """Close a ``/sdd-brief`` task in place: header, per-brief index entry and staging, with no file move.

    Args:
        repo_root: Resolved top level of the checkout.
        index_rel: Repo-relative path of the per-brief index (``sdd/briefs/<slug>.index.json``).
        task_id: Brief task id (``HOTFIX-<KEY>-<N>``).
        feature_slug: Brief slug.
        verification: Verification label recorded on the index entry.
        now: Timestamp used for ``completed_at``.

    Returns:
        0 closed (idempotent), 2 unknown id or missing task file, 5 invalid index, or a failing ``git add`` code.
    """
    index = repo_root / index_rel
    try:
        data = json.loads(index.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        _err(f"jq: error: invalid index JSON: {exc}")
        return 5
    tasks = data.get("tasks") if isinstance(data, dict) else None
    if not isinstance(tasks, list) or not all(isinstance(t, dict) for t in tasks):
        _err("jq: error: index has no iterable task list")
        return 5
    entry = next((t for t in tasks if t.get("id") == task_id), None)
    if entry is None:
        _err(f"✗ {task_id}: not in {index_rel}.")
        return 2
    file_rel = entry.get("file")
    task_file = (repo_root / file_rel).resolve() if isinstance(file_rel, str) and file_rel else None
    if task_file is None or not task_file.is_relative_to(repo_root) or not task_file.is_file():
        _err(f"✗ {task_id}: task file not found: {file_rel}")
        return 2
    if sync_status_header(task_file):
        _out(f"✓ {task_id}: header **Status** → done")
    try:
        update_index(index, task_id, verification, file_rel, now)
    except ValueError as exc:
        _err(f"jq: error: {exc}")
        return 5
    added = _git(["add", "--", index_rel, file_rel], repo_root)
    if added.returncode != 0:
        sys.stderr.write(added.stderr)
        return added.returncode
    _out(f"✅ {task_id} closed in place (verification={verification}).")
    _emit_task_closed(repo_root, task_id, feature_slug, verification)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Port of close_task.sh C1–C14 (positional args only; extra args ignored, verification not validated)."""
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in ("-h", "--help"):
        sys.stdout.write(USAGE.format(prog="parrot sdd task close"))
        return 0
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
    brief_index_rel = f"{BRIEFS_DIR}/{feature_slug}.index.json"
    if not index.is_file() and (repo_root / brief_index_rel).is_file():
        return _close_brief_task(repo_root, brief_index_rel, task_id, feature_slug, verification, now)
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

    # Keep the task file's own `**Status**:` header in step with the index (dev e72348060): only the first
    # `pending`/`in-progress` header line is rewritten; `done` / hand-set `done-with-issues` are left alone.
    if basename_md and (completed_dir / basename_md).is_file():
        if sync_status_header(completed_dir / basename_md):
            _out(f"✓ {task_id}: header **Status** → done")

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
