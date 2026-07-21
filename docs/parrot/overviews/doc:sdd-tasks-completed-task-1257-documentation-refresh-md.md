---
type: Wiki Overview
title: 'TASK-1257: Documentation refresh — three-branch model + release-cut procedure'
id: doc:sdd-tasks-completed-task-1257-documentation-refresh-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This task implements **Module 5** of FEAT-187. After the code changes
---

# TASK-1257: Documentation refresh — three-branch model + release-cut procedure

**Feature**: FEAT-187 — Git Parrot Flow — Staging Branch and Sync Automation
**Spec**: `sdd/specs/git-parrot-flow.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1253, TASK-1254, TASK-1255, TASK-1256
**Assigned-to**: unassigned

---

## Context

This task implements **Module 5** of FEAT-187. After the code changes
(Modules 1–4) land, the documentation that Claude Code sessions and
human contributors read on every interaction needs to describe the new
three-branch model. The two surfaces are:

- `CLAUDE.md` — loaded into every Claude Code conversation in this
  repo. Its "Git Configuration" / "SDD Workflow & Worktree Policy"
  sections currently describe the two-branch model (dev ↔ main) with
  a hotfix bypass. They need rewriting.
- `sdd/WORKFLOW.md` — the canonical SDD documentation. It currently
  has no "Release Cut" section. The release-cut procedure (cutting
  `staging` from `dev`, eventually PR-ing to `main`) needs to be
  documented end-to-end.

Documentation parity between the two files is critical — both are
read together by automated and human readers.

---

## Scope

1. **`CLAUDE.md`**:
   - Rewrite the "Git Configuration" block (currently lines ~28-40,
     verify before editing) to describe three long-lived branches:
     - `main` — tagged releases, hotfix landing zone.
     - `staging` — release candidates, cut from `dev` at freeze time.
     - `dev` — integration branch for all feature work.
   - Document that `.github/workflows/sync-down.yml` auto-propagates
     `main → {staging, dev}` after every hotfix merge.
   - Note that branch protection rules on `main` (and `staging` once
     in active use) are recommended (out-of-scope to configure here).
   - Remove any wording that permits features to base on `main`
     "under request".
   - Add `staging` to the worktree workflow examples where they
     enumerate base branches.

2. **`sdd/WORKFLOW.md`**:
   - Add a new section: `## Release Cut` covering:
     - When to cut: team decision to freeze.
     - How to cut (manual, today): `git checkout dev && git pull
       --ff-only && git checkout -B staging origin/dev && git push
       --set-upstream origin staging`.
     - What happens during the freeze: hotfixes land on `main` and
       auto-sync to `staging` via the Action; feature work continues
       on `dev` independently; fixes specific to the release land on
       `staging` directly (with `type: feature, base_branch: staging`).
     - How to release: open PR `staging → main`, review, merge, tag
       `vX.Y.Z` on `main`. The Action then syncs the tag commit back
       to `dev` automatically.
   - Update the "Git Configuration" subsection (if present) to match
     `CLAUDE.md`.
   - Add a "Recommended Branch Protection" subsection noting that
     `main` should require PRs, status checks, and signed commits
     (purely recommendation; this task does not configure it).

**NOT in scope**:
- Creating a `/sdd-release-cut` command. Open question in spec §8.
- Configuring branch protection rules in the repo settings or via a
  declarative file.
- Modifying any other markdown in the repo (README, package READMEs,
  etc.).
- Touching `.agent/CONTEXT.md` or any rule files in `.claude/rules/`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `CLAUDE.md` | MODIFY | Rewrite "Git Configuration" + SDD Workflow sections |
| `sdd/WORKFLOW.md` | MODIFY | Add "Release Cut" section + update Git Config |

---

## Codebase Contract (Anti-Hallucination)

### Verified Existing Surfaces

