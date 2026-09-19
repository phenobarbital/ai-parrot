"""Discover SDD worktrees and report their task state and health.

Read-only: never writes files or runs mutating git commands.
CLI: ``python -m scripts.sdd.worktree_status [--json]``
Library: ``from scripts.sdd.worktree_status import discover_worktree_reports``
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from scripts.sdd.sdd_meta import WORKTREE_ROOT  # verified: scripts/sdd/sdd_meta.py:15

# ---------------------------------------------------------------------------
# Branch-name patterns
# ---------------------------------------------------------------------------

_FEAT_BRANCH_RE = re.compile(r"^feat-(?:FEAT-)?(\d+)-(.+)$")
_HOTFIX_BRANCH_RE = re.compile(r"^hotfix-([A-Z]+-\d+)-(.+)$")
# sdd-coder pool sub-worktree suffix, e.g. "...--TASK-3505-a1-6818142afc1542a0bdd479267b8ccb6e"
# (FEAT-549). These are task-level attempt branches nested inside a feature
# worktree, not feature worktrees themselves, and must never be reported as
# one (they would otherwise pass _FEAT_BRANCH_RE with a garbage slug).
_POOL_SUB_WORKTREE_RE = re.compile(r"--TASK-\d+-a\d+-[0-9a-f]+$")

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class WorktreeTaskStatus(BaseModel):
    """Per-task status as seen from a worktree's index."""

    id: str
    status: Literal["pending", "in-progress", "done", "done-with-issues"]
    completed_at: str | None = None


class WorktreeHealth(BaseModel):
    """Health signals for a single worktree."""

    dirty_count: int = 0
    unpushed_count: int = 0
    live_process_count: int = 0


class WorktreeReport(BaseModel):
    """Complete worktree state for one feature."""

    feature_slug: str
    feature_id: str | None = None
    flow_type: Literal["feature", "hotfix"]
    worktree_path: str
    branch: str
    base_branch: str = "dev"
    health: WorktreeHealth = Field(default_factory=WorktreeHealth)
    tasks: list[WorktreeTaskStatus] = Field(default_factory=list)
    index_found: bool = True
    ready_for_done: bool = False


# ---------------------------------------------------------------------------
# Git helper
# ---------------------------------------------------------------------------


