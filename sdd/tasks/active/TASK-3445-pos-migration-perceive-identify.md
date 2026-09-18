# TASK-3445: ProductOnShelves perceive/identify hooks and perception_mode

**Feature**: FEAT-574 — New Planogram Compliance Pipeline
**Spec**: `sdd/specs/new-planogram-pipeline.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3419, TASK-3430, TASK-3438, TASK-3443
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 17** (first half). `ProductOnShelves` is one of the two migrated
archetypes (G4). This task makes it a *cycle* type for stages 1 and 2: it
declares the class-level cycle attributes and overrides `perceive` and
`identify`. Stage 3 (`compare` + rule evaluation) is the follow-up task in the
same file.

Spec §2 "Perception default per type (spike-gated)": ProductOnShelves CV
perception is **unproven**. Until the perception spike (TASK-3419) records
passed gates, the class default is `perception_mode="llm_detector"` — the LLM
detector used as the primary detector through the same hook, under the same
membership and unknown-state rules. `planogram_config["perception_mode"] = "cv"`
opts a configuration into the profile-driven proposer.

---

## Scope

- Add the class attributes `identify_strategy`, `requires_slots_definition`,
  `min_usable_shapes = 3`, `uses_enhanced_image = False`,
  `DEFAULT_PERCEPTION_MODE = "llm_detector"`.
- Add `_perception_mode()` reading `planogram_config["perception_mode"]`
  (allowed: `"cv"`, `"llm_detector"`; anything else ⇒ `ValueError`).
- Add `get_shape_profiles()` returning the ProductOnShelves profiles (product
  body, box, fact tag, backlit/poster zone). Take the constants from the
  "Accepted profiles" section of `docs/pipelines/planogram-perception-spike.md`.
  If that report's outcome is not `passed`, the profiles are **provisional**
  (`FILL IN`) and `DEFAULT_PERCEPTION_MODE` stays `"llm_detector"`.
- Override `perceive(image, image_id, ctx)`:
  - `"cv"`: `propose_shapes` (through `ctx.executor`) → zone shapes split from
    product shapes → `detect_shelf_edges` / `group_rows` → `build_slots` with
    `AnchorRule.SHAPE_IS_SLOT` → OCR of fact-tag / zone crops when
    `ctx.ocr.available` → `assign_membership`.
  - `"llm_detector"`: `llm_detect_shapes(..., prompt=self.fallback_detection_prompt())`
    → same rows/slots/membership steps; `detection_source="llm"`.
- Override `identify(image, perception, ctx)` with `identify_full_image`
  (vocabulary = product names + brands of the slots definition).
- Override `fallback_detection_prompt()` — the same product-hint prompt text
  `_detect_legacy` builds, **duplicated** (not extracted: `_detect_legacy`'s
  docstring forbids modifying it).
- Tests for both perception modes, offline.

**NOT in scope**: the `compare` hook and rule evaluation (next task in this
file); deleting or editing any legacy method (`compute_roi`, `detect_objects`,
`_detect_legacy`, `check_planogram_compliance`, `_ocr_fact_tags`, … stay
byte-identical); flipping `DEFAULT_PERCEPTION_MODE` to `"cv"` (a follow-up
one-line change after a passed spike, recorded in the spec revision history).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py` | MODIFY | class attrs, `_perception_mode`, `get_shape_profiles`, `perceive`, `identify`, `fallback_detection_prompt` |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_pos_migrated_perceive_identify.py` | CREATE | offline tests for both perception modes |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
# already at the top of product_on_shelves.py (verified :7-32)
import asyncio
from typing import Any, Dict, List, Optional, Tuple
from PIL import Image
from .abstract import AbstractPlanogramType                                  # :17
from parrot.models.detections import (Detection, DetectionBox, ShelfRegion,
    IdentifiedProduct, BoundingBox, Detections)                              # :18-25

# to ADD — all created by dependency tasks (see "Created by …" below)
import numpy as np                                                           # declared dep after TASK-3428
from typing import ClassVar, Literal, Sequence
from parrot_pipelines.planogram.contracts import (CycleContext, IdentificationResult, IdentifyStrategy,
    ObservationSource, PerceptionResult, Shape, ShapeKind)                   # TASK-3421
from parrot_pipelines.planogram.perception.profiles import ShapeProfile      # TASK-3418
from parrot_pipelines.planogram.perception.shapes import propose_shapes      # TASK-3418
from parrot_pipelines.planogram.perception.rows import group_rows, detect_shelf_edges   # TASK-3433
from parrot_pipelines.planogram.perception.slots import AnchorRule, build_slots         # TASK-3433
from parrot_pipelines.planogram.perception.ocr import read_crop              # TASK-3428
from parrot_pipelines.planogram.perception.membership import assign_membership          # TASK-3437
from parrot_pipelines.planogram.identification.identify import identify_full_image      # TASK-3438
from parrot_pipelines.planogram.identification.detector import llm_detect_shapes        # TASK-3439
```

