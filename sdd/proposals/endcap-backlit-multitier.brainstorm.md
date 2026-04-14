# Brainstorm: Endcap Backlit Multitier Planogram Type

**Date**: 2026-04-13
**Author**: Juan2coder + Claude
**Status**: exploration
**Recommended Option**: Option A

---

## Problem Statement

The existing `product_on_shelves` planogram type was designed for flat shelves with
products arranged horizontally. When applied to **backlit endcaps with multi-tier
structures** (e.g., Epson scanner display at Office Depot, planogram_id=15), it
requires escalating heuristic patches to handle:

1. **Cross-tier hallucinations**: Step-2 LLM draws bboxes for non-existent products
   over the header backlit graphic (e.g., ES-580W bbox drawn over Shaquille O'Neal
   poster — 96% of bbox inside the header area).
2. **Tier band collapse**: When only one detection represents a physical tier, the
   geometric band shrinks to that detection's bbox, causing false vetoes of
   legitimate neighbouring products.
3. **Blind fact-tag injection**: OCR reads model names from fact-tags and injects
   products with placeholder `[0,0,1,1]` bboxes — no visual verification, produces
   false positives.
4. **Hardcoded prompts**: Prompts reference "scanners" instead of deriving the
   product category from config, making the type non-reusable for other product
   types.

**Who is affected**: The planogram compliance pipeline used by retail brands
(Epson, and soon projectors and potentially others) that deploy backlit endcap
displays with multi-tier shelving in retail stores (Office Depot, Best Buy, etc.).

**Why now**: FEAT-091 (illumination check) is complete and works generically.
The remaining structural problems cannot be solved by further patching
`product_on_shelves` — the type's architecture assumes a flat-shelf model that
fundamentally conflicts with multi-tier/multi-section displays.

## Constraints & Requirements

- **Config-driven**: All display structure (sections, products, regions) must come
  from the DB config JSON, not from hardcoded logic in Python.
- **Generic**: Must work for Epson scanners, Epson projectors, and future brands
  without code changes — only config changes.
- **Backward compatible**: Must not break existing `product_on_shelves` behaviour.
  The new type runs alongside existing types, selected via `planogram_type` field.
- **Async-first**: All LLM calls must be `async` and parallelizable via
  `asyncio.gather()`.
- **Cost-aware**: LLM call count should be proportional to display complexity, not
  explode combinatorially.
- **No fact-tag injection**: Products are detected by visual LLM only. Fact-tags
  are detected and reported but do NOT inject or validate products.
- **Illumination reuse**: Must inherit `_check_illumination()` from
  `AbstractPlanogramType` (promoted in FEAT-091).

### Design Decisions from Discovery (Rounds 1 & 2)

| Decision | Resolution |
|----------|-----------|
| Section schema | Generic N-section per shelf with `region` (x+y ratios). Not hardcoded to "upper/lower" or 2 tiers. |
| Section orientation | **Vertical columns** (left/center/right) for Epson top shelf — not horizontal rows. Config-driven, so other orientations possible. |
| Detection strategy | **1 LLM call per section** (Strategy A). Crops per section sent in parallel. Flat shelves = 1 call. |
| Header exclusion | No clean Y-boundary between header and products (they overlap physically). Header has its own illumination crop (top franja). Product sections include header as background — prompt specificity prevents hallucinations. |
| Fact-tag corroboration | **Eliminated**. Fact-tags detected visually and reported; no product injection. |
| Empty slots | Reported as "missing" in compliance. No explicit `empty_slot` detection. |
| Compliance scoring | **Per shelf** (not per section). Sections are an internal detection detail. |
| Section padding | **Automatic 5%** overlap between adjacent sections, configurable. |
| Fact-tag visual detection | **Yes** — detected and rendered in overlay as informational data. |
| Multi-planogram | Must support Epson scanners, projectors, and future configs. Category-agnostic prompts. |

---

## Options Explored

### Option A: Dedicated Composable Type with Per-Section Detection

Create a new `AbstractPlanogramType` subclass `EndcapBacklitMultitier` that:
- Reads `sections` from shelf config to decompose each shelf into sub-regions.
- Crops each section and sends an independent LLM call with a targeted prompt
  (2-4 products max per call).
