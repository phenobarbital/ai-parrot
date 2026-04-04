# Feature Specification: Adaptive Grid Detection for Planogram Pipelines

**Feature ID**: FEAT-084
**Date**: 2026-04-04
**Author**: Jesus Lara
**Status**: approved
**Target version**: 1.x.0
**Brainstorm**: `sdd/proposals/parrot-pipelines-inconsistency.brainstorm.md`

---

## 1. Motivation & Business Requirements

### Problem Statement

The Planogram Compliance Pipeline suffers from **LLM detection inconsistency** caused by three interrelated factors:

1. **Attention dilution**: A single LLM call processes the entire ROI image with ALL products, shelves, and hints concatenated. When the ROI is large or product-dense, the LLM's attention degrades — producing variable results between runs (e.g., ES-C220 detected in one run, misidentified as ES-C320W in the next).

2. **Configuration coupling**: A monolithic prompt containing all product hints means tuning for one planogram type can break detection for another. Different planogram types (Ink Walls, TV Walls, Boxes on Floor) have fundamentally different spatial layouts but share the same single-image detection path.

3. **No spatial decomposition**: The ROI is sent as-is to the LLM. Virtual shelves exist but are only used *after* detection for assignment, not *before* detection to guide the LLM's focus.

**Evidence** (same image, two runs):

| Aspect              | Run A (65.8%)              | Run B (41.4%)                 |
|----------------------|---------------------------|-------------------------------|
| Top shelf            | 100% (7/7 with OCR)       | 85.7% (6/7, ES-C320W miss)   |
| Middle shelf         | 33.3% (ES-C220 correct)   | 0% (ES-C220→ES-C320W)        |
| Bottom shelf         | 50% (V39-II correct)      | 0% (V39-II miss)             |
| ES-580W false pos    | No                         | Yes                           |
| Guards/Boundaries    | Correct                    | Correct                       |

Guards and boundaries work correctly — the problem is purely in the LLM detection layer.

### Goals
- Reduce LLM detection variability by spatially decomposing the ROI into focused grid cells before detection
- Support multiple grid strategies per planogram type: horizontal bands (shelves), NxM matrix (ink walls), named zones (TV walls), flat grid (boxes on floor)
- Enable per-cell focused prompts with only relevant product hints and reference images
- Support multiple reference images per product (different angles/lighting conditions)
- Report unexpected "out of place" objects detected in each cell (informational)
- Maintain full backward compatibility with existing `PlanogramConfig` and API contracts

### Non-Goals (explicitly out of scope)
- Multi-run consensus (too expensive for real-time use)
- YOLO/hybrid detection (performance concerns, fine-tuning limitations)
- Implementing new planogram type handlers (InkWall, TVWall, BoxesOnFloor) — only the grid infrastructure and HorizontalBands for `ProductOnShelves`
- Changing the compliance scoring algorithm
- Modifying the ROI detection stage (Stage 1)
- Database schema migration for `troc.planograms_configurations` (future work)

---

## 2. Architectural Design

### Overview

Introduce a **Detection Grid** layer between ROI detection (Stage 1) and object detection (Stage 2). After the ROI is computed, a pluggable `GridStrategy` decomposes the ROI into independent cells. Each cell is detected in parallel via `asyncio.gather()` with focused prompts, filtered hints, and relevant reference images. Results are merged with coordinate offset correction and IoU-based boundary deduplication, then fed to the existing compliance layer unchanged.

