# Brainstorm: Adaptive Grid Detection for Planogram Pipelines

**Date**: 2026-04-04
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: Option B

---

## Problem Statement

The Planogram Compliance Pipeline suffers from **LLM detection inconsistency** caused by three interrelated factors:

1. **Attention dilution**: A single LLM call processes the entire ROI image with ALL products, shelves, and hints concatenated. When the ROI is large or product-dense, the LLM's attention degrades — producing variable results between runs (e.g., ES-C220 detected in one run, misidentified as ES-C320W in the next).

2. **Configuration coupling**: The current architecture uses a single `detect_objects()` call with a monolithic prompt containing all product hints. Tuning this prompt or reference images for one planogram type (e.g., Epson product_on_shelves) can break detection for another configuration. Different planogram types (Ink Walls, TV Walls, Boxes on Floor) have fundamentally different spatial layouts but share the same detection path.

3. **No spatial decomposition**: The ROI is sent as-is to the LLM — there is no subdivision into manageable regions. Virtual shelves exist but are only used *after* detection for assignment, not *before* detection to guide the LLM's focus.

**Evidence of inconsistency** (same image, two runs):

| Aspect              | Run A (65.8%)              | Run B (41.4%)                 |
|----------------------|---------------------------|-------------------------------|
| Top shelf            | 100% (7/7 with OCR)       | 85.7% (6/7, ES-C320W miss)   |
| Middle shelf         | 33.3% (ES-C220 correct)   | 0% (ES-C220→ES-C320W)        |
| Bottom shelf         | 50% (V39-II correct)      | 0% (V39-II miss)             |
| ES-580W false pos    | No                         | Yes                           |
| Guards/Boundaries    | Correct                    | Correct                       |

The guards and boundaries work correctly — the problem is purely in the LLM detection layer.

**Who is affected**: Retail operations teams relying on compliance scores for planogram audits. Inconsistent scores erode trust in the system.

## Constraints & Requirements

- **Backward compatible**: `PlanogramConfig` schema must remain compatible with existing DB records; new fields must be optional with sensible defaults
- **Async-first**: All detection calls must be non-blocking; parallel execution via `asyncio.gather` is preferred
- **Latency budget**: Pipeline runs in both real-time (app) and batch (task) modes; per-cell parallel calls acceptable, multi-run consensus is NOT (too expensive)
- **Gemini API limits**: Up to 3,600 images per request; images >384px cost 258 tokens per 768x768 tile; 20MB total inline limit
- **Multi-planogram-type support**: Solution must accommodate Product on Shelves (horizontal bands), Ink Walls (NxM grid), TV Walls (zones), Boxes on Floor (flat area) — each with different grid strategies
- **Production system**: This is deployed in production; changes must be incremental and testable
- **LLM reports everything**: Detection should report ALL objects in each cell (including unexpected items like soda bottles); the compliance layer handles "out of place" classification

---

## Options Explored

### Option A: Single Mega-Request with Labeled Crops

Send all grid cells as separate images within ONE Gemini API call, with a structured prompt that labels each image by its grid position.

**How it works:**
1. After ROI detection, split the ROI into grid cells based on planogram type config
2. Crop and downscale each cell independently
3. Assemble a single `contents[]` array: `[prompt, cell_1_img, cell_2_img, ..., ref_img_1, ref_img_2, ...]`
4. Prompt structure: "Image 1 is the top shelf region. Image 2 is the middle shelf region... For each region, detect all objects and return results tagged by region."
5. Parse response, apply coordinate offsets per cell to get absolute positions

**Pros:**
- Single API call — minimal latency overhead
- Gemini natively handles multi-image in `contents[]`
- Reference images shared across cells efficiently
- Simpler error handling (one call to retry)

**Cons:**
- Still ONE LLM context — attention dilution may persist across cells if the total image count is high
- Complex prompt engineering to keep per-cell results separated
- If one cell's detection fails, entire response may be corrupted
- No per-cell hint filtering — all hints still visible to the LLM
- Response parsing is fragile (LLM must tag results by region consistently)

**Effort:** Medium

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `google-genai` | Multi-image Gemini API calls | Already in use, native multi-image |
| `Pillow` | Image cropping/downscaling | Already in use |

**Existing Code to Reuse:**
- `product_on_shelves.py:956` — `_generate_virtual_shelves()` for horizontal band geometry
- `abstract.py` — `_downscale_image()` for per-cell image preparation
- `plan.py` — `PlanogramCompliance` orchestration

---

### Option B: Parallel Per-Cell Detection (Recommended)

Split the ROI into grid cells and execute **independent, parallel LLM calls** per cell — each with focused hints and relevant reference images only.

