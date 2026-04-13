# TASK-630: Add Illumination Enrichment to `ProductOnShelves.detect_objects()`

**Feature**: product-on-shelves-illumination
**Spec**: `sdd/specs/product-on-shelves-illumination.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-628
**Assigned-to**: unassigned

---

## Context

Module 3 of FEAT-091. `ProductOnShelves.detect_objects()` currently routes to
either `_detect_with_grid()` or `_detect_legacy()` and returns immediately.
After both paths complete, we need a common post-processing step that calls
`self._check_illumination()` once (cache result) and prepends the illumination
status string to the visual_features of each identified product that has
`illumination_required` in its raw config entry.

This enrichment is entirely opt-in: if no product config declares
`illumination_required`, the entire block is skipped and behaviour is identical
to before.

Spec section: §3 Module 3, Risk 2 (inject after both paths), Risk 4 (opt-in guard).

---

## Scope

- Refactor `detect_objects()` (lines 122-178) to collect results into local
  variables before returning, enabling a common post-processing area.
- In that post-processing area, scan the raw `planogram_config` shelves for any
  product dict with a truthy `illumination_required` key.
- If any are found: call `self._check_illumination(img, zone_bbox=bbox, roi=roi)`
  once per image (cache in local variable). Prepend the result string to
  `product.visual_features` of the matching identified product.
- If `_check_illumination` returns `None`, do NOT add anything to visual_features
  (graceful fallback — the compliance check will skip the penalty).
- Guard the entire enrichment block: `if not has_illumination_required: skip`.
- Only enrich products with `product_type == "promotional_graphic"` (or close
  variants) that also have `illumination_required` in the raw config.

**NOT in scope**: The compliance penalty logic (TASK-631). Any test files.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py` | MODIFY | Refactor `detect_objects()` to common post-processing + illumination enrichment |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# product_on_shelves.py already imports everything needed:
from .abstract import AbstractPlanogramType      # line 19
from PIL import Image                             # line 17
from parrot.models.detections import IdentifiedProduct  # line 25
# No new imports required for this task.
```

### Existing Signatures to Use

```python
# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py

class ProductOnShelves(AbstractPlanogramType):  # line 38

    async def detect_objects(              # line 122
        self,
        img: Image.Image,
        roi: Any,
        macro_objects: Any,
    ) -> Tuple[List[IdentifiedProduct], List[ShelfRegion]]:
        # Current structure (lines 155-178):
        grid_config = getattr(self.config, "detection_grid", None)
        if grid_config and grid_config.grid_type != GridType.NO_GRID:
            identified_products = await self._detect_with_grid(...)
            # applies ROI offset ...
            return identified_products, []       # ← line 173
        else:
            return await self._detect_legacy(...)  # ← line 176-178

# AFTER refactor, the structure should be:
#   if grid: identified_products, shelf_regions = ..., []
#   else:    identified_products, shelf_regions = await self._detect_legacy(...)
#   # --- common post-processing ---
#   [illumination enrichment here]
#   return identified_products, shelf_regions

# Raw config access pattern (already used at line 360 in check_planogram_compliance):
_pcfg = getattr(planogram_description, "planogram_config", None) or {}
raw_shelves = _pcfg.get("shelves", [])
# planogram_description comes from: self.config.get_planogram_description()

# AbstractPlanogramType._check_illumination (after TASK-628):
async def _check_illumination(
    self,
    img: Image.Image,
    zone_bbox: Optional[Any] = None,
    roi: Optional[Any] = None,
    planogram_description: Optional[Any] = None,
) -> Optional[str]: ...

# IdentifiedProduct (parrot/models/detections.py)
class IdentifiedProduct:
    product_model: str
    product_type: str
    shelf_location: str
    visual_features: List[str]   # prepend illumination result here
    detection_box: Optional[Any]  # has .x1, .y1, .x2, .y2 (pixel coords)
