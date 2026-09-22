# TASK-3642: Strip orchestration and flattening

**Feature**: FEAT-592 — Amazon Nova 2 Lite slot identification for planogram images
**Spec**: `sdd/specs/nova-image-planogram.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3641
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 4 — the heart of the feature.

`identify_strips` (`identify.py:464`) would have provided this loop, but it
cannot be reused: `_run_call` calls `build_identify_prompt` by module-level name
(`identify.py:331`) with no injection point, and FEAT-592 resolved to a
closed-set prompt. So this task owns a per-row loop built from the **public**
pipeline helpers, reusing `strip_box`, `render_marked_strip`, `to_strip_norm`,
`VisionAdapter.ask` and `validate_response` verbatim (spec §2 Overview, §9 S1).

It also owns the flattening join: `Identification` carries **no box**
(`contracts.py:101-114`) and neither does `IdentificationResult`
(`contracts.py:137-142`), so getting from an answer to `{bbox, brand, product}`
requires an explicit id→box join (spec §9 S6).

---

## Scope

- Implement `FlatDetection` and `RunStats`.
- Implement `identify_strips_closed_set()` — per-row chunked concurrent calls,
  Set-of-Marks rendering through the CPU executor, the missing-id repair prompt,
  per-strip failure isolation, and full call accounting.
- Implement `flatten()` — the id→source-pixel-box join.
- Write unit tests for `flatten` — pure, no AWS.

**NOT in scope**: anything under `packages/` (spec G3 / AC6); importing
underscore-prefixed pipeline internals (`_targets`, `_plan_chunks`, `_area`,
`_id_allocator`, `_finalise`) — supply trivial local equivalents instead; the
CLI, perception or output writing (TASK-3643).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/planogram/aws/identify.py` | CREATE | Strip loop, `FlatDetection`, `RunStats`, `flatten` |
| `examples/planogram/tests/test_nova2_identify.py` | CREATE | Unit tests for the flattening join |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.models.detections import DetectionBox                              # verified: identify.py:14
from parrot_pipelines.planogram.contracts import (                             # verified: identify.py:16-25
    Identification, IdentificationResponse, IdentificationResult,
    ObservationSource, PerceptionResult, Shape, Slot,
)
from parrot_pipelines.planogram.identification.identify import (               # verified: identify.py:90,212
    render_marked_strip, validate_response,
)
from parrot_pipelines.planogram.identification.vision import (                 # verified: vision.py:31,131
    VisionAdapter, VisionError,
)
from parrot_pipelines.planogram.perception.executor import CpuExecutor         # verified: perception/executor.py:17
from parrot_pipelines.planogram.perception.slots import strip_box, to_strip_norm  # verified: slots.py:214,242
from examples.planogram.aws.prompt import (                                    # created by TASK-3641
    NOVA_PROMPT_VERSION, NOVA_STAGE, PlanogramVocabulary, build_nova_identify_prompt,
)
```

### Existing Signatures to Use
```python
# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/identify.py
PixelBox = Tuple[int, int, int, int]                                  # line 35
def render_marked_strip(image: np.ndarray, strip: PixelBox,           # line 90
                        marks: List[Tuple[int, PixelBox]]) -> bytes: ...
    # Crops `strip` and draws a 2-px numbered outline per mark; returns PNG bytes.
    # Picklable — designed to run in the CPU executor. Labels at the BOTTOM edge.
def validate_response(response: IdentificationResponse,               # line 212
                      perception: PerceptionResult, *,
                      strip: Optional[DetectionBox],
                      next_shape_id: Callable[[], str],
                      ) -> Tuple[List[Identification], List[Shape], List[str]]: ...
    # Pure and synchronous; never mutates inputs; never alters raw_confidence.
    # strip=None means the call covered the whole image.
    # Known ids are those of the call's targets WITHIN `strip`.
async def _run_call(...)                                              # line 316 — the REFERENCE loop
    #   line 329: mark_list = [(n, _as_tuple(t.box)) for n, t in enumerate(targets, start=1)] if marks else []
    #   line 331: prompt = build_identify_prompt(areas, vocabulary)   ← NO HOOK: why this task exists
    #   line 335: png = await ctx.executor.run(render_marked_strip, image, _as_tuple(strip), mark_list)
    #   line 338-343: VisionError -> every target uncertain + one error string, NEVER raised
    #   line 344-359: missing-id repair prompt -> a SECOND provider call
    #   line 371-374: "identify_incomplete: missing <ids>" error when still short
    #   line 376-377: a padded strip may contain a neighbouring chunk's target -> keep only own ids
