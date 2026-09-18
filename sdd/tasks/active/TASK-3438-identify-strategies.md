# TASK-3438: Identification strategies (full image, strips) and response validation

**Feature**: FEAT-574 — New Planogram Compliance Pipeline
**Spec**: `sdd/specs/new-planogram-pipeline.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3433, TASK-3435, TASK-3436, TASK-3437
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 12** (goals G6, G7-adjacent, G14) — stage 2 of the cycle. The LLM no longer
*detects*: it receives the stage-1 JSON (targets with ids, boxes and OCR text) **plus the image**
and only identifies what is inside the regions it is handed, confirms or corrects the OCR text, and
returns a confidence per identification. The call granularity is declared by the type:
`FULL_IMAGE` (one call: image + stage-1 JSON) or `STRIPS` (one call per row, Set-of-Marks overlay,
sub-strips above 8 slots). This task implements both strategies and the pure validation of the
LLM's answer, per spec §2 **Observation validity** (quoted verbatim):

> Identification responses carry two collections: `existing_identifications` (unknown IDs are
> invalid references; missing known IDs become uncertain) and `added_shapes` (no authority to pick
> an existing detection/facing ID — validated for image/strip ownership, finite in-bounds boxes,
> positive area, membership and duplicates, then given pipeline-owned IDs with
> `source="llm_added"`). Strip coordinates are normalised into their source image before
> deduplication. Duplicates are resolved within an image before cross-photo merging; concordant
> observations of one facing keep all provenance; incompatible admissible identities become
> `conflict` regardless of source; unreadable evidence never overrides a supported identification;
> CV localisation alone never wins an identity disagreement; registration ties stay uncertain.

(Only the first three sentences are this task's job; merging / conflict / registration belong to the
comparison tasks.)

---

## Scope

- Implement `identify_full_image`, `identify_strips`, `validate_response` with the exact spec signatures,
  plus `IDENTIFY_PROMPT_VERSION`, a prompt builder and a picklable Set-of-Marks renderer.
- **Targets**: the areas handed to the LLM are `perception.slots` when there are any, otherwise the
  on-fixture shapes (`usable_shapes(perception.shapes)`). The target id (`slot_id` or `shape_id`) is
  what comes back in `Identification.shape_id`.
- `STRIPS`: one call per `row_index`; a row with more than `substrip_max_slots` targets is split
  into balanced contiguous chunks; each chunk is cropped with `strip_box`, outlined/numbered when
  `marks=True`, PNG-encoded **through `ctx.executor`**, and sent with boxes normalised by `to_strip_norm`.
- `FULL_IMAGE`: one call, boxes normalised against the whole image.
- `validate_response` (pure, sync): unknown ids in `existing_identifications` → error string, entry
  dropped; duplicate id → first wins; known id missing → uncertain `Identification`; each
  `AddedShape` → `from_strip_norm` into **source-image pixels**, reject non-finite / out-of-bounds /
  zero-area / outside-its-strip boxes and duplicates (IoU > 0.5 against any existing target or an
  already accepted addition); accepted ones get `next_shape_id()` and `source=LLM_ADDED`.
  `raw_confidence` is never modified.
- After validation the strategy functions **re-run membership** (`assign_membership`) over the
  accepted additions so they carry `on_fixture` / `off_fixture` / `uncertain` like any CV shape.
- A failed call (`VisionError`) makes **its** targets uncertain, appends one error string to the
  result and to `ctx.errors`; the other calls continue (`asyncio.gather`, no `return_exceptions` leak).
- `vocabulary` is the list of descriptor field names the type wants reported; every name must be a
  field of `Descriptors` (`ValueError` otherwise).
- Offline tests listed under Test Specification.

**NOT in scope**: the LLM-detector fallback and the closed-set verification pass (TASK-3439);
identity resolution against the definition, registration, scoring; OCR itself (stage 1 already put
`ocr_text` on shapes); acquiring the LLM semaphore (the adapter owns it); the prompt must **not**
mention the planogram or any expected product.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/identify.py` | CREATE | Strategies, prompt builder, mark renderer, response validation |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_identify.py` | CREATE | Offline unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references. Dependency-created symbols are copied from the spec skeletons —
> re-read the dependency's file before use and fix this contract FIRST if a name differs.

### Verified Imports
```python
import asyncio, json, logging, math
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple
import cv2
import numpy as np
from parrot.models.detections import DetectionBox                                   # verified: packages/ai-parrot/src/parrot/models/detections.py:37
from parrot_pipelines.planogram.grid.merger import _compute_iou                     # verified: planogram/grid/merger.py:16 (MODULE-LEVEL function)
from parrot_pipelines.planogram.contracts import (                                  # created by TASK-3421 (transitive dependency)
    AddedShape, CycleContext, Identification, IdentificationResponse, IdentificationResult,
    ObservationSource, PerceptionResult, Shape, ShapeKind, Slot)
