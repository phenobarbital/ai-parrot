---
id: F013
query_id: Q012
type: git_log
intent: Is the same code on main (hotfix vs feature base)?
executed_at: 2026-09-02T13:44:30+02:00
duration_ms: 900
parent_id: null
depth: 0
---

# F013 — `origin/main` and `dev` are byte-identical on all three affected files

## Summary

`git diff --stat origin/main..dev -- repl_worker/ pythonpandas.py pythonrepl.py` prints nothing; the last commit on `handle.py` reachable from `origin/main` is `c7b512a90` (2026-07-28), same as on `dev`. The bug therefore ships in the current release — a `type: hotfix` flow based on `main` is viable and would propagate to `dev`/`staging` via sync-down.

## Citations

- path: `packages/ai-parrot/src/parrot/tools/repl_worker/handle.py`
  excerpt: |
    $ git log origin/main -1 -- .../repl_worker/handle.py
    c7b512a90 2026-07-28 fix(sandbox-hardening): address code-review findings across Modules 1-8