### Component Diagram
```
[Stage 1] ROI Detection (unchanged)
    │
    ▼
[GridStrategy] ─── config.detection_grid ──→ resolve strategy
    │                                         │
    │  ┌──────────────────────────────────────┘
    │  │
    ▼  ▼
[GridStrategy.compute_cells(roi_bbox, planogram)]
    │
    ├── GridCell(bbox, hints, ref_images)  ──→ LLM detect_objects()
    ├── GridCell(bbox, hints, ref_images)  ──→ LLM detect_objects()  } asyncio.gather
    └── GridCell(bbox, hints, ref_images)  ──→ LLM detect_objects()
    │
    ▼
[CellResultMerger]
    ├── Apply per-cell coordinate offsets
    ├── Deduplicate boundary objects (IoU)
    └── Tag unexpected objects
    │
    ▼
[Stage 3] Compliance Check (unchanged)
    │
    ▼
[Stage 4] Rendering (unchanged)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractPlanogramType` | extends | Add default `get_grid_strategy()` returning `NoGrid` |
| `ProductOnShelves` | modifies | `detect_objects()` refactored to use grid-based detection |
| `PlanogramConfig` | extends | Add optional `detection_grid` field |
| `PlanogramCompliance` | modifies | Detection stage orchestrates per-cell parallel calls |
| `GoogleAnalysis.detect_objects()` | no change | Already supports multi-image via `contents[]` |
| `ComplianceResult` | extends | Add optional `out_of_place_items` field |
| `IdentifiedProduct` | no change | Existing model sufficient |
| `ShelfRegion` | no change | Generated after detection merge, as before |

### Data Models

```python
from enum import Enum
from typing import Dict, List, Optional, Tuple, Union
from pathlib import Path
from PIL import Image
from pydantic import BaseModel, Field


class GridType(str, Enum):
    """Supported grid decomposition strategies."""
    NO_GRID = "no_grid"
    HORIZONTAL_BANDS = "horizontal_bands"
    MATRIX_GRID = "matrix_grid"
    ZONE_GRID = "zone_grid"
    FLAT_GRID = "flat_grid"


class DetectionGridConfig(BaseModel):
    """Configuration for detection grid decomposition.

    Added as an optional field to PlanogramConfig.
    When None or grid_type='no_grid', pipeline uses current single-image behavior.
    """
    grid_type: GridType = Field(
        default=GridType.NO_GRID,
        description="Grid decomposition strategy"
    )
    overlap_margin: float = Field(
        default=0.05,
        ge=0.0, le=0.20,
        description="Overlap between adjacent cells as ratio of cell dimension"
    )
    max_image_size: int = Field(
        default=1024,
        description="Max pixel dimension for each cell image sent to LLM"
    )
    # For MATRIX_GRID
    rows: Optional[int] = Field(default=None, description="Number of rows (matrix grid)")
    cols: Optional[int] = Field(default=None, description="Number of columns (matrix grid)")
    # For FLAT_GRID
    flat_divisions: Optional[int] = Field(
        default=None,
        description="NxN divisions for flat grid (e.g., 2 = 2x2, 3 = 3x3)"
    )
    # For ZONE_GRID
    zones: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="Named zone definitions [{name, y_start_ratio, y_end_ratio, x_start_ratio, x_end_ratio}]"
    )


class GridCell(BaseModel):
    """A single cell in the detection grid."""
    cell_id: str = Field(description="Unique identifier (e.g., 'shelf_top', 'matrix_1_2')")
    bbox: Tuple[int, int, int, int] = Field(
        description="Absolute pixel coordinates (x1, y1, x2, y2) within the full image"
    )
    expected_products: List[str] = Field(
        default_factory=list,
        description="Product names expected in this cell (from planogram config)"
    )
    reference_image_keys: List[str] = Field(
        default_factory=list,
        description="Keys into reference_images dict for products in this cell"
    )
    level: Optional[str] = Field(
        default=None,
        description="Shelf level or zone name, if applicable"
    )
```

### New Public Interfaces

```python
from abc import ABC, abstractmethod
from typing import List, Tuple, Optional, Any, Dict, Union
from PIL import Image
from parrot.models.detections import IdentifiedProduct, ShelfRegion


class AbstractGridStrategy(ABC):
    """Base class for grid decomposition strategies.

    Concrete strategies implement compute_cells() to split an ROI
    into detection cells based on planogram configuration.
    """

    @abstractmethod
    def compute_cells(
        self,
        roi_bbox: Tuple[int, int, int, int],
        image_size: Tuple[int, int],
        planogram_description: Any,
        grid_config: "DetectionGridConfig",
    ) -> List["GridCell"]:
        """Decompose the ROI into grid cells for detection.

        Args:
            roi_bbox: ROI coordinates (x1, y1, x2, y2) in pixels.
            image_size: Full image (width, height).
            planogram_description: PlanogramDescription with shelf/product info.
            grid_config: Grid configuration parameters.

        Returns:
            List of GridCell, each defining a region to detect independently.
        """


class CellResultMerger:
    """Merges per-cell detection results into a unified product list.

    Handles coordinate offset correction and IoU-based deduplication
    for products spanning cell boundaries.
    """

    def merge(
        self,
        cell_results: List[Tuple["GridCell", List[IdentifiedProduct]]],
        iou_threshold: float = 0.5,
    ) -> List[IdentifiedProduct]:
        """Merge detection results from multiple grid cells.

        Args:
            cell_results: List of (cell, products) tuples from parallel detection.
            iou_threshold: IoU threshold for boundary deduplication.

        Returns:
            Unified list of IdentifiedProduct with absolute coordinates.
        """
```

