# TASK-3439: LLM detector fallback and closed-set verification pass

**Feature**: FEAT-574 — New Planogram Compliance Pipeline
**Spec**: `sdd/specs/new-planogram-pipeline.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3435, TASK-3436, TASK-3437
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 12**, the two auxiliary LLM passes of stage 2:

1. **LLM detector fallback (goal G7).** When the usable on-fixture shapes of a photo fall under the
   type's threshold, the LLM proposes boxes on the full image and the cycle continues with
   `detection_source="llm"`. It is also the *primary* detector of `ProductOnShelves` while its
   `perception_mode` is `"llm_detector"`. Fallback observations obey the **same fixture-membership
   validation** as CV shapes — the fallback never bypasses membership or the unknown-state rules.
2. **Closed-set verification.** An optional second look at identifications that stayed unresolved:
   the LLM chooses among a few candidate products of the definition (plus "other" / "cannot tell").
   Spec §2: *"An admissible exact match needs … product-discriminating evidence tied to the crop.
   Neither a rectangle nor an expected SKU offered in a verification prompt is sufficient.
   Unresolved identity remains unresolved regardless of source or self-reported confidence."* — so
   an offered SKU is **never** evidence by itself; the answer is accepted only through an evidence gate.

Both go through `VisionAdapter` (`parrot_pipelines.planogram.identification.vision`, TASK-3436), use
candidates from `SlotsDefinition` (`parrot_pipelines.planogram.comparison.definition`, TASK-3435) and
`assign_membership` (`parrot_pipelines.planogram.perception.membership`, TASK-3437).

---

## Scope

- `detector.py`: `llm_detect_shapes(image, image_id, ctx, *, prompt) -> List[Shape]` exactly as in the
  spec skeleton, plus `DETECT_PROMPT_VERSION`, `GENERIC_DETECTION_PROMPT` and a picklable
  downscale-and-encode helper. Structured output schema: the **existing** `Detections` model
  (normalised 0..1 boxes) → pixel `DetectionBox` in the **source image**. Degenerate boxes dropped.
  Every shape has `source=ObservationSource.LLM`, `profile="llm_detector"`, `ocr_text` from
  `Detection.content`. Shapes of kind `ZONE` are passed as `zones` to `assign_membership`, the rest
  get their membership from it. Any failure ⇒ `[]` and one message appended to `ctx.errors` (never raises).
- `verify.py`: `verify_unresolved(image, identifications, definition, ctx, *, n_distractors=3, boxes=None)
  -> List[Identification]`, plus `VERIFY_PROMPT_VERSION`, `CHOICE_OTHER`, `CHOICE_CANNOT_TELL`,
  `pick_candidates`, `option_order` and the local response schema. Returns a **new** list (same
  order, same length); inputs are never mutated.
- Candidate selection works from what the identification *partially read* (brand / descriptor
  fields) — not from a registered expectation. No partial read ⇒ no call, identification unchanged.
- Evidence gate: a choice is accepted only when it is one of the offered products **and** the
  answer's evidence cites at least one discriminating token of that candidate (identifier, alias,
  family, or a `display_name` token) that is visible text — otherwise the identification stays unresolved.
- One failed verification call is isolated: that identification is returned unchanged and the error
  goes to `ctx.errors`.
- Offline tests listed under Test Specification.

**NOT in scope**: deciding *when* to fall back (the `run()` template task compares
`usable_shapes` with the type threshold); the per-type fallback prompt text; registration, scoring,
conflict handling; the main identification strategies (TASK-3438); OCR.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/detector.py` | CREATE | LLM detector fallback |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/verify.py` | CREATE | Closed-set, evidence-gated verification |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_detector_verify.py` | CREATE | Offline unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references. Dependency-created symbols are copied from the spec skeletons —
> re-read the dependency's file before use and fix this contract FIRST if a name differs.

