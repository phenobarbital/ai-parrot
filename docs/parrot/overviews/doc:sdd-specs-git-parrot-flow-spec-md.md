---
type: Wiki Overview
title: 'Feature Specification: Git Parrot Flow — Staging Branch and Sync Automation'
id: doc:sdd-specs-git-parrot-flow-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: AI-Parrot has outgrown the two-branch flow (`dev` ↔ `main`) that FEAT-145
---

---
# SDD flow type and base branch (FEAT-145).
# This spec is itself a feature flow that lands on dev.
type: feature
base_branch: dev
---

# Feature Specification: Git Parrot Flow — Staging Branch and Sync Automation

**Feature ID**: FEAT-187
**Date**: 2026-05-19
**Author**: Jesus Lara
**Status**: approved
**Target version**: tooling-only (no library version bump)

---

## 1. Motivation & Business Requirements

### Problem Statement

AI-Parrot has outgrown the two-branch flow (`dev` ↔ `main`) that FEAT-145
formalized. The current model has three structural gaps now that multiple
developers are landing work in parallel:

1. **No release-staging buffer.** Every merge to `dev` is implicitly a
   candidate for the next release. There is no branch where the team can
   freeze a release candidate, stabilize it, and let QA run against a
   stationary target without freezing all of `dev`. Releases today are
   "whatever happens to be on `dev` when we tag `main`."
2. **Hotfix dev-sync is manual.** `/sdd-done --sync-dev` requires a human
   to remember to run it after merging a hotfix PR into `main`. In
   practice this slips, and `dev` diverges from `main` until the next
   release exposes the gap. With a staging branch, the problem doubles
   (now both `dev` and `staging` must be re-synced after every hotfix).
3. **Feature → main escape hatch.** Some specs and proposals describe
   features that could "go to main or dev under request." This optionality
   creates inconsistency — features that bypassed `dev` cannot be diffed
   against the next release cleanly, and reviewers cannot rely on `dev`
   being the canonical integration branch.

The proposed *Git Parrot Flow* closes all three gaps in one coordinated
change:

- A long-lived `staging` branch sits between `dev` and `main`. It is cut
  from `dev` when the team decides to freeze a release, receives hotfix
  back-merges from `main` automatically, and ultimately PRs into `main`
  with the release tag.
- A single GitHub Action (`sync-down.yml`) listens for pushes to `main`
  and tries to fast-forward `staging` and `dev`. When fast-forward is
  not possible it opens a sync PR automatically. The manual
  `/sdd-done --sync-dev` fallback survives but stops being load-bearing.
- `feature` flows MUST base on `dev`. The only flow that touches `main`
  directly is `hotfix`. Releases happen via `staging → main` PRs and are
  an operational concern (not an SDD flow type).

### Goals

- Introduce `staging` as a recognised long-lived branch alongside `main`
  and `dev`. Document its lifecycle (cut from `dev`, sync from `main`,
  merge to `main` at release).
- Add a GitHub Action that auto-syncs `main → {staging, dev}` after every
  push to `main`. Fast-forward when possible; open a sync PR otherwise.
- Update every `.claude/commands/sdd-*.md` and `.claude/agents/sdd-worker.md`
  to recognise `staging` as a valid `base_branch` for `feature` flows
  (used for fixes discovered during a release freeze).
- Update `/sdd-done` so the hotfix dev-sync (currently `--sync-dev`) also
  propagates to `staging`. The flag becomes `--sync-down` (legacy alias
  preserved).
- Reaffirm that `feature` flows base on `dev` (or `staging` during a
  freeze) — NEVER `main`. Remove all "from main or dev under request"
  language from commands and docs.
- Document the release-cut procedure (cut `staging` from `dev`, PR
  `staging → main`, tag, sync-down) without adding a new SDD flow type.

### Non-Goals

- **No new SDD flow type for releases.** Releases are an operational
  step performed by a maintainer on `staging`, not a feature with tasks
  and a worktree. (Rejected: a hypothetical `type: release` flow would
  duplicate `feature` mechanics without adding value.)
