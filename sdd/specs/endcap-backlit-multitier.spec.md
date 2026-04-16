# Feature Specification: Endcap Backlit Multitier Planogram Type

**Feature ID**: FEAT-096
**Date**: 2026-04-13
**Author**: Juan2coder
**Status**: approved
**Target version**: TBD

---

## 1. Motivation & Business Requirements

### Problem Statement

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
   products with placeholder `[0,0,1,1]` bboxes — no visual verification, producing
   false positives.
4. **Hardcoded prompts**: Prompts reference "scanners" instead of deriving the product
   category from config, making the type non-reusable for other product types.

**Who is affected**: The planogram compliance pipeline used by retail brands (Epson,
and soon projectors and potentially others) that deploy backlit endcap displays with
multi-tier shelving in retail stores (Office Depot, Best Buy, etc.).

**Why now**: FEAT-091 (illumination check) is complete. The remaining structural
problems cannot be solved by further patching `product_on_shelves` — the type's
architecture assumes a flat-shelf model that fundamentally conflicts with
multi-tier/multi-section displays.

### Goals

- Eliminate cross-tier and cross-section hallucinations via per-section LLM crops.
- Make the planogram type config-driven: sections, products, and regions come from
  the DB config JSON, not hardcoded Python logic.
- Support generic usage for any product category (Epson scanners, projectors, future
  brands) without code changes.
- Run section LLM calls in parallel via `asyncio.gather()` for no latency overhead.
- Inherit or promote `_check_illumination()` for header backlit detection.
- Promote `_base_model_from_str` to `AbstractPlanogramType` as a static method so
  all types can normalize model names without duplicating code.

### Non-Goals (explicitly out of scope)

- Modifying or patching `product_on_shelves.py` — it remains untouched.
- AI-driven layout analysis (Option C from brainstorm) — we know the layout from config.
- Changing the output format (compliance score, overlay image, API response schema).
- Adding UI or dashboard changes.
- Fact-tag product injection — fact-tags are detected visually and reported, not used
  to inject products into the product list.

---

## 2. Architectural Design

### Overview

Create a new `AbstractPlanogramType` subclass `EndcapBacklitMultitier` that:
- Reads `sections` from `ShelfConfig` to decompose each shelf into sub-regions.
- Crops each section and sends an independent LLM call with a targeted prompt.
- Runs section LLM calls in parallel via `asyncio.gather()`.
- Processes the header as a separate entity (illumination check + visual features).
- Scores compliance per shelf (aggregating section detections).
- Registers under key `"endcap_backlit_multitier"` in `_PLANOGRAM_TYPES`.

Two shared helpers are promoted to `AbstractPlanogramType`:
- `_check_illumination()` — currently only in `EndcapNoShelvesPromotional`. Promoted
  so all endcap types inherit it cleanly.
- `_base_model_from_str()` — currently an instance method on `ProductOnShelves`.
  Promoted as a `@staticmethod` so `EndcapBacklitMultitier` can normalize model names
  without inheriting from `ProductOnShelves`.

### Component Diagram

```
PlanogramCompliance.run()
    │
    ├── type dispatch: _PLANOGRAM_TYPES["endcap_backlit_multitier"]
    │       → EndcapBacklitMultitier
    │
    ├── compute_roi()
    │       → YOLO / LLM detects endcap bbox, promotional graphic, brand logo
    │
    ├── detect_objects_roi()   [header processing]
    │       → _check_illumination()   [inherited from AbstractPlanogramType]
    │       → OCR + visual feature detection on header crop
    │
    ├── detect_objects()       [per-section product detection]
    │       For each shelf:
    │         If sections defined:
    │           asyncio.gather(*[_detect_section(s) for s in shelf.sections])
    │         Else:
    │           single LLM call on full shelf crop (flat mode)
    │       → List[IdentifiedProduct] + List[ShelfRegion]
    │
    └── check_planogram_compliance()
            → Per shelf: count found vs. expected, apply illumination penalty
            → List[ComplianceResult]
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractPlanogramType` (abstract.py) | extends + promotes | New subclass; promote `_check_illumination` and `_base_model_from_str` to base |
| `ShelfConfig` (detections.py) | extends | Add `sections: Optional[List[ShelfSection]]` and `section_padding: Optional[float]` |
| `PlanogramDescriptionFactory` (detections.py) | modifies | Parse new `sections` field when building `ShelfConfig` objects |
| `_PLANOGRAM_TYPES` dict (plan.py:33) | extends | Add `"endcap_backlit_multitier": EndcapBacklitMultitier` entry |
| `PlanogramCompliance.run()` (plan.py) | modifies | Guard calls to `_generate_virtual_shelves()` and `_ocr_fact_tags()` — not all types use them |
| `EndcapNoShelvesPromotional` (endcap_no_shelves_promotional.py) | none | Source reference for `_check_illumination` signature; method promoted to abstract |

