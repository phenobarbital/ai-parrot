---
id: F009
query_id: Q018
type: read
intent: "Presence evaluation — maps to 'graphic is present'."
executed_at: 2026-11-06T16:07:00Z
duration_ms: 400
parent_id: null
depth: 0
lanes: [codebase]
merged_from: [FC-009]
---
# F009 — presence.py reports product facings only; zone presence is the zone_present rule

## Summary

`comparison/presence.py` ("Pure reporting of expected model presence; scoring is intentionally unchanged") builds `SlotPresence` entries by walking `definition.shelves[].facings`. A zone-only row has no facings (`"shelves": []`, F002/F003), so `products_found` is empty for both EcoTank planograms and the "Slot Presence" block of the downstream report never appears. "Graphic is present" is decided only by the `zone_present` rule (F008).

## Citations

- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/presence.py`
  lines: 1-1
  symbol: `(module docstring)`
  excerpt: |
    """Pure reporting of expected model presence; scoring is intentionally unchanged."""
- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/presence.py`
  lines: null
  symbol: `build_slot_presence`
  excerpt: |
    for shelf in definition.shelves:
        for facing in shelf.facings:
            if facing.expected_occupancy == "empty":
                continue
            key = (facing.shelf_id, facing.position if facing.position is not None else facing.slot)
            groups.setdefault(key, []).append(facing)

## Notes

Line numbers for `build_slot_presence` were not captured (the file was read with blank lines stripped); the file is 100 lines long.
