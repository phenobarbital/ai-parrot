---
type: Wiki Overview
title: 'TASK-1256: Block `type: feature, base_branch: main` across SDD commands'
id: doc:sdd-tasks-completed-task-1256-feature-base-validation-commands-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This task implements **Module 4** of FEAT-187. The Git Parrot Flow
---

# TASK-1256: Block `type: feature, base_branch: main` across SDD commands

**Feature**: FEAT-187 — Git Parrot Flow — Staging Branch and Sync Automation
**Spec**: `sdd/specs/git-parrot-flow.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1253
**Assigned-to**: unassigned

---

## Context

This task implements **Module 4** of FEAT-187. The Git Parrot Flow
requires that features NEVER base on `main`. The only flow that touches
`main` directly is `hotfix`. Right now, `/sdd-brainstorm` lines 46–60
explicitly offer "feature lands on main or another integration branch"
as an option, and other commands have no validation against this
config. This task closes that loophole across all SDD commands and
the autonomous agent.

The change is enforcement (refuse with a clear error) and prose
cleanup (drop language permitting feature → main). It also documents
that `staging` is a valid `base_branch` for `feature` flows during a
release-freeze window.

---

## Scope

For each affected file, apply two kinds of edits:

1. **Refuse rule**: where the command currently reads frontmatter and
   acts on `BASE_BRANCH`, add a check that refuses if
   `TYPE == "feature"` and `BASE_BRANCH == "main"`. Error message:
   ```
   ⚠️  type='feature' cannot base on 'main'. Features land on dev (default)
      or staging (during a release freeze). For changes that must base
      on main, set type='hotfix' in the document frontmatter.
   ```

2. **Prose cleanup**:
   - `/sdd-brainstorm.md` lines 46–60: drop "lands on `main` or another
     integration branch"; replace with "lands on `dev` (default) or
     `staging` during a release freeze". Hotfix line unchanged.
   - `/sdd-proposal.md`: same prose cleanup if mirrored.
   - `sdd-worker.md` §0: mention `staging` as a valid `base_branch`
     for feature flows.
   - `/sdd-spec.md`, `/sdd-task.md`: add one-line note in the
     base-branch handling section that `staging` is allowed.

**NOT in scope**:
- Changes to `/sdd-done.md` (covered by TASK-1255).
- Changes to `/sdd-start.md` (already honours `base_branch` from
  frontmatter — verified, no edit needed for this scope).
- Updating `sdd/templates/*.md`. Templates already use the FEAT-145
  frontmatter shape; no schema change is needed.
- Any change to `scripts/sdd/sdd_meta.py` beyond what TASK-1253 did.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.claude/commands/sdd-spec.md` | MODIFY | Add feature-main refusal check; mention staging valid |
| `.claude/commands/sdd-task.md` | MODIFY | Same |
| `.claude/commands/sdd-brainstorm.md` | MODIFY | Lines 46–60 prose cleanup; refuse if type=feature base=main |
| `.claude/commands/sdd-proposal.md` | MODIFY | Mirror prose cleanup |
| `.claude/agents/sdd-worker.md` | MODIFY | §0 mention staging as valid base |

---

## Codebase Contract (Anti-Hallucination)

### Verified Existing Surfaces

| File | Lines | Anchor |
|---|---|---|
| `.claude/commands/sdd-spec.md` | 294 | `BASE_BRANCH` handling at line ~128-157 |
| `.claude/commands/sdd-task.md` | 202 | Sync block at the top of "Steps §1" |
| `.claude/commands/sdd-brainstorm.md` | 198 | Type question at lines 46-60 (verified) |
| `.claude/commands/sdd-proposal.md` | 484 | (locate by grep for "type:" and "base_branch:") |
| `.claude/agents/sdd-worker.md` | 289 | §0 "Sync the Base Branch" block at line ~80 |

The current `/sdd-brainstorm.md` lines 46-60 say (verified):
```
1. Is this a regular **feature** (lands on `dev` or another integration branch) or a **hotfix** (lands on `main`)?
   If `hotfix`, base is fixed to `main` — no choice.
...
type: feature | hotfix
base_branch: dev | main | <other>
```

The "or `main`" in `base_branch: dev | main | <other>` is the offending
language. Replace `dev | main | <other>` with
`dev | staging | <other-feature-branch>` for features, and document
that `main` is only valid when `type == hotfix`.

### Existing Validation Pattern

`/sdd-spec.md:133-136` already shows the hotfix validation pattern:
```
**Validation:** if `TYPE == "hotfix"` and `BASE_BRANCH != "main"`, abort:
```
```
⚠️  type='hotfix' requires base_branch='main' (got base_branch='<value>').
```

The new validation in this task is the SYMMETRIC rule: if
`TYPE == "feature"` and `BASE_BRANCH == "main"`, abort with the
analogous message. Place the new check immediately after the existing
hotfix check.

### KNOWN_BRANCHES Reference

TASK-1253 added `KNOWN_BRANCHES = frozenset({"main", "staging", "dev"})`
to `scripts/sdd/sdd_meta.py`. Commands MAY reference this constant
when documenting valid bases:
```python
from scripts.sdd.sdd_meta import KNOWN_BRANCHES
# Used for soft-warn only when base_branch not in KNOWN_BRANCHES
```

Use it for prose, not for refusal. Refusal is binary: feature + main =
no. Anything else is permitted (with a soft warning for unknown
branches, but not a refuse — sub-feature branches per CLAUDE.md).

### Does NOT Exist
- ~~A central command preamble that all SDD commands share~~ — they are
  independent markdown files. Each edit is local to its file.
- ~~A `FlowMeta.is_feature_main()` helper~~ — no helper. Each command
  inlines the check as a shell condition.
- ~~A Python validator in `sdd_meta.py` for feature-main~~ — explicitly
  rejected in the spec (the validator stays minimal; commands enforce
  policy). Do NOT add a validator.

---

## Implementation Notes

### Pattern to Follow — Refusal Check

Insert immediately after the existing hotfix validation block:

```
**Validation:** if `TYPE == "feature"` and `BASE_BRANCH == "main"`, abort:
```
```
⚠️  type='feature' cannot base on 'main'. Features land on dev (default)
   or staging (during a release freeze). For changes that must base on
   main, set type='hotfix' in the document frontmatter.
```

Apply this verbatim in:
- `/sdd-spec.md` (right after the hotfix-validates-main block)
- `/sdd-task.md` (right after the hotfix-validates-main block)
- `/sdd-brainstorm.md` (in the type-question generation section)
- `/sdd-proposal.md` (mirror)
- `/sdd-worker.md` (§0 sync block)

### Pattern to Follow — Prose Cleanup

In `/sdd-brainstorm.md` line 46-60, replace the block text. Suggested
new wording:

```
1. Is this a regular **feature** or a **hotfix**?
   - `feature` lands on `dev` (default) or, during a release freeze,
     on `staging`. Features NEVER land on `main`.
   - `hotfix` lands on `main`. After the PR to `main` merges, the
     change is propagated back to `staging` and `dev` automatically
     by `.github/workflows/sync-down.yml` (FEAT-187).
...
type: feature | hotfix
base_branch: dev | staging   # for type=feature (defaults to dev)
                              # or `main` (mandatory for type=hotfix)
```

### Key Constraints
- Each file edit MUST use `Edit` (not `Write`) so the file's
  surrounding content is preserved exactly. These are
  surgical changes.
- Do NOT factor the refusal into a shared snippet — duplicating it
  inline is correct for this codebase. Each command file is meant to
  be readable standalone.
- Verify with `grep` that no remaining file contains the literal
  string `feature.*main.*under request` or "feature can land on main"
  in any prose. Spec calls out CLAUDE.md's "When NOT to Use Worktrees"
  section as one such place — but that file is covered by TASK-1257
  (docs), so leave it alone here.

### References in Codebase
- `.claude/commands/sdd-spec.md:128-157` — hotfix-validates-main block (pattern source)
- `.claude/commands/sdd-brainstorm.md:46-60` — type question (primary edit)
- `scripts/sdd/sdd_meta.py` — `KNOWN_BRANCHES` (use only for prose)
- `sdd/specs/git-parrot-flow.spec.md` §3 Module 4 — design intent

---

## Acceptance Criteria

- [ ] All five files mention `staging` at least once.
- [ ] All five files include the `type='feature' cannot base on 'main'` refusal block (or equivalent prose).
- [ ] `.claude/commands/sdd-brainstorm.md` no longer contains the literal `base_branch: dev | main` in its YAML example for `type: feature`.
- [ ] No instance of "feature.*lands on `main`" or "feature.*on main under request" remains in the five files.
- [ ] `grep -l "main \\| <other>" .claude/commands/sdd-*.md` returns no matches in the edited files (the offending literal was removed).
- [ ] `ruff check` / `actionlint` not applicable (markdown).
- [ ] No change to `.claude/commands/sdd-done.md` (covered by TASK-1255).
- [ ] No change to `.claude/commands/sdd-start.md` (out of scope).
- [ ] No change to `sdd/templates/*.md` (out of scope).

---

## Test Specification

Validation by grep (all must return non-empty):

```bash
for f in .claude/commands/sdd-spec.md \
         .claude/commands/sdd-task.md \
         .claude/commands/sdd-brainstorm.md \
         .claude/commands/sdd-proposal.md \
         .claude/agents/sdd-worker.md; do
  grep -q 'staging' "$f" || { echo "FAIL: $f missing staging mention"; exit 1; }
  grep -q "type='feature' cannot base on 'main'" "$f" \
    || grep -qi "feature.*cannot.*base.*main" "$f" \
    || { echo "FAIL: $f missing refusal block"; exit 1; }
done
echo "PASS"
```

The literal regression check:
```bash
! grep -E "feature.*lands on \`main\`" .claude/commands/sdd-*.md .claude/agents/sdd-worker.md
```

---

## Agent Instructions

1. Read each of the five files end-to-end before editing.
2. Apply edits surgically with `Edit` — do NOT rewrite whole files.
3. Verify with the grep checks in Test Specification.
4. Run the existing test from TASK-1258 (if it has been merged) — but
   note TASK-1258 lives downstream; this task does not block on it.
5. Move this task to `sdd/tasks/completed/`, update the per-spec index.

---

## Completion Note

Implemented by sdd-worker (FEAT-187). All five files received surgical edits: (1) sdd-brainstorm.md: rewrote lines 46-60 type-question block with new prose, removed `base_branch: dev | main | <other>` YAML example, added refusal block. (2) sdd-spec.md: added feature-main refusal check immediately after the hotfix validation block, plus staging note. (3) sdd-task.md: updated prose to include `staging` as valid feature base, added refusal block. (4) sdd-proposal.md: updated Step 0 to mention `staging` as valid integration branch, added refusal block. (5) sdd-worker.md: §0 now mentions `staging` as valid base_branch and includes the refusal block. All grep checks pass. No change to sdd-done.md or sdd-start.md.
