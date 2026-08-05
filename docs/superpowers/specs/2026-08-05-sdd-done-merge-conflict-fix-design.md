# Fix sdd-done Merge Conflicts — Design Spec

**Date**: 2026-08-05
**Status**: Approved
**Scope**: `.claude/commands/sdd-done.md`, `CLAUDE.md` (table update)

---

## Problem

`/sdd-done` Step 7 closes tasks on `dev` (moves `active/` → `completed/`,
updates the per-spec index via `close_task.sh`) **before** merging the feature
branch. The feature branch already carries those same state transitions from
`sdd-worker`/`sdd-start`. This causes:

| File | Feature branch | dev (Step 7) | Merge result |
|---|---|---|---|
| `active/TASK-NNN-*.md` | Deleted | Deleted | ✅ delete/delete — OK |
| `completed/TASK-NNN-*.md` | Created | Created | 💥 add/add conflict |
| `index/<slug>.json` | Modified (status→done) | Modified (status→done + verification) | 💥 modify/modify conflict |

The root cause is that Step 7 violates the FEAT-145 design principle: "the
merge in `/sdd-done` brings both [code and per-spec index] to `base_branch`
atomically."

## Design: Merge-First, Stamp-on-Feature-Branch

### Core Principle

The feature branch is the single source of truth for task state. `/sdd-done`
never modifies SDD task files or the index on `dev` before the merge.

The only metadata the feature branch doesn't already carry is:
1. Per-task `verification` field (only set by `close_task.sh`)
2. Feature-level `completed_at` on the index header (set when all tasks done)

Both are stamped on the **feature branch** (in the worktree) before push,
so both `--merge` and PR flows receive the complete state atomically.

### Changes

#### 1. Rewrite Step 7 — Stamp Verification in Worktree

Replace the current Step 7 (which runs `close_task.sh` on `dev`) with a
lightweight verification stamp on the feature branch:

```bash
WORKTREE_PATH=".claude/worktrees/feat-<FEAT-ID>-<slug>"
INDEX="sdd/tasks/index/${FEATURE_SLUG}.json"
NOW="$(date -u +%Y-%m-%dT%H:%M:%S+00:00)"

# Stamp verification on each verified task
for TASK_ID in "${VERIFIED_TASKS[@]}"; do
  jq --arg id "$TASK_ID" --arg now "$NOW" --arg ver "verified" '
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

What this does:
- Adds only the 2 missing fields to the index already in the worktree
- No file moves (already in `completed/`)
- No modifications to `dev`

Verification values by task classification (from Step 5):
- ✅ VERIFIED → `verification: "verified"`
- ⚠️ PARTIAL → `verification: "partial"`
- `--force` → `verification: "forced"`

#### 2. Steps 8-9 — Push and Merge (now conflict-free)

**Step 8 (Push)**: Unchanged — push the feature branch from the worktree.

**Step 9 — PR flow (default)**: Unchanged. The PR now carries complete state
(files in `completed/`, index with `verification` + `completed_at`). When
GitHub merges the PR, everything arrives on `dev` atomically. No prior commit
on `dev` to conflict with.

**Step 9 — `--merge` flow**: Simplified. The merge is clean because `dev`
has no competing SDD changes:

```bash
git merge --no-edit feat-<FEAT-ID>-<slug>

# Safety net — heal_orphans.sh (kept, cheap and defensive)
scripts/sdd/heal_orphans.sh <feature-slug>
if ! git diff --cached --quiet -- sdd/tasks/active sdd/tasks/completed; then
  git commit -m "sdd: reap stalled active task orphans for FEAT-<ID> — <slug>"
fi

git push origin "$BASE_BRANCH"
```

The "merge has conflicts" warning block for SDD files is removed from Step 9.
Code-level merge conflicts remain possible and are handled normally.

**Steps 9.5–12**: Unchanged (sync-down, Jira, cleanup).

#### 3. Update CLAUDE.md Auto-Commit Table

The `/sdd-done` row in the "SDD Auto-Commit Rule" table changes:

| Before | After |
|---|---|
| What it commits: "Per-spec index final state + task file moves" | What it commits: "Verification stamp on per-spec index" |
| Where: `base_branch` | Where: worktree (feature branch); merged to `base_branch` by Step 9 |

### Files Changed

| File | Change |
|---|---|
| `.claude/commands/sdd-done.md` | Rewrite Step 7, simplify Step 9 `--merge` block |
| `CLAUDE.md` | Update `/sdd-done` row in Auto-Commit table |

### Files NOT Changed

| File | Reason |
|---|---|
| `scripts/sdd/close_task.sh` | Still used by `/sdd-start` in worktree; just no longer invoked by `/sdd-done` |
| `scripts/sdd/heal_orphans.sh` | Still runs as post-merge safety net |
| `.claude/commands/sdd-start.md` | Unchanged — closes tasks in worktree as before |
| `.claude/agents/sdd-worker.md` | Unchanged — closes tasks in worktree as before |

### Risk Assessment

**Risk**: Low. The change is a *subtraction* (stop doing something redundant)
plus a lightweight metadata stamp.

**Assumption**: All tasks are always closed on the feature branch before
`/sdd-done` runs. Confirmed by the user — no partial implementation scenario.

### Verification

Run `/sdd-done FEAT-XXX` on a completed feature and verify:
1. No commit on `dev` before the merge
2. The merge is clean (no SDD conflicts)
3. The index on `dev` post-merge has `verification` and `completed_at` fields
