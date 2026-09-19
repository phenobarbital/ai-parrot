# TASK-3433: Row grouping, shelf edges and slot geometry with anchoring rules

**Feature**: FEAT-574 — New Planogram Compliance Pipeline
**Spec**: `sdd/specs/new-planogram-pipeline.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3418, TASK-3421
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 7** (structure half). After shapes are proposed (TASK-3418),
the *perceive* stage must turn loose rectangles into **structure**: rows of
aligned shapes, shelf edges for shelf-anchored fixtures, and **slots** — the
regions where a product facing is expected. Everything downstream of detection
(identification strips, registration, scoring) consumes only rows and slots, so
this is the narrow seam that makes a new planogram type "a shape profile + an
anchoring rule".

The algorithms are re-written, *inspired by* the FEAT-565 reference
(`examples/planogram/plancheck/detection.py::group_rows`,
`grid.py::build_slots / strip_box / to_strip_norm`). The reference knows one
anchoring only — *price tag sits below its product*; here that becomes one
`AnchorRule` among others.

---

## Scope

- `rows.py`: `group_rows` (generalised line-consensus grouping over
  `ShapeCandidate`s) and `detect_shelf_edges` (long horizontal edges).
- `slots.py`: `AnchorRule`, `build_slots` (both rules; gap filling; optional
  untagged bottom row), `strip_box`, `to_strip_norm`, `from_strip_norm`, and the
  small id helper `candidate_shape_id`.
- Offline tests on synthetic candidates/images.

**NOT in scope**: proposing shapes (TASK-3418); OCR; fixture membership; the
process executor; identification/Set-of-Marks rendering; row→shelf
*registration* against a planogram (rows here are *visible* rows, never shelf
identities); editing `perception/__init__.py` (import the new modules by full
module path — that file has a single owner).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/rows.py` | CREATE | `group_rows`, `detect_shelf_edges` |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/slots.py` | CREATE | `AnchorRule`, `build_slots`, strip helpers, `candidate_shape_id` |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_rows_slots.py` | CREATE | Offline unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references. **DO NOT** invent imports, attributes or methods not listed here.

### Verified Imports
```python
import cv2
import numpy as np
from enum import Enum
from statistics import median
from typing import List, Sequence, Tuple
from parrot.models.detections import DetectionBox      # verified: packages/ai-parrot/src/parrot/models/detections.py:37
# Created by TASK-3418 (dependency):
from parrot_pipelines.planogram.perception.profiles import ShapeCandidate
# Created by TASK-3421 (dependency):
from parrot_pipelines.planogram.contracts import Slot
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/models/detections.py:37-60
class DetectionBox(BaseModel):
    x1: int; y1: int; x2: int; y2: int          # :39-42
    confidence: float                            # :43  REQUIRED, ge=0.0 le=1.0  ← every box you build needs one
    class_id: int = None; class_name: str = None; area: int = None   # :53-55
    label: Optional[str] = None; ocr_text: Optional[str] = None      # :56-60

# Created by TASK-3418 (dependency) — planogram/perception/profiles.py
class ShapeCandidate(BaseModel):
    profile: str; kind: str; x1: int; y1: int; x2: int; y2: int; score: float   # SOURCE-image pixels

# Created by TASK-3421 (dependency) — planogram/contracts.py  (spec §2 Data Models)
class Slot(BaseModel):
    slot_id; image_id; row_index; slot_index; box: DetectionBox; anchor_shape_id; inferred
    # Field TYPES are fixed by TASK-3421 — open contracts.py and read them before constructing a Slot.

# REFERENCE ONLY (read, re-implement, NEVER import) — examples/planogram/plancheck/
# detection.py:68-127  group_rows(items, image_width, min_row_labels=4, max_slope=0.12) -> (rows, unassigned)
#     pair (i, j) with |dx| >= 0.2*W and |slope| <= max_slope defines a line             :91-98
#     member gate: residual < 0.40*med_h, 0.6..1.6 x med_h, 0.6..1.6 x med_w            :103-109
#     row needs >= min_row_labels members and x-span >= 0.25*W                          :111-115
#     score = (len(members), -median residual); refit with np.polyfit; members L→R       :116-123
#     rows sorted top→bottom by line height at image centre                             :126
# grid.py:16-21   END_HALF_WIDTH=0.65  CLAMP_HALF_WIDTH=0.85  TOP_OFFSET=0.7  GAP_TOLERANCE=0.25
#                 UNTAGGED_MIN_PITCH=0.6  FIRST_ROW_GAP_FALLBACK=0.2
# grid.py:78      build_slots(rows, image_size) -> list[Slot]   tag-anchored, gap-filled, then untagged bottom row;
#                 index 1-based within the row AFTER gap filling; degenerate boxes skipped
# grid.py:185     strip_box(slots, image_size, pad=0.04) -> Box   union of ONE row's slots (+tags), padded, clipped; ValueError if empty
# grid.py:229-257 to_strip_norm(box, strip) -> [ymin, xmin, ymax, xmax] 0-1000, rounded, clipped; ValueError on degenerate strip
```

