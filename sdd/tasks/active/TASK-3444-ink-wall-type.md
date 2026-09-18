# TASK-3444: InkWall type, registry/exports and developer doc

**Feature**: FEAT-574 — New Planogram Compliance Pipeline
**Spec**: `sdd/specs/new-planogram-pipeline.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3433, TASK-3438, TASK-3441, TASK-3443
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 16** (+ **Module 22**, folded in — spec revision 0.2). Today
`planogram_type="ink_wall"` is accepted by `PlanogramConfig` but raises
`ValueError` in `PlanogramCompliance.__init__` (`plan.py:66-68`): there is no
`InkWall` class, and a dense wall (102 products, 104 facings, 6 shelves) does not
fit `PlanogramDescription`. This task adds the first **fully migrated** type: a
price-tag-anchored composition of the building blocks delivered by the
dependency tasks — `PRICE_TAG_PROFILE` → tag rows → slots above tags (gap-filled
+ untagged bottom row) → `STRIPS` identification → descriptor identity
(`family / xl / colors / pack`, identifiers, aliases) → registration, scoring
and projection. It implements **none** of the legacy methods and requires a
slots definition.

It also owns the wiring: type export, `_PLANOGRAM_TYPES["ink_wall"]`, the lazy
package export, `PIPELINE_REGISTRY` (which is also missing three existing types),
and the developer doc "adding a planogram type".

Algorithmic reference for identity (read, never import):
`examples/planogram/plancheck/reference.py:255` (`resolve_identity`: identifier →
descriptor signature → alias, never using planogram expectations).

---

## Scope

- Create `InkWall(AbstractPlanogramType)` with the class attributes and the three
  hooks of the spec skeleton, and module-level `resolve_identity`.
- `perceive`: BGR array from the **untouched** image → `propose_shapes` with
  `PRICE_TAG_PROFILE` through `ctx.executor` → `group_rows` → `build_slots`
  (`AnchorRule.TAG_BELOW_PRODUCT`, `fill_gaps=True`, `untagged_bottom_row=True`)
  → tag OCR through `ctx.executor.run(read_crop, crop)` when
  `ctx.ocr.available` → `assign_membership` → `PerceptionResult`
  (`detection_source` = the CV source value, `ocr_available` from `ctx.ocr`).
- `identify`: `identify_strips(...)` with the descriptor vocabulary of the
  definition; optional closed-set pass `verify_unresolved(...)` when
  `planogram_config.get("verify_pass")` is truthy.
- `compare`: canonicalise every identification with `resolve_identity` (sets
  `Identification.product` to the definition's product id, or leaves it
  unresolved with candidates in `descriptors["candidates"]`), register each
  image, `merge_positions` → `score_shelves` → `summarize` →
  `project_compliance` → `finalize_comparison`. Optional **price compliance**
  when the facing's descriptors carry `price`: recorded as a note on the
  `PositionResult`, never changing a credit.
- `resolve_identity` rules, in order, **never using the expected facing**:
  (1) exact identifier present in the read text; (2) descriptor signature
  `family` (+ `colors`, `pack`, `xl`) — a signature match with `xl` unknown is
  only a candidate, never a resolution; (3) alias via
  `rapidfuzz.fuzz.token_set_ratio ≥ 92`. Several matches ⇒ `(None, candidates)`.
- Wiring: export in `types/__init__.py`; `"ink_wall": InkWall` in
  `_PLANOGRAM_TYPES`; lazy `InkWall` export in `planogram/__init__.py`;
  `PIPELINE_REGISTRY` gains `InkWall`, `ProductCounter`,
  `EndcapNoShelvesPromotional`, `EndcapBacklitMultitier`.
- Write `docs/pipelines/planogram-compliance-cycle.md` (the three stages, the
  hook contract, "adding a planogram type" = shape profile + anchoring rule +
  descriptor vocabulary, result keys, `ai-parrot-pipelines[planogram]` extra).
- Offline end-to-end test on a synthetic wall with the fake vision client.

**NOT in scope**: migrating any other type; the perception/identification/
comparison blocks themselves; the handler; config conversion tooling and its
runbook; benchmark; descriptor proposal utility.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/ink_wall.py` | CREATE | `InkWall` type + `resolve_identity` |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/__init__.py` | MODIFY | Export `InkWall` |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py` | MODIFY | Import `InkWall`; `_PLANOGRAM_TYPES["ink_wall"]` |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/__init__.py` | MODIFY | Lazy export of `InkWall` |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/__init__.py` | MODIFY | `PIPELINE_REGISTRY` additions (4 entries) |
| `docs/pipelines/planogram-compliance-cycle.md` | CREATE | Developer doc |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_ink_wall.py` | CREATE | Identity unit tests + synthetic end-to-end |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from PIL import Image
import numpy as np                                   # declared directly by the packaging task (TASK-3428)
from rapidfuzz import fuzz                           # idem; reference usage: examples/planogram/plancheck/reference.py:14
from parrot.models.detections import (AisleConfig, DetectionBox, PlanogramDescription)   # verified: detections.py:356, :37, :364
from .abstract import AbstractPlanogramType          # verified: types/abstract.py:30 (hooks added by TASK-3442)
# Created by dependencies (re-verify once merged):
from ..contracts import (ComparisonResult, CycleContext, FixtureMembership, Identification, IdentificationResult,
                         IdentifyStrategy, ObservationSource, PerceptionResult, Shape, ShapeKind)   # TASK-3421
from ..perception.profiles import PRICE_TAG_PROFILE                                          # TASK-3418
from ..perception.shapes import propose_shapes                                               # TASK-3418
from ..perception.rows import group_rows                                                     # TASK-3433
from ..perception.slots import AnchorRule, build_slots                                       # TASK-3433
from ..perception.ocr import read_crop                                                       # TASK-3428
from ..perception.membership import assign_membership                                        # TASK-3437
from ..identification.identify import identify_strips                                        # TASK-3438
from ..identification.verify import verify_unresolved                                        # TASK-3439
from ..comparison.definition import FacingDefinition, SlotsDefinition                        # TASK-3435
from ..comparison.registration import register_image                                         # TASK-3440
from ..comparison.scoring import merge_positions, score_shelves, summarize                   # TASK-3441
from ..comparison.projection import finalize_comparison, project_compliance                  # TASK-3441
```

