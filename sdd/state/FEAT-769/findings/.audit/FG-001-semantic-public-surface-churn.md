# FG-001 — The Semantic Layer public surface landed in one burst on 2026-10-26 and has been frozen for 3 days

**Query**: Q013 · **Type**: git_log · **Depth**: 0

## Summary
Every file an example would import from (`toolkit.py`, `models.py`, `context.py`,
`handoff.py`, `results.py`, `bootstrap.py`, `loader.py`, `policy.py`) was last
touched on **2026-10-26**; there is no public-symbol change in the 3 days since.
That burst is the FEAT-704 implementation itself (TASK-4464…TASK-4481, TASK-4702,
TASK-4707…TASK-4710) plus four same-day ledger-fix commits that changed *behaviour*,
not just internals: `0ac263168` (refuse to override foreign RLS rules, track owned
keys on reload), `32a7762ee` (return pre-RLS SQL to callers, keep governed SQL in the
audit only), `c3e2049de` (metric-only column masks, exact truncation, read-time usage
recheck — touching `bootstrap.py`, `handoff.py`, `loader.py`, `policy.py`, `toolkit.py`
in a single commit) and `ae7e21f16` (read-only governed DuckDB connections, duplicate
column disambiguation). The three commits *after* that date — `ef85c5035`, `9a953146d`,
`07adb66f0` — touched only the example, the doc and tests, never `src/parrot/semantic/`.
Verdict: the surface is settled enough to write examples against, but anything written
must be pinned to the post-`c3e2049de` semantics (pre-RLS SQL returned to callers,
metric-only masks, read-only DuckDB), because the pre-2026-10-26 shape is gone.

## Citations
- `packages/ai-parrot-semantic/src/parrot/semantic/toolkit.py` (+ `bootstrap.py`, `handoff.py`, `loader.py`, `policy.py`) — commit `c3e2049d` (2026-10-26) `fix(semantic-layer): metric-only column masks, exact truncation, precise audit pbac, read-time usage recheck (issue:7e1d9700c5c1)`
- `packages/ai-parrot-semantic/src/parrot/semantic/` — commit `32a7762e` (2026-10-26) `fix(semantic-layer): return pre-RLS SQL to callers, keep governed SQL in the audit only (issue:22fbd14d96a9)`
- `packages/ai-parrot-semantic/src/parrot/semantic/` — commit `0ac26316` (2026-10-26) `fix(semantic-layer): refuse to override foreign RLS rules and track owned keys on reload (issue:e3ff9bfb4a83)`
- `packages/ai-parrot-semantic/src/parrot/semantic/` — commit `ae7e21f1` (2026-10-26) `fix(semantic-layer): read-only governed DuckDB connections, disambiguate duplicate column names`
- `packages/ai-parrot-semantic/tests/test_packaging.py` — commit `07adb66f` (2026-10-28) `fix(semantic-layer): unpin version and update CI sync assertion in packaging test` (no `src/` change)

## Notes
[cross-lane: type=read, intent=confirm the current signatures in `toolkit.py`/`handoff.py` as of `c3e2049d`, since any example written against an older memory of the API will be wrong]