async def identify_strips(image, perception, ctx, *, vocabulary,      # line 464 — NOT reused
                          marks: bool = True, substrip_max_slots: int = 8) -> IdentificationResult: ...
def _id_allocator(perception) -> Callable[[], str]: ...               # line 376 — ids "<image_id>:added:<n>"

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/vision.py
class VisionAdapter:                                                  # line 131
    async def ask(self, prompt: str, images: Sequence[bytes], schema: Type[T], *,   # line 173
                  stage: str, prompt_version: str,
                  system_prompt: Optional[str] = None) -> T: ...
    #   images[0] is the main image, the rest go as reference_images
    #   raises ValueError when images is empty; VisionError on provider failure,
    #   timeout, or an answer still invalid after repair_retries (default 1)

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/slots.py
def strip_box(slots: Sequence[Slot], image_size: Tuple[int, int],     # line 214
              pad: float = 0.04) -> DetectionBox: ...
def to_strip_norm(box: DetectionBox, strip: DetectionBox) -> List[int]: ...   # line 242
    # pixels -> [ymin, xmin, ymax, xmax] 0-1000 relative to `strip`

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/executor.py
class CpuExecutor:                                                    # line 17
    async def run(self, fn: Callable[..., T], *args: Any) -> T: ...   # line 62

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py
class Shape(BaseModel):   # line 50 — "in SOURCE-image pixels"
    shape_id: str; image_id: str; box: DetectionBox
    row_index: Optional[int]; slot_index: Optional[int]; ocr_text: Optional[str]
    source: ObservationSource = ObservationSource.CV
class Slot(BaseModel):    # line 67
    slot_id: str          # "<image_id>:r<row_index>:s<slot_index>"
    row_index: int; slot_index: int; box: DetectionBox
    anchor_shape_id: Optional[str] = None; inferred: bool = False
class Identification(BaseModel):   # line 101 — carries NO box
    shape_id: str; product/brand/text: Optional[str]
    occupancy: str = "unknown"; raw_confidence: float; evidence: List[str]
    source: ObservationSource; uncertain: bool
class IdentificationResult(BaseModel):   # line 137
    image_id: str; identifications: List[Identification]
    added: List[Shape]; errors: List[str]
class DetectionBox(BaseModel):   # parrot/models/detections.py:37
    x1: int; y1: int; x2: int; y2: int; confidence: float
