# TASK-339: AbstractPlanogramType ABC & Types Package

**Feature**: Planogram Compliance Modular
**Spec**: `sdd/specs/planogram-compliance-modular.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (1-2h)
**Depends-on**: —
**Assigned-to**: —

---

## Context

> Define the `AbstractPlanogramType` ABC that establishes the composable contract for all planogram type handlers, and create the `types/` package structure.
> Implements spec Modules 1 and 5.

---

## Scope

### Create `parrot/pipelines/planogram/types/` package

1. Create `parrot/pipelines/planogram/types/__init__.py`:
   - Export `AbstractPlanogramType`.
   - Prepare lazy imports for future concrete types.

2. Create `parrot/pipelines/planogram/types/abstract.py` with `AbstractPlanogramType(ABC)`:
   - **Constructor** `__init__(self, pipeline: "PlanogramCompliance", config: PlanogramConfig)`:
     - Store `self.pipeline` — full reference to parent `PlanogramCompliance` instance.
     - Store `self.config` — the `PlanogramConfig` for this run.
     - Store `self.logger` — from `pipeline.logger`.
   - **Abstract methods** (must be implemented by all concrete types):
     - `async compute_roi(self, img: Image.Image) -> Tuple`: Compute region of interest.
     - `async detect_objects_roi(self, img: Image.Image, roi: Any) -> List[Detection]`: Detect macro objects (poster, logo, backlit) within ROI.
     - `async detect_objects(self, img: Image.Image, roi: Any, macro_objects: Any) -> Tuple[List[IdentifiedProduct], List[ShelfRegion]]`: Detect and identify products.
     - `check_planogram_compliance(self, identified_products: List[IdentifiedProduct], planogram_description: Any) -> List[ComplianceResult]`: Compare detected vs. expected.
   - **Concrete method**:
     - `get_render_colors(self) -> Dict[str, Tuple[int,int,int]]`: Return default color scheme for rendering. Types override for custom colors.
       ```python
       return {
           "roi": (0, 255, 0),
           "detection": (255, 165, 0),
           "product": (0, 255, 255),
           "compliant": (0, 200, 0),
           "non_compliant": (255, 0, 0),
       }
       ```

### Update `parrot/pipelines/planogram/__init__.py`

- Add import/export for `AbstractPlanogramType` from `types` subpackage.

---

## Acceptance Criteria

- [ ] `AbstractPlanogramType` is an ABC that cannot be instantiated directly.
- [ ] All four abstract methods are enforced on subclasses.
- [ ] `get_render_colors()` returns a dict with keys: `roi`, `detection`, `product`, `compliant`, `non_compliant`.
- [ ] Constructor accepts `pipeline` and `config` parameters.
- [ ] `parrot/pipelines/planogram/types/__init__.py` exports `AbstractPlanogramType`.
- [ ] `parrot/pipelines/planogram/__init__.py` updated to include `AbstractPlanogramType`.
- [ ] No circular import issues.

---

## Files to Create / Modify

| File | Action |
|---|---|
| `parrot/pipelines/planogram/types/__init__.py` | **Create** |
| `parrot/pipelines/planogram/types/abstract.py` | **Create** |
| `parrot/pipelines/planogram/__init__.py` | **Modify** — add export |
