# TASK-3549: Worktree Status Library — discovery, health, CLI

**Feature**: FEAT-582 — SDD Status — Worktree-Aware Task State
**Spec**: `sdd/specs/sdd-status-worktrees.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

> This is the foundation module for FEAT-582. It provides a reusable Python
> library that discovers all SDD worktrees, reads their per-spec indexes,
> reports health signals (dirty files, unpushed commits, live processes),
> and flags features ready for `/sdd-done`. All other tasks in this feature
> depend on this module. Implements spec §3 Module 1.

---

## Scope

- Implement Pydantic models: `WorktreeTaskStatus`, `WorktreeHealth`, `WorktreeReport`.
- Implement `_parse_branch()` to extract `(slug, feature_id_or_key, flow_type)` from SDD branch names.
- Implement `_read_worktree_index()` to read `<wt>/sdd/tasks/index/<slug>.json`.
- Implement `_check_health()` for dirty files, unpushed commits, live process count.
- Implement `_live_process_count()` via `/proc` (Linux best-effort).
- Implement `discover_worktree_reports()` as the main entry point.
- Implement `main()` CLI with `--json` flag.
- Handle all graceful degradation: missing directories, malformed JSON, non-SDD branches, detached HEAD, non-Linux `/proc`.

**NOT in scope**: modifying any command/skill file (TASK-3551/3552/3553), writing tests (TASK-3550).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `scripts/sdd/worktree_status.py` | CREATE | Main library + CLI entry point |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from scripts.sdd.sdd_meta import WORKTREE_ROOT  # verified: scripts/sdd/sdd_meta.py:15 (shim re-export)
# WORKTREE_ROOT = ".claude/worktrees"  — verified: packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py:322

from pydantic import BaseModel, Field  # verified: pyproject.toml dependency
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py
WORKTREE_ROOT: str = ".claude/worktrees"  # line 322

# Pattern reference (not imported — reimplemented):
# scripts/sdd/ensure_worktree.py:137
# def _worktree_branches(repo_root: Path) -> dict[Path, str]:
#     Parses `git worktree list --porcelain`

# scripts/remove_worktree.py:140
# def live_processes_in(path: Path) -> list[tuple[int, str]]:
#     Uses /proc/<pid>/cwd via os.readlink

# scripts/remove_worktree.py:124
# def _proc_cwd(pid: int) -> Path | None:
#     os.readlink(f"/proc/{pid}/cwd")
```

### Per-Spec Index JSON structure (read from worktree)
```json
{
  "feature": "<slug>",
  "feature_id": "FEAT-<NNN>",
  "base_branch": "dev",
  "tasks": [
    { "id": "TASK-<NNN>", "status": "pending|in-progress|done|done-with-issues", "completed_at": null }
  ]
}
```

### Does NOT Exist
- ~~`scripts.sdd.worktree_status`~~ — this task creates it
- ~~`sdd_meta.discover_worktrees()`~~ — no such function
- ~~`sdd_meta.worktree_health()`~~ — does not exist
- ~~`ensure_worktree.discover()`~~ — that function is in `remove_worktree`, not `ensure_worktree`

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "scripts/sdd/worktree_status.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Create `scripts/sdd/worktree_status.py` with all Pydantic models — *why*: all other functions return these models.
2. Implement `_git()` helper — *why*: every git call uses this pattern (subprocess, capture, no raise).
3. Implement `_parse_branch()` — *why*: maps branch names to (slug, id, type); used by discovery.
4. Implement `_read_worktree_index()` — *why*: reads the per-spec index inside a worktree path.
5. Implement `_live_process_count()` and `_check_health()` — *why*: enriches each report with health signals.
6. Implement `discover_worktree_reports()` — *why*: the main entry point that orchestrates all of the above.
7. Implement `main()` CLI — *why*: provides `--json` and plain-table output for commands/skills to call.

