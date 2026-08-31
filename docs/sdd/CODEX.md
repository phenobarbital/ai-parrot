# Spec-Driven Development in Codex

This guide explains how to run AI-Parrot's Spec-Driven Development (SDD) flow
from Codex.

The older Claude Code flow used slash commands from `.claude/commands/`. In
Codex, the shared repository workflow is exposed as repo-scoped skills under
`.agents/skills/`. Invoke them with `$sdd-*` from a Codex chat, or select them
through `/skills`.

## Quick Map

| Claude command | Codex skill | Purpose |
|---|---|---|
| `/sdd-brainstorm` | `$sdd-brainstorm` | Explore a feature idea, compare options, and write a brainstorm. |
| `/sdd-proposal` | `$sdd-proposal` | Research a Jira issue, inline request, or notes file before writing a spec. |
| `/sdd-spec` | `$sdd-spec` | Convert a brainstorm, proposal, or direct request into a formal spec. |
| `/sdd-task` | `$sdd-task` | Decompose an approved spec into atomic task files and a per-spec index. |
| `/sdd-start` | `$sdd-start` | Implement and close one task inside the feature worktree. |
| `/sdd-done` | `$sdd-done` | Verify, push, open or describe the PR, and clean up the worktree. |

The autonomous implementation agent is configured at:

```text
.codex/agents/sdd-worker.toml
```

Use it by asking Codex to delegate the feature to `sdd-worker`, for example:

```text
Use the sdd-worker agent to implement FEAT-214.
```

## Codex Surfaces

AI-Parrot uses three Codex surfaces for this workflow:

| Surface | Path | Role |
|---|---|---|
| Repo guidance | `AGENTS.md` | Always-loaded project rules, safety protocol, and coding standards. |
| Repo skills | `.agents/skills/sdd-*/SKILL.md` | Reusable SDD workflows invoked as `$sdd-*`. |
| Custom agent | `.codex/agents/sdd-worker.toml` | Specialized autonomous worker for SDD task execution. |

The `.agent/` directory still contains project context and legacy Antigravity
workflow files. Codex-specific SDD entry points are the `.agents/skills/` files
and `.codex/agents/sdd-worker.toml`.

If a newly added skill or agent does not appear in Codex, restart the Codex
session and run `/skills` or `/agent` again.

## End-to-End Flow

```text
$sdd-proposal or $sdd-brainstorm
        |
        v
$sdd-spec
        |
        v
review spec and set status: approved
        |
        v
$sdd-task
        |
        v
cd .claude/worktrees/<feature-worktree>
        |
        v
$sdd-start TASK-NNN
        |
        v
repeat until all tasks are done, or delegate to sdd-worker
        |
        v
$sdd-done FEAT-NNN
```

The worktree directory is still `.claude/worktrees/` for compatibility with the
existing SDD scripts and task indexes. Codex uses `.codex/agents/` only for
custom agent configuration.

## Start From A Ticket Or Bug Report

Use `$sdd-proposal` when the source is thin and the repository probably has more
context than the request:

```text
$sdd-proposal NAV-8421
$sdd-proposal "Nextstop module does not generate the PDF"
$sdd-proposal docs/notes/pdf-failure.md --mode=investigation
```

The proposal flow:

1. Resolves the source from Jira, inline text, or a file.
2. Runs wiki-first and codebase research.
3. Persists findings under `sdd/state/<FEAT-ID>/`.
4. Produces `sdd/proposals/<slug>.proposal.md`.
5. Recommends the next step, usually `$sdd-spec`.

Use `--resume FEAT-NNN` to continue a previously interrupted proposal run.

## Start From A Feature Idea

Use `$sdd-brainstorm` for greenfield or design-heavy features:

```text
$sdd-brainstorm crew-result-storage -- "Persist AgentCrew outputs for later audit and RAG reuse."
```

The brainstorm flow asks for:

1. Flow type: `feature` or `hotfix`.
2. Base branch: usually `dev`, `staging` during a release freeze, or `main` for
   hotfixes only.
3. At least two rounds of requirements and tradeoff questions.

It then researches the codebase, compares at least three approaches, recommends
one, and writes:

```text
sdd/proposals/<feature-slug>.brainstorm.md
```

## Write The Spec

Use `$sdd-spec` to create the formal specification:

```text
$sdd-spec crew-result-storage
$sdd-spec hotfix-pdf-render --type hotfix --base-branch main
```

The spec is the single source of truth. It must include:

- problem statement and goals
- architectural design
- module breakdown
- test specification
- acceptance criteria
- Codebase Contract
- worktree strategy
- open questions

If a brainstorm or proposal exists, `$sdd-spec` consumes it as authoritative
input. Resolved questions marked `[x]` are carried forward and must not be
re-asked.

Before writing the spec, the flow resolves and validates:

```yaml
---
type: feature
base_branch: dev
---
```

Rules:

- `type: feature` defaults to `base_branch: dev`.
- `type: feature` may use `staging` during a release freeze.
- `type: feature` must not use `main`.
- `type: hotfix` must use `main`.

For feature specs, `$sdd-spec` reserves the formal `FEAT-NNN` through:

```bash
python -m scripts.sdd.reserve_ids --kind feature --count 1 --base-branch <base_branch> --label <feature-slug>
```

Do not hand-compute feature IDs.

## Generate Tasks

After reviewing the spec, set:

```text
**Status**: approved
```

Then run:

```text
$sdd-task sdd/specs/<feature-slug>.spec.md
```

This skill:

