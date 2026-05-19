# AI-Parrot SDD Workflow for Claude Code

## Overview

This document defines the **Spec-Driven Development (SDD)** methodology for AI-Parrot, optimized for Claude Code and Antigravity with multi-agent task distribution.

The key idea: specifications are the Single Source of Truth (SSOT). Claude Code agents
consume spec documents and produce **Task Artifacts** — discrete, self-contained files
in `tasks/active/` that can be independently picked up and executed by any Claude Code
agent in parallel.

---

## The SDD Lifecycle

```
                                 ┌─ /sdd-fromjira → jira-issue → brainstorm ────┐
                                 │                                                 │
                                 ├─ /sdd-proposal → discuss → brainstorm ──────────┤
                                 │                                                 │
                                 ├─ /sdd-spec → scaffold spec ─────────────────────┤
[Human] ────────────────────────┤                                           Feature Spec → [Planner] Tasks → [Executors] Code → [Reviewer] Validation
                                 │                                                 ↑              ↑                                       |
                                 ├─ /sdd-tojira → jira-issue ──────────────────────┘              └────────── Feedback Loop ──────────────┘
                                 │                                                                                                        |
                                 └────────── /sdd-task → decomposes spec into tasks ──────────────────────────────────────────────────────┘
```

### Phase 0 — Feature Proposal *(optional)*
Start here when the idea is not yet well-defined. Use `/sdd-proposal` to discuss
a feature in non-technical language. The agent walks through motivation, scope,
and impact with you, producing `docs/sdd/proposals/<feature>.proposal.md`.

The proposal can then automatically scaffold a formal spec (Phase 1).

### Phase 1 — Feature Specification
Start here when you already know what you want to build. Use `/sdd-spec` to scaffold
`docs/sdd/specs/<feature>.spec.md`, or accept one auto-generated from `/sdd-proposal`.

### Phase 2 — Task Generation (Claude Code Planner Agent)
Run `/sdd-task <spec-file>` to decompose the spec into Task Artifacts.

Each task is written to `tasks/active/TASK-<id>-<slug>.md`.
The **per-spec index** at `sdd/tasks/index/<feature-slug>.json` is created
or updated with task metadata (FEAT-145).

Tasks are designed to be:
- **Atomic** — completable independently
- **Bounded** — clear scope, no ambiguity
- **Testable** — every task includes its own test criteria
- **Assignable** — formatted so any Claude Code agent can start immediately

### Phase 3 — Task Execution (Claude Code Executor Agents)
Each executor agent picks up a task file:
```bash
# In a new Claude Code session:
claude "Read tasks/active/TASK-003-pgvector-loader.md and implement it"
```

Tasks declare their dependencies, so agents know what must be done first.

### Phase 4 — Validation (Claude Code Reviewer Agent)
After execution, tasks move to `tasks/completed/`.
A reviewer agent validates against the Test Specification.

---

## Task Artifact Format

Every task file (`tasks/active/TASK-<NNN>-<slug>.md`) follows this structure:

```markdown
# TASK-<NNN>: <Title>

**Feature**: <parent feature name>
**Spec**: docs/sdd/specs/<feature>.spec.md
**Status**: [ ] pending | [ ] in-progress | [x] done
**Priority**: high | medium | low
**Depends-on**: TASK-<X>, TASK-<Y>   (or "none")
**Assigned-to**: (agent session ID or "unassigned")

## Context
Brief explanation of why this task exists and how it fits the feature.

## Scope
Exactly what this task must implement. Be precise.

## Files to Create/Modify
- `parrot/path/to/file.py` — description
- `tests/path/to/test_file.py` — unit tests

## Implementation Notes
Technical guidance for the agent: patterns to follow, existing code to reference,
gotchas, constraints.

## Reference Code
Existing patterns in the codebase the agent should follow:
- See `parrot/loaders/base.py` for BaseLoader pattern
- See `parrot/bots/orchestration/crew.py` for DAG execution pattern

## Acceptance Criteria
- [ ] Criterion 1
- [ ] Criterion 2
- [ ] All tests pass: `pytest tests/path/ -v`

## Test Specification
```python
# Minimal test scaffold the agent must make pass
def test_feature_does_x():
    ...

def test_feature_handles_edge_case():
    ...
```

## Output
When complete, the agent must:
1. Move this file to `tasks/completed/`
2. Update `tasks/.index.json` status to "done"
3. Add a brief completion note below

### Completion Note
(Agent fills this in when done)
```

---

## Git Configuration (FEAT-187)

The Git Parrot Flow uses three long-lived branches:

- **`main`** — tagged releases only. Hotfixes land here via PR;
  no feature work ever bases on `main`.
- **`staging`** — release candidate branch. Cut from `dev` when the
  team decides to freeze a release. Receives `main → staging` syncs
  automatically (via `.github/workflows/sync-down.yml`); the
  `dev → staging` direction is a manual cut at freeze time.