### `scripts/sdd/worktree_status.py` (CREATE)
```python
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
        ["git", *args], cwd=str(cwd), text=True, capture_output=True,
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
    wt_path: Path, slug: str,
) -> tuple[list[WorktreeTaskStatus], str]:
    """Read the per-spec index inside a worktree.

    Returns (task_list, base_branch).  task_list is empty if not found or
    malformed.  base_branch defaults to ``"dev"`` on any failure.
    """
    # FILL IN: locate index at <wt_path>/sdd/tasks/index/<slug>.json,
    #   json.load it, extract tasks[] and base_branch from header.
    #   Wrap in try/except for FileNotFoundError, json.JSONDecodeError,
    #   KeyError.  Return ([], "dev") on any failure.
    #   — bounded by AC9 (graceful degradation)
    raise NotImplementedError


# ---------------------------------------------------------------------------
# Health checks
# ---------------------------------------------------------------------------

def _live_process_count(path: Path) -> int:
    """Count processes with cwd inside path (Linux /proc, best-effort)."""
    # FILL IN: iterate /proc/<pid>/cwd via os.readlink, count those inside
    #   path.  Return 0 on non-Linux or any OSError.
    #   Pattern: remove_worktree.py:140-165
    #   — bounded by AC9 (non-Linux returns 0)
    raise NotImplementedError


def _check_health(wt_path: Path, base_branch: str) -> WorktreeHealth:
    """Dirty files, unpushed commits, live processes."""
    # FILL IN: run git -C <wt_path> status --porcelain (count lines),
    #   git -C <wt_path> log origin/<base_branch>..HEAD --oneline (count lines),
    #   _live_process_count(wt_path).
    #   Pattern: remove_worktree.py:79-107
    #   — bounded by AC7 (ready_for_done depends on these being accurate)
    raise NotImplementedError


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def _parse_porcelain(output: str) -> list[tuple[Path, str | None]]:
    """Parse ``git worktree list --porcelain`` into [(path, branch_or_None)]."""
    # FILL IN: parse blocks separated by blank lines.  Each block has
    #   "worktree <path>" and optionally "branch refs/heads/<name>".
    #   Pattern: ensure_worktree.py:137-156
    #   — bounded by spec §2 Component Diagram
    raise NotImplementedError


def discover_worktree_reports(repo_root: Path) -> list[WorktreeReport]:
    """Main entry point: discover all SDD worktrees and their task state.

    1. Parse ``git worktree list --porcelain``.
    2. Also scan WORKTREE_ROOT for orphan directories (not in porcelain).
    3. For each SDD branch, parse slug/id, read worktree index, check health.
    4. Compute ready_for_done.
    """
    # FILL IN: orchestrate _parse_porcelain, _parse_branch,
    #   _read_worktree_index, _check_health.  Compute ready_for_done =
    #   (all tasks done/done-with-issues AND dirty_count == 0
    #    AND unpushed_count == 0 AND len(tasks) > 0 AND index_found).
    #   Also scan repo_root / WORKTREE_ROOT for directories not in porcelain
    #   output (orphans — report them with index_found=False).
    #   — bounded by AC2, AC7, AC9
    raise NotImplementedError


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    """CLI entry point.  --json prints list[WorktreeReport]; plain prints a table."""
    # FILL IN: argparse with --json flag.  Resolve repo_root via
    #   git rev-parse --show-toplevel.  Call discover_worktree_reports.
    #   --json: json.dumps([r.model_dump() for r in reports]).
    #   plain: tabular output with columns: Name, Branch, Feature, Tasks, Health, Ready.
    #   — bounded by AC2, AC3
    raise NotImplementedError


if __name__ == "__main__":
    sys.exit(main())
```
**Why this shape**: The Pydantic models, regex patterns, and function signatures are fixed by the spec's §2 Data Models and §3 Module 1 Interface Skeleton.  The `_git()` helper follows the established subprocess pattern from `ensure_worktree.py` and `remove_worktree.py`.  `FILL IN` stubs cover the business logic (index reading, health checks, discovery orchestration, CLI formatting) which requires judgement about error handling paths.