**How it works:**
1. After ROI detection, a `DetectionGrid` strategy (configured per planogram type) splits the ROI into cells
2. Each cell gets its own detection call with:
   - Only the cropped cell image (downscaled independently)
   - Only the reference images for products expected in that cell (or all refs for "unknown" cells)
   - Only the product hints relevant to that cell's expected contents
   - A focused prompt: "Detect ALL objects in this image. Report everything you see."
3. All cell calls execute in parallel via `asyncio.gather()`
4. A merge step combines results: apply per-cell coordinate offsets, deduplicate objects at cell boundaries
5. Merged results feed into the existing compliance/scoring layer unchanged

**Grid strategies by planogram type:**
- `HorizontalBands` — for Product on Shelves: N horizontal strips by `height_ratio`
- `MatrixGrid` — for Ink Walls: NxM rectangular cells
- `ZoneGrid` — for TV Walls: named zones (top-info, tv-area, bottom-info)
- `FlatGrid` — for Boxes on Floor: simple 2x2 or 3x3 overlay
- `NoGrid` (default) — for backward compatibility: single cell = entire ROI (current behavior)

**Reference images per product:**
- Change `reference_images: Dict[str, path]` to support `Dict[str, Union[path, List[path]]]`
- Each product can have multiple reference images (different angles, lighting)
- Per-cell calls send only references for expected products in that cell + a few "general" references

**Pros:**
- Maximum LLM focus per cell — fewer objects, fewer hints, smaller image = more consistent detection
- Truly isolated attention — one cell's complexity doesn't affect another
- Per-cell hint filtering reduces model confusion (ES-C220 vs ES-C320W only compared in cells where both are plausible)
- Parallel execution via `asyncio.gather` — N small calls can be faster than 1 large call
- Clean separation of concerns: grid strategy is pluggable per planogram type
- Backward compatible: `detection_grid: None` = current behavior (single-cell)
- Each cell call is independently retryable on failure
- Natural extension point for future per-cell confidence thresholds

**Cons:**
- Multiple API calls — higher total token cost (though each call is smaller)
- Boundary objects (products spanning two cells) need deduplication logic
- Grid strategy must be configured per planogram type (additional config surface)
- Coordinate offset arithmetic for each cell adds complexity

**Effort:** Medium-High

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `google-genai` | Per-cell Gemini API calls | Already in use |
| `Pillow` | Image cropping/downscaling per cell | Already in use |
| `asyncio` | Parallel cell detection | Already in use throughout parrot |

**Existing Code to Reuse:**
- `product_on_shelves.py:956` — `_generate_virtual_shelves()` as basis for `HorizontalBands` strategy
- `abstract.py` — `_downscale_image()`, `_enhance_image()` for per-cell processing
- `plan.py` — `PlanogramCompliance` orchestration (detection step refactored)
- `models.py:28` — `PlanogramConfig` extended with optional `detection_grid` field
- `types/abstract.py:21` — `AbstractPlanogramType` extended with `get_grid_strategy()` method

---

### Option C: Progressive Grid Refinement

Adaptive approach: start with a coarse grid (few large cells), then automatically subdivide cells where detection confidence is low.

**How it works:**
1. First pass: split ROI into 2-3 coarse bands, run parallel detection
2. Evaluate per-cell confidence: if average confidence < threshold OR expected products not found, flag cell for refinement
3. Second pass: subdivide flagged cells into finer grid, re-detect with more focused prompts
4. Merge all passes, preferring higher-confidence detections

**Pros:**
- Optimal cost/accuracy tradeoff — simple planograms get 2-3 calls, complex ones get more
- Self-adjusting — adapts to image complexity without manual tuning
- Handles edge cases: if a coarse band misses something, the refinement catches it

**Cons:**
- Variable latency — unpredictable for real-time mode
- Two-pass architecture adds complexity
- Confidence thresholds need tuning per planogram type
- Harder to test and debug — non-deterministic execution paths
- Approaches multi-run consensus in cost for complex images

**Effort:** High

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `google-genai` | Multi-pass Gemini calls | Already in use |
| `Pillow` | Dynamic cropping/subdivision | Already in use |

**Existing Code to Reuse:**
- Same as Option B, plus additional refinement/subdivision logic

---

## Recommendation

**Option B (Parallel Per-Cell Detection)** is recommended because:

1. **Directly attacks the root cause**: LLM attention dilution is solved by giving each cell a focused, small image with only relevant hints and references. This is the most impactful change for consistency.

2. **Predictable latency**: Unlike Option C, the number of API calls is deterministic (= number of grid cells), making it suitable for both real-time and batch modes.

3. **Clean architecture**: The `DetectionGrid` strategy pattern maps naturally to the different planogram types (bands for shelves, matrix for ink walls, zones for TV walls). Each type defines its own grid strategy.

4. **Backward compatible by default**: `detection_grid: None` preserves current single-cell behavior. Existing configs continue working unchanged.

