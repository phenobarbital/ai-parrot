---
id: F003
query_id: Q008
type: read
intent: Read compare_observations: how products_found is produced and gated
executed_at: 2026-10-09T20:49:59Z
duration_ms: 0
parent_id: null
depth: 0
---

# F003 — compare_observations is type-agnostic; products_found gated only by ReportingPolicy.slot_presence

## Summary

`compare_observations` is the single shared compare stage. It canonicalises identifications, registers slots, merges positions, scores shelves, then resolves the reporting policy once via `effective_reporting(ctx.layout, definition)` and fills `products_found` with `build_slot_presence(...)` **only when `policy.slot_presence` is true**, otherwise `[]`. Nothing in this function is ink-wall specific: the gate is purely the policy flag.

## Citations

- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/stages/compare.py`
  lines: 188-231
  symbol: `compare_observations`
  excerpt: |
    positions = merge_positions(definition, registrations, canonical, ctx.credit_policy)
    ...
    policy = effective_reporting(ctx.layout, definition)
    comparison = comparison.model_copy(
        update={"products_found": build_slot_presence(positions, definition, policy) if policy.slot_presence else []}
    )
    return finalize_comparison(
        comparison,
        project_compliance(shelves, positions, definition, description, policy=policy, completeness=completeness),
    )

- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/stages/compare.py`
  lines: 11
  symbol: (import)
  excerpt: |
    from parrot_pipelines.planogram.comparison.presence import build_slot_presence