### FILL IN checklist
- [ ] `_read_worktree_index` — JSON loading + error handling; bounded by AC9
- [ ] `_live_process_count` — /proc iteration, Linux-only; bounded by AC9
- [ ] `_check_health` — 3 git/OS calls + aggregation; bounded by AC7
- [ ] `_parse_porcelain` — porcelain block parsing; bounded by spec §2
- [ ] `discover_worktree_reports` — orchestration + orphan scan + ready_for_done; bounded by AC2, AC7, AC9
- [ ] `main` — argparse + table formatting; bounded by AC2, AC3

---

## Acceptance Criteria

- [ ] `scripts/sdd/worktree_status.py` exists with all Pydantic models and functions
- [ ] `python -m scripts.sdd.worktree_status --json` emits valid JSON array of WorktreeReport objects (AC2)
- [ ] `python -m scripts.sdd.worktree_status` prints a human-readable table (AC3)
- [ ] `_parse_branch` handles feat/hotfix/legacy/non-SDD/detached branches correctly
- [ ] `ready_for_done` is True only when all tasks done/done-with-issues + clean + pushed (AC7)
- [ ] Graceful degradation for all failure modes (AC9)
- [ ] No files outside `scripts/sdd/` modified (AC10)
- [ ] No linting errors: `ruff check scripts/sdd/worktree_status.py`

---

## Validation Commands

- `pytest tests/sdd_scripts/test_worktree_status.py -q`

---

## Test Specification

> Tests are written in TASK-3550. This task's validation depends on those tests.

```python
# Minimal smoke test the implementer should verify manually:
# python -m scripts.sdd.worktree_status --json
# python -m scripts.sdd.worktree_status
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/sdd-status-worktrees.spec.md` for full context
2. **Check dependencies** — this task has none
3. **Verify the Codebase Contract** — confirm `WORKTREE_ROOT` is still at `scripts/sdd/sdd_meta.py:15`
4. **Implement** — start from the Implementation Blueprint, complete every `FILL IN` marker
5. **Verify** — run `python -m scripts.sdd.worktree_status --json` in the repo root
6. **Move this file** to `sdd/tasks/completed/TASK-3549-worktree-status-library.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (orchestrator: nova/zai.glm-4.7-flash via parrot-sdd-coder; fix by orchestrator)
**Date**: 2026-09-19
**Notes**: Implemented `scripts/sdd/worktree_status.py` per the Interface
Skeleton: Pydantic models (`WorktreeTaskStatus`, `WorktreeHealth`,
`WorktreeReport`), `_parse_branch`, `_read_worktree_index`, `_check_health`,
`_live_process_count`, `discover_worktree_reports`, `main` (CLI with
`--json`). Post-merge smoke test (`python -m scripts.sdd.worktree_status
--json`/plain, per the task's own Test Specification) found the delivered
`_read_worktree_index` built the index path as `sdd/tasks/<slug>.json`
instead of the spec-documented `sdd/tasks/index/<slug>.json`, so
`index_found` was always `False`. Fixed by the orchestrator in commit
`3446bf986` and re-verified with the same smoke test (index_found=true,
all 5 FEAT-582 tasks correctly listed). Feedback recorded:
`coder-feedback:5812b09407a0ef0dedc23bb7`; review recorded:
`coder-review:b036cb7bcb898d1560d701f8`.
A second defect surfaced while implementing TASK-3550's tests: `_parse_porcelain`
silently dropped detached-HEAD/bare worktree blocks instead of returning
`branch=None`, violating AC9. Fixed in commit `e4b4739f6`; feedback recorded:
`coder-feedback:b94d2b535b26c39aef85025f`.
Seat: glm · Backend: nova · Model: zai.glm-4.7-flash · Attempts: 1 · Duration: 228.012s · Tokens: 407766/3846

**Deviations from spec**: none (fix aligned implementation to the documented path; no scope change)
