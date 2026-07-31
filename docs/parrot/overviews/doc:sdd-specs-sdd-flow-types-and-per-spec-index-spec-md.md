---
type: Wiki Overview
title: 'Feature Specification: SDD Flow Types and Per-Spec Index'
id: doc:sdd-specs-sdd-flow-types-and-per-spec-index-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'The current SDD tooling has two structural defects:'
---

# Feature Specification: SDD Flow Types and Per-Spec Index

**Feature ID**: FEAT-145
**Date**: 2026-05-05
**Author**: Jesus Lara
**Status**: approved
**Target version**: tooling-only (no library version bump)

---

## 1. Motivation & Business Requirements

### Problem Statement

The current SDD tooling has two structural defects:

1. **Monolithic `sdd/tasks/.index.json` causes merge conflicts.** All features
   share a single ~15.850-line JSON file. Even with the documented "code in
   worktree, state on dev" discipline, the file has already shown corruption
   (commit `b4be02dc — sdd: fix index JSON corruption`) and feature ID
   collisions (two distinct specs both labelled `FEAT-142`). The monolith
   amplifies any procedural slip into a real conflict.

2. **The integration branch is hardcoded to `dev`.** `/sdd-task` warns and
   refuses to run if not on `dev`; `/sdd-start` and `/sdd-done` switch to
   `dev` to write state; `sdd-worker` assumes `dev`. There is no path to
   author a hotfix that branches from `main`. The branch name (`feat/` vs
   `fix/`) is the only signal of intent — there is no formal flow type.

### Goals

- Replace the monolithic index with one file per spec at
  `sdd/tasks/index/<feature-name>.json`. Two parallel features touch
  disjoint files and never collide on merge.
- Introduce explicit flow types — `feature` (default base `dev`) and
  `hotfix` (always base `main`) — declared via YAML frontmatter on the
  spec/brainstorm/proposal documents.
- Parameterise every SDD command and the `sdd-worker` agent so the base
  branch is read from frontmatter, not hardcoded.
- Enforce that `/sdd-done` never opens a PR or pushes to `main`. For
  hotfixes, `/sdd-done` keeps `dev` in sync with the hotfix changes.
- Pull the base branch before scaffolding a spec or generating tasks so
  the local working copy is not stale relative to `origin`.
- Preserve historical work: every entry under the current
  `previous_features` registry plus the active feature must round-trip
  into its own per-spec index file.

### Non-Goals

- Not switching to a filesystem-derived index (rejected: option B from the
  design discussion). Status remains stored explicitly in JSON.
- Not moving the index outside the repo (rejected: option D). The index
  remains versioned.
- Not changing the task file format or the `sdd/tasks/{active,completed}/`
  directory layout. Tasks are unchanged.
- Not retroactively rewriting existing `.spec.md` files to add frontmatter.
  Specs without frontmatter default to `type: feature`, `base_branch: dev`.
- Not supporting hotfixes branched from a release tag — `type: hotfix`
  always means `main` HEAD.

---

## 2. Architectural Design

### Overview

The refactor adds three orthogonal capabilities and rewires every SDD
command to consume them:

1. **Frontmatter** (YAML) at the head of brainstorm / proposal / spec
   documents declares `type` and `base_branch`. A small shared parser
   library in `scripts/sdd/sdd_meta.py` reads, validates, and (when the
   document lacks frontmatter) returns sensible defaults.

2. **Per-spec index** files live at `sdd/tasks/index/<feature-name>.json`
   (kebab-case slug, identical to the `.spec.md` filename stem). The
   schema is the current monolithic schema *minus* `previous_features`,
   plus two header fields (`type`, `base_branch`) cached from the spec
   frontmatter for fast reads. Tasks remain in
   `sdd/tasks/{active,completed}/` exactly as today — only the index
   moves.

3. **Branch routing** is computed per command from the spec's
   frontmatter. `feature` flows operate against `base_branch` (default
   `dev`). `hotfix` flows operate against `main`. Worktrees still
   branch from HEAD as documented in `CLAUDE.md`, but `/sdd-spec` and
   `/sdd-task` now ensure HEAD is on the correct base before they run.

