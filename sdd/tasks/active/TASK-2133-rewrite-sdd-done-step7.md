# TASK-2133: Rewrite sdd-done Step 7 — Stamp Verification on Feature Branch

**Feature**: FEAT-414 — Fix sdd-done Merge Conflicts
**Spec**: `sdd/specs/sdd-done-merge-conflict-fix.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

`/sdd-done` Step 7 currently runs `close_task.sh` on `dev`/`base_branch` to
close tasks (move `active/` → `completed/`, update per-spec index). This is
redundant because the feature branch already carries those changes from
`sdd-worker`/`sdd-start`. The redundancy causes add/add and modify/modify
merge conflicts when the feature branch is merged.

This task replaces Step 7 with a lightweight verification stamp committed on
the **feature branch** (in the worktree), eliminating the root cause.

Implements Spec §3 Module 1.

---

## Scope

- **Replace** the entire Step 7 section (lines 164–185) of `.claude/commands/sdd-done.md`
  with the new verification-stamp logic that operates in the worktree.
- The new Step 7 must:
  1. Stamp `verification` on each task entry in the worktree's per-spec index
  2. Stamp feature-level `completed_at` on the index header when all tasks are done
  3. Commit on the feature branch (inside the worktree), NOT on `dev`
- Update the Step 7 heading from `Close Tasks (on <BASE_BRANCH>)` to
  `Stamp Verification (on feature branch)`

**NOT in scope**:
- Changing `close_task.sh` (TASK-2134 simplifies Step 9, not this task)
- Changing Steps 1-6, 8, or 9.5-12
- Changing Step 9 (that's TASK-2134)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.claude/commands/sdd-done.md` | MODIFY | Replace Step 7 (lines 164–185) |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact references.

### Current Step 7 to REPLACE (lines 164–185 of `.claude/commands/sdd-done.md`)

```markdown
### 7. Close Tasks (on `<BASE_BRANCH>`)

For each task being closed, update the per-spec index in place. We are
already on `BASE_BRANCH` (verified in Step 1).

> **CRITICAL — use the script, do NOT hand-roll the move.** See the note in
> `/sdd-start`: closing a task is a *move*, and agents that copy instead leave
> `active/` orphans that survive the merge. `scripts/sdd/close_task.sh` does the
> `git mv` + index stamp + a hard post-condition (exit 3 if an `active/` copy
> survives).

```bash
# Close each task being closed (idempotent; stamps the index header when the
# whole feature is done). Repeat per task id:
scripts/sdd/close_task.sh TASK-<NNN> <feature-slug> verified

# Update task file headers (Status/Completed/Verification) in the completed/ copy.

# Commit ONLY the staged SDD state — never "git add ." / "git add -A".
git diff --cached --name-only      # sanity-check: only index + task files
git commit -m "sdd: close tasks for FEAT-<ID> — <title>"
```
```

### close_task.sh jq Pattern to Reference (lines 91–98 of `scripts/sdd/close_task.sh`)

The new Step 7 stamps only `verification` (not status/completed_at/file — those
are already set by sdd-worker). Reference this jq pattern for the verification stamp:

```bash
jq --arg id "$TASK_ID" --arg now "$NOW" --arg ver "$VERIFICATION" \
   --arg file "$COMPLETED_DIR/$basename_md" '
  (.tasks[] | select(.id == $id) | .status) = "done" |
  (.tasks[] | select(.id == $id) | .completed_at) = $now |
  (.tasks[] | select(.id == $id) | .verification) = $ver |
  (.tasks[] | select(.id == $id) | .file) = $file |
  (if all(.tasks[]; .status == "done") then .completed_at = $now else . end)
' "$INDEX" > "$tmp" && mv "$tmp" "$INDEX"
```

The new Step 7 only needs the `verification` stamp and the feature-level
`completed_at` — NOT the status/completed_at/file fields (already set).

### Per-Spec Index Schema (verified in spec §6)

```json
{
  "completed_at": null,           // ← feature-level, stamped when all tasks done
  "tasks": [
    {
      "id": "TASK-<NNN>",
      "status": "done",            // ← already set by sdd-worker
      "completed_at": "<ISO-8601>",// ← already set by sdd-worker
      "verification": null,        // ← THIS is what new Step 7 stamps
      "file": "sdd/tasks/completed/TASK-NNN-slug.md"  // ← already set
    }
  ]
}
```