### Data Models

```python
# New model: section region with product list
class ShelfSection(BaseModel):
    id: str                          # "left", "center", "right", or any label
    region: SectionRegion            # x/y ratio boundaries within the shelf
    products: List[str]              # product names expected in this section

class SectionRegion(BaseModel):
    x_start: float                   # 0.0 – 1.0 ratio of shelf width
    x_end: float
    y_start: float                   # 0.0 – 1.0 ratio of shelf height
    y_end: float

# ShelfConfig extension (existing model at detections.py:255)
class ShelfConfig(BaseModel):
    # ... all existing fields unchanged ...
    sections: Optional[List[ShelfSection]] = None    # NEW — multi-section shelves
    section_padding: Optional[float] = None          # NEW — overlap between sections
```

**DB config JSON example (planogram_id=15):**

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
    sections: null   # flat shelf, single LLM call
  - level: bottom
    sections: null
```

### New Public Interfaces

```python
# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_backlit_multitier.py
class EndcapBacklitMultitier(AbstractPlanogramType):
    """Planogram type for backlit endcap displays with multi-section shelving."""

    async def compute_roi(self, img: Image.Image) -> Tuple[...]:
        """Detect endcap bbox, promotional graphic, brand logo, poster text."""

    async def detect_objects_roi(self, img: Image.Image, roi: Any) -> List[Detection]:
        """Process header: illumination check + OCR + visual features."""

    async def detect_objects(
        self, img: Image.Image, roi: Any, macro_objects: Any
    ) -> Tuple[List[IdentifiedProduct], List[ShelfRegion]]:
        """Detect products per-section in parallel. Flat shelves use single call."""

    def check_planogram_compliance(
        self,
        identified_products: List[IdentifiedProduct],
        planogram_description: Any,
    ) -> List[ComplianceResult]:
        """Score compliance per shelf. Apply illumination penalty if needed."""
```

---

## 3. Module Breakdown

### Module 1: ShelfSection models + ShelfConfig extension
- **Path**: `packages/ai-parrot/src/parrot/models/detections.py`
- **Responsibility**: Add `SectionRegion`, `ShelfSection` Pydantic models; add
  `sections: Optional[List[ShelfSection]]` and `section_padding: Optional[float]`
  to `ShelfConfig`. Update `PlanogramDescriptionFactory` to parse the new fields.
- **Depends on**: Nothing new — extends existing models.

### Module 2: Promote helpers to AbstractPlanogramType
- **Path**: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py`
- **Responsibility**: 
  1. Promote `_check_illumination()` from `EndcapNoShelvesPromotional` to
     `AbstractPlanogramType` as a concrete (non-abstract) async method.
  2. Promote `_base_model_from_str()` from `ProductOnShelves` to
     `AbstractPlanogramType` as a `@staticmethod`.
- **Depends on**: Module 1 (no change, but must not break existing callers).

### Module 3: EndcapBacklitMultitier type class
- **Path**: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_backlit_multitier.py`
- **Responsibility**: Implement all four abstract methods. Core logic:
  - `compute_roi`: reuse `_find_poster`-style LLM call for ROI detection.
  - `detect_objects_roi`: crop header, call `_check_illumination()`, run OCR.
  - `detect_objects`: per-section parallel crops via `asyncio.gather()`.
  - `check_planogram_compliance`: per-shelf scoring.
- **Depends on**: Module 1 (ShelfSection models) + Module 2 (promoted helpers).

### Module 4: Pipeline integration (plan.py)
- **Path**: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py`
- **Responsibility**: 
  1. Add `"endcap_backlit_multitier": EndcapBacklitMultitier` to `_PLANOGRAM_TYPES`.
  2. Guard `_generate_virtual_shelves()` and `_ocr_fact_tags()` calls so they only
     run for types that define those methods (use `hasattr` check or type check).
