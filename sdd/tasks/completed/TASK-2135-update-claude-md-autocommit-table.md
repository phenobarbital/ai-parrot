# TASK-2135: Update CLAUDE.md Auto-Commit Table for sdd-done

**Feature**: FEAT-414 — Fix sdd-done Merge Conflicts
**Spec**: `sdd/specs/sdd-done-merge-conflict-fix.spec.md`
**Status**: done
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2133
**Assigned-to**: sdd-worker

---

## Context

After TASK-2133 changes where `/sdd-done` commits (feature branch instead of
`base_branch`), the "SDD Auto-Commit Rule" table in `CLAUDE.md` must be
updated to reflect the new behavior.

Implements Spec §3 Module 3.

---

## Scope

- **Update** the `/sdd-done` row in the "SDD Auto-Commit Rule" table
  (line 239 of `CLAUDE.md`) to reflect:
  - What it commits: verification stamp on per-spec index (not "Per-spec index
    final state + task file moves")
  - Where: worktree / feature branch (not `base_branch`)

**NOT in scope**:
- Changing any other rows in the table
- Changing sdd-done.md (done in TASK-2133 and TASK-2134)
- Changing any other section of CLAUDE.md

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `CLAUDE.md` | MODIFY | Update `/sdd-done` row in Auto-Commit table (line 239) |

---

## Codebase Contract (Anti-Hallucination)

### Current Line to Replace (line 239 of `CLAUDE.md`)

```markdown
| `/sdd-done`       | Per-spec index final state + task file moves; merges feature → `base_branch` | `base_branch` (NEVER `main`) |
```

### Replacement Line

```markdown
| `/sdd-done`       | Verification stamp on per-spec index (committed on feature branch); merges feature → `base_branch` | worktree (feature branch), merged to `base_branch` by Step 9 |
```

### Surrounding Context (lines 236–241 for orientation)

```markdown
| `/sdd-spec`       | `sdd/specs/<n>.spec.md` (with frontmatter) + a `reserve_ids.py` FEAT-ID reservation commit to `sdd/tasks/.id_ledger.json` (FEAT-387) | `base_branch` |
| `/sdd-task`       | `sdd/tasks/index/<feature>.json` + `sdd/tasks/active/TASK-*` + a `reserve_ids.py` TASK-ID reservation commit to `sdd/tasks/.id_ledger.json` (FEAT-387) | `base_branch` |
| `/sdd-start`      | Per-spec index status update + implementation code  | worktree (feature branch) |
| `/sdd-done`       | Per-spec index final state + task file moves; merges feature → `base_branch` | `base_branch` (NEVER `main`) |
```

### Does NOT Exist

- ~~A separate auto-commit policy file~~ — the policy lives inline in CLAUDE.md

---

## Implementation Notes

### Key Constraints

- Only modify line 239. Do NOT touch other rows.
- Keep the table formatting consistent with surrounding rows.
- The note about NEVER `main` is no longer needed in the "Where" column
  because the commit happens on the feature branch (the merge into
  base_branch is a separate operation in Step 9, which already has its
  own NEVER-main guardrail).

---

## Acceptance Criteria

- [ ] The `/sdd-done` row reflects "Verification stamp on per-spec index" (not "final state + task file moves")
- [ ] The "Where" column reflects "worktree (feature branch)" (not `base_branch`)
- [ ] No other rows in the table are changed
- [ ] Table formatting is consistent with surrounding rows

---

## Test Specification

No executable tests — this is a markdown documentation file. Verify by reading.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/sdd-done-merge-conflict-fix.spec.md`
2. **Check dependencies** — TASK-2133 must be in `tasks/completed/`
3. **Read** `CLAUDE.md` around line 239 to confirm the current content
4. **Replace** the `/sdd-done` row with the new text
5. **Verify** no other rows are changed
6. **Move this file** to `tasks/completed/`
7. **Update index** → `"done"`

---

## Completion Note

**Completed by**: sdd-worker
**Date**: 2026-08-05
**Notes**: Replaced the `/sdd-done` row (line 239) in CLAUDE.md's "SDD
Auto-Commit Rule" table with the exact replacement text specified in the
task. Confirmed via `git diff` that only this one line changed — no other
rows in the table or other parts of CLAUDE.md were touched.

**Deviations from spec**: none
