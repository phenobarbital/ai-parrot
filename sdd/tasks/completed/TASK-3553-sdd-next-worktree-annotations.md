# TASK-3553: `/sdd-next` — Worktree Progress Annotations

**Feature**: FEAT-582 — SDD Status — Worktree-Aware Task State
**Spec**: `sdd/specs/sdd-status-worktrees.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3549
**Assigned-to**: unassigned

---

## Context

> Updates both the `/sdd-next` command (`.claude/commands/sdd-next.md`) and
> its skill twin (`.agents/skills/sdd-next/SKILL.md`) to annotate task
> suggestions with real worktree progress. Features with active worktrees
> now show how far along they are, and features ready for `/sdd-done` get
> a suggestion to finish rather than start new tasks. Implements spec §3
> Module 4.

---

## Scope

- Modify `/sdd-next` command to call `worktree_status.py --json`.
- Annotate suggestions for features with worktrees: `(N/M done in worktree)`.
- Suggest `/sdd-done` for features where `ready_for_done: true` instead of
  suggesting new tasks.
- Mirror all changes in the skill twin.

**NOT in scope**: modifying the Python library (TASK-3549), tests (TASK-3550), or sdd-status (TASK-3551/3552).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.claude/commands/sdd-next.md` | MODIFY | Add worktree progress annotations |
| `.agents/skills/sdd-next/SKILL.md` | MODIFY | Mirror command changes |

---

## Codebase Contract (Anti-Hallucination)

### Verified Structure — Command
```markdown
# .claude/commands/sdd-next.md — current structure:
# §1 Read All Per-Spec Indexes (line 25)
# §2 Detect Active Worktrees (line 45) — already does `git worktree list`
# §3 Compute Unblocked Tasks (line 50)
# §4 Group and Annotate (line 55)
# §5 Sort and Present (line 64)
# §6 Show In-Progress Summary (line 100)
# §7 Show Ready Ledger Issues (line 109)
```

### Verified Structure — Skill
```markdown
# .agents/skills/sdd-next/SKILL.md — current structure:
# ## Workflow (line 22)
#   1. Aggregate tasks (line 24)
#   2. Inspect worktrees (line 27) — already mentions `git worktree list`
#   3. Compute unblocked tasks (line 29)
#   4. Group & annotate (line 32)
#   5. Sort (line 37)
#   6. Present list... (line 38)
#   7. (FEAT-566) Show ready ledger issues (line 39)
```

### WorktreeReport relevant fields
```json
{
  "feature_slug": "...",
  "feature_id": "FEAT-550",
  "tasks": [{"id": "TASK-3132", "status": "done"}, ...],
  "ready_for_done": true
}
```