---

## 3. Module Breakdown

### Module 1: Detection Grid Models
- **Path**: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/grid/models.py`
- **Responsibility**: Pydantic models — `DetectionGridConfig`, `GridCell`, `GridType` enum
- **Depends on**: `pydantic`

### Module 2: Abstract Grid Strategy
- **Path**: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/grid/strategy.py`
- **Responsibility**: `AbstractGridStrategy` ABC + `NoGrid` default implementation (returns single cell = full ROI)
- **Depends on**: Module 1

### Module 3: HorizontalBands Strategy
- **Path**: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/grid/horizontal_bands.py`
- **Responsibility**: Grid strategy for `product_on_shelves` — splits ROI into N horizontal bands using `height_ratio` from shelf config. Maps expected products per band from `PlanogramDescription.shelves[].products[]`. Applies configurable overlap margin between adjacent bands.
- **Depends on**: Module 2, `PlanogramDescription.shelves`

### Module 4: Cell Result Merger
- **Path**: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/grid/merger.py`
- **Responsibility**: `CellResultMerger` — applies per-cell coordinate offsets to convert cell-relative detections to absolute image coordinates. Deduplicates boundary objects using IoU. Tags objects not in any cell's `expected_products` as potential "out of place" items.
- **Depends on**: Module 1, `IdentifiedProduct`, `DetectionBox`

### Module 5: Grid-Based Detection Orchestrator
- **Path**: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/grid/detector.py`
- **Responsibility**: `GridDetector` — takes a list of `GridCell`, crops images, builds per-cell prompts with filtered hints and reference images, executes parallel LLM calls via `asyncio.gather()`, passes results to `CellResultMerger`. Handles per-cell retry on API failure.
- **Depends on**: Modules 1-4, `GoogleAnalysis.detect_objects()`

### Module 6: PlanogramConfig Extension
- **Path**: `packages/ai-parrot-pipelines/src/parrot_pipelines/models.py` (modify existing)
- **Responsibility**: Add `detection_grid: Optional[DetectionGridConfig] = None` field to `PlanogramConfig`. Support `reference_images: Dict[str, Union[str, Path, List[str], List[Path], Image.Image]]` for multi-reference per product.
- **Depends on**: Module 1

### Module 7: AbstractPlanogramType Extension
- **Path**: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py` (modify existing)
- **Responsibility**: Add `get_grid_strategy() -> AbstractGridStrategy` method with default `NoGrid` implementation. Subclasses override to return their type-specific strategy.
- **Depends on**: Module 2

