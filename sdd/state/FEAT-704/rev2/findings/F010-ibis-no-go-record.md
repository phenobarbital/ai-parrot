---
id: F010
query_id: Q010
type: read
intent: "Read the recorded Ibis NO-GO decision and how FEAT-704 reused it to reject BSL"
executed_at: 2026-10-25T10:50:00Z
duration_ms: 3000
parent_id: null
depth: 0
---

# F010 — Ibis NO-GO (TASK-1437, 2026-06-03) was about connection mapping, and FEAT-704 reused it to reject BSL-over-Ibis

## Summary

TASK-1437's Completion Note records NO-GO because the asyncpg DSN format does not match psycopg/libpq, BigQuery needs a `google.oauth2.Credentials` shim, and two SQL templates were simpler than a heavy dependency; `ibis-framework` was never added. `dataset_manager/spatial/compiler.py:19` cites it. The FEAT-704 brainstorm turned that into "Ibis was already rejected in this repo", listing it as the first con of Option A (BSL), and the spec codified it as a Non-Goal (F002). The reasoning concerned Ibis *connections*; compile-only `ibis.to_sql` on unbound tables (the research's joins-phase idea) was not evaluated by TASK-1437.

## Citations

- path: `sdd/tasks/completed/TASK-1437-ibis-connection-spike.md`
  lines: 124-134
  symbol: `## Completion Note`
  excerpt: |
    **Decision**: NO-GO — TASK-1438 uses hand-written SQL dialect templates; `ibis-framework` is NOT added to `pyproject.toml`.
    - pg DSN: asyncpg DSN format (asyncpg://...) ≠ psycopg/libpq format — non-trivial translation gap
    - bigquery: [...] ibis expects google.oauth2.Credentials object — requires from_service_account_file() shim

- path: `packages/ai-parrot/src/parrot/tools/dataset_manager/spatial/compiler.py`
  lines: 19
  symbol: module docstring
  excerpt: |
    - TASK-1437 resolved NO-GO for Ibis — two hand-written SQL dialect templates are used.

- path: `sdd/proposals/semantic-layer.brainstorm.md`
  lines: 52-54, 122-124
  symbol: `Option A` cons
  excerpt: |
    3. **Ibis was already rejected in this repo**: TASK-1437 (FEAT-219) resolved **NO-GO** for Ibis;
    - **Contradicts a recorded repo decision**: TASK-1437 resolved NO-GO for Ibis (connection
    - Pin `ibis-framework<12` while Ibis 12.0.0 is out since 2026-02-07; two-maintainer project.

- path: `packages/ai-parrot/src/parrot/tools/dataset_manager/spatial/_ibis_probe.py`
  lines: 1-5
  symbol: throwaway probe
  excerpt: |
    THROWAWAY: Ibis connection spike for FEAT-219 Module 2.

## Notes

"BSL reserved for the joins phase" is therefore not free: it needs the NO-GO to be explicitly re-scoped (connections stay NO-GO; compile-only may be evaluated) in whatever spec opens the joins phase.