### Existing Signatures to Use
```python
# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py  (1683 lines)
class ProductOnShelves(AbstractPlanogramType):                               # :35
    def __init__(self, pipeline: Any, config: Any) -> None:                  # :47-52
        # sets self.left_margin_ratio / self.right_margin_ratio from config.endcap_geometry
    async def _detect_legacy(self, target_image, planogram_description, offset_x, offset_y)   # :262-382
        # docstring :269-273: "Do NOT modify this method — it must remain byte-for-byte equivalent"
        # hints = ShelfProduct names of planogram_description.shelves[*].products  :285-290
        # prompt text :293-308; _output_format :320-326;
        # _base_prompt = getattr(self.config, "object_identification_prompt", None) or prompt  :327
# inherited: self.pipeline, self.config, self.logger  (types/abstract.py:53-55)
# self.config.planogram_config: Dict[str, Any]          (parrot_pipelines/models.py:50-52)
# self.config.get_planogram_description() -> PlanogramDescription   (models.py:102-108)
```

```python
# Created by TASK-3442 (dependency, via TASK-3443) — AbstractPlanogramType, spec §3 Module 14
identify_strategy: ClassVar[IdentifyStrategy] = IdentifyStrategy.FULL_IMAGE
requires_slots_definition: ClassVar[bool] = False
min_usable_shapes: ClassVar[int] = 0
uses_enhanced_image: ClassVar[bool] = True
async def perceive(self, image: Image.Image, image_id: str, ctx: CycleContext) -> PerceptionResult
async def identify(self, image: Image.Image, perception: PerceptionResult, ctx: CycleContext) -> IdentificationResult
def fallback_detection_prompt(self) -> Optional[str]

# Created by TASK-3421 (dependency) — planogram/contracts.py, spec §2 Data Models
class Shape(BaseModel):  shape_id, image_id, kind, box: DetectionBox, profile, row_index, slot_index,
                         ocr_text, ocr_confidence, source, membership, membership_evidence
class PerceptionResult(BaseModel): image_id, image_size, shapes, slots, zones, row_count, detection_source,
                         ocr_available, legacy, errors
class CycleContext(BaseModel): vision, executor, ocr, definition, bindings, credit_policy, evidence_weights,
                         output_dir, errors

# Created by TASK-3418 / TASK-3433 / TASK-3428 / TASK-3437 / TASK-3438 / TASK-3439 (dependencies)
def propose_shapes(image: np.ndarray, profiles: Sequence[ShapeProfile], *, work_width: int = 2048) -> List[ShapeCandidate]
def group_rows(candidates, image_width: int, *, min_row_items: int = 4, max_slope: float = 0.12) -> List[List[ShapeCandidate]]
def detect_shelf_edges(image: np.ndarray, *, min_length: float = 0.35) -> List[int]
def build_slots(rows, image_size: Tuple[int, int], *, image_id: str, rule: AnchorRule,
                fill_gaps: bool = True, untagged_bottom_row: bool = False) -> List[Slot]
def read_crop(crop: np.ndarray) -> Tuple[str, float]                 # module-level, picklable
class CpuExecutor:  async def run(self, fn, *args) -> T              # ctx.executor
def assign_membership(shapes, zones, image_size, *, llm_hints=None) -> List[Shape]
async def identify_full_image(image: np.ndarray, perception: PerceptionResult, ctx: CycleContext,
                              *, vocabulary: Sequence[str]) -> IdentificationResult
async def llm_detect_shapes(image: np.ndarray, image_id: str, ctx: CycleContext, *, prompt: str) -> List[Shape]
```