- **Depends on**: Module 3.

### Module 5: DB config migration
- **Path**: DB table `troc.planograms_configurations` (data migration script)
- **Responsibility**: Update planogram_id=15 (Epson scanner endcap):
  - Set `planogram_type = "endcap_backlit_multitier"`.
  - Add `sections` arrays to the top shelf config JSON.
  - Verify projector planogram remains on its current type (no change needed).
- **Depends on**: Module 3 (type must exist before migration is usable).

### Module 6: Tests
- **Path**: `packages/ai-parrot-pipelines/tests/planogram/test_endcap_backlit_multitier.py`
- **Responsibility**: Unit tests for section crop math, deduplication, flat-shelf
  fallback, missing-section handling. Integration test for full pipeline run.
- **Depends on**: Module 3 + Module 4.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_section_region_crop_math` | Module 3 | Section bbox computed correctly from ratios + padding |
| `test_section_padding_overlap` | Module 3 | Adjacent sections overlap by `section_padding` amount |
| `test_flat_shelf_fallback` | Module 3 | Shelf with `sections=None` triggers single LLM call |
| `test_parallel_section_gather` | Module 3 | `asyncio.gather` called with N coroutines for N sections |
| `test_section_bbox_remapping` | Module 3 | Section-local bboxes remapped to full-image coordinates correctly |
| `test_deduplication_boundary_product` | Module 3 | Product detected in two overlapping sections deduplicated by confidence |
| `test_zero_section_detections` | Module 3 | Empty section result → all section products listed as missing |
| `test_section_llm_failure_graceful` | Module 3 | LLM exception for one section → warning logged, section treated as empty |
| `test_compliance_illumination_penalty` | Module 3 | Illumination OFF reduces compliance score as expected |
| `test_shelf_config_sections_field` | Module 1 | `ShelfConfig` accepts and validates `sections` + `section_padding` |
| `test_factory_parses_sections` | Module 1 | `PlanogramDescriptionFactory` correctly hydrates `ShelfSection` objects |
| `test_base_model_from_str_promoted` | Module 2 | `AbstractPlanogramType._base_model_from_str` callable as static method |
| `test_check_illumination_in_abstract` | Module 2 | `AbstractPlanogramType._check_illumination` accessible from new type |
| `test_planogram_types_registry` | Module 4 | `"endcap_backlit_multitier"` key present in `_PLANOGRAM_TYPES` |

### Integration Tests

| Test | Description |
|---|---|
| `test_full_pipeline_multisection` | Full `PlanogramCompliance.run()` with multi-section shelf config using mocked LLM responses |
| `test_full_pipeline_flat_fallback` | Full pipeline with `sections=None` shelves (flat mode) |
| `test_backward_compat_product_on_shelves` | `product_on_shelves` continues to work after plan.py guards added |

### Test Data / Fixtures

```python
@pytest.fixture
def multisection_shelf_config():
    return {
        "level": "top",
        "products": [],
        "sections": [
            {"id": "left", "region": {"x_start": 0.0, "x_end": 0.35, "y_start": 0.0, "y_end": 1.0}, "products": ["ES-60W", "ES-50"]},
            {"id": "center", "region": {"x_start": 0.35, "x_end": 0.65, "y_start": 0.0, "y_end": 1.0}, "products": ["ES-580W"]},
            {"id": "right", "region": {"x_start": 0.65, "x_end": 1.0, "y_start": 0.0, "y_end": 1.0}, "products": ["RR-600W"]},
        ],
        "section_padding": 0.05,
    }

@pytest.fixture
def flat_shelf_config():
    return {"level": "middle", "products": [{"name": "ES-50", "product_type": "scanner", ...}], "sections": None}
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] All unit tests pass (`pytest packages/ai-parrot-pipelines/tests/ -v`)
- [ ] All integration tests pass
- [ ] `product_on_shelves` behavior unchanged (backward compat test passes)
- [ ] `ShelfConfig` accepts `sections` and `section_padding` fields without breaking
      existing configs that omit them