```

### Raw config illumination fields (NOT Pydantic — read from dict)

```python
# Raw product dict in planogram_config["shelves"][*]["products"][*]:
{
    "name": "Epson Scanners Header Graphic (backlit)",
    "product_type": "promotional_graphic",
    "illumination_required": "on",   # NEW — str, optional
    "illumination_penalty": 0.5,     # NEW — float, optional
}
# ShelfProduct Pydantic model does NOT have illumination_required or illumination_penalty.
# Must read from raw dict only.
```

### Does NOT Exist

- ~~`ShelfProduct.illumination_required`~~ — NOT a Pydantic field; read from raw dict
- ~~`ShelfProduct.illumination_penalty`~~ — NOT a Pydantic field; read from raw dict
- ~~`self.config.planogram_config`~~ — wrong; use `getattr(planogram_description, "planogram_config", None)`
  where `planogram_description = self.config.get_planogram_description()`
- ~~`ProductOnShelves._check_illumination()`~~ — does NOT exist directly; inherited from base after TASK-628

---

## Implementation Notes

### Refactored `detect_objects()` skeleton

```python
async def detect_objects(self, img, roi, macro_objects):
    planogram_description = self.config.get_planogram_description()

    # ... existing offset + target_image logic (unchanged) ...

    # Determine detection path: grid or legacy
    grid_config = getattr(self.config, "detection_grid", None)
    if grid_config and grid_config.grid_type != GridType.NO_GRID:
        self.logger.info("Using grid detection path (grid_type=%s).", grid_config.grid_type)
        identified_products = await self._detect_with_grid(
            target_image, planogram_description, grid_config
        )
        # Apply ROI offset to grid results (unchanged)
        for p in identified_products:
            if p.detection_box and (offset_x or offset_y):
                p.detection_box.x1 += offset_x
                ...
        shelf_regions: List[ShelfRegion] = []
    else:
        self.logger.info("Using legacy single-image detection path.")
        identified_products, shelf_regions = await self._detect_legacy(
            target_image, planogram_description, offset_x, offset_y
        )

    # ── Illumination enrichment (opt-in) ──────────────────────────────────────
    _pcfg = getattr(planogram_description, "planogram_config", None) or {}
    raw_shelves = _pcfg.get("shelves", [])
    # Build set of product names that require illumination check
    illum_products: set[str] = {
        rp["name"]
        for rs in raw_shelves
        for rp in rs.get("products", [])
        if rp.get("illumination_required")
    }

    if illum_products:
        illum_result: Optional[str] = None  # cached per image
        for ip in identified_products:
            if ip.product_model in illum_products:
                if illum_result is None:  # call once
                    bbox = getattr(ip.detection_box, None) or None
                    illum_result = await self._check_illumination(
                        img,
                        zone_bbox=bbox,
                        roi=roi,
                        planogram_description=planogram_description,
                    )
                    self.logger.info(
                        "Illumination check result for '%s': %s",
                        ip.product_model,
                        illum_result,
                    )
                if illum_result is not None:
                    ip.visual_features = [illum_result] + (ip.visual_features or [])
    # ── end illumination enrichment ────────────────────────────────────────────

    return identified_products, shelf_regions
```

**Fix in skeleton above**: `getattr(ip.detection_box, None)` is wrong — use
`ip.detection_box if hasattr(ip, "detection_box") else None` or just `ip.detection_box`.

### Name matching for illumination enrichment

Use `ip.product_model` (set during detection to the product name). The
`illum_products` set is built from raw config `name` fields. This match should
work for promotional_graphic products because the LLM returns the config name.

Alternatively, only enrich products with `ip.product_type == "promotional_graphic"`
AND `ip.product_model in illum_products`. This is safer.

### Key Constraints

- Single `_check_illumination` call per `detect_objects` invocation (cache result)
- If `illum_result is None`, do NOT add to `visual_features` — skip silently
- If no products have `illumination_required`, skip the block entirely (zero overhead)
- Use `self.logger.info(...)` with lazy `%s` formatting, not f-strings
- Do NOT call `_check_illumination` inside `_detect_legacy` or `_detect_with_grid`

---

## Acceptance Criteria

- [ ] `detect_objects()` refactored to collect into `identified_products, shelf_regions` before returning
- [ ] Illumination enrichment block present, guarded by `if illum_products:`
- [ ] `_check_illumination` called at most once per `detect_objects` call (cached)
- [ ] If result is `None`, `visual_features` NOT modified
- [ ] Existing behavior unchanged when no product has `illumination_required`
- [ ] `pytest packages/ai-parrot-pipelines/tests/ -v` passes

---

## Agent Instructions

1. Verify TASK-628 is in `tasks/completed/` before starting.
2. Read `product_on_shelves.py` lines 122-178 carefully before editing.
3. Refactor the two `return` statements into assignments + single return at bottom.
4. Add illumination enrichment block after the existing ROI offset code.
5. Run full test suite to confirm no regressions.
6. Move this file to `tasks/completed/` and update index → `done`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