### Does NOT Exist
- ~~`ProductOnShelves.perceive` / `.identify` / `.get_shape_profiles` / `._perception_mode`~~ — this task adds them.
- ~~a helper that returns `_detect_legacy`'s prompt~~ — the prompt is built inline (:293-308); duplicate the text, do not refactor `_detect_legacy`.
- ~~`PlanogramConfig.perception_mode`~~ — not a model field; it is a key of the raw `planogram_config` dict.
- ~~shelf-edge or generic shape detection anywhere in this file today~~ — all detection here is LLM-based.
- ~~`ShapeCandidate.to_shape()`~~ — build `Shape` explicitly from the candidate's `x1,y1,x2,y2,score,profile,kind`.
- ~~`self.pipeline.roi_client`~~ — removed by the provider-neutral tasks; never reintroduce it.

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
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py#ProductOnShelves",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py#ProductOnShelves._detect_legacy",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py#AbstractPlanogramType"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
- CPU work never runs on the event loop: `await ctx.executor.run(propose_shapes, arr, profiles)`.
  Pass `np.ndarray`, never a PIL image or `self`, across the process boundary.
- The image handed to `perceive` is the **untouched full-resolution** image
  (`uses_enhanced_image = False`); never call `_enhance_image` / `_downscale_image` here.
- Header / backlit / poster shapes are **zones detected apart** — they go to
  `PerceptionResult.zones`, never into rows or slots.

### Key Constraints
- **Shape ids**: build every CV `Shape.shape_id` with `candidate_shape_id(image_id, candidate)` from
  `parrot_pipelines.planogram.perception.slots` (TASK-3433) — *why*: `build_slots` fills `Slot.anchor_shape_id` with that
  exact id, and registration joins identifications to slots through it; a different id scheme silently breaks the join.
- Legacy methods stay byte-identical; the characterization tests of the
  feature must stay green.
- Run tests inside the worktree with
  `PYTHONPATH=packages/ai-parrot-pipelines/src:packages/ai-parrot/src`.
- Google-style docstrings, strict type hints, `self.logger`, no `print`.

### References in Codebase
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py:285-308` — legacy prompt text to duplicate
- `docs/pipelines/planogram-perception-spike.md` — spike outcome + accepted profiles (TASK-3419)
- `packages/ai-parrot-pipelines/tests/conftest.py` — `fake_vision_client`, `synthetic_shelf_image` (TASK-3420)

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Never change a
> signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Read `docs/pipelines/planogram-perception-spike.md` and note its outcome — *why*: it decides whether the profile constants are accepted values or provisional ones.
2. Add the imports and class attributes — *why*: `validate_contract()` and the `run()` template read them at construction time.
3. Add `_perception_mode`, `get_shape_profiles`, `fallback_detection_prompt` — *why*: `perceive` depends on all three.
4. Add `perceive` then `identify` — *why*: hooks are called in that order by `run()`.
5. Write the tests, run the Validation Command plus the feature's ProductOnShelves characterization tests — *why*: legacy behaviour must not move.

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py` (MODIFY) — block 1: attributes
```python
# occurrences: 1 (verified: grep -c '    def __init__(self, pipeline: Any, config: Any) -> None:' product_on_shelves.py)
# BEFORE — insert above `    def __init__(self, pipeline: Any, config: Any) -> None:` (verified: product_on_shelves.py:47)
    identify_strategy: ClassVar[IdentifyStrategy] = IdentifyStrategy.FULL_IMAGE
    requires_slots_definition: ClassVar[bool] = True
    min_usable_shapes: ClassVar[int] = 3
    uses_enhanced_image: ClassVar[bool] = False
    DEFAULT_PERCEPTION_MODE: ClassVar[Literal["cv", "llm_detector"]] = "llm_detector"

```
**Why**: values fixed by spec Module 17's skeleton. `"llm_detector"` is the
spike-gated default — do not change it in this task even if the spike passed.