### Does NOT Exist
- ~~`from_strip_norm` anywhere in the reference~~ — the inverse transform is new in this task.
- ~~shelf-edge detection anywhere in the repo~~ — rows come only from aligned price tags today; `detect_shelf_edges` is new (Canny/Hough are not used anywhere in `examples/planogram/`).
- ~~`ShapeCandidate.shape_id` / any id on a candidate~~ — candidates have no id; use `candidate_shape_id()` from this task.
- ~~`DetectionBox()` without `confidence`~~ — validation error; the field is required.
- ~~`plancheck.models.Box/Tag/TagRow/Slot` as importable types~~ — reference engine is not a package; use `DetectionBox` and the cycle `Slot`.
- ~~row → planogram-shelf identity here~~ — that is registration, a different task; `row_index` is the *visible* row order only.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/rows.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/slots.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_rows_slots.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/models/detections.py#DetectionBox"
  ]
}
```

---

## Implementation Notes

### Conventions fixed by this task (other tasks rely on them)
- `row_index` is **0-based**, top→bottom. `slot_index` is **1..n per row**,
  left→right, counted **after** gap filling (spec Module 7).
- `slot_id = f"{image_id}:r{row_index}:s{slot_index}"`.
- `anchor_shape_id = candidate_shape_id(image_id, candidate)` for a slot derived
  from a candidate; `None` for an inferred slot. Type hooks that wrap candidates
  into cycle shapes must use the same helper for their shape ids, so a slot can
  always be traced to its anchor.
- Slot box `confidence` = the anchor candidate's `score`; `0.0` for inferred slots.
- Strip-normalised boxes are `[ymin, xmin, ymax, xmax]` in 0–1000 (the Gemini
  `box_2d` convention used by the reference, `grid.py:229`).

### Key Constraints
- Every function is **pure, synchronous, module-level and picklable** (they run
  in a process pool). No logging handlers created at call time, no PIL.
- Deterministic: same input ⇒ same output, including tie-breaks.
- `group_rows` must not invent shapes: a row may contain a gap; leftover
  candidates are simply not returned in any row.
- `build_slots(rule=SHAPE_IS_SLOT)`: each candidate box *is* the slot; `fill_gaps`
  and `untagged_bottom_row` are ignored. `rule=TAG_BELOW_PRODUCT`: the slot is the
  region **above** the tag, bounded by the previous row line (or the
  first-row fallback), x-bounds halfway to the neighbours.
- `from_strip_norm` validates: exactly 4 finite numbers, each in 0..1000,
  `ymax > ymin` and `xmax > xmin`; otherwise `ValueError`. Output is in
  **source-image** pixels (strip offset added back).
- `detect_shelf_edges` returns `[]` rather than raising when nothing is found.
- Inside a worktree: `PYTHONPATH=packages/ai-parrot-pipelines/src:packages/ai-parrot/src`.

### References in Codebase
- `examples/planogram/plancheck/detection.py:68-127` — row consensus (reference only)
- `examples/planogram/plancheck/grid.py:16-21,78-183` — slot geometry constants and algorithm
- `examples/planogram/plancheck/grid.py:185-257` — strip helpers

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block nearly verbatim, then
> complete every `# FILL IN:`. Never change a signature, class name, or path fixed here.

### Steps (in order)
1. Open `planogram/contracts.py` (TASK-3421) and read the exact field types of
   `Slot` — *why*: the blueprint constructs `Slot` by keyword and the types are
   owned by that task.