from parrot_pipelines.planogram.perception.slots import strip_box, to_strip_norm, from_strip_norm   # created by TASK-3433
from parrot_pipelines.planogram.perception.membership import assign_membership, usable_shapes       # created by TASK-3437
from parrot_pipelines.planogram.identification.vision import VisionError, encode_png                # created by TASK-3436
from parrot_pipelines.planogram.comparison.definition import Descriptors                            # created by TASK-3435
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/models/detections.py:37-60
class DetectionBox(BaseModel):   # x1, y1, x2, y2: int; confidence: float (REQUIRED, 0..1); class_id; class_name; area; label; ocr_text

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/grid/merger.py:16
def _compute_iou(box_a: DetectionBox, box_b: DetectionBox) -> float

# Created by TASK-3421 — parrot_pipelines/planogram/contracts.py  (spec §2 Data Models)
class Shape(BaseModel):            # shape_id, image_id, kind, box: DetectionBox, profile, row_index, slot_index,
                                   # ocr_text, ocr_confidence, source, membership, membership_evidence
class Slot(BaseModel):             # slot_id, image_id, row_index, slot_index, box: DetectionBox, anchor_shape_id, inferred
class PerceptionResult(BaseModel): # image_id, image_size, shapes, slots, zones, row_count, detection_source, ocr_available, legacy, errors
class Identification(BaseModel):   # shape_id, image_id, product, brand, text, descriptors, raw_confidence, evidence, source, uncertain
class AddedShape(BaseModel):       # box_norm (0-1000, [ymin,xmin,ymax,xmax]), kind, product, brand, text, descriptors, raw_confidence, evidence
class IdentificationResponse(BaseModel):   # existing_identifications, added_shapes      ← the LLM structured-output schema
class IdentificationResult(BaseModel):     # image_id, identifications, added, errors
class ObservationSource(str, Enum):        # CV = "cv"; LLM_ADDED = "llm_added"; LLM = "llm"; LEGACY_LLM = "legacy_llm"
class CycleContext(BaseModel):     # vision (VisionAdapter), executor (has `async run(fn, *args)`), ocr, definition, bindings,
                                   # credit_policy, evidence_weights, output_dir, errors: List[str]

# Created by TASK-3433 — parrot_pipelines/planogram/perception/slots.py
def strip_box(slots: Sequence[Slot], image_size: Tuple[int, int], pad: float = 0.04) -> DetectionBox
def to_strip_norm(box: DetectionBox, strip: DetectionBox) -> List[int]          # [ymin, xmin, ymax, xmax] 0-1000 relative to strip
def from_strip_norm(norm: Sequence[int], strip: DetectionBox) -> DetectionBox   # → SOURCE-image pixels; ValueError on non-finite/out-of-range

# Created by TASK-3437 — parrot_pipelines/planogram/perception/membership.py
def assign_membership(shapes: Sequence[Shape], zones: Sequence[Shape], image_size: Tuple[int, int],
                      *, llm_hints: Optional[Dict[str, FixtureMembership]] = None) -> List[Shape]