### Module 8: ProductOnShelves Refactor
- **Path**: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py` (modify existing)
- **Responsibility**: Refactor `detect_objects()` to: (1) resolve grid strategy via `self.get_grid_strategy()`, (2) compute cells, (3) delegate to `GridDetector` for parallel per-cell detection, (4) merge results via `CellResultMerger`. Override `get_grid_strategy()` to return `HorizontalBands`. Falls back to current behavior when `detection_grid` is None.
- **Depends on**: Modules 3, 5, 7

### Module 9: ComplianceResult Extension
- **Path**: `packages/ai-parrot/src/parrot/models/compliance.py` (modify existing)
- **Responsibility**: Add `out_of_place_items: List[str] = Field(default_factory=list)` to `ComplianceResult` for informational reporting of unexpected objects.
- **Depends on**: None (model-only change)

### Module 10: Grid Package Init + Registry
- **Path**: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/grid/__init__.py`
- **Responsibility**: Package init with `__all__` exports. Grid strategy registry mapping `GridType` → strategy class. Factory function `get_grid_strategy(grid_type: GridType) -> AbstractGridStrategy`.
- **Depends on**: Modules 1-4

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_grid_cell_model` | Module 1 | Validates GridCell construction with valid/invalid bbox |
| `test_detection_grid_config_defaults` | Module 1 | DetectionGridConfig defaults to NoGrid, overlap 0.05 |
| `test_no_grid_single_cell` | Module 2 | NoGrid returns single cell covering full ROI |
| `test_horizontal_bands_3_shelves` | Module 3 | 3 shelves with height_ratios [0.34, 0.25, 0.41] produce 3 bands with correct pixel coords |
| `test_horizontal_bands_overlap` | Module 3 | Overlap margin extends cells correctly without exceeding ROI |
| `test_horizontal_bands_expected_products` | Module 3 | Each band maps correct products from PlanogramDescription.shelves |
| `test_merger_offset_correction` | Module 4 | Cell-relative coords correctly converted to absolute |
| `test_merger_iou_dedup` | Module 4 | Overlapping detections at cell boundary merged correctly |
| `test_merger_out_of_place_tagging` | Module 4 | Objects not in expected_products tagged as out_of_place |
| `test_grid_detector_parallel` | Module 5 | N cells produce N parallel LLM calls (mock) |
| `test_grid_detector_cell_failure` | Module 5 | One cell API failure doesn't block other cells |
| `test_planogram_config_backward_compat` | Module 6 | Existing configs without detection_grid still work |
| `test_multi_reference_images` | Module 6 | Dict[str, List[Path]] accepted alongside Dict[str, Path] |
| `test_product_on_shelves_no_grid_fallback` | Module 8 | detection_grid=None produces same results as current behavior |
| `test_compliance_result_out_of_place` | Module 9 | out_of_place_items field serializes correctly |

### Integration Tests
| Test | Description |
|---|---|
| `test_grid_detection_end_to_end` | Full pipeline with HorizontalBands grid on a test image, verify per-cell detection produces merged results |
| `test_no_grid_regression` | Full pipeline without grid config produces identical results to pre-refactor baseline |

### Test Data / Fixtures
```python
@pytest.fixture
def sample_roi_bbox():
    return (100, 50, 900, 750)  # x1, y1, x2, y2

@pytest.fixture
def sample_planogram_3_shelves():
    """PlanogramDescription with 3 shelves and known products."""
    return PlanogramDescription(
        brand="Epson",
        category="printers",
        shelves=[
            ShelfConfig(level="top", height_ratio=0.34, products=[...]),
            ShelfConfig(level="middle", height_ratio=0.25, products=[...]),
            ShelfConfig(level="bottom", height_ratio=0.41, products=[...]),
        ],
        ...
    )

@pytest.fixture
def sample_detection_grid_config():
    return DetectionGridConfig(
        grid_type=GridType.HORIZONTAL_BANDS,
        overlap_margin=0.05,
        max_image_size=1024,
    )