2. Write `rows.py` — *why*: `build_slots` consumes its output shape.
3. Write `slots.py`.
4. Write the tests; run with the `PYTHONPATH` prefix; `ruff check` both modules.

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/rows.py` (CREATE)
```python
"""Row and shelf-edge structure from proposed shapes (FEAT-574). Pure and picklable."""
from __future__ import annotations

from typing import List, Sequence

import cv2
import numpy as np

from .profiles import ShapeCandidate

_MIN_PAIR_DX = 0.20      # a defining pair must be at least this fraction of the width apart
_MIN_ROW_SPAN = 0.25     # a row must span at least this fraction of the width
_RESIDUAL_TOL = 0.40     # |dy| to the line, in median member heights
_SIZE_BAND = (0.6, 1.6)  # member size relative to the defining pair's median


def group_rows(
    candidates: Sequence[ShapeCandidate], image_width: int, *, min_row_items: int = 4, max_slope: float = 0.12
) -> List[List[ShapeCandidate]]:
    """Group aligned, similarly sized candidates into visible rows.

    Reference: plancheck/detection.py:68. Rows are *visible* rows, not planogram shelf identities.

    Args:
        candidates: Proposed shapes of ONE image (any profile mix; callers usually pass one kind).
        image_width: Source image width in pixels.
        min_row_items: Minimum members for a row.
        max_slope: Maximum |slope| of a row line (perspective tolerance).

    Returns:
        Rows ordered top→bottom, items left→right. Candidates that fit no row are omitted.
        ``[]`` when fewer than ``min_row_items`` candidates are given.
    """
    # FILL IN: greedy best-line consensus exactly as the reference (:87-127) using the module
    #          constants above — bounded by: deterministic tie-break (more members, then lower median
    #          residual, then lower first index); never returns a candidate in two rows.
    raise NotImplementedError


def detect_shelf_edges(image: np.ndarray, *, min_length: float = 0.35) -> List[int]:
    """Y coordinates of long horizontal edges, top→bottom. ``[]`` when none.

    Args:
        image: BGR or gray uint8 source image.
        min_length: Minimum edge length as a fraction of the image width.
    """
    # FILL IN: gray -> blur -> cv2.Canny -> cv2.HoughLinesP(minLineLength=min_length*W) -> keep
    #          |angle| <= ~5 degrees -> cluster y within ~1% of H into one edge (median y) — bounded by:
    #          sorted ascending, ints, no duplicates, [] on a blank image, ValueError on non-image input.
    raise NotImplementedError
