# TASK-3866: Migrate EndcapBacklitMultitier to the shared cycle

**Feature**: FEAT-612 — Refactor Planogram Compliance
**Spec**: `sdd/specs/refactor-planogram-compliance.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3856, TASK-3859, TASK-3863
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 7** and §2 "Type defaults" (endcap_backlit_multitier row). Today
`endcap_backlit_multitier.py` (1,796 lines) is a pure legacy type: `compute_roi` → per-section
LLM crop detection (`_detect_section`, `_detect_combined_flat_shelves`, fact-tag prescan) →
`check_planogram_compliance` that scores shelves by name intersection and a 50 % campaign-text /
50 % light-ON header formula. It runs through `legacy_adapter.legacy_perceive` and reports
`legacy_unmeasured`. This task replaces it with the three cycle hooks composed from the shared
stages (TASK-3856 `perceive_image`/`rebuild_geometry`, TASK-3859 `identify_image`, TASK-3863
`compare_observations`) and a fresh `default_layout_profile()`: shared body/box/tag/zone
profiles, `shape_is_slot`, **strips**, threshold 3. Type-specific behavior retained, per spec:
fact tags never count as products (the existing `_is_fact_tag_misdetection` geometry heuristic is
kept for that), and backlight/campaign rules are decided from rule evidence collected during
identification — never from an LLM call in compare. Sections become configured spatial groups of
observed areas (definition zones + `LayoutProfile.zone_selectors`), not the old crop-and-guess calls.

---

## Scope

- Add `EndcapBacklitMultitier.default_layout_profile()` (classmethod, fresh per call).
- Implement `perceive`: `perceive_image`, then drop product/box shapes that are fact-tag
  misdetections and, only if any were dropped, rebuild geometry with `rebuild_geometry`.
- Implement `identify`: `identify_image`, then remove identifications/added shapes that target
  fact tags (fact tags never count as products).
- Implement `compare`: `compare_observations(perceptions, identifications, ctx, self._description())`.
- Add `_ensure_layout(ctx)`, `_drop_fact_tag_misdetections` (pure) and `_description()`.
- Set class variables `identify_strategy=STRIPS`, `requires_slots_definition=True`,
  `min_usable_shapes=3`, `uses_enhanced_image=False` (read by `plan.py` until TASK-3870/3871).
- Delete the whole legacy half: `__init__`, `compute_roi`, `detect_objects_roi`, `detect_objects`,
  `check_planogram_compliance`, all `_compute_section_bbox` … `_iou` helpers, the `_RawBBox`/
  `_RawDetection`/`_RawDetections` models and the legacy-only constants `_DEFAULT_SECTION_PADDING`,
  `_MIN_ROI_FRACTION`.
- Create `test_endcap_backlit_cycle.py` (offline, synthetic).

**NOT in scope**:
- Shared stages, rule evaluation and zone scoring (TASK-3856, TASK-3859, TASK-3861, TASK-3862, TASK-3863).
- `test_neutral_panel_types.py` (still pins `_RawDetections` / 6 legacy call sites) — rewritten by TASK-3876.
- Orchestrator fallback, result assembly, removal of `legacy_adapter.py` (TASK-3871, TASK-3874).
- Converting backlit DB configs into definitions/selectors (TASK-3877).
- Any other type file (TASK-3864/3865/3867/3868/3869).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_backlit_multitier.py` | MODIFY | Three cycle hooks + defaults; legacy half deleted |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_endcap_backlit_cycle.py` | CREATE | Offline cycle tests for the backlit type |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from parrot.models.detections import AisleConfig, PlanogramDescription    # detections.py:356,364 (also imported by types/ink_wall.py:14)
from ..contracts import (ComparisonResult, CycleContext, IdentificationResult, IdentifyStrategy,
    PerceptionResult, Shape, ShapeKind)                                      # contracts.py:295,322,137,43,86,50,15
from ..perception.profiles import ShapeProfile                             # profiles.py:10
from ..perception.slots import AnchorRule                                  # slots.py:27
from .abstract import AbstractPlanogramType                                # endcap_backlit_multitier.py:17; abstract.py:36
# test-side
from parrot_pipelines.models import PlanogramConfig                         # models.py:32
from parrot_pipelines.planogram.plan import PlanogramCompliance             # plan.py:48
from parrot_pipelines.planogram.comparison.definition import RuleBinding, load_slots_definition  # definition.py:88,218
from parrot_pipelines.planogram.contracts import (CreditPolicy, EvidenceWeights, FixtureMembership,
    Identification, AssessmentStatus, ObservationSource, Slot)               # contracts.py:221,282,35,101,161,26,67
from parrot.models.detections import DetectionBox                            # detections.py:37
```

