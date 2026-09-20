# TASK-3552: `/sdd-status` Skill — Worktree Integration

**Feature**: FEAT-582 — SDD Status — Worktree-Aware Task State
**Spec**: `sdd/specs/sdd-status-worktrees.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3549
**Assigned-to**: unassigned

---

## Context

> Updates the `/sdd-status` skill twin (`.agents/skills/sdd-status/SKILL.md`)
> to mirror the worktree integration added to the command in TASK-3551.
> The skill is the agent-facing version of the command and must stay
> consistent. Implements spec §3 Module 3.

---

## Scope

- Add a worktree discovery step to the skill's workflow.
- Add instructions for using worktree task data when available.
- Add the worktree summary panel to the output format.
- Update references.

**NOT in scope**: modifying the Python library (TASK-3549), tests (TASK-3550), command (TASK-3551), or sdd-next (TASK-3553).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.agents/skills/sdd-status/SKILL.md` | MODIFY | Add worktree integration to workflow |

---

## Codebase Contract (Anti-Hallucination)

### Verified Structure
```markdown
# .agents/skills/sdd-status/SKILL.md — current structure (42 lines):
# name: sdd-status (line 2)
# description: Aggregate task state... (line 3)
# ## Purpose (line 8)
# ## Guardrails (line 12)
# ## Workflow (line 17)
#   1. Load all per-spec indexes (line 24)
#   2. Group tasks by feature and status (line 28)
#   3. Highlight blockers (line 33)
#   4. Surface orphans (line 35)
#   5. Print summary totals (line 37)
# ## References (line 39)
```

### Does NOT Exist
- ~~`.agents/skills/sdd-status/SKILL.md` worktree steps~~ — this task adds them

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": ".agents/skills/sdd-status/SKILL.md",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Add worktree step between existing steps 1 and 2 — *why*: worktree data must be available before grouping.
2. Update step 2 to mention worktree task source — *why*: agents need to know which source to use.
3. Add step 5 for the worktree panel — *why*: mirrors the command's §5.
4. Update summary step and references — *why*: completeness.

### `.agents/skills/sdd-status/SKILL.md` (MODIFY)

```markdown
# occurrences: 1 (verified: grep -c '2. Group tasks by feature and status' .agents/skills/sdd-status/SKILL.md)
# BEFORE — insert above `2. Group tasks by feature and status` (verified: .agents/skills/sdd-status/SKILL.md:28)

1.5. Discover worktree state (FEAT-582):
   - Run `python -m scripts.sdd.worktree_status --json` to get worktree reports.
   - Build a map from `feature_slug` → `WorktreeReport`.
   - For features with a worktree (`index_found: true`): use the worktree's `tasks[]` instead of the dev-branch index. Label with `(from worktree: <branch>)`.
```

```markdown
# occurrences: 1 (verified: grep -c '5. Print summary totals' .agents/skills/sdd-status/SKILL.md)
# AFTER — insert below `5. Print summary totals (done, done-with-issues, in-progress, pending, total).` (verified: .agents/skills/sdd-status/SKILL.md:37)

6. Show worktree summary (FEAT-582):
   - List all SDD worktrees with: name, branch, task progress (N/M done), health flags, ready-for-done.
   - Non-SDD worktrees show health only, no task counts.
   - Flag `✅ Ready for /sdd-done` when `ready_for_done: true`.
   - Include worktree count in the summary line.
```
**Why**: The skill is the agent-facing twin of the command. Agents that invoke `sdd-status` (e.g., dev-loop orchestrators) need the same worktree awareness to make correct scheduling decisions.

### FILL IN checklist
- [ ] Step 1.5 worktree discovery instructions — bounded by AC4
- [ ] Step 2 update to reference worktree source — bounded by AC4
- [ ] Step 6 worktree panel instructions — bounded by AC5
- [ ] Summary step update — bounded by AC5

---

## Acceptance Criteria

- [ ] `.agents/skills/sdd-status/SKILL.md` includes worktree discovery step
- [ ] Skill workflow references worktree-sourced task data
- [ ] Skill workflow includes worktree summary panel
- [ ] No files outside `.agents/skills/` modified (AC10)

---

## Validation Commands

- `pytest tests/sdd_scripts/test_worktree_status.py -q`

---

## Test Specification

> This task modifies a markdown skill file — testing is via manual skill
> invocation. The underlying library tests are in TASK-3550.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/sdd-status-worktrees.spec.md` §3 Module 3
2. **Check dependencies** — TASK-3549 must be completed
3. **Read** `.agents/skills/sdd-status/SKILL.md` for the current structure
4. **Implement** the modifications per the blueprint
5. **Move this file** to `sdd/tasks/completed/`
6. **Update index** → `"done"`

---

## Completion Note

**Completed by**: sdd-worker (orchestrator: nova/mistral.devstral-2-123b via parrot-sdd-coder)
**Date**: 2026-09-19
**Notes**: Mirrored the M2 changes into `.agents/skills/sdd-status/SKILL.md`
(worktree discovery step 1.5, worktree summary step 6, references updated).
Reviewed; no unlisted files touched. Review recorded:
`coder-review:42be1bd84adb45d535fc970c`.
Seat: mistral · Backend: nova · Model: mistral.devstral-2-123b · Attempts: 1 · Duration: 243.244s · Tokens: 410239/2193

**Deviations from spec**: none
