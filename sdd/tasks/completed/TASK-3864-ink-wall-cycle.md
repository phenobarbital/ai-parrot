# TASK-3864: Migrate InkWall to the shared profile-driven cycle

**Feature**: FEAT-612 — Refactor Planogram Compliance
**Spec**: `sdd/specs/refactor-planogram-compliance.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3856, TASK-3859, TASK-3863
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 5** and §2 "Type defaults and genuinely specific behavior" (ink_wall row).
`InkWall` is already a cycle type, but its three hooks re-implement perception (price tags →
rows → slots → tag OCR), identification (strips + vocabulary) and comparison (identity →
registration → merge → scoring → projection) inline. TASK-3856/3859/3863 extract those stages
into `planogram/stages/` (`perceive_image`, `identify_image`, `compare_observations`) and
TASK-3861 moves `resolve_identity` into `comparison/identity.py`. This task turns `InkWall`
into a thin composition: a fresh `default_layout_profile()` (price-tag profile, tag-below
anchors, gap fill, untagged bottom row, strips, threshold 8, min_row_items 4, ink vocabulary)
plus the only genuinely ink-specific behavior: `price_mismatch` notes and the optional
`verify_pass`. The historical import `parrot_pipelines.planogram.types.ink_wall.resolve_identity`
must keep working as an alias (spec §2 Stage 3: "preserve the old import as an alias").

---

## Scope

- Add `InkWall.default_layout_profile()` (classmethod) returning a NEW `LayoutProfile` with the
  ink defaults of spec §2 on every call (no shared mutable default).
- Replace `InkWall.perceive` with a composition of `perceive_image(image, image_id, ctx)`.
- Replace `InkWall.identify` with `identify_image(image, perception, ctx)` followed by the existing
  optional `verify_pass` (`planogram_config["verify_pass"]`, off by default).
- Replace `InkWall.compare` with `compare_observations(...)` over perceptions whose slots are
  pre-filtered by the retained `_registrable_slots`, then append `price_mismatch` notes.
- Rewrite `_price_notes` to read tag prices from `PositionResult.observations` and the perception's
  own-box tag OCR (`PerceptionResult.ocr_readings`, falling back to `Shape.ocr_text`).
- Delete the local `resolve_identity` body and its private helpers, and re-export
  `resolve_identity` from `..comparison.identity` so old imports still resolve.
- Delete `_read_tags`, `_canonicalise`, `_vocabulary`, `OCR_BATCH`, `ALIAS_MIN_RATIO`,
  `_VOCABULARY_FIELDS`, `_norm`, `_text_lines`, `_dedupe` (their work moved to shared stages).
- Add a private `_ensure_layout(ctx)` so hooks work before the orchestrator sets `ctx.layout`.
- Update `test_ink_wall.py` for the new contract and add default-profile / no-mutation tests.

**NOT in scope**:
- The shared stages themselves (TASK-3856 perceive, TASK-3857/3858/3859 identify, TASK-3861/3862/3863 compare).
- Editing `comparison/identity.py`, `identification/verify.py` (TASK-3861) or `plan.py` (TASK-3871: it
  will set `ctx.layout` and own fallback geometry rebuild).
- Removing class variables `identify_strategy` / `min_usable_shapes` / `uses_enhanced_image` /
  `requires_slots_definition` — `plan.py:220,248,263` still reads them until TASK-3870/3871.
- `product_on_shelves.py:45` still imports `resolve_identity` from `.ink_wall` — do not touch it
  (TASK-3865 owns that file); the alias keeps it working.
- Config migration (TASK-3877), docs (TASK-3880).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/ink_wall.py` | MODIFY | Thin cycle composition, default profile, alias, price notes |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_ink_wall.py` | MODIFY | Adapt to shared stages; profile and alias tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
# All relative to packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/ink_wall.py
from parrot.models.detections import AisleConfig, DetectionBox, PlanogramDescription  # ink_wall.py:14 (DetectionBox: detections.py:37)
from ..comparison.definition import SlotsDefinition                  # ink_wall.py:16; definition.py:98
from ..contracts import (ComparisonResult, CycleContext, FixtureMembership, Identification,
    IdentificationResult, IdentifyStrategy, PerceptionResult, PositionResult, Shape, Slot)  # ink_wall.py:20-33
from ..identification.verify import verify_unresolved                # ink_wall.py:35; verify.py:205
from ..perception.profiles import PRICE_TAG_PROFILE                  # ink_wall.py:38; profiles.py:65
from ..perception.slots import AnchorRule                            # ink_wall.py:41; slots.py:27
from .abstract import AbstractPlanogramType                          # ink_wall.py:42; abstract.py:36
```