### Existing Signatures to Use
```python
# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_backlit_multitier.py (1796 lines)
# :1-42   docstring, imports, _DEFAULT_SECTION_PADDING (:35), _MIN_ROI_FRACTION (:41)   -> REPLACE
# :43-93  KEEP VERBATIM:
_FACT_TAG_OVERLAP_THRESHOLD: float = 0.30                                    # :46
_PRODUCT_HEIGHT_VS_TAG_RATIO: float = 1.5                                    # :51
def _is_fact_tag_misdetection(det_px: Tuple[int, int, int, int], ft: Tuple[int, int, int, int],
                              overlap_ratio: float) -> bool                  # :54-93
    # overlap_ratio = intersection_area / detection_area (computed by the caller); False when <= 0.30,
    # False for a taller product with the tag in its lower half (occlusion), else True (discard).
# :94-131 comment + class _RawBBox (:110) / _RawDetection (:119) / _RawDetections (:128)  -> DELETE
class EndcapBacklitMultitier(AbstractPlanogramType):                         # :134-1796 -> REPLACE whole class
    # legacy methods (start-end): __init__ 155-156, compute_roi 162-369, detect_objects_roi 371-465,
    # detect_objects 467-758, check_planogram_compliance 760-915, _compute_section_bbox 921-948,
    # _normalize_raw_dets_coords 950-980, _remap_bbox_to_full_image 982-1016, _build_section_prompt 1018-1065,
    # _detect_fact_tags_prescan 1067-1204, _detect_section 1206-1385, _detect_combined_flat_shelves 1391-1646,
    # _detect_flat_shelf 1648-1740, _deduplicate_cross_section 1742-1773, _iou 1775-1796

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py
class AbstractPlanogramType(ABC):                                            # :36
    identify_strategy / requires_slots_definition / min_usable_shapes / uses_enhanced_image  # :54-57 classvars
    def __init__(self, pipeline, config) -> None                             # :63 (pipeline, config, logger, validate_contract)
    def _implements(self, name: str) -> bool                                 # :463
    def validate_contract(self) -> None                                      # :467 (ValueError when requires_slots_definition and none)

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py
class Shape(BaseModel): shape_id, image_id, kind: ShapeKind, box: DetectionBox, ..., membership   # :50
class PerceptionResult(BaseModel): image_id, image_size, shapes, slots, zones, row_count,
                                   detection_source: str, ocr_available, legacy, errors           # :86
class IdentificationResult(BaseModel): image_id, identifications, added: List[Shape], errors      # :137

# Existing importers of this module (verified grep): types/__init__.py:8, plan.py:41,66,
#   parrot_pipelines/__init__.py:20 (lazy path string), tests: test_ink_wall.py:167 (registry check),
#   test_neutral_panel_types.py:15,71,77 (legacy — TASK-3876). Nothing imports _RawDetections or
#   _is_fact_tag_misdetection from outside this file.
```

