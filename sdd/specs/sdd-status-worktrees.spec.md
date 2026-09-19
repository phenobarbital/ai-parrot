---
type: feature
base_branch: dev
projects: [sdd-tooling]
tags: [sdd, worktree, observability, cli]
---

# Feature Specification: SDD Status — Worktree-Aware Task State

**Feature ID**: FEAT-582
**Date**: 2026-09-19
**Author**: Jesus Lara
**Status**: approved
**Target version**: 0.30.0

---

## 1. Motivation & Business Requirements

### Problem Statement

`/sdd-status` currently reads task state exclusively from the per-spec
indexes on the current branch (`dev`). This is wrong for features whose
work happens inside a worktree — the worktree carries its own copy of
the index, and `sdd-worker` updates *that* copy as tasks complete. The
dev-branch index is only updated when `/sdd-done` merges the worktree
back.

Concrete failure mode observed (FEAT-550): on `dev`, all 14 tasks show
`status: "done"` (post-merge), but inside the worktree all 14 show
`status: "pending"` (pre-branch snapshot). For features still in
progress, the dev-branch index shows every task as `"pending"` because
no merge has happened yet — even though the worktree's index has half
the tasks at `"done"`. The user has no way to see this without manually
`jq`-ing inside each worktree.

This makes `/sdd-status` misleading for the most common use cases:
- "Is feature X done? Can I run `/sdd-done`?" → dev says all pending,
  worktree says all done.
- "How far along is the sdd-worker run?" → dev has no visibility into
  worktree progress.
- "Which worktrees have work I forgot about?" → no worktree panel at all.

### Goals

- G1: `/sdd-status` shows the **true** task state per feature by reading
  the worktree's index when a worktree exists for that feature.
- G2: A new "Worktrees" panel shows all active worktrees with their
  health (dirty files, unpushed commits, live processes).
- G3: Features ready for `/sdd-done` (all tasks done in worktree, branch
  pushed, working tree clean) are flagged explicitly.
- G4: The worktree inspection is extracted as a reusable Python module
  (`scripts/sdd/worktree_status.py`) so `/sdd-next` and future commands
  can consume it.

### Non-Goals (explicitly out of scope)

- Automatically running `/sdd-done` when a feature is complete.
- Modifying any index or task file (this feature is strictly read-only).
- Merging or reconciling divergent indexes between dev and worktree.
- Changing how `sdd-worker` updates the index inside worktrees.

---

## 2. Architectural Design

### Overview

A new Python module `scripts/sdd/worktree_status.py` provides the
worktree inspection layer. It:

1. Discovers all registered worktrees via `git worktree list --porcelain`.
2. Maps each SDD worktree (branch name matches `feat-FEAT-<NNN>-*` or
   `hotfix-*-*`) to its feature slug and feature ID.
3. For each matched worktree, reads the per-spec index **inside the
   worktree** (the file at `<wt_path>/sdd/tasks/index/<slug>.json`).
4. Enriches each worktree with health signals: dirty file count,
   unpushed commit count, live process detection.
5. Returns a structured `WorktreeReport` per feature.

The `/sdd-status` command (`.claude/commands/sdd-status.md`) and its
skill twin (`.agents/skills/sdd-status/SKILL.md`) are updated to:

- Call `worktree_status.py` to get the worktree reports.
- For features with a worktree: show the **worktree index** status
  instead of (or alongside) the dev-branch index status, with a clear
  label indicating the source.
- Append a "Worktrees" summary panel after the task board.
- Flag features ready for `/sdd-done`.

### Component Diagram

