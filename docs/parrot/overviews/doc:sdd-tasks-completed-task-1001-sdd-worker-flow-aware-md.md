---
type: Wiki Overview
title: 'TASK-1001: Update `sdd-worker` agent for per-spec index + base_branch'
id: doc:sdd-tasks-completed-task-1001-sdd-worker-flow-aware-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 8** of FEAT-145. The autonomous `sdd-worker`
---

# TASK-1001: Update `sdd-worker` agent for per-spec index + base_branch

**Feature**: FEAT-145 — SDD Flow Types and Per-Spec Index
**Spec**: `sdd/specs/sdd-flow-types-and-per-spec-index.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-994, TASK-995, TASK-998
**Assigned-to**: unassigned

---

## Context

Implements **Module 8** of FEAT-145. The autonomous `sdd-worker`
duplicates the workflow logic of `/sdd-start`. Now that TASK-998 has
moved `/sdd-start` to per-spec indexes and dropped the cd-to-dev
dance, the agent must follow the same pattern. Cardinal Rule #6 ("CODE
IN WORKTREE, STATE ON `dev`") needs replacing — code AND per-spec
index now live together in the worktree.

---

## Scope

Edit `.claude/agents/sdd-worker.md`. Specifically:

1. **Cardinal Rule #6** (line 58–61): replace with:
   ```
   6. CODE AND STATE LIVE TOGETHER IN THE WORKTREE.
      Implementation code and the per-spec index are committed in the same
      worktree. The merge in /sdd-done brings them to base_branch atomically.
      NEVER cd back to the main repo to update state.
   ```

2. **§0 Save the Main Repo Path** (lines 75–78): drop the `REPO_ROOT` capture (no longer needed). Replace with a base-branch sync block:
   ```bash
   META=$(python -c "from pathlib import Path; from scripts.sdd.sdd_meta import parse; m = parse(Path('<spec-path>')); print(m.type, m.base_branch)")
   TYPE=$(echo "$META" | awk '{print $1}')
   BASE_BRANCH=$(echo "$META" | awk '{print $2}')

   git checkout "$BASE_BRANCH"
   git pull --ff-only origin "$BASE_BRANCH"
   ```

3. **§1 Resolve the Feature** (lines 81–92): read `sdd/tasks/index/<feature>.json` (resolved by globbing for the file whose `feature_id` or `feature` matches the user's input). Drop the monolith reference.

4. **§2 Mark All Tasks as In-Progress** (lines 94–102): update the per-spec index in-place. Drop the explicit "git checkout dev" line.

5. **§3 Create the Worktree** (lines 104–114): unchanged structurally, but the worktree branch from is now `BASE_BRANCH` (HEAD will already be on it after §0).

6. **§4 Verify SDD Files Are Visible** (lines 116–121): replace the test for `sdd/tasks/.index.json` with `sdd/tasks/index/<feature>.json`.

7. **Step (g) Update SDD State** (lines 177–199): drop the entire `cd $REPO_ROOT && git checkout dev && ... && cd $WORKTREE_DIR` block. Replace with an in-place update of the per-spec index in the worktree, committed alongside (or as a separate commit immediately after) the code commit.

8. **Examples / hints throughout**: search for any leftover references to `sdd/tasks/.index.json` or `git checkout dev` and update.

**NOT in scope**:
- Changing how the agent runs tests, lints, or verifies acceptance criteria.
- Changing the STOP conditions (lines 233–244) — those remain.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.claude/agents/sdd-worker.md` | MODIFY | Cardinal rule 6, §0, §1, §2, §4, step (g) |

---

## Codebase Contract (Anti-Hallucination)

### Existing File to Modify (verified line counts on 2026-05-05)

