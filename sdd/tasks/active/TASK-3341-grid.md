# TASK-3341: Tag-anchored slot grid (anchored, gap-filled, untagged row) and strip helpers

**Feature**: FEAT-565 — New Planogram Compliance Algorithm
**Spec**: `sdd/specs/new-planogram-compliance-algo.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3337
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 4: grid** — stage 2 of the pipeline (§2 Overview). Price tags sit on the shelf edge
**below** their products, so every product area ("slot") is derived geometrically from the tag rows
produced by the detection stage (`plancheck/detection.py`, TASK-3340):

- (a) **tag-anchored** slots — one per detected tag;
- (b) **gap-filled** slots — where a tag was missed mid-row and the hole is an unambiguous multiple of
  the row pitch (the detector never invents tags; the *grid* may invent slots, and says so in `origin`);
- (c) one synthesized **untagged row** — the bottom shelf whose tags are out of frame
  (on the real photos: 5 tag rows, 6 shelves).

The module also provides the two strip helpers used by pass 1 / pass 2
(`plancheck/identify.py` TASK-3344, `plancheck/verify.py` TASK-3346): the bounding box of one row and
the conversion of a slot box to Gemini's normalised `[ymin, xmin, ymax, xmax]` 0–1000 convention.

Everything here is pure geometry on the `TagRow` / `Slot` models — no image, no I/O, no LLM.

---

## Scope

- Implement `row_pitch(row)`: median centre-to-centre distance of consecutive tags (original pixels).
- Implement `build_slots(rows, image_size)`: tag-anchored slots, then gap-filled slots, then the
  untagged bottom row, with the geometry rules fixed in spec §2 stage 2 (restated under
  *Key Constraints*). `image_size` is `(width, height)`.
- Implement `strip_box(slots, image_size, pad=0.04)` and `to_strip_norm(box, strip)`.
- Write `examples/planogram/tests/test_plancheck_grid.py` with the five M4 tests of spec §4.

**NOT in scope**: tag detection (`plancheck/detection.py`, TASK-3340); rendering/cropping strips or
drawing Set-of-Marks (`plancheck/identify.py`, TASK-3344); occupancy of any slot (LLM, TASK-3344) —
a synthesized slot is **never** assumed empty here; registration pitches (`plancheck/registration.py`,
TASK-3345, receives `row_pitch` values from the pipeline, TASK-3349); perspective rectification
(spec §1 Non-Goals: axis-aligned boxes only).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/planogram/plancheck/grid.py` | CREATE | `row_pitch`, `build_slots`, `strip_box`, `to_strip_norm` |
| `examples/planogram/tests/test_plancheck_grid.py` | CREATE | Unit tests for Module 4 (spec §4) |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified 2026-09-17 on `dev`. Use these exact imports and names.

### Verified Imports
```python
import logging                   # stdlib
from statistics import median    # stdlib
import pytest                    # tests only
```
No third-party import is needed (no numpy, no cv2): inputs and outputs are Pydantic models and ints.

### Created by dependency tasks (exist only after they land)
```python
# examples/planogram/plancheck/models.py — TASK-3337 (models-core). Inside the package:
from .models import Box, Slot, Tag, TagRow
Box = tuple[int, int, int, int]          # x1, y1, x2, y2 — ORIGINAL image pixels
SlotOrigin = Literal["tag_anchored", "gap_filled", "untagged_row"]
class Tag(StrictModel):                  # extra="forbid"
    tag_id: str; image_id: str; row: int; position: int
    box: Box; crop_box: Box; rectangularity: float
class TagRow(StrictModel):
    image_id: str; row: int               # 1-based, top→bottom
    slope: float; intercept: float        # line through tag CENTRES: y = slope*x + intercept (original pixels)
    tags: list[Tag]                       # left→right
    synthesized: bool = False
class Slot(StrictModel):
    slot_id: str                          # f"{image_id}_r{row:02d}_s{index:02d}"
    image_id: str; row: int; index: int; box: Box
    tag_id: str | None = None; tag_box: Box | None = None; origin: SlotOrigin

# examples/planogram/tests/conftest.py — TASK-3337. Layout constants of the synthetic fixture (tests build TagRows
# by hand from these numbers — they must NOT call plancheck.detection, which is a sibling task):
#   TAG_W=70, TAG_H=30, TAG_X0=150, TAG_DX=220, TAG_ROWS_Y=(300, 650, 1000), TAGS_PER_ROW=6 ; image 1600 (w) × 1200 (h)
#   → tag centres x = 185 + 220*i ; row lines y = 315 / 665 / 1015 (slope 0) ; row pitch 350.
```