def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run a git command, return CompletedProcess (never raises on failure).

    A missing/deleted ``cwd`` (e.g. a worktree directory removed without
    ``git worktree remove``/``prune``) would otherwise raise ``OSError``
    before git even runs; that is caught here and reported as a synthetic
    non-zero-exit failure instead, matching the "never raises" contract.
    """
    try:
        return subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            text=True,
            capture_output=True,
        )
    except OSError as exc:
        return subprocess.CompletedProcess(args=["git", *args], returncode=1, stdout="", stderr=str(exc))


# ---------------------------------------------------------------------------
# Branch parsing
# ---------------------------------------------------------------------------


def _parse_branch(
    branch: str,
) -> tuple[str, str | None, Literal["feature", "hotfix"]] | None:
    """Parse an SDD branch name into (slug, feature_id_or_jira_key, flow_type).

    Returns None for non-SDD branches (chore-*, fix-*, detached, etc.) and for
    sdd-coder pool sub-worktree branches (FEAT-549), which are task-level
    attempts nested inside a feature worktree, not feature worktrees.
    Handles both ``feat-FEAT-550-slug`` and legacy ``feat-550-slug``.
    """
    if _POOL_SUB_WORKTREE_RE.search(branch):
        return None
    m = _FEAT_BRANCH_RE.match(branch)
    if m:
        return m.group(2), f"FEAT-{m.group(1)}", "feature"
    m = _HOTFIX_BRANCH_RE.match(branch)
    if m:
        return m.group(2), m.group(1), "hotfix"
    return None


# ---------------------------------------------------------------------------
# Index reading
# ---------------------------------------------------------------------------


def _read_worktree_index(
    wt_path: Path,
    slug: str,
) -> tuple[list[WorktreeTaskStatus], str]:
    """Read the per-spec index inside a worktree.

    Returns (task_list, base_branch).  task_list is empty if not found or
    malformed.  base_branch defaults to ``"dev"`` on any failure.
    """
    index_path = wt_path / "sdd" / "tasks" / "index" / f"{slug}.json"
    try:
        with open(index_path, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return [], "dev"

    base_branch = data.get("base_branch", "dev")
    tasks = []
    for task in data.get("tasks", []):
        try:
            tasks.append(
                WorktreeTaskStatus(
                    id=task["id"],
                    status=task["status"],
                    completed_at=task.get("completed_at"),
                )
            )
        except (KeyError, TypeError, ValueError):
            # Skip malformed task entries (ValueError also covers pydantic's
            # ValidationError, e.g. a status outside the Literal enum).
            continue
    return tasks, base_branch


# ---------------------------------------------------------------------------
# Health checks
# ---------------------------------------------------------------------------


def _live_process_count(path: Path) -> int:
    """Count processes with cwd inside path (Linux /proc, best-effort)."""
    try:
        resolved = path.resolve()
    except OSError:
        return 0

    # Non-Linux systems don't have /proc
    proc_dir = Path("/proc")
    if not proc_dir.exists():
        return 0

    count = 0
    for entry in proc_dir.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            pid = int(entry.name)
            cwd = Path(os.readlink(f"/proc/{pid}/cwd"))
            if cwd == resolved or resolved in cwd.parents:
                count += 1
        except (OSError, PermissionError):
            continue
    return count


def _check_health(wt_path: Path, base_branch: str) -> WorktreeHealth:
    """Dirty files, unpushed commits, live processes."""
    # Count dirty files
    status_proc = _git("status", "--porcelain", cwd=wt_path)
    dirty_count = len([line for line in status_proc.stdout.splitlines() if line.strip()])

    # Count unpushed commits
    log_proc = _git("log", f"origin/{base_branch}..HEAD", "--oneline", cwd=wt_path)
    unpushed_count = len([line for line in log_proc.stdout.splitlines() if line.strip()])

    # Count live processes
    live_process_count = _live_process_count(wt_path)

    return WorktreeHealth(
        dirty_count=dirty_count,
        unpushed_count=unpushed_count,
        live_process_count=live_process_count,
    )


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def _parse_porcelain(output: str) -> list[tuple[Path, str | None]]:
    """Parse ``git worktree list --porcelain`` into [(path, branch_or_None)].

    Every ``worktree`` block is registered exactly once, even when it has no
    ``branch refs/heads/...`` line (detached HEAD, or a bare repository) — in
    that case the branch is ``None`` rather than the block being dropped.
    """
    worktrees: list[tuple[Path, str | None]] = []
    current: Path | None = None
    current_branch: str | None = None

    def _flush() -> None:
        nonlocal current, current_branch
        if current is not None:
            worktrees.append((current, current_branch))
        current = None
        current_branch = None

    for raw in output.splitlines():
        line = raw.strip()
        if line.startswith("worktree "):
            _flush()
            current = Path(line[len("worktree ") :]).resolve()
        elif line.startswith("branch refs/heads/") and current is not None:
            current_branch = line[len("branch refs/heads/") :]
        elif not line:
            # Blank line ends the current block
            _flush()

    _flush()
    return worktrees


def discover_worktree_reports(repo_root: Path) -> list[WorktreeReport]:
    """Main entry point: discover all SDD worktrees and their task state.

    1. Parse ``git worktree list --porcelain``.
    2. Also scan WORKTREE_ROOT for orphan directories (not in porcelain).
    3. For each SDD branch, parse slug/id, read worktree index, check health.
    4. Compute ready_for_done.
    """
    # Get worktrees from git
    porcelain_proc = _git("worktree", "list", "--porcelain", cwd=repo_root)
    git_worktrees = _parse_porcelain(porcelain_proc.stdout)

    # Get all worktree paths from git
    git_worktree_paths = {path for path, _ in git_worktrees}

    # Scan WORKTREE_ROOT for orphan directories. WORKTREE_ROOT is relative
    # (".claude/worktrees") and must be resolved against repo_root, not the
    # process's current working directory (which may itself be a worktree).
    worktree_root = repo_root / WORKTREE_ROOT
    orphan_paths: list[Path] = []
    if worktree_root.exists():
        for entry in worktree_root.iterdir():
            if entry.is_dir() and entry.resolve() not in git_worktree_paths:
                orphan_paths.append(entry)

    # Build set of all worktree paths (git + orphans)
    all_worktree_paths = set(git_worktree_paths) | {p.resolve() for p in orphan_paths}

    reports: list[WorktreeReport] = []

    for wt_path in all_worktree_paths:
        # Try to get branch from git porcelain
        branch = None
        for path, b in git_worktrees:
            if path == wt_path:
                branch = b
                break

        # If not found in porcelain, try to get it from git
        if branch is None:
            branch_proc = _git("rev-parse", "--abbrev-ref", "HEAD", cwd=wt_path)
            if branch_proc.returncode == 0:
                branch = branch_proc.stdout.strip()
            else:
                # Detached HEAD or error
                continue

        # Parse branch name
        parsed = _parse_branch(branch)
        if parsed is None:
            # Not an SDD branch
            continue

        slug, feature_id, flow_type = parsed

        # Read worktree index
        tasks, base_branch = _read_worktree_index(wt_path, slug)
        index_found = len(tasks) > 0 or base_branch != "dev"

        # Check health
        health = _check_health(wt_path, base_branch)

        # Compute ready_for_done
        # All tasks must be done or done-with-issues, no dirty files, no unpushed commits
        all_done = all(t.status in ("done", "done-with-issues") for t in tasks) and len(tasks) > 0
        ready_for_done = all_done and health.dirty_count == 0 and health.unpushed_count == 0 and index_found

        reports.append(
            WorktreeReport(
                feature_slug=slug,
                feature_id=feature_id,
                flow_type=flow_type,
                worktree_path=str(wt_path),
                branch=branch,
                base_branch=base_branch,
                health=health,
                tasks=tasks,
                index_found=index_found,
                ready_for_done=ready_for_done,
            )
        )

    return reports


# ---------------------------------------------------------------------------
# Dev-index reconciliation
# ---------------------------------------------------------------------------

# A worktree may only ever ADVANCE a task's status, never roll it back.
# The dev-branch index is the merged, authoritative record; the worktree index
# is a live-but-unmerged one that can also be a stale pre-branch snapshot (a
# worktree branched before /sdd-task ran carries every task at "pending", and
# a worktree left behind after /sdd-done still carries its own copy long after
# the feature closed).  Taking the worktree as truth re-opens finished
# features; taking the maximum of the two shows work that started in a
# worktree without ever losing what dev already knows.
#
# "done" and "done-with-issues" share a rank so neither side can silently flip
# a finished task between the two terminal states; on a tie the dev value wins.
_STATUS_RANK: dict[str, int] = {
    "pending": 0,
    "in-progress": 1,
    "done": 2,
    "done-with-issues": 2,
}

_TERMINAL_STATUSES = ("done", "done-with-issues")


class ReconciledTask(BaseModel):
    """One task after merging the dev-branch index with a worktree index."""

    id: str
    status: Literal["pending", "in-progress", "done", "done-with-issues"]
    source: Literal["dev", "worktree"] = "dev"


class ReconciledFeature(BaseModel):
    """A feature's task state after dev/worktree reconciliation."""

    feature_slug: str
    feature_id: str | None = None
    spec: str | None = None
    index_path: str | None = None
    worktree_branch: str | None = None
    worktree_path: str | None = None
    #: at least one task's status was advanced by the worktree index
    worktree_ahead: bool = False
    #: the worktree index is behind dev everywhere it differs (leftover worktree)
    worktree_stale: bool = False
    #: dev already considers the feature finished (completed_at, or all tasks terminal)
    dev_closed: bool = False
    #: the feature has no index on dev at all — spec/tasks live only in the worktree
    worktree_only: bool = False
    tasks: list[ReconciledTask] = Field(default_factory=list)