#### Symbols created by dependency tasks (not yet on dev)
```python
# TASK-3854 — contracts.py
CycleContext.layout: Any = None
PerceptionResult.ocr_readings: dict[str, OcrReading]
class RuleObservation(BaseModel): image_id: str; target_id: str
    kind: Literal["illumination", "visual_features", "zone_present"]; value: str | bool | list[str] | None = None
    assessed: bool = False; source: ObservationSource; evidence: list[str] = []
IdentificationResult.rule_observations: list[RuleObservation]
# TASK-3855 — layout.py
class LayoutProfile(BaseModel): shape_profiles; anchor_rule; fill_gaps; untagged_bottom_row; identify_strategy;
    perception_mode; min_usable_shapes; min_row_items; max_row_slope; work_width; substrip_max_slots;
    ocr_batch_size; descriptor_fields; required_descriptor_fields; ocr_targets; references; zone_selectors
def resolve_layout_profile(defaults: LayoutProfile, config: dict[str, Any], *, config_name: str) -> LayoutProfile
# TASK-3856 — stages/perceive.py
async def perceive_image(image: Image.Image, image_id: str, ctx: CycleContext) -> PerceptionResult
async def rebuild_geometry(image: Image.Image, shapes: Sequence[Shape], image_id: str,
                           ctx: CycleContext, *, detection_source: str) -> PerceptionResult
# TASK-3859 — stages/identify.py
async def identify_image(image: Image.Image, perception: PerceptionResult, ctx: CycleContext) -> IdentificationResult
# TASK-3863 — stages/compare.py
def compare_observations(perceptions: Sequence[PerceptionResult], identifications: Sequence[IdentificationResult],
                         ctx: CycleContext, description: PlanogramDescription) -> ComparisonResult
```

### Does NOT Exist
- ~~`EndcapBacklitMultitier.perceive/identify/compare/default_layout_profile`~~ — this task adds them (today it
  inherits the legacy defaults at `abstract.py:497,512,527`).
- ~~A `sections` field on `LayoutProfile`~~ — sections are definition zones plus `zone_selectors`; do not add config keys.
- ~~A shared shelves-profile constant~~ — only `PRICE_TAG_PROFILE` exists in `perception/profiles.py`; the four
  shelves candidates live privately in `product_on_shelves.py:286-338` (being rewritten in parallel by TASK-3865),
  so they are copied below — do NOT import them from `product_on_shelves`.
- ~~`self.pipeline.llm` / `_downscale_image` use in the new hooks~~ — all vision goes through `ctx.vision` inside shared stages.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_backlit_multitier.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_endcap_backlit_cycle.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_backlit_multitier.py#EndcapBacklitMultitier",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_backlit_multitier.py#_is_fact_tag_misdetection",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_backlit_multitier.py#_RawBBox",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_backlit_multitier.py#_RawDetections",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_backlit_multitier.py#EndcapBacklitMultitier.check_planogram_compliance",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py#AbstractPlanogramType",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py#AbstractPlanogramType.validate_contract",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py#Shape",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py#PerceptionResult",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py#IdentificationResult",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/profiles.py#ShapeProfile",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/slots.py#AnchorRule"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
- Same thin composition as TASK-3864/3865: `_ensure_layout(ctx)` → one shared stage → type-only post-step.
- **Fact tags never products** is enforced twice, both purely: (1) in `perceive`, product/box shapes that
  `_is_fact_tag_misdetection` classifies as a mis-detected tag are removed and geometry is rebuilt through
  the SAME shared helper (`rebuild_geometry`) so slots/rows/membership stay consistent (spec §2 Stage 1);
  (2) in `identify`, identifications on fact-tag shapes and LLM-added fact-tag shapes are dropped so the
  compare stage can never register them as facings.
- **Backlight/campaign**: bind them as `illumination` / `text_requirements` / `visual_features` /
  `zone_present` rules on the header zone in the definition; `identify_image` collects neutral
  `RuleObservation`s and `compare_observations` evaluates them. The legacy 50/50 header formula
  (`:835-898`) is intentionally NOT reproduced (spec §7 risk table: never assert legacy numeric parity).
- **Sections**: "configured spatial groups of observed areas" = definition zones/shelves plus
  `layout_profile.zone_selectors` (regions/ordinals), matched by the shared stages; unknown section/zone
  visibility is inconclusive. "Bounded section calls" = the `strips` strategy bounded by
  `substrip_max_slots`; no per-section crop LLM call remains.

### Key Constraints
- `default_layout_profile()` builds new `ShapeProfile` objects each call; numbers identical to the shelves
  candidates (provisional, spec §2 — not an accuracy claim). No retailer names/counts (AC3).
