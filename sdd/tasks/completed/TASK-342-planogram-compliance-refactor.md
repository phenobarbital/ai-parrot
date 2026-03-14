# TASK-342: PlanogramCompliance Refactor — Composable Delegation

**Feature**: Planogram Compliance Modular
**Spec**: `sdd/specs/planogram-compliance-modular.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (3-5h)
**Depends-on**: TASK-339, TASK-340, TASK-341
**Assigned-to**: —

---

## Context

> Refactor `PlanogramCompliance` to be an orchestrator that delegates type-specific steps to a composable type handler resolved from `planogram_type` in the config. This is the core refactor that ties together the ABC, the config field, and the first composable.
> Implements spec Module 3.

---

## Scope

### Modify `parrot/pipelines/planogram/plan.py`

1. **Add internal registry** — class-level dict mapping type strings to composable classes:
   ```python
   from .types import ProductOnShelves

   class PlanogramCompliance(AbstractPipeline):
       _PLANOGRAM_TYPES = {
           "product_on_shelves": ProductOnShelves,
       }
   ```

2. **Update `__init__`**:
   - Read `planogram_type` from `planogram_config.planogram_type` (defaults to `"product_on_shelves"`).
   - Look up composable class in `_PLANOGRAM_TYPES`.
   - If not found, raise `ValueError` with message listing available types.
   - Instantiate: `self._type_handler = composable_cls(pipeline=self, config=planogram_config)`.

3. **Refactor `run()`** to delegate type-specific steps:
   ```python
   async def run(self, image, output_dir=None, image_id=None, **kwargs):
       img = self.open_image(image)
       planogram_description = self.planogram_config.get_planogram_description()

       # Step 1: ROI Detection (type-specific)
       endcap, ad, brand, panel_text, raw_dets = await self._type_handler.compute_roi(img)

       # Step 2: Object Detection (type-specific)
       # ... crop to ROI, call detect_objects_roi and detect_objects via type_handler

       # Step 3: Compliance Check (type-specific)
       compliance_results = self._type_handler.check_planogram_compliance(
           identified_products, planogram_description
       )

       # Step 4: Render (shared, with type-specific colors)
       rendered = self.render_evaluated_image(img, ...)

       return results
   ```

4. **Update `render_evaluated_image()`**:
   - Call `self._type_handler.get_render_colors()` to get type-specific color scheme.
   - Use those colors for drawing ROI bounds, detection boxes, product labels, compliance status.

5. **Remove type-specific methods** from `plan.py`:
   - Delete all methods that have been moved to `ProductOnShelves` (TASK-341).
   - These include: `_find_poster()`, `_generate_virtual_shelves()`, `_assign_products_to_shelves()`, `_refine_shelves_from_fact_tags()`, `_corroborate_products_with_fact_tags()`, `_ocr_fact_tags()`, `check_planogram_compliance()`, `_calculate_visual_feature_match()`, `_looks_like_box()`, `_normalize_ocr_text()`, `_base_model_from_str()`, `_canonical_expected_key()`, `_canonical_found_key()`.
   - Keep: `run()`, `render_evaluated_image()`, `__init__()`, and anything inherited from `AbstractPipeline`.

6. **Preserve `run()` output format** — the return dict must be identical to the current implementation to avoid breaking the handler.

---

## Acceptance Criteria

- [ ] `PlanogramCompliance.__init__` resolves composable from `planogram_type` via `_PLANOGRAM_TYPES`.
- [ ] Unknown `planogram_type` raises `ValueError` listing available types.
- [ ] Missing `planogram_type` defaults to `"product_on_shelves"`.
- [ ] `run()` delegates all type-specific steps to `self._type_handler`.
- [ ] `render_evaluated_image()` uses colors from `self._type_handler.get_render_colors()`.
- [ ] All type-specific methods removed from `plan.py` (now in `ProductOnShelves`).
- [ ] `run()` return dict format is unchanged — no regression in handler output.
- [ ] `plan.py` line count significantly reduced (target: ~200-400 lines down from ~2,000).
- [ ] Pipeline runs end-to-end with `ProductOnShelves` composable producing correct results.

---

## Files to Create / Modify

| File | Action |
|---|---|
| `parrot/pipelines/planogram/plan.py` | **Major refactor** — orchestrator + delegation |