def usable_shapes(shapes: Sequence[Shape]) -> List[Shape]                       # on_fixture only

# Created by TASK-3436 — parrot_pipelines/planogram/identification/vision.py
class VisionAdapter:
    async def ask(self, prompt: str, images: Sequence[bytes], schema: Type[T], *, stage: str,
                  prompt_version: str, system_prompt: Optional[str] = None) -> T      # raises VisionError
def encode_png(image: np.ndarray) -> bytes                                       # module-level, picklable

# Created by TASK-3435 — parrot_pipelines/planogram/comparison/definition.py
class Descriptors(BaseModel):      # display_name, family, xl, colors, pack, identifiers, aliases, price
```

Algorithmic reference (**read-only, NEVER imported**): `examples/planogram/plancheck/identify.py` —
`SUBSTRIP_MAX_SLOTS = 8` :29, `_plan_calls` :33-70 (balanced contiguous chunks), `render_strip` :73
(2-px numbered outlines, labels drawn over the tag area, never over the product),
`build_identify_prompt` :147-180 (forbids reporting outside listed areas; never mentions the
planogram), `_apply_reading_rules` :188-249 (first occurrence wins, unknown ids dropped+reported,
missing ids → uncertain), `identify_rows` :252-303 (failed call → its slots uncertain + one error).

### Does NOT Exist
- ~~`CellResultMerger._compute_iou`~~ — `_compute_iou` is a module-level function.
- ~~`ctx.semaphore`~~ — the semaphore lives inside the `VisionAdapter`; do not acquire one here.
- ~~`Slot.index` / `Slot.row` / `Slot.box` as a tuple~~ — those are the reference engine's names; here it is `slot_index`, `row_index`, `box: DetectionBox`.
- ~~`IdentificationResponse` item fields `image_id` / `source` trusted from the LLM~~ — if the contracts' item model carries them, overwrite them after validation; they are pipeline-owned.
- ~~an `is_local` backend flag~~ — sub-strip splitting depends only on `substrip_max_slots`.
- ~~any mention of expected products in the identify prompt~~ — forbidden by design.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/identify.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_identify.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/models/detections.py#DetectionBox",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/grid/merger.py#_compute_iou"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- CPU work (crop + draw marks + PNG encode) goes through `await ctx.executor.run(render_marked_strip, ...)`.
  The function must be **module-level** and take only picklable arguments (`np.ndarray`, tuples, lists) —
  never a Pydantic model, a client or the context.
- The image handed in is the **untouched full-resolution** BGR `np.ndarray`; `perception.image_size` is `(width, height)`.
- `DetectionBox.confidence` is required: use the addition's `raw_confidence` for added shapes, `1.0` for synthetic strip / full-image boxes.
- Identification `source`: `ObservationSource.LLM` when `perception.detection_source == "llm"`, else `CV`; additions are `LLM_ADDED`.
- Uncertain entry shape: `uncertain=True`, `raw_confidence=0.0`, `product=None`, `evidence=[<reason>]`
  (reasons: `"missing_in_response"`, `"identify_failed: <msg>"`).
- Deterministic output order: identifications sorted by `(row_index, slot_index)` of their target, additions last.
- Tests: `PYTHONPATH=packages/ai-parrot-pipelines/src:packages/ai-parrot/src` inside a worktree.

### References in Codebase
- `examples/planogram/plancheck/identify.py` — algorithm reference (re-implemented against package models).
- Spec §2 "Observation validity", §3 Module 12, §7 "Invalid LLM structure ⇒ one repair retry, then the strip's slots are uncertain" (the retry is inside the adapter).

---

## Implementation Blueprint

### Steps (in order)
1. Write the module header, constants and `_plan_chunks` — *why*: chunking is pure and testable without any LLM.
2. Write `render_marked_strip` (picklable) and `build_identify_prompt` — *why*: they define exactly what the LLM sees; the prompt must list target ids, marks, 0-1000 boxes and stage-1 OCR text, and the `vocabulary` fields to report.
3. Write `validate_response` — *why*: it is the trust boundary; everything the LLM returns passes through it before it can become an observation.
4. Write the shared `_run_call` coroutine, then the two public strategies on top of it — *why*: both strategies differ only in how targets are grouped and which box the coordinates are relative to.
5. Write the tests with an inline stub adapter and inline executor; run the validation command; `ruff check` the file.

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/identify.py` (CREATE)
```python
"""Stage 2 — structured-input / structured-output identification (full image or Set-of-Marks strips)."""
from __future__ import annotations

import asyncio
import json
import logging
import math
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from parrot.models.detections import DetectionBox
from parrot_pipelines.planogram.comparison.definition import Descriptors
from parrot_pipelines.planogram.contracts import (
    AddedShape, CycleContext, Identification, IdentificationResponse, IdentificationResult,
    ObservationSource, PerceptionResult, Shape, ShapeKind, Slot,
)
from parrot_pipelines.planogram.grid.merger import _compute_iou
from parrot_pipelines.planogram.identification.vision import VisionError, encode_png
from parrot_pipelines.planogram.perception.membership import assign_membership, usable_shapes
from parrot_pipelines.planogram.perception.slots import from_strip_norm, strip_box, to_strip_norm

logger = logging.getLogger(__name__)

IDENTIFY_PROMPT_VERSION: str = "identify-v1"
IDENTIFY_STAGE: str = "identify"
DUPLICATE_IOU: float = 0.5
PixelBox = Tuple[int, int, int, int]


def _plan_chunks(targets: Sequence[Any], substrip_max_slots: int) -> List[List[Any]]:
    """Group targets by row_index (top→bottom); split rows above the cap into balanced contiguous chunks."""
    # FILL IN: n_chunks = ceil(n / cap); chunk_size = ceil(n / n_chunks) — bounded by reference identify.py:33-70
    raise NotImplementedError


def render_marked_strip(image: np.ndarray, strip: PixelBox, marks: List[Tuple[int, PixelBox]]) -> bytes:
    """Crop ``strip`` and draw a 2-px numbered outline per mark; PNG bytes. Picklable — runs in the CPU executor.

    An empty ``marks`` list yields the plain crop. Labels are drawn at the BOTTOM edge of each box so the
    product face is never covered.
    """
    # FILL IN: copy the crop, translate boxes to crop coordinates, cv2.rectangle + cv2.putText, return encode_png(crop)
    raise NotImplementedError


def build_identify_prompt(targets: Sequence[Dict[str, Any]], vocabulary: Sequence[str]) -> str:
    """Instructions + ``AREAS`` JSON (``id``, ``mark``, ``box_2d``, ``ocr_text``).

    Must: forbid reporting on listed ids outside their area; ask to confirm or correct ``ocr_text``; ask for
    product, brand, the ``vocabulary`` descriptor fields, a 0..1 confidence and one-sentence evidence; allow
    products the list missed ONLY under ``added_shapes`` with a 0-1000 ``[ymin,xmin,ymax,xmax]`` box;
    say "use null when not legible — do not guess". Must NOT mention a planogram or expected products.
    """
    # FILL IN: prompt text — bounded by the docstring above and reference identify.py:147-180
    raise NotImplementedError
```

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/identify.py` (CREATE) — continued, part 2/2 (same file: append directly below the previous block)
```python
def validate_response(response: IdentificationResponse, perception: PerceptionResult, *,
                      strip: Optional[DetectionBox], next_shape_id: Callable[[], str]
                      ) -> Tuple[List[Identification], List[Shape], List[str]]:
    """(identifications, accepted added shapes with pipeline-owned ids and source=llm_added, errors).

    ``strip=None`` means the call covered the whole image. Pure and synchronous; never mutates its inputs;
    never alters ``raw_confidence``. Known ids are those of the call's targets WITHIN ``strip``.
    """
    # FILL IN — bounded by spec §2 "Observation validity":
    #   existing: first occurrence wins; unknown id → errors += "unknown id <x>" and drop; known-but-missing → uncertain
    #   added:    from_strip_norm (ValueError → reject), inside strip & image bounds, area > 0,
    #             _compute_iou(...) <= DUPLICATE_IOU against every target box and every accepted addition,
    #             then Shape(shape_id=next_shape_id(), source=ObservationSource.LLM_ADDED, ...) + its Identification
    raise NotImplementedError


