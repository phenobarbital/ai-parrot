# TASK-343: Handler Hydration Update & Integration

**Feature**: Planogram Compliance Modular
**Spec**: `sdd/specs/planogram-compliance-modular.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (1-2h)
**Depends-on**: TASK-340, TASK-342
**Assigned-to**: —

---

## Context

> Update the handler's config hydration to include `planogram_type` from the DB row, and ensure the planogram package init exports are correct.
> Implements spec Modules 6, 7, and 9.

---

## Scope

### Modify `parrot/handlers/planogram_compliance.py`

1. In `_build_planogram_config()`, add `planogram_type` from DB row:
   ```python
   planogram_type = row.get("planogram_type", "product_on_shelves")
   ```
   Pass it to `PlanogramConfig(planogram_type=planogram_type, ...)`.

2. No other handler changes — `PlanogramCompliance` is still instantiated the same way.

### Verify `parrot/pipelines/planogram/__init__.py`

3. Ensure exports include:
   - `PlanogramCompliance` (existing)
   - `AbstractPlanogramType` (new, from types subpackage)
   - Any other existing exports remain unchanged.

### Update example configs (if not done in TASK-340)

4. Verify all example configs in `examples/pipelines/planogram/` have `planogram_type` set.

---

## Acceptance Criteria

- [ ] `_build_planogram_config()` reads `planogram_type` from DB row.
- [ ] Default `"product_on_shelves"` used when DB row lacks `planogram_type`.
- [ ] Handler public API unchanged — no new routes, no new parameters.
- [ ] `parrot/pipelines/planogram/__init__.py` exports are correct and complete.
- [ ] No import errors when running the handler.

---

## Files to Create / Modify

| File | Action |
|---|---|
| `parrot/handlers/planogram_compliance.py` | **Modify** — add `planogram_type` to hydration |
| `parrot/pipelines/planogram/__init__.py` | **Verify/Modify** — ensure exports |
