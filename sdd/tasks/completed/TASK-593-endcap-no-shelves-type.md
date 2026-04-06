# TASK-593: Implement EndcapNoShelvesPromotional Planogram Type

**Feature**: planogram-new-types
**Spec**: `sdd/specs/planogram-new-types.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This task implements the `EndcapNoShelvesPromotional` composable class — the second of two new planogram types in FEAT-085. It handles compliance validation for shelf-less promotional endcaps: a retro-illuminated upper panel (brand/promo) and a lower poster. No physical products are detected.

Implements Spec Section 3 — Module 2.

---

## Scope

- Implement `EndcapNoShelvesPromotional` class extending `AbstractPlanogramType` in a new file.
- Implement all four abstract methods:
  - `compute_roi`: LLM-based detection of promotional panel, expand bbox downward to include full endcap.
  - `detect_objects_roi`: Detect `backlit_panel` and `lower_poster` zones.
  - `detect_objects`: Returns `([], [])` — no physical products.
  - `check_planogram_compliance`: Check backlit ON/OFF, check poster presence, score accordingly.
- Reuse illumination-checking logic from `GraphicPanelDisplay._check_illumination_from_roi` — either by extracting it to a shared utility or by duplicating the prompt logic.
- No grid strategy override needed.

**NOT in scope**:
- Registration in `plan.py` / `__init__.py` (TASK-594)
- Example config scripts (TASK-595)
- Tests (TASK-596)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_no_shelves_promotional.py` | CREATE | EndcapNoShelvesPromotional composable class |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/graphic_panel_display.py` | MODIFY (optional) | Extract `_check_illumination_from_roi` to a standalone function if preferred over duplication |

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

    # Same four abstract methods as TASK-592 (see abstract.py lines 49-121)
```

```python
# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/graphic_panel_display.py:665
async def _check_illumination_from_roi(
    self,
    img: Image.Image,
    roi: Any,
    planogram_description: Any,
) -> str:
    """Returns 'illumination_status: ON' or 'illumination_status: OFF'"""
    # Uses self.pipeline._downscale_image(roi_crop, max_side=800, quality=82)
    # Uses self.pipeline.roi_client for LLM call
    # Prompt compares TOP panel brightness vs MIDDLE/BOTTOM panels

# Module-level constants (graphic_panel_display.py):
_DEFAULT_ILLUMINATION_PENALTY: float = 1.0  # line 33
_ILLUMINATION_FEATURE_PREFIX = "illumination_status:"  # line 36
```

```python
# Shared pipeline utilities available via self.pipeline:
#   self.pipeline._downscale_image(img, max_side, quality)
#   self.pipeline.roi_client  — async context manager for LLM calls
#   self.config.get_planogram_description()  — returns PlanogramDescription
#   self.config.roi_detection_prompt  — str
#   self.config.planogram_config  — Dict[str, Any]
```

### Does NOT Exist
- ~~`AbstractPlanogramType.check_illumination()`~~ — not a base class method; lives only on `GraphicPanelDisplay`
- ~~`parrot_pipelines.planogram.types.endcap`~~ — no such module
- ~~`EndcapNoShelvesPromotional`~~ — does not exist yet; you are creating it
- ~~`parrot_pipelines.planogram.utils`~~ — no utils module exists yet (create if extracting illumination logic)

---

## Implementation Notes

### Pattern to Follow
Follow `GraphicPanelDisplay` for the illumination check pattern:

```python
# From graphic_panel_display.py:665-710 — key illumination check logic:
async def _check_illumination_from_roi(self, img, roi, planogram_description):
    iw, ih = img.size
    if roi is not None:
        x1, y1 = int(roi.bbox.x1 * iw), int(roi.bbox.y1 * ih)
        x2, y2 = int(roi.bbox.x2 * iw), int(roi.bbox.y2 * ih)
        roi_crop = img.crop((x1, y1, x2, y2))
    else:
        roi_crop = img.copy()
    roi_small = self.pipeline._downscale_image(roi_crop, max_side=800, quality=82)
    # Prompt asks LLM to compare top panel brightness vs middle/bottom
    # Returns "illumination_status: ON" or "illumination_status: OFF"
```

**Two approaches for reuse (implementer chooses):**
1. **Extract**: Move illumination logic to a module-level async function in a new `utils.py` or in `abstract.py`, then call from both `GraphicPanelDisplay` and `EndcapNoShelvesPromotional`.
2. **Duplicate**: Copy the ~40 lines of illumination prompt/check logic into `EndcapNoShelvesPromotional`. Simpler but duplicates code.

### Key Constraints
- `detect_objects` MUST return `([], [])` — this type has no physical products
- Backlit OFF → apply illumination penalty to compliance score
- Missing lower poster → penalize score
- Read `illumination_expected` from `self.config.planogram_config` dict (default: "ON")
- Use `self.pipeline._downscale_image()` before LLM calls

### References in Codebase
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/graphic_panel_display.py` — illumination logic and zone detection pattern
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py` — base class

---

## Acceptance Criteria

- [ ] `EndcapNoShelvesPromotional` class implements all four abstract methods
- [ ] Class file created at correct path
- [ ] Illumination check correctly identifies ON/OFF state
- [ ] Backlit OFF → compliance score penalized
- [ ] `detect_objects` returns `([], [])` — no products
- [ ] Missing lower poster penalizes score
- [ ] No breaking changes to `GraphicPanelDisplay`

---

## Test Specification

```python
# tests/pipelines/test_endcap_no_shelves.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from parrot_pipelines.planogram.types.endcap_no_shelves_promotional import EndcapNoShelvesPromotional


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
        "expected_elements": ["backlit_panel", "lower_poster"],
        "illumination_expected": "ON",
    }
    config.roi_detection_prompt = "Find the promotional endcap"
    config.get_planogram_description.return_value = MagicMock()
    return config


class TestEndcapNoShelvesPromotional:
    def test_initialization(self, mock_pipeline, mock_config):
        endcap = EndcapNoShelvesPromotional(pipeline=mock_pipeline, config=mock_config)
        assert endcap is not None

    def test_detect_objects_returns_empty(self, mock_pipeline, mock_config):
        endcap = EndcapNoShelvesPromotional(pipeline=mock_pipeline, config=mock_config)
        # detect_objects must return ([], [])
        ...

    def test_compliance_backlit_on(self, mock_pipeline, mock_config):
        # Backlit ON → compliant
        ...

    def test_compliance_backlit_off(self, mock_pipeline, mock_config):
        # Backlit OFF → penalized
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/planogram-new-types.spec.md` for full context
2. **Check dependencies** — none for this task
3. **Verify the Codebase Contract** — confirm `GraphicPanelDisplay._check_illumination_from_roi` signature hasn't changed
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-593-endcap-no-shelves-type.md`
8. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
