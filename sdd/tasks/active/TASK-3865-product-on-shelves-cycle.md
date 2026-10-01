# TASK-3865: Migrate ProductOnShelves and delete its legacy half

**Feature**: FEAT-612 — Refactor Planogram Compliance
**Spec**: `sdd/specs/refactor-planogram-compliance.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: XL (> 8h)
**Depends-on**: TASK-3856, TASK-3859, TASK-3863
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 6** and §2 "Type defaults" (product_on_shelves row). `product_on_shelves.py` is
2,320 lines: ~480 lines of FEAT-574 cycle hooks (perceive with inline rows/slots/OCR, identify,
and a compare that calls the LLM-backed `_check_illumination` at :694) plus ~1,800 lines of the
legacy ROI/grid/LLM-detection pipeline (`compute_roi` … `_assign_products_to_shelves`). The shared
stages (TASK-3856 `perceive_image`, TASK-3859 `identify_image`, TASK-3863 `compare_observations`)
now do all of that generically and without I/O in compare. This task reduces the type to its
defaults (the four existing provisional CV profiles, `shape_is_slot`, full image, threshold 3,
default perception **cv** — it was `llm_detector` at :80) plus the one genuinely specific behavior:
**fact-tag corroboration** — fact-tag text may support identifying an *observed occupied* slot,
never prove an unseen product (spec M6 responsibility). Illumination and other bound rules are
decided from rule evidence collected during identification (spec §2 Stage 2 / Stage 3), so compare
no longer calls `_check_illumination`. Removing the grid imports (:12-15) unblocks TASK-3874.

---

## Scope

- Add `ProductOnShelves.default_layout_profile()` (classmethod) returning a NEW `LayoutProfile`
  per call built from the four existing profile values (`product_body`, `product_box`, `fact_tag`,
  `backlit_zone`, currently `product_on_shelves.py:286-338`), `shape_is_slot`, `full_image`,
  `perception_mode="cv"`, `min_usable_shapes=3`.
- Replace `perceive` / `identify` / `compare` with compositions of `perceive_image`,
  `identify_image` and `compare_observations`; `compare` first applies fact-tag corroboration.
- Add `_corroborate_with_fact_tags` (pure) and module helpers `_tag_text`, `_slot_above`.
- Add a private `_ensure_layout(ctx)` so hooks work before the orchestrator sets `ctx.layout`.
- Delete every legacy and superseded method (full list in the blueprint), the product-hint
  `fallback_detection_prompt` override, `DEFAULT_PERCEPTION_MODE`, `_perception_mode`,
  `get_shape_profiles`, `__init__` (endcap margins only fed `_find_poster`), and the grid imports.
- Rewrite the two owned test files for the new contract.

**NOT in scope**:
- Shared stages / rule evaluation (TASK-3856, TASK-3859, TASK-3861, TASK-3863) and scoring (TASK-3862).
- `abstract.py` helpers (`_check_illumination`, `_extract_illumination_state`, `_base_model_from_str`,
  `get_grid_strategy`) — TASK-3870 decides their removal.
- Deleting `grid/` modules (TASK-3874), `legacy.py` (TASK-3873), orchestrator fallback/assembly (TASK-3871).
- Characterization/legacy suites `test_pos_compliance_characterization.py`,
  `test_pos_fact_tags_illumination_characterization.py` (TASK-3875), `test_legacy_run_orchestration.py`
  (TASK-3874), `test_neutral_shelf_types.py`, `test_planogram_types.py`, `test_vision_kwargs.py` (TASK-3876).
- `ink_wall.py` (TASK-3864) — keep importing nothing from it (see Implementation Notes).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py` | MODIFY | Thin cycle type; legacy half deleted |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_pos_migrated_perceive_identify.py` | MODIFY | Profile defaults, alias, shared perceive/identify |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_pos_migrated_compare.py` | MODIFY | Evidence-only compare, fact-tag corroboration |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
# relative to packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py
from parrot.models.detections import AisleConfig, PlanogramDescription    # product_on_shelves.py:54; detections.py:356,364
from ..comparison.definition import SlotsDefinition                        # product_on_shelves.py:19; definition.py:98
from ..contracts import (ComparisonResult, CycleContext, FixtureMembership, Identification,
    IdentificationResult, IdentifyStrategy, PerceptionResult, Shape, ShapeKind, Slot)   # :23-36; contracts.py:15-322