- `compare()` performs no I/O and no vision call (AC8).
- `rebuild_geometry` runs only when a shape was dropped — no extra CPU work on the common path.
- `requires_slots_definition=True`: a backlit config without a definition must fail at construction (AC10).
- Run tests with `PYTHONPATH=packages/ai-parrot-pipelines/src:packages/ai-parrot/src`.

### Transitional breakage (accepted)
Deleting the legacy half breaks `test_neutral_panel_types.py` (asserts `_RawDetections` and 6 legacy call
sites in this file) and may affect `test_planogram_types.py` / `test_vision_kwargs.py`; those belong to
TASK-3876 (and TASK-3874/3875 for the other legacy suites). Do NOT edit them and do NOT list them in
Validation Commands.

### References in Codebase
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_backlit_multitier.py:1340-1352` — how the legacy code computed `overlap_ratio` before calling `_is_fact_tag_misdetection`
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py:785-797` — minimal `PlanogramDescription` fallback pattern reused by `_description`

---

## Implementation Blueprint

### Steps (in order)
1. Verify TASK-3856/3859/3863 are `done`; confirm `rebuild_geometry` accepts zones inside `shapes` (it
   "rebuilds rows, slots, zones and membership") — *why*: Block C passes `[*kept, *perception.zones]`.
2. REPLACE lines 1-42 with Block A — *why*: drop legacy imports/constants, add stage imports.
3. KEEP lines 43-93 verbatim — *why*: `_is_fact_tag_misdetection` is the retained type-specific heuristic.
4. REPLACE lines 94-1796 with Blocks B, C, D — *why*: delete the `_Raw*` models and the legacy class body (M7).
5. Create the test file, run Validation Commands — *why*: AC1, AC7, AC8, AC16.

### `.../types/endcap_backlit_multitier.py` (MODIFY — Block A, REPLACE lines 1-42)
```python
# occurrences: 1 (verified: grep -Fxc '_MIN_ROI_FRACTION: float = 0.05' endcap_backlit_multitier.py -> :41)
# REPLACE lines 1-42 (verified: docstring :1-6 .. blank line :42 after _MIN_ROI_FRACTION) with:
"""EndcapBacklitMultitier — backlit header + product shelves composed from the shared cycle stages (FEAT-612).

Perception, identification and comparison come from ``planogram/stages``; this type contributes its
defaults and keeps fact tags out of product counts. Header backlight and campaign text are bound rules
decided from rule evidence, never from an LLM call during comparison.
"""

from __future__ import annotations

from typing import ClassVar, List, Sequence, Set, Tuple

from PIL import Image

from parrot.models.detections import AisleConfig, PlanogramDescription

from ..contracts import (
    ComparisonResult,
    CycleContext,
    IdentificationResult,
    IdentifyStrategy,
    PerceptionResult,
    Shape,
    ShapeKind,
)
from ..layout import LayoutProfile, resolve_layout_profile
from ..perception.profiles import ShapeProfile
from ..perception.slots import AnchorRule
from ..stages.compare import compare_observations
from ..stages.identify import identify_image
from ..stages.perceive import perceive_image, rebuild_geometry
from .abstract import AbstractPlanogramType

_BACKLIT_DESCRIPTORS = ("family", "colors", "pack", "xl")
_PRODUCT_KINDS = frozenset({ShapeKind.PRODUCT, ShapeKind.BOX})

```
**Why**: `asyncio`, `json`, `ImageDraw`, `pydantic`, `Detection`/`SectionRegion`/`ShelfSection`/compliance
models were used only by the legacy half.