```

---

## 5. Acceptance Criteria

- [ ] `detection_grid: None` (or absent) produces identical pipeline behavior to current implementation — zero regression
- [ ] `detection_grid` with `horizontal_bands` splits ROI into N cells matching shelf count and height ratios
- [ ] Per-cell LLM calls execute in parallel via `asyncio.gather()` — verified via timing or mock call counting
- [ ] Per-cell prompts contain ONLY the product hints for that cell's expected products
- [ ] Per-cell reference images filtered to only products expected in that cell
- [ ] Multiple reference images per product supported: `{product: [img1, img2, img3]}`
- [ ] Boundary objects deduplicated via IoU with configurable threshold
- [ ] Unexpected objects (not in any cell's expected list) reported in `ComplianceResult.out_of_place_items`
- [ ] All existing planogram compliance tests continue passing
- [ ] No breaking changes to `PlanogramConfig` — existing DB records deserialize correctly
- [ ] Pipeline runs successfully in both real-time and batch modes
- [ ] Unit test coverage for all new modules

---

## 6. Codebase Contract

### Verified Imports
```python
# Confirmed working imports:
from parrot.models.detections import IdentifiedProduct, ShelfRegion, Detection, DetectionBox  # parrot/models/detections.py
from parrot.models.detections import PlanogramDescription  # parrot/models/detections.py:301
from parrot.models.compliance import ComplianceResult, ComplianceStatus  # parrot/models/compliance.py
from parrot_pipelines.models import PlanogramConfig, EndcapGeometry  # models.py:28, :11
from parrot_pipelines.planogram.types.abstract import AbstractPlanogramType  # types/abstract.py:21
from parrot_pipelines.planogram.types.product_on_shelves import ProductOnShelves  # types/product_on_shelves.py
from parrot_pipelines.planogram.plan import PlanogramCompliance  # plan.py:19
```

### Existing Class Signatures

```python
# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py
class AbstractPlanogramType(ABC):  # line 21
    def __init__(self, pipeline: "PlanogramCompliance", config: "PlanogramConfig") -> None:  # line 39
    # Abstract methods:
    async def compute_roi(self, img: Image.Image) -> Tuple[Optional[Tuple[int,int,int,int]], Optional[Any], Optional[Any], Optional[Any], List[Any]]:  # line 48
    async def detect_objects_roi(self, img: Image.Image, roi: Any) -> List[Detection]:  # line 69
    async def detect_objects(self, img: Image.Image, roi: Any, macro_objects: Any) -> Tuple[List[IdentifiedProduct], List[ShelfRegion]]:  # line 88
    def check_planogram_compliance(self, identified_products: List[IdentifiedProduct], planogram_description: Any) -> List[ComplianceResult]:  # line 106
    # Default method:
    def get_render_colors(self) -> Dict[str, Tuple[int, int, int]]:  # line 122 (concrete, not abstract)

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py
class ProductOnShelves(AbstractPlanogramType):
    async def detect_objects(self, img, roi, macro_objects) -> Tuple[List[IdentifiedProduct], List[ShelfRegion]]:  # line 102
        # lines 123: planogram_description = self.config.get_planogram_description()
        # lines 125-132: ROI crop with offset_x, offset_y
        # lines 134-142: Build hints from all shelves → hints_str
        # lines 143-154: Monolithic prompt
        # lines 160: refs = list(self.pipeline.reference_images.values())
        # lines 172-177: Single LLM call → self.pipeline.llm.detect_objects(image=target_image, prompt=obj_prompt, reference_images=refs)
    def _generate_virtual_shelves(self, roi_bbox: DetectionBox, image_size: Tuple[int,int], planogram: Any) -> List[ShelfRegion]:  # line 956

# packages/ai-parrot-pipelines/src/parrot_pipelines/models.py
class EndcapGeometry(BaseModel):  # line 11
    aspect_ratio: float = 1.35  # line 13
    inter_shelf_padding: float = 0.02  # line 20
class PlanogramConfig(BaseModel):  # line 28
    planogram_id: Optional[int]  # line 33
    config_name: str  # line 38
    planogram_type: str  # line 43 — default "product_on_shelves"
    planogram_config: Dict[str, Any]  # line 49
    roi_detection_prompt: str  # line 54
    object_identification_prompt: str  # line 59
    reference_images: Dict[str, Union[str, Path, Image.Image]]  # line 64
    confidence_threshold: float = 0.25  # line 70
    detection_model: str = "yolo11l.pt"  # line 75
    endcap_geometry: EndcapGeometry  # line 80
    def get_planogram_description(self) -> PlanogramDescription:  # line 89

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py
class PlanogramCompliance(AbstractPipeline):  # line 19
    _PLANOGRAM_TYPES = {  # line 32
        "product_on_shelves": ProductOnShelves,
        "graphic_panel_display": GraphicPanelDisplay,
    }
    def __init__(self, planogram_config: PlanogramConfig, llm: Any = None, llm_provider: str = "google", llm_model: Optional[str] = None, **kwargs) -> None:  # line 37
    async def run(self, image: Union[str, Path, Image.Image], output_dir=None, image_id=None, **kwargs) -> Dict[str, Any]:  # line 71
        # line 101: await self._type_handler.compute_roi(img)
        # line 144: await self._type_handler.detect_objects(img, roi=endcap, macro_objects=None)
        # line 239: self._type_handler._generate_virtual_shelves(...)
        # line 307: self._type_handler.check_planogram_compliance(...)

