# TASK-3159: `CLAUDE.md` states the new worktree ownership

**Feature**: FEAT-552 — Worktree Creation Ownership
**Spec**: `sdd/specs/worktree-creation-ownership.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3156
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7. `CLAUDE.md` is loaded into every session in this repo, so a
stale worktree policy there outranks the commands themselves in practice. Four
passages describe the world before FEAT-552 — one of them (the FEAT-466
carve-out) even uses the wrong naming template, which is part of how the drift
spread.

---

## Scope

- Update four anchored passages in `CLAUDE.md`: the base-branch bullet, the
  FEAT-466 carve-out example, the `/sdd-task` row of the SDD Auto-Commit Rule
  table, and step 3 of Typical Workflow.

**NOT in scope**: `.claude/**` files (TASK-3155 to TASK-3158); `sdd/WORKFLOW.md`
and `docs/sdd/WORKFLOW.md` — they describe the task lifecycle, not worktree
creation, and were verified 2026-09-11 to contain no `git worktree add`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `CLAUDE.md` | MODIFY | Four anchored passages |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use
Verbatim current text, each occurring exactly once (verified 2026-09-11 with
`grep -cF`):

```
CLAUDE.md:243
- **Worktrees branch from `base_branch`** (which `/sdd-task` and `sdd-worker` ensure HEAD is on before creating the worktree). Hotfix worktrees branch from `main`; feature worktrees branch from `dev` or `staging` (during a release freeze).

CLAUDE.md:260 (inside the FEAT-466 carve-out blockquote)
> already *is* the intended base — true for `/sdd-task` and `sdd-worker`,
> which always `git checkout "$BASE_BRANCH"` immediately beforehand.

CLAUDE.md:270
> git worktree add -b feat-<id>-<slug> .claude/worktrees/feat-<id>-<slug> origin/dev

CLAUDE.md:321 (SDD Auto-Commit Rule table)
| `/sdd-task`       | `sdd/tasks/index/<feature>.json` + `sdd/tasks/active/TASK-*` + a `reserve_ids.py` TASK-ID reservation commit to `sdd/tasks/.id_ledger.json` (FEAT-387) | `base_branch` |

CLAUDE.md:376-378 (Typical Workflow step 3)
# 3. Create worktree from dev
git worktree add -b feat-014-videoreel-visual-changes \
  .claude/worktrees/feat-014 HEAD
```

### Does NOT Exist
- ~~a `## Worktree Policy` section~~ — the heading is `## Worktree Creation`
  (line 245); `/sdd-spec`'s Reference section calls it "Worktree Policy", which
  is already slightly wrong. Do not rename the heading in this task.
- ~~`git worktree add` in `sdd/WORKFLOW.md` or `docs/sdd/WORKFLOW.md`~~ —
  verified absent; nothing to update there
- ~~a FEAT-552 mention anywhere in `CLAUDE.md` today~~ — this task introduces it

---

## Implementation Notes

### Key Constraints
- Keep the FEAT-466 carve-out's substance. Its point — a hotfix must never
  branch from `HEAD` — is now *enforced* by `plan_worktree`, so the carve-out
  becomes shorter, not deleted. The `feat-<id>-<slug>` example must become
  `feat-FEAT-<NNN>-<slug>` regardless.
- Do not restate the naming template as authoritative anywhere. Point at
  `scripts.sdd.sdd_meta.plan_worktree`, matching the agents (TASK-3158).
- `CLAUDE.md` is read by every session — keep the edits tight.

---

## Implementation Blueprint

### Steps (in order)
1. Rewrite line 243 — *why*: it names the two commands that no longer (or never
   did) own creation.
2. Trim the FEAT-466 carve-out and fix its example — *why*: it teaches the wrong
   template while explaining a rule the code now enforces.
3. Update the `/sdd-task` table row — *why*: the table is what a reader consults
   to know what each command writes.
4. Replace Typical Workflow step 3 — *why*: it is a copy-pasteable command that
   would now create an orphan worktree.

### `CLAUDE.md` (MODIFY — 1 of 4)
```
# occurrences: 1 (verified: grep -cF '**Worktrees branch from `base_branch`**' CLAUDE.md)
# REPLACE — line 243

- **Worktrees branch from `origin/<base_branch>`**, and are created by whoever
  implements: `/sdd-start` and `sdd-worker` for the normal lanes, and the
  dev-loop orchestrators (`sdd-planner`, `sdd-research`, `sdd-autopilot`) which
  plan and dispatch in one run. `/sdd-task` creates none (FEAT-552). Naming and
  base ref come from `scripts.sdd.sdd_meta.plan_worktree` via
  `python -m scripts.sdd.ensure_worktree` — never hand-built.
```

### `CLAUDE.md` (MODIFY — 2 of 4)
```
# occurrences: 1 (verified: grep -cF 'git worktree add -b feat-<id>-<slug>' CLAUDE.md)
# REPLACE — line 270 (inside the carve-out blockquote), and AMEND lines 259-261 so the
#           carve-out no longer claims /sdd-task creates worktrees:

> # Feature — from the base branch (dev, or staging during a freeze)
> python -m scripts.sdd.ensure_worktree --slug <slug> --feature-id FEAT-<NNN>
> # Hotfix — ALWAYS from origin/main, never from HEAD/dev
> python -m scripts.sdd.ensure_worktree --slug <slug> --jira-key <JIRA-KEY>

# FILL IN: rewrite the carve-out's opening sentences so they read as history plus
#   the current guarantee — "HEAD-as-shorthand was the old rule; `plan_worktree`
#   now always returns `origin/<base_branch>`, so a hotfix cannot inherit
#   unreleased dev commits" — bounded by: keep the FEAT-466 / PR #1250
#   attribution, and do not delete the explanation of why it mattered
```

### `CLAUDE.md` (MODIFY — 3 of 4)
```
# occurrences: 1 (verified: grep -cF '| `/sdd-task`       |' CLAUDE.md)
# AFTER — append to the `/sdd-task` row's first cell, before the closing ` | `base_branch` |`:
#   " — and NO worktree (FEAT-552: it is created by the implementing lane)"
```

### `CLAUDE.md` (MODIFY — 4 of 4)
```
# occurrences: 1 (verified: grep -cF '# 3. Create worktree from dev' CLAUDE.md)
# REPLACE — Typical Workflow step 3, lines 376-378

# 3. Start a task — creates the worktree on this machine, idempotently
/sdd-start TASK-069
```
**Why the four together**: a reader who trusts `CLAUDE.md` must not be able to
reconstruct the old flow from any of them. Step 3 is the one most likely to be
copy-pasted, and the carve-out is the one most likely to be cited by a future
editor as licence to hand-build a name.

### FILL IN checklist
- [ ] `CLAUDE.md` carve-out opening sentences; bounded by "keep FEAT-466 / PR #1250
      attribution and the reason it mattered"

---

## Acceptance Criteria

- [ ] `grep -n "feat-<id>-<slug>" CLAUDE.md` returns nothing
- [ ] `CLAUDE.md` no longer says `/sdd-task` creates or precedes a worktree (lines 243, carve-out, table row)
- [ ] Typical Workflow step 3 invokes `/sdd-start`, not `git worktree add`
- [ ] The FEAT-466 carve-out still cites FEAT-466 and PR #1250 and still states that a hotfix must branch from `origin/main`
- [ ] `CLAUDE.md` names `scripts.sdd.ensure_worktree` at least once
- [ ] The `## Worktree Creation` heading and the Cleanup / .gitignore / Quick reference subsections are otherwise unchanged
- [ ] No other section of `CLAUDE.md` is modified: `git diff --stat CLAUDE.md` shows a single file with a small, reviewable hunk count

---

## Test Specification

Documentation only; the greps above are the verification, and TASK-3160 makes
the `feat-<id>-<slug>` one permanent.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above (§3 Module 7)
2. **Check dependencies** — TASK-3156 in `sdd/tasks/completed/`, so the docs
   describe a `/sdd-task` that has actually stopped creating worktrees
3. **Verify the Codebase Contract** — re-confirm each anchor's line number; other
   FEAT-552 tasks do not touch `CLAUDE.md`, so they should still hold
4. **Update status** in `sdd/tasks/index/worktree-creation-ownership.json` → `"in-progress"`
5. **Implement** from the blueprint
6. **Verify** all acceptance criteria
7. **Move this file** to `sdd/tasks/completed/TASK-3159-docs-worktree-ownership.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