- **No automatic release-cut command.** `/sdd-release-cut` is left as a
  follow-up; for now, cutting `staging` from `dev` is a documented git
  procedure. Mentioned in §8 as an open follow-up.
- **No removal of `--sync-dev`.** The flag is preserved as a legacy
  alias for `--sync-down` so existing muscle memory and any external
  docs keep working.
- **No support for hotfixes that branch from a release tag.** Hotfixes
  still branch from `main` HEAD (unchanged from FEAT-145).
- **No bidirectional sync.** The Action is one-way (`main → down`). The
  `dev → staging` direction is explicitly manual — it only happens at
  release-cut time, by a human.
- **Not touching the existing `release.yml` workflow.** That workflow
  publishes wheels on GitHub release events and is unrelated.

---

## 2. Architectural Design

### Overview

The flow has three long-lived branches and one Action:

```
                          (manual cut: git checkout staging; git merge dev)
        ┌───────────────────────────────────────────────────────┐
        ▼                                                       │
  ┌──────────┐                                              ┌────────┐
  │  main    │◄──── PR (release) ──── staging ◄──── (cut) ──│  dev   │
  │  (tags)  │                          ▲                   │        │
  └────┬─────┘                          │                   └────▲───┘
       │                                │                        │
       │ push event                     │ sync-down.yml          │
       │   ─────────────────────────────┴────────────────────────┘
       │                       (FF or sync-PR)
       │
   sync-down.yml on push to main:
     1. Fetch all branches
     2. Try `git push --ff-only origin staging` (server-side FF)
     3. If FF fails → open PR `chore/sync-main-into-staging-<sha>` → staging
     4. Repeat steps 2-3 for dev
```

`hotfix` flows branch from `main`, PR into `main`, then the Action
propagates the change down to `staging` and `dev` without human action.
`feature` flows branch from `dev` (or `staging` during a release freeze)
and merge back into their base.

### Component Diagram

```
brainstorm.md ──┐
proposal.md   ──┤── frontmatter (type, base_branch)
spec.md       ──┘                │
                                 ▼
                  scripts/sdd/sdd_meta.py  ── extended: KNOWN_BRANCHES = {main, staging, dev}
                                 │
       ┌─────────────────────────┼────────────────────────────┐
       ▼                         ▼                            ▼
  /sdd-spec, /sdd-task     /sdd-done                  sdd-worker agent
  pull base_branch         hotfix → push +            same flow as
  (now accepts staging)    sync-down to {staging,     commands
                           dev}                       (no new logic)
                                 │
                                 │  triggers (out-of-band)
                                 ▼
                .github/workflows/sync-down.yml
                  on: push to main
                  → ff staging; pr-fallback if not
                  → ff dev;     pr-fallback if not
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `.claude/commands/sdd-done.md` | rewrite §1, §9, §9.5 | Sync-down now hits `staging` + `dev`; rename flag, keep legacy alias |
| `.claude/commands/sdd-spec.md` | minor edit | Accept `staging` as a valid `base_branch` for feature flows; doc the freeze-window use case |
| `.claude/commands/sdd-task.md` | minor edit | Same — accept `staging` base_branch |
| `.claude/commands/sdd-start.md` | unchanged | Already honours `base_branch` from frontmatter |
| `.claude/commands/sdd-brainstorm.md` | minor edit | Clarify type question: features → dev (or staging during freeze); hotfixes → main. Drop "from main under request" language |
| `.claude/commands/sdd-proposal.md` | minor edit | Same as brainstorm |
| `.claude/agents/sdd-worker.md` | minor edit | Mention staging as an allowed base; otherwise unchanged |
| `scripts/sdd/sdd_meta.py` | additive | Add `KNOWN_BRANCHES: frozenset = {"main", "staging", "dev"}` constant for command-side warning when `base_branch` is outside this set |
| `sdd/WORKFLOW.md` | rewrite "Git Configuration" + add "Release Cut" section | Document staging lifecycle |
| `CLAUDE.md` | rewrite "Git Configuration" / "SDD Workflow & Worktree Policy" | Same |
| `.github/workflows/sync-down.yml` | **NEW** | Auto-sync `main → {staging, dev}` |

### Data Models

No schema change to `FlowMeta` — `type` remains `Literal["feature", "hotfix"]`
and `base_branch: str` already accepts any string. The new contract is
purely conventional:

- `type: feature, base_branch: dev` — default feature flow (unchanged).
- `type: feature, base_branch: staging` — fix discovered during a release
  freeze. Allowed; not flagged.
- `type: feature, base_branch: main` — **NOT ALLOWED**. Commands warn and
  refuse.
- `type: hotfix, base_branch: main` — only valid hotfix config (unchanged).

A small additive constant in `sdd_meta.py` documents the canonical set:

```python
KNOWN_BRANCHES: frozenset[str] = frozenset({"main", "staging", "dev"})
```

Commands use this for a warning ("`base_branch=<x>` is not one of
`main`, `staging`, `dev` — continuing anyway") rather than a hard
refusal, so sub-feature branches remain possible per CLAUDE.md.

### New Public Interfaces

The only new artifact is the GitHub Action workflow file:

```yaml
# .github/workflows/sync-down.yml
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
      - name: Fast-forward ${{ matrix.target }}
        id: ff
        continue-on-error: true
        run: |
          git fetch origin
          git checkout ${{ matrix.target }}
          git merge --ff-only origin/main
          git push origin ${{ matrix.target }}
      - name: Open sync PR if FF failed
        if: steps.ff.outcome == 'failure'
        uses: peter-evans/create-pull-request@v6
        with:
          base: ${{ matrix.target }}
          branch: chore/sync-main-into-${{ matrix.target }}-${{ github.sha }}
          title: "chore: sync main into ${{ matrix.target }}"
          body: |
            Automated sync from `main` (after merge of ${{ github.event.head_commit.message }}).
            Fast-forward to `${{ matrix.target }}` was not possible — please
            review and merge to keep `${{ matrix.target }}` aligned with `main`.
