---
id: F015
query_id: Q013
type: glob
intent: existing E2E coverage, fakes, latent bugs
executed_at: 2026-09-28T20:30:00Z
parent_id: null
depth: 0
---
# F015 — Existing E2E fakes everything external; latent TS/Python drift

## Summary
test_linked_surfaces_e2e.py (4 tests, integration tier, excluded from merge tier) fakes Postgres, QS/MultiQS (same FakeQS), QueryModel and an allow-all guard; refresh always params:{}. Svelte vitest wrappers skip (no node_modules). Latent bugs: conditions.ts emits limit (Python/fixture don't); offset:0 emitted by TS only; serverRefresh discards response; notices show "data as of never" (snapshotAt null); TS setParam no declared-param check.

## Citations
- path: `packages/ai-parrot-server/tests/integration/test_linked_surfaces_e2e.py`
  lines: 203-308
  symbol: FakeQS, fake guard, fake QueryModel
- path: `packages/ai-parrot-server/tests/ui/`
  symbol: test_vitest_a2ui_linked_*.py
- path: `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/conditions.ts`
  lines: 49-51
- path: `packages/ai-parrot/src/parrot/outputs/a2ui/linked/conditions.py`
  lines: 17-37
  symbol: `derive_conditions`
- path: `packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/conditions/limit_offset.json`
- path: `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/A2UISurface.svelte`
  lines: 146-153
- path: `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/index.ts`
  lines: 196-197
- path: `packages/ai-parrot-server/src/parrot/handlers/a2ui_transforms.py`
  lines: 44
  symbol: `publish_transforms` (no callers)
- path: `packages/ai-parrot/src/parrot/outputs/a2ui/linked/manifest.py`
  lines: 65-101