### Existing Signatures to Use
```python
# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/ink_wall.py (current, 421 lines)
_PRICE = re.compile(r"(\d+)[.,](\d{2})")                               # :47  KEEP
def resolve_identity(identification, definition) -> Tuple[Optional[str], List[str]]   # :74-146  DELETE body -> alias
def _to_bgr(image: Image.Image) -> np.ndarray                         # :149-151 KEEP (verify_pass needs BGR)
def _parse_price(text: Optional[str]) -> Optional[float]              # :154-157 KEEP
class InkWall(AbstractPlanogramType):                                 # :160
    identify_strategy = IdentifyStrategy.STRIPS                       # :163 KEEP (plan.py still reads classvars)
    requires_slots_definition = True                                  # :164 KEEP
    min_usable_shapes = 8                                             # :165 KEEP (plan.py:263 fallback threshold)
    uses_enhanced_image = False                                       # :166 KEEP (plan.py:248)
    async def perceive(self, image, image_id, ctx) -> PerceptionResult          # :168-227 REPLACE
    async def _read_tags(self, bgr, shapes, ctx) -> List[Shape]                 # :229-239 DELETE
    async def identify(self, image, perception, ctx) -> IdentificationResult    # :241-261 REPLACE (keep verify_pass lines 256-260 semantics)
    async def compare(self, perceptions, identifications, ctx) -> ComparisonResult  # :263-298 REPLACE
    def _registrable_slots(self, perception, idents) -> List[Slot]             # :300-321 KEEP unchanged
    @staticmethod
    def _fallback_slots(perception) -> List[Slot]                              # :323-353 KEEP unchanged
    @staticmethod
    def _price_notes(positions, definition, perceptions, registrations, slots_by_image) -> List[PositionResult]  # :355-389 REWRITE
    def _canonicalise(self, identification, definition) -> Identification     # :391-396 DELETE
    def _vocabulary(self, definition) -> List[str]                             # :398-407 DELETE
    def _description(self) -> PlanogramDescription                             # :409-421 KEEP unchanged

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py
class AbstractPlanogramType(ABC):                                     # :36
    def __init__(self, pipeline, config) -> None                      # :63  sets self.pipeline, self.config, self.logger
    def _implements(self, name: str) -> bool                          # :463

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/verify.py:205
async def verify_unresolved(image: np.ndarray, identifications: List[Identification], definition: SlotsDefinition,
                            ctx: CycleContext, *, n_distractors: int = 3,
                            boxes: Optional[Dict[str, DetectionBox]] = None) -> List[Identification]

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py
class ObservationRef(BaseModel): image_id: str; shape_id: str; source; raw_confidence; product; occupancy   # :169
class PositionResult(BaseModel): facing_id, shelf_id, status, strict_credit, lenient_credit, identity,
                                 observations: List[ObservationRef], notes: List[str]                        # :191
class CycleContext(BaseModel): vision, executor, ocr, definition, bindings, credit_policy, evidence_weights,
                               output_dir, errors                                                            # :322
# comparison/scoring.py:147 merge_positions puts EVERY registered view of a facing in PositionResult.observations
# (deciding view first); projection.py never reads PositionResult.notes -> notes never change compliance.

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py (transitional facts)
#   :220 handler.requires_slots_definition ; :248 handler.uses_enhanced_image ; :263 handler.min_usable_shapes
#   :231 CycleContext(...) is built WITHOUT a layout until TASK-3871
#   :279 fallback currently returns slots=[]  -> _fallback_slots stays needed until TASK-3871 lands
```

