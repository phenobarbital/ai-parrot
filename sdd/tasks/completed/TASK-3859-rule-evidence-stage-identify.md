# TASK-3859: Neutral rule-evidence collector and shared identify stage

**Feature**: FEAT-612 — Refactor Planogram Compliance
**Spec**: `sdd/specs/refactor-planogram-compliance.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3857, TASK-3858, TASK-3856
**Assigned-to**: unassigned

---

## Context

Spec §2 **Stage 2** (last paragraph: "Collect illumination state and visual facts during
identification through a new neutral `collect_rule_evidence` helper…"), §3 **Module 3**
skeletons `collect_rule_evidence` and `identify_image`, and §7 "Patterns to Follow"
(`identify_image` attaches OCR readings to its run-owned perception; zone-region inspection with
target id `<image_id>:zone-region:<zone_id>`).

Today non-product rule facts are gathered during **compare**: `ProductOnShelves._rule_illumination`
calls the LLM-backed `_check_illumination` (`product_on_shelves.py:667-710`,
`types/abstract.py:167`), which makes compare impure (spec §6 Corrections). FEAT-612 moves every
provider call into stage 2: this task creates

1. `identification/evidence.py` — asks the vision adapter what is VISIBLE on observed zones (and
   on configured zone regions when no zone was observed there) and returns neutral
   `RuleObservation`s; it never asks whether a configured expectation is satisfied.
2. `stages/identify.py` — the shared stage-2 composition every type's `identify` hook calls:
   own-box OCR → strategy dispatch from the profile → rule evidence.

---

## Scope

- Create `collect_rule_evidence(image, perception, ctx) -> list[RuleObservation]`:
  - requested kinds come only from `ctx.bindings` kinds (`illumination`, `visual_features`,
    `zone_present`); with no such binding make no provider call;
  - one crop call per observed, not-off-fixture zone for illumination/visual facts;
  - one crop call per configured `ZoneSelector.region` (for a zone targeted by a `zone_present`
    binding) whose region contains no observed zone centre, emitting a `zone_present`
    observation with target id `f"{image_id}:zone-region:{zone_id}"`;
  - failed crops are isolated (`ctx.errors`), never converted into a negative observation.
- Create `identify_image(image, perception, ctx) -> IdentificationResult`:
  - convert the PIL image to BGR through the CPU executor;
  - `read_target_text` → attach readings to the (run-owned) perception;
  - dispatch `ctx.layout.identify_strategy` to `identify_full_image` / `identify_strips` /
    `identify_slots` with `vocabulary = ctx.layout.descriptor_fields`;
  - attach `collect_rule_evidence(...)` to `IdentificationResult.rule_observations`.
- Write `test_rule_evidence.py` and `test_stage_identify.py`.

**NOT in scope**:
- Binding observations to definition zone ids, conflict handling across photos and rule
  outcomes — TASK-3863 (`comparison/rules.py`).
- The v2 prompt, references, `identify_slots` — TASK-3858. OCR/reference helpers — TASK-3857.
- `verify_pass` (ink closed-set verification) — stays a type decision (TASK-3864).
- Removing `_check_illumination` / `_vision_kwargs` from the abstract type — TASK-3870.
- Editing `stages/__init__.py` (created by TASK-3856) — import the new module by its full path.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/evidence.py` | CREATE | neutral zone / zone-region evidence collection |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/stages/identify.py` | CREATE | `identify_image` shared stage |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_rule_evidence.py` | CREATE | evidence collector tests |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_stage_identify.py` | CREATE | shared identify stage tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from parrot.models.detections import DetectionBox                                   # parrot/models/detections.py:37
from parrot_pipelines.planogram.contracts import (                                  # planogram/contracts.py
    CycleContext,            # :322
    FixtureMembership,       # :35
    IdentificationResult,    # :137
    ObservationSource,       # :26
    PerceptionResult,        # :86
    Shape,                   # :50
)
from parrot_pipelines.planogram.identification.vision import VisionError           # identification/vision.py:31
from parrot_pipelines.planogram.identification.verify import crop_and_encode       # identification/verify.py:132
from parrot_pipelines.planogram.identification.identify import identify_full_image, identify_strips  # identify.py:461, :493
```

