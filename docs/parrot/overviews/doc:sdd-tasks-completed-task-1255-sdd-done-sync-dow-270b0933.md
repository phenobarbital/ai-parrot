---
type: Wiki Overview
title: 'TASK-1255: Refactor `/sdd-done` sync-down to target `{staging, dev}`'
id: doc:sdd-tasks-completed-task-1255-sdd-done-sync-down-refactor-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This task implements **Module 3** of FEAT-187. The `/sdd-done` command
---

# TASK-1255: Refactor `/sdd-done` sync-down to target `{staging, dev}`

**Feature**: FEAT-187 — Git Parrot Flow — Staging Branch and Sync Automation
**Spec**: `sdd/specs/git-parrot-flow.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1253, TASK-1254
**Assigned-to**: unassigned

---

## Context

This task implements **Module 3** of FEAT-187. The `/sdd-done` command
currently has a `--sync-dev` flag that propagates a merged hotfix from
`main` back into `dev`. With FEAT-187 introducing a `staging` branch
that must also be kept in sync, the flag needs to:

1. Be renamed to `--sync-down` (intent: propagate down the chain).
2. Propagate the hotfix to BOTH `staging` and `dev`, in that order.
3. Preserve `--sync-dev` as a deprecated alias that prints a one-line
   notice and behaves identically to `--sync-down`.
4. Handle each target independently: if `staging` FF fails, abort that
   leg and still attempt `dev`, printing actionable recovery commands
   for the failed target.

This command is mostly a fallback now — the new
`.github/workflows/sync-down.yml` Action (TASK-1254) handles the common
case automatically. `/sdd-done --sync-down` is for offline / aborted
Action workflows.

---

## Scope

- Rewrite the relevant header / usage / guardrail blocks of
  `.claude/commands/sdd-done.md` to:
  - Use `--sync-down` as the primary flag name.
  - Document `--sync-dev` as a deprecated alias.
  - Mention the Action as the primary sync mechanism.
- Rewrite §9.5 ("Hotfix → Dev Sync") to "Hotfix → Sync-down" with the
  two-target loop, in the order `[staging, dev]`.
- Each target uses the existing optimistic-FF / safe-abort pattern,
  but failures are independent — print the resolution commands for
  the failed target(s) and continue with the rest.
- Update the documentation block at the top of the command file that
  says "After the user merges the PR, re-run with `--sync-dev` to
  propagate the change back to `dev`" → mention `staging` too.

**NOT in scope**:
- Changing the hard-refusal logic in §9 that blocks merging into
  `main`. That stays exactly as-is.
- Modifying any of the verification / evidence-gathering steps
  (§4–§6). Out of scope.
- Removing the `--sync-dev` flag. Deprecation only; removal is a
  follow-up spec ~90 days later (per spec §7).
- Changes to `/sdd-start`, `/sdd-task`, `/sdd-spec`, or any other
  command. Those are covered by TASK-1256.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.claude/commands/sdd-done.md` | MODIFY | Rename flag, add alias, rewrite §9.5 to two-target sync |

---

## Codebase Contract (Anti-Hallucination)

### Verified Existing Surfaces

`.claude/commands/sdd-done.md` is **459 lines** (verified 2026-05-19).

The Usage block (verified at lines ~20-28):
```
/sdd-done FEAT-014
/sdd-done videoreel-visual-changes
/sdd-done FEAT-014 --dry-run
/sdd-done FEAT-014 --force
/sdd-done FEAT-014 --resolve-jira
/sdd-done FEAT-014 --sync-dev          # ← this is the flag to rename
```

The Guardrails section (verified at lines ~30-44) contains:
```
After the user merges the PR, re-run with `--sync-dev` to propagate the change back to `dev`.
```

§9.5 begins around line 201 with the heading:
```
### 9.5. Hotfix → Dev Sync (FEAT-145, only with `--sync-dev`)
```

and currently runs `git checkout dev && git pull --ff-only && git merge --no-edit feat-<id>-<slug>`,
with a `git merge --abort` on conflict. The block ends around line 237.

### Patterns to Preserve Verbatim

The merge pattern stays identical per target:
```bash
git fetch origin
if ! git merge-base --is-ancestor "feat-<FEAT-ID>-<slug>" origin/main; then
    echo "⚠️  feat-<FEAT-ID>-<slug> is not yet an ancestor of origin/main."
    exit 1
fi

git checkout <TARGET>
git pull --ff-only origin <TARGET>

if git merge --no-edit feat-<FEAT-ID>-<slug>; then
    git push origin <TARGET>
    echo "✅ <TARGET> synced with hotfix feat-<FEAT-ID>-<slug>."
else
    git merge --abort
    # actionable resolution snippet
fi
```

The pre-flight `git merge-base --is-ancestor ... origin/main` check
runs ONCE for both targets — the hotfix only needs to be on `main`
once. Do NOT duplicate the pre-flight per target.

### Does NOT Exist
- ~~A `--sync-down` flag~~ — does not exist yet; this task introduces it.
- ~~A loop or matrix over branches in the current `/sdd-done`~~ — current
  code is a single-target script for `dev` only.
- ~~An automatic auto-sync trigger from `/sdd-done` to the Action~~ —
  the command and the Action are independent; one runs locally, the
  other on GitHub. They do not chain.

---

## Implementation Notes

### Pattern to Follow