### Block B — profiles (REPLACE starts at line 94; `class _RawBBox(BaseModel):` occurrences 1, verified :110)
```python
# occurrences: 1 (verified: grep -Fxc 'class _RawBBox(BaseModel):' endcap_backlit_multitier.py -> :110)
# REPLACE lines 94-1796 (Raw-model comment block :96-108, _RawBBox :110, _RawDetection :119, _RawDetections :128,
#   class EndcapBacklitMultitier :134-1796) with Blocks B, C, D in order.


def _backlit_shape_profiles() -> List[ShapeProfile]:
    """Fresh copies of the provisional shelves CV candidates (verbatim values; not an accuracy claim)."""
    return [
        ShapeProfile(name="product_body", kind=ShapeKind.PRODUCT.value, min_width=0.06, max_width=0.30,
                     min_height=0.08, max_height=0.45, min_aspect=0.5, max_aspect=2.5, polarity="edge",
                     min_rectangularity=0.70, min_contrast_std=5.0),
        ShapeProfile(name="product_box", kind=ShapeKind.BOX.value, min_width=0.04, max_width=0.20,
                     min_height=0.05, max_height=0.25, min_aspect=0.4, max_aspect=2.0, polarity="edge",
                     min_rectangularity=0.80, min_contrast_std=5.0),
        ShapeProfile(name="fact_tag", kind=ShapeKind.FACT_TAG.value, min_width=0.03, max_width=0.12,
                     min_height=0.02, max_height=0.08, min_aspect=1.2, max_aspect=4.0, polarity="bright"),
        ShapeProfile(name="backlit_zone", kind=ShapeKind.ZONE.value, min_width=0.40, max_width=1.0,
                     min_height=0.06, max_height=0.35, min_aspect=1.5, max_aspect=12.0, polarity="bright",
                     min_rectangularity=0.80, min_contrast_std=5.0, thresholds=(200, 220, 240)),
    ]


def _px(shape: Shape) -> Tuple[int, int, int, int]:
    """Source-pixel box tuple of a shape."""
    return (shape.box.x1, shape.box.y1, shape.box.x2, shape.box.y2)
```
**Why**: values copied from `product_on_shelves.py:286-338` at `dev` (spec §2: "Non-ink numerical profile defaults
reuse the already-present shelves candidates"). black will re-wrap these literals; that is fine.

### Block C — class, defaults, perceive/identify/compare
```python
class EndcapBacklitMultitier(AbstractPlanogramType):
    """Backlit header + product shelves: shared perceive/identify/compare; fact tags never count as products."""

    identify_strategy: ClassVar[IdentifyStrategy] = IdentifyStrategy.STRIPS  # plan.py reads until TASK-3871
    requires_slots_definition: ClassVar[bool] = True
    min_usable_shapes: ClassVar[int] = 3
    uses_enhanced_image: ClassVar[bool] = False

    @classmethod
    def default_layout_profile(cls) -> LayoutProfile:
        """Return a fresh profile; never retailer product names, expected counts or shared mutable defaults."""
        return LayoutProfile(
            shape_profiles=_backlit_shape_profiles(),
            anchor_rule=AnchorRule.SHAPE_IS_SLOT,
            fill_gaps=False,
            untagged_bottom_row=False,
            identify_strategy=IdentifyStrategy.STRIPS,
            perception_mode="cv",
            min_usable_shapes=3,
            descriptor_fields=list(_BACKLIT_DESCRIPTORS),
            required_descriptor_fields=[],
        )

    def _ensure_layout(self, ctx: CycleContext) -> LayoutProfile:
        """Resolve defaults + config onto the run context when the orchestrator has not (pre-TASK-3871)."""
        if ctx.layout is None:
            ctx.layout = resolve_layout_profile(
                self.default_layout_profile(),
                dict(self.config.planogram_config or {}),
                config_name=str(getattr(self.config, "config_name", None) or type(self).__name__),
            )
        return ctx.layout

    async def perceive(self, image: Image.Image, image_id: str, ctx: CycleContext) -> PerceptionResult:
        """Compose shared perception and type-specific observed geometry only."""
        self._ensure_layout(ctx)
        perception = await perceive_image(image, image_id, ctx)
        kept = self._drop_fact_tag_misdetections(perception.shapes)
        if len(kept) == len(perception.shapes):
            return perception
        self.logger.debug("Backlit %s: %d fact-tag misdetections dropped", image_id, len(perception.shapes) - len(kept))
        rebuilt = await rebuild_geometry(
            image, [*kept, *perception.zones], image_id, ctx, detection_source=perception.detection_source
        )
        return rebuilt.model_copy(update={"errors": [*perception.errors, *rebuilt.errors]})

    async def identify(
        self, image: Image.Image, perception: PerceptionResult, ctx: CycleContext
    ) -> IdentificationResult:
        """Compose shared OCR/vision/evidence collection; drop any claim on a fact tag."""
        self._ensure_layout(ctx)
        result = await identify_image(image, perception, ctx)
        tags: Set[str] = {s.shape_id for s in perception.shapes if s.kind == ShapeKind.FACT_TAG}
        added_tags = {s.shape_id for s in result.added if s.kind == ShapeKind.FACT_TAG}
        drop = tags | added_tags
        return result.model_copy(
            update={
                "identifications": [i for i in result.identifications if i.shape_id not in drop],
                "added": [s for s in result.added if s.shape_id not in added_tags],
            }
        )

    async def compare(
        self,
        perceptions: Sequence[PerceptionResult],
        identifications: Sequence[IdentificationResult],
        ctx: CycleContext,
    ) -> ComparisonResult:
        """Run deterministic comparison and the type's evidence-based rule projection."""
        self._ensure_layout(ctx)
        return compare_observations(perceptions, identifications, ctx, self._description())
```
**Why**: spec M7 skeleton signatures verbatim. `required_descriptor_fields=[]` because generic types do not
inherit ink's mandatory `xl` (spec §2 Stage 3). `rule_observations` are left untouched by the identify
post-step, so header illumination/campaign evidence reaches compare.

### Block D — pure helpers (inside the class, after `compare`)
```python
    @staticmethod
    def _drop_fact_tag_misdetections(shapes: Sequence[Shape]) -> List[Shape]:
        """Remove product/box shapes that are really fact tags; keep occluded tall products (pure)."""
        tags = [s for s in shapes if s.kind == ShapeKind.FACT_TAG]
        if not tags:
            return list(shapes)
        kept: List[Shape] = []
        for shape in shapes:
            if shape.kind in _PRODUCT_KINDS:
                det = _px(shape)
                area = max(1, (det[2] - det[0]) * (det[3] - det[1]))
                misdetected = False
                for tag in tags:
                    ft = _px(tag)
                    inter_w = max(0, min(det[2], ft[2]) - max(det[0], ft[0]))
                    inter_h = max(0, min(det[3], ft[3]) - max(det[1], ft[1]))
                    if _is_fact_tag_misdetection(det, ft, (inter_w * inter_h) / area):
                        misdetected = True
                        break
                if misdetected:
                    continue
            kept.append(shape)
        return kept

    def _description(self) -> PlanogramDescription:
        """PlanogramDescription for weights/thresholds; minimal when the config no longer describes shelves."""
        try:
            return self.config.get_planogram_description()
        except Exception as exc:  # noqa: BLE001 - migrated configs may omit the legacy keys
            self.logger.debug("EndcapBacklitMultitier: minimal PlanogramDescription (%s)", exc)
            cfg = self.config.planogram_config or {}
            return PlanogramDescription(
                brand=str(cfg.get("brand", "")),
                category=str(cfg.get("category", "")),
                aisle=AisleConfig(name=str(cfg.get("aisle", "") or "aisle")),
                shelves=[],
            )
```
**Why**: the overlap ratio is intersection / detection area, exactly what `_is_fact_tag_misdetection`
documents (:79-81) and what the legacy caller computed (:1340-1352). `_description` mirrors the proven
fallback of `product_on_shelves.py:785-797` so configs without legacy shelves still project results.

### `packages/ai-parrot-pipelines/tests/planogram_cycle/test_endcap_backlit_cycle.py` (CREATE)
See Test Specification — write it as the whole-file starting point.

### FILL IN checklist
- [ ] Block C `_ensure_layout` — confirm TASK-3855's `resolve_layout_profile` input (whole `planogram_config` vs `layout_profile` sub-dict).
- [ ] Block C `perceive` — confirm Step 1 (zones in `rebuild_geometry` shapes); if it takes product shapes only, pass `kept` and keep `perception.zones` via `model_copy`.
- [ ] Tests — the offline full run: pick the fake default output that `VisionAdapter` parses as an empty `IdentificationResponse` (see `test_vision_adapter.py`).
- [ ] Run `ruff check`; remove only imports it flags unused.

---

## Acceptance Criteria

- [ ] `EndcapBacklitMultitier` implements `perceive`, `identify`, `compare`, `default_layout_profile`; none of `compute_roi`, `detect_objects_roi`, `detect_objects`, `check_planogram_compliance` remain; `_RawBBox`/`_RawDetection`/`_RawDetections` are gone (AC1).
- [ ] `default_layout_profile()` is fresh per call: four profiles (product/box/fact_tag/zone), `shape_is_slot`, `strips`, `cv`, `min_usable_shapes=3` (spec §2; AC3, AC4).
- [ ] A product/box shape classified by `_is_fact_tag_misdetection` is dropped and geometry is rebuilt once; an occluded tall product is kept (AC7).
- [ ] Identifications/added shapes on fact tags never reach compare (spec §2 "fact tags never count as products").
- [ ] `compare` makes no vision call; header illumination OFF evidence with a bound `illumination` rule makes the header unit non-compliant; unknown illumination is inconclusive (AC8, AC9).
- [ ] A backlit config without `slots_definition` raises `ValueError` at construction (AC10).
- [ ] One offline `PlanogramCompliance.run()` on the synthetic endcap returns all eight result keys, measured (non-legacy) status and `overall_compliant is False` when nothing is identified (AC2, AC11).
- [ ] Validation Commands pass.
- [ ] Lint/format clean: `ruff check packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_backlit_multitier.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_endcap_backlit_cycle.py`
- [ ] Lint/format clean: `black --check --line-length 120 packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_backlit_multitier.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_endcap_backlit_cycle.py`

## Validation Commands

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_endcap_backlit_cycle.py -q`
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_ink_wall.py::test_ink_wall_is_registered_everywhere -q`

---

## Test Specification

```python
# packages/ai-parrot-pipelines/tests/planogram_cycle/test_endcap_backlit_cycle.py
"""Offline cycle tests for EndcapBacklitMultitier (FEAT-612, Module 7)."""

import logging
from unittest.mock import MagicMock

import pytest

from parrot.models.detections import DetectionBox
from parrot_pipelines.models import PlanogramConfig
from parrot_pipelines.planogram import plan as plan_module
from parrot_pipelines.planogram.comparison.definition import RuleBinding, load_slots_definition
from parrot_pipelines.planogram.contracts import (
    AssessmentStatus, CreditPolicy, CycleContext, EvidenceWeights, FixtureMembership, Identification,
    IdentificationResult, IdentifyStrategy, ObservationSource, PerceptionResult, RuleObservation, Shape, ShapeKind, Slot,
)
from parrot_pipelines.planogram.perception.slots import AnchorRule
from parrot_pipelines.planogram.plan import PlanogramCompliance
from parrot_pipelines.planogram.types import endcap_backlit_multitier as backlit_module
from parrot_pipelines.planogram.types.endcap_backlit_multitier import EndcapBacklitMultitier


class _InlineExecutor:
    async def run(self, fn, *args):
        return fn(*args)

    async def aclose(self) -> None:
        return None


class _NoOcr:
    available = False


class _RaisingVision:
    def __getattr__(self, name):
        raise AssertionError(f"compare must not touch vision ({name})")


def _definition_dict() -> dict:
    """Generic header zone + one shelf of two facings (fictitious ids, no retailer data)."""
    # FILL IN: {"shelves": [{"shelf_id": "header", "shelf_number": 0, "level": "header", "facings": []},
    #   {"shelf_id": "s1", "shelf_number": 1, "level": "s1", "facings": [two facings P-1/P-2 with identifiers]}],
    #   "zones": [{"zone_id": "header_light", "kind": "backlit", "shelf_id": "header", "required": True}]}


def _box(x1, y1, x2, y2) -> DetectionBox:
    return DetectionBox(x1=x1, y1=y1, x2=x2, y2=y2, confidence=0.9)


def test_default_layout_profile_backlit_defaults():
    first, second = EndcapBacklitMultitier.default_layout_profile(), EndcapBacklitMultitier.default_layout_profile()
    assert first is not second and first.shape_profiles[0] is not second.shape_profiles[0]
    assert {p.kind for p in first.shape_profiles} == {"product", "box", "fact_tag", "zone"}
    assert first.anchor_rule == AnchorRule.SHAPE_IS_SLOT and first.identify_strategy == IdentifyStrategy.STRIPS
    assert first.perception_mode == "cv" and first.min_usable_shapes == 3


def test_legacy_contract_removed():
    handler_cls = EndcapBacklitMultitier
    for name in ("compute_roi", "detect_objects_roi", "detect_objects", "check_planogram_compliance"):
        assert name not in vars(handler_cls)
    assert not hasattr(backlit_module, "_RawDetections")


def test_missing_definition_fails_fast(fake_vision_client):
    with pytest.raises(ValueError):
        PlanogramCompliance(
            planogram_config=PlanogramConfig(planogram_type="endcap_backlit_multitier", planogram_config={}),
            llm=fake_vision_client,
        )


def test_drop_fact_tag_misdetections_keeps_occluded_product():
    tag = Shape(shape_id="t", image_id="img0", kind=ShapeKind.FACT_TAG, box=_box(100, 300, 160, 320))
    fake = Shape(shape_id="p1", image_id="img0", kind=ShapeKind.PRODUCT, box=_box(98, 298, 162, 322))  # tag-sized
    tall = Shape(shape_id="p2", image_id="img0", kind=ShapeKind.PRODUCT, box=_box(90, 150, 170, 322))  # tag in lower half
    kept = EndcapBacklitMultitier._drop_fact_tag_misdetections([tag, fake, tall])
    assert [s.shape_id for s in kept] == ["t", "p2"]


async def test_perceive_rebuilds_geometry_only_after_a_drop(monkeypatch):
    # FILL IN: monkeypatch backlit_module.perceive_image -> PerceptionResult with [tag, fake, tall] + one zone;
    #   monkeypatch backlit_module.rebuild_geometry to record the shapes it receives and return a PerceptionResult;
    #   assert rebuild called once with shape ids {"t", "p2", <zone id>}; with no misdetection it is not called.


async def test_identify_drops_fact_tag_claims(monkeypatch):
    # FILL IN: monkeypatch backlit_module.identify_image -> IdentificationResult with identifications on "t" (tag)
    #   and "img0:r0:s1" (slot) and one added FACT_TAG shape; result keeps only the slot identification, no
    #   added fact tag, and rule_observations unchanged.


async def test_compare_header_rules_from_evidence_only():
    # FILL IN: ctx=CycleContext(vision=_RaisingVision(), definition=load_slots_definition(_definition_dict()),
    #   bindings=[zone_present + illumination(required on)], ...); perception with an on-fixture zone shape;
    #   identification result with RuleObservation(kind="illumination", value="off", assessed=True, source=LLM)
    #   -> header unit non_compliant, overall_compliant False; same with assessed=False -> INCONCLUSIVE.


async def test_offline_full_run_reports_measured_result(monkeypatch, fake_vision_client, synthetic_shelf_image):
    # FILL IN: monkeypatch plan_module.CpuExecutor=_InlineExecutor, plan_module.OcrReader=_NoOcr (as test_ink_wall
    #   `offline` fixture); fake client default output parses to an empty IdentificationResponse;
    #   result = await PlanogramCompliance(planogram_config=PlanogramConfig(planogram_type="endcap_backlit_multitier",
    #       planogram_config={}, slots_definition=_definition_dict()), llm=fake_vision_client).run(synthetic_shelf_image)
    #   assert {"step3_compliance_results", "compliance_results", "overall_compliance_score", "overall_compliant",
    #           "identified_products", "shelf_regions", "rendered_image", "overlay_path"} <= set(result)
    #   assert result["compliance_results"] is result["step3_compliance_results"]
    #   assert result["assessment_status"] != "legacy_unmeasured" and result["overall_compliant"] is False
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug refactor-planogram-compliance --feature-id FEAT-612`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in the
   per-spec index `sdd/tasks/index/refactor-planogram-compliance.json`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/refactor-planogram-compliance.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-3866 refactor-planogram-compliance verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