### Existing Signatures to Use
```python
# identification/vision.py
class VisionError(RuntimeError)                                                   # :31
class VisionAdapter:                                                              # :131
    async def ask(self, prompt: str, images: Sequence[bytes], schema: Type[T], *, stage: str,
                  prompt_version: str, system_prompt: Optional[str] = None) -> T   # :173 raises VisionError

# identification/verify.py
def crop_and_encode(image: np.ndarray, box: Tuple[int, int, int, int], pad: float = 0.08) -> bytes   # :132
    # picklable (CPU executor); raises ValueError("empty crop") for a degenerate box

# identification/identify.py (signatures unchanged by TASK-3858)
async def identify_full_image(image: np.ndarray, perception, ctx, *, vocabulary: Sequence[str]) -> IdentificationResult  # :461
async def identify_strips(image: np.ndarray, perception, ctx, *, vocabulary: Sequence[str], marks: bool = True,
                          substrip_max_slots: int = 8) -> IdentificationResult     # :493

# perception/executor.py
async def CpuExecutor.run(self, fn, *args)                                        # :62 positional args, module-level fn

# comparison/definition.py
class RuleBinding(BaseModel): rule_id, kind: RuleKind, target_id, params, mandatory   # :88
RuleKind = Literal["illumination", "text_requirements", "visual_features", "zone_present"]   # :14

# Neutral illumination criteria to REUSE as wording (do not call): types/abstract.py:218-246
#   (uniform self-emitted glow, frame halo, luminous translucent colours vs ambient-lit opaque print)
# PIL -> BGR pattern: types/ink_wall.py:149-151
```

### Symbols created by dependency tasks (not yet on dev)
```python
# TASK-3854 — contracts.py
class IdentifyStrategy(str, Enum): FULL_IMAGE; STRIPS; SLOTS
class RuleObservation(BaseModel):
    image_id: str
    target_id: str
    kind: Literal["illumination", "visual_features", "zone_present"]
    value: str | bool | list[str] | None = None
    assessed: bool = False
    source: ObservationSource
    evidence: list[str] = Field(default_factory=list)
# PerceptionResult.ocr_readings: dict[str, OcrReading]; IdentificationResult.rule_observations: list[RuleObservation]
# CycleContext.layout: Any (LayoutProfile)
# TASK-3855 — layout.py
class ZoneSelector(BaseModel): zone_id: str; profile: str | None; kind: str | None; ordinal: int | None
                               region: tuple[float, float, float, float] | None   # full-source normalised [x1,y1,x2,y2]
# LayoutProfile.identify_strategy, .descriptor_fields, .substrip_max_slots, .zone_selectors
# TASK-3856 — stages/__init__.py (package exists)
# TASK-3857 — identification/targets.py
async def read_target_text(image: np.ndarray, perception: PerceptionResult, ctx: CycleContext) -> dict[str, OcrReading]
# TASK-3858 — identification/identify.py
async def identify_slots(image: np.ndarray, perception, ctx, *, vocabulary: Sequence[str], marks: bool = True) -> IdentificationResult
```

