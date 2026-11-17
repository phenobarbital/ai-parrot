---
title: "Guide to using the SDD slash commands"
---

# Guide to using the SDD slash commands

> A practical guide for AI-Parrot developers. It explains how we work with
> **Spec-Driven Development (SDD)** inside Claude Code: which commands
> exist, when to use each one, and how they fit into the lifecycle of a feature.
>
> For the full methodology and the artifact contract, see
> [`WORKFLOW.md`](https://phenobarbital.github.io/ai-parrot/docs/sdd/WORKFLOW/). For the worktree policy and the
> flow types (`feature` / `hotfix`), see `CLAUDE.md` at the repo root.

---

## 1. Overview

SDD is our way of working on features with Claude Code. The fundamental
rule is:

> **Specifications are the single source of truth (SSOT).**
> First we discuss and design in documents, then we decompose into
> atomic tasks, and only then do we write code.

This gives us three concrete benefits:

1. **Fewer hallucinations**: every spec and every task contains a *Codebase
   Contract* with imports, signatures and "Does NOT Exist" entries verified
   against the real code.
2. **Parallelism**: each feature lives in its own worktree and in
   its own task index (`sdd/tasks/index/<feature>.json`), so
   several features move forward at once without colliding.
3. **Auditability**: every step is left as a commit on `dev` or on the
   feature branch, and optionally synchronized with a Jira ticket.

---

## 2. The lifecycle of a feature

```
                                     ┌──────────────────┐
                                     │  /sdd-fromjira   │
                                     │  (optional)      │
                                     └────────┬─────────┘
                                              ▼
       ┌──────────────────┐         ┌──────────────────┐
       │ /sdd-proposal    │   or    │ /sdd-brainstorm  │
       │ (guided chat)    │         │ (3 options +     │
       └────────┬─────────┘         │  recommendation) │
                │                   └────────┬─────────┘
                ▼                            ▼
                       ┌──────────────────┐
                       │  /sdd-spec       │  ← spec approved on `dev`
                       └────────┬─────────┘
                                ▼
                       ┌──────────────────┐
                       │  /sdd-tojira     │  (optional, exports to Jira)
                       └────────┬─────────┘
                                ▼
                       ┌──────────────────┐
                       │  /sdd-task       │  ← creates TASK-* (worktree via parrot sdd worktree ensure)
                       └────────┬─────────┘
                                ▼
              cd "$WORKTREES_DIR/feat-<ID>-<slug>"
                                │
                                ▼
       ┌──────────────────┐  loop  ┌──────────────────┐
       │  /sdd-start      │  ◄───  │  /sdd-next       │
       │  (implements)    │        │  /sdd-status     │
       └────────┬─────────┘        └──────────────────┘
                │
                ▼
       ┌──────────────────┐
       │  /sdd-codereview │  (optional, per task)
       └────────┬─────────┘
                ▼
       ┌──────────────────┐
       │  /sdd-done       │  ← merge feature → base, push, cleanup
       └──────────────────┘
```

The arrows are what matters: **each command consumes the output of the
previous one**. If you skip a step, the next one will not find the artifact
it needs.

---

## 3. Quick command table

| Command | What it does | Where it runs | Output |
|---|---|---|---|
| `/sdd-proposal` | Guided chat (Why/What) in non-technical language | `dev` | `sdd/proposals/<n>.proposal.md` |
| `/sdd-brainstorm` | 2+ rounds of Q&A + 3 technical options + recommendation | `dev` | `sdd/proposals/<n>.brainstorm.md` |
| `/sdd-fromjira` | Starts a brainstorm from a Jira ticket | `dev` | `sdd/proposals/<key>-<slug>.brainstorm.md` |
| `/sdd-spec` | Generates the formal spec with a *Codebase Contract* | `dev` | `sdd/specs/<n>.spec.md` |
| `/sdd-tojira` | Uploads the spec to Jira as a Story (optional subtasks) | `dev` | updates the spec with `**Jira**: ...` |
| `/sdd-task` | Decomposes the spec into `TASK-*` + creates the worktree | `dev` (not in a worktree) | `sdd/tasks/active/TASK-*.md` + `sdd/tasks/index/<n>.json` |
| `/sdd-status` | Aggregated board of all features | anywhere | print | 
| `/sdd-next` | Suggests the next unblocked tasks | anywhere | print |
| `/sdd-start` | Marks the task `in-progress`, implements, commits, marks `done` | inside the worktree | code + commits |
| `/sdd-codereview` | Structured review of a completed task | anywhere | `sdd/reviews/TASK-*-review.md` |
| `/sdd-done` | Verifies, merges feature → base, pushes, cleans up the worktree | `dev` (not in a worktree) | merge to `dev` (or a PR snippet for a hotfix) |

> **Model tip**: `/sdd-status`, `/sdd-next` and `/sdd-done` are
> configured to use **Haiku** (they are mechanical). The rest use
> Sonnet/Opus by default, because they require reasoning.

---

## 4. Commands in detail

### 4.1. `/sdd-proposal` — Initial discussion

A **gentle** entry point when you are not yet clear on the scope.
A chat in non-technical language (Why / What / Impact / Open Questions) that
can optionally generate the spec automatically at the end.

```bash
/sdd-proposal multi-agent-handoff -- "queremos que un agente pueda
delegar una conversación a otro sin perder contexto"
```

It first asks for the **flow type** (`feature` vs `hotfix`) and the
`base_branch`. It stores them in the proposal's frontmatter.

### 4.2. `/sdd-brainstorm` — Structured exploration

The **technical** entry point. It runs a minimum of **two rounds** of Q&A,
investigates the existing code, and produces **at least 3 options** with
pros, cons and references to libraries and code in the repo.

```bash
/sdd-brainstorm crew-result-storage -- "queremos persistir
los resultados de un AgentCrew en pgvector, redis, o disco"
```

Rules you should know:

- It **does not generate implementation code**. Only ideas, libraries and references.
- It captures a verified **Code Context**: every cited class/method is
  read from the real file with its path and line.
- It marks resolved questions with `[x]` — `/sdd-spec` will not ask them
  again.

### 4.3. `/sdd-fromjira` — Bootstrap from Jira

If the feature already exists as a Jira ticket, start from there:

```bash
/sdd-fromjira NAV-8036
/sdd-fromjira NAV-8036 --complexity=fix     # minimal Q&A
/sdd-fromjira NAV-8036 --skip-qa            # uses the description as-is
```

It only **reads** the ticket (it never modifies Jira). It produces a standard
brainstorm; from there, continue with `/sdd-spec`.

### 4.4. `/sdd-spec` — Formal specification

It takes the brainstorm (or the proposal) and turns it into a formal spec with:

- Motivation, scope and concrete *Acceptance Criteria*.
- **Codebase Contract** (§6): verified imports, exact signatures and a
  "Does NOT Exist" section — the best defense against hallucinations.
- *Worktree Strategy* (per-spec or mixed).

```bash
/sdd-spec crew-result-storage
```

> Before scaffolding, it runs `git checkout <base_branch>` and
> `git pull --ff-only`. If the working tree is dirty, it aborts — it
> does not attempt an automatic stash.

When you approve it, mark `status: approved` in the spec.

### 4.5. `/sdd-tojira` — Export to Jira (optional)

Uploads the spec as a Story to the `NAV` project (or the one you specify):

```bash
/sdd-tojira sdd/specs/crew-result-storage.spec.md
/sdd-tojira FEAT-147 --with-subtasks
/sdd-tojira FEAT-147 --ticket NAV-8036    # updates an existing ticket
```

It uses **mcp-atlassian** if available, with a fallback to `curl`. Credentials
are loaded via `navconfig` (`JIRA_INSTANCE`,
`JIRA_USERNAME`, `JIRA_API_TOKEN`).

### 4.6. `/sdd-task` — Decomposition into tasks

Decomposes an **approved** spec into atomic tasks (1–4h each) and
creates the worktree for that feature:

```bash
/sdd-task sdd/specs/crew-result-storage.spec.md
```

What it does:

1. Syncs the `base_branch` (checkout + pull --ff-only).
2. Creates `sdd/tasks/active/TASK-NNN-<slug>.md` for each task.
3. Creates/updates the **per-spec index** at
   `sdd/tasks/index/<feature>.json` (one file per feature — no
   collisions between features).
4. Commits everything to `<base_branch>`.
5. Ensures the worktree under the configured root:
   `parrot sdd worktree ensure --slug <slug> --feature-id FEAT-<ID>`

> **Important**: `/sdd-task` runs from the main repo, **not**
> from a worktree.

Each task inherits a *Codebase Contract* specific to its scope, copied
from §6 of the spec and re-verified against the current code.

### 4.7. `/sdd-status` — Task board

An aggregated read of all `sdd/tasks/index/*.json`:

```bash
/sdd-status                        # all features
/sdd-status crew-result-storage    # just one
```

It groups by `in-progress` → `pending` → `done`, flags blockers and shows
*orphans* (tasks without attribution rescued by the FEAT-145 migration).

### 4.8. `/sdd-next` — Next unblocked task

Suggests what to do now:

```bash
/sdd-next
```

It orders by priority (high → medium → low) and then by effort
(S → M → L → XL). For each task it proposes:

- If the feature **already has an active worktree**: the exact command
  `/sdd-start TASK-<NNN>` to run **inside** that worktree.
- If it does not: the corresponding `git worktree add`.
- If the task is `parallel: true`: an option for its own worktree.

### 4.9. `/sdd-start` — Implement a task

The workhorse. It accepts the ID or the slug:

```bash
MAIN_ROOT=$(cd "$(git rev-parse --path-format=absolute --git-common-dir)/.." && pwd)
WORKTREES_DIR=$(parrot sdd worktree root --root "$MAIN_ROOT") || exit $?
cd "$WORKTREES_DIR/feat-147-crew-result-storage"
/sdd-start TASK-1019
# or
/sdd-start crew-result-storage-tests
```

What it does, in order:

1. Resolves the task in `sdd/tasks/index/*.json`.
2. Validates that `status == "pending"` and that all its `depends_on` are
   `done`. If it is blocked, it **stops**.
3. Marks the task `in-progress` and commits the index.
4. **Verifies the Codebase Contract**: it runs `grep`/`read` on every listed
   import and signature. If anything changed, it updates the task's contract
   *before* starting to code.
5. **Implements**: creates/modifies the files in scope, runs lint and
   the tests from the Acceptance Criteria.
6. Commits with `feat(<feature-slug>): TASK-<NNN> — <title>`.
7. Moves the file to `sdd/tasks/completed/`, updates the index and
   commits as `sdd: complete TASK-<NNN>`.

> It only stops if a dependency is broken, the spec is ambiguous, or
> tests fail and it cannot determine the fix. Otherwise it continues until `done`.

### 4.10. `/sdd-codereview` — Per-task review (optional)

Reads the file in `sdd/tasks/completed/` and all the files it touched,
and applies a structured review (correctness, DRY/SOLID, performance,
security, docstrings, tests).

```bash
/sdd-codereview TASK-1019
/sdd-codereview crew-result-storage-tests
```

Output: a markdown report with a verdict (`✅ Approved` / `⚠ Approved with
notes` / `❌ Needs changes`), an Acceptance Criteria table and findings
classified by severity. Optionally saves to
`sdd/reviews/TASK-<NNN>-review.md`.

### 4.11. `/sdd-done` — Close the feature

Closes a feature from the main repo (not from the worktree):

```bash
git checkout dev
/sdd-done FEAT-147
/sdd-done FEAT-147 --dry-run         # see what would happen without touching anything
/sdd-done FEAT-147 --force           # close even with tasks that have issues
# Configure the post_pr hook jira.transition; see wiki/sdd-tooling/sdd/closeout-hooks.md
```

Steps:

1. Verifies you are on `<base_branch>` (leaves the worktree if
   needed).
2. Gathers evidence from the worktree: commits that mention the task,
   expected files exist, tests pass.
3. Prints the **Verification Report** (✅ / ⚠ / ❌ per task).
4. Moves the `TASK-*.md` files to `completed/` and updates the index.
5. **If it is a feature**: runs `git merge --no-edit feat-<ID>-<slug>` on
   `<base_branch>` and `git push origin <base_branch>`.
6. **If it is a hotfix**: it does NOT merge to `main`. It prints the snippet
   `gh pr create --base main` so you open the PR by hand. After the
   merge, you run it again with `--sync-dev` to carry the change to
   `dev`.
7. If you configure the `post_pr` hook `jira.transition`, it transitions the ticket
   (and subtasks) to the configured state. See `wiki/sdd-tooling/sdd/closeout-hooks.md`.
8. Cleans up the worktree: `git worktree remove ...`.

> **Non-negotiable rule**: `/sdd-done` **never** pushes to `main` nor opens
> a PR against `main`, under any flag. Hotfixes are merged to `main`
> only via a manual PR.

---

## 5. Complete examples

### 5.1. New feature, immature idea

```bash
# 1. Guided chat
/sdd-proposal agent-tracing -- "necesitamos trazas distribuidas
   en los AgentCrew para debugging"

# 2. Generate the spec from the proposal
/sdd-spec agent-tracing

# (Review the spec, mark status: approved)

# 3. Decompose and create the worktree
/sdd-task sdd/specs/agent-tracing.spec.md

# 4. Work inside the worktree
MAIN_ROOT=$(cd "$(git rev-parse --path-format=absolute --git-common-dir)/.." && pwd)
WORKTREES_DIR=$(parrot sdd worktree root --root "$MAIN_ROOT") || exit $?
cd "$WORKTREES_DIR/feat-150-agent-tracing"
/sdd-start TASK-001
/sdd-start TASK-002
# ...
/sdd-done FEAT-150
# (go back to the main repo)
```

### 5.2. Technical feature with several options to evaluate

```bash
# Brainstorm with 3 options
/sdd-brainstorm batch-embedding-pipeline -- "embeddings
   en batch nocturno: ¿celery, dramatiq o asyncio puro?"

# Convert to a spec (carry-forward of Code Context and options)
/sdd-spec batch-embedding-pipeline

/sdd-task sdd/specs/batch-embedding-pipeline.spec.md
# ... the rest is the same as above
```

### 5.3. Bug coming from Jira

```bash
/sdd-fromjira NAV-8036
# (answer the short Q&A)
/sdd-spec ...
/sdd-tojira sdd/specs/<slug>.spec.md --ticket NAV-8036
/sdd-task sdd/specs/<slug>.spec.md

MAIN_ROOT=$(cd "$(git rev-parse --path-format=absolute --git-common-dir)/.." && pwd)
WORKTREES_DIR=$(parrot sdd worktree root --root "$MAIN_ROOT") || exit $?
cd "$WORKTREES_DIR/feat-NNN-<slug>"
/sdd-start ...
# When finished:
# Configure jira.transition in .parrot/sdd_hooks.toml; see wiki/sdd-tooling/sdd/closeout-hooks.md
```

### 5.4. Urgent hotfix on `main`

```bash
# The brainstorm/proposal must declare type: hotfix, base_branch: main
/sdd-brainstorm fix-pgvector-deadlock
# (in Round 0 you say: hotfix → base_branch: main)

/sdd-spec fix-pgvector-deadlock
/sdd-task sdd/specs/fix-pgvector-deadlock.spec.md

MAIN_ROOT=$(cd "$(git rev-parse --path-format=absolute --git-common-dir)/.." && pwd)
WORKTREES_DIR=$(parrot sdd worktree root --root "$MAIN_ROOT") || exit $?
cd "$WORKTREES_DIR/feat-NNN-fix-pgvector-deadlock"
/sdd-start TASK-...

# Hotfix closeout — does NOT merge to main
git checkout main
/sdd-done FEAT-NNN
# Prints the gh pr create --base main snippet → you open it yourself

# After merging the PR to main:
/sdd-done FEAT-NNN --sync-dev
# This propagates the hotfix to dev automatically
```

---

## 6. Golden rules (don't forget them)

1. **Never** use `claude --worktree`. Always create the worktree by hand
   from the correct branch (`/sdd-task` does it for you).
2. **Do not** run `/sdd-task` or `/sdd-done` inside a worktree —
   both live in the main repo on `<base_branch>`.
3. Every command that creates files **commits only those files**. If you
   see `git add .` or `git add -A` in an SDD session, it is a bug — the
   commands run `git reset HEAD` first and stage by name.
4. **The spec is the SSOT**. If during implementation you discover that
   the spec is wrong, update the spec before continuing to code — do not
   improvise in the code.
5. **The Codebase Contract is not decorative**: if a task references an
   import or a signature, that item was verified against the real code.
   If you change it, update the contract.
6. **One task, one logical commit**. `/sdd-start` does this on its own.
7. **Hotfixes are never merged automatically to `main`**. Manual PR only.
   `/sdd-done` reminds you of this on every flag.

---

## 7. File structure

```
sdd/
├── proposals/                       # brainstorms and proposals
│   ├── <feature>.brainstorm.md
│   └── <feature>.proposal.md
├── specs/                           # approved specs (SSOT)
│   └── <feature>.spec.md
├── tasks/
│   ├── active/TASK-NNN-<slug>.md    # tasks in pending / in-progress
│   ├── completed/TASK-NNN-<slug>.md # done tasks (with Completion Note)
│   └── index/                       # per-spec index (FEAT-145)
│       ├── <feature>.json           # one file per feature
│       └── _orphans.json            # rescued by the migration
├── reviews/                         # output of /sdd-codereview
├── templates/                       # templates (do not edit lightly)
└── WORKFLOW.md                      # contract and schemas

.claude/
├── commands/                        # implementation of the slash commands
│   └── sdd-*.md
├── agents/
│   ├── sdd-worker.md                # autonomous task agent
│   ├── sdd-research.md
│   └── sdd-qa.md
└── worktrees/                       # ephemeral worktrees (git-ignored)
    └── feat-<ID>-<slug>/
```

---

## 8. Autonomous mode: the `sdd-worker` agent

If you want to leave Claude implementing a **complete** feature without
intervention, launch `sdd-worker` inside the worktree:

```bash
parrot sdd launch worker FEAT-150

# In the background:
parrot sdd launch worker FEAT-150 --tmux --detach
# Run the same command with --tmux to reattach.
```

The agent executes all of the feature's tasks in dependency order,
commits per task and respects the scope of the spec exactly (it does not
redesign).

---

## 9. When NOT to use SDD

The ceremony is not worth it when:

- It is a docs-only change.
- It is a single-commit fix (a typo, a version bump, etc.).
- It is pure exploration (`/sdd-brainstorm` already covers the "do not implement
  yet" part, but if there is no intention to implement, even that is unnecessary).
- A feature has a single task — a worktree adds overhead with no
  benefit. Work on a normal branch.

For everything else (features with several modules, risky refactors,
hotfixes that require validation, new integrations), follow the
full SDD cycle.

---

## 10. References

- Full SDD methodology: [`WORKFLOW.md`](https://phenobarbital.github.io/ai-parrot/docs/sdd/WORKFLOW/)
- Worktree policy and flow types (FEAT-145): `CLAUDE.md`
- Templates: `sdd/templates/{brainstorm,proposal,spec,task}.md`
- Command implementation: `.claude/commands/sdd-*.md`
- Related agents: `.claude/agents/sdd-{worker,research,qa}.md`