### Verified Imports
```python
import asyncio, hashlib, logging
from typing import Dict, List, Optional, Sequence, Tuple
import cv2
import numpy as np
from pydantic import BaseModel, Field
from parrot.models.detections import Detection, Detections, DetectionBox       # verified: packages/ai-parrot/src/parrot/models/detections.py:24, :32, :37
from parrot_pipelines.planogram.contracts import (                             # created by TASK-3421 (transitive dependency)
    CycleContext, Identification, ObservationSource, Shape, ShapeKind)
from parrot_pipelines.planogram.identification.vision import VisionError, encode_png    # created by TASK-3436
from parrot_pipelines.planogram.comparison.definition import FacingDefinition, SlotsDefinition   # created by TASK-3435
from parrot_pipelines.planogram.perception.membership import assign_membership           # created by TASK-3437
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/models/detections.py
class BoundingBox(BaseModel):                         # :5-22   x1, y1, x2, y2: float in [0, 1]
    def get_pixel_coordinates(self, width: int, height: int) -> tuple[int, int, int, int]   # :16-22  (x1, y1, x2, y2) ints
class Detection(BaseModel):                           # :24-29  label: Optional[str]; confidence: float (0..1, required);
                                                      #         content: Optional[str]; bbox: BoundingBox
class Detections(BaseModel):                          # :32-34  detections: List[Detection] = []
class DetectionBox(BaseModel):                        # :37-60  x1,y1,x2,y2: int; confidence: float (REQUIRED); label; ocr_text …

# Created by TASK-3421 — parrot_pipelines/planogram/contracts.py  (spec §2 Data Models)
class ShapeKind(str, Enum):         # PRICE_TAG, PRODUCT, BOX, FACT_TAG, ZONE, UNKNOWN   (re-read the string values)
class ObservationSource(str, Enum): # CV, LLM_ADDED, LLM, LEGACY_LLM
class Shape(BaseModel):             # shape_id, image_id, kind, box: DetectionBox, profile, row_index, slot_index,
                                    # ocr_text, ocr_confidence, source, membership, membership_evidence
class Identification(BaseModel):    # shape_id, image_id, product, brand, text, descriptors, raw_confidence, evidence, source, uncertain
class CycleContext(BaseModel):      # vision, executor (has `async run(fn, *args)`), ocr, definition, bindings, …, errors: List[str]

# Created by TASK-3436 — parrot_pipelines/planogram/identification/vision.py
class VisionAdapter:
    async def ask(self, prompt: str, images: Sequence[bytes], schema: Type[T], *, stage: str,
                  prompt_version: str, system_prompt: Optional[str] = None) -> T      # raises VisionError
def encode_png(image: np.ndarray) -> bytes            # module-level, picklable

# Created by TASK-3435 — parrot_pipelines/planogram/comparison/definition.py
class Descriptors(BaseModel):       # display_name, family, xl, colors, pack, identifiers, aliases, price
class FacingDefinition(BaseModel):  # facing_id, shelf_id, slot, product, brand, facings, facing_index, position, descriptors
class SlotsDefinition(BaseModel):   # version, meta, shelves, zones;  def all_facings(self) -> List[FacingDefinition]

# Created by TASK-3437 — parrot_pipelines/planogram/perception/membership.py
def assign_membership(shapes: Sequence[Shape], zones: Sequence[Shape], image_size: Tuple[int, int],
                      *, llm_hints: Optional[Dict[str, FixtureMembership]] = None) -> List[Shape]
```

Existing precedent for `structured_output=Detections` on a full image:
`packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py:825-833`
(`_find_poster`, downscaled image, `max_tokens=8192`).

Algorithmic reference (**read-only, NEVER imported**): `examples/planogram/plancheck/verify.py` —
`CHOICE_OTHER` / `CHOICE_CANNOT_TELL` :23-24, `pick_distractors` :27-69 (same brand; tier 1 same
family, tier 2 neighbours; never more than `n`), `option_order` :72-74 (deterministic order seeded by
`sha256(f"{slot_id}|{sku}")` so the likeliest option is not always first), `verify_rows` :172 (a failed
call fails only its own unit).

### Does NOT Exist
- ~~`client.detect_objects` in the new cycle~~ — the fallback goes through `VisionAdapter.ask`, never the provider's `detect_objects` (Google's hard-codes its model).
- ~~a box on `Identification`~~ — identifications carry no geometry; crops come from the optional `boxes` mapping (`shape_id → DetectionBox`). No box ⇒ that identification is skipped.
- ~~a registered expectation as verification input~~ — this function receives no registration; candidates derive from the partial read only.
- ~~`ctx.semaphore`~~ — the adapter owns the semaphore.
- ~~`Catalog` / `PlanogramRef` / `SlotObservation`~~ — reference-engine models, not available here.
- ~~modifying `raw_confidence` by a source weight~~ — evidence weights never touch it.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/detector.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/verify.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_detector_verify.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/models/detections.py#Detections",
    "sym:packages/ai-parrot/src/parrot/models/detections.py#Detection",
    "sym:packages/ai-parrot/src/parrot/models/detections.py#BoundingBox",
    "sym:packages/ai-parrot/src/parrot/models/detections.py#DetectionBox"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Images are untouched full-resolution BGR `np.ndarray`s. Downscale/crop/encode are CPU work: module-level
  picklable helpers called as `await ctx.executor.run(helper, image, ...)` with plain tuples/ints only.