### Does NOT Exist
- ~~`parrot_pipelines.planogram.stages.identify`~~ / ~~`identification.evidence`~~ — this task creates them.
- ~~an expected-state field in the evidence prompt~~ — `RuleBinding.params` (`required`, `expected`, `penalty`) must never reach a prompt.
- ~~a `Shape`/`Slot` for a zone region~~ — a region crop is recorded ONLY as a `RuleObservation` target id; never manufacture geometry (spec §7).
- ~~`AbstractPlanogramType._check_illumination` in the shared stage~~ — shared stages must not import concrete/abstract types (spec §7 "Avoid cycles").

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/evidence.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/stages/identify.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_rule_evidence.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_stage_identify.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/vision.py#VisionAdapter.ask",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/vision.py#VisionError",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/verify.py#crop_and_encode",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/identify.py#identify_full_image",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/identify.py#identify_strips",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/executor.py#CpuExecutor.run",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py#RuleBinding",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py#CycleContext",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py#PerceptionResult",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py#IdentificationResult",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py#FixtureMembership"
  ]
}
```

---

## Implementation Notes

### Planner cross-task notes (added at /sdd-task time)
- Selector matches are recorded by TASK-3856 as `membership=ON_FIXTURE` plus a `membership_evidence` entry `"zone_selector:<zone_id>"`; import `SELECTOR_EVIDENCE_PREFIX` from `parrot_pipelines.planogram.stages.perceive` and parse that — do not invent a second convention.


### Pattern to Follow
- Provider calls: exactly `await ctx.vision.ask(prompt, [png], Schema, stage=EVIDENCE_STAGE,
  prompt_version=EVIDENCE_PROMPT_VERSION)` — the same adapter/backend as identification, so the
  cache and retries apply (spec §2 Integration Points "same resolved backend").
- Crops: `png = await ctx.executor.run(crop_and_encode, image, (x1, y1, x2, y2))` (module-level,
  picklable, positional args — spec §7).
- Isolation: mirror `_run_call`'s VisionError handling (`identify.py:367-371`): record
  `f"{perception.image_id}: evidence_failed {target_id}: {exc}"` in `ctx.errors`, emit NO
  observation for that crop (unknown ⇒ later unassessed), continue with the others.

### Key Constraints
- **Neutral questions** (AC7): prompts ask what is visible (illumination on/off/unknown, visible
  elements, whether any display element occupies a region). They never include the rule's
  `required` value, the expected zone id/kind, product names or text requirements.
- **Binding happens later**: `target_id` is the OBSERVED zone's `shape_id`, or the region id
  `<image_id>:zone-region:<zone_id>` (the only place a definition zone id appears, by the §7
  convention TASK-3863 consumes). Never map an observation to a definition zone here.
- `assessed=True` only when the answer is decisive: illumination `on`/`off`; region presence
  `yes`/`no`; visual features whenever the call succeeded (an empty list is a real observation).
- Zone-region inspection happens only when (a) a `zone_present` binding targets the selector's
  `zone_id`, (b) the selector has a `region`, and (c) no observed zone of this image has its centre
  inside the scaled region. Region box = `(x1*W, y1*H, x2*W, y2*H)` rounded and clamped; a
  degenerate box is skipped with an error.
- Off-fixture zones (`membership == OFF_FIXTURE`) are never inspected; `UNCERTAIN` and `ON_FIXTURE` are.
- `identify_image`:
  - `ctx.layout is None` ⇒ `ValueError("identify_image requires a resolved layout profile (ctx.layout)")`
    (the orchestrator always sets it, TASK-3871; failing loudly beats a silent default);
  - mutate only the perception passed in (run-owned): `perception.ocr_readings = readings` and
    `perception.ocr_available = bool(getattr(ctx.ocr, "available", False))`; never touch
    `ctx.layout`, the config or another run's objects;
  - strips use `substrip_max_slots=ctx.layout.substrip_max_slots`;
  - the result is returned via `result.model_copy(update={"rule_observations": observations})`.
- Cancellation propagates everywhere (no bare `except BaseException`).

### References in Codebase
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py:218-246` — illumination wording to neutralise
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py:667-710` — the compare-time LLM call this replaces
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/identify.py:345-402` — call isolation pattern

---

## Implementation Blueprint

### Steps (in order)
1. Confirm dependencies: `ls .../planogram/stages/__init__.py`, `grep -n "class RuleObservation" .../contracts.py`, `grep -n "def read_target_text" .../identification/targets.py`, `grep -n "def identify_slots" .../identification/identify.py` — *why*: all imported below; STOP if any is missing.
2. Write `evidence.py` — *why*: `stages/identify.py` imports it.
3. Write `stages/identify.py` — *why*: composes TASK-3857/3858 helpers with the evidence collector.
4. Write both test files; run the Validation Commands — *why*: spec §4 rows "neutral rule evidence" and "prompt/strategies".

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/evidence.py` (CREATE)
```python
"""Neutral, crop-tied rule evidence collected during identification (FEAT-612, spec §2 Stage 2 / Module 3)."""

from __future__ import annotations

import asyncio
import logging
from typing import List, Literal, Optional, Sequence, Tuple

import numpy as np
from pydantic import BaseModel, Field

from parrot_pipelines.planogram.contracts import (
    CycleContext,
    FixtureMembership,
    ObservationSource,
    PerceptionResult,
    RuleObservation,
    Shape,
)
from parrot_pipelines.planogram.identification.verify import crop_and_encode
from parrot_pipelines.planogram.identification.vision import VisionError

logger = logging.getLogger(__name__)

EVIDENCE_STAGE: str = "evidence"
EVIDENCE_PROMPT_VERSION: str = "evidence-v1"
ZONE_REGION_TARGET: str = "{image_id}:zone-region:{zone_id}"  # spec §7 convention, consumed by comparison/rules.py


class ZoneEvidenceAnswer(BaseModel):
    """What the model sees on one observed zone crop."""

    illumination: Literal["on", "off", "unknown"] = "unknown"
    visual_features: List[str] = Field(default_factory=list)
    raw_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: List[str] = Field(default_factory=list)


