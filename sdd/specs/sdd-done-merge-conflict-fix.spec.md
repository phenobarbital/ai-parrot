---
type: feature
base_branch: dev
---

# Feature Specification: Fix sdd-done Merge Conflicts

**Feature ID**: FEAT-414
**Date**: 2026-08-05
**Author**: Jesus Lara
**Status**: approved
**Target version**: next

---

## 1. Motivation & Business Requirements

### Problem Statement

`/sdd-done` Step 7 closes tasks on `dev` (moves `active/` → `completed/`,
updates the per-spec index via `close_task.sh`) **before** merging the feature
branch. The feature branch already carries those same state transitions from
`sdd-worker`/`sdd-start`. This creates guaranteed merge conflicts:

| File | Feature branch | dev (Step 7) | Merge result |
|---|---|---|---|
| `active/TASK-NNN-*.md` | Deleted | Deleted | ✅ delete/delete — OK |
| `completed/TASK-NNN-*.md` | Created | Created | 💥 add/add conflict |
| `index/<slug>.json` | Modified (status→done) | Modified (+verification) | 💥 modify/modify conflict |

This violates the FEAT-145 design principle: "the merge in `/sdd-done` brings
both [code and per-spec index] to `base_branch` atomically."

### Goals

- Eliminate SDD-file merge conflicts in `/sdd-done` for both PR and `--merge` flows.
- Preserve the `verification` metadata field on the per-spec index.
- Preserve the feature-level `completed_at` stamp on the per-spec index header.

### Non-Goals (explicitly out of scope)

- Handling partial implementations (all tasks are always closed before `/sdd-done`).
- Changing `close_task.sh` itself (still used by `/sdd-start` in the worktree).
- Changing `heal_orphans.sh` (still runs as post-merge safety net).
- Changing `sdd-worker.md` or `sdd-start.md`.

---

## 2. Architectural Design

### Overview

Replace `/sdd-done` Step 7 (pre-merge `close_task.sh` on `dev`) with a
lightweight verification stamp committed on the **feature branch** (in the
worktree). Since `dev` is no longer modified before the merge, both PR and
`--merge` flows produce clean merges.

The feature branch already carries:
- Task files moved `active/` → `completed/` ✅
- Per-task `status: "done"` ✅
- Per-task `completed_at` ✅
- Per-task `file` path updated ✅

The only missing metadata:
1. Per-task `verification` field — stamped by new Step 7 on the feature branch.
2. Feature-level `completed_at` on index header — stamped by new Step 7 when
   all tasks are done.

### Flow Change

```
BEFORE (causes conflict):
  Step 7: close_task.sh on dev  →  commit on dev
  Step 8: push feature branch
  Step 9: merge feature→dev     →  💥 CONFLICT

AFTER (conflict-free):
  Step 7: stamp verification on feature branch (worktree)  →  commit on feature branch
  Step 8: push feature branch
  Step 9: merge feature→dev     →  ✅ clean merge
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `.claude/commands/sdd-done.md` | modifies | Rewrite Step 7, simplify Step 9 `--merge` block |
| `CLAUDE.md` | modifies | Update `/sdd-done` row in Auto-Commit table (line 239) |
| `scripts/sdd/close_task.sh` | none | Still used by `/sdd-start`; no longer called by `/sdd-done` |
| `scripts/sdd/heal_orphans.sh` | none | Still runs as post-merge safety net for `--merge` |

---

## 3. Module Breakdown

### Module 1: Rewrite sdd-done Step 7

- **Path**: `.claude/commands/sdd-done.md`
- **Responsibility**: Replace the current Step 7 (lines 164–185) that runs
  `close_task.sh` on `dev` with a verification stamp on the feature branch.
- **Depends on**: none

**New Step 7 content** (replaces lines 164–185):

The new step stamps verification metadata in the worktree's per-spec index
and commits on the feature branch:

```bash
WORKTREE_PATH=".claude/worktrees/feat-<FEAT-ID>-<slug>"
INDEX="sdd/tasks/index/${FEATURE_SLUG}.json"
NOW="$(date -u +%Y-%m-%dT%H:%M:%S+00:00)"