from ..perception.profiles import ShapeProfile                             # :41; profiles.py:10
from ..perception.slots import AnchorRule                                  # :44; slots.py:27
from .abstract import AbstractPlanogramType                                # :17; abstract.py:36
```

### Existing Signatures to Use
```python
# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py (current, 2320 lines)
# imports :7-61 ; grid imports to remove :12-15 ; `from .ink_wall import resolve_identity` :45 (remove)
class ProductOnShelves(AbstractPlanogramType):                                  # :64
    identify_strategy: ClassVar[IdentifyStrategy] = IdentifyStrategy.FULL_IMAGE # :76 KEEP (plan.py reads classvars)
    requires_slots_definition: ClassVar[bool] = True                            # :77 KEEP
    min_usable_shapes: ClassVar[int] = 3                                        # :78 KEEP (plan.py:263)
    uses_enhanced_image: ClassVar[bool] = False                                 # :79 KEEP (plan.py:248)
    DEFAULT_PERCEPTION_MODE = "llm_detector"                                    # :80 DELETE
    def __init__(self, pipeline, config)                                        # :82-87 DELETE (margins only for _find_poster)
    # legacy / superseded — DELETE (start-end lines, from AST):
    #   compute_roi 93-117, detect_objects_roi 119-138, get_grid_strategy 140-152, detect_objects 154-257,
    #   _perception_mode 263-275, get_shape_profiles 277-338 (values move to _shelf_shape_profiles),
    #   fallback_detection_prompt 340-376 (injects expected product names — forbidden by spec §2 Stage 1),
    #   perceive 378-425 (REPLACE), _candidate_to_shape 427-447, _rows_and_slots 449-510,
    #   _ocr_tags_and_zones 512-526, identify 528-552 (REPLACE), _images_for_rules 558-564,
    #   _observed_zones 566-581, _facing_views 583-593, _target_texts 595-621, _evaluate_rules 623-661,
    #   _unassessed 663-665, _rule_illumination 667-710, _rule_text 712-743, _rule_visual 745-760,
    #   _rule_zone_present 762-771, _canonical_identity 773-783, compare 799-862 (REPLACE),
    #   _detect_with_grid 864-900, _detect_legacy 902-1022, check_planogram_compliance 1024-1437,
    #   _find_poster 1443-1609, _canonical_expected_key 1611-1624, _canonical_found_key 1626-1659,
    #   _looks_like_box 1661-1673, _normalize_ocr_text 1675-1688, _calculate_visual_feature_match 1690-1757,
    #   _get_default_shelf_configs 1759-1768, _generate_virtual_shelves 1770-1855, _ocr_fact_tags 1857-2020,
    #   _corroborate_products_with_fact_tags 2022-2129, _assign_products_to_shelves 2131-2320
    def _cycle_description(self) -> PlanogramDescription                        # :785-797 KEEP unchanged

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py
class AbstractPlanogramType(ABC):                                               # :36
    def __init__(self, pipeline, config) -> None                                # :63 sets pipeline/config/logger, validate_contract()
    def _implements(self, name: str) -> bool                                    # :463
    def fallback_detection_prompt(self) -> Optional[str]                        # :569 returns None -> generic prompt

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py
class Shape(BaseModel): shape_id, image_id, kind, box, profile, row_index, slot_index, ocr_text,
                        ocr_confidence, source, membership, membership_evidence           # :50
class Slot(BaseModel): slot_id, image_id, row_index, slot_index, box, anchor_shape_id, inferred   # :67
class Identification(BaseModel): shape_id, image_id, product, brand, text, descriptors, occupancy,
                                  raw_confidence, evidence: List[str], source, uncertain  # :101
