# AI-Parrot SDD Workflow — Agent Quick Reference

**Spec-Driven Development (SDD)**: the spec is the single source of truth;
it is decomposed into atomic task files that agents implement, one feature
per worktree. This page is the always-loaded summary — enough to follow the
workflow **without** running the `/sdd-*` commands. Details:

- Full reference: `sdd/WORKFLOW.md` (flow types, taxonomy, release cut, ID ledger, intake mode).
- Branch policy, auto-commit rule, per-spec index schema: `CLAUDE.md` § SDD Workflow & Worktree Policy.
- Worktrees: `.claude/rules/worktree-management.md`.

---

## Where things live

| Path | Contents |
|---|---|
| `sdd/proposals/<slug>.brainstorm.md` / `.proposal.md` | Exploration documents (frontmatter: `type`, `base_branch`, `projects`, `tags`) |
| `sdd/specs/<slug>.spec.md` | Feature specifications |
| `sdd/tasks/active/TASK-<NNN>-<slug>.md` | Tasks not yet closed |
| `sdd/tasks/completed/TASK-<NNN>-<slug>.md` | Closed tasks (with Completion Note) |
| `sdd/tasks/index/<feature-slug>.json` | **Per-spec index** — the task state of ONE feature (FEAT-145) |
| `sdd/tasks/.id_ledger.json` | TASK/FEAT number counter (FEAT-387) — never edit by hand |
| `sdd/templates/` | Templates for brainstorm, proposal, spec, task |
| `sdd/state/<FEAT-ID>/` | Research / design-research artifacts of a feature |
| `sdd/reviews/` | Feature code-review reports |
| `sdd/ledger/issues.jsonl` | Committed snapshot of the work ledger (written by `/sdd-done`) |

Gone / legacy — never write to them: `sdd/tasks/.index.json` (old monolith,
ignored), `tasks/` at the repo root, `docs/sdd/specs/`, `docs/sdd/proposals/`.

---

## Lifecycle

| Phase | Artifact | Command | Committed on |
|---|---|---|---|
| 0. Explore *(optional)* | brainstorm / proposal | `/sdd-brainstorm`, `/sdd-proposal`, `/sdd-fromjira` | `base_branch` |
| 1. Specify | spec (+ FEAT-ID reservation) | `/sdd-spec` | `base_branch` |
| 2. Decompose | tasks + per-spec index (+ TASK-ID reservation) | `/sdd-task <spec>` | `base_branch` |
| 3. Implement | code + index/task state | `/sdd-start <task>` or the `sdd-worker` agent | feature worktree |
| 4. Review & finish | review, PR / merge, cleanup | `/sdd-codereview`, `/sdd-done <feat>` | feature branch → `base_branch` |

Flow types: `feature` bases on `dev` (or `staging` during a freeze), never
`main`; `hotfix` bases on `main`, reserves **no** FEAT/TASK IDs, is keyed by
its Jira issue, and normally skips `/sdd-task`.

---

## Implementing a task by hand (no `/sdd-*` commands)

1. **Pick the task.** Find it in `sdd/tasks/index/*.json` (skip `_orphans.json`).
   Its `status` must be `pending`, and every id in `depends_on` must be
   `done` in the index. Otherwise stop.
2. **Enter the feature worktree** (idempotent; never `git worktree add` by hand):
   ```bash
   python -m scripts.sdd.ensure_worktree --slug <slug> --feature-id FEAT-<NNN> \
     --spec sdd/specs/<slug>.spec.md --index sdd/tasks/index/<slug>.json
   ```
   All remaining steps happen **inside** the worktree, never on `base_branch`.
3. **Mark it in progress** in the per-spec index (`status: "in-progress"`,
   `started_at: <UTC ISO-8601>`) and commit only that index file.
4. **Read** the task file and its spec. Check known issues:
   `wikitoolkit ledger context <files the task touches>`.
5. **Verify the Codebase Contract** before writing code: confirm every
   "Verified Import" and "Existing Signature" in the source, never use
   anything under "Does NOT Exist". If an entry is stale, fix the contract in
   the task file first.
6. **Implement** exactly the files and names the task lists — no extra files,
   no redesign, no refactors outside scope (conventions:
   `.claude/rules/codebase-conventions.md`).
7. **Validate**: `ruff check --fix <files>`; run the task's
   `## Validation Commands` with `PYTHONPATH=packages/<dist>/src`; optionally
   the merge-tier selector
   `python -m scripts.sdd.select_tests --tier merge --base origin/<base_branch> --task-file <task.md> --run`.
   Never run a full-suite `pytest` by hand.