#### Symbols created by dependency tasks (not yet on dev)
```python
# TASK-3854 — planogram/contracts.py additions
IdentifyStrategy.SLOTS = "slots"
class OcrReading(BaseModel): text: str = ""; confidence: float = 0.0
PerceptionResult.ocr_readings: dict[str, OcrReading]          # keyed by observed target id (shape_id / slot_id)
CycleContext.layout: Any = None                               # validated LayoutProfile
IdentificationResult.rule_observations: list[RuleObservation]

# TASK-3855 — planogram/layout.py
class LayoutProfile(BaseModel):  # extra="forbid"
    shape_profiles: list[ShapeProfile]; anchor_rule: AnchorRule = AnchorRule.SHAPE_IS_SLOT
    fill_gaps: bool = False; untagged_bottom_row: bool = False
    identify_strategy: IdentifyStrategy = IdentifyStrategy.FULL_IMAGE
    perception_mode: Literal["cv", "llm_detector"] = "cv"; min_usable_shapes: int = 1
    min_row_items: int = 1; max_row_slope: float = 0.12; work_width: int = 2048
    substrip_max_slots: int = 8; ocr_batch_size: int = 16
    descriptor_fields: list[str]; required_descriptor_fields: list[str]
    ocr_targets: list[Literal["slot", "tag", "zone"]]; references: ReferencePolicy; zone_selectors: list[ZoneSelector]
def resolve_layout_profile(defaults: LayoutProfile, config: dict[str, Any], *, config_name: str) -> LayoutProfile

# TASK-3856 — planogram/stages/perceive.py
async def perceive_image(image: Image.Image, image_id: str, ctx: CycleContext) -> PerceptionResult

# TASK-3859 — planogram/stages/identify.py
async def identify_image(image: Image.Image, perception: PerceptionResult, ctx: CycleContext) -> IdentificationResult

# TASK-3861 — planogram/comparison/identity.py
def resolve_identity(identification: Identification, definition: SlotsDefinition, *,
                     vocabulary: Sequence[str] = ("family", "colors", "pack", "xl"),
                     required_fields: Sequence[str] = ("family", "xl")) -> tuple[str | None, list[str]]

# TASK-3863 — planogram/stages/compare.py
def compare_observations(perceptions: Sequence[PerceptionResult], identifications: Sequence[IdentificationResult],
                         ctx: CycleContext, description: PlanogramDescription) -> ComparisonResult
```

### Does NOT Exist
- ~~`InkWall.default_layout_profile`~~ — this task adds it.
- ~~`CycleContext.layout` set by `plan.py`~~ — not until TASK-3871; hooks must resolve it themselves meanwhile.
- ~~`ImageRegistration` inside `ComparisonResult`~~ — `compare_observations` returns no registrations; price
  notes must use `PositionResult.observations` instead.
- ~~`compare_observations(..., slots=...)` / a type hook parameter~~ — the only way to restrict registered slots
  is to pass perceptions whose `slots` were already filtered.