class IdentificationResult(BaseModel): image_id, identifications, added, errors            # :137

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/ink_wall.py:48 (moves to comparison/identity.py in TASK-3861)
_LINE_SPLIT = re.compile(r"\s*(?:\n|\|)\s*")   # evidence strings are split on "\n" or "|" into matchable lines
# resolve_identity rule 1 (ink_wall.py:95-101): a definition identifier equal to one normalised line resolves identity.

# plan.py transitional facts: :231 CycleContext built without layout until TASK-3871;
#   :270 `handler.fallback_detection_prompt() or GENERIC_DETECTION_PROMPT` -> base None selects the generic prompt.
```

#### Symbols created by dependency tasks (not yet on dev)
```python
# TASK-3854 — contracts.py additions
class OcrReading(BaseModel): text: str = ""; confidence: float = 0.0
PerceptionResult.ocr_readings: dict[str, OcrReading]      # own-box OCR keyed by target id
CycleContext.layout: Any = None
class RuleObservation(BaseModel): image_id: str; target_id: str
    kind: Literal["illumination", "visual_features", "zone_present"]; value: str | bool | list[str] | None = None
    assessed: bool = False; source: ObservationSource; evidence: list[str] = []
IdentificationResult.rule_observations: list[RuleObservation]

# TASK-3855 — layout.py
class LayoutProfile(BaseModel): shape_profiles; anchor_rule; fill_gaps; untagged_bottom_row; identify_strategy;
    perception_mode: Literal["cv", "llm_detector"] = "cv"; min_usable_shapes; min_row_items; max_row_slope;
    work_width; substrip_max_slots; ocr_batch_size; descriptor_fields; required_descriptor_fields;
    ocr_targets; references; zone_selectors            # extra="forbid"
class ZoneSelector(BaseModel): zone_id: str; profile: str | None; kind: str | None; ordinal: int | None;
    region: tuple[float, float, float, float] | None
def resolve_layout_profile(defaults: LayoutProfile, config: dict[str, Any], *, config_name: str) -> LayoutProfile

# TASK-3856 — stages/perceive.py
async def perceive_image(image: Image.Image, image_id: str, ctx: CycleContext) -> PerceptionResult
# TASK-3859 — stages/identify.py
async def identify_image(image: Image.Image, perception: PerceptionResult, ctx: CycleContext) -> IdentificationResult
# TASK-3863 — stages/compare.py
def compare_observations(perceptions: Sequence[PerceptionResult], identifications: Sequence[IdentificationResult],
                         ctx: CycleContext, description: PlanogramDescription) -> ComparisonResult