### Does NOT Exist
- ~~`/sdd-next --worktrees`~~ — not a flag; worktree data is always shown

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": ".claude/commands/sdd-next.md",
      "action": "MODIFY"
    },
    {
      "path": ".agents/skills/sdd-next/SKILL.md",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Modify command §2 to also call `worktree_status --json` — *why*: richer data than bare `git worktree list`.
2. Modify command §4 to annotate with worktree progress — *why*: AC6 requires `(N/M done in worktree)`.
3. Add ready-for-done suggestion in command §5 — *why*: AC6 requires `/sdd-done` suggestion.
4. Mirror changes in the skill twin — *why*: skill must stay consistent with command.

### `.claude/commands/sdd-next.md` (MODIFY)

```markdown
# occurrences: 1 (verified: grep -c '### 2. Detect Active Worktrees' .claude/commands/sdd-next.md)
# AFTER — insert below `### 2. Detect Active Worktrees` block (verified: .claude/commands/sdd-next.md:45)

Additionally, call the worktree status library for richer data:
```bash
WT_REPORTS=$(python -m scripts.sdd.worktree_status --json 2>/dev/null || echo "[]")
```
Build a lookup from `feature_slug` → `WorktreeReport`. This provides task progress
counts and `ready_for_done` flags that the bare `git worktree list` cannot give.
```

```markdown
# occurrences: 1 (verified: grep -c '### 4. Group and Annotate' .claude/commands/sdd-next.md)
# AFTER — insert below the `### 4. Group and Annotate` introductory paragraph (verified: .claude/commands/sdd-next.md:55)

For features with a `WorktreeReport`:
- If `ready_for_done: true`: do NOT suggest new tasks. Instead show:
  ```
  FEAT-550 — Token Budget Bedrock
    ✅ All 14 tasks done — ready for /sdd-done FEAT-550
  ```
- If tasks are partially done: annotate the feature header with progress:
  ```
  FEAT-582 — SDD Status Worktrees  (3/5 done in worktree)
    🟢 Active worktree: feat-FEAT-582-sdd-status-worktrees
  ```

The progress count comes from: `done_count = sum(1 for t in report.tasks if t.status in ("done", "done-with-issues"))`.
```
**Why**: `/sdd-next` already detects worktrees (§2) but only for branch presence. This adds the task-level progress and ready-for-done intelligence that the worktree_status library provides, fulfilling AC6.

### `.agents/skills/sdd-next/SKILL.md` (MODIFY)

```markdown
# occurrences: 1 (verified: grep -c '2. Inspect worktrees' .agents/skills/sdd-next/SKILL.md)
# AFTER — insert below `2. Inspect worktrees:` and its sub-bullet (verified: .agents/skills/sdd-next/SKILL.md:27)

   - Additionally run `python -m scripts.sdd.worktree_status --json` for task-level progress and `ready_for_done` flags.
```

```markdown
# occurrences: 1 (verified: grep -c '4. Group & annotate' .agents/skills/sdd-next/SKILL.md)
# AFTER — insert below `4. Group & annotate:` and its sub-bullets (verified: .agents/skills/sdd-next/SKILL.md:32)

   - For features with `ready_for_done: true`: suggest `/sdd-done` instead of new tasks.
   - For features with worktree progress: annotate header with `(N/M done in worktree)`.
```
**Why**: The skill twin must mirror the command's worktree annotations so agents invoking the skill get the same intelligence.

### FILL IN checklist
- [ ] Command §2 enhancement with `worktree_status --json` call — bounded by AC6
- [ ] Command §4 progress annotation format — bounded by AC6
- [ ] Command §5 ready-for-done suggestion — bounded by AC6
- [ ] Skill step 2 and step 4 updates — bounded by AC6

---

## Acceptance Criteria

- [ ] `/sdd-next` annotates features with worktree progress `(N/M done in worktree)` (AC6)
- [ ] `/sdd-next` suggests `/sdd-done` for features where all tasks are complete (AC6)
- [ ] Skill twin mirrors the command changes
- [ ] No files outside `.claude/commands/` and `.agents/skills/` modified (AC10)

---

## Validation Commands

- `pytest tests/sdd_scripts/test_worktree_status.py -q`

---

## Test Specification

> This task modifies markdown command/skill files — testing is via manual
> invocation of `/sdd-next` and visual inspection. The underlying library
> tests are in TASK-3550.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/sdd-status-worktrees.spec.md` §3 Module 4
2. **Check dependencies** — TASK-3549 must be completed
3. **Read** both files: `.claude/commands/sdd-next.md` and `.agents/skills/sdd-next/SKILL.md`
4. **Implement** the modifications per the blueprint for both files
5. **Verify** by running `/sdd-next` and confirming annotations appear
6. **Move this file** to `sdd/tasks/completed/`
7. **Update index** → `"done"`

---

## Completion Note

**Completed by**: sdd-worker (orchestrator: google-compat/gemini-3.5-flash via parrot-sdd-coder)
**Date**: 2026-09-19
**Notes**: Updated `.claude/commands/sdd-next.md` and its skill twin
`.agents/skills/sdd-next/SKILL.md` to call `worktree_status.py --json`,
annotate feature headers with `(N/M done in worktree)`, and suggest
`/sdd-done` instead of new tasks when `ready_for_done: true`. Reviewed; no
unlisted files touched. Review recorded:
`coder-review:da2f3249eec989eb2b3e152b`.
Seat: gemini · Backend: google-compat · Model: gemini-3.5-flash · Attempts: 1 · Duration: 132.612s · Tokens: 265484/1770

**Deviations from spec**: none
