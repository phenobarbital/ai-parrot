---
description: Single source of truth for git worktrees in this repo — where they live, how they are created, how to work inside one, how to finish and clean up. Replaces using-git-worktrees, worktree-start-feature, worktree-status and worktree-pr-and-clean.
---

# Worktree Management

Worktrees isolate **features** from each other: one worktree per feature (or
hotfix); the tasks of a feature run sequentially inside that same worktree.
Branch *policy* (which base each flow type uses, sync-down, `/sdd-done` never
targeting the hotfix base) lives in `sdd/WORKFLOW.md` § Git Configuration — this file is the
how-to.

## 1. Where they live, how they are named

- Always under the worktree root (default `.parrot/worktrees/`, override with an exported `WORKTREE_BASE_PATH`) (git-ignored). Never `.worktrees/`, never a global directory.
- Names come from `parrot.sdd.scripts.sdd_meta.plan_worktree`, never invented:
  - feature → `feat-<FEAT-ID>-<slug>` (the doubled `feat-FEAT-` prefix is intentional — `/sdd-done` greps on it)
  - hotfix → `hotfix-<JIRA-KEY>-<slug>`
- Base ref is **always `origin/<base_branch>`** — `dev` (or `staging` during a freeze) for features, `main` for hotfixes — never `HEAD`, so a worktree can never inherit an unpushed local commit (FEAT-466).

## 2. Create (idempotent)

```bash
if [ -f .venv/bin/activate ]; then source .venv/bin/activate; fi   # only a repo with a project venv
parrot sdd worktree ensure --slug <slug> --feature-id FEAT-<NNN>   # feature → origin/<base_branch>
parrot sdd worktree ensure --slug <slug> --jira-key <JIRA-KEY>     # hotfix  → origin/<hotfix_base>
parrot sdd worktree ensure --slug <slug> --brief-key <KEY> --base-branch <branch>   # /sdd-brief → hotfix-<KEY>-<slug> / fix-<KEY>-<slug>
```

`ensure()` clears the auto-set upstream of a fresh worktree branch (FEAT-698), so the first push is an explicit `git push -u origin <branch>`.

- Created by whoever implements: `/sdd-start`, `sdd-worker`, `/sdd-fix` (Fast lane, via `--brief-key <ledger-short-id> --base-branch <base_branch>`), and the dev-loop orchestrators (`sdd-planner`, `sdd-research`, `sdd-autopilot`). `/sdd-task` creates none (FEAT-552).
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

