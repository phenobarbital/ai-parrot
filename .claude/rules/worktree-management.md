---
description: Single source of truth for git worktrees in this repo — where they live, how they are created, how to work inside one, how to finish and clean up. Replaces using-git-worktrees, worktree-start-feature, worktree-status and worktree-pr-and-clean.
---

# Worktree Management

Worktrees isolate **features** from each other: one worktree per feature (or
hotfix); the tasks of a feature run sequentially inside that same worktree.
Branch *policy* (which base each flow type uses, sync-down, `/sdd-done` never
targeting `main`) lives in `CLAUDE.md` § Git Configuration — this file is the
how-to.

## 1. Where they live, how they are named

- Always under `.claude/worktrees/` (git-ignored). Never `.worktrees/`, never a global directory.
- Names come from `scripts.sdd.sdd_meta.plan_worktree`, never invented:
  - feature → `feat-<FEAT-ID>-<slug>` (the doubled `feat-FEAT-` prefix is intentional — `/sdd-done` greps on it)
  - hotfix → `hotfix-<JIRA-KEY>-<slug>`
- Base ref is **always `origin/<base_branch>`** — `dev` (or `staging` during a freeze) for features, `main` for hotfixes — never `HEAD`, so a worktree can never inherit an unpushed local commit (FEAT-466).

## 2. Create (idempotent)

```bash
source .venv/bin/activate
python -m scripts.sdd.ensure_worktree --slug <slug> --feature-id FEAT-<NNN>   # feature → origin/dev
python -m scripts.sdd.ensure_worktree --slug <slug> --jira-key <JIRA-KEY>     # hotfix  → origin/main
```

- Created by whoever implements: `/sdd-start`, `sdd-worker`, and the dev-loop orchestrators (`sdd-planner`, `sdd-research`, `sdd-autopilot`). `/sdd-task` creates none (FEAT-552).
- **Never** `claude --worktree` (it branches from `main`, which has no SDD artifacts) and never hand-build `git worktree add` for SDD work.
- Skip the worktree entirely for docs-only changes, single-commit fixes, single-task specs and brainstorms — work on a plain branch.

## 3. Inspect

```bash
git worktree list                         # primary checkout + every worktree
git -C <path> rev-parse --abbrev-ref HEAD  # branch
git -C <path> status --porcelain           # empty = clean
```

The active worktree is the one whose branch matches the feature at hand; with
several candidates prefer the newest `feat-*` / `hotfix-*` entry. Report
**path, branch, clean / not clean**, and remind: *all feature edits happen
inside `<path>`* — never in the primary checkout.

## 4. Work inside

- Run git as `git -C <path> ...` (or `cd` in). Small commits, one task per commit, and **push early** (`git push -u origin <branch>`): other sessions may merge or `reset --hard` the shared tree, and only pushed commits are safe.
- The shared `.venv` is editable-installed against the **main checkout**, so a bare `pytest` inside a worktree imports the wrong branch. Prefix with `PYTHONPATH=packages/ai-parrot/src` (one entry per changed package). Never `uv sync` inside a worktree — it repoints the shared venv's `.pth` and breaks `import parrot` for every session once the worktree is removed.
- Shared environments are read/execute-only for worktree agents. Use installed tools directly or `uv run --no-sync`; `uv add --no-sync` may update scoped dependency declarations without installing. Dependency installation requires a real task-local environment with an explicit interpreter target, or a controlled installation by the main-checkout operator. Agents must not switch to the main checkout to perform that installation themselves.
- SDD in-process commands and native Claude Bash hooks use Bubblewrap filesystem protection. The checkout, Git metadata, the primary checkout's `.claude/worktrees/` (so `/sdd-done` can add the ledger-snapshot worktree and remove the feature worktree from inside it) and the primary checkout's `.parrot/ledger/` (so `wikitoolkit ledger open/claim/close` work from inside a worktree) are writable; the rest of the primary checkout and shared environments are mounted read-only, with private temporary storage — except Claude Code's scratchpad root (`/tmp/claude-<uid>`), which is bound back in so the session scratchpad persists across Bash calls. Missing Bubblewrap or denied namespaces must stop execution, never trigger an unsandboxed retry. Other CLI hosts must provide equivalent protection. Command allowlists and prompt rules alone do not guarantee this policy.
- Run the tests your task names; do not start with a full baseline sweep.

## 5. Finish

- Working tree clean, branch pushed.
- SDD lane: `/sdd-done <FEAT-ID>` verifies the tasks, stamps the index, merges feature → `base_branch` and cleans up.
- Ad-hoc lane: `gh pr create --base <base_branch> --head <branch> --title "..." --body "..."` — never against `main` for a feature. If `gh` is missing or unauthenticated, hand the user the exact commands instead.

## 6. Clean up

```bash
/remove-worktree                          # list first; refuses worktrees with a live sdd-worker
git worktree remove .claude/worktrees/<name>
git worktree prune                        # drop stale admin data
```

Never remove a worktree with uncommitted changes, never `--force` unless the
user explicitly asks, and look for orphan directories under
`.claude/worktrees/` that `git worktree list` no longer knows about —
`/remove-worktree` handles those; `prune` does not.