- Because `Detections` boxes are normalised 0..1, the detector may send a downscaled copy
  (longest side ≤ 2048) and still map boxes to **source** pixels with `get_pixel_coordinates(width, height)` of the source.
- `llm_detect_shapes` never raises for a model/transport failure: catch `VisionError`, log with
  `logger.warning`, append `f"llm_detector {image_id}: {exc}"` to `ctx.errors`, return `[]`.
  `asyncio.CancelledError` propagates.
- Shape ids are pipeline-owned: `f"{image_id}:llm:{n}"` (1-based, response order after dropping degenerate boxes).
- Label → kind: the prompt asks for a `label` drawn from the `ShapeKind` values; anything else ⇒ `ShapeKind.UNKNOWN`.
- `verify_unresolved` targets = identifications with `product is None or uncertain` that have a box **and** a partial read.
- Accepted verification: copy with `product=<choice>`, `uncertain=False`, `evidence += [f"verify: {answer.evidence}"]`,
  `raw_confidence=<the verification answer's confidence, unscaled>`; `source` unchanged.
- Tests: `PYTHONPATH=packages/ai-parrot-pipelines/src:packages/ai-parrot/src` inside a worktree.

### References in Codebase
- `examples/planogram/plancheck/verify.py` — reference (re-implemented against package models).
- Spec §2 (evidence rules), §3 Module 12, §7 "No/too few shapes ⇒ fallback; if it also fails ⇒ `not_assessed` + `errors`".

---

## Implementation Blueprint

### Steps (in order)
1. Write `detector.py` — *why*: smallest unit; it fixes the pattern (executor → adapter → validate → membership) the verifier reuses.
2. Write `verify.py`: pure helpers first (`pick_candidates`, `option_order`, `_evidence_supports`), then the coroutine — *why*: the evidence gate is the safety property of this task and must be testable without an LLM.
3. Write the tests with the inline stub adapter/executor below; run the validation command; `ruff check` both files.

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/detector.py` (CREATE)
```python
"""LLM detector fallback: full-image box proposals through the vision adapter (detection_source="llm")."""
from __future__ import annotations

import logging
from typing import List, Tuple

import cv2
import numpy as np

from parrot.models.detections import Detection, Detections, DetectionBox
from parrot_pipelines.planogram.contracts import CycleContext, ObservationSource, Shape, ShapeKind
from parrot_pipelines.planogram.identification.vision import VisionError, encode_png
from parrot_pipelines.planogram.perception.membership import assign_membership

logger = logging.getLogger(__name__)

DETECT_PROMPT_VERSION: str = "detect-v1"
DETECT_STAGE: str = "detect"
MAX_SIDE: int = 2048
GENERIC_DETECTION_PROMPT: str = ""   # FILL IN: generic instruction — list every product, product box, price/fact tag and
#   header/backlit/poster zone in the photo, one detection each, label ∈ ShapeKind values, normalised 0..1 bbox,
#   `content` = legible text or null; never mention expected products — bounded by spec §3 Module 12


def downscale_and_encode(image: np.ndarray, max_side: int = MAX_SIDE) -> bytes:
    """Resize so the longest side is <= max_side (never upscale) and PNG-encode. Picklable (CPU executor)."""
    height, width = image.shape[:2]
    scale = min(1.0, max_side / float(max(height, width)))
    if scale < 1.0:
        image = cv2.resize(image, (int(width * scale), int(height * scale)), interpolation=cv2.INTER_AREA)
    return encode_png(image)


def _to_shape(detection: Detection, index: int, image_id: str, size: Tuple[int, int]) -> Shape | None:
    """Pixel Shape in SOURCE-image coordinates, or None for a degenerate box."""
    # FILL IN: x1,y1,x2,y2 = detection.bbox.get_pixel_coordinates(*size); clamp to the image; None when x2<=x1 or y2<=y1;
    #   kind from detection.label (unknown → ShapeKind.UNKNOWN); DetectionBox(confidence=detection.confidence, ...)
    raise NotImplementedError


async def llm_detect_shapes(image: np.ndarray, image_id: str, ctx: CycleContext, *, prompt: str) -> List[Shape]:
    """Full-image LLM proposals through VisionAdapter; every shape has source=llm. [] on failure
    (the failure is appended to ctx.errors)."""
    height, width = image.shape[:2]
    try:
        png = await ctx.executor.run(downscale_and_encode, image, MAX_SIDE)
        answer = await ctx.vision.ask(prompt, [png], Detections, stage=DETECT_STAGE,
                                      prompt_version=DETECT_PROMPT_VERSION)
    except VisionError as exc:
        logger.warning("LLM detector failed for %s: %s", image_id, exc)
        ctx.errors.append(f"llm_detector {image_id}: {exc}")
        return []
    # FILL IN: shapes = [_to_shape(...)] minus None, ids f"{image_id}:llm:{n}"; split zones (kind ZONE) from the rest;
    #   return [*zones, *assign_membership(rest, zones, (width, height))] — fallback observations obey membership too
    raise NotImplementedError