```

The exact body is in §5 acceptance criteria; the snippet above is the
shape.

---

## 3. Module Breakdown

The work is grouped into six modules. The Worktree Strategy below explains
why this is per-spec sequential.

### Module 1: `sdd_meta` additive constant
- **Path**: `scripts/sdd/sdd_meta.py`
- **Responsibility**: Add `KNOWN_BRANCHES: frozenset = frozenset({"main", "staging", "dev"})`. Export it. No behavioural change to `parse()` or `FlowMeta`.
- **Depends on**: nothing.
- **Tested by**: `tests/scripts/test_sdd_meta.py` (extend existing test file with a single import/equality test).

### Module 2: `sync-down.yml` GitHub Action
- **Path**: `.github/workflows/sync-down.yml`
- **Responsibility**: On every push to `main`, fast-forward `staging` and `dev`. If FF is not possible (the target branch has diverged), open a sync PR via `peter-evans/create-pull-request@v6` against the target. Matrix job so `staging` and `dev` are independent — one can FF while the other opens a PR.
- **Depends on**: `staging` branch existing on the remote. The Action must skip gracefully when the target branch does not exist (first run before `staging` is cut). See §7 Known Risks.
- **Tested by**: GitHub Actions native run — a synthetic `main` push (test via a throwaway commit). Documented in §4.

### Module 3: `/sdd-done` sync-down refactor
- **Path**: `.claude/commands/sdd-done.md`
- **Responsibility**:
  - Rename `--sync-dev` to `--sync-down`. Preserve `--sync-dev` as a deprecated alias that prints a one-line deprecation notice and proceeds.
  - Step 9.5 (currently "Hotfix → Dev Sync") becomes "Hotfix → Sync-down" and propagates the hotfix to BOTH `staging` and `dev` using the same optimistic-FF / safe-abort pattern as today, in that order. On conflict for either target, abort the merge for THAT target and continue with the other; print actionable resolution commands for the failed target.
  - Document that `--sync-down` is mostly a fallback now — the Action handles it in the common case. The flag is for offline / aborted-Action workflows.
- **Depends on**: Module 1 (constant), Module 2 (Action exists, so the manual fallback can reference it in messages).

### Module 4: Feature-base validation across SDD commands
- **Paths**:
  - `.claude/commands/sdd-spec.md`
  - `.claude/commands/sdd-task.md`
  - `.claude/commands/sdd-brainstorm.md`
  - `.claude/commands/sdd-proposal.md`
  - `.claude/agents/sdd-worker.md`
- **Responsibility**:
  - Where the command currently allows `base_branch: <any string>`, add a warning when `base_branch == "main"` and `type == "feature"`: features MUST NOT base on `main` (use `hotfix` instead). Abort with a clear message.
  - Drop any prose that says features can land on `main`. The only places this currently exists (per grep) are `sdd-brainstorm.md:46-60` and CLAUDE.md's "When NOT to Use Worktrees" section.
  - Add a one-line note that `staging` is a valid `base_branch` during a release freeze.
- **Depends on**: Module 1 for the canonical branch set (used in warning text).

### Module 5: Documentation refresh
- **Paths**:
  - `sdd/WORKFLOW.md`
  - `CLAUDE.md`
- **Responsibility**:
  - Replace the "Git Configuration" block in `CLAUDE.md` with the three-branch flow: `main` (tagged releases), `staging` (release candidates), `dev` (integration).
  - Add a "Release Cut" section to `sdd/WORKFLOW.md` documenting the manual procedure: when the team decides to freeze, a maintainer runs `git checkout staging && git merge --ff-only dev && git push`. From that moment on, `staging` is the release candidate; new feature work continues on `dev`.
  - Document the Action's behaviour and the fallback (`/sdd-done --sync-down`).
- **Depends on**: Modules 1–4 (documents what was built).

### Module 6: Acceptance check
- **Path**: `tests/sdd/test_git_parrot_flow.py` (new) or extension of an existing harness.
- **Responsibility**:
  - Smoke-test the Action workflow file with `actionlint` (or its Python equivalent — see §7) to catch YAML/syntax errors before push.
  - Lightweight pytest that asserts: every `.claude/commands/sdd-*.md` and `.claude/agents/sdd-worker.md` mentions `staging` at least once (regression guard so the docs refresh isn't silently reverted).
- **Depends on**: Modules 1–5.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_known_branches_contains_main_staging_dev` | Module 1 | Importing `KNOWN_BRANCHES` from `scripts.sdd.sdd_meta` yields `{"main", "staging", "dev"}` |
| `test_known_branches_is_frozenset` | Module 1 | `KNOWN_BRANCHES` is immutable (frozenset, not set) |
| `test_flowmeta_feature_main_still_parses` | Module 1 | Parser does NOT block `type: feature, base_branch: main` at the schema layer; the warning lives in commands, not the model |
| `test_commands_mention_staging` | Module 6 | Every `sdd-*.md` command file and the `sdd-worker.md` agent file contains the literal string `staging` |