### Existing Signatures to Use
```python
# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/__init__.py  (16 lines, eager imports)
from .endcap_backlit_multitier import EndcapBacklitMultitier      # :7
__all__ = (..., "EndcapBacklitMultitier",)                        # :9-16

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py
from .types import (ProductOnShelves, GraphicPanelDisplay, ProductCounter,
                    EndcapNoShelvesPromotional, EndcapBacklitMultitier,)          # :15-21
    _PLANOGRAM_TYPES = {... "endcap_backlit_multitier": EndcapBacklitMultitier,}  # :37-43 (last entry :42)

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/__init__.py  (22 lines)
__all__ = ("PlanogramCompliancePipeline", "RetailDetector", "PlanogramCompliance", "AbstractPlanogramType",)  # :4-9
def __getattr__(name: str):                                       # :12-22
    if name == "AbstractPlanogramType":                           # :19
        mod = import_module('.types', __name__)                   # :20
        return getattr(mod, name)                                 # :21
    raise AttributeError(name)                                    # :22

# packages/ai-parrot-pipelines/src/parrot_pipelines/__init__.py  (17 lines)
PIPELINE_REGISTRY: dict[str, str] = {                             # :4-15  value = dotted path to the class
    "ProductOnShelves": "parrot_pipelines.planogram.types.product_on_shelves.ProductOnShelves",        # :13
    "GraphicPanelDisplay": "parrot_pipelines.planogram.types.graphic_panel_display.GraphicPanelDisplay",  # :14
}
# existing modules of the three missing types (verified present in planogram/types/):
#   product_counter.py -> ProductCounter; endcap_no_shelves_promotional.py -> EndcapNoShelvesPromotional;
#   endcap_backlit_multitier.py -> EndcapBacklitMultitier

# packages/ai-parrot/src/parrot/models/detections.py
class AisleConfig(BaseModel):          # :356-361  name: str (required)
class PlanogramDescription(BaseModel): # :364-407  REQUIRED: brand :369, category :370, aisle :371, shelves :380
# packages/ai-parrot-pipelines/src/parrot_pipelines/models.py
class PlanogramConfig(BaseModel):      # planogram_config: Dict[str, Any]; get_planogram_description() -> PlanogramDescription :102-108

# ---- Created by TASK-3442 (dependency) — planogram/types/abstract.py ----
class AbstractPlanogramType(ABC):
    def __init__(self, pipeline: "PlanogramCompliance", config: "PlanogramConfig") -> None   # sets pipeline, config, logger
    identify_strategy / requires_slots_definition / min_usable_shapes / uses_enhanced_image   # ClassVars
    async def perceive(self, image: Image.Image, image_id: str, ctx: CycleContext) -> PerceptionResult
    async def identify(self, image: Image.Image, perception: PerceptionResult, ctx: CycleContext) -> IdentificationResult
    async def compare(self, perceptions: Sequence[PerceptionResult],
                      identifications: Sequence[IdentificationResult], ctx: CycleContext) -> ComparisonResult

# ---- Building blocks (dependency tasks; signatures from the spec skeletons) ----
def propose_shapes(image: np.ndarray, profiles: Sequence[ShapeProfile], *, work_width: int = 2048) -> List[ShapeCandidate]
class ShapeCandidate(BaseModel):  # profile, kind, x1, y1, x2, y2, score
def group_rows(candidates, image_width: int, *, min_row_items: int = 4, max_slope: float = 0.12) -> List[List[ShapeCandidate]]
def build_slots(rows, image_size: Tuple[int, int], *, image_id: str, rule: AnchorRule, fill_gaps: bool = True,
                untagged_bottom_row: bool = False) -> List[Slot]
def read_crop(crop: np.ndarray) -> Tuple[str, float]                   # module-level, picklable
def assign_membership(shapes, zones, image_size, *, llm_hints=None) -> List[Shape]
async def identify_strips(image: np.ndarray, perception: PerceptionResult, ctx: CycleContext, *,
                          vocabulary: Sequence[str], marks: bool = True, substrip_max_slots: int = 8) -> IdentificationResult
async def verify_unresolved(image: np.ndarray, identifications: List[Identification], definition: SlotsDefinition,
                            ctx: CycleContext, *, n_distractors: int = 3) -> List[Identification]
def register_image(image_id, slots, identifications, definition) -> ImageRegistration
def merge_positions(definition, registrations, identifications, policy) -> List[PositionResult]
def score_shelves(positions, definition, bindings, rule_outcomes, description, policy) -> List[ShelfScore]
def summarize(shelf_scores, positions, definition, weights) -> ComparisonResult
def project_compliance(shelf_scores, positions, definition, description) -> List[ComplianceResult]
def finalize_comparison(comparison, compliance_results) -> ComparisonResult
class CpuExecutor:  async def run(self, fn, *args)      # positional args only; fn module-level and picklable
class Shape(BaseModel):  # shape_id, image_id, kind, box: DetectionBox, profile, row_index, slot_index, ocr_text,
                         # ocr_confidence, source, membership, membership_evidence
class Descriptors(BaseModel):  # display_name, family, xl, colors, pack, identifiers, aliases, price (all optional)
```
Dependency field **types** are fixed by their tasks — open each module before coding.

