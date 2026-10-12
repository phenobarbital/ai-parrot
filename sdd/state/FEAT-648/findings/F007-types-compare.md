---
id: F007
query_id: Q006
type: read
intent: Do the endcap / shelf types go through compare_observations?
executed_at: 2026-10-09T20:49:59Z
duration_ms: 0
parent_id: null
depth: 0
---

# F007 — All six types delegate compare() to compare_observations

## Summary

Every registered type's `compare()` returns `compare_observations(perceptions, identifications, ctx, description)`: EndcapBacklitMultitier (214-222), EndcapNoShelvesPromotional (96-103), ProductOnShelves (141-158, after fact-tag corroboration), GraphicPanelDisplay (94-101), ProductCounter (115-122), InkWall (126-142, on filtered registrable slots, then `model_copy(update={"position_results": ...})` which keeps `products_found`). Therefore enabling `slot_presence` is sufficient for `products_found` to be produced for any type.

## Citations

- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_backlit_multitier.py`
  lines: 214-222
  symbol: `EndcapBacklitMultitier.compare`
  excerpt: |
    self._ensure_layout(ctx)
    return compare_observations(perceptions, identifications, ctx, self._description())

- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_no_shelves_promotional.py`
  lines: 96-103
  symbol: `EndcapNoShelvesPromotional.compare`

- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py`
  lines: 141-158
  symbol: `ProductOnShelves.compare`
  excerpt: |
    return compare_observations(perceptions, corroborated, ctx, self._cycle_description())

- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/ink_wall.py`
  lines: 126-142
  symbol: `InkWall.compare`
  excerpt: |
    comparison = compare_observations(filtered, identifications, ctx, self._description())
    positions = self._price_notes(list(comparison.position_results), ctx.definition, filtered)
    return comparison.model_copy(update={"position_results": positions})
