# TASK-658: Tests for EndcapBacklitMultitier

**Feature**: FEAT-096 — Endcap Backlit Multitier Planogram Type
**Spec**: `sdd/specs/endcap-backlit-multitier.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-655, TASK-656
**Assigned-to**: unassigned

---

## Context

This is Module 6 of FEAT-096. Comprehensive tests for the new `EndcapBacklitMultitier`
type, the `ShelfSection`/`SectionRegion` models (from TASK-653), the promoted helpers
in `AbstractPlanogramType` (from TASK-654), the plan.py integration (from TASK-656),
and backward-compatibility of `ProductOnShelves` and `EndcapNoShelvesPromotional`.

---

## Scope

- Unit tests: section crop math, bbox remapping, padding overlap, flat-shelf fallback,
  empty-section handling, LLM failure graceful degradation, compliance scoring,
  illumination penalty.
- Integration test: full `PlanogramCompliance.run()` with multi-section shelf config
  using mocked LLM responses.
- Backward-compat tests: `product_on_shelves` pipeline and `endcap_no_shelves_promotional`
  still work after plan.py guards and abstract.py promotions.
- Model tests: `ShelfConfig` + `ShelfSection` + `SectionRegion` field validation.

**NOT in scope**: End-to-end test with real images and real DB (manual / integration env).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/tests/planogram/test_endcap_backlit_multitier.py` | CREATE | Full unit + integration test suite |
| `packages/ai-parrot-pipelines/tests/planogram/conftest.py` | MODIFY | Add fixtures for section configs (if file exists; create if not) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from PIL import Image

# Models (verify post TASK-653 changes):
from parrot.models.detections import (
    ShelfConfig, ShelfProduct, ShelfSection, SectionRegion,
    PlanogramDescription, PlanogramDescriptionFactory,
    IdentifiedProduct, ShelfRegion, DetectionBox,
)
from parrot.models.compliance import ComplianceResult, ComplianceStatus

# Type class (added by TASK-655):
from parrot_pipelines.planogram.types.endcap_backlit_multitier import EndcapBacklitMultitier

# Abstract base (verify post TASK-654 changes):
from parrot_pipelines.planogram.types.abstract import AbstractPlanogramType

# Pipeline (verify post TASK-656 changes):
from parrot_pipelines.planogram.plan import PlanogramCompliance
from parrot_pipelines.models import PlanogramConfig
```

### Existing Signatures to Use

```python
# ShelfConfig (post TASK-653):
ShelfConfig(
    level="top",
    products=[],
    sections=[ShelfSection(id="left", region=SectionRegion(...), products=["ES-60W"])],
    section_padding=0.05,
)

# ShelfSection (post TASK-653):
ShelfSection(id="left", region=SectionRegion(x_start=0.0, x_end=0.35, y_start=0.0, y_end=1.0), products=["ES-60W"])

# ComplianceResult:
ComplianceResult(
    shelf_level="top",
    expected_products=["ES-60W"],
    found_products=[],
    missing_products=["ES-60W"],
    unexpected_products=[],
    compliance_status=ComplianceStatus.NON_COMPLIANT,
    compliance_score=0.0,
)

# EndcapBacklitMultitier constructor:
handler = EndcapBacklitMultitier(pipeline=mock_pipeline, config=mock_config)
```

### Does NOT Exist

- ~~`EndcapBacklitMultitier._generate_virtual_shelves()`~~ — not implemented; do not test for it.
- ~~`EndcapBacklitMultitier._assign_products_to_shelves()`~~ — not implemented.
- ~~`ShelfProduct.section`~~ — not a field; do not reference.
- ~~`planogram_description.category_noun()`~~ — not a method.

---

## Implementation Notes

### Mock pattern for LLM calls

```python
@pytest.fixture
def mock_pipeline():
    pipeline = MagicMock()
    pipeline.logger = MagicMock()
    pipeline.roi_client = MagicMock()
    pipeline._downscale_image = MagicMock(side_effect=lambda img, **kwargs: img)
    return pipeline