async def _run_call(image: np.ndarray, targets: Sequence[Any], strip: DetectionBox, perception: PerceptionResult,
                    ctx: CycleContext, *, vocabulary: Sequence[str], marks: bool,
                    next_shape_id: Callable[[], str]) -> Tuple[List[Identification], List[Shape], List[str]]:
    """One LLM call for ``targets``. VisionError ⇒ every target uncertain + one error string (never raises it)."""
    # FILL IN: png = await ctx.executor.run(render_marked_strip, image, <strip tuple>, <marks or []>)
    #   answer = await ctx.vision.ask(prompt, [png], IdentificationResponse, stage=IDENTIFY_STAGE,
    #                                 prompt_version=IDENTIFY_PROMPT_VERSION)
    #   return validate_response(answer, perception, strip=strip, next_shape_id=next_shape_id)
    raise NotImplementedError


async def identify_full_image(image: np.ndarray, perception: PerceptionResult, ctx: CycleContext,
                              *, vocabulary: Sequence[str]) -> IdentificationResult:
    """One call: whole image + stage-1 JSON. Boxes are normalised against the full image."""
    # FILL IN: _check_vocabulary; targets = slots or usable_shapes; one _run_call with the full-image box, marks=False;
    #   then _finalise(...)
    raise NotImplementedError


