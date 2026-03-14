# TASK-344: Unit Tests for Planogram Compliance Modular

**Feature**: Planogram Compliance Modular
**Spec**: `sdd/specs/planogram-compliance-modular.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (3-5h)
**Depends-on**: TASK-339, TASK-340, TASK-341, TASK-342, TASK-343
**Assigned-to**: —

---

## Context

> Write unit and integration tests for the composable pattern: AbstractPlanogramType contract, ProductOnShelves implementation, PlanogramCompliance delegation/registry, and handler hydration.
> Implements spec Module 8.

---

## Scope

### Create `tests/pipelines/test_planogram_types.py`

#### ABC Contract Tests

1. **`test_abstract_planogram_type_contract`**: Verify `AbstractPlanogramType` cannot be instantiated directly — raises `TypeError`.
2. **`test_abstract_methods_enforced`**: Subclass missing any abstract method raises `TypeError` on instantiation.
3. **`test_default_render_colors`**: `get_render_colors()` returns dict with expected keys: `roi`, `detection`, `product`, `compliant`, `non_compliant`.

#### Registry & Delegation Tests

4. **`test_planogram_compliance_registry_resolution`**: `PlanogramCompliance` resolves `ProductOnShelves` from `planogram_type="product_on_shelves"`.
5. **`test_planogram_compliance_default_type`**: Missing `planogram_type` (or empty) defaults to `"product_on_shelves"` — no error.
6. **`test_planogram_compliance_unknown_type`**: `planogram_type="nonexistent"` raises `ValueError` with message listing available types.
7. **`test_planogram_compliance_run_delegates`**: Mock `_type_handler` and verify `run()` calls `compute_roi`, `detect_objects_roi`, `detect_objects`, `check_planogram_compliance` in order.

#### PlanogramConfig Tests

8. **`test_planogram_config_planogram_type_field`**: `PlanogramConfig(planogram_type="ink_wall")` stores the value correctly.
9. **`test_planogram_config_default_type`**: `PlanogramConfig()` defaults `planogram_type` to `"product_on_shelves"`.

#### ProductOnShelves Tests

10. **`test_product_on_shelves_implements_contract`**: `ProductOnShelves` can be instantiated (all abstract methods implemented).
11. **`test_product_on_shelves_virtual_shelves`**: `_generate_virtual_shelves()` produces correct number of shelves from a sample config.
12. **`test_product_on_shelves_assign_products`**: `_assign_products_to_shelves()` correctly assigns promotional vs. regular products.
13. **`test_product_on_shelves_compliance_check`**: `check_planogram_compliance()` returns correct `ComplianceResult` for a known expected/found product set.

#### Rendering Tests

14. **`test_render_uses_type_colors`**: Verify `render_evaluated_image()` calls `get_render_colors()` on the type handler.

#### Handler Hydration Tests

15. **`test_handler_hydrates_planogram_type`**: `_build_planogram_config()` includes `planogram_type` from DB row.
16. **`test_handler_default_planogram_type`**: DB row without `planogram_type` defaults to `"product_on_shelves"`.

#### Integration Tests

17. **`test_backwards_compatibility_no_type`**: Full pipeline run with config lacking `planogram_type` succeeds using `ProductOnShelves`.

### Test Fixtures

- Mock `PlanogramCompliance` with mocked LLM client for unit tests.
- Sample `PlanogramConfig` with shelf-based planogram description.
- Sample `IdentifiedProduct` list for compliance testing.
- Sample DB row dict for handler hydration tests.

---

## Acceptance Criteria

- [ ] All 17 test cases implemented and passing.
- [ ] Tests run with: `pytest tests/pipelines/test_planogram_types.py -v`
- [ ] No mocked external services (LLM calls mocked, no real API calls).
- [ ] Tests cover: ABC contract, registry resolution, delegation flow, config field, ProductOnShelves logic, rendering colors, handler hydration.

---

## Files to Create / Modify

| File | Action |
|---|---|
| `tests/pipelines/test_planogram_types.py` | **Create** |
