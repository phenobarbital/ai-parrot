# Feature Specification: Planogram New Types

**Feature ID**: FEAT-085
**Date**: 2026-04-06
**Author**: Antigravity
**Status**: approved
**Target version**: N/A
**Prior exploration**: `sdd/proposals/planogram-new-types.brainstorm.md` (Option A — Recommended)

---

## 1. Motivation & Business Requirements

### Problem Statement

The `planogram_compliance` module in `ai-parrot-pipelines` currently only supports two composable types: `product_on_shelves` and `graphic_panel_display`. Two additional physical retail formats need compliance validation:

1. **Product Counter (`product_counter`)**: A single product displayed on a counter with promotional background material and an information label describing it.
2. **Endcap No Shelves Promotional (`endcap_no_shelves_promotional`)**: A shelf-less endcap featuring a retro-illuminated upper panel (brand/promo message) and a lower poster. No physical products — compliance checks whether the backlit is ON and the poster is present.

### Goals
- Add `ProductCounter` and `EndcapNoShelvesPromotional` composable classes extending `AbstractPlanogramType`.
- Register both types in `PlanogramCompliance._PLANOGRAM_TYPES` so they are automatically available via `planogram_type` config field.
- Provide example JSON `planogramConfig` payloads for inserting into `troc.planograms_configurations`.
- Reuse existing illumination-check logic from `GraphicPanelDisplay` for the endcap type.

### Non-Goals (explicitly out of scope)
- Modifying the DB schema — existing `PlanogramConfig` model is sufficient.
- Adding YOLO-based detection — both types rely on LLM-only detection.
- Grid decomposition — neither type uses shelves or grids.

---

## 2. Architectural Design

### Overview

Following the **Composable Pattern** already established: each new type is a subclass of `AbstractPlanogramType` that implements the four abstract methods (`compute_roi`, `detect_objects_roi`, `detect_objects`, `check_planogram_compliance`). `PlanogramCompliance` resolves the class from the `planogram_type` string and delegates all type-specific logic.

### Component Diagram
```
PlanogramCompliance (plan.py)
    │
    ├── _PLANOGRAM_TYPES["product_counter"] ──→ ProductCounter
    ├── _PLANOGRAM_TYPES["endcap_no_shelves_promotional"] ──→ EndcapNoShelvesPromotional
    ├── _PLANOGRAM_TYPES["product_on_shelves"] ──→ ProductOnShelves  (existing)
    └── _PLANOGRAM_TYPES["graphic_panel_display"] ──→ GraphicPanelDisplay  (existing)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractPlanogramType` | extends | Both new classes inherit from it |
| `GraphicPanelDisplay._check_illumination_from_roi` | reuses (extracted) | Endcap type needs illumination checking |
| `PlanogramCompliance._PLANOGRAM_TYPES` | modifies | Add two new entries |
| `types/__init__.py` | modifies | Export new classes |

### Data Models

No new Pydantic models required. Both types use the existing `PlanogramConfig`, `ComplianceResult`, `ComplianceStatus`, `Detection`, `BoundingBox`, `IdentifiedProduct`, and `ShelfRegion` models.

### New Public Interfaces

```python
# parrot_pipelines/planogram/types/product_counter.py
class ProductCounter(AbstractPlanogramType):
    """Planogram type for product-on-counter displays.

    Detects a single product, promotional background material, and an
    information label on a counter/podium. Compliance is based on
    presence of all three elements.
    """
    async def compute_roi(self, img: Image.Image) -> Tuple[...]: ...
    async def detect_objects_roi(self, img: Image.Image, roi: Any) -> List[Detection]: ...
    async def detect_objects(self, img: Image.Image, roi: Any, macro_objects: Any) -> Tuple[...]: ...
    def check_planogram_compliance(self, identified_products, planogram_description) -> List[ComplianceResult]: ...
```