```

### Does NOT Exist
- ~~a prompt-builder hook on `identify_strips` / `_run_call`~~ — `identify.py:331` calls it by name. Do NOT monkeypatch the pipeline; do NOT edit it.
- ~~`Identification.box` / `.bbox`~~ — `Identification` carries **no box** (`contracts.py:101-114`); the join in `flatten` is mandatory.
- ~~`IdentificationResult.boxes`~~ — not a field (`contracts.py:137-142`).
- ~~`IdentifyStrategy.CROPS`~~ — the enum has only `FULL_IMAGE` and `STRIPS` (`contracts.py:43-47`).
- ~~public `plan_chunks` / `targets` / `area` helpers~~ — these exist only as `_`-prefixed privates in `identify.py`; write local equivalents, do not import them.
- ~~`examples/planogram/aws/identify.py`~~ — created by this task. Note it shadows nothing: the pipeline module is imported by its full dotted path.
- ~~`cv2.imread` / `cv2.imwrite` inside a coroutine~~ — every OpenCV call goes through `CpuExecutor.run` (spec §9 S5).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "examples/planogram/aws/identify.py",
      "action": "CREATE"
    },
    {
      "path": "examples/planogram/tests/test_nova2_identify.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/identify.py#render_marked_strip",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/identify.py#validate_response",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/vision.py#VisionAdapter",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/slots.py#strip_box",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/slots.py#to_strip_norm",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py#IdentificationResult"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Define `FlatDetection` and `RunStats` first — *why*: TASK-3643 imports both, so their field names are a published contract.
2. Write the local target/chunk helpers (targets = slots when present else shapes; chunk at 8) — *why*: the pipeline's equivalents are `_`-private and must not be imported.
3. Write the per-strip call body mirroring `_run_call` (`identify.py:329-378`), substituting `build_nova_identify_prompt` — *why*: the mark numbering, the strip padding and the "keep only own ids" rule are load-bearing and already correct there.
4. Count every provider attempt into `RunStats` — *why*: spec §9 S8 — one strip can cost three calls and AC5 requires the number.
5. Isolate a failing strip: catch `VisionError`, emit uncertain identifications plus one error string, never re-raise — *why*: a single bad row must not lose the whole photo.
6. Write `flatten` with the three-way id join — *why*: spec §9 S6; without it there is no bbox in the output at all.
7. Write the `flatten` tests — *why*: the join is pure, and it is the one place a wrong bbox silently corrupts every downstream number.

### `examples/planogram/aws/identify.py` (CREATE)
```python
"""Closed-set strip orchestration for Nova (FEAT-592).

Example-local replacement for identify_strips (verified: identify.py:464), which cannot
be reused: _run_call calls build_identify_prompt by module-level name with no hook
(verified: identify.py:331).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np
from pydantic import BaseModel, Field

from parrot.models.detections import DetectionBox  # verified: identify.py:14
from parrot_pipelines.planogram.contracts import (  # verified: identify.py:16-25
    Identification, IdentificationResponse, IdentificationResult,
    ObservationSource, PerceptionResult, Shape, Slot,
)
from parrot_pipelines.planogram.identification.identify import (  # verified: identify.py:90,212
    render_marked_strip, validate_response,
)
from parrot_pipelines.planogram.identification.vision import VisionAdapter, VisionError  # verified: vision.py:31,131
from parrot_pipelines.planogram.perception.executor import CpuExecutor  # verified: executor.py:17
from parrot_pipelines.planogram.perception.slots import strip_box, to_strip_norm  # verified: slots.py:214,242

from examples.planogram.aws.prompt import (  # TASK-3641
    NOVA_PROMPT_VERSION, NOVA_STAGE, PlanogramVocabulary, build_nova_identify_prompt,
)

logger = logging.getLogger(__name__)

PixelBox = Tuple[int, int, int, int]
Target = Union[Slot, Shape]
SUBSTRIP_MAX_SLOTS: int = 8  # mirrors identify_strips' default (verified: identify.py:471)


class FlatDetection(BaseModel):
    """One row of detections.json. ``bbox`` is ALWAYS source-image pixels."""

    shape_id: str
    bbox: List[int]
    occupancy: str = "unknown"
    brand: Optional[str] = None
    product: Optional[str] = None
    text: Optional[str] = None
    confidence: float = 0.0
    evidence: Optional[str] = None
    source: str = "cv"
    inferred: bool = False
    uncertain: bool = False


class RunStats(BaseModel):
    """Provider-call accounting — one strip can cost up to three calls (spec §9 S8)."""

    strips: int = 0
    failed_strips: int = 0
    calls: int = 0
    cache_hits: int = 0
    incomplete_retries: int = 0
    image_bytes_sent: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    wall_seconds: float = 0.0


def _targets(perception: PerceptionResult) -> List[Target]:
    """Slots when perception produced any, else shapes. Local equivalent of identify.py:58."""
    # FILL IN: return list(perception.slots) or list(perception.shapes) — bounded by:
    #   never import the pipeline's _targets
    raise NotImplementedError


def _target_id(target: Target) -> str:
    """``Slot.slot_id`` or ``Shape.shape_id``."""
    return target.slot_id if isinstance(target, Slot) else target.shape_id


async def identify_strips_closed_set(
    image: np.ndarray,
    perception: PerceptionResult,
    vision: VisionAdapter,
    vocabulary: PlanogramVocabulary,
    *,
    executor: CpuExecutor,
    schema_instruction: str,
    marks: bool = True,
    substrip_max_slots: int = SUBSTRIP_MAX_SLOTS,
) -> Tuple[IdentificationResult, RunStats]:
    """One call per row (sub-strips above the cap), concurrently; a failed strip is isolated.

    Returns:
        The validated result for the whole image, and the call accounting.
    """
    # FILL IN: chunk _targets(perception) by row_index, splitting above
    #   substrip_max_slots; asyncio.gather one _run_strip per chunk; merge the
    #   per-chunk identifications/added/errors into one IdentificationResult and sum
    #   the RunStats — bounded by: chunk order must stay row-major (top->bottom,
    #   left->right) so flatten's output is deterministic
    raise NotImplementedError


async def _run_strip(
    image: np.ndarray,
    targets: Sequence[Target],
    perception: PerceptionResult,
    vision: VisionAdapter,
    vocabulary: PlanogramVocabulary,
    *,
    executor: CpuExecutor,
    schema_instruction: str,
    marks: bool,
    next_shape_id: Callable[[], str],
    stats: RunStats,
) -> Tuple[List[Identification], List[Shape], List[str]]:
    """One provider call for ``targets``; a VisionError becomes uncertain targets, never raises."""
    # FILL IN: mirror identify.py:329-378 exactly, substituting the prompt builder:
    #   1. strip = strip_box(targets, perception.image_size)
    #   2. mark_list = [(n, box_as_tuple(t.box)) for n, t in enumerate(targets, 1)] if marks else []
    #   3. areas = [{"id": _target_id(t), "mark": n if marks else None,
    #                "box_2d": to_strip_norm(t.box, strip), "ocr_text": <t.ocr_text or "">}
    #               for n, t in enumerate(targets, 1)]
    #   4. prompt = build_nova_identify_prompt(areas, vocabulary, schema_instruction)
    #   5. png = await executor.run(render_marked_strip, image, box_as_tuple(strip), mark_list)
    #      -> stats.image_bytes_sent += len(png)
    #   6. answer = await vision.ask(prompt, [png], IdentificationResponse,
    #                                stage=NOVA_STAGE, prompt_version=NOVA_PROMPT_VERSION)
    #      -> stats.calls += 1; on VisionError -> stats.failed_strips += 1 and return
    #         uncertain identifications + one error string (NEVER re-raise)
    #   7. missing ids -> ONE corrective call appending the missing id list
    #      -> stats.incomplete_retries += 1, stats.calls += 1
    #   8. validate_response(answer, perception, strip=strip, next_shape_id=next_shape_id)
    #   9. keep only this call's own ids + its additions (identify.py:376-377)
    #   — bounded by AC5 (every attempt counted) and spec §9 S8
    raise NotImplementedError


def flatten(result: IdentificationResult, perception: PerceptionResult) -> List[FlatDetection]:
    """Join identifications back to source-pixel boxes.

    Identification carries no box (verified: contracts.py:101-114), so the join is
    explicit: slot_id -> Slot.box, shape_id -> Shape.box, added id -> added Shape.box.

    Returns:
        Rows ordered by row then left->right; an unmatched id is skipped and logged.
    """
    # FILL IN: build {slot_id: Slot} / {shape_id: Shape} / {added.shape_id: Shape}
    #   lookups, emit FlatDetection per identification with bbox
    #   [box.x1, box.y1, box.x2, box.y2], source="llm_added" for added ids else "cv",
    #   inferred from Slot.inferred, evidence joined to one string — bounded by
    #   spec §9 S6: NEVER expose Nova's 0-1000 coordinates as the primary bbox
    raise NotImplementedError
```
**Why this shape**: steps 1–9 of `_run_strip` reproduce `_run_call`
(`identify.py:329-378`) because its mark numbering, 4 % strip padding, repair prompt
and "keep only own ids" rule are all load-bearing — the padded strip genuinely can
contain a neighbouring chunk's target, and dropping that filter double-counts
detections. The one intended substitution is the prompt builder. `validate_response`
is passed `strip=<this strip>` (never `None`) because the call covered a strip, not
the whole image. `RunStats` is threaded through rather than returned per call so the
three-call worst case is visible in one place (AC5).

### `examples/planogram/tests/test_nova2_identify.py` (CREATE)
```python
"""Unit tests for the flattening join (FEAT-592, TASK-3642).

