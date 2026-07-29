---
type: Wiki Overview
title: 'TASK-1254: Create `sync-down.yml` GitHub Action'
id: doc:sdd-tasks-completed-task-1254-sync-down-github-action-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This task implements **Module 2** of FEAT-187. It creates the GitHub
---

# TASK-1254: Create `sync-down.yml` GitHub Action

**Feature**: FEAT-187 — Git Parrot Flow — Staging Branch and Sync Automation
**Spec**: `sdd/specs/git-parrot-flow.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This task implements **Module 2** of FEAT-187. It creates the GitHub
Action that auto-propagates merges to `main` down to `staging` and
`dev`. The Action is the linchpin of the new flow — without it, the
team would have to manually run `/sdd-done --sync-down` after every
hotfix PR merges into `main`, which is exactly the failure mode
FEAT-187 is fixing.

The Action uses a matrix over `[staging, dev]` so the two targets are
independent: if `staging` cannot fast-forward (rare, but possible
during a release freeze when `staging` has diverged), `dev` still
syncs and a sync-PR is opened for `staging` only.

This task is functionally independent of TASK-1253 (no code overlap)
but conventionally sequenced after it per the spec's stated order.

---

## Scope

- Create `.github/workflows/sync-down.yml` per the design in spec §2 ("New Public Interfaces").
- Matrix strategy over `[staging, dev]` with `fail-fast: false`.
- FF-step uses `continue-on-error: true` so a failure routes to the PR-fallback step.
- PR-fallback step uses `peter-evans/create-pull-request@v6`, pinned by major.
- First-run guard: the FF step MUST check that the target branch exists on origin via `git ls-remote --exit-code --heads origin <target>`; if absent, exit 0 with a `::notice::` log line. This is documented in spec §7 as the "first-run race" hazard.
- Trigger: `on: push: branches: [main]`. No PR, no schedule, no manual trigger.
- Permissions: `contents: write, pull-requests: write` on the default `GITHUB_TOKEN`. No PAT.
- PR branch name pattern: `chore/sync-main-into-<target>-<sha>` (collision-safe).
- PR title: `chore: sync main into <target>`.
- PR body: identifies the source commit and target, explains why FF failed (informational).

**NOT in scope**:
- Cutting the `staging` branch on the remote (operator action, documented in TASK-1257).
- Branch protection rules (mentioned in TASK-1257 docs as recommended; not configured here).
- Any change to `ci.yml`, `release.yml`, or `codeql-analysis.yml` (regression guard).
- Bidirectional sync (`dev → staging` automatic) — explicitly rejected in spec §1 Non-Goals.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.github/workflows/sync-down.yml` | CREATE | The new Action — see spec §2 for skeleton |

---

## Codebase Contract (Anti-Hallucination)

### Verified Patterns

Pinning convention from `.github/workflows/ci.yml:14` (verified 2026-05-19):
```yaml
- uses: actions/checkout@v4
```

The `setup-uv` action is pinned by major:
```yaml
- name: Install uv
  uses: astral-sh/setup-uv@v4
```

Apply the same major-pin discipline to `peter-evans/create-pull-request@v6`.

### Existing Workflow Files (do NOT modify in this task)

| File | Lines | Purpose |
|---|---|---|
| `.github/workflows/ci.yml` | 32+ | Lint + matrix tests on push to main/dev, PRs to main/dev |
| `.github/workflows/release.yml` | 80+ | Build wheels on GitHub release event |
| `.github/workflows/codeql-analysis.yml` | (unread, security scan) | CodeQL static analysis |

None of these listen for the bare `push: branches: [main]` trigger we
need, so there is no overlap or conflict.

### Does NOT Exist
- ~~`.github/workflows/sync-down.yml`~~ — does not exist yet. This task creates it.
- ~~`origin/staging`~~ — branch does not exist on remote at the time
  this task ships. The Action MUST handle this gracefully (skip with
  notice, exit 0). Do NOT assume the branch exists.
- ~~A pre-existing `peter-evans/create-pull-request` reference~~ — this
  is the first use of that action in the repo. No prior config to copy.
- ~~A `permissions:` block in any current workflow~~ — verify before
  assuming. Recent GitHub default is `read-all`; this workflow needs
  `write` so the block is mandatory.

---

## Implementation Notes

### Pattern to Follow

Use this skeleton (refined from spec §2 with the first-run guard and
PR body shape added):

