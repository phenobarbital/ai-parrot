# TASK-592: Implement ProductCounter Planogram Type

**Feature**: planogram-new-types
**Spec**: `sdd/specs/planogram-new-types.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This task implements the `ProductCounter` composable class — the first of two new planogram types defined in FEAT-085. It handles compliance validation for product-on-counter displays: a single product on a counter/podium with promotional background material and an information label.

Implements Spec Section 3 — Module 1.

---

## Scope

- Implement `ProductCounter` class extending `AbstractPlanogramType` in a new file.
- Implement all four abstract methods:
  - `compute_roi`: LLM-based detection of counter/podium area.
  - `detect_objects_roi`: Detect macro elements (product, promotional_background, information_label).
  - `detect_objects`: Map detected product to `IdentifiedProduct`. Return empty `ShelfRegion` list.
  - `check_planogram_compliance`: Score based on element presence with configurable penalties (label=0.3, promo=0.5, product=1.0).
- No grid strategy override needed (`NoGrid` default from base class is correct).

**NOT in scope**:
- Registration in `plan.py` / `__init__.py` (TASK-594)
- Example config scripts (TASK-595)
- Tests (TASK-596)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_counter.py` | CREATE | ProductCounter composable class |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_pipelines.planogram.types.abstract import AbstractPlanogramType  # abstract.py:22
from parrot.models.detections import Detection, BoundingBox, Detections, IdentifiedProduct, ShelfRegion  # parrot/models/detections.py
from parrot.models.compliance import ComplianceResult, ComplianceStatus  # parrot/models/compliance.py
from PIL import Image  # third-party
```

### Existing Signatures to Use
```python
# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py:22
class AbstractPlanogramType(ABC):
    def __init__(self, pipeline: "PlanogramCompliance", config: "PlanogramConfig") -> None:  # line 40
        self.pipeline = pipeline  # line 45
        self.config = config      # line 46
        self.logger = pipeline.logger  # line 47

    @abstractmethod
    async def compute_roi(self, img: Image.Image) -> Tuple[Optional[Tuple[int,int,int,int]], Optional[Any], Optional[Any], Optional[Any], List[Any]]:  # line 49

    @abstractmethod
    async def detect_objects_roi(self, img: Image.Image, roi: Any) -> List[Detection]:  # line 70

    @abstractmethod
    async def detect_objects(self, img: Image.Image, roi: Any, macro_objects: Any) -> Tuple[List[IdentifiedProduct], List[ShelfRegion]]:  # line 89

    @abstractmethod
    def check_planogram_compliance(self, identified_products: List[IdentifiedProduct], planogram_description: Any) -> List[ComplianceResult]:  # line 107

    def get_grid_strategy(self) -> "AbstractGridStrategy":  # line 139 — returns NoGrid() by default
```

```python
# Shared pipeline utilities available via self.pipeline:
#   self.pipeline._downscale_image(img, max_side=1024, quality=78)
#   self.pipeline.roi_client  — async context manager for LLM calls
#   self.pipeline.planogram_config  — PlanogramConfig instance
#   self.config.get_planogram_description()  — returns PlanogramDescription
#   self.config.roi_detection_prompt  — str
#   self.config.object_identification_prompt  — str
```

### Does NOT Exist
- ~~`AbstractPlanogramType.check_illumination()`~~ — not a base class method
- ~~`PlanogramConfig.expected_elements`~~ — not a model field; element expectations live inside `planogram_config` dict
- ~~`parrot_pipelines.planogram.types.counter`~~ — no such module
- ~~`ProductCounter`~~ — does not exist yet; you are creating it

---

## Implementation Notes

### Pattern to Follow
Follow the structure of `ProductOnShelves` (same file organization, same method signatures):

```python
# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py
class ProductOnShelves(AbstractPlanogramType):
    def __init__(self, pipeline: Any, config: Any) -> None:
        super().__init__(pipeline, config)
        # type-specific init

    async def compute_roi(self, img: Image.Image) -> Tuple[...]:
        planogram_description = self.config.get_planogram_description()
        # Use self.pipeline.roi_client + ask_to_image for LLM detection
        ...

    async def detect_objects_roi(self, img: Image.Image, roi: Any) -> List[Detection]:
        # Crop image to ROI, ask LLM for macro objects
        image_small = self.pipeline._downscale_image(cropped, max_side=1024, quality=78)
        async with self.pipeline.roi_client as client:
            msg = await client.ask_to_image(image=image_small, ...)
        ...
```

### Key Constraints
- Use `self.pipeline.roi_client` + `ask_to_image` for all LLM calls
- Use `self.pipeline._downscale_image()` before sending images to LLM
- `detect_objects` returns `(identified_products, [])` — no shelf regions for counters
- Default scoring weights: product=1.0, promotional_background=0.5, information_label=0.3
- Read weights from `self.config.planogram_config` dict if provided, else use defaults
- Missing label should penalize but not zero the score

### References in Codebase
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py` — primary pattern reference
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py` — base class

---

## Acceptance Criteria

- [ ] `ProductCounter` class implements all four abstract methods
- [ ] Class file created at correct path
- [ ] Uses `self.pipeline.roi_client` for LLM calls (not direct SDK calls)
- [ ] `detect_objects` returns empty `ShelfRegion` list
- [ ] Missing label penalizes score but doesn't zero it
- [ ] No modifications to existing types

---

## Test Specification

```python
# tests/pipelines/test_product_counter.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from parrot_pipelines.planogram.types.product_counter import ProductCounter


@pytest.fixture
def mock_pipeline():
    pipeline = MagicMock()
    pipeline.logger = MagicMock()
    pipeline._downscale_image = MagicMock(return_value=b"fake_img")
    return pipeline


@pytest.fixture
def mock_config():
    config = MagicMock()
    config.planogram_config = {
        "brand": "Epson",
        "expected_elements": ["product", "promotional_background", "information_label"],
    }
    config.roi_detection_prompt = "Find the counter display area"
    config.object_identification_prompt = "Identify elements on counter"
    config.get_planogram_description.return_value = MagicMock()
    return config


class TestProductCounter:
    def test_initialization(self, mock_pipeline, mock_config):
        counter = ProductCounter(pipeline=mock_pipeline, config=mock_config)
        assert counter is not None
        assert counter.pipeline is mock_pipeline

    def test_compliance_all_present(self, mock_pipeline, mock_config):
        counter = ProductCounter(pipeline=mock_pipeline, config=mock_config)
        # Test with all elements present → full compliance
        ...

    def test_compliance_missing_label(self, mock_pipeline, mock_config):
        counter = ProductCounter(pipeline=mock_pipeline, config=mock_config)
        # Test with missing label → penalized but not zero
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/planogram-new-types.spec.md` for full context
2. **Check dependencies** — none for this task
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists
   - Confirm `AbstractPlanogramType` still has the listed methods
   - If anything has changed, update the contract FIRST, then implement
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-592-product-counter-type.md`
8. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