```

### Does NOT Exist
- ~~`ProductOnShelves.default_layout_profile`~~ / ~~`_corroborate_with_fact_tags`~~ — this task adds them.
- ~~`ProductOnShelves._evaluate_rules` after this task~~ — rule evaluation is `comparison/rules.py` (TASK-3863).
- ~~A shared shelves-profile constant in `perception/profiles.py`~~ — only `PRICE_TAG_PROFILE` exists (:65);
  keep the four shelf profiles private to this module.
- ~~`CycleContext.layout` set by `plan.py`~~ — not before TASK-3871.
- ~~`Slot.kind`~~ — slots have no kind; body/box distinction lives on the anchor `Shape.kind` (PRODUCT vs BOX).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_pos_migrated_perceive_identify.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_pos_migrated_compare.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py#ProductOnShelves",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py#ProductOnShelves.perceive",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py#ProductOnShelves.identify",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py#ProductOnShelves.compare",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py#ProductOnShelves.get_shape_profiles",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py#ProductOnShelves._cycle_description",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py#ProductOnShelves.fallback_detection_prompt",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py#AbstractPlanogramType",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py#AbstractPlanogramType.fallback_detection_prompt",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py#Shape",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py#Slot",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py#Identification",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py#IdentificationResult",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/profiles.py#ShapeProfile",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/slots.py#AnchorRule"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
- Same thin-composition shape as TASK-3864 (`InkWall`): `_ensure_layout(ctx)` → one shared stage →
  type-only post-step. Do not import from `ink_wall.py` (sibling migration task; types stay independent).
- Fact-tag corroboration is a pure transformation of `IdentificationResult` applied at the start of
  `compare`: it appends `"fact_tag | <text>"` evidence lines to an **occupied** slot read whose product is
  not already an exact catalogue id. The `|` makes `_LINE_SPLIT` produce the bare tag text as its own line,
  so resolve_identity's identifier rule can use it. It never creates an identification, never changes
  `occupancy`, `product`, `uncertain` or `raw_confidence` (AC7: raw confidence unchanged; evidence cannot be
  invented from an unseen product).
- Body/box distinction is retained through the profiles: `product_body` → `ShapeKind.PRODUCT`,
  `product_box` → `ShapeKind.BOX`; the shared stage anchors one slot per product/box shape and never on
  fact tags (spec §2 Stage 1: tags must not inflate product counts).

### Key Constraints
- `default_layout_profile()` returns fresh objects (new list, new `ShapeProfile`s) on every call.
- Keep profile numbers byte-identical to `product_on_shelves.py:286-338`; they are provisional, not an
  accuracy claim (spec §2). No retailer product names or counts.
- `compare` must not await any vision call and must not call `_check_illumination` (spec corrections
  table: `:667` was the offending call); illumination comes from `rule_observations` (AC8).
- Default perception is `cv`; the old top-level `planogram_config["perception_mode"]` stays accepted as an
  alias through `resolve_layout_profile` (spec §2 compatibility policy) — do not re-implement it here.
- Keep the four class variables until TASK-3870/3871.
- Run tests with `PYTHONPATH=packages/ai-parrot-pipelines/src:packages/ai-parrot/src`.

### Transitional breakage (accepted)
Deleting the legacy half breaks legacy-pinning suites owned by TASK-3874/3875/3876:
`test_legacy_run_orchestration.py`, `test_pos_compliance_characterization.py`,
`test_pos_fact_tags_illumination_characterization.py`, `test_neutral_shelf_types.py`,
`test_planogram_types.py` (`_looks_like_box`, `_normalize_ocr_text`, `_calculate_visual_feature_match`),
`test_vision_kwargs.py`. They stay red until those tasks land. Do NOT edit them and do NOT list them in
Validation Commands. `grid/detector.py:233` only mentions this file in a comment — no import to fix.

### References in Codebase
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py:2022-2129` — legacy corroboration (injected synthetic products; the new rule must NOT do that)
- spec §2 "Type defaults" product_on_shelves row; §3 Module 6

---

## Implementation Blueprint

### Steps (in order)
1. Verify TASK-3856/3859/3863 are `done` and read their public signatures — *why*: the hooks are one-line delegations to them.
2. Replace the whole file (lines 1-2320) with Blocks A–D below, in order — *why*: the legacy half is ~1,800 of 2,320 lines; editing around it is error-prone. Carry `_cycle_description` (:785-797) over verbatim.
3. Check deleted names are gone: `grep -nE "grid\.|compute_roi|detect_objects|check_planogram_compliance|_check_illumination|DEFAULT_PERCEPTION_MODE" product_on_shelves.py` must print nothing — *why*: AC1/AC14 and TASK-3874 unblocking.
4. Rewrite the two test files per Test Specification, run Validation Commands — *why*: AC16.