- Runs section LLM calls in parallel via `asyncio.gather()`.
- Processes the header as a separate entity (illumination + OCR + visual features).
- Scores compliance per shelf (aggregating section detections).

The pipeline orchestration (`plan.py`) calls the standard abstract methods:
`compute_roi()` → `detect_objects_roi()` → `detect_objects()` →
`check_planogram_compliance()`. All section logic lives inside the type's
`detect_objects()` implementation.

**Config schema extension** — add `sections` to `ShelfConfig`:

```yaml
shelves:
  - level: top
    sections:
      - id: left
        region: {x_start: 0.0, x_end: 0.35, y_start: 0.0, y_end: 1.0}
        products: [ES-60W, ES-C320W, ES-50]
      - id: center
        region: {x_start: 0.35, x_end: 0.65, y_start: 0.0, y_end: 1.0}
        products: [ES-580W, FF-680W]
      - id: right
        region: {x_start: 0.65, x_end: 1.0, y_start: 0.0, y_end: 1.0}
        products: [RR-70W, RR-600W]
    section_padding: 0.05
  - level: middle
    sections: null   # flat shelf, single detection call
  - level: bottom
    sections: null
```

**Pros:**
- Cross-tier/cross-section hallucinations eliminated by design (LLM only sees 2-4
  products per crop).
- Prompts are trivial (short, specific product list per section).
- Parallel section calls = same latency as a single call.
- Clean separation from `product_on_shelves` — no patches, no regressions.
- Config-driven: adding a new planogram = new JSON row in DB.
- Inherits `_check_illumination()`, `_extract_illumination_state()`,
  `get_render_colors()` from abstract.

**Cons:**
- New type class to maintain alongside existing types.
- Requires `ShelfConfig` model extension (adding `sections` field).
- `plan.py` may need minor adjustments if it assumes all types have
  `_generate_virtual_shelves()` or `_ocr_fact_tags()`.

**Effort:** Medium

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `asyncio` | Parallel section LLM calls | stdlib, already used |
| `PIL/Pillow` | Image cropping per section | already a dependency |
| `google-genai` | Gemini Flash for section detection | already used via `GoogleGenAIClient` |

**Existing Code to Reuse:**
- `abstract.py` — `AbstractPlanogramType` base class, `_check_illumination()`,
  `_extract_illumination_state()`, `get_render_colors()`, `get_grid_strategy()`
- `plan.py` — `PlanogramCompliance` pipeline orchestration (type dispatch, rendering)
- `detections.py` — `IdentifiedProduct`, `ShelfRegion`, `DetectionBox`, `Detection`,
  `ComplianceResult` models
- `product_on_shelves.py` — `_base_model_from_str()`, `_find_poster()`,
  `_generate_virtual_shelves()`, `_assign_products_to_shelves()` (adapt, not copy)
- `models.py` — `PlanogramConfig`, `EndcapGeometry`

---

### Option B: Extend Grid Strategy for Section-Based Detection

Instead of a new type, extend the existing `AbstractGridStrategy` system to support
section-based decomposition. Create a `SectionGrid` strategy that decomposes shelves
into sections (like `HorizontalBands` decomposes into rows).

`ProductOnShelves` already supports grid-based detection via `_detect_with_grid()`.
The new strategy would:
- Read `sections` from shelf config.
- Generate `GridCell` objects for each section with appropriate bbox and expected
  products.
- Use the existing `GridDetector` to run parallel LLM calls per cell.

**Pros:**
- Reuses existing grid infrastructure (GridDetector, GridCell, parallel detection).
- No new type class — stays within `product_on_shelves`.
- Smaller code change.

**Cons:**
- `product_on_shelves` still handles header/illumination/compliance in a way that
  assumes flat shelves — patching continues.
- Grid system is designed for spatial decomposition of a single image, not for
  semantic decomposition by product groups. The abstraction mismatch remains.
- Still inherits all the complexity of `product_on_shelves` (1739 lines) including
  fact-tag corroboration, tier inference, etc.
- Header exclusion still a problem — GridDetector sends cells from the full ROI.
- Doesn't solve the fundamental architectural mismatch.