# Stamp verification on each task being closed
for TASK_ID in "${TASK_IDS[@]}"; do
  VER="verified"  # or "partial" / "forced" per Step 5 classification
  jq --arg id "$TASK_ID" --arg ver "$VER" '
    (.tasks[] | select(.id == $id) | .verification) = $ver
  ' "$WORKTREE_PATH/$INDEX" > tmp && mv tmp "$WORKTREE_PATH/$INDEX"
done

# Stamp feature-level completed_at if all tasks are done
jq --arg now "$NOW" '
  if all(.tasks[]; .status == "done") then .completed_at = $now else . end
' "$WORKTREE_PATH/$INDEX" > tmp && mv tmp "$WORKTREE_PATH/$INDEX"

# Commit on the feature branch
git -C "$WORKTREE_PATH" add "$INDEX"
git -C "$WORKTREE_PATH" commit -m "sdd: close tasks for FEAT-<ID> — <slug>"
```

Key behavioral notes for the implementing agent:
- The `CRITICAL` note about `close_task.sh` (lines 169–173) must be **removed**
  — this step no longer calls `close_task.sh`.
- The `git commit` at line 184 that committed on `dev` is removed — the commit
  now happens in the worktree on the feature branch.
- Verification values map from Step 5 classifications:
  - ✅ VERIFIED → `"verified"`
  - ⚠️ PARTIAL → `"partial"`
  - `--force` → `"forced"`

### Module 2: Simplify sdd-done Step 9 `--merge` block

- **Path**: `.claude/commands/sdd-done.md`
- **Responsibility**: Remove the merge-conflict warning block for SDD files
  from the `--merge` flow (lines 273–284). SDD conflicts are eliminated by
  design. Code-level conflicts are still possible and handled normally.
  The `heal_orphans.sh` safety net (lines 286–297) is **kept unchanged**.
- **Depends on**: Module 1

### Module 3: Update CLAUDE.md Auto-Commit table

- **Path**: `CLAUDE.md`
- **Responsibility**: Update the `/sdd-done` row (line 239) in the
  "SDD Auto-Commit Rule" table to reflect the new commit location.
- **Depends on**: Module 1

**Before** (line 239):
```
| `/sdd-done`       | Per-spec index final state + task file moves; merges feature → `base_branch` | `base_branch` (NEVER `main`) |
```

**After**:
```
| `/sdd-done`       | Verification stamp on per-spec index (committed on feature branch); merges feature → `base_branch` | worktree (feature branch), merged to `base_branch` by Step 9 |
```

---

## 4. Test Specification

This feature modifies a Claude Code skill file (markdown instructions) and a
documentation file — there is no executable Python code to unit-test.

### Manual Verification

| Test | Description |
|---|---|
| Run `/sdd-done FEAT-XXX` on a completed feature (PR flow) | Verify: no commit on `dev` before PR is opened; PR has `verification` field in index |
| Run `/sdd-done FEAT-XXX --merge` on a completed feature | Verify: merge is clean (no SDD conflicts); index on `dev` post-merge has `verification` + `completed_at` |
| Read the spec's per-spec index after merge | Verify: every task has `verification: "verified"` and the header has `completed_at` set |

### Regression Check

| Test | Description |
|---|---|
| `heal_orphans.sh` still runs post-merge | Verify: safety net is preserved in `--merge` flow |
| `close_task.sh` not called by `/sdd-done` | Verify: grep the new Step 7 — no reference to `close_task.sh` |
| Steps 1-6, 8, 9.5-12 unchanged | Verify: diff only touches Step 7 and the `--merge` conflict block in Step 9 |

---

## 5. Acceptance Criteria

- [ ] Step 7 of `sdd-done.md` no longer calls `close_task.sh` or commits on `dev`/`base_branch`
- [ ] Step 7 stamps `verification` on each task in the worktree's per-spec index
- [ ] Step 7 stamps feature-level `completed_at` on the index header when all tasks are done
- [ ] Step 7 commits the stamp on the feature branch (inside the worktree)
- [ ] Step 9 `--merge` block no longer contains the SDD-specific merge-conflict warning
- [ ] `heal_orphans.sh` safety net is still present in Step 9 `--merge` block
- [ ] CLAUDE.md auto-commit table row for `/sdd-done` reflects the new behavior
- [ ] Steps 1-6, 8, 9.5-12 are unchanged

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**

### Files to Modify

```
.claude/commands/sdd-done.md          # Step 7 (lines 164-185), Step 9 --merge conflict block (lines 273-284)
CLAUDE.md                              # Auto-commit table row (line 239)
```

### Files NOT to Modify

```
scripts/sdd/close_task.sh             # Still used by /sdd-start — do NOT change
scripts/sdd/heal_orphans.sh           # Post-merge safety net — do NOT change
.claude/commands/sdd-start.md         # Closes tasks in worktree — do NOT change
.claude/agents/sdd-worker.md          # Closes tasks in worktree — do NOT change
```

### Verified References

```bash
# close_task.sh — verification stamp logic (lines 88-100)
# This is what we're REPLACING (on dev) with a lighter version (on feature branch):
jq --arg id "$TASK_ID" --arg now "$NOW" --arg ver "$VERIFICATION" \
   --arg file "$COMPLETED_DIR/$basename_md" '
  (.tasks[] | select(.id == $id) | .status) = "done" |
  (.tasks[] | select(.id == $id) | .completed_at) = $now |
  (.tasks[] | select(.id == $id) | .verification) = $ver |
  (.tasks[] | select(.id == $id) | .file) = $file |
  (if all(.tasks[]; .status == "done") then .completed_at = $now else . end)
