---
id: F008
query_id: Q008
type: read
intent: "What does the over-broad test-command guard rewrite a command to?"
executed_at: 2026-11-04T22:37:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F008 — The broad-test guard rewrites to `python scripts/sdd/select_tests.py`, a path that exists only in ai-parrot

## Summary

`VERDICT_ARGV` hard-codes a bare `python` and the repo-relative path
`scripts/sdd/select_tests.py`. That file exists at the ai-parrot repository root; the
installer ships no `scripts/sdd/` target, and the packaged entry point is
`parrot sdd tests select`. The guard is wired into the Bash hook through
`worktree_environment.py`, whose runner heads include `vitest`, `pnpm` and `npx`.

## Citations

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/guard.py`
  lines: 21-21
  symbol: `VERDICT_ARGV`
  excerpt: |
    VERDICT_ARGV: tuple[str, ...] = ("python", "scripts/sdd/select_tests.py", "--tier", "task", "--run", "--verdict")

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/guard.py`
  lines: 73-120
  symbol: null
  excerpt: |
    argvs=((*VERDICT_ARGV, "--worktree", str(worktree)),),
    verdict_argv = (*VERDICT_ARGV, "--worktree", str(worktree))

- path: `packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py`
  lines: 333-360
  symbol: `_RUNNER_HEADS`
  excerpt: |
    from test_scope.guard import guard_bash
    _RUNNER_HEADS = frozenset({"pytest", "python", "python3", "vitest", "pnpm", "npx", "cargo", "uv"})

## Notes

`ls scripts/sdd/select_tests.py` succeeds in ai-parrot; `grep -c "scripts/sdd"
sdd/_assets/manifest.json` → 0. A broad `pnpm test` in a target repository is rewritten
to a command that cannot start there.
