---
id: F012
query_id: Q008
type: read
intent: Output contract: SlotPresence model, _assemble, handler; docs coverage
executed_at: 2026-10-09T20:49:59Z
duration_ms: 0
parent_id: null
depth: 0
---

# F012 — SlotPresence is the structure to reuse; docs do not mention products_found

## Summary

`SlotPresence` (contracts.py:231-249) carries shelf_id, shelf_level, slot, position, facing_ids, model, sku, brand, display_name, found (Optional[bool]), misplaced, status (FacingStatus), confidence, facings, facings_found, observed. `_assemble` (plan.py:505-540) emits it additively next to `position_results`, `shelf_scores`, etc. `docs/pipelines/planogram-compliance-cycle.md` is the only doc mentioning `ink_wall`, and it contains **no** mention of `reporting`, `slot_presence`, `products_found` or `ReportingPolicy` (grep empty) — a documentation gap this feature should close.

## Citations

- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py`
  lines: 231-249
  symbol: `SlotPresence`
  excerpt: |
    class SlotPresence(BaseModel):
        shelf_id: str; shelf_level: Optional[str] = None; slot: int; position: Optional[int] = None
        facing_ids: List[str]; model: str; sku: Optional[str] = None; brand: Optional[str] = None
        display_name: Optional[str] = None; found: Optional[bool] = None; misplaced: bool = False
        status: FacingStatus; confidence: Optional[float] = None; facings: int = 1; facings_found: int = 0
        observed: Optional[str] = None

- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py`
  lines: 218-228
  symbol: `PositionResult`

- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py`
  lines: 505-540
  symbol: `PlanogramCompliance._assemble`

- path: `docs/pipelines/planogram-compliance-cycle.md`
  lines: (whole file)
  symbol: —
  excerpt: |
    (no matches for reporting|slot_presence|products_found|product_label|ReportingPolicy)