```
**Why this shape**: signatures are the spec skeleton verbatim (note
`min_row_items` replaces the reference's `min_row_labels` and the return type is
rows of candidates, not index lists — downstream code wants objects). The
tolerances are module constants, not parameters, because the spec fixes the
public signature.

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/slots.py` (CREATE)
```python
"""Slot geometry with pluggable anchoring rules (FEAT-574). Pure and picklable."""
from __future__ import annotations

from enum import Enum
from statistics import median
from typing import List, Sequence, Tuple

from parrot.models.detections import DetectionBox  # verified: detections.py:37

from ..contracts import Slot
from .profiles import ShapeCandidate

END_HALF_WIDTH = 0.65          # row-end half width, in median anchor widths   (ref grid.py:16)
CLAMP_HALF_WIDTH = 0.85        # never stretch a slot further than this        (ref grid.py:17)
TOP_OFFSET = 0.7               # see ref grid.py:18
GAP_TOLERANCE = 0.25           # |d/pitch - k| allowed for gap filling         (ref grid.py:19)
UNTAGGED_MIN_PITCH = 0.6       # ref grid.py:20
FIRST_ROW_GAP_FALLBACK = 0.2   # ref grid.py:21


class AnchorRule(str, Enum):
    """How a slot is derived from its anchor shape."""

    TAG_BELOW_PRODUCT = "tag_below_product"
    SHAPE_IS_SLOT = "shape_is_slot"


def candidate_shape_id(image_id: str, candidate: ShapeCandidate) -> str:
    """Deterministic id of a candidate: ``"<image_id>:<profile>:<x1>-<y1>-<x2>-<y2>"``."""
    return f"{image_id}:{candidate.profile}:{candidate.x1}-{candidate.y1}-{candidate.x2}-{candidate.y2}"


def build_slots(
    rows: Sequence[Sequence[ShapeCandidate]],
    image_size: Tuple[int, int],
    *,
    image_id: str,
    rule: AnchorRule,
    fill_gaps: bool = True,
    untagged_bottom_row: bool = False,
) -> List[Slot]:
    """Build every slot of one image. Reference: plancheck/grid.py:78.

    Returns:
        Slots ordered by row then left→right. ``slot_index`` is 1..n per row after gap filling;
        gap-filled and synthesized bottom-row slots have ``inferred=True`` and no anchor.
        Degenerate boxes are skipped.
    """
    # FILL IN (SHAPE_IS_SLOT): one slot per candidate, box = candidate box — bounded by: fill_gaps and
    #          untagged_bottom_row ignored; conventions of "Implementation Notes".
    # FILL IN (TAG_BELOW_PRODUCT): port grid.py:78-183 — x-bounds halfway to neighbours (END/CLAMP
    #          half widths at row ends), y from previous row line + TOP_OFFSET (FIRST_ROW_GAP_FALLBACK for
    #          row 0), gap filling when |d/pitch - k| <= GAP_TOLERANCE, optional bottom row when at least
    #          UNTAGGED_MIN_PITCH of a row pitch remains below the last row — bounded by AC-3..AC-5.
    raise NotImplementedError


def strip_box(slots: Sequence[Slot], image_size: Tuple[int, int], pad: float = 0.04) -> DetectionBox:
    """Padded, clipped union of ONE row's slots. Raises ValueError when ``slots`` is empty."""
    # FILL IN — bounded by: confidence=1.0 on the returned box; pad is a fraction of the union size per side.
    raise NotImplementedError


def to_strip_norm(box: DetectionBox, strip: DetectionBox) -> List[int]:
    """[ymin, xmin, ymax, xmax] in 0-1000 relative to the strip (rounded, clipped)."""
    # FILL IN: port of grid.py:229-257 — bounded by: ValueError("degenerate strip") when w or h <= 0.
    raise NotImplementedError


def from_strip_norm(norm: Sequence[int], strip: DetectionBox) -> DetectionBox:
    """Inverse of to_strip_norm, into SOURCE-image pixels. Raises ValueError on non-finite/out-of-range."""
    # FILL IN — bounded by: validation list in "Key Constraints"; confidence=1.0; result clipped to the strip.
    raise NotImplementedError
```
**Why this shape**: spec-skeleton signatures verbatim. `candidate_shape_id` is the
one addition — candidates carry no id, and `Slot.anchor_shape_id` would
otherwise be unusable; a pure function of the geometry keeps it deterministic
across processes. Constants are copied by value from the reference (we never
import it). Boxes are `DetectionBox` so no parallel box vocabulary appears.

### `packages/ai-parrot-pipelines/tests/planogram_cycle/test_rows_slots.py` (CREATE)
Write the **Test Specification** scaffold to this path and complete the bodies.

### FILL IN checklist
- [ ] `rows.py::group_rows` — consensus loop, deterministic tie-breaks
- [ ] `rows.py::detect_shelf_edges` — Canny + HoughLinesP + y clustering
- [ ] `slots.py::build_slots` — both rules, gap filling, bottom row
- [ ] `slots.py::strip_box`, `to_strip_norm`, `from_strip_norm`
- [ ] `test_rows_slots.py` — every body

---

## Acceptance Criteria

