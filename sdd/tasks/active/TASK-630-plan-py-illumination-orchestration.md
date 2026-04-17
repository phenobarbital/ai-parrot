# TASK-630: Add Illumination Enrichment Hook in `plan.py` (Step 3.5)

**Feature**: FEAT-091 — Product-On-Shelves Illumination Support
**Spec**: `sdd/specs/product-on-shelves-illumination.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-628
**Assigned-to**: unassigned

---

## Context

Module 3 of FEAT-091. The illumination enrichment CANNOT live in
`ProductOnShelves.detect_objects()` because at that point products have not yet
been assigned to shelves (`_assign_products_to_shelves()` runs later, in
`plan.py` around line 291). Without shelf assignment, we cannot identify which
detected product is on the "header" shelf and therefore cannot target the
illumination check correctly.

The correct insertion point is `PlanogramCompliance._execute()` in `plan.py`,
**after** `_assign_products_to_shelves()` (line 291-293) and **before** the
`check_planogram_compliance()` call ("Step 3" comment at line 344). This is
placed as a new "Step 3.5" orchestration step, detection-path-agnostic (works
for both `_detect_with_grid()` and `_detect_legacy()`).

The check is entirely opt-in: if no product in raw config declares
`illumination_required`, the entire block is a no-op — behaviour is identical
to before and no LLM call is made.

Spec section: §3 Module 3, §2 Component Diagram, §6 Integration Points.

---

## Scope

Add three private helper methods to `PlanogramCompliance` (in `plan.py`) and a
single orchestration block between shelf assignment (line 293) and the
compliance check (line 344):

1. `_has_illumination_requirements(raw_config: dict) -> bool`
   Cheap config scan: returns `True` if any product dict in
   `raw_config["shelves"][*]["products"][*]` has a truthy `illumination_required`.
2. `_compute_header_zone_bbox(raw_config, img, roi) -> Optional[tuple]`
   Find the header shelf(s) (`is_background: True` or equivalent), compute
   the header zone bbox from config ratios + ROI (mirror pattern from
   `endcap_no_shelves_promotional.py:405-406`).
3. `_apply_illumination_to_header_products(identified_products, raw_config, illum_state) -> None`
   For each identified product whose `shelf_location == "header"` and whose
   name matches a config product with `illumination_required`: prepend the
   `illum_state` string (e.g. `"illumination_status: ON"`) to that product's
   `visual_features` list.

Orchestration block (inserted between lines 293 and 344):

```python
# Step 3.5: Illumination enrichment (opt-in — only if any product declares
# illumination_required). Runs AFTER _assign_products_to_shelves so
# shelf_location is populated on each identified_product.
_raw_cfg = getattr(self.planogram_config, "planogram_config", {}) or {}
if self._has_illumination_requirements(_raw_cfg):
    header_bbox = self._compute_header_zone_bbox(_raw_cfg, img, endcap)
    illum_state = await self._type_handler._check_illumination(
        img, endcap, planogram_description, illum_zone_bbox=header_bbox
    )
    self._apply_illumination_to_header_products(
        identified_products, _raw_cfg, illum_state
    )
    self.logger.info("Illumination state applied to header products: %s", illum_state)
