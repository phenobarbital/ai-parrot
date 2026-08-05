# TASK-2134: Simplify sdd-done Step 9 --merge Conflict Block

**Feature**: FEAT-414 — Fix sdd-done Merge Conflicts
**Spec**: `sdd/specs/sdd-done-merge-conflict-fix.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2133
**Assigned-to**: sdd-worker

---

## Context

After TASK-2133 removes the pre-merge close on `dev`, SDD-file merge conflicts
in the `--merge` flow are eliminated by design. The Step 9 `--merge` block
currently contains a warning about merge conflicts (lines 272–284) that is no
longer relevant for SDD files. Code-level conflicts can still occur and should
still be handled, but the SDD-specific framing should be removed/simplified.

Implements Spec §3 Module 2.

---

## Scope

- **Remove or simplify** the merge-conflict warning block in Step 9's `--merge`
  section (lines 272–284 of `.claude/commands/sdd-done.md`).
- Keep a **generic** merge-conflict handler (code conflicts are still possible).
- The `heal_orphans.sh` safety net (lines 286–297) MUST be **kept unchanged**.

**NOT in scope**:
- Changing Step 7 (already done in TASK-2133)
- Changing the PR flow section of Step 9
- Changing the hotfix refusal block
- Changing heal_orphans.sh

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.claude/commands/sdd-done.md` | MODIFY | Simplify Step 9 --merge conflict block (lines 272–284) |

---

## Codebase Contract (Anti-Hallucination)

### Current --merge Conflict Block to SIMPLIFY (lines 263–297 of sdd-done.md)

```markdown
**Feature flow with `--merge` — direct merge (old behavior):**

When `--merge` is explicitly passed, perform a direct merge instead of a PR:

```bash
# We're already on $BASE_BRANCH (verified in Step 1)
git merge --no-edit feat-<FEAT-ID>-<slug>
```

If the merge has conflicts:
```
⚠️  Merge conflict when merging feat-<FEAT-ID>-<slug> into <BASE_BRANCH>.
   Conflicting files:
     - <file1>
     - <file2>

   Options:
     1. Resolve conflicts now (recommended)
     2. Abort merge: git merge --abort
```
If conflicts are resolved, commit the merge. If the user aborts, STOP and
do NOT proceed to cleanup.

**Self-heal — reap stalled `active/` orphans (runs after every `--merge`):**

> Only applies when `--merge` is used. When using PR flow, the orphan sweep
> happens on the PR merge side.

```bash
scripts/sdd/heal_orphans.sh <feature-slug>
# If it reaped anything, commit the cleanup before pushing:
if ! git diff --cached --quiet -- sdd/tasks/active sdd/tasks/completed; then
  git commit -m "sdd: reap stalled active task orphans for FEAT-<ID> — <title>"
fi
```
```

### Lines to PRESERVE UNCHANGED (lines 286–297)

The `heal_orphans.sh` block (Self-heal section) MUST remain exactly as-is.

### Does NOT Exist

- ~~A separate "SDD conflict resolution" handler~~ — conflicts are now generic
- ~~`heal_orphans.sh --skip-sdd`~~ — no such flag

---

## Implementation Notes

### What to Change

Replace the SDD-specific conflict warning (lines 272–284) with a shorter,
generic conflict handler. The merge command itself (lines 267–270) stays.
The heal_orphans block (lines 286–297) stays.

**Suggested replacement for lines 272–284:**

```markdown
If the merge has conflicts (e.g. code-level changes to the same files):
```
⚠️  Merge conflict when merging feat-<FEAT-ID>-<slug> into <BASE_BRANCH>.
   Resolve conflicts, then continue with: git merge --continue
   Or abort: git merge --abort
```
If the user aborts, STOP and do NOT proceed to cleanup.
```

This is shorter, generic (not SDD-specific), and still handles the case.

### Key Constraints

- Do NOT remove the `heal_orphans.sh` block.
- Do NOT change the PR flow section or hotfix refusal block.
- The merge command line (`git merge --no-edit`) stays unchanged.

---

## Acceptance Criteria

- [ ] The SDD-specific merge-conflict framing (listing file1/file2 and numbered options) is removed
- [ ] A generic merge-conflict handler remains for code-level conflicts
- [ ] The `heal_orphans.sh` safety net block (lines 286–297) is preserved unchanged
- [ ] The merge command (`git merge --no-edit`) is preserved
- [ ] The PR flow section is unchanged
- [ ] The hotfix refusal block is unchanged

---

## Test Specification

No executable tests — this is a markdown instruction file. Verify by reading.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/sdd-done-merge-conflict-fix.spec.md`
2. **Check dependencies** — TASK-2133 must be in `tasks/completed/`
3. **Read** `.claude/commands/sdd-done.md` — the file will have TASK-2133's changes
4. **Simplify** the merge-conflict block per Implementation Notes
5. **Verify** `heal_orphans.sh` block is unchanged
6. **Move this file** to `tasks/completed/`
7. **Update index** → `"done"`

---

## Completion Note

**Completed by**: sdd-worker
**Date**: 2026-08-05
**Notes**: Simplified the `--merge` conflict block in Step 9 of
`.claude/commands/sdd-done.md` — replaced the SDD-specific framing (listing
`file1`/`file2` and numbered resolve/abort options) with the shorter generic
handler from the Implementation Notes. The merge command
(`git merge --no-edit`), the `heal_orphans.sh` self-heal block, the PR flow
section, and the hotfix refusal block were all left untouched — confirmed via
`git diff` scoped to only this block.

**Deviations from spec**: none