**Effort:** Medium (similar to Option A but with more tech debt)

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| Same as Option A | — | — |

**Existing Code to Reuse:**
- `grid/strategy.py` — `AbstractGridStrategy`, `GridCell`
- `grid/detector.py` — `GridDetector.detect_cells()`
- `product_on_shelves.py` — full type (extended, not replaced)

---

### Option C: AI-Driven Layout Analysis (No Config Sections)

Instead of declaring sections in config, use a two-phase LLM pipeline:
1. **Phase 1 (Layout)**: Send full shelf image to LLM and ask it to identify
   the physical structure — "how many tiers/columns? where are the boundaries?"
2. **Phase 2 (Products)**: Based on LLM-identified structure, crop and detect
   products per zone.

**Pros:**
- Zero config needed for section regions — the AI figures out the layout.
- Works for any display structure without pre-declaring geometry.
- Adapts to physical variations (stores that don't follow the planogram exactly).

**Cons:**
- Adds an extra LLM call per shelf (layout detection).
- Layout detection is unreliable — LLM may misidentify structure, especially
  with perspective distortion.
- We already know the layout from the planogram config — asking the LLM to
  rediscover it wastes money and introduces error.
- Debugging is harder — "why did it detect 2 columns instead of 3?"
- Phase 1 errors cascade into Phase 2 (wrong crop = wrong detection).

**Effort:** High

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| Same as Option A | — | — |
| Additional Gemini calls | Layout analysis phase | Extra cost |

**Existing Code to Reuse:**
- Same as Option A, plus additional prompting logic.

---

## Recommendation

**Option A** is recommended because:

1. **Clean architectural separation**: A dedicated type class inherits the abstract
   contract and implements section-based detection without touching
   `product_on_shelves`. Zero regression risk.

2. **Config-driven by design**: Sections are declared in the planogram JSON, not
   inferred by heuristics or AI. The system knows the layout upfront and uses it
   to create optimal crops. Debugging is deterministic — "section X has these
   products, the crop is this region."

3. **Option B reuses the wrong abstraction**: The grid system was designed for
   spatial tiling (overlapping cells for large images), not for semantic product
   groups. Forcing sections into grid cells creates an abstraction mismatch that
   will generate more patches.

4. **Option C solves a problem we don't have**: We already know the display
   structure from the planogram config. Asking the LLM to rediscover it wastes
   money, adds latency, and introduces unreliability.

5. **Cost**: Option A's per-section LLM calls cost roughly the same as a single
   full-shelf call (each section crop has ~1/N of the pixels, so 3 calls × 1/3
   tokens ≈ 1 call × full tokens). Latency is equivalent when calls run in
   parallel.

**Tradeoff accepted**: We add a new type class to maintain. This is the right kind
of complexity — explicit, isolated, and config-driven — vs. the wrong kind (patches
and heuristics inside a mismatched type).

---

## Feature Description

### User-Facing Behavior

From the **retail brand's perspective** (Epson, projector vendors, etc.):
- Configure a planogram in the DB with `planogram_type = "endcap_backlit_multitier"`.
- Define shelves with optional `sections` (column-based or any rectangular region).
- Run the compliance pipeline as before. Get the same output format: compliance
  score per shelf, product detections with bboxes, rendered overlay image.
- No change to dashboards, reports, or API response schema.

From the **developer's perspective**:
- New planogram type registered in `_PLANOGRAM_TYPES` dict.
- Add `sections` optional field to `ShelfConfig` model.
- New type class with ~400-600 lines (vs. 1739 in `product_on_shelves`).

### Internal Behavior

**Pipeline flow** (within `PlanogramCompliance.run()`):

```
Step 1 — ROI Detection (same as existing):
  • YOLO or LLM detects the endcap bounding box in the full store image.
  • Returns endcap_bbox, promotional_graphic detection, brand_logo, poster_text.

Step 2 — Header Processing:
  • Crop the clean top franja of the header (above all products).
  • Run _check_illumination() → ON/OFF.
  • Run OCR on header crop → verify text requirements ("Scan & Done", etc.).
  • Verify visual features ("large backlit lightbox", "image of Shaquille O'Neal").
  • Verify brand logo presence.

Step 3 — Product Detection (per-section):
  For each shelf in config:
    If shelf has sections:
      For each section (IN PARALLEL via asyncio.gather):
        • Compute section crop bbox from shelf bbox + section region ratios
          + padding (default 5%).
        • Crop the image to section region.
        • Build prompt: "In this crop, identify these products: [list].
          For each product found, return label + bbox. If a product slot
          is empty, do not report it."
        • Send to Gemini Flash → get detections.
        • Map section-local bboxes back to full-image coords.
    If shelf is flat (no sections):
      • Single LLM call on full shelf crop (same as existing legacy path).
  
  Merge all detections across sections into a flat list.

Step 4 — Shelf Assignment:
  • Assign each detection to its shelf based on Y-center position.
  • Fact-tags detected by Step 2 are assigned to shelves but NOT used for
    product injection.

Step 5 — Compliance Scoring:
  For each shelf:
    • Count found products vs. expected products (from all sections combined).
    • Score = found / expected.
    • Apply illumination penalty if header backlit is expected ON but detected OFF.
    • Apply text compliance scoring for header shelf.
  Overall score = average of shelf scores.

Step 6 — Rendering:
  • Draw bboxes for all detections (products, fact-tags, promotional graphic).
  • Color-code by compliance status (compliant=green, non-compliant=red).
  • Save overlay image.
```

### Edge Cases & Error Handling

| Edge Case | Handling |
|-----------|---------|
| Section crop returns 0 detections | All products in that section reported as "missing". Score reflects it. |
| LLM call for a section fails (network, timeout) | Log warning, treat section as 0 detections. Do not crash pipeline. |
| Product sits on boundary between two sections | Padding (5% default, configurable) ensures overlap. If detected in both sections, deduplicate by highest confidence. |
| Shelf has no sections defined | Falls back to single LLM call on full shelf crop (flat mode). |
| Config has 0 shelves | Return empty compliance results with 0 score. |
| Image too dark / blurry | LLM returns low-confidence or no detections. Score reflects reality. |
| Header illumination check fails | Return None, skip illumination penalty (don't default to OFF). Already implemented in `_check_illumination()`. |
| Planogram config missing `sections` field | Treat as flat shelf (backward compatible). |

---

## Capabilities

### New Capabilities
- `endcap-backlit-multitier-type`: New planogram type composable for backlit endcap
  displays with multi-section shelving.
- `section-based-detection`: Per-section LLM detection with parallel execution.
- `shelf-section-config`: Schema extension for declaring sections on shelves.

### Modified Capabilities
- `planogram-config-models`: Add optional `sections` field to `ShelfConfig`.
- `planogram-type-registry`: Add `"endcap_backlit_multitier"` entry to
  `_PLANOGRAM_TYPES` dict.
- `planogram-compliance-pipeline`: Minor adjustments to `plan.py` orchestration
  to handle types that don't use `_generate_virtual_shelves()` or
  `_ocr_fact_tags()`.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `ShelfConfig` model (detections.py) | extends | Add optional `sections: Optional[List[ShelfSection]]` field |
| `PlanogramDescriptionFactory` (detections.py) | modifies | Parse `sections` from shelf config dict |
| `_PLANOGRAM_TYPES` dict (plan.py) | extends | Add new type entry |
| `PlanogramCompliance.run()` (plan.py) | modifies | Guard `_generate_virtual_shelves()` and `_ocr_fact_tags()` calls for types that don't use them |
| `product_on_shelves.py` | none | No changes. Continues working for flat-shelf planograms. |
| `abstract.py` | none | Already has `_check_illumination()` from FEAT-091. No changes needed. |
| DB table `troc.planograms_configurations` | data | Migrate planogram_id=15 config: change `planogram_type` and add `sections` to shelf configs |
| Compliance dashboard | none | Output schema unchanged (score per shelf, product list, overlay image) |

---

## Code Context

### Verified Codebase References

#### Type Registry (plan.py:33-38)
```python
# From packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py:33
_PLANOGRAM_TYPES = {
    "product_on_shelves": ProductOnShelves,
    "graphic_panel_display": GraphicPanelDisplay,
    "product_counter": ProductCounter,
    "endcap_no_shelves_promotional": EndcapNoShelvesPromotional,
}
```

#### AbstractPlanogramType (abstract.py:26-174)
```python
# From packages/ai-parrot-pipelines/.../types/abstract.py:44
def __init__(self, pipeline: "PlanogramCompliance", config: "PlanogramConfig") -> None:
    self.pipeline = pipeline      # Parent PlanogramCompliance
    self.config = config          # PlanogramConfig
    self.logger = pipeline.logger

# abstract.py:53 — MUST implement
async def compute_roi(self, img: Image.Image) -> Tuple[
    Optional[Tuple[int, int, int, int]], Optional[Any], Optional[Any],
    Optional[Any], List[Any]
]:

# abstract.py:74 — MUST implement
async def detect_objects_roi(self, img: Image.Image, roi: Any) -> List[Detection]:

# abstract.py:93 — MUST implement
async def detect_objects(self, img: Image.Image, roi: Any, macro_objects: Any
) -> Tuple[List[IdentifiedProduct], List[ShelfRegion]]:

# abstract.py:111 — MUST implement
def check_planogram_compliance(self, identified_products: List[IdentifiedProduct],
    planogram_description: Any) -> List[ComplianceResult]:

# abstract.py:147 — inherited, works for illumination
async def _check_illumination(self, img, zone_bbox=None, roi=None,
    planogram_description=None) -> Optional[str]:

# abstract.py:127 — inherited static helper
@staticmethod
def _extract_illumination_state(features: List[str]) -> Optional[str]:
```

#### ShelfConfig & ShelfProduct (detections.py:246-267)
```python
# From packages/ai-parrot/src/parrot/models/detections.py:246
class ShelfProduct(BaseModel):
    name: str
    product_type: str
    quantity_range: tuple[int, int]      # default (1, 1)
    position_preference: Optional[Literal["left", "center", "right"]]
    mandatory: bool                      # default True
    visual_features: Optional[List[str]]

# detections.py:255
class ShelfConfig(BaseModel):
    level: str                           # "header", "top", "middle", "bottom"
    products: List[ShelfProduct]
    compliance_threshold: float          # default 0.8
    allow_extra_products: bool           # default False
    position_strict: bool                # default False
    height_ratio: Optional[float]        # 0.30 = 30% of ROI
    y_start_ratio: Optional[float]       # explicit Y position
    is_background: bool                  # default False
    product_weight: Optional[float]
    text_weight: Optional[float]
    visual_weight: Optional[float]
```

#### PlanogramDescription (detections.py:305-349)
```python
# From detections.py:305
class PlanogramDescription(BaseModel):
    brand: str
    category: str
    shelves: List[ShelfConfig]
    model_normalization_patterns: Optional[List[str]]
    advertisement_endcap: Optional[AdvertisementEndcap]
    # ... (see full model in detections.py)
```

#### PlanogramConfig (models.py:29-108)
```python
# From packages/ai-parrot-pipelines/src/parrot_pipelines/models.py:29
class PlanogramConfig(BaseModel):
    planogram_id: Optional[int]
    config_name: str
    planogram_type: str                 # "product_on_shelves", etc.
    planogram_config: Dict[str, Any]    # → PlanogramDescription via factory
    roi_detection_prompt: str
    object_identification_prompt: str
    reference_images: Dict[str, Union[str, Path, List[str], Image.Image]]
    confidence_threshold: float         # default 0.25
    detection_model: str                # default "yolo11l.pt"
    endcap_geometry: EndcapGeometry
    detection_grid: Optional[DetectionGridConfig]
```

#### ComplianceResult (compliance.py:32-52)
```python
# From packages/ai-parrot/src/parrot/models/compliance.py:32
class ComplianceResult(BaseModel):
    shelf_level: str
    expected_products: List[str]
    found_products: List[str]
    missing_products: List[str]
    unexpected_products: List[str]
    compliance_status: ComplianceStatus  # COMPLIANT | NON_COMPLIANT | MISSING
    compliance_score: float
    text_compliance_results: List[TextComplianceResult]
    text_compliance_score: float
```

#### GoogleModel (google.py:9-37)
```python
# From packages/ai-parrot/src/parrot/models/google.py
class GoogleModel(Enum):
    GEMINI_3_FLASH_PREVIEW = "gemini-3-flash-preview"
    GEMINI_2_5_FLASH = "gemini-2.5-flash"
    # ... (used for section detection calls)
```

#### Pipeline Attributes (via self.pipeline)
```python
# Available on self.pipeline (PlanogramCompliance instance):
self.pipeline.roi_client       # GoogleGenAIClient — for vision LLM calls
self.pipeline.logger           # Logger instance
self.pipeline._downscale_image(img, max_side=1024, quality=82)  # Image optimization
```

#### Reusable Helpers from ProductOnShelves
```python
# product_on_shelves.py:872 — model name normalization
@staticmethod
def _base_model_from_str(s: str, brand: str = None, patterns: Optional[List[str]] = None) -> str:

# product_on_shelves.py:684 — ROI detection via LLM
async def _find_poster(image, planogram, partial_prompt) -> Any:

# product_on_shelves.py:1076 — virtual shelf generation from config ratios
def _generate_virtual_shelves(roi_bbox, image_size, planogram) -> List[ShelfRegion]:
```

### Does NOT Exist (Anti-Hallucination)
- ~~`ShelfConfig.sections`~~ — does not exist on dev. Must be added by FEAT-092.
- ~~`ShelfConfig.tiers`~~ — does not exist on dev (was only in FEAT-091 scope creep,
  discarded).
- ~~`ShelfProduct.tier`~~ — does not exist on dev (discarded with FEAT-091 reset).
- ~~`ShelfProduct.section`~~ — does not exist. Products are associated to sections
  via the section config, not via a field on ShelfProduct.
- ~~`PlanogramDescription.category`~~ — **does not exist on dev** (was only in
  FEAT-091 uncommitted changes). Must be added or derived from config if needed.
- ~~`AbstractPlanogramType._category_noun()`~~ — does not exist (was only in
  FEAT-091 uncommitted changes). Reimplement in FEAT-092 if needed.
- ~~`EndcapBacklitMultitier`~~ — does not exist yet. This is what FEAT-092 creates.
- ~~Formal plugin/registry system for types~~ — types are hardcoded imports + dict
  entry in `_PLANOGRAM_TYPES`.
- ~~Per-type configuration schema validation~~ — `planogram_config` is a generic
  `Dict[str, Any]` parsed by `PlanogramDescriptionFactory`.

---

## Parallelism Assessment

- **Internal parallelism**: Tasks can be split into independent units:
  - Model extensions (ShelfConfig.sections) — independent of type class.
  - Type class implementation — core logic, depends on model extension.
  - Pipeline integration (plan.py guards) — small, depends on type class.
  - Config migration (planogram_id=15 JSON) — independent of code.
  - Tests — depend on type class.

- **Cross-feature independence**: No conflicts with in-flight specs. The only
  shared file is `plan.py` (type registry dict) which is a single-line addition.

- **Recommended isolation**: `per-spec` (sequential tasks in one worktree).
  The feature is cohesive — model extension feeds into type class feeds into
  pipeline integration. Parallelizing would create merge conflicts on
  `detections.py` and `plan.py`.

- **Rationale**: 5-6 tasks, all touching overlapping files. Sequential execution
  in one worktree is simpler and avoids conflict resolution overhead.

---

## Open Questions

- [ ] **Exact product-to-section mapping for Epson projectors**: The projectors
  planogram config needs to be examined to validate the section schema works for
  a second planogram. — *Owner: juanfran*
- [ ] **Section padding default**: 5% was agreed as default. Should it be stored
  in `EndcapGeometry` or per-shelf in `ShelfConfig`? — *Owner: juanfran*
- [ ] **`_base_model_from_str` extraction**: This helper is defined on
  `ProductOnShelves` as a static method. Should it be promoted to a shared mixin
  or utility module so `EndcapBacklitMultitier` can reuse it without import
  coupling? — *Owner: Claude*
- [ ] **`category` field on PlanogramDescription**: Does not exist on dev. Needed
  for category-agnostic prompts. Add it in FEAT-092 or as a prerequisite? —
  *Owner: juanfran*