### same file — block 2: mode, profiles, prompt
```python
# occurrences: 1 (verified: grep -c '    async def _detect_with_grid(' product_on_shelves.py)
# BEFORE — insert above `    async def _detect_with_grid(` (verified: product_on_shelves.py:224)
    def _perception_mode(self) -> str:
        """Return the perception mode of this configuration.

        Raises:
            ValueError: When planogram_config["perception_mode"] is not "cv" or "llm_detector".
        """
        raw = (self.config.planogram_config or {}).get("perception_mode", self.DEFAULT_PERCEPTION_MODE)
        if raw not in ("cv", "llm_detector"):
            raise ValueError(f"Invalid perception_mode '{raw}'. Use 'cv' or 'llm_detector'.")
        return raw

    def get_shape_profiles(self) -> List[ShapeProfile]:
        """Shape profiles for product bodies, boxes, fact tags and the backlit/poster zone."""
        # FILL IN: one ShapeProfile per kind with the constants of the "Accepted profiles"
        #   section of the spike report — bounded by: if the report outcome is not "passed",
        #   use the report's provisional values and add the comment "PROVISIONAL (spike: <outcome>)".
        #   The zone profile must use kind=ShapeKind.ZONE.value; printers need polarity="edge".
        raise NotImplementedError

    def fallback_detection_prompt(self) -> Optional[str]:
        """Prompt for the LLM detector: the legacy product-hint prompt (see _detect_legacy)."""
        description = self.config.get_planogram_description()
        hints = sorted({p.name for s in description.shelves for p in s.products if getattr(p, "name", "")})
        # FILL IN: return the same instruction text as _detect_legacy (:293-308) with
        #   ", ".join(hints) interpolated — bounded by: copy the wording, do NOT call or
        #   edit _detect_legacy; prefer self.config.object_identification_prompt when set (:327).
        raise NotImplementedError
```
**Why**: `hints` is sorted (the legacy code joins a `set`, whose order is
random) so the prompt — and therefore the vision cache key — is deterministic.

### same file — block 3: hooks
```python
# AFTER — insert directly below block 2
    async def perceive(self, image: Image.Image, image_id: str, ctx: CycleContext) -> PerceptionResult:
        """Stage 1 on the untouched full-resolution image (no ROI gate)."""
        arr = np.asarray(image.convert("RGB"))[:, :, ::-1].copy()   # BGR for OpenCV
        mode = self._perception_mode()
        errors: List[str] = []
        if mode == "cv":
            candidates = await ctx.executor.run(propose_shapes, arr, self.get_shape_profiles())
            # FILL IN: convert candidates to Shape (source=ObservationSource.CV, shape_id
            #   f"{image_id}:s{n}") — bounded by: ids unique per image, box in source pixels.
            detection_source = "cv"
        else:
            shapes = await llm_detect_shapes(arr, image_id, ctx, prompt=self.fallback_detection_prompt() or "")
            detection_source = "llm"
        # FILL IN: split zones (kind == ZONE) from product shapes; rows via detect_shelf_edges
        #   + group_rows(min_row_items=1 for sparse shelves); slots via build_slots(rule=
        #   AnchorRule.SHAPE_IS_SLOT, fill_gaps=False) — bounded by: zones never enter rows/slots;
        #   product rows ordered top→bottom.
        # FILL IN: when ctx.ocr.available, OCR fact-tag and zone crops with
        #   ctx.executor.run(read_crop, crop) — bounded by: never import rapidocr here.
        # FILL IN: shapes = assign_membership(shapes, zones, image.size) — bounded by:
        #   expected products are NOT an input to membership.
        self.logger.debug("perceive[%s] mode=%s", image_id, mode)
        raise NotImplementedError  # FILL IN: return PerceptionResult(...)

    async def identify(self, image: Image.Image, perception: PerceptionResult,
                       ctx: CycleContext) -> IdentificationResult:
        """Stage 2: one full-image call (image + stage-1 JSON)."""
        arr = np.asarray(image.convert("RGB"))[:, :, ::-1].copy()
        # FILL IN: vocabulary = sorted product names + brands from ctx.definition facings
        #   — bounded by: never offer an expected SKU as evidence, only as vocabulary.
        return await identify_full_image(arr, perception, ctx, vocabulary=[])
```
**Why this shape**: both perception modes converge on the same rows → slots →
OCR → membership tail, so the fallback obeys the same membership and
unknown-state rules (spec G7, G13). The `run()` template performs the
threshold-triggered fallback itself; this hook only handles the *configured* mode.

### `packages/ai-parrot-pipelines/tests/planogram_cycle/test_pos_migrated_perceive_identify.py` (CREATE)
See **Test Specification** — write it verbatim, then fill the test bodies.

### FILL IN checklist
- [ ] `get_shape_profiles` — constants from the spike report; provisional comment when outcome ≠ passed
- [ ] `fallback_detection_prompt` — duplicated legacy wording, deterministic hints
- [ ] `perceive` — candidate→Shape conversion; zone split; rows/slots; OCR; membership; `PerceptionResult`
- [ ] `identify` — vocabulary from `ctx.definition`
- [ ] test bodies

---

## Acceptance Criteria

- [ ] `ProductOnShelves.DEFAULT_PERCEPTION_MODE == "llm_detector"`; `planogram_config["perception_mode"]="cv"` switches to the proposer; any other value raises `ValueError`.
- [ ] `perceive` never calls `_enhance_image`, `compute_roi` or `_detect_legacy`.
- [ ] Zone shapes appear in `PerceptionResult.zones` and in no slot.
- [ ] `detection_source` is `"cv"` or `"llm"` according to the mode; `ocr_available` mirrors `ctx.ocr.available`.
- [ ] `identify` issues exactly one `ask_to_image` call per image (full-image strategy).
- [ ] No legacy method of the file changed (diff shows only insertions + imports).
- [ ] `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_pos_migrated_perceive_identify.py -q` passes offline.
- [ ] `ruff check packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py` passes.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_pos_migrated_perceive_identify.py -q`

---

## Test Specification

```python
# packages/ai-parrot-pipelines/tests/planogram_cycle/test_pos_migrated_perceive_identify.py
"""Offline tests for the ProductOnShelves perceive/identify hooks."""
import pytest
from unittest.mock import MagicMock

from parrot_pipelines.planogram.types.product_on_shelves import ProductOnShelves


def _make_handler(planogram_config: dict) -> ProductOnShelves:
    """Build the type with a MagicMock pipeline and a minimal config."""
    # FILL IN: MagicMock pipeline (logger, reference_images={}) + MagicMock config exposing
    #   planogram_config, endcap_geometry, get_planogram_description(), object_identification_prompt=None
    ...


def test_default_perception_mode_is_llm_detector():
    assert ProductOnShelves.DEFAULT_PERCEPTION_MODE == "llm_detector"


def test_invalid_perception_mode_raises():
    handler = _make_handler({"perception_mode": "yolo"})
    with pytest.raises(ValueError, match="perception_mode"):
        handler._perception_mode()


def test_fallback_prompt_is_deterministic_and_lists_hints():
    """Two calls return the same text; product names appear sorted."""


@pytest.mark.asyncio
async def test_perceive_llm_detector_mode(fake_vision_client, synthetic_shelf_image):
    """detection_source == 'llm'; zones excluded from slots; membership assigned."""


@pytest.mark.asyncio
async def test_perceive_cv_mode_uses_executor_not_event_loop(synthetic_shelf_image):
    """propose_shapes is dispatched through ctx.executor.run; detection_source == 'cv'."""


@pytest.mark.asyncio
async def test_identify_makes_one_full_image_call(fake_vision_client, synthetic_shelf_image):
    """Exactly one ask_to_image call is recorded on the fake client."""
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
7. **Move this file** to `tasks/completed/TASK-3445-pos-migration-perceive-identify.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