# packages/ai-parrot/src/parrot/clients/google/analysis.py
class GoogleAnalysis:  # (mixin used by GoogleGenAIClient)
    async def detect_objects(
        self,
        image: Union[str, Path, Image.Image],
        prompt: str,
        reference_images: Optional[List[Union[str, Path, Image.Image]]] = None,
        output_dir: Optional[Union[str, Path]] = None
    ) -> List[Dict[str, Any]]:  # line 1094
        # line 1114: im.thumbnail([1024, 1024])
        # line 1118-1121: ThinkingConfig(thinking_budget=0), response_mime_type="application/json"
        # line 1124: model="gemini-3-flash"
        # line 1127-1133: contents = [prompt, im, *refs]
        # line 1135: client.aio.models.generate_content(model="gemini-3-flash", contents=contents, config=config)

# packages/ai-parrot/src/parrot/models/detections.py
class DetectionBox(BaseModel):  # bounding box with get_pixel_coordinates()
class ShelfRegion(BaseModel):  # line 62
    shelf_id: str
    bbox: DetectionBox
    level: str
    objects: List[DetectionBox] = []
    is_background: bool = False
class IdentifiedProduct(BaseModel):  # line 71
    detection_id: int = None
    product_type: str
    product_model: Optional[str] = None
    brand: Optional[str] = None
    confidence: float
    visual_features: List[str] = []
    reference_match: Optional[str] = None
    shelf_location: Optional[str] = None
    position_on_shelf: Optional[str] = None
    ocr_text: Optional[str] = None
    detection_box: Optional[DetectionBox] = None
    extra: Dict[str, str] = {}
class PlanogramDescription(BaseModel):  # line 301
    brand: str
    shelves: List[ShelfConfig]
    global_compliance_threshold: float = 0.8
    model_normalization_patterns: Optional[List[str]] = None

# packages/ai-parrot/src/parrot/models/compliance.py
class ComplianceResult(BaseModel):  # line 32
    shelf_level: str
    expected_products: List[str]
    found_products: List[str]
    missing_products: List[str]
    unexpected_products: List[str]
    compliance_status: ComplianceStatus
    compliance_score: float
    text_compliance_results: List[TextComplianceResult] = []
    brand_compliance_result: Optional[BrandComplianceResult] = None
    text_compliance_score: float = 1.0
    overall_text_compliant: bool = True
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `GridDetector` | `GoogleAnalysis.detect_objects()` | async method call | `analysis.py:1094` |
| `HorizontalBands` | `PlanogramDescription.shelves` | reads shelf config | `detections.py:301` |
| `ProductOnShelves.detect_objects()` | `GridDetector.detect_cells()` | delegates detection | `product_on_shelves.py:102` |
| `PlanogramConfig.detection_grid` | `DetectionGridConfig` | optional Pydantic field | `models.py:28` |
| `AbstractPlanogramType.get_grid_strategy()` | `AbstractGridStrategy` | returns strategy | `abstract.py:21` |
| `CellResultMerger` | `IdentifiedProduct.detection_box` | reads bbox for IoU | `detections.py:71` |