```
**Why this shape**: signature fixed by the spec skeleton. Reusing the existing `Detections` model
avoids a second box schema and lets a downscaled image be sent safely (normalised coordinates).
Only `VisionError` is swallowed — a programming error must still surface in tests.

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/verify.py` (CREATE)
```python
"""Closed-set, evidence-gated verification of unresolved identifications."""
from __future__ import annotations

import asyncio
import hashlib
import logging
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
from pydantic import BaseModel, Field

from parrot.models.detections import DetectionBox
from parrot_pipelines.planogram.comparison.definition import FacingDefinition, SlotsDefinition
from parrot_pipelines.planogram.contracts import CycleContext, Identification
from parrot_pipelines.planogram.identification.vision import VisionError, encode_png

logger = logging.getLogger(__name__)

VERIFY_PROMPT_VERSION: str = "verify-v1"
VERIFY_STAGE: str = "verify"
CHOICE_OTHER: str = "other"
CHOICE_CANNOT_TELL: str = "cannot_tell"


class VerificationAnswer(BaseModel):
    """LLM structured output for one crop."""
    choice: str = Field(description="One of the offered product ids, 'other' or 'cannot_tell'")
    visible_text: List[str] = Field(default_factory=list, description="Text actually legible in the crop")
    evidence: str = Field(default="", description="One sentence: what in the crop supports the choice")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


def pick_candidates(identification: Identification, definition: SlotsDefinition, n: int) -> List[FacingDefinition]:
    """Up to ``n + 1`` distinct-product candidates compatible with the PARTIAL READ (brand / descriptors).

    Returns [] when the identification has no partial read — a closed set is never built from expectation alone.
    """
    # FILL IN: same brand (casefold) when a brand was read; a read descriptor field must not contradict the candidate's;
    #   one FacingDefinition per distinct `product`; described candidates first — bounded by reference verify.py:27-69
    raise NotImplementedError


def option_order(shape_id: str, products: Sequence[str]) -> List[str]:
    """Deterministic order seeded by sha256(shape_id|product) — no option is systematically first."""
    return sorted(set(products), key=lambda p: hashlib.sha256(f"{shape_id}|{p}".encode("utf-8")).hexdigest())


def _evidence_supports(answer: VerificationAnswer, candidate: FacingDefinition) -> bool:
    """True only when ``visible_text``/``evidence`` cite a discriminating token of ``candidate``.

    An offered SKU is never evidence by itself: the token must come from the crop (visible_text), not the prompt.
    """
    # FILL IN: tokens = identifiers + aliases + family + display_name words (len >= 3, casefold);
    #   require a token inside the casefolded visible_text — bounded by spec §2 "admissible exact match"
    raise NotImplementedError


def crop_and_encode(image: np.ndarray, box: Tuple[int, int, int, int], pad: float = 0.08) -> bytes:
    """Padded crop clamped to the image, PNG bytes. Picklable (CPU executor)."""
    # FILL IN: mechanical crop + encode_png
    raise NotImplementedError


async def verify_unresolved(image: np.ndarray, identifications: List[Identification],
                            definition: SlotsDefinition, ctx: CycleContext, *, n_distractors: int = 3,
                            boxes: Optional[Dict[str, DetectionBox]] = None) -> List[Identification]:
    """Closed-set pass for unresolved slots. An offered expected SKU is never evidence by itself.

    Returns a NEW list, same order and length. Untouched when: already resolved, no box, no partial read,
    choice is other/cannot_tell/not offered, evidence gate fails, or the call failed (error → ctx.errors).
    """
    # FILL IN: build one coroutine per target (crop via ctx.executor.run, prompt listing option_order(...) + the two
    #   escape choices, ctx.vision.ask(..., VerificationAnswer, stage=VERIFY_STAGE, prompt_version=VERIFY_PROMPT_VERSION));
    #   asyncio.gather; VisionError is caught PER target
    raise NotImplementedError
```
**Why this shape**: the positional signature is the spec's; `boxes` is an additive keyword-only
parameter because `Identification` carries no geometry and a verification without a crop would be
guessing. The gate reads `visible_text` (what the model says it *sees*) rather than the free-text
justification alone, so echoing an offered option cannot pass.