```yaml
name: Sync main → {staging, dev}

on:
  push:
    branches: [main]

permissions:
  contents: write
  pull-requests: write

jobs:
  sync:
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        target: [staging, dev]
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
          token: ${{ secrets.GITHUB_TOKEN }}

      - name: Configure git
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

      - name: Check that ${{ matrix.target }} exists on origin
        id: target_exists
        run: |
          if git ls-remote --exit-code --heads origin ${{ matrix.target }} >/dev/null; then
            echo "exists=true" >> "$GITHUB_OUTPUT"
          else
            echo "::notice::Target branch '${{ matrix.target }}' does not exist on origin; skipping."
            echo "exists=false" >> "$GITHUB_OUTPUT"
          fi

      - name: Fast-forward ${{ matrix.target }}
        id: ff
        if: steps.target_exists.outputs.exists == 'true'
        continue-on-error: true
        run: |
          git fetch origin
          git checkout ${{ matrix.target }}
          git merge --ff-only origin/main
          git push origin ${{ matrix.target }}

      - name: Open sync PR if FF failed
        if: steps.target_exists.outputs.exists == 'true' && steps.ff.outcome == 'failure'
        uses: peter-evans/create-pull-request@v6
        with:
          base: ${{ matrix.target }}
          branch: chore/sync-main-into-${{ matrix.target }}-${{ github.sha }}
          title: "chore: sync main into ${{ matrix.target }}"
          body: |
            Automated sync from `main` after merge of commit ${{ github.sha }}.

            Fast-forward to `${{ matrix.target }}` was not possible — the branches
            have diverged. Please review and merge to keep `${{ matrix.target }}`
            aligned with `main`.

            Generated by `.github/workflows/sync-down.yml` (FEAT-187).
```

### Key Constraints
- The `target_exists` step MUST run BEFORE `git fetch origin`. Otherwise the FF step would fail on a missing branch reference rather than skip gracefully.
- The FF step MUST set `continue-on-error: true`. Without it, the matrix leg fails red and the PR-fallback never runs.
- `fetch-depth: 0` is required so the runner has the full history needed for `merge --ff-only`.
- Pin `peter-evans/create-pull-request` to `@v6` (major only). Avoid commit SHA pins for marketplace actions in this repo's convention.

### Validation Before Push

Before committing, validate the YAML:

```bash
source .venv/bin/activate
python -c "import yaml; yaml.safe_load(open('.github/workflows/sync-down.yml')); print('YAML OK')"
```

If `actionlint` is installed (`which actionlint`):
```bash
actionlint .github/workflows/sync-down.yml
```

Both checks must pass before commit.

### References in Codebase
- `.github/workflows/ci.yml` — pattern for `on: push: branches:` trigger
- `sdd/specs/git-parrot-flow.spec.md` §2 — the design source for this workflow
- `sdd/specs/git-parrot-flow.spec.md` §7 — "first-run race" risk this task mitigates

---

## Acceptance Criteria

- [ ] `.github/workflows/sync-down.yml` exists.
- [ ] `python -c "import yaml; yaml.safe_load(open('.github/workflows/sync-down.yml'))"` exits 0.
- [ ] If `actionlint` is available locally, `actionlint .github/workflows/sync-down.yml` exits 0.
- [ ] Trigger is `on: push: branches: [main]` only (no PR, no schedule).
- [ ] Job uses matrix over `[staging, dev]` with `fail-fast: false`.
- [ ] The workflow includes a target-exists guard that skips with `::notice::` when the branch is absent on origin.
- [ ] FF step uses `continue-on-error: true`.
- [ ] PR-fallback uses `peter-evans/create-pull-request@v6` (major-only pin).
- [ ] PR branch name is `chore/sync-main-into-<target>-<sha>`.
- [ ] PR title is `chore: sync main into <target>`.
- [ ] No other workflow file is modified.

---

## Test Specification

Static validation only (manual integration test deferred to operator):

```bash
# In repo root, with venv active:
source .venv/bin/activate
python -c "
import yaml
data = yaml.safe_load(open('.github/workflows/sync-down.yml'))
assert data['on']['push']['branches'] == ['main'], 'trigger mismatch'
assert data['jobs']['sync']['strategy']['matrix']['target'] == ['staging', 'dev']
assert data['jobs']['sync']['strategy']['fail-fast'] is False
print('Static checks passed')
"
```

Manual integration test (post-merge, documented for the operator):
1. Cut `staging` from `dev` on the remote (`git checkout dev && git checkout -b staging && git push origin staging`).
2. Push a trivial commit to `main` and observe the Action run.
3. Verify `staging` and `dev` were both FF-updated; check the Action's logs for `::notice::` if either was already up-to-date.

---

## Agent Instructions

1. Read the spec section §2 ("New Public Interfaces") for the design intent.
2. Create `.github/workflows/sync-down.yml` using the skeleton above.
3. Validate the YAML parses cleanly with `python -c "import yaml; ..."`.
4. If `actionlint` is installed, run it; otherwise note "actionlint not available" in the completion note.
5. Move this task to `sdd/tasks/completed/`, update the per-spec index.

---

## Completion Note

Implemented by sdd-worker (FEAT-187). Created `.github/workflows/sync-down.yml` with matrix over `[staging, dev]`, `fail-fast: false`, target-exists guard using `git ls-remote --exit-code`, FF step with `continue-on-error: true`, and `peter-evans/create-pull-request@v6` PR fallback. YAML validates cleanly with PyYAML. `actionlint` not available in this environment (noted per task spec). No existing workflow files modified.