```
/sdd-status (command/skill)
    │
    ├── reads sdd/tasks/index/*.json  (dev branch — existing)
    │
    └── calls scripts/sdd/worktree_status.py
            │
            ├── git worktree list --porcelain
            ├── parse branch → (feature_id, slug, type)
            ├── read <wt>/sdd/tasks/index/<slug>.json
            ├── git -C <wt> status --porcelain
            ├── git -C <wt> log origin/<base>..HEAD --oneline
            └── /proc/<pid>/cwd  (live process check)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `ensure_worktree._worktree_branches()` | pattern reuse | Same `git worktree list --porcelain` parsing; new module reimplements for richer output (not an import — `ensure_worktree` is a CLI script, not a library) |
| `remove_worktree.discover()` | pattern reuse | Dirty/unpushed/live-process detection pattern reused; but that module also does removal — we only need the read side |
| `sdd_meta.WORKTREE_ROOT` | import | Canonical worktree directory constant |
| `sdd_meta.plan_worktree()` | reference | Naming convention docs; not called at runtime (we parse existing names, not plan new ones) |
| Per-spec index files | reads | `sdd/tasks/index/<slug>.json` inside each worktree |

### Data Models

```python
from pydantic import BaseModel, Field
from typing import Literal

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
    health: WorktreeHealth
    tasks: list[WorktreeTaskStatus] = Field(default_factory=list)
    index_found: bool = True
    ready_for_done: bool = False
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: worktree_status.py | yes | Pydantic models above; `discover_worktree_reports(repo_root) -> list[WorktreeReport]`; branch-name regex; git subprocess calls | — |
| M2: sdd-status command update | yes | New §2.5 step; output format decided below; calls `python -m scripts.sdd.worktree_status --json` | — |
| M3: sdd-status skill update | yes | Mirror of M2 for the `.agents/skills/` twin | — |
| M4: sdd-next integration | yes | Same `worktree_status` call; annotates suggestions with worktree progress | — |
| M5: tests | yes | Fixtures for `git worktree list --porcelain` output, mock index JSON, process detection | — |

### Module 1: Worktree Status Library (`scripts/sdd/worktree_status.py`)

- **Path**: `scripts/sdd/worktree_status.py`
- **Responsibility**: Discover SDD worktrees, read their per-spec indexes,
  report health and task status. Pure read-only — no git mutations.
- **Depends on**: `scripts.sdd.sdd_meta` (for `WORKTREE_ROOT`)
- **Interface Skeleton**:
  ```python
  # scripts/sdd/worktree_status.py  (new)
  import re
  import json
  import subprocess
  from pathlib import Path
  from pydantic import BaseModel, Field
  from typing import Literal

  # Branch name patterns for SDD worktrees
  # feat-FEAT-<NNN>-<slug>  or  feat-<NNN>-<slug> (legacy)
  _FEAT_BRANCH_RE = re.compile(
      r"^feat-(?:FEAT-)?(\d+)-(.+)$"
  )
  # hotfix-<KEY>-<slug>
  _HOTFIX_BRANCH_RE = re.compile(
      r"^hotfix-([A-Z]+-\d+)-(.+)$"
  )

  class WorktreeTaskStatus(BaseModel): ...   # as §2
  class WorktreeHealth(BaseModel): ...       # as §2
  class WorktreeReport(BaseModel): ...       # as §2

  def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess:
      """Run git, return CompletedProcess (never raises)."""
      ...

  def _parse_branch(branch: str) -> tuple[str, str | None, Literal["feature", "hotfix"]] | None:
      """Parse an SDD branch name into (slug, feature_id_or_jira_key, flow_type).

      Returns None for non-SDD branches.
      """
      ...

  def _read_worktree_index(wt_path: Path, slug: str) -> list[WorktreeTaskStatus] | None:
      """Read the per-spec index inside a worktree. Returns None if not found."""
      ...

  def _check_health(wt_path: Path, base_branch: str) -> WorktreeHealth:
      """Dirty files, unpushed commits, live processes."""
      ...

  def _live_process_count(path: Path) -> int:
      """Count processes with cwd inside path (Linux /proc)."""
      ...

  def discover_worktree_reports(repo_root: Path) -> list[WorktreeReport]:
      """Main entry point: discover all SDD worktrees and their task state."""
      ...

  def main() -> int:
      """CLI: --json prints list[WorktreeReport]; plain prints a summary table."""
      ...
  ```

### Module 2: `/sdd-status` Command Update

