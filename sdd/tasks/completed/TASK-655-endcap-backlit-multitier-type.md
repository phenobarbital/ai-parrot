# TASK-655: EndcapBacklitMultitier type class implementation

**Feature**: FEAT-096 — Endcap Backlit Multitier Planogram Type
**Spec**: `sdd/specs/endcap-backlit-multitier.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-653, TASK-654
**Assigned-to**: unassigned

---

## Context

This is Module 3 of FEAT-096 and the core deliverable. It creates the new
`EndcapBacklitMultitier` planogram type class — an `AbstractPlanogramType` subclass
that implements per-section parallel LLM detection for backlit endcap displays.

Key behaviors:
- `compute_roi`: detects the endcap bounding box, promotional graphic, and brand logo
  via LLM (same pattern as `EndcapNoShelvesPromotional`).
- `detect_objects_roi`: processes the header shelf — illumination check, OCR, visual
  features.
- `detect_objects`: for each shelf, if `sections` is defined, runs one LLM call per
  section IN PARALLEL via `asyncio.gather()`. Flat shelves (no sections) get a single
  LLM call. Section-local bboxes are remapped to full-image coordinates.
- `check_planogram_compliance`: scores compliance per shelf by aggregating section
  detections. Applies illumination penalty if header is expected ON but detected OFF.

---

## Scope

- Create `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_backlit_multitier.py`
- Implement all four abstract methods: `compute_roi`, `detect_objects_roi`,
  `detect_objects`, `check_planogram_compliance`.
- Implement private helpers: `_detect_section()`, `_compute_section_bbox()`,
  `_remap_bbox_to_full_image()`, `_deduplicate_cross_section()`.
- Use `asyncio.gather()` for parallel section calls.
- Derive product category from `planogram_description.category` — no hardcoded strings.
- Handle edge cases: section LLM failure → treat as empty, 0 detections → all products missing.

**NOT in scope**: Registration in `_PLANOGRAM_TYPES` (TASK-656). Tests (TASK-658).
DB migration (TASK-657).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_backlit_multitier.py` | CREATE | Full type class implementation |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Standard library
import asyncio
from typing import Any, Dict, List, Optional, Tuple

# PIL
from PIL import Image

# Abstract base
from parrot_pipelines.planogram.types.abstract import AbstractPlanogramType
# verified: packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py

# Models
from parrot.models.detections import (
    Detection,
    IdentifiedProduct,
    ShelfRegion,
    DetectionBox,
    ShelfConfig,
    ShelfSection,          # added by TASK-653
    SectionRegion,         # added by TASK-653
    PlanogramDescription,
)
# verified: packages/ai-parrot/src/parrot/models/detections.py

from parrot.models.compliance import ComplianceResult, ComplianceStatus
# verified: packages/ai-parrot/src/parrot/models/compliance.py:32
```

### Existing Signatures to Use

```python
# abstract.py:42 — constructor (call via super().__init__)
def __init__(self, pipeline: "PlanogramCompliance", config: "PlanogramConfig") -> None:
    self.pipeline = pipeline   # access roi_client, _downscale_image, logger via this
    self.config = config
    self.logger = pipeline.logger

# abstract.py — MUST implement (all four):
@abstractmethod
async def compute_roi(self, img: Image.Image) -> Tuple[
    Optional[Tuple[int,int,int,int]], Optional[Any], Optional[Any], Optional[Any], List[Any]
]: ...

@abstractmethod
async def detect_objects_roi(self, img: Image.Image, roi: Any) -> List[Detection]: ...

@abstractmethod
async def detect_objects(
    self, img: Image.Image, roi: Any, macro_objects: Any
) -> Tuple[List[IdentifiedProduct], List[ShelfRegion]]: ...

@abstractmethod
def check_planogram_compliance(
    self, identified_products: List[IdentifiedProduct], planogram_description: Any
) -> List[ComplianceResult]: ...

# abstract.py:126 — inherited static helper
@staticmethod
def _extract_illumination_state(features: List[str]) -> Optional[str]:
    # returns "on" / "off" / None

# abstract.py (promoted by TASK-654) — inherited illumination check
async def _check_illumination(
    self, img: Image.Image, roi: Any, planogram_description: Any,
    illum_zone_bbox: Optional[Any] = None
) -> str:
    # returns "illumination_status: ON" or "illumination_status: OFF"