```python
# parrot_pipelines/planogram/types/endcap_no_shelves_promotional.py
class EndcapNoShelvesPromotional(AbstractPlanogramType):
    """Planogram type for shelf-less promotional endcaps.

    Validates presence and illumination state of a retro-illuminated
    upper panel and a lower promotional poster. No physical products.
    """
    async def compute_roi(self, img: Image.Image) -> Tuple[...]: ...
    async def detect_objects_roi(self, img: Image.Image, roi: Any) -> List[Detection]: ...
    async def detect_objects(self, img: Image.Image, roi: Any, macro_objects: Any) -> Tuple[...]: ...
    def check_planogram_compliance(self, identified_products, planogram_description) -> List[ComplianceResult]: ...
```

---

## 3. Module Breakdown

### Module 1: ProductCounter Type
- **Path**: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_counter.py`
- **Responsibility**: Implement `ProductCounter` composable — ROI detection around counter area, macro detection of product + promotional material + information label, compliance scoring based on element presence.
- **Depends on**: `AbstractPlanogramType`, `parrot.models.detections`, `parrot.models.compliance`

### Module 2: EndcapNoShelvesPromotional Type
- **Path**: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_no_shelves_promotional.py`
- **Responsibility**: Implement `EndcapNoShelvesPromotional` composable — ROI detection of full endcap, backlit illumination check (reusing logic from `GraphicPanelDisplay._check_illumination_from_roi`), lower poster detection, compliance scoring.
- **Depends on**: `AbstractPlanogramType`, `GraphicPanelDisplay` (illumination logic), `parrot.models.detections`, `parrot.models.compliance`

### Module 3: Registration & Exports
- **Path**: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/__init__.py` and `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py`
- **Responsibility**: Add both new classes to `__init__.py` exports and to `PlanogramCompliance._PLANOGRAM_TYPES` dict.
- **Depends on**: Module 1, Module 2

### Module 4: Example Configuration Scripts
- **Path**: `packages/ai-parrot-pipelines/examples/planogram_configs/`
- **Responsibility**: Python scripts generating JSON `planogramConfig` payloads for `product_counter` and `endcap_no_shelves_promotional` types, ready for insertion into `troc.planograms_configurations`.
- **Depends on**: Module 1, Module 2 (for field documentation)

### Module 5: Unit & Integration Tests
- **Path**: `tests/pipelines/test_product_counter.py`, `tests/pipelines/test_endcap_no_shelves.py`
- **Responsibility**: Test both composable classes — ROI, detection, compliance logic, edge cases.
- **Depends on**: Module 1, Module 2, Module 3

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_product_counter_init` | Module 1 | Validates initialization with valid PlanogramConfig |
| `test_product_counter_compute_roi` | Module 1 | ROI correctly identifies counter area from mock LLM response |
| `test_product_counter_detect_objects_roi` | Module 1 | Detects product, promotional material, label from mock response |
| `test_product_counter_compliance_all_present` | Module 1 | Full compliance when all three elements detected |
| `test_product_counter_compliance_missing_label` | Module 1 | Penalized but not zeroed when label missing |
| `test_endcap_promo_init` | Module 2 | Validates initialization |
| `test_endcap_promo_compute_roi` | Module 2 | ROI identifies promotional panel and extends downward |
| `test_endcap_promo_illumination_on` | Module 2 | Backlit ON → compliant |
| `test_endcap_promo_illumination_off` | Module 2 | Backlit OFF → non-compliant (penalized) |
| `test_endcap_promo_poster_absent` | Module 2 | Missing lower poster → penalized |
| `test_type_registration` | Module 3 | Both types resolvable from `PlanogramCompliance._PLANOGRAM_TYPES` |

### Integration Tests
| Test | Description |
|---|---|
| `test_product_counter_pipeline_run` | Full pipeline run with `planogram_type="product_counter"` using mocked LLM |
| `test_endcap_promo_pipeline_run` | Full pipeline run with `planogram_type="endcap_no_shelves_promotional"` using mocked LLM |

### Test Data / Fixtures
```python
@pytest.fixture
def product_counter_config():
    return PlanogramConfig(
        planogram_type="product_counter",
        planogram_config={
            "brand": "Epson",
            "expected_elements": ["product", "promotional_background", "information_label"],
        },
        roi_detection_prompt="Identify the product counter display area...",
        object_identification_prompt="Identify the product, promotional material, and label...",
    )

@pytest.fixture
def endcap_no_shelves_config():
    return PlanogramConfig(
        planogram_type="endcap_no_shelves_promotional",
        planogram_config={
            "brand": "Epson",
            "expected_elements": ["backlit_panel", "lower_poster"],
            "illumination_expected": "ON",
        },
        roi_detection_prompt="Identify the promotional endcap display...",
        object_identification_prompt="Identify the backlit panel and lower poster...",
    )
```

