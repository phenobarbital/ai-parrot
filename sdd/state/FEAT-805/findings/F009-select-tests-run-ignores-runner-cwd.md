---
id: F009
query_id: Q009
type: read
intent: "Does `select_tests --run` honour a runner's cwd and options for non-pytest runners?"
executed_at: 2026-11-04T22:52:00Z
duration_ms: 0
parent_id: F007
depth: 1
---

# F009 — `select_tests --run` (non-verdict) runs every invocation from the worktree root and appends a pytest flag

## Summary

Verdict mode runs each invocation in `worktree / invocation.cwd`. The plain `--run`
path calls `subprocess.run(argv, cwd=worktree)`, ignoring `invocation.cwd`, and appends
`--timeout=N` (a pytest-timeout flag) to every runner's argv. A vitest runner with a
`cwd` other than `"."` therefore runs from the wrong directory in this mode.

## Citations

- path: `packages/ai-parrot/src/parrot/sdd/scripts/select_tests.py`
  lines: 248-275
  symbol: `_run_verdict_mode`
  excerpt: |
    run_cwd = worktree / invocation.cwd
    ...
        cwd=run_cwd,

- path: `packages/ai-parrot/src/parrot/sdd/scripts/select_tests.py`
  lines: 497-521
  symbol: `main`
  excerpt: |
    argv = list(invocation.argv)
    if args.timeout is not None:
        argv.append(f"--timeout={args.timeout}")
    ...
        result = subprocess.run(argv, cwd=worktree)

## Notes

For a repository whose `package.json` is at the root (`cwd = "."`) the cwd defect is
latent; the `--timeout` append is not.