5. **Better than Option A**: While a single mega-request has lower API overhead, the core problem (attention dilution) may persist when all cells share one LLM context. Option B ensures true isolation.

**Tradeoff accepted**: Higher total token cost from multiple API calls. Mitigated by smaller per-call context and parallel execution making wall-clock time comparable or better.

---

## Feature Description

### User-Facing Behavior

From the API consumer's perspective, nothing changes — same endpoints, same `PlanogramConfig` structure, same compliance results. The improvement is:
- **More consistent scores** between runs (reduced LLM variability)
- **Better detection of visually similar products** (focused reference images per cell)
- **New "out of place" items** reported in compliance results (unexpected objects detected per cell)
- **Optional**: New `detection_grid` field in config for fine-tuning grid strategy per planogram

### Internal Behavior

**Detection flow (refactored):**

```
[Stage 1] ROI Detection (unchanged)
    ↓
[NEW] Grid Strategy Resolution
    → PlanogramType.get_grid_strategy(roi, config) → List[GridCell]
    → Each GridCell has: bbox, expected_products, relevant_reference_images
    ↓
[Stage 2 - Refactored] Per-Cell Detection
    → For each GridCell:
        → Crop ROI to cell bbox
        → Downscale cell image
        → Build focused prompt with cell-specific hints
        → Attach only relevant reference images
    → asyncio.gather(*cell_detection_tasks)
    ↓
[NEW] Result Merge
    → Apply coordinate offsets per cell
    → Deduplicate boundary objects (IoU-based)
    → Tag unexpected objects as "out_of_place"
    ↓
[Stage 3] Compliance Check (unchanged — receives merged products)
    ↓
[Stage 4] Rendering (unchanged)
```

**Grid strategies:**

| Planogram Type     | Grid Strategy      | Cell Layout |
|--------------------|--------------------|-------------|
| product_on_shelves | HorizontalBands    | N horizontal strips by height_ratio |
| ink_wall           | MatrixGrid         | NxM rectangular cells |
| tv_wall            | ZoneGrid           | Named zones (configurable) |
| boxes_on_floor     | FlatGrid           | Simple 2x2 or 3x3 overlay |
| (any, no config)   | NoGrid             | Single cell = entire ROI |

**Reference image changes:**
- `reference_images` field supports both `str/Path` (single) and `List[str/Path]` (multiple per product)
- Per-cell detection selects only references for products expected in that cell
- If cell has no expected products (exploratory), all references are sent

### Edge Cases & Error Handling

- **Boundary objects**: Products that span two grid cells are detected in both. A deduplication step using IoU (Intersection over Union) merges overlapping detections, keeping the higher-confidence one.
- **Cell overlap margin**: Grid cells include a small overlap margin (configurable, default ~5% of cell height) to ensure boundary products appear in at least one cell fully.
- **Empty cells**: If a cell returns no detections, it's not an error — it means the shelf/zone is empty (reported as such in compliance).
- **API failures**: Per-cell calls are independently retryable. If one cell fails after retries, results from other cells are still used; the failed cell is reported as "detection_failed" in compliance.
- **NoGrid fallback**: If `detection_grid` is None or missing, the pipeline behaves exactly as it does today (single-cell, full ROI).
- **Reference image loading**: Multi-reference per product loads lazily; missing images log a warning but don't block detection.

---

## Capabilities

### New Capabilities
- `detection-grid-strategy`: Pluggable grid decomposition system for splitting ROI into detection cells
- `per-cell-detection`: Parallel per-cell LLM detection with focused prompts and reference images
- `multi-reference-images`: Support for multiple reference images per product
- `out-of-place-detection`: Informational reporting of unexpected objects detected in compliance results
- `boundary-deduplication`: IoU-based merge of detections spanning grid cell boundaries

### Modified Capabilities
- `product-detection` (product_on_shelves.py `detect_objects`): Refactored to use grid strategy instead of single-image detection
- `planogram-config` (models.py `PlanogramConfig`): Extended with optional `detection_grid` field
- `abstract-planogram-type` (abstract.py `AbstractPlanogramType`): Extended with `get_grid_strategy()` method

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot_pipelines/planogram/types/product_on_shelves.py` | modifies | `detect_objects()` refactored to use grid cells |
| `parrot_pipelines/planogram/types/abstract.py` | extends | Add `get_grid_strategy()` abstract method with default NoGrid |
| `parrot_pipelines/models.py` | extends | Add optional `detection_grid` field to `PlanogramConfig` |
| `parrot_pipelines/planogram/plan.py` | modifies | Detection stage orchestrates per-cell parallel calls |
| `parrot/clients/google/analysis.py` | no change | `detect_objects()` already supports multi-image via `contents[]` |
| `parrot/models/detections.py` | extends | Add `GridCell`, `DetectionGridConfig` models |
| `parrot/models/compliance.py` | extends | Add `out_of_place_items` field to `ComplianceResult` |
| DB: `troc.planograms_configurations` | extends | New optional JSON field for grid config (nullable) |

---

## Code Context

### Verified Codebase References

#### Classes & Signatures
```python
# From packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py:21
class AbstractPlanogramType(ABC):
    def __init__(self, pipeline: "PlanogramCompliance", config: "PlanogramConfig") -> None:
    async def compute_roi(self, img: Image.Image) -> Tuple[...]:  # line 48
    async def detect_objects_roi(self, img: Image.Image, roi: Any) -> List[Detection]:  # line 69
    async def detect_objects(self, img, roi, macro_objects) -> Tuple[List[IdentifiedProduct], List[ShelfRegion]]:  # abstract

