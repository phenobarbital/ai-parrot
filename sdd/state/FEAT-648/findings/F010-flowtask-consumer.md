---
id: F010
query_id: Q012
type: read
intent: Downstream consumer of products_found (flowtask FEAT-564)
executed_at: 2026-10-09T20:49:59Z
duration_ms: 0
parent_id: null
depth: 0
---

# F010 — flowtask reads result['products_found'] type-agnostically; absent key → []

## Summary

The sibling repo spec `../flowtask/sdd/specs/planogram-ink-wall-changes.spec.md` (FEAT-564) makes flowtask's `PlanogramCompliance._execute_pipeline_on_row` read `result.get("products_found") or []`, put it in `compliance_analysis_json["products_found"]` and in a top-level object-dtype DataFrame column `products_found` (written via CopyToPg json_columns). It does not branch on `planogram_type`; a missing key yields `[]`. So once ai-parrot fills the key for endcap rows, flowtask persists it with no change.

## Citations

- path: `../flowtask/sdd/specs/planogram-ink-wall-changes.spec.md`
  lines: 34-53, 72-79, 99-104, 113-132
  symbol: `_products_found(result)`, `_post_process_results`
  excerpt: |
    `PlanogramCompliance._execute_pipeline_on_row` reads `result.get("products_found") or []`.
    | ai-parrot pipeline result key `"products_found"` | depends on | FEAT-645; absent → `[]` |
    No new Pydantic model in flowtask. `products_found` is `List[Dict[str, Any]]`
