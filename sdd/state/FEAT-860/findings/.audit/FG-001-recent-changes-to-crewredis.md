---
id: FG-001
query_id: Q018
type: git_log
intent: "Recent changes to CrewRedis (tenant keys FEAT-446, extra=forbid compat)."
executed_at: 2026-11-09T17:16:00Z
duration_ms: 900
parent_id: null
depth: 0
---

# FG-001 — Recent history of CrewRedis (redis_persistence.py)

## Summary

Plain `git log origin/dev --follow` (180 days) shows only 4 commits on
`redis_persistence.py`: the satellite move (2026-05-29), a logging fix, the
`extra="forbid"` read-compat fix (60811a57bd, 2026-08-17) and the flow-authoring
review fix (3f6a5d3ffa, 2026-08-20). The tenant-hardening commit 413d4067a8
(2026-08-24, saas-auth-hardening) changed this file by 75 lines but is hidden
by default history simplification — `--full-history` is needed to see it.
Design rule carried by 60811a57bd: the persistence layer, not the model, drops
unknown keys on read and logs them, so historical rows stay loadable.

## Citations

- sha: `434423d45b`
  date: 2026-05-29
  author: Jesus
  message: "feat(ai-parrot-server): TASK-1371 — Move handlers/ to satellite"
  files: `packages/ai-parrot-server/src/parrot/handlers/crew/redis_persistence.py` (moved from core)

- sha: `5ae58a2fb7`
  date: 2026-05-29
  author: Jesus
  message: "fix(feat-203): convert all f-string logger calls to %-style formatting across satellite"

- sha: `60811a57bd`
  date: 2026-08-17
  author: Claude
  message: "fix(crew): keep already-stored crews loadable under extra=\"forbid\""
  files: `packages/ai-parrot-server/src/parrot/handlers/crew/redis_persistence.py` (+19), `packages/ai-parrot-server/src/parrot/handlers/flow_authoring.py` (+8)
  excerpt: |
    Strictness exists to stop a *new* definition from silently dropping a
    field; refusing to read historical data is not part of that job. The
    persistence layer drops unknown keys and logs which ones, so the crew stays
    loadable and the drift stays visible.

- sha: `3f6a5d3ffa`
  date: 2026-08-20
  author: Jesus
  message: "fix(flows): address code-review findings on workflow authoring"
  excerpt: |
    `CrewDefinition.validate_flow_relations` rejected relations written
    against an `agent_id`, making previously-loadable crews raise inside
    `CrewRedis._deserialize_crew`. Those references are now accepted and
    normalised to the canonical display name

- sha: `413d4067a8`
  date: 2026-08-24
  author: Jesus Lara
  message: "fix(saas-auth-hardening): close cross-tenant gaps found in code review"
  files: `packages/ai-parrot-server/src/parrot/handlers/crew/redis_persistence.py` (75 lines), `packages/ai-parrot/src/parrot/models/crew_definition.py` (68 lines), `packages/ai-parrot-server/src/parrot/handlers/crew/handler.py` (20), `packages/ai-parrot-server/src/parrot/handlers/crew/execution_handler.py` (84), `examples/crew/redis_persistence_example.py` (8); 19 files total
  note: not listed by `git log origin/dev -- <path>` (with or without --follow); found via `git log --grep=FEAT-446`.

## Notes

- Any Postgres backend must reproduce the read-side compat path: `_deserialize_crew` +
  unknown-key stripping (60811a57bd) and the agent_id → display-name relation normalisation
  (3f6a5d3ffa) — otherwise rows migrated from Redis could fail to load.
- Tenant key layout (`crew:{tenant}:{name}`) predates the 180-day window as visible
  through `--follow`; 413d4067a8 is the latest cross-tenant hardening.
- [cross-lane: type=read, intent=confirm _deserialize_crew / unknown-key stripping and tenant handling in current redis_persistence.py so the Postgres backend can share them]