`.claude/agents/sdd-worker.md` — 244 lines:
- Frontmatter: lines 1–23
- Cardinal Rules (NEVER VIOLATE): lines 35–62
- §0 Save Main Repo Path: lines 75–78
- §1 Resolve the Feature: lines 81–92
- §2 Mark Tasks In-Progress: lines 94–102
- §3 Create Worktree: lines 104–114
- §4 Verify SDD Files Visible: lines 116–121
- §5 Read the Spec: lines 123–124
- Execution Loop §a–§h: lines 128–202
- Step (g) Update SDD State: lines 177–199 (the dance to drop)
- Completion: lines 204–231
- STOP Conditions: lines 233–244

### Pattern Reference (current line 60, to be replaced)

```
6. CODE IN WORKTREE, STATE ON `dev`.
   Implementation code is committed in the feature worktree.
   SDD state changes (index updates, task file moves) are committed on `dev`.
   NEVER commit SDD state changes in the worktree.
```

### Does NOT Exist

- ~~`sdd/tasks/.index.json` reads in the post-rewrite agent~~ — must be eliminated.
- ~~`cd $REPO_ROOT` blocks~~ — must be eliminated from §2 and step (g).

---

## Implementation Notes

### New Cardinal Rule 6 (replacement, exact text)

```markdown
6. **CODE AND STATE LIVE TOGETHER IN THE WORKTREE.**
   Implementation code and the per-spec index (`sdd/tasks/index/<feature>.json`)
   are committed in the SAME worktree. The merge in `/sdd-done` brings them
   to `base_branch` atomically. NEVER cd back to the main repo to update state.
   This is the new model — eliminating the cd-dance is a feature, not a bug.
```

### Step (g) Replacement (must be drop-in compatible with §a–§f)

```markdown
### g) Update SDD State (in worktree, alongside code)

After committing the code in step (f), update the per-spec index in
the SAME worktree:

```bash
INDEX="sdd/tasks/index/<feature>.json"

# Move task file from active to completed (in-place)
mkdir -p sdd/tasks/completed/
mv sdd/tasks/active/TASK-<NNN>-<slug>.md sdd/tasks/completed/

# Update index: status → done, completed_at → now
jq --arg id "TASK-<NNN>" '
  (.tasks[] | select(.id == $id) | .status) = "done" |
  (.tasks[] | select(.id == $id) | .completed_at) = (now | strftime("%Y-%m-%dT%H:%M:%S+00:00"))
' "$INDEX" > "$INDEX.tmp" && mv "$INDEX.tmp" "$INDEX"

# Stage and commit (in the worktree, on the feature branch)
git add "$INDEX" sdd/tasks/active/TASK-<NNN>-<slug>.md sdd/tasks/completed/TASK-<NNN>-<slug>.md
git commit -m "sdd: complete TASK-<NNN> — <title>"
```

The merge in `/sdd-done` will bring this commit to `base_branch`.
```

### Key Constraints

- All edits surgical via `Edit`, NOT `Write` over the whole file.
- Preserve every Cardinal Rule except #6 (and the model frontmatter, which stays).
- Preserve all STOP conditions verbatim.

---

## Acceptance Criteria

- [ ] Cardinal Rule #6 reflects the new model.
- [ ] `grep -c "sdd/tasks/.index.json" .claude/agents/sdd-worker.md` returns 0.
- [ ] `grep -c "sdd/tasks/index/" .claude/agents/sdd-worker.md` returns ≥ 2.
- [ ] `grep -nE "cd \\\$REPO_ROOT\|cd .{REPO_ROOT}" .claude/agents/sdd-worker.md` returns 0 hits.
- [ ] `grep -c "BASE_BRANCH\|base_branch" .claude/agents/sdd-worker.md` ≥ 1.
- [ ] `grep -c "git checkout dev" .claude/agents/sdd-worker.md` returns 0.
- [ ] All seven Cardinal Rules remain (count: 6 numbered + 1 boldface intro).
- [ ] STOP Conditions section (line 233 area) unchanged.

---

## Test Specification

