---
id: F005
query_id: Q009
type: read
intent: Read build_slot_presence to assess reuse for non-ink-wall types
executed_at: 2026-10-09T20:49:59Z
duration_ms: 0
parent_id: null
depth: 0
---

# F005 — build_slot_presence depends only on definition + positions; no ink-wall assumptions

## Summary

`build_slot_presence` groups occupied-expected facings by `(shelf_id, position or slot)` walking `definition.shelves`, derives `found` per facing from `PositionResult.status` (`facing_presence`: MATCH/VARIANT_UNRESOLVED/INFERRED_PRESENT → True; MISMATCH/EMPTY → False; MISPLACED → True only above `misplaced_min_confidence`; NOT_VISIBLE/NOT_ASSESSED/CONFLICT → None), and emits one `SlotPresence` per slot with `model=first.product`, `sku`/`display_name` from descriptors, `brand`, `observed=position.identity`. Definitions without shelves yield `[]`. There is no ink-wall-specific branch; the module docstring says scoring is intentionally untouched.

## Citations

- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/presence.py`
  lines: 1-39
  symbol: `facing_presence`
  excerpt: |
    _FOUND = {FacingStatus.MATCH, FacingStatus.VARIANT_UNRESOLVED, FacingStatus.INFERRED_PRESENT}
    if position.status in _FOUND: return True, False, confidence
    if position.status is FacingStatus.MISPLACED:
        if confidence is not None and confidence >= policy.misplaced_min_confidence: return True, True, confidence
        return None, False, confidence
    if position.status in {FacingStatus.MISMATCH, FacingStatus.EMPTY}: return False, False, confidence

- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/presence.py`
  lines: 42-99
  symbol: `build_slot_presence`
  excerpt: |
    for shelf in definition.shelves:
        for facing in shelf.facings:
            if facing.expected_occupancy == "empty": continue
            key = (facing.shelf_id, facing.position if facing.position is not None else facing.slot)
    ...
    SlotPresence(shelf_id=first.shelf_id, shelf_level=shelf.level, slot=first.slot, position=first.position,
                 facing_ids=[...], model=first.product or "", sku=first.descriptors.sku, brand=first.brand,
                 display_name=first.descriptors.display_name, found=found, misplaced=misplaced, status=...,
                 confidence=confidence, facings=len(facings), facings_found=..., observed=...identity)
