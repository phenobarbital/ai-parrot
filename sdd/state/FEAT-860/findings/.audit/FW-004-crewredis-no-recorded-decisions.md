---
id: FW-004
query_id: Q002
type: wiki_query
intent: "Capture recorded design decisions (ADRs) for CrewRedis."
executed_at: 2026-11-09T17:13:12Z
duration_ms: 150
parent_id: FW-002
depth: 1
---

# FW-004 — No ADR or inferred decision is recorded for CrewRedis

## Summary

`wiki_decisions_for_symbol("CrewRedis")` returned `status: empty` — no documented decisions and no inferred
candidates. Nothing in the decision plane fixes Redis as the required store for crew definitions, so a
Postgres backend does not supersede a recorded decision; the proposal would be the first one.

## Citations

- path: `packages/ai-parrot-server/src/parrot/handlers/crew/redis_persistence.py`
  lines: 17-17
  symbol: `CrewRedis`
  excerpt: |
    {"status": "empty", "documented": [], "candidates": [], "alternatives": []}

## Notes

A spec for this feature should add a Decisions block (sym: targets) so the choice is recorded.