---

## 5. Acceptance Criteria

- [ ] `ProductCounter` class implements all four abstract methods from `AbstractPlanogramType`
- [ ] `EndcapNoShelvesPromotional` class implements all four abstract methods from `AbstractPlanogramType`
- [ ] Both types are registered in `PlanogramCompliance._PLANOGRAM_TYPES`
- [ ] Both types are exported from `parrot_pipelines.planogram.types`
- [ ] Missing information label in product counter penalizes score but does not zero it
- [ ] Endcap type correctly calls illumination check and penalizes when backlit is OFF
- [ ] Example JSON config scripts are provided for both types
- [ ] All unit tests pass (`pytest tests/pipelines/test_product_counter.py tests/pipelines/test_endcap_no_shelves.py -v`)
- [ ] No breaking changes to existing `ProductOnShelves` or `GraphicPanelDisplay` types
- [ ] `get_grid_strategy()` returns `NoGrid()` for both types (no shelf grid)

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**

### Verified Imports
```python
# All confirmed to resolve:
from parrot_pipelines.planogram.types.abstract import AbstractPlanogramType  # abstract.py:22
from parrot.models.detections import Detection, BoundingBox, Detections, IdentifiedProduct, ShelfRegion  # parrot/models/detections.py
from parrot.models.compliance import ComplianceResult, ComplianceStatus, TextComplianceResult, TextMatcher  # parrot/models/compliance.py
from parrot_pipelines.planogram.grid.strategy import NoGrid  # grid/strategy.py
from PIL import Image  # third-party
```

### Existing Class Signatures
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

    def get_render_colors(self) -> Dict[str, Tuple[int, int, int]]:  # line 123
    def get_grid_strategy(self) -> "AbstractGridStrategy":  # line 139 — returns NoGrid() by default
```

```python
# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/graphic_panel_display.py:39
class GraphicPanelDisplay(AbstractPlanogramType):
    async def _check_illumination_from_roi(self, img: Image.Image, roi: Any, planogram_description: Any) -> str:  # line 665
        """Returns 'illumination_status: ON' or 'illumination_status: OFF'"""

# Module-level constants:
_DEFAULT_ILLUMINATION_PENALTY: float = 1.0  # line 33
_ILLUMINATION_FEATURE_PREFIX = "illumination_status:"  # line 36
```

```python
# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py:19
class PlanogramCompliance(AbstractPipeline):
    _PLANOGRAM_TYPES = {  # line 32
        "product_on_shelves": ProductOnShelves,
        "graphic_panel_display": GraphicPanelDisplay,
    }
    # Shared utilities available via self.pipeline:
    #   self.pipeline._downscale_image(img, max_side, quality)  — plan.py / legacy.py
    #   self.pipeline.roi_client  — async context manager for LLM calls
    #   self.pipeline.planogram_config  — PlanogramConfig instance
```

```python
# packages/ai-parrot-pipelines/src/parrot_pipelines/models.py:29
class PlanogramConfig(BaseModel):
    planogram_type: str  # line 44, default="product_on_shelves"
    planogram_config: Dict[str, Any]  # line 50
    roi_detection_prompt: str  # line 55
    object_identification_prompt: str  # line 60
    reference_images: Dict[str, Union[str, Path, List[str], List[Path], Image.Image]]  # line 65
    endcap_geometry: EndcapGeometry  # implicit (via Field default_factory)
    def get_planogram_description(self) -> PlanogramDescription: ...
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `ProductCounter` | `AbstractPlanogramType` | inheritance | `types/abstract.py:22` |
| `EndcapNoShelvesPromotional` | `AbstractPlanogramType` | inheritance | `types/abstract.py:22` |
| `EndcapNoShelvesPromotional` | `GraphicPanelDisplay._check_illumination_from_roi` | method reuse (call or extract) | `types/graphic_panel_display.py:665` |
| Both types | `PlanogramCompliance._PLANOGRAM_TYPES` | dict registration | `plan.py:32` |
| Both types | `self.pipeline.roi_client` | LLM calls via `ask_to_image` | `plan.py:187` |
| Both types | `self.pipeline._downscale_image` | image preprocessing | used in all existing types |