- Run git as `git -C <path> ...` (or `cd` in). Use small commits, one task per commit. From a trusted host shell, **push early** (`git push -u origin <branch>`): other sessions may merge or `reset --hard` the shared tree, and only pushed commits are safe. Never push from a worker sandbox.
- Run commands with the environment your repository documents (`sdd/CONVENTIONS.md` § Repository layout), and never reinstall a shared environment from inside a worktree.
- Compiled artifacts arrive with the worktree: `ensure_worktree` copies the native build artifacts a repository declares (for example under `[tool.parrot.worktree]` in its root `pyproject.toml`) from the main checkout on create and on reuse, and builds a missing one automatically. Never hand-copy `.so` files and never run `maturin develop` to repair a tree — it rewrites the shared environment. If a warning says a build failed, run the repository's documented native build yourself. Opt out with `--no-native-sync` / `--no-autobuild`.
- Shared environments are read/execute-only for worktree agents. Use installed tools directly or `uv run --no-sync`; `uv add --no-sync` may update scoped dependency declarations without installing. Dependency installation requires a real task-local environment with an explicit interpreter target, or a controlled installation by the main-checkout operator. Agents must not switch to the main checkout to perform that installation themselves.
- SDD in-process commands and native Claude Bash hooks use Bubblewrap filesystem protection. The checkout, Git metadata, the primary checkout's worktree root (so `/sdd-done` can add the ledger-snapshot worktree and remove the feature worktree from inside it), the primary checkout's `.parrot/ledger/` (so `wikitoolkit ledger open/claim/close` work from inside a worktree) and the primary checkout's sdd-coder evidence store (`${SDD_HOOKS_ARTIFACT_ROOT}`, so `parrot sdd task review prepare` and `finalize` can write; the rest of `artifacts/` stays read-only) are writable; the rest of the primary checkout and shared environments are mounted read-only, with private temporary storage — except Claude Code's scratchpad root (`/tmp/claude-<uid>`), which is bound back in so the session scratchpad persists across Bash calls. When `rtk` is on `PATH`, the native hook also passes each command through `rtk rewrite` (after the test-scope guard), so RTK runs inside the sandbox; `PARROT_SANDBOX_RTK=0` turns this off. RTK's data directory stays read-only, because it holds RTK's trust store for project `.rtk/filters.toml`; sandboxed runs are therefore not counted by `rtk gain`. Another `PreToolUse` hook that rewrites Bash input (RTK's global hook included) can replace the sandbox wrapper, so sandboxed sessions never load the `user` setting source (`issue:6756c929a450`): launch a worker with `parrot sdd launch worker <FEAT-ID|KEY>` (features and briefs; add `--tmux [--detach]` to run it unattended), and the dev-loop dispatcher forces the same for `sdd-worker`/`sdd-coder` seats. With `PARROT_SDD_SANDBOX_BACKEND` unset the hook runs each command natively when Claude Code's native sandbox is active and through Bubblewrap otherwise; `PARROT_SDD_SANDBOX_BACKEND=bubblewrap` forces the legacy wrapper. Missing Bubblewrap or denied namespaces must stop execution, never trigger an unsandboxed retry. Other CLI hosts must provide equivalent protection. Command allowlists and prompt rules alone do not guarantee this policy.
- Run the tests your task names; do not start with a full baseline sweep.
- Need a tree of the base ref (e.g. to check a failure is pre-existing)? `parrot sdd worktree baseline create --base origin/<base_branch>` — never `git archive` / a hand-built `git worktree add --detach`: those carry no gitignored `.so` files. Remove it with `parrot sdd worktree baseline remove <path>`.
- Need a base fix inside the sandbox? Run `parrot sdd worktree sync-base <FEAT-ID|KEY|name|path> --cherry-pick <sha>`. Never run `git fetch`, `git pull` or `git push` inside the worker sandbox. Full-base sync is a host operator action before starting the worker. If push-protection prerequisites are missing, ask the host operator to provision them; never change protected Git config. The host entry point prints the stale-base advisory; do not run that check inside the sandbox.

## 5. Finish

- Working tree clean, branch pushed.
- SDD lane: `/sdd-done <FEAT-ID>` verifies the tasks, stamps the index, pushes, opens a PR feature → `base_branch` (`main` included for a hotfix brief; `--merge` merges directly, but it never merges into `main`) and cleans up.
- Ad-hoc lane: `gh pr create --base <base_branch> --head <branch> --title "..." --body "..."` — never against `main` for a feature. If `gh` is missing or unauthenticated, hand the user the exact commands instead.

## 6. Clean up

```bash
/remove-worktree                          # list first; refuses worktrees with a live sdd-worker
git worktree remove "$WORKTREES_DIR/<name>"
git worktree prune                        # drop stale admin data
```

Never remove a worktree with uncommitted changes, never `--force` unless the
user explicitly asks, and look for orphan directories under
the worktree root that `git worktree list` no longer knows about —
`/remove-worktree` handles those; `prune` does not.

Users with worktrees under the legacy `.claude/worktrees/` must run the recipe `parrot self doctor` prints to migrate. Any line that names `.claude/worktrees` must also contain `git worktree repair` (the TASK-5183 guard test allows exactly those lines).

Untracked leftovers (logs or scratch files a tool left behind) are not uncommitted
changes, but `git worktree remove` refuses them too unless the path is gitignored. Park
them aside first — `/sdd-done` moves them to `${SDD_HOOKS_ARTIFACT_ROOT:-/tmp/claude-$(id -u)/sdd-hooks}/<FEAT-ID>/worktree-leftovers/` —
instead of forcing (issue:4a534ef4f3ee).