# abstract.py (promoted by TASK-654) — inherited model normalizer
@staticmethod
def _base_model_from_str(
    s: str, brand: str = None, patterns: Optional[List[str]] = None
) -> str:
    # strips brand prefix, normalizes model key

# Pipeline attributes (access via self.pipeline):
self.pipeline.roi_client          # GoogleGenAIClient — for all LLM vision calls
self.pipeline.logger              # Logger
self.pipeline._downscale_image(img, max_side=1024, quality=82)  # PIL Image → optimized
self.planogram_config             # PlanogramConfig — via self.config

# detections.py:305 — PlanogramDescription fields available in detect_objects:
planogram_description.brand       # str — brand name
planogram_description.category    # str — product category (REQUIRED field)
planogram_description.shelves     # List[ShelfConfig]
planogram_description.model_normalization_patterns  # Optional[List[str]]

# detections.py:255 — ShelfConfig fields:
shelf.level               # str — "header", "top", "middle", "bottom"
shelf.products            # List[ShelfProduct]
shelf.sections            # Optional[List[ShelfSection]] — added by TASK-653
shelf.section_padding     # Optional[float] — added by TASK-653
shelf.compliance_threshold  # float — default 0.8

# detections.py (added by TASK-653) — ShelfSection fields:
section.id                # str
section.region            # SectionRegion
section.products          # List[str] — product names

# detections.py (added by TASK-653) — SectionRegion fields:
region.x_start, region.x_end     # float (0.0–1.0 ratio of shelf width)
region.y_start, region.y_end     # float (0.0–1.0 ratio of shelf height)

# compliance.py:32 — ComplianceResult fields:
ComplianceResult(
    shelf_level=...,           # str
    expected_products=...,     # List[str]
    found_products=...,        # List[str]
    missing_products=...,      # List[str]
    unexpected_products=...,   # List[str]
    compliance_status=...,     # ComplianceStatus
    compliance_score=...,      # float
    text_compliance_results=[], # default
    text_compliance_score=1.0,  # default
)
```

### Does NOT Exist

- ~~`self.pipeline.llm_client`~~ — the attribute is `self.pipeline.roi_client`.
- ~~`planogram_description.category_noun()`~~ — not a method. Use `planogram_description.category`.
- ~~`ShelfConfig.tiers`~~ — does not exist. Use `ShelfConfig.sections`.
- ~~`ShelfSection.bbox`~~ — not a field. Bbox is computed from `section.region` ratios.
- ~~`ShelfProduct.section`~~ — not a field.
- ~~`AbstractPlanogramType._ocr_fact_tags()`~~ — does NOT exist on abstract; only on `ProductOnShelves`. Do NOT call it.
- ~~`AbstractPlanogramType._generate_virtual_shelves()`~~ — does NOT exist on abstract; only on `ProductOnShelves`. Do NOT call it.
- ~~`_assign_products_to_shelves()`~~ — not needed in the new type. Products are already
  assigned to shelves in `detect_objects()` by construction (each section crop knows its shelf).

---

## Implementation Notes

### Section bbox computation

Given shelf bbox `(sx1, sy1, sx2, sy2)` in PIXEL coordinates and a `SectionRegion`:

```python
def _compute_section_bbox(
    self,
    shelf_bbox: Tuple[int, int, int, int],
    region: "SectionRegion",
    padding: float,
    image_size: Tuple[int, int],
) -> Tuple[int, int, int, int]:
    sx1, sy1, sx2, sy2 = shelf_bbox
    sw, sh = sx2 - sx1, sy2 - sy1
    iw, ih = image_size
    x1 = max(0, int(sx1 + (region.x_start - padding) * sw))
    x2 = min(iw, int(sx1 + (region.x_end   + padding) * sw))
    y1 = max(0, int(sy1 + (region.y_start - padding) * sh))
    y2 = min(ih, int(sy1 + (region.y_end   + padding) * sh))
    return (x1, y1, x2, y2)
```

Shelf bbox comes from `ShelfRegion` objects generated in `detect_objects`; it is in
PIXEL coordinates (not ratios). `image_size = img.size` (PIL width, height).

### Default padding
If `shelf.section_padding` is `None`, use `0.05` as default.

### Parallel section detection
```python
async def _detect_section(self, img, section, shelf_bbox, padding, category, brand, patterns):
    crop_bbox = self._compute_section_bbox(shelf_bbox, section.region, padding, img.size)
    crop = img.crop(crop_bbox)
    crop_small = self.pipeline._downscale_image(crop, max_side=1024, quality=82)
    prompt = self._build_section_prompt(section.products, category, brand)
    try:
        detections = await self.pipeline.roi_client.some_vision_call(crop_small, prompt)
        # remap each detection bbox from crop-local to full-image coords
        return self._remap_detections(detections, crop_bbox)
    except Exception as e:
        self.logger.warning("Section %s LLM call failed: %s", section.id, e)
        return []