### Integration Tests

| Test | Description |
|---|---|
| `actionlint_sync_down_yml` | Run `actionlint` (or `python -m yaml` + manual schema check if actionlint is unavailable) on `.github/workflows/sync-down.yml` — must exit 0 |
| `sync-down ff path (manual)` | Push a trivial commit to `main` on a test branch; observe the Action FF-update `staging` and `dev` on the next CI run |
| `sync-down PR path (manual)` | Make `dev` and `main` diverge by one commit on each; push to `main`; observe the Action open a sync PR for `dev` |
| `sdd_done_sync_down_legacy_alias` | Run `/sdd-done <FEAT> --sync-dev` on a hotfix; verify it prints a deprecation notice and behaves identically to `--sync-down` |

### Test Data / Fixtures

```python
# tests/sdd/conftest.py
@pytest.fixture
def all_sdd_command_files() -> list[Path]:
    """Return paths to every .claude/commands/sdd-*.md and the sdd-worker agent."""
    root = Path(__file__).resolve().parents[1]
    return [
        *root.glob(".claude/commands/sdd-*.md"),
        root / ".claude/agents/sdd-worker.md",
    ]
```

---

## 5. Acceptance Criteria

This feature is complete when ALL of the following are true:

- [ ] `scripts/sdd/sdd_meta.py` exports `KNOWN_BRANCHES = frozenset({"main", "staging", "dev"})`.
- [ ] `tests/scripts/test_sdd_meta.py` includes a passing test for the new constant.
- [ ] `.github/workflows/sync-down.yml` exists, validates with `actionlint` (or a documented equivalent), and uses a matrix over `[staging, dev]` with continue-on-error on the FF step and a `peter-evans/create-pull-request@v6` fallback on FF failure.
- [ ] The Action handles a missing target branch gracefully: if `origin/staging` does not exist, that matrix leg logs a skip and does NOT fail the workflow.
- [ ] `/sdd-done --sync-down` propagates a merged hotfix to BOTH `staging` and `dev` using the existing optimistic-FF / safe-abort pattern, in that order, with independent failure recovery per target.
- [ ] `/sdd-done --sync-dev` still works as a deprecated alias for `--sync-down` and prints a one-line deprecation notice.
- [ ] Every `.claude/commands/sdd-*.md` file and `.claude/agents/sdd-worker.md` either rejects `type: feature, base_branch: main` or contains no language permitting it.
- [ ] `.claude/commands/sdd-brainstorm.md` lines 46–60 (the type-question block) no longer offer `main` as a feature base; staging is mentioned as the release-freeze base.
- [ ] `CLAUDE.md` "Git Configuration" section documents the three-branch model: `main` (tagged releases), `staging` (RC), `dev` (integration).
- [ ] `sdd/WORKFLOW.md` contains a new "Release Cut" section with the manual procedure.
- [ ] `tests/sdd/test_git_parrot_flow.py` (or an existing test) asserts every SDD command file mentions `staging`.
- [ ] No `.github/workflows/release.yml` changes (out of scope; regression guard).