### Does NOT Exist (Anti-Hallucination)
- ~~`DetectionGridConfig`~~ — must be created in Module 1
- ~~`GridCell`~~ — must be created in Module 1
- ~~`GridType`~~ — must be created in Module 1
- ~~`AbstractGridStrategy`~~ — must be created in Module 2
- ~~`NoGrid`~~ — must be created in Module 2
- ~~`HorizontalBands`~~ — must be created in Module 3
- ~~`CellResultMerger`~~ — must be created in Module 4
- ~~`GridDetector`~~ — must be created in Module 5
- ~~`AbstractPlanogramType.get_grid_strategy()`~~ — does not exist; add in Module 7
- ~~`PlanogramConfig.detection_grid`~~ — does not exist; add in Module 6
- ~~`ComplianceResult.out_of_place_items`~~ — does not exist; add in Module 9
- ~~`parrot_pipelines.planogram.grid`~~ — package does not exist; create in Module 10
- ~~`parrot_pipelines.planogram.types.ink_wall`~~ — does not exist (out of scope)
- ~~`parrot_pipelines.planogram.types.tv_wall`~~ — does not exist (out of scope)
- ~~`parrot_pipelines.planogram.types.boxes_on_floor`~~ — does not exist (out of scope)
- ~~`MatrixGrid`~~ — out of scope for this spec (future grid strategy)
- ~~`ZoneGrid`~~ — out of scope for this spec (future grid strategy)
- ~~`FlatGrid`~~ — out of scope for this spec (future grid strategy)

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Use `AbstractGridStrategy` ABC pattern consistent with `AbstractPlanogramType`
- All grid strategies must be stateless — configuration via `DetectionGridConfig`
- Use `asyncio.gather(*tasks, return_exceptions=True)` for parallel cell detection with per-cell error isolation
- Pydantic models for all new data structures (`GridCell`, `DetectionGridConfig`)
- Comprehensive logging with `self.logger` for each cell detection (cell_id, timing, product count)
- Follow existing coordinate system: `(x1, y1, x2, y2)` absolute pixel coords

### Known Risks / Gotchas
- **Boundary deduplication**: IoU threshold of 0.5 is standard but may need per-planogram tuning. Start with 0.5, expose as config.
- **Gemini rate limits**: Parallel calls per pipeline run (typically 3-5) should be within limits, but batch mode running many images may hit rate limits. Consider a semaphore if needed.
- **Reference image filtering**: If a product is expected on multiple shelves, its reference images go to all relevant cells. If no products are expected (exploratory cell), send all references.
- **Coordinate precision**: Cell-relative coords must be accurately offset-corrected. Off-by-one errors at cell boundaries will cause misalignment. Use the same offset pattern as existing ROI crop (lines 125-132 of product_on_shelves.py).
- **Prompt size per cell**: With fewer hints and fewer reference images, per-cell prompts should be well within Gemini's limits. But monitor total token usage.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `google-genai` | (existing) | LLM API calls — no new dependency |
| `Pillow` | (existing) | Image cropping/resizing — no new dependency |
| `pydantic` | (existing) | Data models — no new dependency |

**No new external dependencies required.**

---

## 8. Open Questions

- [x] What overlap margin (%) between grid cells minimizes boundary object duplication while ensuring coverage? Start with 5%, tune empirically. — *Owner: Jesus Lara*: Let's tune empirically starting from 5%
- [x] What IoU threshold for boundary deduplication? Start with 0.5, tune empirically. — *Owner: Jesus Lara*: same, start with 0.5
- [x] Should `out_of_place` be a field on `ComplianceResult` (per-shelf list) or on `IdentifiedProduct` (per-product flag)? Brainstorm suggested ComplianceResult field. — *Owner: Jesus Lara*: on IdentifiedProduct.
- [x] For future grid strategies (MatrixGrid, ZoneGrid, FlatGrid): what are typical dimensions for Ink Walls and TV Walls? Need example configs. — *Owner: Jesus Lara*: We don't have it yet.
- [x] Should reference images be stored in DB as paths or base64? Current `Dict[str, path]` assumes filesystem access. — *Owner: Jesus Lara*: current asumes filesystem access, in future (not this scope), will be extracted from database.

---

## Worktree Strategy

- **Isolation unit**: `per-spec` — all tasks run sequentially in one worktree
- **Rationale**: Modules 1-5 build on each other (grid models → strategy ABC → concrete strategy → merger → detector). Modules 6-9 modify existing files that must see the new grid package. Sequential development ensures consistency.
- **Cross-feature dependencies**: None — this feature touches the detection layer of `parrot_pipelines` which has no conflicts with FEAT-082 (sqlagent-repair) or FEAT-083 (formdesigner-authentication).

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-04-04 | Jesus Lara | Initial draft from brainstorm |