- [ ] AC-1: 3 synthetic rows × 8 candidates (slight slope, jittered sizes) ⇒ 3 rows, top→bottom, items left→right; 3 stray candidates appear in no row.
- [ ] AC-2: fewer than `min_row_items` candidates ⇒ `[]`; a row whose x-span is < 25 % of the width is rejected.
- [ ] AC-3: `TAG_BELOW_PRODUCT` on a row with one missing tag and `fill_gaps=True` ⇒ n+1 slots, `slot_index == [1..n+1]`, exactly one `inferred=True` with `anchor_shape_id is None`; with `fill_gaps=False` ⇒ n slots.
- [ ] AC-4: every anchored slot lies strictly **above** its tag (`slot.box.y2 <= tag.y1 + 1`) and inside the image.
- [ ] AC-5: `untagged_bottom_row=True` adds a synthesized last row (all `inferred=True`) only when enough vertical room remains; otherwise no row is added.
- [ ] AC-6: `SHAPE_IS_SLOT` returns one slot per candidate with the candidate's box and `anchor_shape_id == candidate_shape_id(...)`.
- [ ] AC-7: `from_strip_norm(to_strip_norm(b, strip), strip)` is within ±2 px of `b` for boxes inside the strip; NaN/inf, a value outside 0..1000, wrong length or an inverted box raise `ValueError`.
- [ ] AC-8: `strip_box([])` raises `ValueError`; the strip is clipped to the image.
- [ ] AC-9: `detect_shelf_edges` finds the y of 3 drawn horizontal shelf lines (±3 px) and returns `[]` on a blank image.
- [ ] AC-10: all public functions survive `pickle.dumps`.
- [ ] No linting errors: `ruff check` on both new modules.
- [ ] All tests pass (see Validation Commands).

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_rows_slots.py -q`

---

## Test Specification

```python
# packages/ai-parrot-pipelines/tests/planogram_cycle/test_rows_slots.py
"""Offline tests for row grouping, shelf edges and slot geometry."""
import math
import pickle

import cv2
import numpy as np
import pytest

from parrot.models.detections import DetectionBox
from parrot_pipelines.planogram.perception.profiles import ShapeCandidate
from parrot_pipelines.planogram.perception.rows import detect_shelf_edges, group_rows
from parrot_pipelines.planogram.perception.slots import (
    AnchorRule, build_slots, candidate_shape_id, from_strip_norm, strip_box, to_strip_norm,
)

W, H = 2000, 1500


def _tag(x: int, y: int, w: int = 120, h: int = 50) -> ShapeCandidate:
    return ShapeCandidate(profile="price_tag", kind="price_tag", x1=x, y1=y, x2=x + w, y2=y + h, score=0.9)


def _tag_rows(n_rows: int = 3, n_cols: int = 8, skip: tuple[int, int] | None = None) -> list[ShapeCandidate]:
    """Grid of tags with a slight slope; ``skip=(row, col)`` leaves a gap."""
    ...  # FILL IN


def test_group_rows_orders_rows_and_items(): ...            # AC-1
def test_group_rows_rejects_short_or_sparse_rows(): ...     # AC-2
def test_group_rows_and_gap_filled_slots(): ...             # AC-3 (spec §4 name)
def test_anchored_slots_sit_above_their_tags(): ...         # AC-4
def test_untagged_bottom_row_only_with_room(): ...          # AC-5
def test_shape_is_slot_rule(): ...                          # AC-6
def test_strip_norm_roundtrip_and_bounds(): ...             # AC-7 (spec §4 name)


@pytest.mark.parametrize("bad", [[0, 0, 10], [0, 0, math.nan, 10], [0, 0, 1001, 10], [500, 0, 100, 10]])
def test_from_strip_norm_rejects_invalid(bad):
    strip = DetectionBox(x1=0, y1=0, x2=1000, y2=500, confidence=1.0)
    with pytest.raises(ValueError):
        from_strip_norm(bad, strip)


def test_strip_box_empty_raises_and_clips(): ...            # AC-8
def test_detect_shelf_edges_synthetic_and_blank(): ...      # AC-9


def test_public_functions_are_picklable():                  # AC-10
    for fn in (group_rows, detect_shelf_edges, build_slots, strip_box, to_strip_norm, from_strip_norm):
        pickle.dumps(fn)
```

---

## Agent Instructions

1. **Read the spec** (§3 Module 7, §2 Data Models, §6 reference-engine anchors)
2. **Check dependencies** — TASK-3418 and TASK-3421 are merged
3. **Verify the Codebase Contract** — read `Slot` in `planogram/contracts.py`, and
   re-read the reference lines you port; update the contract FIRST if anything moved
4. **Implement** from the blueprint; complete every `# FILL IN:`; never change a fixed signature
5. **Verify** all acceptance criteria
6. **Commit code only** — never touch `sdd/`, never edit `perception/__init__.py`
7. **Fill in the Completion Note** in your final report

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
