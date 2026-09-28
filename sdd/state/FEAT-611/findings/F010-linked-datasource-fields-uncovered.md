---
id: F010
query_id: Q010
type: read
intent: LinkedDataSource feature surface not exercised by FEAT-610
executed_at: 2026-09-28T20:30:00Z
parent_id: null
depth: 0
---
# F010 — LinkedDataSource fields FEAT-610 never touches

## Summary
FEAT-610 uses only public slugs with fields/filter/group_by. Unexercised: tenant, is_multiquery/multi_output, params/locked ParamSpec, transform.ops DSL (10 ops), transform.ref, refresh policy (on_mount|manual|interval>=30s; no on_param_change), request.ordering/limit/offset, snapshot=False.

## Citations
- path: `packages/ai-parrot/src/parrot/outputs/a2ui/linked/models.py`
  lines: 192-223
  symbol: `LinkedDataSource`
- path: `packages/ai-parrot/src/parrot/outputs/a2ui/linked/models.py`
  lines: 19-56
  symbol: `ParamSpec`, refresh policy
- path: `packages/ai-parrot/src/parrot/outputs/a2ui/linked/models.py`
  lines: 59-175
  symbol: transform ref / ops
- path: `packages/ai-parrot/src/parrot/outputs/a2ui/linked/executor.py`
  lines: 153-177
  symbol: param override rules (locked/undeclared -> ignored_params)
- path: `packages/ai-parrot/src/parrot/outputs/a2ui/linked/executor.py`
  lines: 201-215
  symbol: tenant passthrough, DSL run off-loop, transform.ref skipped
- path: `packages/ai-parrot/src/parrot/outputs/a2ui/linked/dsl.py`
  symbol: Python DSL
- path: `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/dsl.ts`
  symbol: TS DSL
- path: `packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/dsl/`
  symbol: 17 DSL golden fixtures
- path: `packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/envelopes/linked_no_snapshot.json`
- path: `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/scheduler.ts`
  symbol: interval scheduler (pauses on document.hidden)

## Notes
Nothing in admin UI calls refreshAll() besides A2UISurface.svelte:105 proxy; manual sources only refresh via FilterBar setParam.