### Does NOT Exist (Anti-Hallucination)
- ~~`ProductCounter`~~ — does not exist yet (will be created)
- ~~`EndcapNoShelvesPromotional`~~ — does not exist yet (will be created)
- ~~`AbstractPlanogramType.check_illumination()`~~ — not a base class method; illumination check lives only in `GraphicPanelDisplay`
- ~~`PlanogramConfig.expected_elements`~~ — not a model field; element expectations live inside `planogram_config` dict
- ~~`parrot_pipelines.planogram.types.endcap`~~ — no such module exists
- ~~`parrot_pipelines.planogram.types.counter`~~ — no such module exists

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Follow the same structure as `ProductOnShelves` and `GraphicPanelDisplay` — each in its own file under `types/`.
- Use `self.pipeline.roi_client` + `ask_to_image` for all LLM calls.
- Use `self.pipeline._downscale_image()` before sending images to LLM.
- For `EndcapNoShelvesPromotional` illumination: either call `GraphicPanelDisplay._check_illumination_from_roi` as a standalone function (extract to a utility), or duplicate the ~40 lines of prompt logic. Extracting to a shared utility in `abstract.py` or a new `utils.py` is preferred.
- `detect_objects` for `EndcapNoShelvesPromotional` returns empty lists `([], [])` since no physical products exist — similar to how `GraphicPanelDisplay` handles it.
- Both types should return `NoGrid()` from `get_grid_strategy()` (inherited default behavior — no override needed).

### ProductCounter — Detection Logic
1. **`compute_roi`**: Use LLM to find the counter/podium area in the image. Return the bounding box of the display.
2. **`detect_objects_roi`**: Within the ROI, ask LLM to identify three macro elements: `product`, `promotional_background`, `information_label`.
3. **`detect_objects`**: Map the detected product to an `IdentifiedProduct`. Return empty `ShelfRegion` list (no shelves).
4. **`check_planogram_compliance`**: Score based on presence of all three elements. Missing label → penalty (configurable weight, default 0.3). Missing product → 0 score.

### EndcapNoShelvesPromotional — Detection Logic
1. **`compute_roi`**: Use LLM to find the promotional panel (top backlit area). Expand bbox downward to include the full endcap including lower poster.
2. **`detect_objects_roi`**: Within ROI, ask LLM to identify `backlit_panel` and `lower_poster` zones.
3. **`detect_objects`**: No products — return `([], [])`.
4. **`check_planogram_compliance`**: Check backlit ON/OFF via illumination logic. Check poster presence. Score accordingly.

### Known Risks / Gotchas
- **Illumination reuse**: `_check_illumination_from_roi` is currently a private method on `GraphicPanelDisplay`. Best approach is to extract the prompt logic to a shared function, but duplicating it is acceptable to avoid modifying existing code.
- **Ambient light confusion**: The brainstorm notes that high ambient light can confuse the LLM on backlit status. The existing illumination prompt already handles this by comparing top vs. middle/bottom panel brightness — reuse that prompt.
- **Label weight scoring**: The weight for missing labels in `ProductCounter` should be configurable via the `planogram_config` dict (e.g., `label_missing_penalty: 0.3`).

### External Dependencies
No new external dependencies required.

---

## 8. Open Questions

- [x] Define exact weights for missing label vs. missing promotional material in `ProductCounter` — *Owner: SDD Implementer (use defaults: label=0.3, promo=0.5, product=1.0)*
- [x] Should illumination logic be extracted to a shared utility or duplicated? — *Owner: SDD Implementer (prefer extraction if touching GraphicPanelDisplay is safe)*

---

## Worktree Strategy

- **Isolation unit**: `per-spec` (sequential tasks in one worktree)
- All five modules are tightly coupled and should be implemented in order within a single worktree.
- **Cross-feature dependencies**: None — this spec is independent of other open specs.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-04-06 | Antigravity | Initial draft from brainstorm Option A |