# From packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py:102
class ProductOnShelves(AbstractPlanogramType):
    async def detect_objects(self, img, roi, macro_objects) -> Tuple[List[IdentifiedProduct], List[ShelfRegion]]:
        # line 102-222: single ROI crop → single LLM call with all hints + all refs

    def _generate_virtual_shelves(self, ...) -> List[ShelfRegion]:
        # line 956-1041: creates shelf regions from ROI + planogram config ratios

# From packages/ai-parrot-pipelines/src/parrot_pipelines/models.py:28
class PlanogramConfig(BaseModel):
    planogram_type: str  # line 43 — "product_on_shelves" | "graphic_panel_display"
    planogram_config: Dict[str, Any]  # line 49
    reference_images: Dict[str, Union[str, Path, Image.Image]]  # line 64
    endcap_geometry: EndcapGeometry  # line 80

# From packages/ai-parrot/src/parrot/clients/google/analysis.py:1094
class GoogleGenAIClient:
    async def detect_objects(
        self, image, prompt, reference_images=None, output_dir=None
    ) -> List[Dict[str, Any]]:
        # line 1094-1237: sends [prompt, image, *refs] to gemini-3-flash
        # Supports multiple images natively in contents[]
```

#### Verified Imports
```python
# These imports have been confirmed to work:
from parrot.models.detections import IdentifiedProduct, ShelfRegion, Detection  # parrot/models/detections.py
from parrot.models.compliance import ComplianceResult  # parrot/models/compliance.py
from parrot_pipelines.models import PlanogramConfig, EndcapGeometry  # models.py
from parrot_pipelines.planogram.types.abstract import AbstractPlanogramType  # types/abstract.py
```

### Does NOT Exist (Anti-Hallucination)
- ~~`DetectionGrid`~~ — does not exist yet; must be created
- ~~`GridCell`~~ — does not exist yet; must be created
- ~~`AbstractPlanogramType.get_grid_strategy()`~~ — does not exist; must be added
- ~~`PlanogramConfig.detection_grid`~~ — does not exist; must be added
- ~~`ComplianceResult.out_of_place_items`~~ — does not exist; must be added
- ~~`parrot_pipelines.planogram.types.ink_wall`~~ — module does not exist yet
- ~~`parrot_pipelines.planogram.types.tv_wall`~~ — module does not exist yet
- ~~`parrot_pipelines.planogram.types.boxes_on_floor`~~ — module does not exist yet

---

## Parallelism Assessment

- **Internal parallelism**: HIGH — Grid strategies, per-cell detection, and model changes are independent modules. The grid strategy implementations (HorizontalBands, MatrixGrid, etc.) can be developed in parallel. The merge/deduplication logic is independent of grid strategy.
- **Cross-feature independence**: This feature modifies the detection layer of `product_on_shelves.py` and extends `abstract.py`. No conflict with current in-flight features (FEAT-082 sqlagent-repair, FEAT-083 formdesigner-authentication).
- **Recommended isolation**: `per-spec` — tasks are sequential within the detection pipeline refactor; grid strategies share the same abstract base and should be developed after it.
- **Rationale**: While grid strategy implementations could theoretically be parallel, they all depend on the `DetectionGrid` base class and the refactored `detect_objects()` interface. Sequential development within one worktree ensures consistency.

---

## Open Questions

- [ ] What overlap margin (%) between grid cells minimizes boundary object duplication while ensuring coverage? — *Owner: Jesus Lara (empirical testing needed)*
- [ ] Should the `out_of_place` reporting be a separate field in `ComplianceResult` or a flag on each `IdentifiedProduct`? — *Owner: Jesus Lara*
- [ ] For Ink Walls and TV Walls: what are the exact grid dimensions (NxM) for typical configurations? Need example images/configs. — *Owner: Jesus Lara*
- [ ] Should reference images be stored in DB as paths or as base64? Current Dict[str, path] assumes filesystem access. — *Owner: Jesus Lara*
- [ ] What IoU threshold for boundary deduplication? Standard 0.5 or planogram-specific? — *Owner: Jesus Lara (empirical testing)*