- ~~`LayoutProfile.vocabulary`~~ — the field is `descriptor_fields`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/ink_wall.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_ink_wall.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/ink_wall.py#InkWall",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/ink_wall.py#InkWall.perceive",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/ink_wall.py#InkWall.identify",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/ink_wall.py#InkWall.compare",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/ink_wall.py#InkWall._registrable_slots",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/ink_wall.py#InkWall._fallback_slots",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/ink_wall.py#InkWall._price_notes",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/ink_wall.py#InkWall._description",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/ink_wall.py#resolve_identity",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/ink_wall.py#_parse_price",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/ink_wall.py#_to_bgr",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/verify.py#verify_unresolved",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py#AbstractPlanogramType",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py#ObservationRef",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py#PositionResult",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py#CycleContext",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/profiles.py#PRICE_TAG_PROFILE",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/slots.py#AnchorRule"
  ]
}
```

---

## Implementation Notes

### Planner cross-task notes (added at /sdd-task time)
- `test_ink_wall.py:171` reads `InkWall._LEGACY_CONTRACT`; TASK-3870 deletes that attribute and no later task owns this test file — remove that assertion here (replace it with a check that the three cycle hooks and `default_layout_profile` are defined on `InkWall`).


### Pattern to Follow
- Composition, not orchestration: each hook is "ensure layout → call one shared stage → apply the
  ink-only post-step". The shared stages read everything else (profiles, anchor rule, strategy,
  OCR targets, vocabulary) from `ctx.layout` (spec §7 "stage modules are implementation helpers").
- `_registrable_slots` stays the ink-specific slot filter (on-fixture tag rows with evidence, plus the
  untagged row just below the last tag row). Apply it by handing `compare_observations` perceptions
  whose `slots` were replaced: `perception.model_copy(update={"slots": kept})`. Never mutate the input.
- Price notes are informational: they are appended after scoring and never change a credit
  (`test_ink_wall_price_note_does_not_change_credits` pins this).

### Key Constraints
- `default_layout_profile()` must build a new object each call and deep-copy `PRICE_TAG_PROFILE`
  (`model_copy(deep=True)`) — spec §2 forbids shared mutable defaults and class-default mutation.
- No retailer product names, SKU codes or expected counts anywhere in the type (AC3).
- `_ensure_layout` resolves `resolve_layout_profile(self.default_layout_profile(), planogram_config,
  config_name=...)` only when `ctx.layout is None`; it assigns the result to the run-owned `ctx`
  (per-run state, spec §2 Overview) and never caches it on `self`.
- `compare()` must perform no I/O and no vision call (AC8) — `verify_pass` lives in `identify()`.
- Keep the four class variables unchanged; `plan.py` still reads them (removed by TASK-3870/3871).
- Run tests with `PYTHONPATH=packages/ai-parrot-pipelines/src:packages/ai-parrot/src` inside the worktree.

### Transitional breakage (accepted)
Once shared stages replace the inline logic, legacy-pinning suites owned by TASK-3874/3875/3876
(`test_legacy_run_orchestration`, `test_pos_*_characterization`, `test_neutral_*_types`,
`test_planogram_types`, `test_vision_kwargs`) may fail until those tasks land. Do NOT edit them and do
NOT add them to Validation Commands.

### References in Codebase
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/ink_wall.py:168-298` — current inline stages being replaced
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/scoring.py:147-215` — how observations are filled
- spec §2 "Type defaults" table, ink_wall row

---

## Implementation Blueprint

### Steps (in order)
1. Confirm TASK-3856/3859/3863 (and transitively TASK-3854/3855/3861) are `done`; open
   `stages/compare.py` and check whether `compare_observations` drops slots whose `anchor_shape_id`
   is `None` — *why*: the untagged bottom row and gap-filled slots of an ink wall have no anchor; if the
   shared stage drops them, stop and record it in the Completion Note instead of re-implementing compare.
2. Replace the module header/imports (lines 1-72) — *why*: drop helpers whose work moved to shared modules and add the alias.
3. Replace `InkWall` head + `perceive`/`_read_tags`/`identify`/`compare` (lines 160-298) with the hooks block — *why*: thin composition (M5).
4. Rewrite `_price_notes` (lines 355-389) and delete `_canonicalise`/`_vocabulary` (lines 391-407) — *why*: registrations are no longer returned by the shared compare.
5. Update `test_ink_wall.py`, run the Validation Commands — *why*: AC1/AC3/AC16.

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/ink_wall.py` (MODIFY — header)
```python
# occurrences: 1 (verified: grep -Fxc 'def resolve_identity(identification: Identification, definition: SlotsDefinition) -> Tuple[Optional[str], List[str]]:' ink_wall.py)
# REPLACE lines 1-146 (module docstring .. end of resolve_identity, verified: ink_wall.py:1-146) with:
"""InkWall — price-tag anchored planogram type composed from the shared cycle stages (FEAT-574, FEAT-612)."""

from __future__ import annotations

import re
from statistics import median
from typing import Dict, List, Optional, Sequence, Set, Tuple

import numpy as np
from PIL import Image

from parrot.models.detections import AisleConfig, PlanogramDescription

from ..comparison.definition import SlotsDefinition
from ..comparison.identity import resolve_identity  # noqa: F401 - historical import path (spec §2 Stage 3)
from ..contracts import (
    ComparisonResult,
    CycleContext,
    FixtureMembership,
    Identification,
    IdentificationResult,
    IdentifyStrategy,
    PerceptionResult,
    PositionResult,
    Shape,
    Slot,
)
from ..identification.verify import verify_unresolved
from ..layout import LayoutProfile, resolve_layout_profile
from ..perception.profiles import PRICE_TAG_PROFILE
from ..perception.slots import AnchorRule
from ..stages.compare import compare_observations
from ..stages.identify import identify_image
from ..stages.perceive import perceive_image
from .abstract import AbstractPlanogramType

_PRICE = re.compile(r"(\d+)[.,](\d{2})")
_INK_DESCRIPTORS = ("family", "colors", "pack", "xl")
_INK_REQUIRED = ("family", "xl")

__all__ = ["InkWall", "resolve_identity"]
```
**Why**: `resolve_identity` now lives in `comparison/identity.py` (TASK-3861) with ink defaults
(`family/colors/pack/xl`, required `family/xl`), so a plain re-export preserves both the historical import
and the old behaviour; `product_on_shelves.py:45` keeps importing it from here. `_to_bgr` and
`_parse_price` (lines 149-157) stay below this block unchanged.

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/ink_wall.py` (MODIFY — hooks)
```python
# occurrences: 1 (verified: grep -Fxc 'class InkWall(AbstractPlanogramType):' ink_wall.py)
# REPLACE lines 160-298 (class head .. end of compare, verified: ink_wall.py:160-298) with:
class InkWall(AbstractPlanogramType):
    """Price-tag anchored type: shared perceive/identify/compare plus ink price notes and verify pass."""

    identify_strategy = IdentifyStrategy.STRIPS  # read by plan.py until TASK-3870/3871
    requires_slots_definition = True
    min_usable_shapes = 8
    uses_enhanced_image = False

    @classmethod
    def default_layout_profile(cls) -> LayoutProfile:
        """Return a fresh ink-wall profile; never retailer product names, counts or shared mutable defaults."""
        return LayoutProfile(
            shape_profiles=[PRICE_TAG_PROFILE.model_copy(deep=True)],
            anchor_rule=AnchorRule.TAG_BELOW_PRODUCT,
            fill_gaps=True,
            untagged_bottom_row=True,
            identify_strategy=IdentifyStrategy.STRIPS,
            perception_mode="cv",
            min_usable_shapes=8,
            min_row_items=4,
            descriptor_fields=list(_INK_DESCRIPTORS),
            required_descriptor_fields=list(_INK_REQUIRED),
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
        self.logger.info(
            "InkWall %s: %d shapes, %d rows, %d slots",
            image_id, len(perception.shapes), perception.row_count, len(perception.slots),
        )
        return perception

    async def identify(
        self, image: Image.Image, perception: PerceptionResult, ctx: CycleContext
    ) -> IdentificationResult:
        """Compose shared OCR/vision/evidence collection, then the optional closed-set verify pass."""
        self._ensure_layout(ctx)
        result = await identify_image(image, perception, ctx)
        if (self.config.planogram_config or {}).get("verify_pass") and ctx.definition is not None:
            boxes = {s.slot_id: s.box for s in perception.slots}
            boxes.update({s.shape_id: s.box for s in perception.shapes})
            verified = await verify_unresolved(
                _to_bgr(image), list(result.identifications), ctx.definition, ctx, boxes=boxes
            )
            return result.model_copy(update={"identifications": verified})
        return result

    async def compare(
        self,
        perceptions: Sequence[PerceptionResult],
        identifications: Sequence[IdentificationResult],
        ctx: CycleContext,
    ) -> ComparisonResult:
        """Run deterministic comparison on registrable ink slots, then append price notes (no I/O)."""
        self._ensure_layout(ctx)
        by_image = {i.image_id: i for i in identifications}
        filtered: List[PerceptionResult] = []
        for perception in perceptions:
            ident = by_image.get(perception.image_id)
            kept = self._registrable_slots(perception, ident.identifications if ident else [])
            filtered.append(perception.model_copy(update={"slots": kept}))
        comparison = compare_observations(filtered, identifications, ctx, self._description())
        positions = self._price_notes(list(comparison.position_results), ctx.definition, filtered)
        return comparison.model_copy(update={"position_results": positions})
```
**Why**: spec M5 skeleton signatures verbatim. `compare` pre-filters slots because `compare_observations`
has no type hook (Does NOT Exist), and `_registrable_slots` falls back to `_fallback_slots` when a
(pre-TASK-3871) LLM fallback left `slots == []`. `verify_unresolved` needs a BGR ndarray, hence `_to_bgr`.

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/ink_wall.py` (MODIFY — price notes)
```python
# occurrences: 1 (verified: grep -Fxc '    def _price_notes(' ink_wall.py -> 1, at :356; decorator at :355)
# REPLACE lines 355-407 (_price_notes + _canonicalise + _vocabulary, verified: ink_wall.py:355-407) with:
    @staticmethod
    def _price_notes(
        positions: List[PositionResult],
        definition: SlotsDefinition,
        perceptions: Sequence[PerceptionResult],
    ) -> List[PositionResult]:
        """Append ``price_mismatch`` notes (tag OCR vs descriptors.price); credits are never touched."""
        expected = {f.facing_id: f.descriptors.price for f in definition.all_facings() if f.descriptors.price}
        if not expected:
            return positions
        tag_text: Dict[Tuple[str, str], Optional[str]] = {}
        for perception in perceptions:
            readings = getattr(perception, "ocr_readings", None) or {}
            shapes = {s.shape_id: s for s in perception.shapes}
            for slot in perception.slots:
                if not slot.anchor_shape_id:
                    continue
                reading = readings.get(slot.anchor_shape_id)
                anchor = shapes.get(slot.anchor_shape_id)
                text = (reading.text if reading is not None and reading.text else None) or (
                    anchor.ocr_text if anchor is not None else None
                )
                tag_text[(perception.image_id, slot.slot_id)] = text
                tag_text[(perception.image_id, slot.anchor_shape_id)] = text
        updated: List[PositionResult] = []
        for position in positions:
            price = expected.get(position.facing_id)
            seen: Set[float] = set()
            for ref in position.observations:
                amount = _parse_price(tag_text.get((ref.image_id, ref.shape_id)))
                if amount is not None:
                    seen.add(amount)
            ordered = sorted(seen)
            if price is not None and ordered and any(abs(amount - price) > 0.005 for amount in ordered):
                note = f"price_mismatch: expected {price:.2f}, tag reads {', '.join(f'{a:.2f}' for a in ordered)}"
                position = position.model_copy(update={"notes": [*position.notes, note]})
            updated.append(position)
        return updated
```
**Why**: `ObservationRef(image_id, shape_id)` identifies every registered view of a facing
(`scoring.py:147-215`), so registrations are no longer needed; reading `ocr_readings` first honours spec
§2 Stage 2 (own-box OCR attached by `identify_image`), `Shape.ocr_text` keeps directly-built test fixtures
working. The note text is byte-identical to today's (`ink_wall.py:386`).

### `packages/ai-parrot-pipelines/tests/planogram_cycle/test_ink_wall.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -Fxc 'class _InlineExecutor:' test_ink_wall.py -> :45)
# 1) REPLACE test_resolve_identity_never_reads_expected_facing (:222-229): assert the first two parameters are
#    ["identification", "definition"] and that no parameter name contains "facing", "slot" or "expected";
#    keep the "same reading resolves the same everywhere" assertion.
# 2) ADD after test_resolve_identity_never_reads_expected_facing (new tests listed in Test Specification):
#    test_resolve_identity_alias_is_shared_function, test_default_layout_profile_is_fresh_and_ink_shaped,
#    test_ink_hooks_resolve_layout_when_ctx_has_none, test_compare_never_calls_vision.
# 3) KEEP unchanged: _registrable_slots, perceive-synthetic, end-to-end (still 4 ask_to_image calls), price-note
#    and fallback tests — they pin retained behaviour; only fix them if the shared stage changed an id format,
#    and say so in the Completion Note.
```
**Why**: the historical assertion `parameters == ["identification", "definition"]` becomes false once
TASK-3861 adds keyword-only `vocabulary`/`required_fields`; the business guarantee (no expected-slot input) is what matters.

### FILL IN checklist
- [ ] header — run `ruff check`; remove only imports it flags unused (`median`, `np`, `Shape`, `Slot`, `Identification`, `FixtureMembership` are still used by the kept `_to_bgr`/`_registrable_slots`/`_fallback_slots`).
- [ ] `_ensure_layout` — confirm `resolve_layout_profile` expects the whole `planogram_config` (it handles the top-level `perception_mode` alias, spec §2 compatibility policy); if TASK-3855 expects only the `layout_profile` sub-dict, pass that instead.
- [ ] `compare` — if `compare_observations` drops anchor-less slots (Step 1), STOP and report (AC1/AC8 cannot be met without TASK-3863 change).
- [ ] tests — implement bodies per Test Specification.

---

## Acceptance Criteria

- [ ] `InkWall.default_layout_profile()` returns a new `LayoutProfile` per call: one price-tag profile, `tag_below_product`, `fill_gaps=True`, `untagged_bottom_row=True`, `strips`, `cv`, `min_usable_shapes=8`, `min_row_items=4`, descriptors `family/colors/pack/xl`, required `family/xl` (spec §2 table; AC3, AC4).
- [ ] `perceive`/`identify`/`compare` delegate to `perceive_image`/`identify_image`/`compare_observations`; no inline propose_shapes/group_rows/build_slots/register_image/merge_positions remain in `ink_wall.py` (AC1).
- [ ] `from parrot_pipelines.planogram.types.ink_wall import resolve_identity` returns the same object as `parrot_pipelines.planogram.comparison.identity.resolve_identity`.
- [ ] `compare` performs no vision call (spy that raises on any call stays unused) and price notes never change credits (AC8).
- [ ] Synthetic end-to-end run: 3 rows × 8 slots + untagged row, 4 strip calls, `assessment_status == "complete"`, `overall_compliant is True` (AC16).
- [ ] No retailer product names/counts added to `ink_wall.py` (AC3).
- [ ] `ruff check` and `black --check --line-length 120` pass on both touched files.
- [ ] Lint/format clean: `ruff check packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/ink_wall.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_ink_wall.py`
- [ ] Lint/format clean: `black --check --line-length 120 packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/ink_wall.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_ink_wall.py`

## Validation Commands

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_ink_wall.py -q`

---

## Test Specification

```python
# packages/ai-parrot-pipelines/tests/planogram_cycle/test_ink_wall.py (additions; reuse _ctx, _definition_dict, _ident)
from parrot_pipelines.planogram.comparison import identity as identity_module
from parrot_pipelines.planogram.contracts import IdentifyStrategy
from parrot_pipelines.planogram.perception.slots import AnchorRule


def test_resolve_identity_alias_is_shared_function():
    """Historical import path re-exports the shared resolver."""
    assert resolve_identity is identity_module.resolve_identity


def test_resolve_identity_never_reads_expected_facing():
    params = list(inspect.signature(resolve_identity).parameters)
    assert params[:2] == ["identification", "definition"]
    assert not any(k in p for p in params for k in ("facing", "slot", "expected"))
    # FILL IN: keep the existing first == again == ("ACME-3-2", ["ACME-3-2"]) assertion


def test_default_layout_profile_is_fresh_and_ink_shaped():
    first, second = InkWall.default_layout_profile(), InkWall.default_layout_profile()
    assert first is not second and first.shape_profiles[0] is not second.shape_profiles[0]
    assert first.anchor_rule == AnchorRule.TAG_BELOW_PRODUCT and first.fill_gaps and first.untagged_bottom_row
    assert first.identify_strategy == IdentifyStrategy.STRIPS and first.perception_mode == "cv"
    assert (first.min_usable_shapes, first.min_row_items) == (8, 4)
    assert first.required_descriptor_fields == ["family", "xl"]
    first.descriptor_fields.append("mutated")
    assert "mutated" not in InkWall.default_layout_profile().descriptor_fields


async def test_ink_hooks_resolve_layout_when_ctx_has_none(fake_vision_client, synthetic_ink_wall, synthetic_slots_definition):
    """A context without layout (pre-orchestrator cutover) gets the resolved ink profile; config overrides apply."""
    # FILL IN: PlanogramConfig(planogram_type="ink_wall", planogram_config={"brand": "Acme",
    #   "layout_profile": {"min_row_items": 3}}, slots_definition=...); ctx=_ctx(); await handler.perceive(...);
    #   assert ctx.layout.min_row_items == 3 and ctx.layout.anchor_rule == AnchorRule.TAG_BELOW_PRODUCT


async def test_compare_never_calls_vision(fake_vision_client):
    """compare() is pure: a vision object that raises on every attribute access is never touched."""
    # FILL IN: build the price-note fixture (as in test_ink_wall_price_note_does_not_change_credits), set
    #   ctx.vision = object whose __getattr__ raises AssertionError; await handler.compare(...) succeeds;
    #   assert fake_vision_client.calls_to("ask_to_image") == []
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
9. **Close the task** with `scripts/sdd/close_task.sh TASK-3864 refactor-planogram-compliance verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

Merged cleanly via sdd-worker orchestration; lint clean. test_neutral_panel_types.py transitional breakage accepted by task 3866.

