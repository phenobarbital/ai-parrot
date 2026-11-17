---
id: F011
query_id: Q011
type: grep
intent: "Does any SDD or dev-loop code install dependencies into a new worktree?"
executed_at: 2026-11-04T22:45:00Z
duration_ms: 0
parent_id: F003
depth: 1
---

# F011 — Nothing installs dependencies into a new worktree

## Summary

`grep -rnE 'node_modules|pnpm install|npm (ci|install)|package\.json'` over
`sdd/scripts` and `flows/dev_loop` returns only an ignore list, a write-deny rule and
the vitest `package.json` check. `ensure_worktree` runs `git worktree add` and the
native artifact sync (F003) and nothing else. In `navigator-frontend-next` the one live
SDD worktree has its own real `node_modules` directory, which the tooling cannot have
created.

## Citations

- path: `packages/ai-parrot/src/parrot/sdd/scripts/dangerous_actions.py`
  lines: 377-377
  symbol: null
  excerpt: |
    if "/node_modules/" in slashed or "/.git/objects/" in slashed:

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/replication.py`
  lines: 52-52
  symbol: null
  excerpt: |
    "/node_modules/", "/site-packages/", "/dist-packages/", "/.venv/",

- path: `packages/ai-parrot/src/parrot/sdd/scripts/ensure_worktree.py`
  lines: 442-451
  symbol: `main`
  excerpt: |
    if not args.dry_run and not args.no_native_sync:
        ...
            native = sync_native_artifacts(

## Notes

Observed in `/home/jesuslara/proyectos/navigator/navigator-frontend-next/.claude/worktrees/
feat-FEAT-099-vault-crypto-hardening`: `node_modules` is a real directory dated
2026-09-16, and `pnpm exec vitest --version` prints `vitest/3.2.7` there.
Lane report (inferred from the mount table, not executed): the bubblewrap sandbox mounts
`/` read-only, so an install from inside the sandbox cannot write a user-level package
store, and the native sandbox's `strictAllowlist` blocks the registry (F002). A setup
step therefore has to run on the host, at worktree creation.