### `.../types/product_on_shelves.py` (MODIFY — Block A: header, REPLACE lines 1-62)
```python
# occurrences: 1 (verified: grep -Fxc 'class ProductOnShelves(AbstractPlanogramType):' product_on_shelves.py -> :64)
# REPLACE lines 1-62 (docstring + imports, verified :1-62) with:
"""ProductOnShelves — shelved-product planogram type composed from the shared cycle stages (FEAT-574, FEAT-612).

Perception, identification and comparison come from ``planogram/stages``; this type contributes its
provisional CV defaults and fact-tag corroboration of observed, occupied slots.
"""

from __future__ import annotations

from typing import ClassVar, Dict, List, Mapping, Optional, Sequence

from PIL import Image

from parrot.models.detections import AisleConfig, PlanogramDescription

from ..comparison.definition import SlotsDefinition
from ..contracts import (
    ComparisonResult,
    CycleContext,
    FixtureMembership,
    Identification,
    IdentificationResult,
    IdentifyStrategy,
    PerceptionResult,
    Shape,
    ShapeKind,
    Slot,
)
from ..layout import LayoutProfile, resolve_layout_profile
from ..perception.profiles import ShapeProfile
from ..perception.slots import AnchorRule
from ..stages.compare import compare_observations
from ..stages.identify import identify_image
from ..stages.perceive import perceive_image
from .abstract import AbstractPlanogramType

_SHELF_DESCRIPTORS = ("family", "colors", "pack", "xl")
```
**Why**: removes the grid imports (:12-15, required by TASK-3874), the `.ink_wall` import (:45), and every
import only the legacy half used (asyncio, re, unicodedata, numpy, compliance models, Detection…).

### Block B — module helpers (append after Block A)
```python
def _shelf_shape_profiles() -> List[ShapeProfile]:
    """Fresh copies of the provisional shelves CV candidates (spike: inconclusive; not an accuracy claim)."""
    # FILL IN: return the four ShapeProfile(...) literals copied VERBATIM from product_on_shelves.py:286-338
    #   (product_body/PRODUCT, product_box/BOX, fact_tag/FACT_TAG, backlit_zone/ZONE) — bounded by spec §2
    #   "reuse the already-present shelves candidates"; do not retune a single number.
    raise NotImplementedError


def _tag_text(tag: Shape, readings: Mapping[str, object], reads: Mapping[str, Identification]) -> Optional[str]:
    """Own-box OCR of a fact tag, else its shape OCR, else the text the vision call read on that tag."""
    reading = readings.get(tag.shape_id)
    text = getattr(reading, "text", "") or tag.ocr_text
    if not text and tag.shape_id in reads:
        text = reads[tag.shape_id].text
    return text.strip() if text and text.strip() else None


def _slot_above(tag: Shape, slots: Sequence[Slot]) -> Optional[Slot]:
    """The slot a shelf-edge tag labels: horizontally covering the tag centre, tag at/below its lower half."""
    cx = (tag.box.x1 + tag.box.x2) / 2
    cy = (tag.box.y1 + tag.box.y2) / 2
    best: Optional[Slot] = None
    for slot in slots:
        height = max(1, slot.box.y2 - slot.box.y1)
        if not slot.box.x1 <= cx <= slot.box.x2:
            continue
        if not (slot.box.y1 + slot.box.y2) / 2 <= cy <= slot.box.y2 + height:
            continue
        if best is None or abs(tag.box.y1 - slot.box.y2) < abs(tag.box.y1 - best.box.y2):
            best = slot
    return best
```
**Why**: profiles stay private to the type (Does NOT Exist: no shared constant). `_slot_above` encodes the
shelf-edge convention (a fact tag hangs at the lower edge of the product it labels) purely geometrically —
no expected product is consulted.