- **Path**: `.claude/commands/sdd-status.md`
- **Responsibility**: Integrate worktree reports into the status board.
- **Depends on**: Module 1
- **Changes**:
  1. New step §2.5 between "Read All Per-Spec Indexes" and "Group and Display":
     run `python -m scripts.sdd.worktree_status --json` to get worktree reports.
  2. For features with a worktree report: show the worktree task statuses
     instead of (or alongside) the dev-branch ones, labeled
     `(from worktree: <branch>)`.
  3. New "Worktrees" panel at the end showing all active SDD worktrees,
     their health, and ready-for-done flags.
  4. Update the Summary line to include worktree count.

### Module 3: `/sdd-status` Skill Update

- **Path**: `.agents/skills/sdd-status/SKILL.md`
- **Responsibility**: Mirror M2 changes for the skill twin.
- **Depends on**: Module 2

### Module 4: `/sdd-next` Integration

- **Path**: `.claude/commands/sdd-next.md` + `.agents/skills/sdd-next/SKILL.md`
- **Responsibility**: Annotate task suggestions with worktree progress context.
- **Depends on**: Module 1
- **Changes**:
  1. Call `worktree_status.py` to get reports.
  2. For features with a worktree where tasks are in-progress/done:
     annotate the suggestion with `(N/M done in worktree)`.
  3. For features ready for `/sdd-done`: suggest running `/sdd-done`
     instead of starting new tasks.

### Module 5: Tests

- **Path**: `tests/sdd_scripts/test_worktree_status.py`
- **Responsibility**: Unit tests for `worktree_status.py`.
- **Depends on**: Module 1
- **Test cases**:
  - `_parse_branch` with feat/hotfix/non-SDD/legacy branches
  - `_read_worktree_index` with valid/missing/malformed JSON
  - `discover_worktree_reports` with mocked git output + mock filesystem
  - `ready_for_done` logic (all done + clean + pushed = True)
  - `_live_process_count` with mocked `/proc` (or skipped on non-Linux)
  - CLI `--json` output schema validation

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_parse_branch_feature` | M1 | `feat-FEAT-550-token-budget` → `("token-budget", "FEAT-550", "feature")` |
| `test_parse_branch_hotfix` | M1 | `hotfix-PAR-123-fix-foo` → `("fix-foo", "PAR-123", "hotfix")` |
| `test_parse_branch_legacy` | M1 | `feat-465-fix-weak-sha1` → `("fix-weak-sha1", "FEAT-465", "feature")` |
| `test_parse_branch_non_sdd` | M1 | `chore-ruff-config` → `None` |
| `test_read_worktree_index_valid` | M1 | Reads a mock index JSON and returns `WorktreeTaskStatus` list |
| `test_read_worktree_index_missing` | M1 | Returns `None` for non-existent path |
| `test_health_clean` | M1 | Clean worktree → `WorktreeHealth(0, 0, 0)` |
| `test_health_dirty` | M1 | Dirty worktree → non-zero `dirty_count` |
| `test_ready_for_done` | M1 | All tasks done + clean + pushed → `ready_for_done=True` |
| `test_not_ready_dirty` | M1 | All tasks done but dirty → `ready_for_done=False` |
| `test_discover_end_to_end` | M1 | Mocked git + filesystem → correct `WorktreeReport` list |
| `test_cli_json_output` | M1 | `--json` emits valid JSON matching schema |

### Test Data / Fixtures

```python
@pytest.fixture
def sample_porcelain_output():
    return (
        "worktree /repo\n"
        "HEAD abc123\n"
        "branch refs/heads/dev\n"
        "\n"
        "worktree /repo/.claude/worktrees/feat-FEAT-550-token-budget-bedrock\n"
        "HEAD def456\n"
        "branch refs/heads/feat-FEAT-550-token-budget-bedrock\n"
        "\n"
    )

@pytest.fixture
def sample_index():
    return {
        "feature": "token-budget-bedrock",
        "feature_id": "FEAT-550",
        "tasks": [
            {"id": "TASK-3132", "status": "done", "completed_at": "2026-09-10T23:54:36+00:00"},
            {"id": "TASK-3133", "status": "in-progress", "completed_at": None},
        ],
    }