Pure-function tests over hand-built contracts: no AWS, no image, no event loop.
"""
from __future__ import annotations

from parrot.models.detections import DetectionBox
from parrot_pipelines.planogram.contracts import (
    Identification, IdentificationResult, ObservationSource, PerceptionResult, Shape, Slot,
)

from examples.planogram.aws.identify import FlatDetection, flatten


def _box(x1: int, y1: int, x2: int, y2: int) -> DetectionBox:
    return DetectionBox(x1=x1, y1=y1, x2=x2, y2=y2, confidence=1.0)


def _perception() -> PerceptionResult:
    """One image, one row, two slots — the second gap-filled."""
    return PerceptionResult(
        image_id="img0",
        image_size=(1000, 800),
        slots=[
            Slot(slot_id="img0:r0:s1", image_id="img0", row_index=0, slot_index=1,
                 box=_box(10, 20, 110, 220), inferred=False),
            Slot(slot_id="img0:r0:s2", image_id="img0", row_index=0, slot_index=2,
                 box=_box(120, 20, 220, 220), inferred=True),
        ],
    )


def test_flatten_joins_slot_ids_to_source_pixels() -> None:
    """A slot identification gets that slot's box, in source pixels."""
    result = IdentificationResult(
        image_id="img0",
        identifications=[
            Identification(shape_id="img0:r0:s1", product="9C228AN", brand="HP",
                           occupancy="occupied", raw_confidence=0.9, evidence=["black HP box"]),
        ],
    )
    rows = flatten(result, _perception())
    assert [r.bbox for r in rows] == [[10, 20, 110, 220]]
    assert rows[0].brand == "HP" and rows[0].occupancy == "occupied"