1. Syncs the spec's `base_branch`.
2. Decomposes the spec into atomic tasks.
3. Reserves `TASK-NNN` IDs for feature work.
4. Writes task files to `sdd/tasks/active/`.
5. Writes or updates the per-spec index at `sdd/tasks/index/<feature-slug>.json`.
6. Commits only the task files and index.
7. Creates the feature worktree under `.claude/worktrees/`.

Task IDs are reserved with:

```bash
python -m scripts.sdd.reserve_ids --kind task --count <N> --base-branch <base_branch> --label <feature-slug>
```

Do not hand-compute task IDs.

## Implement One Task

Move into the generated worktree:

```bash
cd .claude/worktrees/feat-<FEAT-ID>-<feature-slug>
```

Then run:

```text
$sdd-start TASK-NNN
```

`$sdd-start` does not stop after a kickoff summary. It must continue through
implementation unless a stop condition is reached.

The worker must:

- read the task and spec
- verify the task's Codebase Contract
- modify only files listed by the task
- run the task's acceptance checks
- commit the implementation files
- close the task with `scripts/sdd/close_task.sh`
- fill the task Completion Note
- commit the SDD state update

Use this command for a single task when you want tight control over each step.

## Implement A Whole Feature With `sdd-worker`

For unattended implementation, ask Codex to delegate to the custom agent:

```text
Use the sdd-worker agent to implement FEAT-214 in its worktree.
```

The `sdd-worker` agent:

- resolves the feature from `sdd/tasks/index/*.json`
- syncs the base branch
- creates or reuses the feature worktree
- implements tasks in dependency order
- commits after each task
- updates SDD state in the same worktree branch
- runs an adversarial review before pushing
- pushes the feature branch

It also supports task-scoped JSON briefs:

```json
{"task_id": "TASK-1857"}
```

In task-scoped mode it implements only that task and does not touch unrelated
task state.

Use `/agent` or `/subagents` in Codex to inspect spawned agent threads while
they run.

## Close The Feature

Run closeout from the main repository, not from inside the worktree:

```text
$sdd-done FEAT-NNN
$sdd-done FEAT-NNN --dry-run
$sdd-done FEAT-NNN --force
$sdd-done FEAT-NNN --resolve-jira
```

`$sdd-done` verifies:

- current branch matches the spec's `base_branch`
- the command is not running inside `.claude/worktrees/`
- the feature worktree exists
- every task has commit and file evidence

It then stamps verification into the worktree's per-spec index, pushes the
feature branch, and opens a PR for feature flows.

For feature work, the default closeout opens a PR against `dev`, `staging`, or
the configured parent branch. Use `--merge` only when direct merge is
intentional.

For hotfix work, `$sdd-done` never merges directly to `main` and never pushes
to `main`. It prints the manual `gh pr create --base main ...` command. After
that PR is merged, use `--sync-down` only if the automatic sync workflow did
not propagate the hotfix to `staging` and `dev`.

## Artifact Locations

| Artifact | Path |
|---|---|
| Brainstorms | `sdd/proposals/<slug>.brainstorm.md` |
| Proposals | `sdd/proposals/<slug>.proposal.md` |
| Proposal research state | `sdd/state/<FEAT-ID>/` |
| Specs | `sdd/specs/<slug>.spec.md` |
| Active tasks | `sdd/tasks/active/TASK-NNN-<slug>.md` |
| Completed tasks | `sdd/tasks/completed/TASK-NNN-<slug>.md` |
| Per-spec task index | `sdd/tasks/index/<slug>.json` |
| Worktrees | `.claude/worktrees/<branch-name>/` |
| Codex SDD skills | `.agents/skills/sdd-*/SKILL.md` |
| Codex worker agent | `.codex/agents/sdd-worker.toml` |

## Safety Rules

Keep these rules intact when running the flow:

1. Commit the output of each SDD stage before creating or using worktrees.
2. Do not use `git add .` or `git add -A` for SDD state commits.
3. Do not update task state in the main repo while implementing inside a
   worktree.
4. Do not touch files outside the task scope without updating the task or asking
   the user.
5. Do not invent imports, symbols, or dependencies. Verify with wiki, `rg`, and
   source reads.
6. Store persisted test logs under `artifacts/logs/`.
7. Do not run `$sdd-task` or `$sdd-done` from inside a worktree.
8. Do not direct-merge hotfixes to `main`.

## Common Recipes

Ticket-driven feature:

```text
$sdd-proposal NAV-8036
$sdd-spec nav-8036-<slug>
# edit spec status to approved
$sdd-task sdd/specs/nav-8036-<slug>.spec.md
cd .claude/worktrees/feat-<FEAT-ID>-nav-8036-<slug>
$sdd-start TASK-NNN
# repeat tasks
cd ../../..
$sdd-done FEAT-NNN --resolve-jira
```

Greenfield feature:

```text
$sdd-brainstorm batch-embedding-pipeline -- "Batch embeddings with resumable checkpoints."
$sdd-spec batch-embedding-pipeline
# edit spec status to approved
$sdd-task sdd/specs/batch-embedding-pipeline.spec.md
Use the sdd-worker agent to implement FEAT-NNN.
$sdd-done FEAT-NNN
```

Hotfix:

```text
$sdd-proposal NAV-9001 --mode=investigation
$sdd-spec nav-9001-pdf-hotfix --type hotfix --base-branch main
# usually skip task decomposition for very small hotfixes
Use the sdd-worker agent to implement the hotfix spec.
$sdd-done NAV-9001
```

## Related Documentation

- [SDD Workflow](./WORKFLOW.md)
- [SDD Guide](./GUIDE.md)
- [SDD Platform](./PLATFORM.md)
- `AGENTS.md`
- `.agents/skills/sdd-*/SKILL.md`
- `.codex/agents/sdd-worker.toml`