`CLAUDE.md` is **304 lines** (verified 2026-05-19). It opens with a
"Git Configuration" block (visible in the project instructions) that
contains:
- `**Integration branch**: dev`
- `**Production branch**: main`
- `**Flow types** (FEAT-145): every brainstorm/proposal/spec declares type and base_branch`
- A line that says `/sdd-done NEVER pushes to or opens a PR against main`
- A reference to `/sdd-done <FEAT-ID> --sync-dev` (this becomes `--sync-down` per TASK-1255)

`sdd/WORKFLOW.md` is **242 lines** (verified 2026-05-19). It documents
the SDD lifecycle phases. There is no Release Cut section currently.

### Patterns to Preserve

The existing voice / style of both files:
- Use `>` blockquotes for critical warnings.
- Use shell code blocks with `bash` highlighting for commands.
- Use tables for command-to-purpose mappings.
- Sections demarcated with `---` and `##` / `###` headers.

The new content MUST match this style.

### Cross-Reference Conventions

Both files reference `(FEAT-XXX)` for spec provenance. New content
referring to staging/sync-down should cite `(FEAT-187)`.

### Does NOT Exist
- ~~A `staging` mention in either file today~~ — verified absent via
  `grep -i staging CLAUDE.md sdd/WORKFLOW.md` (no matches). This task
  introduces it.
- ~~A `## Release Cut` section anywhere in the repo~~ — verified absent.
- ~~A `branch-protection.yml` or similar declarative config~~ — not in
  the repo; explicitly out of scope.
- ~~Any reference to `peter-evans/create-pull-request` outside of
  TASK-1254's new workflow~~ — these docs should mention the Action by
  filename (`.github/workflows/sync-down.yml`), not by the third-party
  action it uses.

---

## Implementation Notes

### Pattern to Follow — `CLAUDE.md` Git Configuration Rewrite

Suggested replacement for the current "Git Configuration" subsection:

```markdown
## Git Configuration

The Git Parrot Flow (FEAT-187) uses three long-lived branches:

- **`main`** — tagged releases only. Hotfixes land here via PR;
  no feature work ever bases on `main`.
- **`staging`** — release candidate branch. Cut from `dev` when the
  team decides to freeze a release. Receives `main → staging` syncs
  automatically (via `.github/workflows/sync-down.yml`); the
  `dev → staging` direction is a manual cut at freeze time.
- **`dev`** — integration branch for all feature work. Default base
  for `type: feature` flows.

**Flow types** (FEAT-145, refined by FEAT-187):
- `feature` — base is `dev` (default) or `staging` (during a release
  freeze). NEVER `main`.
- `hotfix` — base is `main` (mandatory).

**Sync-down automation** (FEAT-187): `.github/workflows/sync-down.yml`
listens for pushes to `main` and tries to fast-forward `staging` and
`dev`. When fast-forward is not possible, it opens a sync PR against
the lagging branch. `/sdd-done --sync-down` is the manual fallback for
the same operation.

**`/sdd-done` NEVER pushes to or opens a PR against `main`** —
hotfix PRs are user-initiated. After the user merges the hotfix into
`main`, the Action propagates the change to `staging` and `dev`. If
the Action fails (or the user is offline), run
`/sdd-done <FEAT-ID> --sync-down` to do the same locally.

**Recommended branch protection**: `main` (and `staging` once in use)
should require PRs, passing CI, and signed commits. Not configured
declaratively in this repo — set via GitHub repo settings.
```

### Pattern to Follow — `sdd/WORKFLOW.md` New Section

Append a `## Release Cut` section at the end of the "Git Configuration"
block (or wherever the file's existing flow sections live; locate by
reading the file before editing).

Suggested content sketch:

```markdown
## Release Cut

When the team decides to freeze a release, a maintainer cuts `staging`
from `dev`. This is a manual, infrequent operation today (see open
question in `sdd/specs/git-parrot-flow.spec.md` §8 about a future
`/sdd-release-cut` command).

### Cutting the branch

```bash
git checkout dev
git pull --ff-only origin dev

# First freeze (creates the branch):
git checkout -B staging origin/dev
git push --set-upstream origin staging