class RegionPresenceAnswer(BaseModel):
    """Whether any display element occupies an inspected region crop."""

    present: Literal["yes", "no", "unknown"] = "unknown"
    raw_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: List[str] = Field(default_factory=list)


def build_zone_prompt(ask_illumination: bool, ask_features: bool) -> str:
    """Neutral zone prompt: visible illumination and elements only; no expected state, ids or products."""
    # FILL IN: short instructions; illumination criteria reworded from types/abstract.py:218-246
    #   (self-emitted uniform glow / frame halo / luminous colours = on; ambient-lit opaque print = off;
    #   cannot tell = unknown); visual_features = short phrases of visible logos, graphics, text, screens,
    #   products; one-sentence evidence. Omit the parts not requested — bounded by AC7
    raise NotImplementedError


def build_region_prompt() -> str:
    """Neutral presence prompt for a configured region crop."""
    # FILL IN: "does any display element (sign, graphic panel, header, poster, screen, product) occupy this
    #   area? yes / no / unknown (unknown when blurred, occluded or cut off)" + evidence — bounded by AC7
    raise NotImplementedError


def _region_box(region: Tuple[float, float, float, float], size: Tuple[int, int]) -> Optional[Tuple[int, int, int, int]]:
    """Normalised full-source region -> clamped pixel box, or None when degenerate."""
    # FILL IN: scale by (W, H), round, clamp to the image, None when x2<=x1 or y2<=y1
    raise NotImplementedError


def _centre_inside(shape: Shape, box: Tuple[int, int, int, int]) -> bool:
    """True when the shape's box centre lies inside ``box``."""
    cx, cy = (shape.box.x1 + shape.box.x2) / 2, (shape.box.y1 + shape.box.y2) / 2
    return box[0] <= cx <= box[2] and box[1] <= cy <= box[3]


async def collect_rule_evidence(
    image: np.ndarray, perception: PerceptionResult, ctx: CycleContext
) -> List[RuleObservation]:
    """Observe requested zone/facing facts neutrally via VisionAdapter; isolate failed crops.

    Args:
        image: Untouched full-resolution BGR image.
        perception: Stage-1 output of the image (observed zones in source pixels).
        ctx: Per-run services (vision, executor, bindings, layout.zone_selectors, errors).

    Returns:
        Neutral observations in deterministic order (zones top-to-bottom/left-to-right, then regions).
    """
    kinds = {b.kind for b in ctx.bindings}
    ask_illumination = "illumination" in kinds
    ask_features = "visual_features" in kinds
    presence_zone_ids = {b.target_id for b in ctx.bindings if b.kind == "zone_present"}
    observations: List[RuleObservation] = []
    # FILL IN (zones): if ask_illumination or ask_features: for each zone not OFF_FIXTURE (sorted by y1, x1)
    #   gather one ask per crop (crop via ctx.executor.run(crop_and_encode, image, box)); per success emit
    #   RuleObservation(kind="illumination", value=answer.illumination, assessed=answer.illumination != "unknown")
    #   and/or RuleObservation(kind="visual_features", value=list(answer.visual_features), assessed=True),
    #   image_id=perception.image_id, target_id=zone.shape_id, source=ObservationSource.LLM, evidence=answer.evidence;
    #   VisionError/ValueError -> ctx.errors entry, no observation — bounded by AC7, AC12
    # FILL IN (regions): selectors = ctx.layout.zone_selectors if ctx.layout is not None else [];
    #   for selector with region and zone_id in presence_zone_ids: box = _region_box(...); skip when any observed
    #   zone centre is inside; else ask RegionPresenceAnswer and emit kind="zone_present",
    #   target_id=ZONE_REGION_TARGET.format(image_id=perception.image_id, zone_id=selector.zone_id),
    #   value=(answer.present == "yes") if decisive else None, assessed=answer.present != "unknown" — bounded by spec §7
    return observations