def test_flatten_marks_inferred_slots() -> None:
    """A gap-filled slot carries inferred=True into the flat row."""
    # FILL IN: identify "img0:r0:s2" as empty; assert rows[0].inferred is True
    #   — bounded by spec §2 Data Models (FlatDetection.inferred)
    raise NotImplementedError


def test_flatten_joins_added_shapes() -> None:
    """An LLM-added shape is emitted with source='llm_added' and its own box."""
    # FILL IN: result.added = [Shape(shape_id="img0:added:1", image_id="img0",
    #   box=_box(300, 20, 400, 220), source=ObservationSource.LLM_ADDED)] plus a
    #   matching Identification; assert source == "llm_added"
    #   — bounded by spec §9 S6: additions must never be confused with CV boxes
    raise NotImplementedError


def test_flatten_skips_unmatched_ids() -> None:
    """An identification whose id matches nothing is dropped, not emitted with a null box."""
    # FILL IN: Identification(shape_id="img0:r9:s9", ...) -> rows == []
    #   — bounded by the flatten docstring ("an unmatched id is skipped and logged")
    raise NotImplementedError


def test_flatten_never_emits_normalised_coordinates() -> None:
    """Every bbox is within the source image, proving 0-1000 values never leak."""
    # FILL IN: assert every coordinate is inside image_size — bounded by spec AC4
    raise NotImplementedError
```
**Why**: `flatten` is the one pure function in this module and the single place a
wrong bbox would silently corrupt every downstream number, so it carries the task's
validation command. The fixtures build contracts by hand — no image, no AWS, no
executor — so the tests stay fast and deterministic. The last case is the cheap
guard against the 0-1000-vs-pixels confusion spec §9 S6 warns about.

### FILL IN checklist
- [ ] `identify.py::_targets` — slots-else-shapes; bounded by: no pipeline private imports
- [ ] `identify.py::identify_strips_closed_set` — row chunking + gather + merge; bounded by row-major determinism
- [ ] `identify.py::_run_strip` — the nine mirrored steps; bounded by `identify.py:329-378` and AC5
- [ ] `identify.py::flatten` — the three-way id join; bounded by spec §9 S6 (source pixels only)
- [ ] `test_nova2_identify.py` — four test bodies; bounded by AC4 and spec §2 Data Models

---

## Acceptance Criteria

- [ ] `identify_strips_closed_set` issues one call per row chunk, concurrently, capped at 8 targets per call.
- [ ] Every PNG is rendered via `CpuExecutor.run(render_marked_strip, ...)`, never inline — spec §9 S5.
- [ ] `validate_response` is called with `strip=<this strip>`, never `None`.
- [ ] A `VisionError` on one strip yields uncertain identifications plus one error string and never propagates; other strips still return results.
- [ ] A response missing requested ids triggers exactly one corrective call, counted in `RunStats.incomplete_retries`.
- [ ] `RunStats.calls` counts every provider attempt including repairs (worst case 3 per strip) — spec AC5, §9 S8.
- [ ] `RunStats.image_bytes_sent` is the sum of the PNG bytes handed to the adapter.
- [ ] `flatten` emits `bbox` as `[x1, y1, x2, y2]` in source-image pixels for every matched id — spec §9 S6.
- [ ] Added shapes are emitted with `source="llm_added"`; unmatched ids are skipped.
- [ ] No underscore-prefixed pipeline symbol is imported.
- [ ] No file under `packages/` is modified — spec AC6.
- [ ] `ruff check` and `black --check --line-length 120` pass — spec AC12.

---

## Validation Commands

- `pytest examples/planogram/tests/test_nova2_identify.py -q`

---

## Test Specification

See the `test_nova2_identify.py` blueprint block above — five cases over `flatten`,
built from hand-constructed `PerceptionResult` / `IdentificationResult` contracts.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above (§3 Module 4, §9 S1/S5/S6/S8).
2. **Check dependencies** — TASK-3641 must be in `sdd/tasks/completed/`; this module
   imports `build_nova_identify_prompt`, `PlanogramVocabulary`, `NOVA_PROMPT_VERSION`
   and `NOVA_STAGE` from it.
3. **Verify the Codebase Contract** — re-read `identify.py:316-378` before mirroring it;
   that loop is the reference implementation and its details are load-bearing.
4. **Update status** in `sdd/tasks/index/nova-image-planogram.json` → `"in-progress"`.
5. **Implement** — start from the blueprint blocks, complete every `# FILL IN:`, and
   never change a signature, class name or file path the blueprint fixes.
6. **Verify** all acceptance criteria are met.
7. **Move this file** to `sdd/tasks/completed/TASK-3642-strip-orchestration-and-flatten.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
