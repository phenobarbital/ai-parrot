# TASK-3551: `/sdd-status` Command — Worktree Panel Integration

**Feature**: FEAT-582 — SDD Status — Worktree-Aware Task State
**Spec**: `sdd/specs/sdd-status-worktrees.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3549
**Assigned-to**: unassigned

---

## Context

> Updates the `/sdd-status` command (`.claude/commands/sdd-status.md`) to
> integrate worktree-sourced task status. When a feature has an active SDD
> worktree, the command now shows the worktree's index status instead of
> the dev-branch status — the worktree is the source of truth for active
> work. Also adds a "Worktrees" summary panel and flags features ready
> for `/sdd-done`. Implements spec §3 Module 2.

---

## Scope

- Add a new step §2.5 to `/sdd-status` that calls `python -m scripts.sdd.worktree_status --json`.
- For features with a worktree report: show worktree task statuses labeled `(from worktree: <branch>)`.
- Add a "Worktrees" panel after the task board showing all SDD worktrees with health and ready-for-done.
- Update the Summary line to include worktree count.

**NOT in scope**: modifying the Python library (TASK-3549), tests (TASK-3550), skill (TASK-3552), or sdd-next (TASK-3553).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.claude/commands/sdd-status.md` | MODIFY | Add worktree integration steps |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```bash
# The command calls this CLI:
python -m scripts.sdd.worktree_status --json
# Returns: JSON array of WorktreeReport objects (created by TASK-3549)
```

### Existing Structure to Modify
```markdown
# .claude/commands/sdd-status.md — current structure:
# §1 Read All Per-Spec Indexes (line 24)
# §2 Group and Display (line 48)
# §3 Highlight Blockers (line 88)
# §4 Show Orphan Tasks (line 95)
# New §2.5 goes between §1 and §2.
```

### WorktreeReport JSON shape (from TASK-3549)
```json
{
  "feature_slug": "token-budget-bedrock",
  "feature_id": "FEAT-550",
  "flow_type": "feature",
  "worktree_path": ".claude/worktrees/feat-FEAT-550-token-budget-bedrock",
  "branch": "feat-FEAT-550-token-budget-bedrock",
  "base_branch": "dev",
  "health": {"dirty_count": 0, "unpushed_count": 0, "live_process_count": 0},
  "tasks": [{"id": "TASK-3132", "status": "done", "completed_at": "..."}],
  "index_found": true,
  "ready_for_done": true
}
```

### Does NOT Exist
- ~~`/sdd-status --worktrees-only`~~ — deferred (spec §8 open question)

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": ".claude/commands/sdd-status.md",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Add step §1.5 to call `worktree_status --json` — *why*: must have worktree data before grouping.
2. Modify §2 to use worktree task statuses when available — *why*: worktree is truth for active features (AC4).
3. Add §4.5 Worktrees panel after orphans — *why*: new panel showing all SDD worktrees (AC5).
4. Update Summary line — *why*: include worktree count for quick overview.

### `.claude/commands/sdd-status.md` (MODIFY)

```markdown
# occurrences: 1 (verified: grep -c '### 2. Group and Display' .claude/commands/sdd-status.md)
# BEFORE — insert above `### 2. Group and Display` (verified: .claude/commands/sdd-status.md:48)

### 1.5. Discover Worktree State (FEAT-582)

Run the worktree status library to get the real task state from active worktrees:

```bash
WT_REPORTS=$(python -m scripts.sdd.worktree_status --json 2>/dev/null || echo "[]")
```

Build a lookup map from `feature_slug` → `WorktreeReport`. For each feature in §2,
if a worktree report exists with `index_found: true`, use its `tasks[]` array
instead of the dev-branch index for that feature's task lines.

Label the source: append `(from worktree: <branch>)` after the feature header
when using worktree data. When `index_found: false`, note
`(worktree exists but index not found — using dev branch)`.
```

```markdown
# occurrences: 1 (verified: grep -c '## Reference' .claude/commands/sdd-status.md)
# BEFORE — insert above `## Reference` (verified: .claude/commands/sdd-status.md:113)

### 5. Show Worktree Summary (FEAT-582)

After the orphan panel, show a worktree health panel for all SDD worktrees
from the `WT_REPORTS` data:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🌳 Worktrees (N active):

  feat-FEAT-550-token-budget-bedrock
    Branch: feat-FEAT-550-token-budget-bedrock
    Tasks: 14/14 done  |  Health: clean  |  ✅ Ready for /sdd-done

  feat-FEAT-582-sdd-status-worktrees
    Branch: feat-FEAT-582-sdd-status-worktrees
    Tasks: 2/5 done  |  Health: 3 dirty, 1 unpushed  |  🔄 In progress

  chore-ruff-config  (non-SDD)
    Branch: chore-ruff-config
    Health: clean
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

Health flags:
- `clean` = dirty_count == 0 AND unpushed_count == 0
- `N dirty` = dirty_count > 0
- `N unpushed` = unpushed_count > 0
- `N live processes` = live_process_count > 0

Ready-for-done flag:
- `✅ Ready for /sdd-done` when `ready_for_done: true`
- `🔄 In progress` when tasks are not all done
- `⚠️ Done but needs cleanup` when all done but dirty/unpushed

Non-SDD worktrees (those with no parsed feature_id) show health only, no task
counts.

Update the Summary line to include:
```
Summary: <N> done / ... / <N> total | <W> worktrees (<R> ready for /sdd-done)
```
```
**Why**: The command currently has no worktree awareness. These additions implement spec §3 Module 2's three changes: worktree-sourced task status, worktree panel, and summary line update.

### FILL IN checklist
- [ ] §1.5 worktree data retrieval and lookup map construction — bounded by AC4
- [ ] §2 integration of worktree task statuses into per-feature display — bounded by AC4
- [ ] §5 worktree summary panel formatting — bounded by AC5
- [ ] Summary line update with worktree count — bounded by AC5

---

## Acceptance Criteria

- [ ] `/sdd-status` shows worktree-sourced task status for features with a worktree (AC4)
- [ ] `/sdd-status` appends a "Worktrees" panel listing all SDD worktrees (AC5)
- [ ] Source is labeled `(from worktree: <branch>)` for worktree-sourced data
- [ ] Summary line includes worktree count and ready-for-done count
- [ ] Non-SDD worktrees appear in the panel with health only
- [ ] No files outside `.claude/commands/` modified (AC10)

---

## Validation Commands

- `pytest tests/sdd_scripts/test_worktree_status.py -q`

---

## Test Specification

> This task modifies a markdown command file — testing is via manual invocation
> of `/sdd-status` and visual inspection. The worktree library tests in
> TASK-3550 validate the underlying data.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/sdd-status-worktrees.spec.md` §3 Module 2
2. **Check dependencies** — TASK-3549 must be completed
3. **Read** `.claude/commands/sdd-status.md` for the current structure
4. **Implement** the modifications per the blueprint
5. **Verify** by running `/sdd-status` and confirming the new panels appear
6. **Move this file** to `sdd/tasks/completed/`
7. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: 
**Date**: 
**Notes**: 

**Deviations from spec**: none | describe if any
