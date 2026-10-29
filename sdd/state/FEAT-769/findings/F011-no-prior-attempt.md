# F011 — Nothing to salvage: no unmerged branch does this work

**Merged from**: FG-003

<!-- merged from FG-003 -->
**Query**: Q013 · **Type**: git_log · **Depth**: 0

## Summary
`git branch -a --list '*semantic*'` returns three remote-only branches:
`origin/feat-FEAT-704-semantic-layer`, `origin/fix-semantic-packaging-test` and
`origin/feat-141-rust-semantic-text-splitter` (unrelated — Rust text splitter), plus five
stale local `sdd-coder` attempt sub-worktree branches
(`feat-FEAT-704-semantic-layer--TASK-4480-a1-…`, `…TASK-4481-a1-…`, `…TASK-4702-a1-…`).
Both relevant remote branches are **0 commits ahead of `origin/dev`**
(`git rev-list --count origin/dev..origin/feat-FEAT-704-semantic-layer` → `0`;
`git log origin/dev..origin/fix-semantic-packaging-test` → empty), and
`git log origin/dev..origin/feat-FEAT-704-semantic-layer -- examples/` is empty.
So the branch recorded as a "salvage-only source" holds nothing `dev` does not already
have — there is no hidden prior attempt at `examples/agents/semantic/` to recover, and
FEAT-769 starts from a clean `dev`. The five local `--TASK-…-a1-…` branches are leftover
coder-pool attempt branches and should not be mined or re-entered.

## Citations
- `git branch -a --list '*semantic*'` → remote-only: `feat-FEAT-704-semantic-layer`, `fix-semantic-packaging-test`, `feat-141-rust-semantic-text-splitter`
- `git rev-list --count origin/dev..origin/feat-FEAT-704-semantic-layer` → `0`
- `git log --oneline origin/dev..origin/fix-semantic-packaging-test` → no commits
- Latest `dev` commit touching the package: `07adb66f` (2026-10-28) `fix(semantic-layer): unpin version and update CI sync assertion in packaging test`

## Notes
Stale sub-worktree branches exist; `/remove-worktree` territory, out of scope for FEAT-769.