```

---

## 5. Acceptance Criteria

- [x] AC1: `scripts/sdd/worktree_status.py` exists as a standalone module with
  CLI and library entry points.
- [ ] AC2: `python -m scripts.sdd.worktree_status --json` emits a JSON array of
  `WorktreeReport` objects, one per SDD worktree.
- [ ] AC3: `python -m scripts.sdd.worktree_status` (no `--json`) prints a
  human-readable table with columns: worktree name, branch, feature_id,
  task progress (N done / M total), health flags, ready-for-done.
- [ ] AC4: `/sdd-status` (command) shows worktree-sourced task status for
  features that have a worktree, labeled `(from worktree: <branch>)`.
- [ ] AC5: `/sdd-status` appends a "Worktrees" panel listing all SDD
  worktrees with health and ready-for-done flags.
- [ ] AC6: `/sdd-next` annotates suggestions for features with active
  worktrees showing progress (`N/M done in worktree`), and suggests
  `/sdd-done` for features where all tasks are complete.
- [ ] AC7: `ready_for_done` is True only when: all tasks in the worktree
  index are `"done"` or `"done-with-issues"`, `git status --porcelain` is
  empty, and there are no unpushed commits.
- [ ] AC8: All unit tests pass: `pytest tests/sdd_scripts/test_worktree_status.py -v`
- [ ] AC9: The module handles gracefully: missing worktree directory, missing
  index inside worktree, malformed JSON, non-SDD branches, detached HEAD
  worktrees.
- [ ] AC10: No files outside `scripts/sdd/`, `tests/sdd_scripts/`,
  `.claude/commands/`, and `.agents/skills/` are modified.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**

### Verified Imports

```python
from scripts.sdd.sdd_meta import WORKTREE_ROOT  # verified: packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py:322
# WORKTREE_ROOT = ".claude/worktrees"

from pydantic import BaseModel, Field  # verified: pyproject.toml dependency
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py
WORKTREE_ROOT: str = ".claude/worktrees"  # line 322

class WorktreePlan(BaseModel):  # line 328
    name: str
    path: str
    base_ref: str

def plan_worktree(  # line 336
    meta: FlowMeta,
    *,
    slug: str,
    feature_id: str | None = None,
    jira_key: str | None = None,
) -> WorktreePlan: ...

# scripts/sdd/ensure_worktree.py
def _worktree_branches(repo_root: Path) -> dict[Path, str]:  # line 137
    """Map every registered worktree path to its checked-out local branch."""

# scripts/remove_worktree.py
class Worktree:  # line 59
    path: Path
    branch: str | None
    registered: bool
    primary: bool = False
    live_processes: list[tuple[int, str]]
    def dirty_files(self) -> list[str]: ...  # line 79
    def unpushed(self) -> list[str]: ...     # line 86

def live_processes_in(path: Path) -> list[tuple[int, str]]:  # line 140
def discover() -> list[Worktree]:  # line 168
```

### Per-Spec Index JSON Schema (in worktree)

```json
{
  "feature": "<slug>",
  "feature_id": "FEAT-<NNN>",
  "spec": "sdd/specs/<slug>.spec.md",
  "type": "feature",
  "base_branch": "dev",
  "completed_at": null,
  "tasks": [
    {
      "id": "TASK-<NNN>",
      "status": "pending|in-progress|done|done-with-issues",
      "completed_at": null
    }
  ]
}
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `worktree_status._parse_worktrees()` | `git worktree list --porcelain` | subprocess | same pattern as `ensure_worktree.py:147` |
| `worktree_status._check_health()` | `git -C <wt> status --porcelain` | subprocess | same pattern as `remove_worktree.py:79-84` |
| `worktree_status._check_health()` | `git -C <wt> log origin/<base>..HEAD --oneline` | subprocess | same pattern as `remove_worktree.py:86-107` |
| `worktree_status._live_process_count()` | `/proc/<pid>/cwd` | os.readlink | same pattern as `remove_worktree.py:124-129` |
| `worktree_status._read_worktree_index()` | `<wt>/sdd/tasks/index/<slug>.json` | json.load | standard; path constructed from slug |

### Does NOT Exist (Anti-Hallucination)