```
**Why this shape**: spec §3 fixes `collect_rule_evidence`'s signature; answer schemas are local
Pydantic models because `VisionAdapter.ask` validates into a schema (`vision.py:173`). The region
id convention is a module constant so TASK-3863 can match it textually without importing this
module's provider code.

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/stages/identify.py` (CREATE)
```python
"""Shared stage 2: own-box OCR -> configured strategy -> neutral rule evidence (FEAT-612, Module 3)."""

from __future__ import annotations

import logging

import numpy as np
from PIL import Image

from parrot_pipelines.planogram.contracts import CycleContext, IdentificationResult, IdentifyStrategy, PerceptionResult
from parrot_pipelines.planogram.identification.evidence import collect_rule_evidence
from parrot_pipelines.planogram.identification.identify import identify_full_image, identify_slots, identify_strips
from parrot_pipelines.planogram.identification.targets import read_target_text

logger = logging.getLogger(__name__)


def to_bgr(image: Image.Image) -> np.ndarray:
    """Untouched full-resolution PIL image -> contiguous BGR array. Module-level, picklable (CPU executor)."""
    return np.asarray(image.convert("RGB"))[:, :, ::-1].copy()


async def identify_image(image: Image.Image, perception: PerceptionResult, ctx: CycleContext) -> IdentificationResult:
    """Read OCR, dispatch configured strategy, then attach neutral rule observations.

    Args:
        image: Untouched full-resolution image.
        perception: Run-owned stage-1 output of the image (receives the OCR readings in place).
        ctx: Per-run services; ``ctx.layout`` must be a resolved LayoutProfile.

    Returns:
        The identification result with ``rule_observations`` attached.

    Raises:
        ValueError: ``ctx.layout`` is None.
    """
    layout = ctx.layout
    if layout is None:
        raise ValueError("identify_image requires a resolved layout profile (ctx.layout)")
    bgr = await ctx.executor.run(to_bgr, image)
    perception.ocr_readings = await read_target_text(bgr, perception, ctx)
    perception.ocr_available = bool(getattr(ctx.ocr, "available", False))
    vocabulary = list(layout.descriptor_fields)
    strategy = IdentifyStrategy(layout.identify_strategy)
    # FILL IN: FULL_IMAGE -> identify_full_image(bgr, perception, ctx, vocabulary=vocabulary);
    #   STRIPS -> identify_strips(..., vocabulary=vocabulary, substrip_max_slots=layout.substrip_max_slots);
    #   SLOTS -> identify_slots(..., vocabulary=vocabulary) — bounded by AC3 (strategy from profile)
    result: IdentificationResult = IdentificationResult(image_id=perception.image_id)
    observations = await collect_rule_evidence(bgr, perception, ctx)
    logger.debug(
        "identify_image[%s]: strategy=%s readings=%d observations=%d",
        perception.image_id, strategy.value, len(perception.ocr_readings), len(observations),
    )
    return result.model_copy(update={"rule_observations": observations})
```
**Why this shape**: spec §3 fixes the signature; the PIL→BGR conversion is CPU work, so it goes
through the executor as a module-level function (spec §2 Stage 1 / §7). Readings are attached
before dispatch because `_area` (TASK-3858) reads `perception.ocr_readings`.

### FILL IN checklist
- [ ] `evidence.py::build_zone_prompt` / `build_region_prompt` — neutral wording; bounded by AC7
- [ ] `evidence.py::_region_box` — scale/clamp; bounded by spec §2 "normalized [x1,y1,x2,y2]"
- [ ] `evidence.py::collect_rule_evidence` zones + regions; bounded by AC7, AC12, spec §7
- [ ] `stages/identify.py::identify_image` strategy dispatch; bounded by AC3

---

## Acceptance Criteria

- [ ] AC7: evidence prompts never contain a binding's `required`/`expected` params, a definition zone id, or a product; `unknown` answers yield `assessed=False`.
- [ ] AC7: without an observed zone or a configured region crop, no `zone_present` observation is produced (nothing is inferred from absence).
- [ ] AC12: one failed evidence crop is recorded in `ctx.errors`, others still produce observations; `CancelledError` propagates.
- [ ] AC3: `identify_image` dispatches `full_image` / `strips` / `slots` from `ctx.layout.identify_strategy` and passes `descriptor_fields` / `substrip_max_slots`.
- [ ] AC5: after `identify_image`, `perception.ocr_readings` holds the own-box readings; `ocr_available` mirrors `ctx.ocr`.
- [ ] No provider call is made when `ctx.bindings` requests no illumination / visual / zone-presence evidence.
- [ ] `ruff check` / `black --check --line-length 120` pass on the four files.

---
- [ ] Lint/format clean: `ruff check packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/evidence.py packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/stages/identify.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_rule_evidence.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_stage_identify.py`
- [ ] Lint/format clean: `black --check --line-length 120 packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/evidence.py packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/stages/identify.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_rule_evidence.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_stage_identify.py`

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_rule_evidence.py -q`
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_stage_identify.py -q`
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_identify.py -q`

---

## Test Specification

```python
# packages/ai-parrot-pipelines/tests/planogram_cycle/test_rule_evidence.py
import asyncio
import numpy as np
import pytest