### Existing Signatures to Use
```python
# Reference only — the anchored-slot geometry this task adapts. The file lives in the PRIMARY checkout only
# (examples/planogram/inkcheck/ is git-ignored and absent from worktrees); the relevant lines are quoted here:
# examples/planogram/inkcheck/inkcheck/prepare.py:37-60 (verified)
#   centers = [(b[0]+b[2])/2 for b in boxes] ; median_width = median(b[2]-b[0])
#   left  = (centers[j-1]+x)/2 if j else x-median_width*.65                       # :43
#   right = (centers[j+1]+x)/2 if j+1<len(boxes) else x+median_width*.65          # :44
#   left,right = max(left,x-median_width*.85),min(right,x+median_width*.85)       # :46  (never stretch over a missed tag)
#   top = previous["slope"]*x+previous["intercept"]+(b[3]-b[1])*.7   (rows after the first)   # :49
#   gap = rows[1]["intercept"]-row["intercept"] if len(rows)>1 else sh*.2 ; top = b[1]-gap*.7  (first row)  # :51-52
#   bottom = b[1]-3  in inkcheck  →  THE SPEC CHANGES THIS TO  bottom = tag top (b[1])          # :54
```

### Does NOT Exist
- ~~`import inkcheck`~~ / ~~`from inkcheck.prepare import …`~~ — not a package on the path; adapt, never import.
- ~~`TagRow.pitch`~~, ~~`TagRow.median_width`~~, ~~`Tag.center`~~ — not model fields; compute them in this module.
- ~~`Slot.label_box`~~, ~~`Slot.facing_id`~~, ~~`Slot.reviewed`~~ — inkcheck `Region` fields, not `Slot` fields (`tag_box` is the tag rectangle; registration lives on `SlotObservation`).
- ~~`Slot.occupancy`~~ — occupancy is perception (TASK-3344); the grid never marks anything empty.
- ~~a `TagRow` returned for the synthesized row~~ — `build_slots` returns `list[Slot]` only; the synthesized row exists only as slots with `origin="untagged_row"` and `row = last row + 1`.
- ~~`from parrot… import …`~~ / ~~`cv2`, `numpy`~~ — pure module, stdlib + models only; no `print`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "examples/planogram/plancheck/grid.py",
      "action": "CREATE"
    },
    {
      "path": "examples/planogram/tests/test_plancheck_grid.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints (the geometry — normative, from spec §2 stage 2; do not re-decide)
Per tag row, with `cx` = tag centre x, `mw` = median tag width of the row, `th` = tag height
(median tag height of the row for a virtual column), `line(x) = slope*x + intercept`:

1. **Columns.** Start with the real tag centres. Between two consecutive tags at distance `d`, with
   `p = row_pitch(row)` and `k = round(d / p)`: when `k >= 2` **and** `abs(d / p - k) <= 0.25`,
   insert `k-1` virtual centres evenly spaced (`cx_a + j*d/k`); otherwise insert none
   (`d = 2.0 p` → one slot; `d = 1.5 p` → none — `test_gap_fill_*`).
2. **Horizontal bounds** of column `j` over the merged centre list `C` (real + virtual):
   `left = (C[j-1]+C[j])/2` or `C[j] - 0.65*mw` at the row start;
   `right = (C[j]+C[j+1])/2` or `C[j] + 0.65*mw` at the row end;
   then clamp: `left = max(left, C[j] - 0.85*mw)`, `right = min(right, C[j] + 0.85*mw)`.
3. **Vertical bounds.** `bottom = tag top` (`tag.box[1]`; for a virtual column `line(cx) - th/2`).
   `top = line_prev(cx) + 0.7*th` when a previous (upper) tag row exists; for the first row
   `top = tag_top - 0.7*row_gap` with `row_gap = line_next(cx) - line(cx)` when a second row exists,
   else `0.2 * image_height`.
4. **Untagged bottom row.** Only with >= 2 tag rows: `row_pitch_v` = median of `line_{r+1}(xc) - line_r(xc)`
   at `xc = image_width/2`. `remaining = image_height - max(tag.box[3] of the last row)`.
   When `remaining >= 0.6 * row_pitch_v`, synthesize one slot per column of the last row with the **same
   x bounds**, `top = line_last(cx) + 0.7*th`, `bottom = min(image_height, line_last(cx) - th/2 + row_pitch_v)`.
   Row number = last row + 1, `origin="untagged_row"`, `tag_id=None`, `tag_box=None`.
5. Boxes are rounded to int, clipped to `[0, width] × [0, height]`; a box with `x1 >= x2` or `y1 >= y2`
   is skipped (logged at DEBUG). `index` is 1-based left→right **after** gap filling;
   `slot_id = f"{image_id}_r{row:02d}_s{index:02d}"`. Anchored slots carry `tag_id` and `tag_box = tag.box`.

Other constraints: pure module (stdlib + `.models`), no `print` (`logger = logging.getLogger(__name__)`),
strict type hints, Google-style docstrings, black line length 120. Output order: rows top→bottom, slots
left→right, the untagged row last.

### Worked numbers (fixture layout, image 1600×1200) — use them in tests
- Row 1 interior column at `cx=405`: midpoints 295/515, clamps `405 ± 59.5` → x ≈ (346, 464) (clamp wins because
  `mw=70` is small against the 220 pitch); row-start column `cx=185` → x ≈ (140, 244) (`185-45.5`, `185+59.5`).
- Row 1: `top = 300 - 0.7*350 = 55`, `bottom = 300`. Row 2: `top = 315 + 0.7*30 = 336`, `bottom = 650`.
- Untagged row: `remaining = 1200 - 1030 = 170 < 0.6*350 = 210` → none at height 1200; with
  `image_size=(1600, 1300)`: `remaining = 270` → 6 slots, `top = 1015 + 21 = 1036`, `bottom = min(1300, 1350) = 1300`, row 4.
- With wide tags (`width=200`, lefts `100+220*i` → centres `200+220*i`) the clamp is `±170` and the **midpoints** win: interior column `cx=420` → x = (310, 530).

### References in Codebase
- `examples/planogram/plancheck/models.py` (TASK-3337) — `TagRow`, `Tag`, `Slot`, `Box`.
- Spec §2 Overview stage 2; §7 Known Risks ("Missed tag mid-row", "Bottom shelf without tags").

---

## Implementation Blueprint

> Write each block to its path nearly verbatim, then complete every `# FILL IN:` marker.
> Never change a signature, name or path fixed here (spec §3 Module 4).

### Steps (in order)
1. Create `grid.py` part 1 (imports, small geometry helpers, `row_pitch`, `_columns`) — *why*: gap filling must be decided once per row, *before* bounds are computed, so that real neighbours of a hole get their midpoints against the virtual centres.
2. Implement the gap rule as `abs(d/p - round(d/p)) <= 0.25 and round(d/p) >= 2` — *why*: a 1.5× hole is ambiguous (one missed tag or just a wide product?) and the spec requires inventing nothing in that case; the alignment absorbs it as a gap later.
3. Add part 2 (`_x_bounds`, `_y_bounds`, `build_slots`) — *why*: one bounds rule for real and virtual columns keeps the slot row gap-free and overlap-free.
4. Use `bottom = tag top` (not inkcheck's `tag top - 3`) — *why*: fixed by spec §2 stage 2.
5. Synthesize the untagged row from the **columns of the last tag row** and only when `remaining >= 0.6 * row_pitch_v` — *why*: the bottom shelf has products but its tags are out of frame; with less room it is floor/kickplate, not a shelf.
6. Add part 3 (`strip_box`, `to_strip_norm`) — *why*: identify/verify send one row strip plus slot boxes normalised to that strip in Gemini's `[ymin, xmin, ymax, xmax]` 0–1000 order.
7. Write the tests from hand-built `TagRow`s (helper `_row(...)` below) — *why*: this task must not depend on `plancheck/detection.py`, a sibling task running concurrently.
8. Run the validation command and `ruff check` on both files.

### `examples/planogram/plancheck/grid.py` (CREATE) — part 1/3
```python
"""Slot grid derived from price-tag rows: anchored, gap-filled and untagged-row slots (FEAT-565).

Pure geometry over ``TagRow``/``Slot`` models in ORIGINAL image pixels. No image access, no I/O.
Tags sit BELOW their products, so a slot spans from the previous row's line down to its own tag's top.
"""
from __future__ import annotations

import logging
from statistics import median

from .models import Box, Slot, Tag, TagRow

logger = logging.getLogger(__name__)

END_HALF_WIDTH = 0.65      # row-end half width, in median tag widths
CLAMP_HALF_WIDTH = 0.85    # never stretch a slot further than this from its centre
TOP_OFFSET = 0.7           # fraction of tag height below the previous row line / of the row gap above the first row
GAP_TOLERANCE = 0.25       # |d/pitch - k| allowed for gap filling
UNTAGGED_MIN_PITCH = 0.6   # fraction of the vertical row pitch that must remain below the last tag row
FIRST_ROW_GAP_FALLBACK = 0.2   # fraction of image height when there is a single tag row


def _cx(tag: Tag) -> float:
    return (tag.box[0] + tag.box[2]) / 2


def _line_y(row: TagRow, x: float) -> float:
    """Row line (through tag centres) evaluated at ``x``."""
    return row.slope * x + row.intercept


def row_pitch(row: TagRow) -> float:
    """Median centre-to-centre distance of consecutive tags (original pixels); ``0.0`` with fewer than two tags."""
    centres = [_cx(tag) for tag in row.tags]
    gaps = [b - a for a, b in zip(centres, centres[1:])]
    return float(median(gaps)) if gaps else 0.0


def _columns(row: TagRow) -> list[tuple[float, Tag | None]]:
    """Centres of the row's columns left→right: real tags plus virtual centres for unambiguous holes.

    Returns:
        ``[(cx, tag_or_None), ...]`` — ``None`` marks a gap-filled (virtual) column.
    """
    pitch = row_pitch(row)
    columns: list[tuple[float, Tag | None]] = []
    for position, tag in enumerate(row.tags):
        if position and pitch > 0:
            previous = _cx(row.tags[position - 1])
            distance = _cx(tag) - previous
            # FILL IN: k = round(distance / pitch); when k >= 2 and abs(distance / pitch - k) <= GAP_TOLERANCE append
            #   k-1 virtual columns (previous + j * distance / k, None) for j in 1..k-1; otherwise append nothing —
            #   bounded by Key Constraint 1, test_gap_fill_integer_pitch and test_gap_fill_rejects_ambiguous.
            raise NotImplementedError
        columns.append((_cx(tag), tag))
    return columns
```
**Why this shape**: the constants are the spec's numbers, named once. `_columns` is separated from bounds so the
gap decision is testable alone and so *both* neighbours of a hole see the virtual centres when their midpoints are
computed. Remove the placeholder `raise` when the FILL IN is done — the loop structure is final.

### `examples/planogram/plancheck/grid.py` (CREATE) — part 2/3
```python
def _x_bounds(centres: list[float], j: int, median_width: float) -> tuple[float, float]:
    """Horizontal bounds of column ``j``: neighbour midpoints, row-end half widths, then the ±0.85 clamp."""
    cx = centres[j]
    left = (centres[j - 1] + cx) / 2 if j else cx - END_HALF_WIDTH * median_width
    right = (centres[j + 1] + cx) / 2 if j + 1 < len(centres) else cx + END_HALF_WIDTH * median_width
    return max(left, cx - CLAMP_HALF_WIDTH * median_width), min(right, cx + CLAMP_HALF_WIDTH * median_width)


def _clip(box: tuple[float, float, float, float], image_size: tuple[int, int]) -> Box | None:
    """Round, clip to the image, and return ``None`` for a degenerate box."""
    width, height = image_size
    x1, y1 = max(0, round(box[0])), max(0, round(box[1]))
    x2, y2 = min(width, round(box[2])), min(height, round(box[3]))
    return (x1, y1, x2, y2) if x1 < x2 and y1 < y2 else None


def build_slots(rows: list[TagRow], image_size: tuple[int, int]) -> list[Slot]:
    """Build every slot of one image: tag-anchored, gap-filled, then the untagged bottom row.

    Args:
        rows: Tag rows top→bottom (as returned by detection), coordinates in original pixels.
        image_size: ``(width, height)`` of the original image.

    Returns:
        Slots ordered by row then left→right. ``index`` is 1-based within the row after gap filling;
        the synthesized row number is ``last row + 1``. Degenerate boxes are skipped.
    """
    width, height = image_size
    slots: list[Slot] = []
    last_columns: list[tuple[float, float, float]] = []   # (cx, left, right) of the last tag row
    for r, row in enumerate(rows):
        if not row.tags:
            continue
        columns = _columns(row)
        centres = [cx for cx, _ in columns]
        median_width = float(median(tag.box[2] - tag.box[0] for tag in row.tags))
        median_height = float(median(tag.box[3] - tag.box[1] for tag in row.tags))
        last_columns = []
        index = 0
        for j, (cx, tag) in enumerate(columns):
            left, right = _x_bounds(centres, j, median_width)
            last_columns.append((cx, left, right))
            tag_height = float(tag.box[3] - tag.box[1]) if tag else median_height
            bottom = float(tag.box[1]) if tag else _line_y(row, cx) - tag_height / 2
            # FILL IN: top — rows[r-1] line at cx + TOP_OFFSET*tag_height when r > 0; else bottom - TOP_OFFSET*row_gap,
            #   row_gap = _line_y(rows[1], cx) - _line_y(row, cx) if len(rows) > 1 else FIRST_ROW_GAP_FALLBACK*height —
            #   bounded by Key Constraint 3 and test_anchored_slot_geometry (row 1 top 55, row 2 top 336).
            # FILL IN: box = _clip((left, top, right, bottom), image_size); skip (logger.debug) when None; else index += 1 and
            #   append Slot(slot_id=f"{row.image_id}_r{row.row:02d}_s{index:02d}", image_id=row.image_id, row=row.row,
            #   index=index, box=box, tag_id=tag.tag_id if tag else None, tag_box=tag.box if tag else None,
            #   origin="tag_anchored" if tag else "gap_filled") — bounded by Key Constraint 5.
            raise NotImplementedError
    # FILL IN: untagged bottom row — only when len(rows_with_tags) >= 2: row_pitch_v = median of consecutive
    #   _line_y differences at x = width/2; remaining = height - max(tag.box[3] for the last row's tags);
    #   when remaining >= UNTAGGED_MIN_PITCH*row_pitch_v, one slot per entry of last_columns with the SAME left/right,
    #   top = line_last(cx) + TOP_OFFSET*median_height, bottom = min(height, line_last(cx) - median_height/2 + row_pitch_v),
    #   row = last row + 1, origin="untagged_row", tag_id=None, tag_box=None, index 1-based —
    #   bounded by Key Constraint 4 and test_untagged_bottom_row.
    logger.info("built %d slots from %d tag rows", len(slots), len(rows))
    return slots
```
**Why this shape**: `_x_bounds` is the inkcheck rule (`prepare.py:43-46`) applied to the *merged* centre list;
`bottom` is the tag top as the spec demands. `last_columns` carries the last tag row's horizontal bounds to the
untagged row ("using the column boundaries of the row above", spec §2). The grid records `origin` and never says
anything about occupancy — a synthesized slot is an *area to look at*, not an empty slot.

### `examples/planogram/plancheck/grid.py` (CREATE) — part 3/3
```python
def strip_box(slots: list[Slot], image_size: tuple[int, int], pad: float = 0.04) -> Box:
    """Bounding box of one row's slots and their tags, padded and clipped to the image.

    Args:
        slots: Slots of ONE row (non-empty).
        image_size: ``(width, height)`` of the original image.
        pad: Padding per side as a fraction of the union's width (x) and height (y).

    Raises:
        ValueError: ``slots`` is empty.
    """
    if not slots:
        raise ValueError("strip_box needs at least one slot")
    # FILL IN: union of slot.box and (when present) slot.tag_box; pad by pad*union_width / pad*union_height per side;
    #   round and clip to [0, width] × [0, height] — bounded by: every slot box and tag box lies inside the result.
    raise NotImplementedError


def to_strip_norm(box: Box, strip: Box) -> list[int]:
    """Convert an original-pixel box to ``[ymin, xmin, ymax, xmax]`` in 0–1000 relative to ``strip``.

    This is the Gemini ``box_2d`` convention (y first, normalised to 1000). Values are rounded and clipped to 0..1000.
    """
    sx1, sy1, sx2, sy2 = strip
    strip_w, strip_h = sx2 - sx1, sy2 - sy1
    if strip_w <= 0 or strip_h <= 0:
        raise ValueError(f"Degenerate strip: {strip}")
    # FILL IN: ymin = round((box[1]-sy1)/strip_h*1000) … xmax likewise with strip_w; clip each to 0..1000;
    #   return [ymin, xmin, ymax, xmax] — bounded by test_to_strip_norm.
    raise NotImplementedError
```
**Why this shape**: the strip includes the tags so the Set-of-Marks numbers (drawn over the tag area by TASK-3344)
are inside the image sent to the model. The y-first order is easy to get wrong — it is Gemini's native convention
(verified in `packages/ai-parrot-client-google/src/parrot/clients/google/analysis.py`, `box_2d` handling) and is what
the spec fixes for the slot JSON.

### `examples/planogram/tests/test_plancheck_grid.py` (CREATE)
```python
"""Unit tests for plancheck.grid (FEAT-565, spec §4 — Module 4). Hand-built TagRows; no detection, no image."""
from __future__ import annotations

import pytest

from plancheck.grid import build_slots, row_pitch, strip_box, to_strip_norm
from plancheck.models import Slot, Tag, TagRow

IMAGE = (1600, 1200)          # (width, height) of the conftest fixture layout
ROWS_Y = (300, 650, 1000)     # tag tops; row lines are y + 15


def _row(row: int, top: int, lefts: list[int], width: int = 70, height: int = 30, image_id: str = "img") -> TagRow:
    """A horizontal TagRow with one tag per ``left`` x (slope 0, line through the tag centres)."""
    tags = [
        Tag(
            tag_id=f"{image_id}_r{row:02d}_p{i:02d}", image_id=image_id, row=row, position=i,
            box=(x, top, x + width, top + height), crop_box=(x, top, x + width, top + height), rectangularity=1.0,
        )
        for i, x in enumerate(lefts, 1)
    ]
    return TagRow(image_id=image_id, row=row, slope=0.0, intercept=top + height / 2, tags=tags)


def _full_rows() -> list[TagRow]:
    return [_row(r, top, [150 + 220 * i for i in range(6)]) for r, top in enumerate(ROWS_Y, 1)]


def test_anchored_slot_geometry() -> None:
    # FILL IN: build_slots(_full_rows(), IMAGE) → 18 slots, all origin "tag_anchored", ids img_r01_s01 … img_r03_s06,
    #   tag_box == tag box. Row 1: y == (55, 300); row 2: y == (336, 650). Row 1 interior column cx=405: x within ±1 of
    #   (346, 464); row-start column: x within ±1 of (140, 244). Wide tags (width=200, lefts 100+220*i): interior x bounds
    #   are the MIDPOINTS (clamp ±170 does not bind). Slots of a row never overlap horizontally.
    raise NotImplementedError


def test_gap_fill_integer_pitch() -> None:
    # FILL IN: drop the 3rd tag of row 2 (distance 440 = 2×220) → row 2 has 6 slots, the 3rd with origin "gap_filled",
    #   tag_id None, tag_box None, centre x ≈ 625, index 3 and indexes 1..6 contiguous; its y bounds follow the same
    #   rule as its neighbours (336, 650). row_pitch of that row is still 220.
    raise NotImplementedError


def test_gap_fill_rejects_ambiguous() -> None:
    # FILL IN: lefts [150, 370, 700, 920, 1140] (one distance 330 = 1.5×220) → 5 slots, none "gap_filled";
    #   the slots either side of the hole are clamped to ±0.85*70 of their centre (no stretching across the hole).
    raise NotImplementedError


def test_untagged_bottom_row() -> None:
    # FILL IN: IMAGE height 1200 → no "untagged_row" slot (170 < 210). image_size (1600, 1300) → 6 extra slots, row 4,
    #   origin "untagged_row", tag_id/tag_box None, same x bounds as row 3's slots, y == (1036, 1300).
    #   A single tag row → never synthesizes (no vertical pitch). A gap-filled last row → the untagged row has the
    #   gap-filled column too.
    raise NotImplementedError


def test_to_strip_norm() -> None:
    # FILL IN: strip (100, 200, 1100, 700), box (100, 200, 600, 450) → [0, 0, 500, 500]; box equal to the strip →
    #   [0, 0, 1000, 1000]; a box poking outside is clipped to 0..1000; degenerate strip → ValueError.
    raise NotImplementedError


def test_strip_box_contains_slots_and_tags() -> None:
    # FILL IN: slots of row 2 → strip contains every slot.box and tag_box, is clipped to IMAGE, and grows with pad;
    #   strip_box([], IMAGE) → ValueError.
    raise NotImplementedError


def test_row_pitch() -> None:
    # FILL IN: full row → 220.0; one tag → 0.0; a row with one 440 hole among 220 gaps → 220.0 (median).
    raise NotImplementedError
```
**Why this shape**: the first five names are the spec §4 rows for M4 (`test_gap_fill_integer_pitch` /
`test_gap_fill_rejects_ambiguous` are the two halves of one row); the last two cover the helpers that have no row.
Expected numbers come from *Worked numbers* above. The `_row` helper is complete so the executor only writes assertions.

### FILL IN checklist
- [ ] `grid.py::_columns` — gap rule `k >= 2 and abs(d/p - k) <= 0.25`, `k-1` evenly spaced virtual centres.
- [ ] `grid.py::build_slots` — `top` for first row / later rows (Key Constraint 3).
- [ ] `grid.py::build_slots` — clip, skip degenerate, 1-based contiguous `index`, `Slot` construction with the right `origin`.
- [ ] `grid.py::build_slots` — untagged bottom row (Key Constraint 4); remove every placeholder `raise`.
- [ ] `grid.py::strip_box` — union + padding + clip.
- [ ] `grid.py::to_strip_norm` — y-first 0–1000, rounded and clipped.
- [ ] `test_plancheck_grid.py` — seven test bodies per their FILL IN comments.

---

## Acceptance Criteria

- [ ] Anchored slots follow the clamp / midpoint / row-end rules and `top`/`bottom` rules of spec §2 stage 2 (`bottom = tag top`).
- [ ] A hole of `2×pitch` yields exactly one `gap_filled` slot; a hole of `1.5×pitch` yields none and no slot is stretched across it.
- [ ] The untagged bottom row is synthesized only with ≥ 2 tag rows and ≥ 0.6 × vertical row pitch remaining below the last tags; it reuses the last row's column bounds; its slots have `origin="untagged_row"`, no tag.
- [ ] Every `Slot` carries its `origin`; `index` is 1-based and contiguous per row; `slot_id` follows `f"{image_id}_r{row:02d}_s{index:02d}"`; all boxes are inside the image and non-degenerate.
- [ ] `to_strip_norm` returns `[ymin, xmin, ymax, xmax]` ints in 0..1000.
- [ ] `grid.py` imports only the stdlib and `.models`; no `print`.
- [ ] All tests pass: `pytest examples/planogram/tests/test_plancheck_grid.py -q`
- [ ] `ruff check examples/planogram/plancheck/grid.py examples/planogram/tests/test_plancheck_grid.py` is clean.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest examples/planogram/tests/test_plancheck_grid.py -q`

---

## Test Specification

The scaffold is the test-file blueprint block above. Required tests (spec §4, Module 4):

| Test | Asserts |
|---|---|
| `test_anchored_slot_geometry` | clamps, midpoints, row-end widths, top/bottom rules |
| `test_gap_fill_integer_pitch` | `2×pitch` hole → 1 `gap_filled` slot, contiguous indexes |
| `test_gap_fill_rejects_ambiguous` | `1.5×pitch` hole → no synthesized slot, no stretching |
| `test_untagged_bottom_row` | synthesized only when ≥ 0.6 pitch remains (and ≥ 2 rows) |
| `test_to_strip_norm` | 0–1000 `[ymin, xmin, ymax, xmax]`, clipping, degenerate strip |
| `test_strip_box_contains_slots_and_tags` | containment, clipping, empty input |
| `test_row_pitch` | median pitch, robust to one hole |

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** (§2 Overview stage 2, §3 Module 4, §4, §7 Known Risks).
2. **Check dependencies** — TASK-3337 must be in `sdd/tasks/completed/`; confirm `examples/planogram/plancheck/models.py` has `Tag`, `TagRow`, `Slot`, `Box` with the fields listed above.
3. **Verify the Codebase Contract** — if a model field differs from the contract, STOP and report; do not adapt silently.
4. **Update status** in `sdd/tasks/index/new-planogram-compliance-algo.json` → `"in-progress"`.
5. **Implement** from the blueprint blocks; complete every `# FILL IN:`; never change a fixed signature or constant.
6. **Verify** every acceptance criterion; run the validation command (no `PYTHONPATH` prefix needed — no parrot import).
7. **Move this file** to `sdd/tasks/completed/TASK-3341-grid.md` and set the index entry to `"done"`.
8. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
