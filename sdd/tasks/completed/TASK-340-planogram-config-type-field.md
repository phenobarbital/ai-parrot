# TASK-340: PlanogramConfig — Add planogram_type Field

**Feature**: Planogram Compliance Modular
**Spec**: `sdd/specs/planogram-compliance-modular.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (0.5-1h)
**Depends-on**: —
**Assigned-to**: —

---

## Context

> Add the `planogram_type` field to `PlanogramConfig` Pydantic model so that planogram configurations can declare which composable type handler to use.
> Implements spec Module 4.

---

## Scope

### Modify `parrot/pipelines/models.py`

1. Add `planogram_type: str = "product_on_shelves"` field to `PlanogramConfig`:
   - Default `"product_on_shelves"` ensures backwards compatibility for configs instantiated in code.
   - Field should be placed after `config_name` for logical grouping.

### Update example configs

2. Add `planogram_type` field to all example `PlanogramConfig` instances in `examples/pipelines/planogram/`:
   - `hisense.py` → `planogram_type="tv_wall"`
   - `firetv.py` → `planogram_type="tv_wall"`
   - `google.py` → `planogram_type="product_on_shelves"`
   - `canvas.py` → `planogram_type="product_on_shelves"` (or appropriate type)
   - `new_hisense.py` → `planogram_type="tv_wall"`

---

## Acceptance Criteria

- [ ] `PlanogramConfig` has `planogram_type: str` field with default `"product_on_shelves"`.
- [ ] Existing code that creates `PlanogramConfig` without `planogram_type` continues to work (default kicks in).
- [ ] All example configs include `planogram_type`.
- [ ] No breaking changes to `PlanogramConfig` serialization/deserialization.

---

## Files to Create / Modify

| File | Action |
|---|---|
| `parrot/pipelines/models.py` | **Modify** — add field |
| `examples/pipelines/planogram/hisense.py` | **Modify** — add `planogram_type` |
| `examples/pipelines/planogram/firetv.py` | **Modify** — add `planogram_type` |
| `examples/pipelines/planogram/google.py` | **Modify** — add `planogram_type` |
| `examples/pipelines/planogram/canvas.py` | **Modify** — add `planogram_type` |
| `examples/pipelines/planogram/new_hisense.py` | **Modify** — add `planogram_type` |