- [ ] `EndcapBacklitMultitier` registered in `_PLANOGRAM_TYPES` under key
      `"endcap_backlit_multitier"`
- [ ] Per-section LLM calls run in parallel (verified via asyncio mock or timing)
- [ ] Flat-shelf fallback works when `sections` is `None`
- [ ] `_check_illumination()` and `_base_model_from_str()` accessible from
      `AbstractPlanogramType` (confirmed by test + grep)
- [ ] `EndcapNoShelvesPromotional` still works after `_check_illumination` promotion
      (backward compat)
- [ ] DB config migration script for planogram_id=15 documented (or applied)
- [ ] No hardcoded category strings in `EndcapBacklitMultitier` prompts — category
      derived from `PlanogramDescription.category` field

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.

### Verified Imports

```python
# plan.py top-of-file — import pattern for new type
from parrot_pipelines.planogram.types.endcap_backlit_multitier import EndcapBacklitMultitier
# verified pattern from plan.py:28-32

# abstract.py — base class
from parrot_pipelines.planogram.types.abstract import AbstractPlanogramType
# verified: packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py

# models used in new type
from parrot.models.detections import (
    ShelfConfig, ShelfProduct, PlanogramDescription,
    IdentifiedProduct, ShelfRegion, DetectionBox, Detection
)
# verified: packages/ai-parrot/src/parrot/models/detections.py

from parrot.models.compliance import ComplianceResult, ComplianceStatus
# verified: packages/ai-parrot/src/parrot/models/compliance.py:32
```

### Existing Class Signatures

```python
# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py

class AbstractPlanogramType(ABC):
    # line 42
    def __init__(self, pipeline: "PlanogramCompliance", config: "PlanogramConfig") -> None:
        self.pipeline = pipeline      # PlanogramCompliance instance
        self.config = config          # PlanogramConfig
        self.logger = pipeline.logger

    # line 52 — MUST implement
    @abstractmethod
    async def compute_roi(self, img: Image.Image) -> Tuple[
        Optional[Tuple[int, int, int, int]], Optional[Any], Optional[Any],
        Optional[Any], List[Any]
    ]: ...

    # line 73 — MUST implement
    @abstractmethod
    async def detect_objects_roi(self, img: Image.Image, roi: Any) -> List[Detection]: ...

    # line 92 — MUST implement
    @abstractmethod
    async def detect_objects(
        self, img: Image.Image, roi: Any, macro_objects: Any
    ) -> Tuple[List[IdentifiedProduct], List[ShelfRegion]]: ...

    # line 110 — MUST implement
    @abstractmethod
    def check_planogram_compliance(
        self, identified_products: List[IdentifiedProduct], planogram_description: Any
    ) -> List[ComplianceResult]: ...

    # line 126 — inherited static helper (already in abstract)
    @staticmethod
    def _extract_illumination_state(features: List[str]) -> Optional[str]: ...

    # line 145 — inherited, returns default render colors
    def get_render_colors(self) -> Dict[str, Tuple[int, int, int]]: ...

    # line 161 — inherited grid strategy (default: NoGrid)
    def get_grid_strategy(self) -> "AbstractGridStrategy": ...
```

```python
# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py

# line 33 — type registry (add new entry here)
_PLANOGRAM_TYPES = {
    "product_on_shelves": ProductOnShelves,
    "graphic_panel_display": GraphicPanelDisplay,
    "product_counter": ProductCounter,
    "endcap_no_shelves_promotional": EndcapNoShelvesPromotional,
}
```