```bash
# Run all greps; every count below must match.
grep -c "sdd/tasks/.index.json" .claude/agents/sdd-worker.md          # 0
grep -c "sdd/tasks/index/" .claude/agents/sdd-worker.md               # ≥ 2
grep -c "cd .*REPO_ROOT" .claude/agents/sdd-worker.md                 # 0
grep -c "git checkout dev" .claude/agents/sdd-worker.md               # 0
grep -cE "^[0-9]+\. \*\*[A-Z]" .claude/agents/sdd-worker.md           # 6 cardinal rules
```

A mental dry-run: walk the agent through implementing TASK-1002 (next
task in this very feature) — every state change must be in the
worktree, no `cd` calls.

---

## Agent Instructions

1. Read `.claude/agents/sdd-worker.md` end-to-end.
2. Apply edits in this order: Cardinal Rule 6 → §0 → §1 → §2 → §4 → step (g) → final pass for stragglers.
3. Run all grep verifications.
4. Commit: `feat(sdd): TASK-1001 — sdd-worker uses per-spec index, no cd dance`.

---

## Completion Note

**Completed by**: Claude (Opus 4.7) — interactive session via `/sdd-start TASK-1001`
**Date**: 2026-05-05
**Notes**: The sdd-worker agent now mirrors `/sdd-start` exactly (TASK-998's contract). No more cd-dance; per-spec index lives with the code in the worktree.

**What landed:**
- **Key principle (line 30-32)**: rewritten — "code AND per-spec index live together in the worktree".
- **Cardinal Rule #6**: replaced with the FEAT-145 model. Explicitly forbids `cd` to the main repo for state updates.
- **§0 Save Main Repo Path** → **§0 Sync the Base Branch**: drops `REPO_ROOT=$(pwd)`, replaces with `python -c "from scripts.sdd.sdd_meta import parse; ..."` to read frontmatter, then `git checkout $BASE_BRANCH && git pull --ff-only`.
- **§1 Resolve the Feature**: globs `sdd/tasks/index/*.json` (excluding `_orphans.json`) instead of reading the monolith. Includes a working `jq` snippet that finds the per-spec index file matching the user's input.
- **§2 Mark All Tasks as In-Progress**: `jq` mutation of the per-spec index in place; commit on the current branch (no `cd`).
- **§3 Create the Worktree**: unchanged structurally — branches from HEAD, which is now BASE_BRANCH after §0. Documented that the branch name `feat-<FEAT-ID>-…` is used regardless of flow type.
- **§4 Verify SDD Files Are Visible**: replaced the test for `sdd/tasks/.index.json` with `sdd/tasks/index/<feature>.json`.
- **Step (g) Update SDD State**: completely rewritten — drops the entire `cd "${REPO_ROOT}" && git checkout dev && ... && cd "${WORKTREE_DIR}"` block. Uses `jq` to mutate the per-spec index in the worktree, then commits on the feature branch.

**Acceptance grep results:**
| Check                                | Value | Required |
|--------------------------------------|-------|----------|
| `sdd/tasks/.index.json` refs         | 0     | = 0 ✅   |
| `sdd/tasks/index/` refs              | 6     | ≥ 2 ✅   |
| `cd .*REPO_ROOT` blocks              | 0     | = 0 ✅   |
| `git checkout dev`                   | 0     | = 0 ✅   |
| `BASE_BRANCH` references             | 12    | ≥ 1 ✅   |
| Numbered cardinal rules (1-6)        | 6     | = 6 ✅   |
| STOP Conditions section unchanged    | yes   | yes ✅   |

**Deviations from contract**: none.

**Heads-up**: this rewrite changes the cardinal rules of the agent's prompt. **An sdd-worker process that is already running keeps its OLD prompt** until restarted. Future sessions of the agent will use the new flow. For this very feature (FEAT-145), all subsequent work is happening through the user's interactive `/sdd-start` invocations, NOT through sdd-worker — so this rewrite has no impact on the in-flight work.