async def identify_strips(image: np.ndarray, perception: PerceptionResult, ctx: CycleContext,
                          *, vocabulary: Sequence[str], marks: bool = True,
                          substrip_max_slots: int = 8) -> IdentificationResult:
    """One call per row (sub-strips above the cap), concurrently; a failed strip is isolated."""
    # FILL IN: chunks = _plan_chunks(...); strip = strip_box(chunk, perception.image_size);
    #   results = await asyncio.gather(*(_run_call(...) for chunk in chunks)); then _finalise(...)
    raise NotImplementedError


def _check_vocabulary(vocabulary: Sequence[str]) -> None:
    """ValueError when a name is not a field of Descriptors."""
    unknown = [name for name in vocabulary if name not in Descriptors.model_fields]
    if unknown:
        raise ValueError(f"unknown descriptor fields in vocabulary: {unknown}")
```
**Why this shape**: the three public signatures and `IDENTIFY_PROMPT_VERSION` are fixed by the spec's
Module 12 skeleton. `validate_response` stays pure so the trust boundary is unit-testable without
an event loop. `_run_call` never lets `VisionError` escape — that is what isolates a failed strip.
A `_finalise(perception, ctx, per_call_results) -> IdentificationResult` helper (FILL IN, not shown
to keep the block under the size cap) must: concatenate, re-run
`assign_membership([*perception.shapes, *added], perception.zones, perception.image_size)` and keep
the membership values for the additions only, sort deterministically, and extend `ctx.errors`.

### `packages/ai-parrot-pipelines/tests/planogram_cycle/test_identify.py` (CREATE)
See **Test Specification**. No `__init__.py` in this folder.

### FILL IN checklist
- [ ] `identify.py::_plan_chunks` — balanced contiguous chunks per row; bounded by the reference
- [ ] `identify.py::render_marked_strip` — picklable; labels never over the product face
- [ ] `identify.py::build_identify_prompt` — structured input incl. `ocr_text`; never names expected products
- [ ] `identify.py::validate_response` — every rule of "Observation validity" sentences 1-2; `raw_confidence` untouched
- [ ] `identify.py::_run_call` — executor + adapter; `VisionError` → uncertain targets + error
- [ ] `identify.py::_finalise` — membership revalidation of additions, ordering, `ctx.errors`
- [ ] `identify.py::identify_full_image` / `identify_strips`
- [ ] `test_identify.py` — every test body

---

## Acceptance Criteria

- [ ] `from parrot_pipelines.planogram.identification.identify import identify_full_image, identify_strips, validate_response, IDENTIFY_PROMPT_VERSION` works.
- [ ] `FULL_IMAGE` makes exactly one adapter call; `STRIPS` makes one per row and splits a 20-target row into balanced chunks of ≤ 8.
- [ ] Out-of-bounds, non-finite, zero-area, outside-strip and duplicate additions are rejected with an error string; accepted ones get a pipeline-owned id and `source="llm_added"`; their `raw_confidence` equals the LLM's value.
- [ ] Added-shape coordinates are in **source-image pixels** before the duplicate check.
- [ ] Unknown existing id ⇒ error + dropped; missing known id ⇒ uncertain identification.
- [ ] A failed strip leaves the other strips identified; its targets are uncertain; `result.errors` and `ctx.errors` both record it.
- [ ] Accepted additions carry a membership value after the strategy returns.
- [ ] The prompt contains the stage-1 `ocr_text` and the vocabulary field names, and no product name from any definition.
- [ ] Unknown vocabulary name ⇒ `ValueError`.
- [ ] No blocking CV/encoding call outside `ctx.executor.run`; `ruff check` passes on the file.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_identify.py -q`