### Does NOT Exist

- ~~`scripts/sdd/stamp_verification.sh`~~ — does not exist; the stamp is inline in the instructions
- ~~`close_task.sh --stamp-only`~~ — no such flag exists
- ~~`close_task.sh --worktree`~~ — no such flag exists

---

## Implementation Notes

### New Step 7 Content

Replace lines 164–185 with the following markdown section:

```markdown
### 7. Stamp Verification (on feature branch)

Stamp verification metadata on each closed task in the worktree's per-spec
index. The feature branch already carries the task files in `completed/` and
the index with `status: "done"` — this step only adds the `verification`
field and the feature-level `completed_at`.

> **Why not close_task.sh?** The feature branch already moved files
> `active/` → `completed/` and set status/completed_at/file during
> `sdd-worker`/`sdd-start`. Running `close_task.sh` again on `base_branch`
> would create duplicate state that conflicts on merge (FEAT-414).

```bash
WORKTREE_PATH=".claude/worktrees/feat-<FEAT-ID>-<slug>"
INDEX="sdd/tasks/index/${FEATURE_SLUG}.json"
NOW="$(date -u +%Y-%m-%dT%H:%M:%S+00:00)"

# Stamp verification on each task being closed.
# Use "verified" for ✅ VERIFIED tasks, "partial" for ⚠️ PARTIAL, "forced" for --force.
for TASK_ID in "${TASK_IDS[@]}"; do
  jq --arg id "$TASK_ID" --arg ver "$VERIFICATION" '
    (.tasks[] | select(.id == $id) | .verification) = $ver
  ' "$WORKTREE_PATH/$INDEX" > tmp && mv tmp "$WORKTREE_PATH/$INDEX"
done

# Stamp feature-level completed_at if all tasks are done.
jq --arg now "$NOW" '
  if all(.tasks[]; .status == "done") then .completed_at = $now else . end
' "$WORKTREE_PATH/$INDEX" > tmp && mv tmp "$WORKTREE_PATH/$INDEX"

# Commit on the feature branch (inside the worktree) — never on base_branch.
git -C "$WORKTREE_PATH" add "$INDEX"
git -C "$WORKTREE_PATH" diff --cached --name-only   # sanity-check: only the index
git -C "$WORKTREE_PATH" commit -m "sdd: close tasks for FEAT-<ID> — <slug>"
```
```

### Key Constraints

- The replacement must be an **exact substitution** of lines 164–185. Do NOT
  modify anything before line 164 or after line 185.
- The new section heading is `### 7. Stamp Verification (on feature branch)` —
  NOT the old `### 7. Close Tasks (on <BASE_BRANCH>)`.
- No reference to `close_task.sh` should appear in the new Step 7.
- The `git commit` must use `git -C "$WORKTREE_PATH"` (commits on the feature
  branch), NOT bare `git commit` (which would commit on `dev`).

---

## Acceptance Criteria

- [ ] Step 7 heading changed to `### 7. Stamp Verification (on feature branch)`
- [ ] No reference to `close_task.sh` in the new Step 7
- [ ] New Step 7 stamps `verification` on each task via `jq`
- [ ] New Step 7 stamps feature-level `completed_at` when all tasks are done
- [ ] New Step 7 commits on the feature branch via `git -C "$WORKTREE_PATH"`
- [ ] Lines before 164 and after 185 are unchanged
- [ ] The verification values (`verified`/`partial`/`forced`) are documented

---

## Test Specification

No executable tests — this is a markdown instruction file. Verify by reading
the modified file and confirming the acceptance criteria.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/sdd-done-merge-conflict-fix.spec.md` for full context
2. **Check dependencies** — none for this task
3. **Read** `.claude/commands/sdd-done.md` to see the current Step 7 (lines 164–185)
4. **Replace** lines 164–185 with the new Step 7 content from Implementation Notes
5. **Verify** no reference to `close_task.sh` remains in the new Step 7
6. **Verify** lines before 164 and after 185 are unchanged
7. **Move this file** to `tasks/completed/TASK-2133-rewrite-sdd-done-step7.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: unassigned
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