---

## 6. Codebase Contract

> **Anti-Hallucination Anchor.** Every entry below was verified by reading
> the file or running the command on 2026-05-19.

### Verified Existing Files (to be modified)

| Path | Lines | Purpose |
|---|---|---|
| `.claude/commands/sdd-done.md` | 459 | Feature/hotfix closing command — primary surface for this refactor |
| `.claude/commands/sdd-spec.md` | 294 | Spec scaffolding — needs minor staging-aware edit |
| `.claude/commands/sdd-task.md` | 202 | Task decomposition — needs minor staging-aware edit |
| `.claude/commands/sdd-brainstorm.md` | 198 | Asks the type question (lines 46–60) — needs prose cleanup |
| `.claude/commands/sdd-proposal.md` | 484 | Same prose cleanup |
| `.claude/commands/sdd-start.md` | 225 | No change expected; verified `base_branch` is consumed from frontmatter |
| `.claude/agents/sdd-worker.md` | 289 | Minor: mention staging in §0 sync block |
| `scripts/sdd/sdd_meta.py` | (verified ~85 lines) | Add `KNOWN_BRANCHES` constant |
| `sdd/WORKFLOW.md` | 242 | Document staging and release cut |
| `CLAUDE.md` | 304 | "Git Configuration" block needs rewrite |

### Existing Schema Reference

`scripts/sdd/sdd_meta.py:18-27` (verified):
```python
class FlowMeta(BaseModel):
    type: Literal["feature", "hotfix"]
    base_branch: str

    @model_validator(mode="after")
    def _hotfix_implies_main(self) -> "FlowMeta":
        if self.type == "hotfix" and self.base_branch != "main":
            raise ValueError(...)
        return self
```

No change to this model is needed — `base_branch: str` already accepts
`"staging"`. Module 1 is purely additive.

### Existing Workflow Patterns

`.claude/commands/sdd-done.md:6-8` (verified):
> **This command runs on the spec's `base_branch`** — read from the spec's
> YAML frontmatter (FEAT-145). For `type: feature` that is `dev` (default);
> for `type: hotfix` that is `main`.