### Block C — class, defaults and hooks (append after Block B)
```python
class ProductOnShelves(AbstractPlanogramType):
    """Shelved products: shared perceive/identify/compare plus fact-tag corroboration."""

    identify_strategy: ClassVar[IdentifyStrategy] = IdentifyStrategy.FULL_IMAGE  # plan.py reads until TASK-3871
    requires_slots_definition: ClassVar[bool] = True
    min_usable_shapes: ClassVar[int] = 3
    uses_enhanced_image: ClassVar[bool] = False

    @classmethod
    def default_layout_profile(cls) -> LayoutProfile:
        """Return a fresh profile; never retailer product names, expected counts or shared mutable defaults."""
        return LayoutProfile(
            shape_profiles=_shelf_shape_profiles(),
            anchor_rule=AnchorRule.SHAPE_IS_SLOT,
            fill_gaps=False,
            untagged_bottom_row=False,
            identify_strategy=IdentifyStrategy.FULL_IMAGE,
            perception_mode="cv",
            min_usable_shapes=3,
            descriptor_fields=list(_SHELF_DESCRIPTORS),
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
        return await perceive_image(image, image_id, ctx)

    async def identify(
        self, image: Image.Image, perception: PerceptionResult, ctx: CycleContext
    ) -> IdentificationResult:
        """Compose shared OCR/vision/evidence collection with the resolved profile."""
        self._ensure_layout(ctx)
        return await identify_image(image, perception, ctx)

    async def compare(
        self,
        perceptions: Sequence[PerceptionResult],
        identifications: Sequence[IdentificationResult],
        ctx: CycleContext,
    ) -> ComparisonResult:
        """Run deterministic comparison and the type's evidence-based rule projection."""
        self._ensure_layout(ctx)
        by_image = {p.image_id: p for p in perceptions}
        corroborated = [
            self._corroborate_with_fact_tags(by_image[i.image_id], i, ctx.definition) if i.image_id in by_image else i
            for i in identifications
        ]
        return compare_observations(perceptions, corroborated, ctx, self._cycle_description())
```
**Why**: spec M6 skeleton signatures verbatim. `required_descriptor_fields=[]` follows spec §2 Stage 3
("generic types do not inherit a mandatory xl field") and §7 ("no required fields means the signature step is
disabled"); identity then relies on exact ids, identifiers, aliases and reference evidence. No
`fallback_detection_prompt` override: the base returns `None`, so the orchestrator uses the generic prompt.

### Block D — corroboration + description (append after Block C)
```python
    @staticmethod
    def _corroborate_with_fact_tags(
        perception: PerceptionResult, result: IdentificationResult, definition: Optional[SlotsDefinition]
    ) -> IdentificationResult:
        """Add fact-tag text as evidence to OCCUPIED, not-yet-catalogued slot reads; never create or occupy a slot."""
        tags = [
            s for s in perception.shapes
            if s.kind == ShapeKind.FACT_TAG and s.membership != FixtureMembership.OFF_FIXTURE
        ]
        if not tags or not perception.slots:
            return result
        catalogue = {f.product.casefold() for f in definition.all_facings() if f.product} if definition else set()
        readings = getattr(perception, "ocr_readings", None) or {}
        reads = {i.shape_id: i for i in result.identifications}
        slot_of: Dict[str, Slot] = {}
        for slot in perception.slots:
            slot_of[slot.slot_id] = slot
            if slot.anchor_shape_id:
                slot_of.setdefault(slot.anchor_shape_id, slot)
        extra: Dict[str, List[str]] = {}
        for tag in tags:
            text = _tag_text(tag, readings, reads)
            slot = _slot_above(tag, perception.slots) if text else None
            if slot is not None:
                extra.setdefault(slot.slot_id, []).append(f"fact_tag | {text}")
        updated: List[Identification] = []
        for ident in result.identifications:
            slot = slot_of.get(ident.shape_id)
            lines = extra.get(slot.slot_id, []) if slot is not None else []
            known = (ident.product or "").casefold().strip() in catalogue
            if lines and ident.occupancy == "occupied" and not known:
                ident = ident.model_copy(update={"evidence": [*ident.evidence, *lines]})
            updated.append(ident)
        return result.model_copy(update={"identifications": updated})

    # _cycle_description: carry over product_on_shelves.py:785-797 VERBATIM here.
```
**Why**: replaces the legacy `_corroborate_products_with_fact_tags` (:2022-2129), which injected synthetic
`IdentifiedProduct`s — proof of an unseen product, forbidden by spec M6. Only observed, occupied reads are
enriched; resolution still happens (or not) inside `compare_observations`.

### `.../tests/planogram_cycle/test_pos_migrated_perceive_identify.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -Fxc 'class _InlineExecutor:' test_pos_migrated_perceive_identify.py -> :25)
# REPLACE tests :83-108 (test_default_perception_mode_is_llm_detector, test_invalid_perception_mode_raises,
#   test_fallback_prompt_is_deterministic_and_lists_hints, test_shape_profiles_cover_four_kinds) with the
#   profile tests in Test Specification. In test_perceive_llm_detector_mode (:111) build the handler with
#   _make_handler({"perception_mode": "llm_detector"}) (explicit diagnostic mode; default is now cv).
# In test_perceive_cv_mode_uses_executor_not_event_loop (:136) use _make_handler({}) and assert
#   executor.dispatched is non-empty (the shared stage may dispatch module-level wrappers with other names).
```

### `.../tests/planogram_cycle/test_pos_migrated_compare.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -Fxc '"""Offline tests for ProductOnShelves.compare and rule evaluation (FEAT-574, TASK-3446)."""' -> :1)
# REPLACE line 1 with '"""Offline tests for ProductOnShelves.compare: evidence-only rules and fact-tag corroboration (FEAT-612)."""'
# DELETE _set_context (:126-133) and the tests that call removed private helpers:
#   test_illumination_mismatch_sets_penalty, test_illumination_unknown_is_unassessed, test_text_rule_score_and_mandatory,
#   test_visual_rule_uses_calculate_visual_feature_match, test_zone_present_uncertain_membership_is_unassessed,
#   test_rule_exception_is_isolated (per-rule logic is now covered by TASK-3863's test_shared_comparison.py).
# REWRITE test_compare_zone_only_header_shelf_penalty_once to feed RuleObservation evidence (Test Specification).
# KEEP test_compare_inconclusive_is_not_compliant, test_compare_complete_and_compliant,
#   test_compare_ignores_off_fixture_observations, test_handler_is_a_full_cycle_type.
```

### FILL IN checklist
- [ ] Block B `_shelf_shape_profiles` — paste the four literals verbatim from `:286-338` before deleting them.
- [ ] Block C `_ensure_layout` — confirm TASK-3855's `resolve_layout_profile` takes the whole `planogram_config` (top-level `perception_mode` alias); adapt the argument if it takes the `layout_profile` sub-dict.
- [ ] Block D — carry `_cycle_description` over verbatim; run ruff to drop any unused import from Block A.
- [ ] Tests — implement bodies per Test Specification; confirm how TASK-3863 binds an observed zone to `zone_backlit` (unambiguous single zone vs `zone_selectors`) and configure the fixture accordingly.

---

## Acceptance Criteria

- [ ] `product_on_shelves.py` has no legacy method (`compute_roi`, `detect_objects_roi`, `detect_objects`, `check_planogram_compliance`, `get_grid_strategy`, `_detect_*`, `_find_poster`, …), no `grid` import and no `DEFAULT_PERCEPTION_MODE` (AC1, AC14).
- [ ] `default_layout_profile()` is fresh per call with the four existing profiles, `shape_is_slot`, `full_image`, `cv`, `min_usable_shapes=3` (spec §2; AC3, AC4).
- [ ] Top-level `planogram_config["perception_mode"]="llm_detector"` still selects the detector; an invalid value raises `ValueError` naming `perception_mode`.
- [ ] `compare` performs no vision call and never calls `_check_illumination`; header illumination is decided from `rule_observations` (AC8).
- [ ] Fact-tag text corroborates an occupied, uncatalogued slot read into a `match`; a fact tag under an empty/unread slot never produces an occupied facing (AC7).
- [ ] `fallback_detection_prompt()` returns `None` (no expected product names in prompts; AC7).
- [ ] Validation Commands pass; `ruff check` and `black --check --line-length 120` clean.
- [ ] Lint/format clean: `ruff check packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_pos_migrated_perceive_identify.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_pos_migrated_compare.py`
- [ ] Lint/format clean: `black --check --line-length 120 packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_pos_migrated_perceive_identify.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_pos_migrated_compare.py`

## Validation Commands

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_pos_migrated_perceive_identify.py -q`
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_pos_migrated_compare.py -q`

---

## Test Specification

```python
# test_pos_migrated_perceive_identify.py (profile section; reuse _make_handler, _ctx, _InlineExecutor)
from parrot_pipelines.planogram.contracts import IdentifyStrategy
from parrot_pipelines.planogram.perception.slots import AnchorRule