```

**NOT in scope**:
- The compliance penalty logic (TASK-631).
- Any modification to `ProductOnShelves.detect_objects()`.
- Any modification to `_detect_with_grid()` or `_detect_legacy()`.
- Unit tests (TASK-632).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py` | MODIFY | Add Step 3.5 orchestration + 3 private helper methods on `PlanogramCompliance` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# plan.py already has everything needed:
# - self.planogram_config.planogram_config (raw dict)  verified plan.py:174, 283
# - self._type_handler                                  verified plan.py:72
# - self.logger                                         pre-existing
# No new imports required.
```

### Insertion Point (Exact)

```python
# plan.py — current state (verified 2026-04-12 against dev):
#
#   line 291-293:
#       self._type_handler._assign_products_to_shelves(
#           identified_products, shelf_regions, use_y1_assignment=_use_y1
#       )
#
#   line 344-347:
#       # Step 3: Planogram Compliance Verification (type-specific)
#       compliance_results = self._type_handler.check_planogram_compliance(
#           identified_products, planogram_description
#       )
#
# NEW block goes BETWEEN line 293 (end of assign_products_to_shelves) and
# line 344 (Step 3 compliance check). Do NOT move existing code. Insert only.
```

### Variables in Scope at Insertion Point

```python
# Available locals in PlanogramCompliance._execute() at this point:
img                   # PIL.Image.Image
endcap                # the ROI object (Endcap detection) — verified line 273
planogram_description # PlanogramDescription (from self.planogram_config.get_planogram_description())
identified_products   # List[IdentifiedProduct] — already shelf-assigned
shelf_regions         # List[ShelfRegion] — from virtual shelf generation
self.planogram_config.planogram_config  # raw dict — verified plan.py:174, 283
self._type_handler    # ProductOnShelves / EndcapNoShelvesPromotional / etc.
self.logger
```

### Existing Signatures to Use

```python
# AbstractPlanogramType._check_illumination (after TASK-628 promotes it):
async def _check_illumination(
    self,
    img: Image.Image,
    roi: Any,
    planogram_description: Any,
    illum_zone_bbox: Optional[Any] = None,
) -> str:
    # Returns "illumination_status: ON"/"OFF"; NEVER None
    # (defaults to ON on LLM exception — endcap:547)

# Header zone bbox pattern from endcap_no_shelves_promotional.py:405-406:
# y_start_ratio and height_ratio come from the shelf config. In absolute pixels:
#   bbox_y1 = roi.bbox.y1 + int(y_start_ratio * roi_height)
#   bbox_y2 = bbox_y1 + int(height_ratio * roi_height)
# bbox_x spans the full ROI width.

# IdentifiedProduct fields used (parrot.models.detections):
class IdentifiedProduct:
    product_model: str              # matched against raw config "name"
    product_type: str               # "promotional_graphic" etc.
    shelf_location: str             # "header" after _assign_products_to_shelves
    visual_features: List[str]      # prepend illum_state here
```

### Raw config fields (NOT Pydantic — read from dict)

```python
# Structure at self.planogram_config.planogram_config["shelves"]:
[
  {
    "level": "header",
    "is_background": True,
    "y_start_ratio": 0.0,
    "height_ratio": 0.25,
    "products": [
      {
        "name": "Epson Scanners Header Graphic (backlit)",
        "product_type": "promotional_graphic",
        "illumination_required": "on",   # str "on"/"off" (case-insensitive); optional
        "illumination_penalty": 0.5,     # float; optional; defaults 0.5 for ProductOnShelves
      }
    ]
  },
  ...
]

# Read pattern (same as FEAT-090 text_requirements):
_raw_cfg = getattr(self.planogram_config, "planogram_config", {}) or {}
raw_shelves = _raw_cfg.get("shelves", [])
```

### Does NOT Exist

- ~~`PlanogramCompliance._check_illumination()`~~ — does NOT exist; call via `self._type_handler._check_illumination(...)` (inherited from `AbstractPlanogramType` after TASK-628)
- ~~`self.pipeline`~~ inside `PlanogramCompliance` — `self` IS the pipeline; `self._type_handler.pipeline` references back to `self`
- ~~`ShelfProduct.illumination_required`~~ — NOT a Pydantic field; read from raw dict only
- ~~Injecting illumination in `detect_objects()`~~ — impossible; shelf assignment has not yet run there

---

## Implementation Notes

### Helper 1: `_has_illumination_requirements`

```python
def _has_illumination_requirements(self, raw_config: dict) -> bool:
    """Return True if any product in config declares illumination_required."""
    for shelf in raw_config.get("shelves", []) or []:
        for product in shelf.get("products", []) or []:
            if product.get("illumination_required"):
                return True
    return False