@pytest.fixture
def handler(mock_pipeline):
    config = MagicMock()
    return EndcapBacklitMultitier(pipeline=mock_pipeline, config=config)
```

### Test coverage checklist

```python
class TestShelfSectionModels:
    def test_section_region_valid():
    def test_shelf_config_with_sections():
    def test_shelf_config_flat_no_sections():
    def test_factory_parses_sections():

class TestSectionCropMath:
    def test_compute_section_bbox_no_padding():
    def test_compute_section_bbox_with_padding():
    def test_compute_section_bbox_clamps_to_image():
    def test_adjacent_sections_overlap_with_padding():

class TestBboxRemapping:
    def test_remap_section_local_to_full_image():
    def test_remap_at_image_origin():
    def test_remap_at_non_zero_offset():

class TestDetectObjects:
    async def test_parallel_gather_called_for_sections():
    async def test_flat_shelf_single_call():
    async def test_section_llm_failure_returns_empty():
    async def test_zero_detections_empty_list():
    async def test_deduplication_boundary_product():

class TestCompliancScoring:
    def test_all_found_score_1():
    def test_none_found_score_0():
    def test_partial_found_correct_score():
    def test_illumination_off_penalty():

class TestPromotedHelpers:
    def test_base_model_from_str_is_static():
    def test_check_illumination_exists_on_abstract():

class TestPlanRegistration:
    def test_type_registered_in_planogram_types():
    def test_endcap_no_shelves_backward_compat():
    def test_product_on_shelves_backward_compat():
```

---

## Acceptance Criteria

- [ ] All tests pass: `pytest packages/ai-parrot-pipelines/tests/planogram/test_endcap_backlit_multitier.py -v`
- [ ] Backward-compat tests pass: `product_on_shelves` and `endcap_no_shelves_promotional` work
- [ ] Coverage ≥ 80% on `endcap_backlit_multitier.py` (check with `pytest --cov`)
- [ ] No warnings or errors from `ruff check` on the test file

---

## Test Specification

(See Implementation Notes above — the full test class structure.)

Key test to not forget:

```python
@pytest.mark.asyncio
async def test_parallel_gather_called_for_sections(handler):
    """detect_objects calls asyncio.gather for all sections in parallel."""
    shelf_sections = [
        ShelfSection(id="left", region=SectionRegion(0.0, 0.35, 0.0, 1.0), products=["A"]),
        ShelfSection(id="right", region=SectionRegion(0.65, 1.0, 0.0, 1.0), products=["B"]),
    ]
    shelf_config = ShelfConfig(level="top", products=[], sections=shelf_sections)
    # mock _detect_section to return immediately
    call_log = []
    async def fake_detect(section, *args, **kwargs):
        call_log.append(section.id)
        return []
    handler._detect_section = fake_detect

    img = Image.new("RGB", (800, 600))
    roi = MagicMock()
    roi.bbox = MagicMock(x1=0.0, y1=0.3, x2=1.0, y2=0.7)

    await handler.detect_objects(img, roi, macro_objects=None)
    assert set(call_log) == {"left", "right"}
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/endcap-backlit-multitier.spec.md`.
2. **Check dependencies** — TASK-655 and TASK-656 must be in `tasks/completed/`.
3. **Read the implementation files** first: `endcap_backlit_multitier.py`, `abstract.py`
   (post TASK-654), `detections.py` (post TASK-653), `plan.py` (post TASK-656).
4. **Update status** in `tasks/.index.json` → `"in-progress"`.
5. **Implement** all test classes listed above.
6. **Run** `source .venv/bin/activate && pytest packages/ai-parrot-pipelines/tests/planogram/test_endcap_backlit_multitier.py -v`.
7. **Move this file** to `tasks/completed/TASK-658-tests-endcap-backlit.md`.
8. **Update index** → `"done"`.
9. **Commit** with message: `sdd: TASK-658 add tests for EndcapBacklitMultitier`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: —
**Date**: —
**Notes**: —
**Deviations from spec**: none