---

## Test Specification

```python
# packages/ai-parrot-pipelines/tests/planogram_cycle/test_identify.py
import numpy as np
import pytest

from parrot_pipelines.planogram.contracts import (
    AddedShape, CreditPolicy, CycleContext, EvidenceWeights, IdentificationResponse, PerceptionResult, Slot,
)
from parrot_pipelines.planogram.identification.identify import (
    build_identify_prompt, identify_full_image, identify_strips, validate_response,
)
from parrot_pipelines.planogram.identification.vision import VisionError


class InlineExecutor:
    async def run(self, fn, *args):
        return fn(*args)


class StubAdapter:
    """Pops queued answers; an Exception instance is raised."""
    def __init__(self, *answers): self.answers, self.calls = list(answers), []
    async def ask(self, prompt, images, schema, *, stage, prompt_version, system_prompt=None):
        self.calls.append(prompt)
        item = self.answers.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _ctx(adapter) -> CycleContext:
    return CycleContext(vision=adapter, executor=InlineExecutor(), ocr=None,
                        credit_policy=CreditPolicy.default(), evidence_weights=EvidenceWeights())


@pytest.fixture
def perception() -> PerceptionResult:
    """600x300 image, 2 rows x 3 slots with ocr_text on the anchor shapes."""
    raise NotImplementedError   # FILL IN


def test_added_shapes_validation(perception): ...               # 5 rejections + 1 accepted (pipeline id, llm_added)
def test_added_shape_coordinates_are_source_pixels(perception): ...
def test_unknown_and_missing_existing_ids(perception): ...
async def test_failed_strip_is_isolated(perception): ...        # StubAdapter(answer_row0, VisionError("boom"))
async def test_full_image_makes_one_call(perception): ...
async def test_strips_split_large_rows(): ...                   # 20 targets in one row → 3 calls (7/7/6)
def test_prompt_has_ocr_text_and_vocabulary_not_products(perception): ...
async def test_unknown_vocabulary_raises(perception): ...
async def test_additions_get_membership(perception): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** (§2 Observation validity, §3 Module 12) for full context
2. **Check dependencies** — TASK-3433, TASK-3435, TASK-3436, TASK-3437 completed; re-read their modules and `contracts.py`; update this contract FIRST if a field name differs (in particular the item model of `IdentificationResponse.existing_identifications`)
3. **Implement** from the blueprint; complete every `# FILL IN:`; never change a fixed signature or path
4. **Verify** acceptance criteria; run the Validation Command with the `PYTHONPATH` prefix
5. Commit only the two files listed; never touch `sdd/`
6. **Fill in the Completion Note**

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
