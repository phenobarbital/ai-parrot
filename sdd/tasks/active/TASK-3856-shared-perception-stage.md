# TASK-3856: Shared CV perception stage and fallback geometry rebuild

**Feature**: FEAT-612 — Refactor Planogram Compliance
**Spec**: `sdd/specs/refactor-planogram-compliance.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3854, TASK-3855
**Assigned-to**: unassigned

---

## Context

Spec §2 **"Stage 1: observed geometry"** and §3 **Module 2**. Today two types compose the
perception primitives by hand — `InkWall.perceive` (`types/ink_wall.py:168-222`, price tags →
`group_rows` → `build_slots(TAG_BELOW_PRODUCT, fill_gaps=True, untagged_bottom_row=True)`) and
`ProductOnShelves.perceive` / `_rows_and_slots` (`types/product_on_shelves.py:378-511`, profiles →
shelf-edge bands → `build_slots(SHAPE_IS_SLOT)`) — and the orchestrator's LLM fallback
(`plan.py:253-281`) returns replacement shapes with `slots=[]`, so comparison loses slot geometry
(spec §6 corrections: "`plan.py:279` resets slots; M2/M11 must rebuild geometry"). This task
extracts ONE profile-driven geometry pipeline into `planogram/stages/perceive.py` that every type
(TASK-3864..3869) calls, and that the orchestrator (TASK-3871) calls again after a successful
fallback so rows, slots, anchor ids and membership stay usable.

---

## Scope

- Create the package `planogram/stages/` with an `__init__.py` that has a docstring only (no
  re-exports: spec §2 "New helper imports are direct module imports"; TASK-3859/3863 add sibling
  modules without touching `__init__.py`).
- Implement `perceive_image(image, image_id, ctx)`: run the *configured* perception of
  `ctx.layout` only — `cv` proposes shapes with `profile.shape_profiles` / `work_width`;
  `llm_detector` asks `llm_detect_shapes` with `GENERIC_DETECTION_PROMPT` — then build geometry
  through `rebuild_geometry`. It NEVER triggers the automatic fallback (orchestrator-owned).
- Implement `rebuild_geometry(image, shapes, image_id, ctx, *, detection_source)`: zones split,
  rows (per `anchor_rule`), `build_slots` with `fill_gaps` / `untagged_bottom_row`, anchor ids
  remapped to the input shape ids, `row_index`/`slot_index` set, zone selectors matched, membership
  assigned, detection source reported (`mixed` when retained shapes have different sources).
- Implement `count_usable_targets(perception, profile)`: on-fixture anchor/product targets relevant
  to the profile; zone-only profiles count usable zones.
- Dispatch CPU-bound work (PIL→BGR conversion, `propose_shapes`, `detect_shelf_edges`,
  `group_rows`) through `ctx.executor.run` with **module-level picklable wrappers** taking only
  positional arguments.
- Write `tests/planogram_cycle/test_shared_perception.py`.

**NOT in scope**: the fallback decision / threshold comparison / "at most once" rule and error
reporting for a failed fallback (TASK-3871 owns fallback: it calls `count_usable_targets`,
`llm_detect_shapes` and then `rebuild_geometry`); OCR of any target (TASK-3857 `read_target_text`
— perceive leaves `ocr_readings` empty and `ocr_available=False`); storing images in `ctx.images`
(TASK-3871); per-type default profiles and switching the types to this stage (TASK-3864..3869);
editing `types/*.py`, `plan.py` or any `perception/*.py` primitive.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/stages/__init__.py` | CREATE | Package marker, docstring only |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/stages/perceive.py` | CREATE | `perceive_image`, `rebuild_geometry`, `count_usable_targets` + picklable CPU wrappers |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_shared_perception.py` | CREATE | Offline geometry / threshold / provenance tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
import numpy as np
from PIL import Image
from parrot.models.detections import DetectionBox                                                   # detections.py:37
from parrot_pipelines.planogram.contracts import (CycleContext, FixtureMembership, ObservationSource,
    PerceptionResult, Shape, ShapeKind, Slot)                                                        # contracts.py:322, 35, 26, 86, 50, 15, 67
from parrot_pipelines.planogram.identification.detector import GENERIC_DETECTION_PROMPT, llm_detect_shapes  # detector.py:22, 85
from parrot_pipelines.planogram.perception.membership import assign_membership, usable_shapes       # membership.py:192, 249
from parrot_pipelines.planogram.perception.profiles import ShapeCandidate, ShapeProfile            # profiles.py:53, 10
from parrot_pipelines.planogram.perception.rows import detect_shelf_edges, group_rows              # rows.py:88, 20
from parrot_pipelines.planogram.perception.shapes import propose_shapes                            # shapes.py:128
from parrot_pipelines.planogram.perception.slots import AnchorRule, build_slots, candidate_shape_id # slots.py:27, 115, 34
```

### Existing Signatures to Use
```python
# perception/shapes.py:128 — pure, picklable; kw-only work_width => needs a positional wrapper
def propose_shapes(image: np.ndarray, profiles: Sequence[ShapeProfile], *, work_width: int = 2048) -> List[ShapeCandidate]
# perception/rows.py:20 — kw-only min_row_items / max_slope => needs a positional wrapper
def group_rows(candidates: Sequence[ShapeCandidate], image_width: int, *, min_row_items: int = 4,
               max_slope: float = 0.12) -> List[List[ShapeCandidate]]
# perception/rows.py:88 — positional call is fine: ctx.executor.run(detect_shelf_edges, bgr) (as product_on_shelves.py:407)
def detect_shelf_edges(image: np.ndarray, *, min_length: float = 0.35) -> List[int]
# perception/slots.py:115 — pure; fill_gaps / untagged_bottom_row only act for TAG_BELOW_PRODUCT (docstring :126-131)
def build_slots(rows, image_size: Tuple[int, int], *, image_id: str, rule: AnchorRule, fill_gaps: bool = True,
                untagged_bottom_row: bool = False) -> List[Slot]
def candidate_shape_id(image_id: str, candidate: ShapeCandidate) -> str   # slots.py:34 "<image_id>:<profile>:<x1>-<y1>-<x2>-<y2>"
# perception/membership.py:192 — pure; returns copies in the same order; zones are evidence, may be []
def assign_membership(shapes, zones, image_size, *, llm_hints=None) -> List[Shape]
def usable_shapes(shapes) -> List[Shape]                                   # membership.py:249 — ON_FIXTURE subset
# perception/profiles.py:53
class ShapeCandidate(BaseModel): profile: str; kind: str; x1, y1, x2, y2: int; score: float (0..1)
# perception/executor.py:62
class CpuExecutor: async def run(self, fn: Callable[..., T], *args: Any) -> T    # positional args only, fn module-level
# identification/detector.py:85 — [] on VisionError (error appended to ctx.errors); shapes have profile="llm_detector",
#   ids "<image_id>:llm:<n>", source=ObservationSource.LLM (detector.py:76-83)
async def llm_detect_shapes(image: np.ndarray, image_id: str, ctx: CycleContext, *, prompt: str) -> List[Shape]
GENERIC_DETECTION_PROMPT: str                                                   # detector.py:22 (no product names)
# contracts.py
class PerceptionResult(BaseModel): image_id, image_size (w, h), shapes, slots, zones, row_count,
    detection_source: str = "cv", ocr_available: bool = False, legacy=None, errors         # :86-98
class Shape(BaseModel): shape_id, image_id, kind, box: DetectionBox, profile, row_index, slot_index, ocr_text,
    ocr_confidence, source, membership, membership_evidence: List[str]                   # :50-64
class Slot(BaseModel): slot_id, image_id, row_index, slot_index, box, anchor_shape_id, inferred   # :67-76
```

Reference compositions to port (read, do not edit):
- `types/ink_wall.py:179-209` — TAG_BELOW_PRODUCT path (anchors = price tags, `group_rows`, row/slot index from slot anchors).
- `types/product_on_shelves.py:394-425` and `:449-511` (`_rows_and_slots`) — SHAPE_IS_SLOT path (shelf-edge
  bands, else vertical-centre bands; `ShapeCandidate` built from each Shape; `by_candidate` map back to shape ids).
- `types/product_on_shelves.py:427-446` (`_candidate_to_shape`) — candidate → Shape (unknown kind → `ShapeKind.UNKNOWN`).

### Symbols created by dependency tasks (not yet on dev)
```python
# TASK-3855 — planogram/layout.py
class ZoneSelector(BaseModel): zone_id: str; profile: str | None; kind: str | None; ordinal: int | None;
                               region: tuple[float, float, float, float] | None
class LayoutProfile(BaseModel): shape_profiles: list[ShapeProfile]; anchor_rule: AnchorRule; fill_gaps: bool;
    untagged_bottom_row: bool; perception_mode: Literal["cv", "llm_detector"]; min_usable_shapes: int;
    min_row_items: int; max_row_slope: float; work_width: int; zone_selectors: list[ZoneSelector]; ...
# TASK-3854 — contracts.py
CycleContext.layout: Any = None          # holds the resolved LayoutProfile
PerceptionResult.ocr_readings: dict[str, OcrReading] = {}   # stays empty here
```

### Does NOT Exist
- ~~`parrot_pipelines.planogram.stages`~~ — this task creates the package.
- ~~A `fallback` / `min_usable_shapes` comparison inside the stage~~ — the orchestrator owns it (spec §2, M2 skeleton docstring).
- ~~`Shape.zone_id` / `PerceptionResult.zone_bindings`~~ — no such fields; record selector matches as
  `membership_evidence` entries (see Implementation Notes).
- ~~`CpuExecutor.run(fn, *args, **kwargs)`~~ — keyword arguments are NOT forwarded; never pass kwargs, lambdas, `functools.partial` of bound methods or closures.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/stages/__init__.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/stages/perceive.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_shared_perception.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/shapes.py#propose_shapes",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/rows.py#group_rows",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/rows.py#detect_shelf_edges",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/slots.py#build_slots",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/slots.py#candidate_shape_id",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/slots.py#AnchorRule",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/membership.py#assign_membership",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/membership.py#usable_shapes",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/profiles.py#ShapeCandidate",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/executor.py#CpuExecutor.run",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/detector.py#llm_detect_shapes",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/detector.py#GENERIC_DETECTION_PROMPT",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py#PerceptionResult",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py#Shape",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py#CycleContext",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/ink_wall.py#InkWall.perceive",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py#ProductOnShelves._rows_and_slots",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py#ProductOnShelves._candidate_to_shape"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
- The geometry tail is ONE private coroutine used by both the CV path and `rebuild_geometry` —
  spec §2: fallback "calls the SAME geometry-building helper so slots, anchor ids, row indices and
  membership remain usable". `perceive_image` in `cv` mode is literally
  `rebuild_geometry(image, cv_shapes, image_id, ctx, detection_source="cv")`.
- **Anchor rule dispatch**:
  - `TAG_BELOW_PRODUCT` → anchors = shapes of kind `PRICE_TAG`; rows = `group_rows(anchors_as_candidates,
    width, min_row_items=profile.min_row_items, max_slope=profile.max_row_slope)`;
    `build_slots(..., rule=TAG_BELOW_PRODUCT, fill_gaps=profile.fill_gaps, untagged_bottom_row=profile.untagged_bottom_row)`.
  - `SHAPE_IS_SLOT` → anchors = kinds `PRODUCT`, `BOX`, `UNKNOWN` (never `FACT_TAG`, `PRICE_TAG`, `ZONE`);
    rows = shelf-edge bands from `detect_shelf_edges`, else vertical-centre bands (port of
    `_rows_and_slots`); drop bands with fewer than `profile.min_row_items` members (their shapes keep
    `row_index=None`); `build_slots(..., rule=SHAPE_IS_SLOT, fill_gaps=profile.fill_gaps,
    untagged_bottom_row=profile.untagged_bottom_row)`.
- **Anchor id remap**: `build_slots` names anchors with `candidate_shape_id(image_id, candidate)`.
  Build every candidate from a Shape and keep `{candidate_shape_id(...): shape.shape_id}` so LLM
  shapes (`"<image_id>:llm:<n>"`) keep their own ids as `Slot.anchor_shape_id` (port of `product_on_shelves.py:479-509`).
- **Zone selectors** (spec §2 selector paragraph): for each selector, candidates = observed zones
  whose `profile` equals `selector.profile` (if set), whose `kind.value` equals `selector.kind` (if
  set), and whose box centre lies inside `selector.region` scaled to the image (if set). Group the
  selectors by `(profile, kind, region)`. A group with one selector and exactly one candidate
  matches it. When a group has several selectors, sort candidates top-to-bottom, then
  left-to-right, and apply `ordinal` ONLY when the candidate count equals the number of selectors
  in the group (full view); otherwise the group stays unmatched (partial view must not shift zones).
  Record a match as `membership=FixtureMembership.ON_FIXTURE` plus
  `membership_evidence += [f"zone_selector:{zone_id}"]` on the zone copy. Never create a zone for an
  unmatched selector.
- **Detection source**: map each shape's source to `"cv"` (`ObservationSource.CV`) or `"llm"`
  (`LLM`, `LLM_ADDED`); if all input shapes (zones included) map to the `detection_source` argument
  report it, otherwise report `"mixed"`; an empty shape list reports the argument.
- **Usable-target count** (`count_usable_targets`):
  - zone-only profile (`profile.shape_profiles` non-empty and every `kind == "zone"`): count zones whose
    `membership_evidence` contains a `zone_selector:` entry when `profile.zone_selectors` is non-empty,
    else every zone. Unmatched zones never count (spec: "unresolved zone membership cannot suppress fallback").
  - `TAG_BELOW_PRODUCT`: `len` of on-fixture `PRICE_TAG` shapes (`usable_shapes`).
  - otherwise: `len` of on-fixture `PRODUCT` / `BOX` / `UNKNOWN` shapes — tags and zones never
    inflate product counts (spec §2 Stage 1).

### Key Constraints
- Pure stage helpers: no retained state on modules, never mutate the input `shapes` list or the
  profile; return new `Shape` copies (`model_copy(update=...)`).
- `ctx.layout` must be a `LayoutProfile`; if it is `None` raise `ValueError("CycleContext.layout is not set")`
  — silently defaulting would hide a construction bug.
- Coordinates stay in source pixels: the CV proposer already rescales from `work_width`; never resize the image here.
- `llm_detector` mode with no shapes returned: append `f"{image_id}: llm_detector produced no shapes"`
  to `PerceptionResult.errors` (spec §2 "No silent empty success"); do not retry.
- Pickling: every function passed to `ctx.executor.run` is defined at module level in `perceive.py`
  (or an imported module-level primitive) with positional parameters only.
- `build_slots` and `assign_membership` are pure and cheap; call them inline (as both existing types do).
- Run tests with `PYTHONPATH=packages/ai-parrot-pipelines/src:packages/ai-parrot/src`; spawned
  workers cannot import worktree-only Cython builds, so tests use an inline executor stub
  (pattern: `tests/planogram_cycle/test_ink_wall.py:43-53`).

### References in Codebase
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py:253-281` — today's fallback that drops slots (what TASK-3871 will replace with `rebuild_geometry`)
- `packages/ai-parrot-pipelines/tests/planogram_cycle/test_ink_wall.py:82-93, 272-289` — synthetic ink wall image and the geometry assertions to mirror

---

## Implementation Blueprint

### Steps (in order)
1. Create `stages/__init__.py` (docstring only) — *why*: sibling stage modules import directly; no eager imports.
2. Write the module-level CPU wrappers `_to_bgr`, `_propose`, `_group_rows` — *why*: `CpuExecutor.run` forwards positional args only and needs picklable callables.
3. Write `_shape_from_candidate` and `_candidate_from_shape` — *why*: one id scheme for CV and LLM shapes.
4. Write `_rows_tag_below` and `_rows_shape_is_slot` returning candidate rows plus the candidate-id → shape-id map — *why*: anchor rule selects the row primitive.
5. Write `_match_zone_selectors` and `_detection_source` — *why*: selector evidence and honest provenance.
6. Write `rebuild_geometry`, then `perceive_image` on top of it, then `count_usable_targets`.
7. Write the tests; run the validation commands.

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/stages/__init__.py` (CREATE)
```python
"""Shared, profile-driven stage helpers of the perceive → identify → compare cycle (FEAT-612).

Import the stage modules directly (``from parrot_pipelines.planogram.stages.perceive import perceive_image``);
this package deliberately re-exports nothing.
"""
```
**Why this shape**: TASK-3859 (`stages/identify.py`) and TASK-3863 (`stages/compare.py`) add
modules here without editing this file, so it must not import any of them.

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/stages/perceive.py` (CREATE)
```python
"""Stage 1: configured perception and the shared geometry tail reused by the fallback (FEAT-612)."""

from __future__ import annotations

import logging
from typing import Dict, List, Sequence, Tuple

import numpy as np
from PIL import Image

from parrot.models.detections import DetectionBox

from ..contracts import CycleContext, FixtureMembership, ObservationSource, PerceptionResult, Shape, ShapeKind
from ..identification.detector import GENERIC_DETECTION_PROMPT, llm_detect_shapes
from ..layout import LayoutProfile, ZoneSelector
from ..perception.membership import assign_membership, usable_shapes
from ..perception.profiles import ShapeCandidate, ShapeProfile
from ..perception.rows import detect_shelf_edges, group_rows
from ..perception.shapes import propose_shapes
from ..perception.slots import AnchorRule, build_slots, candidate_shape_id

logger = logging.getLogger(__name__)

_PRODUCT_KINDS = (ShapeKind.PRODUCT, ShapeKind.BOX, ShapeKind.UNKNOWN)
SELECTOR_EVIDENCE_PREFIX = "zone_selector:"


def _to_bgr(image: Image.Image) -> np.ndarray:
    """Picklable CPU helper: untouched PIL image -> contiguous BGR array."""
    return np.ascontiguousarray(np.asarray(image.convert("RGB"))[:, :, ::-1])


def _propose(bgr: np.ndarray, profiles: List[ShapeProfile], work_width: int) -> List[ShapeCandidate]:
    """Picklable positional wrapper of ``propose_shapes`` (kw-only ``work_width``)."""
    return propose_shapes(bgr, profiles, work_width=work_width)


def _group_rows(
    candidates: List[ShapeCandidate], image_width: int, min_row_items: int, max_slope: float
) -> List[List[ShapeCandidate]]:
    """Picklable positional wrapper of ``group_rows``."""
    return group_rows(candidates, image_width, min_row_items=min_row_items, max_slope=max_slope)


def _profile(ctx: CycleContext) -> LayoutProfile:
    """The resolved profile of this run; a missing profile is a construction bug."""
    if ctx.layout is None:
        raise ValueError("CycleContext.layout is not set")
    return ctx.layout


def _shape_from_candidate(image_id: str, candidate: ShapeCandidate) -> Shape:
    """CV candidate -> Shape; id scheme equals the one ``build_slots`` uses for anchors."""
    # FILL IN: port product_on_shelves.py:427-446 (unknown kind -> ShapeKind.UNKNOWN, confidence clamped 0..1)


def _candidate_from_shape(shape: Shape) -> ShapeCandidate:
    """Shape -> candidate for the row / slot primitives (profile falls back to "shape")."""
    # FILL IN: port product_on_shelves.py:484-492


async def _rows_tag_below(
    anchors: List[Shape], size: Tuple[int, int], profile: LayoutProfile, ctx: CycleContext
) -> Tuple[List[List[ShapeCandidate]], Dict[str, str]]:
    """Rows of price-tag anchors via ``group_rows`` (min_row_items / max_row_slope from the profile)."""
    # FILL IN: candidates + {candidate_shape_id(image_id, c): shape.shape_id}; rows via
    #          await ctx.executor.run(_group_rows, candidates, size[0], profile.min_row_items, profile.max_row_slope)


async def _rows_shape_is_slot(
    bgr: np.ndarray, anchors: List[Shape], size: Tuple[int, int], profile: LayoutProfile, ctx: CycleContext
) -> Tuple[List[List[ShapeCandidate]], Dict[str, str]]:
    """Shelf-edge bands, else vertical-centre bands (port of ProductOnShelves._rows_and_slots)."""
    # FILL IN: edges = await ctx.executor.run(detect_shelf_edges, bgr); band logic of product_on_shelves.py:463-478;
    #          drop bands with fewer than profile.min_row_items members; rows left->right by x1


def _match_zone_selectors(
    zones: List[Shape], selectors: Sequence[ZoneSelector], size: Tuple[int, int]
) -> List[Shape]:
    """Copies of ``zones``; unambiguously matched ones get ON_FIXTURE + ``zone_selector:<zone_id>`` evidence."""
    # FILL IN: grouping/ordinal rules of Implementation Notes "Zone selectors"; never create a zone — bounded by spec §2
    return list(zones)


def _detection_source(shapes: Sequence[Shape], requested: str) -> str:
    """``requested`` when every shape's source agrees with it, ``"mixed"`` otherwise."""
    # FILL IN: CV -> "cv"; LLM / LLM_ADDED -> "llm"; empty -> requested


async def rebuild_geometry(image: Image.Image, shapes: Sequence[Shape], image_id: str,
                           ctx: CycleContext, *, detection_source: str) -> PerceptionResult:
    """Rebuild rows, slots, zones and membership from replacement source-pixel shapes."""
    profile = _profile(ctx)
    size = (image.width, image.height)
    bgr = await ctx.executor.run(_to_bgr, image)
    zones = [s for s in shapes if s.kind == ShapeKind.ZONE]
    others = [s for s in shapes if s.kind != ShapeKind.ZONE]
    if profile.anchor_rule == AnchorRule.TAG_BELOW_PRODUCT:
        anchors = [s for s in others if s.kind == ShapeKind.PRICE_TAG]
        rows, by_candidate = await _rows_tag_below(anchors, size, profile, ctx)
    else:
        anchors = [s for s in others if s.kind in _PRODUCT_KINDS]
        rows, by_candidate = await _rows_shape_is_slot(bgr, anchors, size, profile, ctx)
    slots = build_slots(rows, size, image_id=image_id, rule=profile.anchor_rule, fill_gaps=profile.fill_gaps,
                        untagged_bottom_row=profile.untagged_bottom_row)
    # FILL IN: remap slot.anchor_shape_id through by_candidate; set row_index/slot_index on the anchor shapes
    #          (port product_on_shelves.py:497-509); zones = _match_zone_selectors(zones, profile.zone_selectors, size);
    #          others = assign_membership(others, zones, size)
    source = _detection_source([*zones, *others], detection_source)
    logger.debug("rebuild_geometry[%s] source=%s shapes=%d slots=%d rows=%d", image_id, source, len(others),
                 len(slots), len(rows))
    return PerceptionResult(image_id=image_id, image_size=size, shapes=others, slots=slots, zones=zones,
                            row_count=len(rows), detection_source=source, ocr_available=False, errors=[])


async def perceive_image(image: Image.Image, image_id: str, ctx: CycleContext) -> PerceptionResult:
    """Run configured perception only; automatic fallback remains orchestrator-owned."""
    profile = _profile(ctx)
    if profile.perception_mode == "llm_detector":
        bgr = await ctx.executor.run(_to_bgr, image)
        shapes = await llm_detect_shapes(bgr, image_id, ctx, prompt=GENERIC_DETECTION_PROMPT)
        result = await rebuild_geometry(image, shapes, image_id, ctx, detection_source=ObservationSource.LLM.value)
        # FILL IN: when shapes == [] append f"{image_id}: llm_detector produced no shapes" to result.errors (copy)
        return result
    bgr = await ctx.executor.run(_to_bgr, image)
    candidates = await ctx.executor.run(_propose, bgr, list(profile.shape_profiles), profile.work_width)
    shapes = [_shape_from_candidate(image_id, c) for c in candidates]
    return await rebuild_geometry(image, shapes, image_id, ctx, detection_source=ObservationSource.CV.value)


def count_usable_targets(perception: PerceptionResult, profile: LayoutProfile) -> int:
    """Count only on-fixture targets relevant to the anchor/zone strategy."""
    # FILL IN: rules of Implementation Notes "Usable-target count"; use usable_shapes() for on-fixture filtering
```
**Why this shape**: the three public signatures are the M2 skeleton verbatim. `rebuild_geometry`
converts the image itself (it receives a PIL image) so the orchestrator never touches arrays.
`DetectionBox`, `FixtureMembership` are needed by the FILL IN bodies (`_shape_from_candidate`,
`_match_zone_selectors`). `SELECTOR_EVIDENCE_PREFIX` is a module constant so later stages
(TASK-3859/3863) can import it instead of re-typing the string. Never add a fallback call or a
`min_usable_shapes` comparison here.

### FILL IN checklist
- [ ] `_shape_from_candidate` / `_candidate_from_shape` — ports; bounded by the id scheme of `candidate_shape_id`.
- [ ] `_rows_tag_below` / `_rows_shape_is_slot` — anchor-rule dispatch; profile fields reach `group_rows` / band filter (AC3).
- [ ] `rebuild_geometry` — anchor remap, row/slot indices, selectors, membership; AC4 (usable slot geometry after fallback).
- [ ] `_match_zone_selectors` — unambiguous matches only; spec §2 selector paragraph.
- [ ] `_detection_source` — `mixed` provenance; spec §2 Stage 1.
- [ ] `perceive_image` — llm_detector empty result error; no fallback; AC4.
- [ ] `count_usable_targets` — tags never inflate product counts; zone-only counts matched zones; AC4.

---

## Acceptance Criteria

- [ ] `perceive_image` on the synthetic ink-wall image with a price-tag profile (`TAG_BELOW_PRODUCT`,
      `fill_gaps=True`, `untagged_bottom_row=True`, `min_row_items=4`) yields 23 tags, 4 rows of 8 slots,
      one inferred gap slot and an all-inferred bottom row — the same geometry as `test_ink_wall.py:272-289` (AC4).
- [ ] Changing `min_row_items`, `fill_gaps` or `anchor_rule` in the profile changes the produced rows/slots (AC3).
- [ ] `rebuild_geometry` on LLM-sourced shapes (`"<id>:llm:<n>"`) returns non-empty slots whose
      `anchor_shape_id`s are those LLM shape ids and sets `row_index`/`slot_index` on them (AC4).
- [ ] LLM product shapes + CV zones ⇒ `detection_source == "mixed"`; LLM-only ⇒ `"llm"`; CV-only ⇒ `"cv"`.
- [ ] `count_usable_targets` excludes off-fixture/uncertain shapes, never counts fact tags or zones for
      product profiles, counts price tags for tag-below profiles, and counts only selector-matched zones for a
      zone-only profile with selectors (AC4).
- [ ] `perceive_image` never calls the vision adapter in `cv` mode (spy raises on any call) and calls
      `llm_detect_shapes` exactly once in `llm_detector` mode.
- [ ] `_to_bgr`, `_propose`, `_group_rows` are picklable (`pickle.dumps` succeeds).
- [ ] Validation commands pass; `ruff check` and `black --check` clean.
- [ ] Lint/format clean: `ruff check packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/stages/__init__.py packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/stages/perceive.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_shared_perception.py`
- [ ] Lint/format clean: `black --check --line-length 120 packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/stages/__init__.py packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/stages/perceive.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_shared_perception.py`

## Validation Commands

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_shared_perception.py -q`
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_rows_slots.py -q`
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_membership.py -q`

---

## Test Specification

```python
# packages/ai-parrot-pipelines/tests/planogram_cycle/test_shared_perception.py
"""Shared CV perception, geometry rebuild and usable-target counting (FEAT-612, Module 2)."""

import pickle

import cv2
import numpy as np
import pytest
from PIL import Image

from parrot.models.detections import DetectionBox
from parrot_pipelines.planogram.contracts import (
    CycleContext, FixtureMembership, ObservationSource, PerceptionResult, Shape, ShapeKind,
)
from parrot_pipelines.planogram.layout import LayoutProfile, ZoneSelector
from parrot_pipelines.planogram.perception.profiles import PRICE_TAG_PROFILE, ShapeProfile
from parrot_pipelines.planogram.perception.slots import AnchorRule
from parrot_pipelines.planogram.stages import perceive as stage
from parrot_pipelines.planogram.stages.perceive import count_usable_targets, perceive_image, rebuild_geometry

W, H = 2000, 1400
TAG_TOPS = (380, 760, 1100)
PITCH = 220
GAP = (1, 3)


class _InlineExecutor:
    """Runs CPU helpers inline (spawned workers cannot import worktree-only builds)."""

    async def run(self, fn, *args):
        return fn(*args)


class _RaisingVision:
    """Any vision call is a test failure."""

    async def ask(self, *args, **kwargs):
        raise AssertionError("vision must not be called")


def _ink_profile(**overrides) -> LayoutProfile:
    base = dict(shape_profiles=[PRICE_TAG_PROFILE], anchor_rule=AnchorRule.TAG_BELOW_PRODUCT, fill_gaps=True,
                untagged_bottom_row=True, min_row_items=4)
    return LayoutProfile(**{**base, **overrides})


def _ctx(profile: LayoutProfile, vision=None) -> CycleContext:
    return CycleContext(vision=vision or _RaisingVision(), executor=_InlineExecutor(), layout=profile)


@pytest.fixture
def ink_image() -> Image.Image:
    """Same synthetic wall as test_ink_wall.py:82-93 (3 rows x 8 bright labels, one gap)."""
    # FILL IN: copy the synthetic_ink_wall drawing code


def _shape(shape_id, kind, box, source=ObservationSource.LLM, profile="llm_detector") -> Shape:
    return Shape(shape_id=shape_id, image_id="img0", kind=kind, box=DetectionBox(x1=box[0], y1=box[1], x2=box[2],
                 y2=box[3], confidence=0.9), profile=profile, source=source)


async def test_cv_tag_below_geometry_matches_ink_wall(ink_image):
    perception = await perceive_image(ink_image, "img0", _ctx(_ink_profile()))
    assert perception.detection_source == "cv" and perception.row_count == 3
    assert len([s for s in perception.shapes if s.kind == ShapeKind.PRICE_TAG]) == 23
    # FILL IN: 4 slot rows x 8; one inferred slot in row 1; row 3 all inferred; anchors are tag ids


async def test_profile_overrides_reach_primitives(ink_image):
    # FILL IN: fill_gaps=False -> row 1 has 7 slots; untagged_bottom_row=False -> 3 slot rows;
    #          min_row_items=9 -> no rows / no slots


async def test_rebuild_geometry_keeps_llm_anchor_ids(ink_image):
    # FILL IN: 3 LLM PRODUCT shapes side by side + profile(anchor_rule=SHAPE_IS_SLOT, shape_profiles=[], perception_mode=
    #          "llm_detector"); assert slots non-empty, {s.anchor_shape_id} == LLM ids, row_index set on each shape,
    #          detection_source == "llm"


async def test_mixed_source_when_cv_zones_retained(ink_image):
    # FILL IN: LLM products + one CV ZONE shape -> detection_source == "mixed"


def test_count_usable_targets_excludes_off_fixture_and_tags():
    # FILL IN: PerceptionResult with on-fixture PRODUCT x2, off-fixture PRODUCT x1, on-fixture FACT_TAG x3 ->
    #          SHAPE_IS_SLOT profile counts 2; tag-below profile counts on-fixture PRICE_TAG only


def test_zone_only_counts_matched_zones():
    # FILL IN: zone-only profile with one ZoneSelector(region=...) and two zones, one centre inside the region
    #          (evidence "zone_selector:z1"), one outside -> 1; without selectors -> 2


async def test_selector_ordinal_requires_full_view():
    # FILL IN: two selectors (same kind, ordinals 0/1) + only one observed zone -> no zone gets selector evidence


async def test_llm_detector_mode_calls_detector_once(ink_image, monkeypatch):
    # FILL IN: monkeypatch stage.llm_detect_shapes with a counting fake returning [] -> result.errors mentions
    #          "llm_detector produced no shapes" and the fake was awaited exactly once


def test_cpu_helpers_are_picklable():
    for fn in (stage._to_bgr, stage._propose, stage._group_rows):
        assert pickle.loads(pickle.dumps(fn)) is fn


async def test_missing_layout_raises(ink_image):
    with pytest.raises(ValueError, match="layout"):
        await perceive_image(ink_image, "img0", CycleContext(executor=_InlineExecutor()))
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
9. **Close the task** with `scripts/sdd/close_task.sh TASK-3856 refactor-planogram-compliance verified`
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