### Does NOT Exist
- ~~`InkWall` / `ink_wall` module~~ — this task creates it.
- ~~`InkWallAnalysis`~~ — a name in an unrelated docstring, never defined; do not reference it.
- ~~`InkWall.compute_roi` / `detect_objects` / `check_planogram_compliance`~~ — InkWall implements **none** of the legacy methods (the base raises `NotImplementedError` for them).
- ~~`plancheck` as an importable package; a `Catalog` object~~ — descriptors live on `FacingDefinition.descriptors`.
- ~~`CLOSEOUT` sentinel, `$` price regex constants~~ — reference-engine details; not ported unless the FILL IN for price notes needs a regex, which must then live in this module.
- ~~`CpuExecutor.run(fn, **kwargs)`~~ — positional arguments only.
- ~~`PIPELINE_REGISTRY` values as classes~~ — values are dotted-path **strings**.
- ~~A valid `PlanogramDescription` inside every ink-wall `planogram_config`~~ — it may lack `brand`/`category`/`aisle`/`shelves`; build a minimal one (see blueprint).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/ink_wall.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/__init__.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/__init__.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-pipelines/src/parrot_pipelines/__init__.py",
      "action": "MODIFY"
    },
    {
      "path": "docs/pipelines/planogram-compliance-cycle.md",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_ink_wall.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py#AbstractPlanogramType",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py#PlanogramCompliance",
    "sym:packages/ai-parrot/src/parrot/models/detections.py#PlanogramDescription",
    "sym:packages/ai-parrot/src/parrot/models/detections.py#AisleConfig",
    "sym:packages/ai-parrot/src/parrot/models/detections.py#DetectionBox"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
A migrated type is **composition only**: no CV, OCR, prompt or scoring code is
written here — each hook wires building blocks. Hooks are `async`; CPU work goes
through `ctx.executor.run(module_level_fn, *args)` with `np.ndarray` arguments
(never PIL images or bound methods across the process boundary).

### Key Constraints
- **Shape ids**: build every CV `Shape.shape_id` with `candidate_shape_id(image_id, candidate)` from
  `parrot_pipelines.planogram.perception.slots` (TASK-3433) — *why*: `build_slots` fills `Slot.anchor_shape_id` with that
  exact id, and registration joins identifications to slots through it; a different id scheme silently breaks the join.
- BGR array: `np.asarray(image.convert("RGB"))[:, :, ::-1].copy()`.
- Only `on_fixture` slots/shapes go to `register_image`; everything else stays in
  the audit output (`PerceptionResult.shapes`).
- A perception produced by the LLM-detector fallback has `slots == []`: treat
  every on-fixture shape as its own slot by building slots with
  `AnchorRule.SHAPE_IS_SLOT` from single-shape rows (`compare` must cope).
- `raw_confidence` is never modified. Identity canonicalisation copies the
  identification (`model_copy(update=...)`), it does not mutate input lists.
- `resolve_identity` never receives nor reads the expected facing of the slot.
- Ink-wall `planogram_config` may not describe shelves: `_description()` tries
  `self.config.get_planogram_description()` and falls back to a minimal
  `PlanogramDescription(brand=…, category="ink", aisle=AisleConfig(name="ink"), shelves=[])`.
- Price compliance is a **note** (`PositionResult.notes`), never a credit change.
- Tests run with `PYTHONPATH=packages/ai-parrot-pipelines/src:packages/ai-parrot/src`.
- The repository is public: the test wall and definition are synthetic; never
  copy content of the git-ignored ink-wall JSON.

### References in Codebase
- `examples/planogram/plancheck/reference.py:255-310` — identity rules to re-implement
- `packages/ai-parrot-pipelines/tests/conftest.py` — `fake_vision_client`
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py` — hook defaults being overridden

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Never change a
> signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Read every dependency module named in the contract and confirm signatures/field names — *why*: this blueprint copied them from the spec skeletons, not from merged code.
2. Write `resolve_identity` and its unit tests first — *why*: it is pure, and scoring only works if `Identification.product` is canonical.
3. Write the three hooks — *why*: they are thin compositions once identity works.
4. Apply the four wiring edits — *why*: until `_PLANOGRAM_TYPES` has the key, `planogram_type="ink_wall"` still raises `ValueError`.
5. Write the synthetic end-to-end test, then the doc — *why*: the doc describes behaviour the test proves.

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/ink_wall.py` (CREATE) — part 1
```python
"""InkWall — price-tag anchored planogram type for dense walls (FEAT-574)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
from PIL import Image
from rapidfuzz import fuzz

from parrot.models.detections import AisleConfig, DetectionBox, PlanogramDescription

from .abstract import AbstractPlanogramType
from ..contracts import (
    ComparisonResult, CycleContext, FixtureMembership, Identification, IdentificationResult,
    IdentifyStrategy, ObservationSource, PerceptionResult, Shape, ShapeKind,
)
from ..comparison.definition import FacingDefinition, SlotsDefinition
from ..comparison.projection import finalize_comparison, project_compliance
from ..comparison.registration import register_image
from ..comparison.scoring import merge_positions, score_shelves, summarize
from ..identification.identify import identify_strips
from ..identification.verify import verify_unresolved
from ..perception.membership import assign_membership
from ..perception.ocr import read_crop
from ..perception.profiles import PRICE_TAG_PROFILE
from ..perception.rows import group_rows
from ..perception.shapes import propose_shapes
from ..perception.slots import AnchorRule, build_slots

ALIAS_MIN_RATIO = 92.0


def _norm(text: Optional[str]) -> str:
    return text.casefold().strip() if text else ""


def resolve_identity(identification: Identification, definition: SlotsDefinition
                     ) -> Tuple[Optional[str], List[str]]:
    """(facing product id or None, candidate ids). Reference: plancheck/reference.py:255.

    Rules in order — identifier, descriptor signature, alias. Never uses the expected facing of the slot.
    Several matches => (None, candidates); nothing => (None, []).
    """
    facings: List[FacingDefinition] = [f for s in definition.shelves for f in s.facings]
    brand = _norm(identification.brand)
    pool = [f for f in facings if not brand or _norm(f.brand) == brand]
    # FILL IN: rule 1 (normalised identifier equals a line of identification.text / evidence);
    #   rule 2 (descriptors.family equal; colors/pack/xl must not contradict; `xl` unknown => candidates only);
    #   rule 3 (fuzz.token_set_ratio(alias, text line) >= ALIAS_MIN_RATIO) — bounded by AC-3; dedupe product ids
    #   preserving definition order; an unknown brand returns (None, []).
    raise NotImplementedError


def _to_bgr(image: Image.Image) -> np.ndarray:
    """Untouched full-resolution PIL image -> contiguous BGR array."""
    return np.asarray(image.convert("RGB"))[:, :, ::-1].copy()
```
**Why this shape**: `resolve_identity`'s signature is the spec Module 16 skeleton. Filtering the pool by brand
first mirrors the reference and keeps a wrong-brand alias from resolving.

### `ink_wall.py` (CREATE) — part 2: the type
```python
class InkWall(AbstractPlanogramType):
    """Price-tag anchored type: tags -> rows -> slots above tags -> strips -> descriptor identity."""

    identify_strategy = IdentifyStrategy.STRIPS
    requires_slots_definition = True
    min_usable_shapes = 8
    uses_enhanced_image = False

    async def perceive(self, image: Image.Image, image_id: str, ctx: CycleContext) -> PerceptionResult:
        """Deterministic stage: price tags, rows, slots, tag OCR, fixture membership."""
        bgr = _to_bgr(image)
        size = (image.width, image.height)
        candidates = await ctx.executor.run(propose_shapes, bgr, [PRICE_TAG_PROFILE])
        rows = group_rows(candidates, image.width)
        slots = build_slots(rows, size, image_id=image_id, rule=AnchorRule.TAG_BELOW_PRODUCT,
                            fill_gaps=True, untagged_bottom_row=True)
        shapes: List[Shape] = []
        # FILL IN: one Shape per candidate (shape_id f"{image_id}:tag:{n}", kind=ShapeKind.PRICE_TAG, source CV,
        #   box=DetectionBox(..., confidence=candidate.score clipped to 0..1), row_index/slot_index from `rows`);
        #   when ctx.ocr.available: text, conf = await ctx.executor.run(read_crop, bgr[y1:y2, x1:x2]) per tag
        #   (bounded concurrency: gather in chunks of 16) — bounded by AC-1; slot.anchor_shape_id must equal the
        #   shape_id of its tag (check how build_slots derives it; rebuild ids if it uses its own scheme).
        shapes = assign_membership(shapes, [], size)
        self.logger.info("InkWall %s: %d tags, %d rows, %d slots", image_id, len(shapes), len(rows), len(slots))
        # FILL IN: return PerceptionResult(image_id, image_size=size, shapes, slots, zones=[], row_count=len(rows),
        #   detection_source=<cv value>, ocr_available=bool(ctx.ocr.available), legacy=None, errors=[])
        raise NotImplementedError

    async def identify(self, image: Image.Image, perception: PerceptionResult,
                       ctx: CycleContext) -> IdentificationResult:
        """LLM stage: one call per row strip (Set-of-Marks), optional closed-set verification."""
        bgr = _to_bgr(image)
        result = await identify_strips(bgr, perception, ctx, vocabulary=self._vocabulary(ctx.definition))
        if self.config.planogram_config.get("verify_pass"):
            # FILL IN: verified = await verify_unresolved(bgr, list(result.identifications), ctx.definition, ctx);
            #   return result.model_copy(update={"identifications": verified}) — bounded by: an offered expected SKU
            #   is never evidence by itself (the verify module enforces it; do not add logic here).
            pass
        return result

    async def compare(self, perceptions: Sequence[PerceptionResult],
                      identifications: Sequence[IdentificationResult], ctx: CycleContext) -> ComparisonResult:
        """Deterministic stage: identity -> registration per image -> merge -> scores -> projection."""
        definition: SlotsDefinition = ctx.definition
        description = self._description()
        canonical: List[Identification] = []
        registrations = []
        for perception, ident_result in zip(perceptions, identifications):
            idents = [self._canonicalise(i, definition) for i in ident_result.identifications]
            # FILL IN: on-fixture slots only (join slot -> tag shape membership); fallback perception with
            #   slots == [] => build SHAPE_IS_SLOT slots from on-fixture shapes — bounded by AC-4.
            slots = list(perception.slots)
            registrations.append(register_image(perception.image_id, slots, idents, definition))
            canonical.extend(idents)
        positions = merge_positions(definition, registrations, canonical, ctx.credit_policy)
        # FILL IN: price notes — when a facing's descriptors.price is set and the tag OCR text of its slot parses
        #   to a different amount, append a note to that PositionResult; never touch credits — bounded by AC-5.
        shelves = score_shelves(positions, definition, ctx.bindings, {}, description, ctx.credit_policy)
        comparison = summarize(shelves, positions, definition, ctx.evidence_weights)
        comparison = comparison.model_copy(update={"position_results": positions, "shelf_scores": shelves})
        return finalize_comparison(comparison, project_compliance(shelves, positions, definition, description))

    def _canonicalise(self, identification: Identification, definition: SlotsDefinition) -> Identification:
        """Copy with ``product`` set to the definition's product id, or unresolved with candidates recorded."""
        product, candidates = resolve_identity(identification, definition)
        descriptors = dict(identification.descriptors or {})
        descriptors["candidates"] = candidates
        return identification.model_copy(update={"product": product, "descriptors": descriptors})

    def _vocabulary(self, definition: Optional[SlotsDefinition]) -> List[str]:
        """Descriptor vocabulary offered to the LLM: brands and families of the definition (no SKU list)."""
        # FILL IN: sorted unique brand + descriptors.family values — bounded by: never the per-slot expectation.
        raise NotImplementedError

    def _description(self) -> PlanogramDescription:
        """PlanogramDescription for weights/thresholds; minimal fallback when the config has no shelves."""
        try:
            return self.config.get_planogram_description()
        except Exception as exc:  # ink-wall configs may omit the ProductOnShelves-shaped keys
            self.logger.debug("InkWall: minimal PlanogramDescription (%s)", exc)
            cfg = self.config.planogram_config or {}
            return PlanogramDescription(brand=str(cfg.get("brand", "")), category=str(cfg.get("category", "ink")),
                                        aisle=AisleConfig(name=str(cfg.get("aisle", "ink"))), shelves=[])
```
**Why**: class attributes are the spec skeleton (`STRIPS`, slots required, fallback under 8 usable shapes,
untouched image). `compare` passes `{}` rule outcomes: an ink wall has no non-product rules unless bindings
are configured, in which case unassessed mandatory rules correctly make the run inconclusive.

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from .endcap_backlit_multitier import EndcapBacklitMultitier' types/__init__.py)
# AFTER — insert below `from .endcap_backlit_multitier import EndcapBacklitMultitier` (verified: types/__init__.py:7)
from .ink_wall import InkWall

# occurrences: 1 (verified: grep -c '    "EndcapBacklitMultitier",' types/__init__.py)
# AFTER — insert below `    "EndcapBacklitMultitier",` (verified: types/__init__.py:15)
    "InkWall",
```
**Why**: eager export, same style as the other five types.

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    EndcapBacklitMultitier,' plan.py)
# AFTER — insert below `    EndcapBacklitMultitier,` in the `from .types import (` block (verified: plan.py:20)
    InkWall,

# occurrences: 1 (verified: grep -c '        "endcap_backlit_multitier": EndcapBacklitMultitier,' plan.py)
# AFTER — insert below `        "endcap_backlit_multitier": EndcapBacklitMultitier,` (verified: plan.py:42)
        "ink_wall": InkWall,
```
**Why**: the only two lines of `plan.py` this task touches; line numbers were verified before TASK-3429/3443
edited the file — re-locate by the quoted anchors, not by number.

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    "AbstractPlanogramType",' planogram/__init__.py)
# AFTER — insert below `    "AbstractPlanogramType",` inside __all__ (verified: planogram/__init__.py:8)
    "InkWall",

# occurrences: 1 (verified: grep -c '    raise AttributeError(name)' planogram/__init__.py)
# BEFORE — insert above `    raise AttributeError(name)` (verified: planogram/__init__.py:22)
    if name == "InkWall":
        mod = import_module('.types', __name__)
        return getattr(mod, name)
```
**Why**: same lazy `__getattr__` pattern as `AbstractPlanogramType` (:19-21) — importing the package must stay cheap.

### `packages/ai-parrot-pipelines/src/parrot_pipelines/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '"GraphicPanelDisplay"' parrot_pipelines/__init__.py)
# AFTER — insert below the `"GraphicPanelDisplay": "parrot_pipelines.planogram.types.graphic_panel_display.GraphicPanelDisplay",`
#         entry (verified: parrot_pipelines/__init__.py:14)
    "ProductCounter": "parrot_pipelines.planogram.types.product_counter.ProductCounter",
    "EndcapNoShelvesPromotional": "parrot_pipelines.planogram.types.endcap_no_shelves_promotional.EndcapNoShelvesPromotional",
    "EndcapBacklitMultitier": "parrot_pipelines.planogram.types.endcap_backlit_multitier.EndcapBacklitMultitier",
    "InkWall": "parrot_pipelines.planogram.types.ink_wall.InkWall",
```
**Why**: registry values are dotted-path strings; three existing types were missing (spec §6).

### `docs/pipelines/planogram-compliance-cycle.md` (CREATE)
```markdown
# Planogram compliance cycle (perceive → identify → compare)

## Overview
<!-- FILL IN: 3 short paragraphs — why the ROI-first cycle was replaced; the three stages; what is deterministic -->

## Stage contracts
<!-- FILL IN: table Stage | Hook | Input | Output | Runs where (event loop / CpuExecutor / LLM) -->

## Type hook contract
<!-- FILL IN: ClassVars (identify_strategy, requires_slots_definition, min_usable_shapes, uses_enhanced_image),
     legacy adapter defaults, validate_contract() rules -->

## Adding a planogram type
1. Shape profile(s) …  2. Anchoring rule …  3. Descriptor vocabulary …  4. Register it …
<!-- FILL IN: each step with a 5-10 line code sketch taken from InkWall — bounded by: real symbol names only -->

## Result keys
<!-- FILL IN: the 8 legacy keys + additive keys, one line each; compliance vs coverage vs evidence quality -->

## Optional local OCR
`pip install "ai-parrot-pipelines[planogram]"` — without it text is read by the LLM only and `ocr_available=False`.
```
**Why**: spec Module 22's developer doc; headings are fixed so other docs can link to them.

### `packages/ai-parrot-pipelines/tests/planogram_cycle/test_ink_wall.py` (CREATE)
```python
"""InkWall: identity rules and synthetic end-to-end (FEAT-574, Module 16)."""
from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from parrot_pipelines import PIPELINE_REGISTRY
from parrot_pipelines.models import PlanogramConfig
from parrot_pipelines.planogram.plan import PlanogramCompliance
from parrot_pipelines.planogram.types import InkWall
from parrot_pipelines.planogram.types.ink_wall import resolve_identity


@pytest.fixture
def synthetic_ink_wall() -> Image.Image:
    """Dark wall, 3 rows x 8 bright landscape labels, one gap, one untagged bottom row (spec §4 fixture)."""
    # FILL IN: draw with numpy/cv2 at ~2000x1400 so labels fall inside PRICE_TAG_PROFILE's size band.
    raise NotImplementedError


@pytest.fixture
def synthetic_slots_definition() -> dict:
    """3 shelves x 8 facings, stable ids, 20 described / 4 undescribed (spec §4 fixture)."""
    raise NotImplementedError  # FILL IN


def test_ink_wall_is_registered_everywhere(): ...
def test_ink_wall_requires_slots_definition(): ...
def test_resolve_identity_by_identifier(): ...
def test_resolve_identity_signature_without_xl_is_candidate_only(): ...
def test_resolve_identity_alias_fuzzy(): ...
def test_resolve_identity_unknown_brand_is_unresolved(): ...
def test_resolve_identity_never_reads_expected_facing(): ...
async def test_ink_wall_perceive_synthetic(synthetic_ink_wall, fake_vision_client): ...
async def test_ink_wall_end_to_end_synthetic(synthetic_ink_wall, synthetic_slots_definition, fake_vision_client): ...  # spec §4
async def test_ink_wall_price_note_does_not_change_credits(...): ...
```
**Why**: `test_ink_wall_end_to_end_synthetic` is named in spec §4; the identity tests pin the three rules.

### FILL IN checklist
- [ ] `ink_wall.py::resolve_identity` — three rules; bounded by AC-3
- [ ] `ink_wall.py::InkWall.perceive` — shapes + OCR + result; bounded by AC-1
- [ ] `ink_wall.py::InkWall.identify` — optional verification pass
- [ ] `ink_wall.py::InkWall.compare` — on-fixture slots / fallback slots; bounded by AC-4
- [ ] `ink_wall.py::InkWall.compare` — price notes; bounded by AC-5
- [ ] `ink_wall.py::InkWall._vocabulary` — brands + families only
- [ ] `planogram-compliance-cycle.md` — five sections
- [ ] `test_ink_wall.py` — two fixtures + ten test bodies

---

## Acceptance Criteria

- [ ] AC-1: `InkWall.perceive` works on the untouched image, runs CV/OCR through `ctx.executor`, and returns tags as shapes, rows, gap-filled slots and an untagged bottom row; `ocr_available` mirrors `ctx.ocr.available`.
- [ ] AC-2: `PlanogramCompliance(planogram_config=PlanogramConfig(planogram_type="ink_wall", …))` constructs; without a valid `slots_definition` it fails at construction with `ValueError`; `InkWall` implements no legacy method.
- [ ] AC-3: `resolve_identity` applies identifier → signature → alias, returns candidates on ambiguity, treats a signature match with unknown `xl` as candidate-only, and never reads the expected facing.
- [ ] AC-4: Only on-fixture observations are registered; a fallback perception (`slots == []`) still compares.
- [ ] AC-5: Price differences appear as `PositionResult` notes and change no credit or status.
- [ ] AC-6: The synthetic end-to-end run yields the eight legacy keys, `detection_source` of the CV path, one `ComplianceResult` per definition shelf, and the undescribed facings reduce `definition_coverage` below 1.0.
- [ ] AC-7: `from parrot_pipelines.planogram import InkWall` and `from parrot_pipelines.planogram.types import InkWall` work; `PIPELINE_REGISTRY` lists `InkWall`, `ProductCounter`, `EndcapNoShelvesPromotional`, `EndcapBacklitMultitier`, and every registry value imports.
- [ ] AC-8: `docs/pipelines/planogram-compliance-cycle.md` exists with the five sections filled.
- [ ] All tests pass: `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_ink_wall.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/ink_wall.py`

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_ink_wall.py -q`

---

## Test Specification

```python
def test_ink_wall_is_registered_everywhere():
    from importlib import import_module
    assert PlanogramCompliance._PLANOGRAM_TYPES["ink_wall"] is InkWall
    for name in ("InkWall", "ProductCounter", "EndcapNoShelvesPromotional", "EndcapBacklitMultitier"):
        module_path, cls = PIPELINE_REGISTRY[name].rsplit(".", 1)
        assert getattr(import_module(module_path), cls).__name__ == name
    import parrot_pipelines.planogram as pkg
    assert pkg.InkWall is InkWall


def test_ink_wall_requires_slots_definition():
    with pytest.raises(ValueError):
        PlanogramCompliance(planogram_config=PlanogramConfig(planogram_type="ink_wall", planogram_config={}))


def test_resolve_identity_signature_without_xl_is_candidate_only():
    """family+colors match exactly one facing but `xl` was not read => (None, [that id])."""
    ...


async def test_ink_wall_end_to_end_synthetic(synthetic_ink_wall, synthetic_slots_definition, fake_vision_client):
    """Fake LLM answers every strip with the expected identifiers => all described facings `match`."""
    ...
    assert {"compliance_results", "overall_compliance_score", "overall_compliant", "rendered_image"} <= set(result)
    assert len(result["compliance_results"]) == 3
    assert result["definition_coverage"] == pytest.approx(20 / 24)
    assert str(result["assessment_status"]).endswith("inconclusive")   # 4 undescribed facings stay unresolved
    assert result["overall_compliant"] is False
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-3444-ink-wall-type.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