Step 9.5 rewrite, in pseudocode (the actual edit is to the markdown
that documents this — it's a Claude Code skill file, not a script):

```
### 9.5. Hotfix → Sync-down (FEAT-187, only with `--sync-down`)

This sub-step runs ONLY when the user passes `--sync-down` (or the
deprecated `--sync-dev` alias) AND `TYPE == "hotfix"`. It propagates
a hotfix that has just been merged into `main` (via the manual PR
from §9) back into `staging` and `dev` so both stay in sync.

In normal operation, `.github/workflows/sync-down.yml` does this
automatically. Run this command only when the Action has failed or
the user is operating offline.

**Pre-flight (run once):** verify the hotfix landed on `origin/main`.
[existing block]

**For each TARGET in [staging, dev]:**
  Run the optimistic-FF / safe-abort pattern.
  Track per-target outcome.

**Summary:** print one line per target with success/failure status.
If any target failed, exit with code 1; otherwise exit 0.
```

The actual edits are to a markdown skill file. Follow the existing
prose style in `sdd-done.md` (numbered steps, code fences for
bash blocks, ⚠️/✅ for status lines).

### Flag Aliasing

In the Usage block:
```
/sdd-done FEAT-014 --sync-down          # for hotfixes: after the user merges the PR
                                        # to main, propagate the change to staging + dev
                                        # (mostly redundant with sync-down.yml Action)
/sdd-done FEAT-014 --sync-dev           # deprecated alias for --sync-down
```

In the parsing logic block (described in prose in the skill), the
agent that runs `/sdd-done` should treat the two flags as equivalent
and emit a one-line deprecation notice if `--sync-dev` is used:
```
ℹ️  --sync-dev is deprecated; use --sync-down. Continuing with sync-down behaviour.
```

### Key Constraints
- Each target runs in sequence (NOT parallel). The order is
  `[staging, dev]` — staging first because it is closer to `main` in
  the chain and typically has fewer divergent commits.
- `git checkout` between targets means the working directory branch
  changes; the final state should leave the user on `BASE_BRANCH`
  (i.e., `main`, since this is a hotfix flow). End the block with an
  explicit `git checkout main`.
- The pre-flight `--is-ancestor` check uses `origin/main` and runs
  ONCE.
- Do NOT introduce a `for` loop in shell prose — that's hard to read
  in a skill file. Repeat the per-target block once per target, with
  the only difference being the `<TARGET>` substitution. Two blocks
  = two targets, explicit.

### References in Codebase
- `.claude/commands/sdd-done.md:201-237` — the §9.5 block to rewrite
- `.claude/commands/sdd-done.md:6-12` — the "runs on base_branch" preamble (mention staging is allowed for `feature` during freeze)
- `sdd/specs/git-parrot-flow.spec.md` §1 Goals — the rationale
- `sdd/specs/git-parrot-flow.spec.md` §3 Module 3 — the target list and order

---

## Acceptance Criteria

- [ ] `.claude/commands/sdd-done.md` Usage block documents `--sync-down` and `--sync-dev` (deprecated).
- [ ] The Guardrails preamble mentions `staging` as one of the propagation targets.
- [ ] §9.5 is renamed "Hotfix → Sync-down" and propagates to both `staging` and `dev`.
- [ ] The pre-flight `--is-ancestor origin/main` check runs once, not per target.
- [ ] Each target's failure is independent — the script continues to the next target.
- [ ] On `--sync-dev` use, a one-line deprecation notice is documented.
- [ ] Final exit code is 0 only if BOTH targets succeed; otherwise 1.
- [ ] The block ends with an explicit `git checkout main` so the user lands on the hotfix's base branch.
- [ ] No change to §9 hard-refusal logic that blocks pushing to `main`.
- [ ] No other command file is modified.

---

## Test Specification

This is a skill file (markdown), not executable code. Validation is
by grep / read review:

```bash
# All four checks must pass
grep -q -- '--sync-down' .claude/commands/sdd-done.md
grep -q -- '--sync-dev.*deprecated' .claude/commands/sdd-done.md
grep -qE '(staging.*dev|dev.*staging)' .claude/commands/sdd-done.md
! grep -qE 'sync.*to.*dev"$' .claude/commands/sdd-done.md  # no longer dev-only

# Integration tests (manual, post-merge):
# - Run /sdd-done <hotfix-feat-id> --sync-down on a test hotfix
# - Run /sdd-done <hotfix-feat-id> --sync-dev (deprecation notice should appear)
```

---

## Agent Instructions

1. Read `.claude/commands/sdd-done.md` end-to-end to understand the existing structure.
2. Identify the exact line ranges to edit:
   - Usage block (~lines 20-28)
   - Guardrails preamble (~lines 30-44)
   - §9.5 Hotfix → Dev Sync (~lines 201-237)
3. Apply edits using `Edit` (not `Write` — preserve everything else exactly).
4. Verify with the grep checks in Test Specification.
5. Move this task to `sdd/tasks/completed/`, update the per-spec index.

---

## Completion Note

Implemented by sdd-worker (FEAT-187). Renamed flag `--sync-dev` to `--sync-down` in Usage block with `--sync-dev` kept as deprecated alias. Guardrails updated to mention both `staging` and `dev` propagation targets and reference the sync-down.yml Action. §9 hard-refusal block updated to reference `--sync-down`. §9.5 completely rewritten as "Hotfix → Sync-down" with two independent target blocks (staging first, then dev), one-time pre-flight check, independent failure handling per target, explicit `git checkout main` at end, and summary exit code. All grep checks pass.