- ~~`scripts.sdd.worktree_status`~~ — does not exist yet; this spec creates it
- ~~`sdd_meta.discover_worktrees()`~~ — no such function; discovery is done by `ensure_worktree` and `remove_worktree` independently
- ~~`sdd_meta.worktree_health()`~~ — does not exist; health checks are in `remove_worktree.Worktree`
- ~~`ensure_worktree.discover()`~~ — that function is in `remove_worktree`, not `ensure_worktree`
- ~~`scripts.sdd.close_task`~~ — the close script is a shell script (`close_task.sh`), not a Python module

### Configuration References

- `WORKTREE_ROOT = ".claude/worktrees"` — `sdd_meta.py:322`
- Branch naming: `feat-FEAT-<NNN>-<slug>` (feature), `hotfix-<KEY>-<slug>` (hotfix) — `sdd_meta.plan_worktree():379,383`
- Index location inside worktree: `<wt_path>/sdd/tasks/index/<slug>.json`

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Subprocess pattern**: use `subprocess.run(capture_output=True, text=True, check=False)` and check `returncode`, same as `ensure_worktree._git()` and `remove_worktree.run()`.
- **Pydantic for all models**: `WorktreeReport`, `WorktreeHealth`, `WorktreeTaskStatus`.
- **Read-only invariant**: the module MUST NOT write any file or run any mutating git command.
- **Graceful degradation**: every external call (git, /proc, json.load) must be wrapped in try/except and degrade to "unknown" state, never crash the whole report.
- **CLI entry point**: `if __name__ == "__main__": sys.exit(main())` with `--json` flag.

### Known Risks / Gotchas

1. **Worktree directory exists but git doesn't track it** (orphan): `git worktree list --porcelain` won't show it. The module should also scan `WORKTREE_ROOT` for directories not in the porcelain output (same pattern as `remove_worktree.discover()`).
2. **Index inside worktree may be stale**: the worktree was branched before tasks were generated. In this case `index_found=False` and the dev-branch index is used.
3. **Legacy branch naming**: some worktrees use `feat-<NNN>-<slug>` (without the `FEAT-` prefix, e.g. `feat-465-fix-weak-sha1-arango-store`). The regex must handle both.
4. **Non-SDD worktrees**: branches like `chore-ruff-config` or `fix-*` are not SDD features — they have no per-spec index and are shown in the worktree panel but not matched to a feature.
5. **`/proc` is Linux-only**: live process detection should be best-effort; on non-Linux, `_live_process_count()` returns 0.
6. **Performance**: with 33+ worktrees, running `git -C <wt> status` for each is ~2-3 seconds total. Acceptable for a CLI status command.
7. **sdd-coder sub-worktrees**: branches like `TASK-3351-a1-*` are task-level sub-worktrees created by the sdd-coder engine inside the feature worktree. These are NOT feature worktrees — `_parse_branch` must return None for them.

### External Dependencies

No new external dependencies. Uses only stdlib + pydantic (already a project dependency).

---

## 8. Open Questions

- [x] Should the worktree index *replace* or be shown *alongside* the dev-branch index? — *Resolved*: Replace when a worktree exists (the worktree is truth for active work); the dev-branch status is only shown for features without a worktree.
- [x] Should non-SDD worktrees (chore-*, fix-*) be shown? — *Resolved*: Yes, in the Worktrees panel only (no task board entry since they have no per-spec index).
- [ ] Should `/sdd-status --worktrees-only` be a flag to show just the worktree panel? — *Owner: Jesus* — can be deferred to implementation.
- [ ] Should `worktree_status.py` reuse `remove_worktree.discover()` directly or reimplement? — *Owner: implementer* — Both are viable; reimplementing keeps `worktree_status` self-contained and avoids importing a CLI script's internals. Recommended: reimplement the subset needed.

---

## 9. Design Research Cross-Check

Status: skipped (no exploration document with status accepted)

---

## Worktree Strategy

- **Isolation**: one worktree for this feature.
- **Module dependency graph**: M1 is the foundation → M2 + M3 + M4 depend on M1 → M5 depends on M1.
  M2, M3, M4 have no edges between them (parallel-safe).
- **Shared files**: none — each module touches different files.
- **Exclusive resources**: none.
- **Cross-feature dependencies**: none.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-19 | Jesus Lara | Initial draft |