def test_default_layout_profile_is_cv_and_fresh():
    first, second = ProductOnShelves.default_layout_profile(), ProductOnShelves.default_layout_profile()
    assert first is not second and first.shape_profiles[0] is not second.shape_profiles[0]
    assert {p.kind for p in first.shape_profiles} == {"product", "box", "fact_tag", "zone"}
    assert first.perception_mode == "cv" and first.anchor_rule == AnchorRule.SHAPE_IS_SLOT
    assert first.identify_strategy == IdentifyStrategy.FULL_IMAGE and first.min_usable_shapes == 3
    assert ProductOnShelves.requires_slots_definition is True and ProductOnShelves.uses_enhanced_image is False
    assert not hasattr(ProductOnShelves, "DEFAULT_PERCEPTION_MODE")


def test_top_level_perception_mode_alias_and_invalid_value():
    ctx = _ctx()
    assert _make_handler({"perception_mode": "llm_detector"})._ensure_layout(ctx).perception_mode == "llm_detector"
    with pytest.raises(ValueError, match="perception_mode"):
        _make_handler({"perception_mode": "yolo"})._ensure_layout(_ctx())


def test_no_product_hint_fallback_prompt_and_no_legacy_hooks():
    handler = _make_handler({})
    assert handler.fallback_detection_prompt() is None
    assert not any(handler._implements(n) for n in ("compute_roi", "detect_objects", "check_planogram_compliance"))