The new prose adds: "or `staging`, when fixing an issue discovered during
a release freeze."

`.claude/commands/sdd-done.md:201-237` (verified — the §9.5 "Hotfix → Dev
Sync" block) is the surface area Module 3 rewrites. The optimistic-FF /
safe-abort pattern stays; only the target list expands from `[dev]` to
`[staging, dev]`.

`.github/workflows/` (verified):
- `ci.yml` (32+ lines, triggers on push to main/dev and PRs to main/dev)
- `codeql-analysis.yml` (security scan)
- `release.yml` (publishes wheels on release event)

None of these workflows touch branch synchronisation — Module 2's
`sync-down.yml` is a wholly new workflow with no overlap.

### Does NOT Exist (Anti-Hallucination)

- ~~`origin/staging`~~ — branch does NOT exist on remote yet. Module 2's
  Action must handle this gracefully (skip target, log, do not fail).
  Operator action item: cut `staging` from `dev` BEFORE merging this
  spec's branch, so the first push to `main` after merge has a valid
  target. Captured in §7 Known Risks.
- ~~`type: release` flow type~~ — not introduced. `FlowMeta.type` remains
  `Literal["feature", "hotfix"]`.
- ~~`/sdd-release-cut` command~~ — not introduced in this spec. See §8.
- ~~`peter-evans/create-pull-request` dependency~~ — not in any existing
  workflow. Added only in `sync-down.yml`. Pinned to `@v6`.
- ~~`KNOWN_BRANCHES` constant in `sdd_meta.py`~~ — does not exist yet;
  added by Module 1.
- ~~Bidirectional auto-sync (`dev → staging` automatic)~~ — explicitly
  rejected. Documented in §1 Non-Goals.

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `sync-down.yml` | `main` push event | `on: push: branches: [main]` | Pattern reference: `ci.yml:5-7` |
| `sync-down.yml` PR-fallback | `peter-evans/create-pull-request@v6` | GitHub Marketplace action, pinned by major | Pin convention matches `actions/checkout@v4` in `ci.yml:14` |
| `KNOWN_BRANCHES` | `sdd_meta.py` module-level export | `from scripts.sdd.sdd_meta import KNOWN_BRANCHES` | New export, additive |
| `/sdd-done --sync-down` | `staging` AND `dev` | Two iterations of the §9.5 optimistic-FF block | Pattern at `sdd-done.md:209-237` |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Action permissions are explicit.** `sync-down.yml` declares
  `permissions: contents: write, pull-requests: write`. Never use a
  PAT — the default `GITHUB_TOKEN` is sufficient for cross-branch FF
  and PR creation in the same repo.
- **Matrix with `fail-fast: false`.** When one target leg fails, the
  other must still run. `staging` lagging is independent of `dev`
  lagging.
- **PR titles include the source SHA.** `chore/sync-main-into-<target>-<sha>`.
  This prevents two consecutive failed FFs from colliding on the same
  PR branch name.
- **Deprecation, not removal.** `--sync-dev` becomes an alias. Plan to
  remove in a follow-up spec ~90 days after this one ships, after
  external docs/scripts have had time to migrate.
- **Documentation parity.** Any prose change in `CLAUDE.md` MUST have a
  matching update in `sdd/WORKFLOW.md` and vice versa. The two are read
  together by Claude Code sessions and human contributors alike.

### Known Risks / Gotchas

- **First-run race: `staging` does not exist yet.** Until a maintainer
  cuts `staging` from `dev` manually, the `staging` matrix leg of the
  Action will fail at the `git checkout staging` step. The Action MUST
  catch this case and exit 0 with a log message — otherwise every push
  to `main` will spam failure notifications. Implementation hint: prefix
  the FF step with `git ls-remote --exit-code --heads origin staging || { echo "::notice::staging branch not yet created; skipping"; exit 0; }`.
- **PR loop hazard.** If `dev` cannot FF, the Action opens a sync PR. If

…(truncated)…