8. **Commit code** — stage only task files (never `git add .` / `-A`):
   `feat(<slug>): TASK-<NNN> — <title>`.
9. **Close the task** with the script (never a hand-rolled `mv`/copy — it
   leaves an orphan in `active/`):
   ```bash
   scripts/sdd/close_task.sh TASK-<NNN> <slug> verified   # or partial | forced
   ```
   Fill in the Completion Note of the moved file, then commit the staged SDD
   state: `sdd: complete TASK-<NNN> — <title>`. Push early.
10. **Finish the feature** with `/sdd-done FEAT-<NNN>`: it verifies every task,
    snapshots the ledger, pushes, and opens a PR against `base_branch`
    (`--merge` merges directly). It never pushes to or opens a PR against `main`.

If a task cannot be completed, set it `done-with-issues` and explain why in
the Completion Note. If the spec is ambiguous, stop and write it down there.

**Never allocate IDs by scanning files.** Reserve them:
`python -m scripts.sdd.reserve_ids --kind task|feature --count N --base-branch dev --label <slug>`.

---

## Task file format

Template: `sdd/templates/task.md`. Header: **Feature**, **Spec**, **Status**,
**Priority**, **Estimated effort**, **Depends-on**, **Assigned-to**. Sections:
Context · Scope (with *NOT in scope*) · Files to Create / Modify ·
**Codebase Contract** (Verified Imports / Existing Signatures / Does NOT
Exist) · Complexity Contract · Delegation Contract *(optional)* ·
Implementation Notes · Implementation Blueprint · Acceptance Criteria ·
Validation Commands · Test Specification · Agent Instructions · Completion Note.

Index `status` values: `pending` → `in-progress` → `done` | `done-with-issues`.

---

## Parallelism

Tasks whose `depends_on` are all `done` may run in parallel; the rest wait.
Parallel **features** never collide because each owns its per-spec index and
its own worktree. Within one feature, tasks run in that feature's worktree
(the `sdd-worker` orchestrator gives each parallel coder a sub-worktree).

---

## Ledger-Driven Fix Lane (`/sdd-fix`)

Findings verified but not fixed (e.g. deferred code-review items) go into the
work ledger: `wikitoolkit ledger open --kind … --severity … --discovered-from spec:FEAT-<NNN> --about sym:<file>#<symbol> --title … --body …`.
`/sdd-fix` drains it (`wikitoolkit ledger plan-fix --json`): `critical`/`major`,
any `vulnerability`, or unscoped groups go through the **SDD lane** (spec →
tasks → worktree → `/sdd-done`); single-file `minor`/`low` `tech_debt` go
through the **Fast lane** (branch `fix/<id>-<slug>` off `origin/dev`, always
`gh pr create --base dev`). `ledger claim` is authoritative; close with `ledger close --resolved-by`.

---

## Commands

| Command | Purpose |
|---|---|
| `/sdd-brainstorm` | Explore options and write a brainstorm |
| `/sdd-proposal` | Research-first proposal from Jira / text / file |
| `/sdd-fromjira` · `/sdd-tojira` | Brainstorm from a Jira ticket · export a spec to Jira |
| `/sdd-spec` | Write a spec (from exploration, a request, or an intake interview) |
| `/sdd-task <spec>` | Decompose a spec into tasks + per-spec index |
| `/sdd-start <task>` | Implement and close one task in the feature worktree |
| `/sdd-codereview <task>` | Review a completed task with adversarial cross-checks |
| `/sdd-done <feat>` | Verify, push, PR/merge, clean up |
| `/sdd-status` · `/sdd-next` | Task board · next unblocked tasks |
| `/sdd-fix [issue]` | Drain the work ledger |
| `/sdd-explain <target>` | Code-grounded architecture map or trace |
| `/sdd-insight` | Collaboration and SDD-adherence report |
| `/remove-worktree` | Safely remove stale or finished worktrees |

Codex uses the same workflow via `.agents/skills/sdd-*` (`$sdd-*`).

---

## Quality rules

1. Touch only the files the task lists; never refactor outside scope.
2. Verify before you reference — no guessed imports, attributes or methods.
3. Tests for every task; run them before committing.
4. One task = one code commit + one SDD-state commit, both on the feature branch.
5. State changes go through the per-spec index and `close_task.sh` — never the legacy monolith.
6. Ambiguity goes into the Completion Note, not into an improvised design.