```python
# packages/ai-parrot/src/parrot/models/detections.py

# line 246 — ShelfProduct (no changes)
class ShelfProduct(BaseModel):
    name: str
    product_type: str
    quantity_range: tuple[int, int]                              # default (1, 1)
    position_preference: Optional[Literal["left", "center", "right"]]  # default None
    mandatory: bool                                              # default True
    visual_features: Optional[List[str]]                         # default None

# line 255 — ShelfConfig (will be extended by Module 1)
class ShelfConfig(BaseModel):
    level: str
    products: List[ShelfProduct]
    compliance_threshold: float                                  # default 0.8
    allow_extra_products: bool                                   # default False
    position_strict: bool                                        # default False
    height_ratio: Optional[float]                                # default 0.30
    y_start_ratio: Optional[float]                               # default None
    is_background: bool                                          # default False
    product_weight: Optional[float]
    text_weight: Optional[float]
    visual_weight: Optional[float]
    # sections and section_padding DO NOT EXIST yet — added by Module 1

# line 305 — PlanogramDescription (category field already exists)
class PlanogramDescription(BaseModel):
    brand: str
    category: str          # line 311 — REQUIRED field, already exists
    shelves: List[ShelfConfig]
    advertisement_endcap: Optional[AdvertisementEndcap]         # default None
    model_normalization_patterns: Optional[List[str]]           # default None
    # ... (see detections.py:305 for full list)
```

```python
# packages/ai-parrot/src/parrot/models/compliance.py

# line 32 — ComplianceResult
class ComplianceResult(BaseModel):
    shelf_level: str
    expected_products: List[str]
    found_products: List[str]
    missing_products: List[str]
    unexpected_products: List[str]
    compliance_status: ComplianceStatus
    compliance_score: float
    text_compliance_results: List[TextComplianceResult]          # default []
    brand_compliance_result: Optional[BrandComplianceResult]    # default None
    text_compliance_score: float                                 # default 1.0
    overall_text_compliant: bool                                 # default True
```

```python
# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py

# line 872 — _base_model_from_str (instance method, NOT static — promote to abstract as @staticmethod)
def _base_model_from_str(
    self, s: str, brand: str = None, patterns: Optional[List[str]] = None
) -> str: ...

# line 684 — _find_poster (reference only — do not reuse directly; copy pattern)
async def _find_poster(self, image: Image.Image, planogram: Any, partial_prompt: str) -> Any: ...

# line 1076 — _generate_virtual_shelves (NOT used by new type)
def _generate_virtual_shelves(self, roi_bbox: DetectionBox, image_size: Tuple[int, int], planogram: Any) -> List[ShelfRegion]: ...
```

```python
# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_no_shelves_promotional.py

# line 454 — _check_illumination (source for promotion to abstract)
async def _check_illumination(
    self,
    img: Image.Image,
    roi: Any,
    planogram_description: Any,
    illum_zone_bbox: Optional[Any] = None,
) -> str: ...
# Returns: "illumination_status: ON" or "illumination_status: OFF"
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `EndcapBacklitMultitier` | `AbstractPlanogramType` | inheritance | `abstract.py:26` |
| `EndcapBacklitMultitier` | `_PLANOGRAM_TYPES` dict | dict entry | `plan.py:33` |
| `EndcapBacklitMultitier` | `ShelfConfig.sections` | field access | `detections.py:255` (added by Module 1) |
| `EndcapBacklitMultitier` | `AbstractPlanogramType._check_illumination()` | method call | `abstract.py` (promoted by Module 2) |
| `EndcapBacklitMultitier` | `AbstractPlanogramType._base_model_from_str()` | static call | `abstract.py` (promoted by Module 2) |
| `EndcapBacklitMultitier` | `self.pipeline.roi_client` | LLM calls | `plan.py` (PlanogramCompliance attr) |
| `EndcapBacklitMultitier` | `self.pipeline._downscale_image()` | image prep | `plan.py` |

### Does NOT Exist (Anti-Hallucination)

- ~~`ShelfConfig.sections`~~ — does not exist yet. Added by Module 1 of this spec.
- ~~`ShelfConfig.section_padding`~~ — does not exist yet. Added by Module 1.
- ~~`ShelfSection`~~ — does not exist yet. Created by Module 1.
- ~~`SectionRegion`~~ — does not exist yet. Created by Module 1.
- ~~`EndcapBacklitMultitier`~~ — does not exist yet. Created by Module 3.
- ~~`AbstractPlanogramType._check_illumination()`~~ — does NOT exist in abstract.py
  today. It is defined in `EndcapNoShelvesPromotional` (line 454). Module 2 promotes
  it to `AbstractPlanogramType`.
- ~~`AbstractPlanogramType._base_model_from_str()`~~ — does NOT exist in abstract.py
  today. It is an instance method on `ProductOnShelves` (line 872). Module 2 promotes
  it as a `@staticmethod` to `AbstractPlanogramType`.
- ~~`ShelfProduct.tier`~~ — does not exist.
- ~~`ShelfProduct.section`~~ — does not exist. Section-to-product association is via
  `ShelfSection.products`, not via a field on `ShelfProduct`.
- ~~`AbstractPlanogramType._category_noun()`~~ — does not exist. Use
  `PlanogramDescription.category` (already a required field at detections.py:311).
- ~~Formal plugin/registry system for types~~ — types are hardcoded imports + dict
  entry in `_PLANOGRAM_TYPES`.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Inherit from `AbstractPlanogramType` — never from `ProductOnShelves`.
- Use `asyncio.gather()` for parallel section LLM calls.
- All LLM calls via `self.pipeline.roi_client` — never instantiate clients directly.
- Use `self.pipeline._downscale_image(img, max_side=1024, quality=82)` before sending
  section crops to the LLM.
- Google-style docstrings + strict type hints on all methods.
- `self.logger` for all logging — never use `print()`.
- Pydantic `BaseModel` for `ShelfSection` and `SectionRegion`.
- Flat-shelf fallback (sections=None) must silently work — no special-casing at the
  call site in `PlanogramCompliance.run()`.

### Pipeline Behavior: section bbox computation

Given a shelf bbox `(sx1, sy1, sx2, sy2)` in full-image pixels and a section region
`{x_start, x_end, y_start, y_end}` as ratios within that shelf:

```python
sw = sx2 - sx1   # shelf width in pixels
sh = sy2 - sy1   # shelf height in pixels
padding = shelf.section_padding or config.section_padding_default  # e.g. 0.05