A non-obvious benefit emerges: with per-spec indexes, a worktree can
safely write its own index file directly. Two parallel feature
worktrees touch different paths in `sdd/tasks/index/`. The "switch
back to dev to update state" pattern in `/sdd-start` and `sdd-worker`
becomes optional — the merge in `/sdd-done` brings the per-spec index
along with the code, with no conflict surface. We exploit this to
simplify the agent and command flow.

### Component Diagram

```
brainstorm.md ──┐
proposal.md   ──┤── frontmatter (type, base_branch) ──┐
spec.md       ──┘                                     │
                                                      ▼
                                        scripts/sdd/sdd_meta.py
                                        (parse + validate + defaults)
                                                      │
       ┌──────────────────────────────────────────────┤
       ▼                ▼              ▼              ▼
  /sdd-spec        /sdd-task      /sdd-start     /sdd-done
  pull base        pull base      worktree       merge to base
  scaffold spec    write index    writes own     enforce no main PR
                   per-spec       index file     hotfix → sync dev
                                                      │
       ┌──────────────────────────────────────────────┤
       ▼                ▼                             ▼
  /sdd-next        /sdd-status                  sdd-worker agent
  scan glob        scan glob                    same flow as commands
  index/*.json     index/*.json                 reads frontmatter
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `.claude/commands/sdd-spec.md` | rewrite §1, add §6 | Read/emit frontmatter; pull base_branch |
| `.claude/commands/sdd-task.md` | rewrite §1 + §4–§5 | Read frontmatter; write per-spec index |
| `.claude/commands/sdd-start.md` | rewrite §3–§4, §8 | Read per-spec index; honour base_branch |
| `.claude/commands/sdd-done.md` | rewrite §1, §7–§9 | Per-spec index; enforce no-main-PR; hotfix dev-sync |
| `.claude/commands/sdd-next.md` | rewrite §1 | Glob `sdd/tasks/index/*.json` |
| `.claude/commands/sdd-status.md` | rewrite §1–§2 | Glob `sdd/tasks/index/*.json` |
| `.claude/commands/sdd-brainstorm.md` | minor edit | Emit frontmatter; ask for type when ambiguous |
| `.claude/commands/sdd-proposal.md` | minor edit | Emit frontmatter |
| `.claude/commands/sdd-fromjira.md` | minor edit | Emit frontmatter on generated brainstorm |
| `.claude/commands/sdd-tojira.md` | unchanged | Reads spec metadata; frontmatter is additive |
| `.claude/agents/sdd-worker.md` | rewrite §0–§3, §g | Read per-spec index; honour base_branch |
| `sdd/templates/spec.md` | extend | Add YAML frontmatter block at the top |
| `sdd/templates/brainstorm.md` | extend | Add YAML frontmatter block |
| `sdd/templates/proposal.md` | extend | Add YAML frontmatter block |
| `sdd/WORKFLOW.md` | rewrite "Task Index Schema" + flow sections | Document new model |
| `CLAUDE.md` | minor edit | Update SDD Workflow section + flow types |

### Data Models

#### Frontmatter (YAML, mandatory on new docs)

```yaml
---
type: feature        # one of: feature | hotfix
base_branch: dev     # for feature: any branch; for hotfix: must be "main"
---
```

#### Per-spec index file (`sdd/tasks/index/<feature>.json`)

```json
{
  "feature": "<feature-slug>",
  "feature_id": "FEAT-<NNN>",
  "spec": "sdd/specs/<feature-slug>.spec.md",
  "type": "feature",
  "base_branch": "dev",
  "created_at": "<ISO-8601>",
  "completed_at": null,
  "tasks": [
    {
      "id": "TASK-<NNN>",
      "slug": "<slug>",
      "title": "<title>",
      "feature_id": "FEAT-<NNN>",
      "feature": "<feature-slug>",
      "spec": "sdd/specs/<feature-slug>.spec.md",
      "status": "pending",
      "priority": "high|medium|low",
      "effort": "S|M|L|XL",
      "depends_on": [],
      "parallel": false,
      "parallelism_notes": "...",
      "assigned_to": null,
      "started_at": null,
      "completed_at": null,
      "file": "sdd/tasks/active/TASK-<NNN>-<slug>.md"
    }
  ]
}
```

Schema is identical to the current per-task entry in `tasks[]`, with two
extra header fields (`type`, `base_branch`) and `completed_at` to enable
fast "is this feature fully done" queries by `/sdd-status` and `/sdd-done`.

#### Orphan bucket (`sdd/tasks/index/_orphans.json`)

Same schema as a regular per-spec index, with:
- `feature: "_orphans"`
- `feature_id: null`
- `spec: null`
- `type: "feature"` (default), `base_branch: "dev"` (default)
- `tasks[]`: tasks the migration script could not attribute to any
  feature in the source monolith.

The migration script emits a stderr warning per orphaned task. Orphans
are never picked up by `/sdd-next` (filter: `feature_id != null`).

### New Public Interfaces

`scripts/sdd/sdd_meta.py` — small Python utility consumed by every
command via `python -m`:

```python
class FlowMeta(BaseModel):
    type: Literal["feature", "hotfix"]
    base_branch: str

def parse(doc_path: Path) -> FlowMeta:
    """Parse YAML frontmatter from a brainstorm/proposal/spec.

    Returns FlowMeta(type="feature", base_branch="dev") if no
    frontmatter is present (backwards-compat for in-flight specs).

    Raises ValidationError when frontmatter is present but invalid
    (e.g. type=hotfix with base_branch != "main").
    """
```

`scripts/sdd/migrate_index.py` — one-shot migration script
(executable). Reads `sdd/tasks/.index.json`, writes per-spec files
into `sdd/tasks/index/`, emits a report, leaves the source untouched.

---

## 3. Module Breakdown

The work is grouped into nine modules. The Worktree Strategy below
explains why this is per-spec sequential.

### Module 1: Frontmatter helper (`sdd_meta`)
- **Path**: `scripts/sdd/sdd_meta.py` and `scripts/sdd/__init__.py`
- **Responsibility**: Parse YAML frontmatter from any of brainstorm /
  proposal / spec markdown. Validate `type` and `base_branch`. Return
  `FlowMeta` with documented defaults when no frontmatter is present.
- **Depends on**: pyyaml (already in tree), pydantic (already in tree).
- **Tested by**: `tests/scripts/test_sdd_meta.py`.

### Module 2: Migration script
- **Path**: `scripts/sdd/migrate_index.py`
- **Responsibility**: Read `sdd/tasks/.index.json`, group tasks by
  `feature_id`/`feature`, write `sdd/tasks/index/<feature>.json` per
  group. Tasks without a resolvable feature go to `_orphans.json`.
  Idempotent (re-running with the same input produces the same output).
  Does NOT delete the source monolith — that is a manual final step.
- **Depends on**: Module 1 (writes default frontmatter values into
  per-spec index headers).
- **Tested by**: `tests/scripts/test_migrate_index.py` with a fixture
  derived from the real monolith.

### Module 3: Template extensions
- **Paths**:
  - `sdd/templates/spec.md`
  - `sdd/templates/brainstorm.md`
  - `sdd/templates/proposal.md`
- **Responsibility**: Add the YAML frontmatter block at the very top of
  each template, with placeholders and inline guidance. The existing
  body (markdown headings, `**Feature ID**:` line, etc.) is unchanged.

### Module 4: Generation commands (frontmatter emission)
- **Paths**:
  - `.claude/commands/sdd-brainstorm.md`
  - `.claude/commands/sdd-proposal.md`
  - `.claude/commands/sdd-spec.md`
  - `.claude/commands/sdd-fromjira.md`
- **Responsibility**:
  - `sdd-brainstorm` and `sdd-proposal`: ask the user during the
    discovery rounds whether this is a `feature` or `hotfix`; default
    to `feature` if not asked. Emit frontmatter at the top of the
    generated document. Hotfix → set `base_branch: main`.
  - `sdd-spec`: read frontmatter from the brainstorm if present and
    carry it forward; otherwise ask once during clarifying questions.
    Before scaffolding, run `git checkout <base_branch>` followed by
    `git pull origin <base_branch>` (warn-and-skip if working tree
    dirty). For `type: hotfix`, validate `base_branch == "main"` and
    refuse otherwise.
  - `sdd-fromjira`: emit frontmatter (default `feature`/`dev`) on the
    generated brainstorm and let the user adjust before `/sdd-spec`.
- **Depends on**: Module 1.

### Module 5: Decomposition + start commands
- **Paths**:
  - `.claude/commands/sdd-task.md`
  - `.claude/commands/sdd-start.md`
- **Responsibility**:
  - `sdd-task`: drop the "must be on dev" check; instead read the spec's
    frontmatter, switch to `<base_branch>`, pull, then generate. Write
    the per-spec index at `sdd/tasks/index/<feature>.json`. Stage only
    that file and the new `TASK-*.md` files.
  - `sdd-start`: read tasks from
    `sdd/tasks/index/<feature>.json` (resolved from the task file's
    `**Feature**:` header). Update the per-spec index in the *current
    location* (worktree or main repo) — no more `cd $REPO_ROOT &&
    git checkout dev` dance. The merge in `sdd-done` brings the index
    file along with the code naturally.
- **Depends on**: Modules 1, 2, 3.

### Module 6: Closing command (`sdd-done`)
- **Path**: `.claude/commands/sdd-done.md`
- **Responsibility**:
  - Read frontmatter via Module 1 to determine the flow type.
  - Hard-block any path that would open a PR against `main` or push to
    `main` directly. For hotfixes, push the hotfix branch and print a
    `gh pr create --base main` snippet for the user to run manually.
  - For `type: hotfix`, after the user has merged the PR into `main`
    externally (verified by `git fetch origin && git merge-base --is-
    ancestor hotfix-<slug> origin/main`), perform the dev-sync:
    optimistic `git checkout dev && git merge hotfix-<slug>`. On
    conflict, run `git merge --abort` and print a message instructing
    the user to resolve manually. (Decision 4c from the design
    discussion.)
  - For `type: feature`, behave as today: merge into `base_branch`,
    push it, no main involvement.
- **Depends on**: Module 1.

### Module 7: Read-only commands
- **Paths**:
  - `.claude/commands/sdd-next.md`
  - `.claude/commands/sdd-status.md`
- **Responsibility**: Replace `read sdd/tasks/.index.json` with
  `glob sdd/tasks/index/*.json` and aggregate. Skip
  `_orphans.json` from the unblocked-tasks suggestion in `/sdd-next`.
  `/sdd-status` shows orphans in a final "Unowned tasks" panel so they
  remain visible.
- **Depends on**: Module 2 (output schema).

### Module 8: Agent (`sdd-worker`)
- **Path**: `.claude/agents/sdd-worker.md`
- **Responsibility**:
  - Replace the "code in worktree, state on dev" cardinal rule with
    "code AND per-spec index live in the worktree; merge brings them
    together on /sdd-done".
  - Step 1 (Resolve the Feature) reads `sdd/tasks/index/<feature>.json`
    instead of the monolith.
  - Step 2 (Mark in-progress) updates the per-spec index in-place
    (worktree or repo, whichever is current).
  - Step 3 (Create the Worktree) honours `base_branch` from frontmatter.
  - Step g (Update SDD State) drops the cd-back-to-dev dance — commit
    in the worktree alongside the code commit.
- **Depends on**: Modules 1, 2, 3, 5.

### Module 9: Documentation
- **Paths**:
  - `sdd/WORKFLOW.md` — new "Task Index Schema" + flow types section
  - `CLAUDE.md` — replace the "Worktree Policy" / "SDD Auto-Commit Rule"
    sections with the new flow-aware rules
- **Responsibility**: Document the new model so future contributors and
  Claude sessions don't re-introduce the old assumptions.
- **Depends on**: Modules 1–8 (documents the result).

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_parse_no_frontmatter_returns_defaults` | Module 1 | Parsing a doc without frontmatter returns `FlowMeta(type="feature", base_branch="dev")` |
| `test_parse_feature_with_dev_base` | Module 1 | Standard feature frontmatter parses correctly |
| `test_parse_hotfix_requires_main` | Module 1 | `type: hotfix` with `base_branch: dev` raises validation error |
| `test_parse_unknown_type_rejected` | Module 1 | Bad `type` value raises validation error |
| `test_migrate_groups_by_feature_id` | Module 2 | Tasks with same `feature_id` land in one per-spec index |
| `test_migrate_handles_previous_features` | Module 2 | Each `previous_features[]` entry produces its own index file |
| `test_migrate_orphans_unattributable_tasks` | Module 2 | Tasks without resolvable feature go to `_orphans.json` with stderr warning |
| `test_migrate_idempotent` | Module 2 | Running twice produces identical output |
| `test_migrate_does_not_delete_source` | Module 2 | Source `.index.json` is preserved |

### Integration Tests (manual, scripted as `tests/sdd/`)

| Test | Description |
|---|---|
| `parallel_features_no_conflict` | Two simulated worktrees update their own per-spec index; merge into base produces no conflicts. |
| `hotfix_blocks_main_push_in_done` | `/sdd-done` for a `type: hotfix` spec refuses to push to `main`; emits `gh pr create` snippet. |
| `hotfix_dev_sync_clean` | After hotfix lands in `main`, `/sdd-done` merges it into `dev` cleanly. |
| `hotfix_dev_sync_conflict_aborts` | Same with a conflicting change on `dev` — `merge --abort` runs and an actionable message is printed. |

### Test Data / Fixtures

```python
# tests/scripts/conftest.py
@pytest.fixture
def monolith_index_fixture(tmp_path):
    """A minimal monolithic .index.json with one current feature plus
    two previous_features and one orphan task."""
    return tmp_path / "fixture.index.json"
```

A real-data smoke test reads the actual `sdd/tasks/.index.json` via a
read-only fixture path, asserts the migration produces a non-empty
`sdd/tasks/index/` and a valid `_orphans.json` (possibly empty).

---

## 5. Acceptance Criteria

This feature is complete when ALL of the following are true:

- [ ] `scripts/sdd/sdd_meta.py` exists, has 100% branch coverage in
      `tests/scripts/test_sdd_meta.py`, and is importable as
      `from scripts.sdd.sdd_meta import FlowMeta, parse`.
- [ ] `scripts/sdd/migrate_index.py` runs to completion against the
      current `sdd/tasks/.index.json`, produces one file per feature
      under `sdd/tasks/index/`, and is idempotent.
- [ ] `tests/scripts/test_migrate_index.py` passes with a synthetic
      monolith fixture covering current feature, previous_features,
      and orphans.
- [ ] `sdd/templates/spec.md`, `brainstorm.md`, `proposal.md` start with
      a YAML frontmatter block.
- [ ] Every `.claude/commands/sdd-*.md` file documents the
      frontmatter-aware behaviour described in the matching module.
- [ ] `.claude/agents/sdd-worker.md` no longer references
      `sdd/tasks/.index.json` (monolith) or `git checkout dev` for
      state updates; it reads per-spec indexes and updates them in
      the worktree.
- [ ] A new spec with `type: hotfix` causes `/sdd-spec` to refuse if
      not on `main` (or to switch+pull).
- [ ] A new spec with `type: feature` and `base_branch: dev` produces
      the same end-to-end behaviour as today (modulo the index file
      location).
- [ ] `/sdd-done` for `type: feature` merges into `dev` and never
      touches `main`.
- [ ] `/sdd-done --resolve-jira` for `type: hotfix` refuses to merge
      into `main` and prints a manual `gh pr create --base main`
      reminder.
- [ ] `/sdd-done` for `type: hotfix` after the PR has merged auto-syncs
      `dev` cleanly when no conflict, and aborts cleanly with an
      actionable message when there is a conflict.
- [ ] `/sdd-next` and `/sdd-status` produce equivalent output to the
      pre-migration behaviour for the same task data.
- [ ] `sdd/WORKFLOW.md` and `CLAUDE.md` describe the new model.

---

## 6. Codebase Contract

> **Anti-Hallucination Anchor.** Every entry below was verified by
> reading the file at the cited line number on 2026-05-05.

### Verified Existing Files (to be modified)

| Path | Lines | Purpose |
|---|---|---|
| `.claude/commands/sdd-spec.md` | 248 | Spec scaffolding command |
| `.claude/commands/sdd-task.md` | 166 | Task decomposition command |
| `.claude/commands/sdd-start.md` | 221 | Task execution command |
| `.claude/commands/sdd-done.md` | 355 | Feature closing command |
| `.claude/commands/sdd-next.md` | 88 | Unblocked task suggestion |
| `.claude/commands/sdd-status.md` | 56 | Task board command |
| `.claude/commands/sdd-brainstorm.md` | (read for length) | Idea exploration |
| `.claude/commands/sdd-proposal.md` | (read for length) | Plain-language proposal |
| `.claude/commands/sdd-fromjira.md` | (verify) | Jira → brainstorm bootstrap |
| `.claude/commands/sdd-tojira.md` | (verify, unchanged) | Spec → Jira sync |
| `.claude/agents/sdd-worker.md` | 244 | Autonomous SDD implementer |
| `sdd/templates/spec.md` | 188 | Spec template |
| `sdd/templates/brainstorm.md` | (verify) | Brainstorm template |
| `sdd/templates/proposal.md` | (verify) | Proposal template |
| `sdd/WORKFLOW.md` | (verify) | Workflow doc |
| `CLAUDE.md` | (verify) | Project rules |
| `sdd/tasks/.index.json` | 15.850 | Source for migration; preserved post-migration |

### Existing Schema Reference (current monolith top-level keys)

Verified via `jq 'keys[]' sdd/tasks/.index.json`:
```
created_at
feature
feature_id
previous_features
spec
tasks
```

The per-spec index keeps `created_at`, `feature`, `feature_id`, `spec`,
`tasks`, drops `previous_features` (one file per feature replaces it),
and adds `type`, `base_branch`, `completed_at`.

### Existing Workflow Patterns (referenced verbatim in agent/commands)

`.claude/agents/sdd-worker.md:60` —
> CODE IN WORKTREE, STATE ON `dev`.

This rule is rewritten by Module 8.

`.claude/commands/sdd-task.md:16` —
> Must run on `dev` branch (or the integration branch). Not inside a worktree.

This rule is rewritten by Module 5.

`.claude/commands/sdd-done.md:25` —
> Must run on `dev`, not inside a worktree.

This rule is generalised to "must run on `<base_branch>`" by Module 6.

### Does NOT Exist (Anti-Hallucination)

- ~~`sdd/tasks/index/`~~ — directory does not exist yet; created by Module 2.
- ~~`scripts/sdd/`~~ — directory does not exist (`scripts/` exists; `scripts/sdd/` does not).
- ~~`scripts/sdd/sdd_meta.py`~~ — created by Module 1.
- ~~`scripts/sdd/migrate_index.py`~~ — created by Module 2.
- ~~`tests/scripts/`~~ — verify before assuming; create if missing.
- ~~Any existing YAML frontmatter on specs~~ — `head -8` of every `sdd/specs/*.spec.md` shows the markdown-bold metadata pattern (`**Feature ID**:`); no `---` frontmatter delimiters in current files.
- ~~A `flow_type` field in current `.index.json`~~ — verified absent; introduced by this feature.

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `FlowMeta.parse()` | Frontmatter at top of `.md` | `pyyaml.safe_load` on the block between the first two `---` lines | Pattern reference: Jekyll-style frontmatter |
| `migrate_index.py` | `sdd/tasks/.index.json` | Direct JSON read, group-by, write multiple JSON files | `sdd/tasks/.index.json` keys verified |
| `/sdd-task` | per-spec index | Replaces lines 86-109 of `.claude/commands/sdd-task.md` (the index schema block) | `.claude/commands/sdd-task.md:86` |
| `sdd-worker` | per-spec index | Replaces step 1 (line ~82) | `.claude/agents/sdd-worker.md:82` |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Backwards compatibility for specs without frontmatter.** Any
  `sdd/specs/*.spec.md` that pre-dates this refactor will not have a
  YAML frontmatter block. `FlowMeta.parse()` MUST return the defaults
  (`type="feature"`, `base_branch="dev"`) in that case; never raise.
- **Migration runs first, deployment runs second.** The migration
  script is committed and run on `dev` before the new commands are
  rolled out. After migration, `sdd/tasks/.index.json` remains in
  place but the new commands ignore it. A separate trailing commit
  removes the monolith once the team has had a window to compare.
- **Pull semantics.** `/sdd-spec` and `/sdd-task` run
  `git checkout <base_branch> && git pull --ff-only origin
  <base_branch>` before doing any work. If `--ff-only` fails or the
  working tree is dirty, abort with a clear message — do NOT attempt
  to stash or merge.

…(truncated)…