from parrot.models.detections import DetectionBox
from parrot_pipelines.planogram.comparison.definition import RuleBinding
from parrot_pipelines.planogram.contracts import CycleContext, FixtureMembership, PerceptionResult, Shape, ShapeKind
from parrot_pipelines.planogram.identification.evidence import (
    EVIDENCE_STAGE, RegionPresenceAnswer, ZoneEvidenceAnswer, collect_rule_evidence,
)
from parrot_pipelines.planogram.identification.vision import VisionError
from parrot_pipelines.planogram.layout import LayoutProfile, ZoneSelector
from parrot_pipelines.planogram.perception.profiles import PRICE_TAG_PROFILE


class InlineExecutor:
    async def run(self, fn, *args):
        return fn(*args)


class RecordingVision:
    """Queued answers; records (prompt, stage); raises queued exceptions."""
    def __init__(self, *answers): self.answers, self.prompts = list(answers), []
    async def ask(self, prompt, images, schema, *, stage, prompt_version, system_prompt=None):
        assert stage == EVIDENCE_STAGE
        self.prompts.append(prompt)
        item = self.answers.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

# fixture: 400x300 BGR image; perception with one ON_FIXTURE zone "img0:zone0" (box 20,10,380,80)


async def test_no_bindings_no_calls(): ...
    # ctx.bindings=[] -> [] and RecordingVision.prompts == []


async def test_illumination_observation_is_neutral(): ...
    # binding {"kind": "illumination", "target_id": "zone_header", "params": {"required": "off", "penalty": 0.3}}
    # answer illumination="on" -> one observation(kind="illumination", value="on", assessed=True, target_id="img0:zone0")
    # prompt: "required" not in lower(); "zone_header" absent; "0.3" absent


async def test_unknown_illumination_is_unassessed(): ...
    # answer illumination="unknown" -> observation.assessed is False


async def test_visual_features_recorded_as_seen(): ...
    # binding visual_features -> value == answer.visual_features; target is the observed zone id


async def test_off_fixture_zone_not_inspected(): ...
    # zone membership OFF_FIXTURE -> no call


async def test_failed_crop_is_isolated(): ...
    # two zones, first VisionError -> ctx.errors has "evidence_failed", second zone still observed


async def test_region_inspected_only_without_observed_zone(): ...
    # layout zone_selectors=[ZoneSelector(zone_id="zone_header", region=(0.0, 0.0, 1.0, 0.3))], zone_present binding
    # with an observed zone centre inside -> no region call; with perception.zones=[] -> one call,
    # target_id == "img0:zone-region:zone_header", present "no" -> value False, assessed True


async def test_region_unknown_stays_unassessed(): ...
    # present "unknown" -> assessed False, value None


async def test_cancellation_propagates(): ...
    # RecordingVision(asyncio.CancelledError()) -> pytest.raises(asyncio.CancelledError)


# packages/ai-parrot-pipelines/tests/planogram_cycle/test_stage_identify.py
from PIL import Image
from parrot_pipelines.planogram.contracts import IdentificationResult, IdentifyStrategy, OcrReading
from parrot_pipelines.planogram.stages import identify as stage


async def test_requires_layout(): ...
    # ctx.layout None -> pytest.raises(ValueError, match="layout")


@pytest.mark.parametrize("strategy,expected", [("full_image", "identify_full_image"),
                                               ("strips", "identify_strips"), ("slots", "identify_slots")])
async def test_dispatches_configured_strategy(monkeypatch, strategy, expected): ...
    # monkeypatch each stage.<fn> with a recorder returning IdentificationResult(image_id="img0");
    # only `expected` is called, with vocabulary == layout.descriptor_fields; strips gets substrip_max_slots


async def test_ocr_readings_attached_before_dispatch(monkeypatch): ...
    # monkeypatch stage.read_target_text -> {"img0:r0:s1": OcrReading(text="62XL", confidence=0.9)};
    # the strategy recorder sees perception.ocr_readings already set; perception.ocr_available mirrors ctx.ocr


async def test_rule_observations_attached(monkeypatch): ...
    # monkeypatch stage.collect_rule_evidence -> [obs]; result.rule_observations == [obs]
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
9. **Close the task** with `scripts/sdd/close_task.sh TASK-3859 refactor-planogram-compliance verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

Merged cleanly via sdd-worker orchestration; lint clean.