def reconcile_feature(
    dev_index: dict | None,
    report: WorktreeReport | None,
) -> ReconciledFeature:
    """Merge one feature's dev-branch index with its worktree index.

    The worktree may only advance a task (``pending`` → ``in-progress`` →
    terminal); a lower-ranked worktree status is ignored and marks the
    worktree stale instead.  Tasks that exist only in the worktree index are
    appended (they were generated inside the worktree and never merged).

    Args:
        dev_index: The parsed ``sdd/tasks/index/<slug>.json`` from the current
            branch, or ``None`` when the feature exists only in a worktree.
        report: The worktree report for the same feature, or ``None``.

    Returns:
        The reconciled feature, carrying per-task provenance and the
        ``worktree_ahead`` / ``worktree_stale`` / ``dev_closed`` flags the
        task board uses for labelling.
    """
    dev_index = dev_index or {}
    dev_tasks = [t for t in dev_index.get("tasks", []) if isinstance(t, dict) and "id" in t]
    dev_by_id = {t["id"]: t for t in dev_tasks}

    dev_closed = bool(dev_index.get("completed_at")) or (
        bool(dev_tasks) and all(t.get("status") in _TERMINAL_STATUSES for t in dev_tasks)
    )

    wt_by_id: dict[str, WorktreeTaskStatus] = {}
    if report is not None and report.index_found:
        wt_by_id = {t.id: t for t in report.tasks}

    merged: list[ReconciledTask] = []
    ahead = False
    behind = False

    for task in dev_tasks:
        dev_status = task.get("status", "pending")
        wt_task = wt_by_id.get(task["id"])
        if wt_task is None:
            merged.append(ReconciledTask(id=task["id"], status=dev_status, source="dev"))
            continue
        dev_rank = _STATUS_RANK.get(dev_status, 0)
        wt_rank = _STATUS_RANK.get(wt_task.status, 0)
        if wt_rank > dev_rank:
            ahead = True
            merged.append(ReconciledTask(id=task["id"], status=wt_task.status, source="worktree"))
        else:
            behind = behind or wt_rank < dev_rank
            merged.append(ReconciledTask(id=task["id"], status=dev_status, source="dev"))

    # Tasks the worktree knows about and dev does not (generated in-worktree).
    for task_id, wt_task in wt_by_id.items():
        if task_id in dev_by_id:
            continue
        ahead = True
        merged.append(ReconciledTask(id=task_id, status=wt_task.status, source="worktree"))

    return ReconciledFeature(
        feature_slug=dev_index.get("feature") or (report.feature_slug if report else ""),
        feature_id=dev_index.get("feature_id") or (report.feature_id if report else None),
        spec=dev_index.get("spec"),
        index_path=dev_index.get("_index_path"),
        worktree_branch=report.branch if report else None,
        worktree_path=report.worktree_path if report else None,
        worktree_ahead=ahead,
        worktree_stale=bool(wt_by_id) and not ahead and behind,
        dev_closed=dev_closed,
        worktree_only=not dev_tasks and bool(wt_by_id),
        tasks=merged,
    )


