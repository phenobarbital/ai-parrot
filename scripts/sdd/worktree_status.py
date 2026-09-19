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


def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    """Run a git command, return CompletedProcess (never raises on failure)."""
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        text=True,
        capture_output=True,
    )


# ---------------------------------------------------------------------------
# Branch parsing
# ---------------------------------------------------------------------------


def _parse_branch(
    branch: str,
) -> tuple[str, str | None, Literal["feature", "hotfix"]] | None:
    """Parse an SDD branch name into (slug, feature_id_or_jira_key, flow_type).

    Returns None for non-SDD branches (chore-*, fix-*, detached, etc.).
    Handles both ``feat-FEAT-550-slug`` and legacy ``feat-550-slug``.
    """
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
        except (KeyError, TypeError):
            # Skip malformed task entries
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

    # Scan WORKTREE_ROOT for orphan directories
    worktree_root = Path(WORKTREE_ROOT)
    orphan_paths: list[Path] = []
    if worktree_root.exists():
        for entry in worktree_root.iterdir():
            if entry.is_dir() and entry.name not in git_worktree_paths:
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
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    """CLI entry point.  --json prints list[WorktreeReport]; plain prints a table."""
    import argparse

    parser = argparse.ArgumentParser(description="Discover SDD worktrees and report their task state and health.")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON array of WorktreeReport objects",
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
