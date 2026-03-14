# TASK-341: ProductOnShelves Composable — Extract Current Logic

**Feature**: Planogram Compliance Modular
**Spec**: `sdd/specs/planogram-compliance-modular.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: XL (4-8h)
**Depends-on**: TASK-339, TASK-340
**Assigned-to**: —

---

## Context

> Extract all shelf-based planogram logic from `PlanogramCompliance` into the `ProductOnShelves` composable class. This is the migration target — all current type-specific logic moves here.
> Implements spec Module 2.

---

## Scope

### Create `parrot/pipelines/planogram/types/product_on_shelves.py`

Implement `ProductOnShelves(AbstractPlanogramType)` with all methods currently in `plan.py` that handle shelf-based planogram compliance:

1. **`async compute_roi(self, img)`**:
   - Move `_find_poster()` logic here (poster-anchor ROI detection via LLM).
   - Access LLM via `self.pipeline.roi_client`.
   - Access config prompts via `self.config.roi_detection_prompt`.
   - Return endcap bounding box, ad/brand/panel_text detections, raw detection list.

2. **`async detect_objects_roi(self, img, roi)`**:
   - LLM-based macro object detection (endcap, poster_panel, brand_logo, promotional_graphic).
   - Uses `self.pipeline.roi_client` for detection.

3. **`async detect_objects(self, img, roi, macro_objects)`**:
   - LLM-based product detection with shelf-aware identification.
   - Move these helper methods:
     - `_generate_virtual_shelves()` — virtual shelf generation from ROI bbox and geometry ratios.
     - `_assign_products_to_shelves()` — spatial assignment with background/foreground shelf preference.
     - `_refine_shelves_from_fact_tags()` — adjust shelf boundaries from fact-tag rows.
     - `_corroborate_products_with_fact_tags()` — cross-validate placement with OCR price tags.
     - `_ocr_fact_tags()` — read model numbers from price tags.
   - Access LLM via `self.pipeline.llm`.
   - Access config prompts via `self.config.object_identification_prompt`.

4. **`check_planogram_compliance(self, identified_products, planogram_description)`**:
   - Per-shelf expected vs. found product comparison.
   - Move these helper methods:
     - `_calculate_visual_feature_match()` — semantic keyword matching with `semantic_mappings`.
     - `_looks_like_box()` — heuristic for product_box vs product classification.
     - `_normalize_ocr_text()` — OCR string cleaning (de-accent, punctuation removal).
     - `_base_model_from_str()` — extract model name from full product label.
     - `_canonical_expected_key()` / `_canonical_found_key()` — string normalization for matching.
   - `_PROMO_TYPES` set and type-relaxation rules (printer ≈ product, product ≈ product_box).
   - `TextMatcher` integration for text compliance.
   - Brand compliance checking.
   - Return `List[ComplianceResult]`.

### Important migration rules

- All `self.planogram_config` references become `self.config`.
- All `self.llm` references become `self.pipeline.llm`.
- All `self.roi_client` references become `self.pipeline.roi_client`.
- All `self.reference_images` references become `self.pipeline.reference_images`.
- All `self.logger` references stay as `self.logger` (set in ABC constructor).
- All `self._json` references become `self.pipeline._json`.
- All `self.open_image()` calls become `self.pipeline.open_image()`.
- All `self._downscale_image()` calls become `self.pipeline._downscale_image()`.
- All `self._save_detections()` calls become `self.pipeline._save_detections()`.

### Update `parrot/pipelines/planogram/types/__init__.py`

- Export `ProductOnShelves`.

---

## Acceptance Criteria

- [ ] `ProductOnShelves` implements all four abstract methods from `AbstractPlanogramType`.
- [ ] All helper methods listed in the spec's Method Migration Map are present in `product_on_shelves.py`.
- [ ] All `self.pipeline.*` references correctly access parent pipeline utilities.
- [ ] `_PROMO_TYPES`, `semantic_mappings`, and type-relaxation rules are in `ProductOnShelves`, not in `plan.py`.
- [ ] `ProductOnShelves` is exported from `types/__init__.py`.
- [ ] No circular imports.

---

## Files to Create / Modify

| File | Action |
|---|---|
| `parrot/pipelines/planogram/types/product_on_shelves.py` | **Create** |
| `parrot/pipelines/planogram/types/__init__.py` | **Modify** — add export |