### `packages/ai-parrot-pipelines/tests/planogram_cycle/test_detector_verify.py` (CREATE)
See **Test Specification**. No `__init__.py` in this folder.

### FILL IN checklist
- [ ] `detector.py::GENERIC_DETECTION_PROMPT` — generic, label vocabulary = `ShapeKind` values, no expected products
- [ ] `detector.py::_to_shape` — source-pixel box, clamp, degenerate ⇒ `None`, label→kind
- [ ] `detector.py::llm_detect_shapes` tail — ids, zone split, membership
- [ ] `verify.py::pick_candidates` — partial-read compatibility; `[]` without a partial read; ≤ `n + 1`
- [ ] `verify.py::_evidence_supports` — discriminating token from `visible_text`
- [ ] `verify.py::crop_and_encode`
- [ ] `verify.py::verify_unresolved` — per-target isolation; new list; acceptance rule from Implementation Notes
- [ ] `test_detector_verify.py` — every test body

---

## Acceptance Criteria

- [ ] `from parrot_pipelines.planogram.identification.detector import llm_detect_shapes` and `from parrot_pipelines.planogram.identification.verify import verify_unresolved` work.
- [ ] Detector shapes are in source-image pixels even when a downscaled image was sent; all have `source="llm"`; degenerate boxes are dropped; non-zone shapes carry a membership value.
- [ ] Detector failure ⇒ `[]` and exactly one message in `ctx.errors`; no exception.
- [ ] Verification: no partial read ⇒ zero adapter calls; no box ⇒ skipped; `other` / `cannot_tell` / not-offered choice ⇒ unchanged.
- [ ] A chosen offered SKU **without** supporting visible text stays unresolved; with a cited identifier it becomes resolved (`uncertain=False`, product set, evidence extended).
- [ ] One failed verification call leaves the other targets processed; inputs are never mutated.
- [ ] Option order is deterministic per `shape_id` and differs between shape ids.
- [ ] `ruff check` passes on both files; no `requests`/`httpx`/`print`.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_detector_verify.py -q`

---

## Test Specification

```python
# packages/ai-parrot-pipelines/tests/planogram_cycle/test_detector_verify.py
import numpy as np
import pytest

from parrot.models.detections import BoundingBox, Detection, Detections, DetectionBox
from parrot_pipelines.planogram.comparison.definition import load_slots_definition
from parrot_pipelines.planogram.contracts import CreditPolicy, CycleContext, EvidenceWeights, Identification
from parrot_pipelines.planogram.identification.detector import llm_detect_shapes
from parrot_pipelines.planogram.identification.verify import (
    VerificationAnswer, option_order, pick_candidates, verify_unresolved,
)
from parrot_pipelines.planogram.identification.vision import VisionError


class InlineExecutor:
    async def run(self, fn, *args):
        return fn(*args)


class StubAdapter:
    def __init__(self, *answers): self.answers, self.calls = list(answers), []
    async def ask(self, prompt, images, schema, *, stage, prompt_version, system_prompt=None):
        self.calls.append((stage, prompt))
        item = self.answers.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _ctx(adapter) -> CycleContext:
    return CycleContext(vision=adapter, executor=InlineExecutor(), ocr=None,
                        credit_policy=CreditPolicy.default(), evidence_weights=EvidenceWeights())


async def test_detector_maps_to_source_pixels_and_sets_source_llm(): ...     # 4000x3000 image → boxes in 4000x3000 space
async def test_detector_drops_degenerate_boxes(): ...
async def test_detector_failure_returns_empty_and_records_error(): ...       # StubAdapter(VisionError("x"))
async def test_detector_applies_membership(): ...
def test_pick_candidates_requires_partial_read(): ...
def test_option_order_is_deterministic(): ...
async def test_offered_sku_without_visible_text_is_not_evidence(): ...
async def test_verification_accepts_cited_identifier(): ...
async def test_other_and_cannot_tell_leave_unresolved(): ...
async def test_missing_box_is_skipped_without_call(): ...
async def test_failed_verification_call_is_isolated(): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** (§2 evidence rules, §3 Module 12) for full context
2. **Check dependencies** — TASK-3435, TASK-3436, TASK-3437 completed; re-read their modules and `contracts.py`; update this contract FIRST if a name differs (in particular the `ShapeKind` string values)
3. **Implement** from the blueprint; complete every `# FILL IN:`; never change a fixed signature or path
4. **Verify** acceptance criteria; run the Validation Command with the `PYTHONPATH` prefix
5. Commit only the three files listed; never touch `sdd/`
6. **Fill in the Completion Note**

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