- **`dev`** — integration branch for all feature work. Default base
  for `type: feature` flows.

**Sync-down automation** (FEAT-187): `.github/workflows/sync-down.yml`
listens for pushes to `main` and tries to fast-forward both `staging` and
`dev`. When fast-forward is not possible, it opens a sync PR against the
lagging branch. `/sdd-done --sync-down` is the manual fallback.

---

## Flow Types (FEAT-145, refined by FEAT-187)

Every brainstorm/proposal/spec declares its flow type via YAML frontmatter
at the top of the document:

```yaml
---
type: feature        # one of: feature | hotfix
base_branch: dev     # for feature: dev or staging; for hotfix: must be "main"
---
```

| Type      | base_branch         | When to use                                                  |
|-----------|---------------------|--------------------------------------------------------------|
| `feature` | `dev` (default)     | Most work. Lands on `dev` via `/sdd-done`.                   |
| `feature` | `staging`           | Stabilization fix during a release freeze. Lands on `staging`. |
| `feature` | `<other-branch>`    | Sub-features extending another feature branch.               |
| `hotfix`  | `main` (required)   | Production hotfixes. Land on `main` via manual PR.           |

Features MUST NOT base on `main`. `/sdd-done` enforces: hotfixes are NEVER
auto-pushed or auto-PR'd to `main`. The user opens the PR manually; afterwards,
`.github/workflows/sync-down.yml` propagates the change back to `staging` and
`dev` automatically. If the Action fails, run `/sdd-done --sync-down` locally.

---

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

### Recommended Branch Protection

`main` (and `staging` once in active use) should require PRs, passing CI
status checks, and signed commits. Configure via GitHub repo settings —
not declaratively in this repo (open question in spec §8).

---

## Per-Spec Index Schema (`sdd/tasks/index/<feature-slug>.json`, FEAT-145)

> **Migration history**: the legacy monolithic `sdd/tasks/.index.json` was
> split into per-spec files by `scripts/sdd/migrate_index.py`. The original
> monolith is preserved as a historical artifact. New tooling reads only
> per-spec indexes.

Each per-spec index file contains a header describing the feature plus
the `tasks[]` array for that feature only. Two parallel features touch
disjoint files and never collide on merge.

```json
{
  "feature": "feature-slug",
  "feature_id": "FEAT-NNN",
  "spec": "sdd/specs/feature-slug.spec.md",
  "type": "feature",
  "base_branch": "dev",
  "created_at": "ISO-8601",
  "completed_at": null,
  "tasks": [
    {
      "id": "TASK-001",
      "slug": "base-loader-interface",
      "title": "Define BaseLoader abstract interface",
      "feature_id": "FEAT-NNN",
      "feature": "feature-slug",
      "status": "done",
      "priority": "high",
      "depends_on": [],
      "assigned_to": null,
      "started_at": null,
      "completed_at": "ISO-8601",
      "file": "sdd/tasks/completed/TASK-001-base-loader-interface.md"
    }
  ]
}
```

Tasks orphaned by the migration (no resolvable `feature`) live in
`sdd/tasks/index/_orphans.json` with the same schema and `feature: "_orphans"`.
`/sdd-status` surfaces them in a dedicated panel; `/sdd-next` skips them.

See `sdd/specs/sdd-flow-types-and-per-spec-index.spec.md` (FEAT-145) for
the authoritative design rationale.

---

## Parallelism Rules

Claude Code agents can work in parallel when tasks have no shared dependencies:

```
TASK-001 (base interface)
    ├── TASK-002 (pgvector)    ← parallel after 001
    ├── TASK-003 (arangodb)    ← parallel after 001
    └── TASK-004 (embeddings)  ← parallel after 001
            └── TASK-005 (rag-pipeline) ← waits for 002, 003, 004
```

A Claude Code agent should **never start a task** if its `depends_on` tasks
are not in `tasks/completed/`.

---

## Commands Reference

These commands are available as both Claude Code commands (`.claude/commands/`) and
Antigravity workflows (`.agent/workflows/`):

| Command | Description |
|---|---|
| /sdd-fromjira | Bootstrap an SDD Brainstorm from a Jira ticket |
| /sdd-tojira | Export an SDD Specification to a Jira Story |
| `/sdd-proposal` | Propose and discuss a feature idea before building a spec |
| `/sdd-spec` | Scaffold a new Feature Specification |
| `/sdd-task <spec.md>` | Decompose a spec into Task Artifacts |
| `/sdd-status` | Show task index status summary |
| `/sdd-next` | Suggest next unblocked tasks to assign |

---

## Quality Rules for Agents

1. **Never modify files outside the task scope** — respect boundaries
2. **Follow existing patterns** — reference code mentioned in the task
3. **Write tests first** — TDD approach per task
4. **Update the index** — always update `.index.json` on completion
5. **Small commits** — one task = one logical commit
6. **Ask via the spec** — if unclear, note the ambiguity in the completion note
   and let the Planner agent refine the spec for the next iteration