' "$INDEX" > "$tmp" && mv "$tmp" "$INDEX"

# heal_orphans.sh — invoked at sdd-done.md line 292
scripts/sdd/heal_orphans.sh <feature-slug>

# CLAUDE.md auto-commit table — line 239
| `/sdd-done`       | Per-spec index final state + task file moves; merges feature → `base_branch` | `base_branch` (NEVER `main`) |
```

### Per-Spec Index Schema (sdd/tasks/index/<slug>.json)

```json
{
  "feature": "<slug>",
  "feature_id": "FEAT-<NNN>",
  "spec": "sdd/specs/<slug>.spec.md",
  "type": "feature",
  "base_branch": "dev",
  "created_at": "<ISO-8601>",
  "completed_at": null,           // ← stamped by new Step 7 when all tasks done
  "tasks": [
    {
      "id": "TASK-<NNN>",
      "feature_id": "FEAT-<NNN>",
      "feature": "<slug>",
      "status": "done",            // ← already set by sdd-worker
      "completed_at": "<ISO-8601>",// ← already set by sdd-worker
      "verification": null,        // ← stamped by new Step 7
      "file": "sdd/tasks/completed/TASK-NNN-slug.md",
      "depends_on": []
    }
  ]
}
```

### Does NOT Exist (Anti-Hallucination)

- ~~`scripts/sdd/stamp_verification.sh`~~ — does not exist; the stamp logic
  is inline in the sdd-done.md instructions, not a separate script
- ~~`close_task.sh --stamp-only`~~ — no such flag exists

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- The new Step 7 uses `jq` for JSON manipulation — same pattern as
  `close_task.sh` (lines 91-98).
- Git operations in the worktree use `git -C <worktree-path>` — same
  pattern as existing Steps 4 and 8.
- Commit messages follow the `sdd: <action> for <feature-name>` convention.

### Known Risks / Gotchas

- **Risk**: An agent implementing this could accidentally leave stale
  references to `close_task.sh` in Step 7.
  **Mitigation**: Acceptance criterion explicitly checks for no `close_task.sh`
  reference in the new Step 7.

- **Risk**: The `heal_orphans.sh` call in Step 9 could be accidentally removed
  while simplifying the `--merge` block.
  **Mitigation**: Acceptance criterion explicitly checks for its presence.

### External Dependencies

None — this change only modifies markdown instruction files.

---

## 8. Open Questions

None — all questions resolved during design.

- [x] Handle partial implementations? — *Resolved in design*: No. All tasks
  are always closed before `/sdd-done` runs.
- [x] Where to stamp verification? — *Resolved in design*: On the feature
  branch (in the worktree), not on `dev`.

---

## Worktree Strategy

**Isolation**: `per-spec` — all 3 modules are sequential edits to 2 files.
A single worktree is sufficient. No parallelism needed.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-05 | Jesus Lara / Claude | Initial draft from approved design |