def test_module_imports_no_grid_execution():
    import inspect
    import parrot_pipelines.planogram.types.product_on_shelves as module
    assert "planogram.grid" not in inspect.getsource(module)


# test_pos_migrated_compare.py (rewritten parts; reuse _definition, _perception, _identifications, _zone, _ctx)
from parrot_pipelines.planogram.contracts import ObservationSource, RuleObservation


class _RaisingVision:
    def __getattr__(self, name):
        raise AssertionError(f"compare must not touch vision ({name})")


async def test_compare_header_illumination_from_evidence_penalty_once(handler):
    # FILL IN: ctx = _ctx(definition, bindings[zone_present + illumination required on, penalty 0.5]); ctx.vision = _RaisingVision();
    #   idents = _identifications().model_copy(update={"rule_observations": [RuleObservation(image_id="img0",
    #       target_id="img0:zone", kind="illumination", value="off", assessed=True, source=ObservationSource.LLM)]})
    #   result = await handler.compare([_perception(_zone())], [idents], ctx)
    #   assert header.lenient_score == pytest.approx(0.5); header compliance non_compliant; overall_compliant False


async def test_compare_unknown_illumination_is_inconclusive(handler):
    # FILL IN: same binding, observation assessed=False -> result.assessment_status == INCONCLUSIVE, overall_compliant False


async def test_fact_tag_corroborates_occupied_unresolved_slot(handler):
    # FILL IN: perception with a FACT_TAG shape (ocr_text="ES-100") just below slot img0:r0:s1; identification for
    #   img0:r0:s1 occupancy="occupied", product="scanner", brand="Acme" -> position top_f1 status MATCH;
    #   the returned identification's raw_confidence and occupancy are unchanged.


async def test_fact_tag_never_creates_unseen_product(handler):
    # FILL IN: FACT_TAG "ES-200" below slot img0:r0:s2 but NO identification for that slot (or occupancy "empty")
    #   -> top_f2 status is not MATCH and result.detected_products does not count it.
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
9. **Close the task** with `scripts/sdd/close_task.sh TASK-3865 refactor-planogram-compliance verified`
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
