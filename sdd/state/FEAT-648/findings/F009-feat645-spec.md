---
id: F009
query_id: Q004
type: read
intent: FEAT-645 spec: the products_found contract and its explicit non-ink-wall decision
executed_at: 2026-10-09T20:49:59Z
duration_ms: 0
parent_id: null
depth: 0
---

# F009 — FEAT-645 deliberately scoped products_found to ink_wall ([] for other types)

## Summary

FEAT-645 (`sdd/specs/planogram-ink-wall-slot-presence.spec.md`, status approved, 2026-10-08) introduced `SlotPresence`, `ReportingPolicy`, `effective_reporting`, `presence.py`, `LayoutProfile.reporting` and the result key. Its test matrix explicitly requires `test_non_ink_wall_result_unchanged`: an endcap / product_on_shelves run yields `products_found == []` (spec line 329; implemented at test_ink_wall.py:546-613 with `planogram_type="product_on_shelves"`). AC line 354: "The pipeline result dict and the aiohttp handler expose `products_found` (empty list when presence is off)". The gotchas note slot-level dedup exists only in `products_found` and that a {EMPTY, NOT_VISIBLE} slot reports `found=None`. This proposal reverses the "other types → []" decision.

## Citations

- path: `sdd/specs/planogram-ink-wall-slot-presence.spec.md`
  lines: 49, 85-95, 144-148, 328-330, 351-354, 466-475
  symbol: (G2, wiring, test matrix, acceptance criteria, gotchas)
  excerpt: |
    | `test_non_ink_wall_result_unchanged` | an endcap / product_on_shelves fixture run: `products_found == []`, lists identical to before |
    - [ ] The pipeline result dict and the aiohttp handler expose `products_found` (empty list when presence is off).

- path: `packages/ai-parrot-pipelines/tests/planogram_cycle/test_ink_wall.py`
  lines: 546-613
  symbol: `test_non_ink_wall_result_unchanged`
  excerpt: |
    config = PlanogramConfig(planogram_type="product_on_shelves", planogram_config={"brand": "Acme"},
                             slots_definition=synthetic_slots_definition)
    ...
    assert comparison.products_found == []
    assert assembled["products_found"] == []

- path: `packages/ai-parrot-pipelines/tests/planogram_cycle/test_ink_wall.py`
  lines: 616-630
  symbol: `test_reporting_meta_override_reaches_pipeline`
  excerpt: |
    synthetic_slots_definition["meta"] = {"reporting": {"product_label": "display_name", "slot_presence": False}}
    ...
    assert result["products_found"] == []