# Subsequent freezes (staging already exists):
git checkout staging
git merge --ff-only dev
git push origin staging
```

### During the freeze

- New feature work continues on `dev`. It is destined for the NEXT
  release, not this one.
- Hotfixes land on `main` as usual. The sync-down Action propagates
  them to `staging` and `dev` automatically.
- Stabilization fixes that target THIS release should land on
  `staging` directly: open a brainstorm/spec with
  `type: feature, base_branch: staging`.

### Releasing

1. Open PR `staging → main`.
2. Review, run full CI, ensure all stabilization fixes are in.
3. Merge the PR.
4. Tag the merge commit: `git tag vX.Y.Z && git push origin vX.Y.Z`.
5. The Action propagates the merge commit back to `dev` (and to
   `staging` if any post-merge fixes were on `main`).
6. `.github/workflows/release.yml` fires on the tag event and
   publishes the release artifacts.
```

### Key Constraints
- Both files MUST cite `FEAT-187` at least once so future readers can
  trace provenance.
- The shell snippets in both files MUST be identical — no drift between
  `CLAUDE.md` and `WORKFLOW.md`.
- Do NOT introduce new markdown features (admonitions, mermaid
  diagrams, etc.) that the existing files don't use.

### References in Codebase
- `CLAUDE.md` — lines 28-44 contain the current Git Configuration / SDD Workflow & Worktree Policy block (verify with `head -50 CLAUDE.md`)
- `sdd/WORKFLOW.md` — full file
- `sdd/specs/git-parrot-flow.spec.md` §1 Goals, §2 Component Diagram, §7 Patterns to Follow
- `.github/workflows/sync-down.yml` (after TASK-1254) — reference target

---

## Acceptance Criteria

- [ ] `CLAUDE.md` contains the word `staging` at least 3 times in the Git Configuration / SDD Workflow section.
- [ ] `CLAUDE.md` no longer says `dev` is "the integration branch" alone — it must list all three long-lived branches.
- [ ] `CLAUDE.md` cites `FEAT-187` at least once.
- [ ] `CLAUDE.md` references `/sdd-done --sync-down` (not `--sync-dev` alone).
- [ ] `sdd/WORKFLOW.md` contains a new `## Release Cut` section with three subsections: cutting the branch, during the freeze, releasing.
- [ ] `sdd/WORKFLOW.md` cites `FEAT-187`.
- [ ] Shell snippets in `CLAUDE.md` and `sdd/WORKFLOW.md` for `staging`-related operations are byte-identical (verify by extraction + diff).
- [ ] No `branch-protection.yml` or similar config file is created (out of scope).
- [ ] No other markdown file is modified.

---

## Test Specification

Validation by grep:

```bash
grep -c 'staging' CLAUDE.md  # ≥ 3
grep -q 'FEAT-187' CLAUDE.md  # exit 0
grep -q -- '--sync-down' CLAUDE.md  # exit 0

grep -q '## Release Cut' sdd/WORKFLOW.md  # exit 0
grep -q 'FEAT-187' sdd/WORKFLOW.md  # exit 0
grep -q 'sync-down.yml' sdd/WORKFLOW.md  # exit 0
```

---

## Agent Instructions

1. Read `CLAUDE.md` and `sdd/WORKFLOW.md` end-to-end first.
2. Locate the Git Configuration block in each (line numbers may have shifted since the spec was written; re-verify).
3. Apply edits with `Edit` (preserve surrounding content).
4. Verify with the grep checks in Test Specification.
5. Move this task to `sdd/tasks/completed/`, update the per-spec index.

---

## Completion Note

Implemented by sdd-worker (FEAT-187). CLAUDE.md "Git Configuration" block rewritten to describe the three long-lived branches (main, staging, dev), the sync-down.yml Action, --sync-down flag, and recommended branch protection. 8 `staging` mentions total, cites FEAT-187, references --sync-down. sdd/WORKFLOW.md received a "Git Configuration (FEAT-187)" subsection update and a new `## Release Cut` section with three subsections (cutting the branch, during the freeze, releasing) plus Recommended Branch Protection note. Both files cite FEAT-187 and reference sync-down.yml. All grep checks pass.