def _load_dev_indexes(repo_root: Path) -> list[dict]:
    """Load every per-spec index on the current branch (``_orphans.json`` aside)."""
    index_dir = repo_root / "sdd" / "tasks" / "index"
    indexes: list[dict] = []
    if not index_dir.is_dir():
        return indexes
    for path in sorted(index_dir.glob("*.json")):
        if path.name == "_orphans.json":
            continue
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            data["_index_path"] = str(path.relative_to(repo_root))
            indexes.append(data)
    return indexes


def reconcile_reports(
    repo_root: Path,
    reports: list[WorktreeReport],
) -> list[ReconciledFeature]:
    """Reconcile every per-spec index on this branch with its worktree, if any.

    Features whose work only ever existed inside a worktree (no index on the
    current branch) are appended so the task board can surface them too.

    Args:
        repo_root: The primary checkout's root.
        reports: Worktree reports from :func:`discover_worktree_reports`.

    Returns:
        One :class:`ReconciledFeature` per dev index, plus one per
        worktree-only feature, in index-filename order.
    """
    by_feature_id = {r.feature_id: r for r in reports if r.feature_id}
    by_slug = {r.feature_slug: r for r in reports}

    reconciled: list[ReconciledFeature] = []
    matched: set[str] = set()

    for dev_index in _load_dev_indexes(repo_root):
        report = by_feature_id.get(dev_index.get("feature_id")) or by_slug.get(dev_index.get("feature"))
        if report is not None:
            matched.add(report.branch)
        reconciled.append(reconcile_feature(dev_index, report))

    for report in reports:
        if report.branch in matched or not report.index_found:
            continue
        reconciled.append(reconcile_feature(None, report))

    return reconciled


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    """CLI entry point.

    ``--json`` prints ``list[WorktreeReport]``; plain prints a table.
    ``--reconcile`` switches both outputs to ``list[ReconciledFeature]``, the
    dev-index/worktree merge the ``/sdd-status`` task board consumes.
    """
    import argparse

    parser = argparse.ArgumentParser(description="Discover SDD worktrees and report their task state and health.")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON array of WorktreeReport objects",
    )
    parser.add_argument(
        "--reconcile",
        action="store_true",
        help=(
            "Merge each worktree index into the dev-branch index (worktree may only advance a task) "
            "and report list[ReconciledFeature] instead of the raw worktree reports"
        ),
    )
    args = parser.parse_args()

    # Resolve repo root
    repo_root_proc = _git("rev-parse", "--show-toplevel", cwd=Path.cwd())
    if repo_root_proc.returncode != 0:
        print("error: not a git repository", file=sys.stderr)
        return 1
    repo_root = Path(repo_root_proc.stdout.strip())

    # Get reports
    reports = discover_worktree_reports(repo_root)

    if args.reconcile:
        features = reconcile_reports(repo_root, reports)
        if args.json:
            print(json.dumps([f.model_dump() for f in features], indent=2))
        else:
            print(f"{'Feature':<45} {'Id':<12} {'Tasks (done/total)':<20} {'Source'}")
            print("-" * 100)
            for feature in features:
                done = sum(1 for t in feature.tasks if t.status in ("done", "done-with-issues"))
                flags = []
                if feature.worktree_ahead:
                    flags.append(f"worktree ahead: {feature.worktree_branch}")
                if feature.worktree_stale:
                    flags.append(f"stale worktree: {feature.worktree_branch}")
                if feature.worktree_only:
                    flags.append("worktree only")
                source = ", ".join(flags) if flags else "dev"
                tasks_str = f"{done}/{len(feature.tasks)}"
                print(f"{feature.feature_slug:<45} {feature.feature_id or '-':<12} {tasks_str:<20} {source}")
        return 0

    if args.json:
        # JSON output
        output = json.dumps([r.model_dump() for r in reports], indent=2)
        print(output)
    else:
        # Plain table output
        print(f"{'Name':<40} {'Branch':<30} {'Feature':<15} {'Tasks':<12} {'Health':<20} {'Ready'}")
        print("-" * 130)
        for r in reports:
            # Name: feature_slug
            name = r.feature_slug
            if r.feature_id:
                name = f"{r.feature_slug} ({r.feature_id})"

            # Branch
            branch = r.branch

            # Tasks: N done / M total
            done_count = sum(1 for t in r.tasks if t.status in ("done", "done-with-issues"))
            total_count = len(r.tasks)
            tasks_str = f"{done_count}/{total_count}" if total_count > 0 else "0/0"

            # Health flags
            health_parts = []
            if r.health.dirty_count > 0:
                health_parts.append(f"dirty:{r.health.dirty_count}")
            if r.health.unpushed_count > 0:
                health_parts.append(f"unpushed:{r.health.unpushed_count}")
            if r.health.live_process_count > 0:
                health_parts.append(f"live:{r.health.live_process_count}")
            health_str = ", ".join(health_parts) if health_parts else "clean"

            # Ready flag
            ready_str = "✓" if r.ready_for_done else ""

            print(f"{name:<40} {branch:<30} {r.feature_id or '-':<15} {tasks_str:<12} {health_str:<20} {ready_str}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