```

### Helper 2: `_compute_header_zone_bbox`

```python
def _compute_header_zone_bbox(self, raw_config, img, endcap):
    """Compute header zone bbox in absolute pixels from config ratios + ROI.

    Returns the bbox tuple (x1, y1, x2, y2) of the first ``is_background``
    shelf that has at least one product with ``illumination_required``.
    Returns ``None`` if no such shelf is found or if the endcap ROI is missing.
    """
    if not endcap or not getattr(endcap, "bbox", None):
        return None
    bb = endcap.bbox
    # Handle either normalized (0..1) or absolute (pixel) bbox values
    def _to_px(v, dim):
        return int(v * dim) if (isinstance(v, float) and v <= 1.0) else int(v)
    roi_x1 = _to_px(bb.x1, img.width)
    roi_y1 = _to_px(bb.y1, img.height)
    roi_x2 = _to_px(bb.x2, img.width)
    roi_y2 = _to_px(bb.y2, img.height)
    roi_h = max(1, roi_y2 - roi_y1)

    for shelf in raw_config.get("shelves", []) or []:
        if not shelf.get("is_background"):
            continue
        if not any(p.get("illumination_required") for p in (shelf.get("products") or [])):
            continue
        y_start = float(shelf.get("y_start_ratio", 0.0))
        h_ratio = float(shelf.get("height_ratio", 0.25))
        bbox_y1 = roi_y1 + int(y_start * roi_h)
        bbox_y2 = bbox_y1 + int(h_ratio * roi_h)
        return (roi_x1, bbox_y1, roi_x2, bbox_y2)
    return None
```

### Helper 3: `_apply_illumination_to_header_products`

```python
def _apply_illumination_to_header_products(
    self, identified_products, raw_config, illum_state
):
    """Prepend illum_state to visual_features of header products that
    declare illumination_required in the raw config.

    Uses ``shelf_location == "header"`` set by _assign_products_to_shelves,
    combined with a product-name match against the raw config.
    """
    if not illum_state:
        return
    illum_names: set[str] = set()
    for shelf in raw_config.get("shelves", []) or []:
        if not shelf.get("is_background"):
            continue
        for product in shelf.get("products", []) or []:
            if product.get("illumination_required"):
                name = product.get("name")
                if name:
                    illum_names.add(name)
    if not illum_names:
        return
    for ip in identified_products:
        if getattr(ip, "shelf_location", None) != "header":
            continue
        if ip.product_model not in illum_names:
            continue
        existing = list(ip.visual_features or [])
        if not any(f.startswith("illumination_status") for f in existing):
            ip.visual_features = [illum_state] + existing
```

### Orchestration block

Insert between `_assign_products_to_shelves` (line 293) and the `# Step 3:`
compliance comment (line 344). Use `await` (the enclosing method is async).

### Key Constraints

- Single `_check_illumination` call per pipeline invocation (guarded by
  `_has_illumination_requirements` short-circuit).
- If `header_bbox is None`, still call `_check_illumination` — the method falls
  back to ROI, then to full image.
- Do NOT modify `ProductOnShelves.detect_objects()`, `_detect_legacy()`, or
  `_detect_with_grid()` in this task.
- Use `self.logger.info(...)` with lazy `%s` formatting, never f-strings.
- Zero overhead when no product has `illumination_required`.

---

## Acceptance Criteria

- [ ] Three helper methods added to `PlanogramCompliance` in `plan.py`
- [ ] Step 3.5 orchestration block inserted between line 293 and line 344
- [ ] `_check_illumination` called at most once per pipeline invocation
- [ ] Zero behaviour change when no product has `illumination_required`
- [ ] Header products get `illumination_status: ON`/`OFF` prepended to `visual_features`
- [ ] No changes to `ProductOnShelves.detect_objects()` in this task
- [ ] `pytest packages/ai-parrot-pipelines/tests/ -v` passes

---

## Agent Instructions

1. Verify TASK-628 is in `tasks/completed/` before starting.
2. Read `plan.py` lines 270-350 carefully before editing.
3. Add the three private helper methods at the bottom of `PlanogramCompliance`.
4. Insert the orchestration block between `_assign_products_to_shelves` and the
   `# Step 3:` compliance comment (currently line 344).
5. Run full test suite to confirm no regressions.
6. Move this file to `tasks/completed/` and update index → `done`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
