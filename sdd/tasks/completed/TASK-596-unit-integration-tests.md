# TASK-596: Unit and Integration Tests for New Planogram Types

**Feature**: planogram-new-types
**Spec**: `sdd/specs/planogram-new-types.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-592, TASK-593, TASK-594
**Assigned-to**: unassigned

---

## Context

This task creates comprehensive unit and integration tests for both `ProductCounter` and `EndcapNoShelvesPromotional` types. Tests validate ROI computation, object detection, compliance scoring, illumination logic, and full pipeline runs.

Implements Spec Section 3 — Module 5 and Spec Section 4 — Test Specification.

---

## Scope

- Create unit tests for `ProductCounter`:
  - Initialization, `compute_roi`, `detect_objects_roi`, `detect_objects`, `check_planogram_compliance`
  - Edge case: missing label penalizes but doesn't zero
- Create unit tests for `EndcapNoShelvesPromotional`:
  - Initialization, `compute_roi`, `detect_objects_roi`, `detect_objects` (returns empty), `check_planogram_compliance`
  - Illumination ON/OFF scoring
  - Missing poster penalization
- Create integration tests:
  - Full pipeline run with `planogram_type="product_counter"` (mocked LLM)
  - Full pipeline run with `planogram_type="endcap_no_shelves_promotional"` (mocked LLM)
- Verify type registration resolves correctly

**NOT in scope**:
- Tests against real LLM APIs (all LLM calls mocked)
- Tests for existing types

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/pipelines/test_product_counter.py` | CREATE | Unit tests for ProductCounter |
| `tests/pipelines/test_endcap_no_shelves.py` | CREATE | Unit tests for EndcapNoShelvesPromotional |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_pipelines.planogram.types.product_counter import ProductCounter  # created by TASK-592
from parrot_pipelines.planogram.types.endcap_no_shelves_promotional import EndcapNoShelvesPromotional  # created by TASK-593
from parrot_pipelines.planogram.types.abstract import AbstractPlanogramType  # abstract.py:22
from parrot_pipelines.planogram.plan import PlanogramCompliance  # plan.py:19
from parrot.models.detections import Detection, BoundingBox, IdentifiedProduct, ShelfRegion  # parrot/models/detections.py
from parrot.models.compliance import ComplianceResult, ComplianceStatus  # parrot/models/compliance.py
```

### Existing Test Patterns
```python
# tests/pipelines/test_abstract_type_grid.py — pattern for testing planogram types with mocks
# tests/pipelines/test_grid_strategy.py — pattern for mocking pipeline and config
# tests/pipelines/test_product_on_shelves_grid.py — existing ProductOnShelves tests
```

### Does NOT Exist
- ~~`parrot_pipelines.planogram.types.product_counter`~~ — does not exist until TASK-592 completes
- ~~`parrot_pipelines.planogram.types.endcap_no_shelves_promotional`~~ — does not exist until TASK-593 completes

---

## Implementation Notes

### Test Pattern to Follow
Follow existing planogram test patterns:

```python
# From tests/pipelines/ — standard mock setup pattern:
@pytest.fixture
def mock_pipeline():
    pipeline = MagicMock()
    pipeline.logger = MagicMock()
    pipeline._downscale_image = MagicMock(return_value=b"fake")
    pipeline.roi_client = AsyncMock()
    return pipeline

@pytest.fixture
def mock_config():
    config = MagicMock()
    config.planogram_config = {...}
    config.get_planogram_description.return_value = MagicMock()
    return config
```

### Key Test Scenarios

**ProductCounter:**
1. All elements present → compliance score near 1.0
2. Missing label only → penalized (score > 0, but < 1.0)
3. Missing product → score 0 or near 0
4. Missing promo background → moderate penalty

**EndcapNoShelvesPromotional:**
1. Backlit ON + poster present → full compliance
2. Backlit OFF → heavy penalty
3. Missing poster → moderate penalty
4. `detect_objects` always returns `([], [])`

### Key Constraints
- All LLM calls must be mocked (use `AsyncMock` for `pipeline.roi_client`)
- Use `pytest-asyncio` for async test methods
- Follow existing test file naming: `tests/pipelines/test_*.py`

---

## Acceptance Criteria

- [ ] All tests pass: `pytest tests/pipelines/test_product_counter.py tests/pipelines/test_endcap_no_shelves.py -v`
- [ ] Minimum 8 test cases across both files
- [ ] Integration test verifies type resolution via `PlanogramCompliance._PLANOGRAM_TYPES`
- [ ] All LLM calls properly mocked
- [ ] Edge cases covered (missing elements, illumination states)

---

## Agent Instructions

When you pick up this task:

1. **Verify dependencies** — TASK-592, TASK-593, TASK-594 must be completed
2. **Read existing tests** in `tests/pipelines/` for pattern reference
3. **Read the implemented classes** to understand exact method signatures and return types
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** all tests
6. **Run tests**: `pytest tests/pipelines/test_product_counter.py tests/pipelines/test_endcap_no_shelves.py -v`
7. **Verify** all pass
8. **Move this file** to `tasks/completed/`
9. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