x1 = sx1 + (section.region.x_start - padding) * sw
x2 = sx1 + (section.region.x_end   + padding) * sw
y1 = sy1 + (section.region.y_start - padding) * sh
y2 = sy1 + (section.region.y_end   + padding) * sh
# Clamp to image bounds
```

### Known Risks / Gotchas

- **`_check_illumination` promotion**: `EndcapNoShelvesPromotional` currently defines
  its own copy. After promotion to abstract, the concrete class should call `super()`
  or delegate. Do not delete the local copy until tests confirm both paths work.
- **`_base_model_from_str` promotion**: the instance method in `ProductOnShelves`
  uses `self` only for accessing `self.config`. As a `@staticmethod`, it must receive
  `patterns` explicitly. Existing callers in `ProductOnShelves` must be updated to
  call `AbstractPlanogramType._base_model_from_str(s, brand, patterns)`.
- **`PlanogramDescription.category`**: already a required field (detections.py:311).
  No migration needed — existing configs must already supply it.
- **`plan.py` guards**: `_generate_virtual_shelves()` and `_ocr_fact_tags()` are
  called unconditionally in `PlanogramCompliance.run()`. Use `hasattr(type_instance, '_generate_virtual_shelves')` or check the planogram type before calling.
- **DB migration**: planogram_id=15 must have its config updated before the new type
  can be exercised end-to-end. The migration is data-only; no schema change required.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `asyncio` | stdlib | Parallel section LLM calls |
| `PIL/Pillow` | already in deps | Image cropping per section |
| `google-genai` | already in deps | Gemini Flash for section detection via `GoogleGenAIClient` |

---

## 8. Open Questions

> All questions from the brainstorm are resolved. No open questions.

---

## Worktree Strategy

- **Isolation unit**: `per-spec` (sequential tasks in one worktree).
- **Rationale**: All 6 modules touch overlapping files (`detections.py`, `abstract.py`,
  `plan.py`). Sequential execution in one worktree avoids merge conflicts.
- **Tasks run in order**: Module 1 → Module 2 → Module 3 → Module 4 → Module 5 → Module 6.
- **Cross-feature dependencies**: None. `product_on_shelves.py` is untouched.
- **Worktree creation**:
  ```bash
  git worktree add -b feat-096-endcap-backlit-multitier \
    .claude/worktrees/feat-096-endcap-backlit-multitier HEAD
  ```

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-04-13 | Juan2coder | Initial spec from brainstorm (FEAT-096) |