# In detect_objects:
section_tasks = [self._detect_section(..., section, ...) for section in shelf.sections]
results = await asyncio.gather(*section_tasks)
all_detections = [d for sublist in results for d in sublist]
```

### Bbox remapping (section-local → full-image)
Section LLM responses return bboxes relative to the CROP. Remap:
```python
# crop_bbox = (cx1, cy1, cx2, cy2) in full-image pixels
# section_local_bbox = (lx1, ly1, lx2, ly2) as ratios of crop
full_x1 = cx1 + lx1 * (cx2 - cx1)
full_y1 = cy1 + ly1 * (cy2 - cy1)
# normalize back to full-image ratios:
full_x1_ratio = full_x1 / image_width
```

### look at EndcapNoShelvesPromotional for compute_roi pattern
`compute_roi` in the new type should follow the same pattern as `EndcapNoShelvesPromotional.compute_roi`:
- Use YOLO or LLM to detect endcap bbox.
- Return `(endcap_det, ad_det, brand_det, panel_text_det, raw_dets)`.
- Read `endcap_no_shelves_promotional.py` lines 1-200 for the exact pattern.

### check_planogram_compliance scoring
For each shelf, compute:
```python
expected = [p.name for p in shelf.products]  # all products across all sections
found = [p.product_model for p in shelf_products]
score = len(set(found) & set(expected)) / max(len(expected), 1)
status = ComplianceStatus.COMPLIANT if score >= shelf.compliance_threshold else ComplianceStatus.NON_COMPLIANT
```

---

## Acceptance Criteria

- [ ] File `endcap_backlit_multitier.py` created and importable
- [ ] `from parrot_pipelines.planogram.types.endcap_backlit_multitier import EndcapBacklitMultitier` works
- [ ] `EndcapBacklitMultitier` is a concrete subclass of `AbstractPlanogramType` (no abstract methods remaining)
- [ ] `detect_objects` uses `asyncio.gather()` for parallel section calls
- [ ] Flat shelf (sections=None) falls back to single LLM call
- [ ] Section bbox remapping produces full-image coordinates
- [ ] `ruff check packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_backlit_multitier.py`
- [ ] No hardcoded category strings in prompts

---

## Test Specification

Full tests live in TASK-658. For a quick import smoke test:

```python
from parrot_pipelines.planogram.types.endcap_backlit_multitier import EndcapBacklitMultitier
from parrot_pipelines.planogram.types.abstract import AbstractPlanogramType

def test_is_concrete():
    """EndcapBacklitMultitier must be fully concrete (no abstract methods)."""
    import inspect
    abstract_methods = {
        name for name, m in inspect.getmembers(EndcapBacklitMultitier, predicate=inspect.isfunction)
        if getattr(m, "__isabstractmethod__", False)
    }
    assert abstract_methods == set(), f"Still abstract: {abstract_methods}"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/endcap-backlit-multitier.spec.md` — especially Section 2 (pipeline flow diagram) and Section 6 (Codebase Contract).
2. **Check dependencies** — TASK-653 and TASK-654 must be in `tasks/completed/`.
3. **Read reference files** before writing code:
   - `endcap_no_shelves_promotional.py` lines 1-250 for `compute_roi` pattern
   - `abstract.py` full file for inherited methods
   - `detections.py` lines 246-380 for model signatures (post TASK-653 changes)
4. **Update status** in `tasks/.index.json` → `"in-progress"`.
5. **Implement** following the scope above.
6. **Run** `source .venv/bin/activate && python -c "from parrot_pipelines.planogram.types.endcap_backlit_multitier import EndcapBacklitMultitier"` to verify import.
7. **Move this file** to `tasks/completed/TASK-655-endcap-backlit-multitier-type.md`.
8. **Update index** → `"done"`.
9. **Commit** with message: `sdd: TASK-655 implement EndcapBacklitMultitier type class`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: —
**Date**: —
**Notes**: —
**Deviations from spec**: none
