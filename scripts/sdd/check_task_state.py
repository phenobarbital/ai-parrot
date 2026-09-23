"""``check_task_state.py`` — read-only backstop for stalled SDD task files.

A task is *closed* by moving its file from ``sdd/tasks/active/`` to
``sdd/tasks/completed/`` and marking its per-spec index entry ``done``
(``scripts/sdd/close_task.sh`` / ``scripts/sdd/finalize_task.py``). When a
lane copies instead of moving, or closes on one branch while a merge brings
the old ``active/`` copy back, the base branch ends up with a *stalled*
``active/`` file for a task that is already finished. ``heal_orphans.sh``
reaps those, but only when ``/sdd-done --merge`` runs it — the default PR
flow never did, so orphans accumulated silently.

This check fails CI on the two states that are unambiguous by construction:

* ``twin`` — the same task file exists in both ``active/`` and
  ``completed/`` (identical basename).
* ``closed-but-active`` — a per-spec index entry marks the task ``done`` /
  ``done-with-issues`` while its file still lives in ``active/``.

It deliberately does NOT flag ``pending`` / ``in-progress`` tasks: whether
one of those is abandoned depends on branches and worktrees this script
cannot see. Fix a reported violation with
``scripts/sdd/heal_orphans.sh <feature-slug>`` (twins) or
``scripts/sdd/close_task.sh <TASK-ID> <feature-slug>`` (closed-but-active).

Usage:
    python -m scripts.sdd.check_task_state [--index-dir DIR] [--active-dir DIR]
        [--completed-dir DIR] [--baseline FILE]
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

#: Matches a TASK filename prefix, e.g. "TASK-1939-repl-dedicated-executor.md".
_TASK_FILENAME_RE = re.compile(r"^(TASK-\d+)-")

#: Index statuses that mean the task is finished and must not stay in active/.
_CLOSED_STATUSES = frozenset({"done", "done-with-issues"})


class TaskStateViolation(BaseModel):
    """One stalled ``active/`` task file and why it is stalled."""

    task_id: str
    kind: Literal["twin", "closed-but-active"]
    active_file: str
    detail: str


def _closed_entries(index_dir: Path) -> dict[str, list[tuple[str, str, str]]]:
    """Map each active-file basename to the closed index entries that own it.

    An entry owns a basename when its ``id`` matches the filename's TASK
    prefix AND its ``file`` field names that same basename (in ``active/``
    or ``completed/``). Matching on the basename, not the bare id, keeps
    historical cross-feature ``TASK-<NNN>`` reuse (see
    ``check_id_collisions.py``) from producing false positives.

    Args:
        index_dir: Directory holding the per-spec ``<feature>.json`` indexes.

    Returns:
        ``{basename: [(index_path, feature, status), ...]}`` for entries whose
        status is in ``_CLOSED_STATUSES``.
    """
    owners: dict[str, list[tuple[str, str, str]]] = {}
    if not index_dir.is_dir():
        return owners
    for index_file in sorted(index_dir.glob("*.json")):
        try:
            data = json.loads(index_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        for task in data.get("tasks") or []:
            if not isinstance(task, dict):
                continue
            status = task.get("status")
            file_field = task.get("file")
            task_id = task.get("id")
            if status not in _CLOSED_STATUSES or not file_field or not task_id:
                continue
            basename = Path(str(file_field)).name
            if not basename.startswith(f"{task_id}-"):
                continue
            feature = str(task.get("feature") or data.get("feature") or index_file.stem)
            owners.setdefault(basename, []).append((str(index_file), feature, str(status)))
    return owners


def find_violations(*, index_dir: Path, active_dir: Path, completed_dir: Path) -> list[TaskStateViolation]:
    """Scan ``active/`` for task files that should already be closed.

    Args:
        index_dir: Directory holding the per-spec indexes.
        active_dir: ``sdd/tasks/active``.
        completed_dir: ``sdd/tasks/completed``.

    Returns:
        Every violation found, ordered by active filename.
    """
    violations: list[TaskStateViolation] = []
    if not active_dir.is_dir():
        return violations
    closed = _closed_entries(index_dir)
    for active_file in sorted(active_dir.glob("TASK-*.md")):
        match = _TASK_FILENAME_RE.match(active_file.name)
        if not match:
            continue
        task_id = match.group(1)
        twin = completed_dir / active_file.name
        if twin.is_file():
            violations.append(
                TaskStateViolation(
                    task_id=task_id,
                    kind="twin",
                    active_file=str(active_file),
                    detail=f"completed copy also exists at {twin}",
                )
            )
            continue
        for index_path, feature, status in closed.get(active_file.name, []):
            violations.append(
                TaskStateViolation(
                    task_id=task_id,
                    kind="closed-but-active",
                    active_file=str(active_file),
                    detail=f"{index_path} ({feature}) marks it {status!r}",
                )
            )
    return violations


def _load_baseline(path: Path | None) -> set[str]:
    """Load a JSON list of pre-existing violation TASK-IDs to report but not fail on.

    Args:
        path: JSON file holding a list of ``TASK-<NNN>`` strings, or ``None``.

    Returns:
        The baselined ids; empty when ``path`` is ``None`` or unreadable.
    """
    if path is None:
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    return {str(item) for item in data} if isinstance(data, list) else set()


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: exit 1 on any non-baselined violation, 0 otherwise.

    Args:
        argv: Optional argument list (defaults to ``sys.argv[1:]``).

    Returns:
        Process exit code.
    """
    parser = argparse.ArgumentParser(description="Fail on stalled sdd/tasks/active/ task files.")
    parser.add_argument("--index-dir", type=Path, default=Path("sdd/tasks/index"))
    parser.add_argument("--active-dir", type=Path, default=Path("sdd/tasks/active"))
    parser.add_argument("--completed-dir", type=Path, default=Path("sdd/tasks/completed"))
    parser.add_argument(
        "--baseline",
        type=Path,
        default=None,
        help="JSON list of pre-existing violation TASK-IDs to report but NOT fail on.",
    )
    args = parser.parse_args(argv)

    violations = find_violations(index_dir=args.index_dir, active_dir=args.active_dir, completed_dir=args.completed_dir)
    baseline = _load_baseline(args.baseline)
    new = [v for v in violations if v.task_id not in baseline]

    if violations:
        print("Stalled task files in active/:")
        for v in violations:
            note = " (baselined — non-fatal)" if v.task_id in baseline else ""
            print(f"  {v.task_id} [{v.kind}]{note}: {v.active_file} — {v.detail}")
    if new:
        print(
            f"\nFAIL: {len(new)} stalled active/ task file(s). Twins: "
            "scripts/sdd/heal_orphans.sh <feature-slug>; closed-but-active: "
            "scripts/sdd/close_task.sh <TASK-ID> <feature-slug>."
        )
        return 1
    print(f"OK: no stalled active/ task files ({len(violations) - len(new)} baselined).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
