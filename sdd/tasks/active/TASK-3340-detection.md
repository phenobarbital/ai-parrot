# TASK-3340: Price-tag detection and row grouping

**Feature**: FEAT-565 — New Planogram Compliance Algorithm
**Spec**: `sdd/specs/new-planogram-compliance-algo.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3337
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 3: detection** — stage 1 of the pipeline (§2 Overview): find the white electronic
shelf labels (price tags) and group them into visible rows. Tags are the anchors from which the
whole slot grid is derived (`plancheck/grid.py`, TASK-3341), so this stage must
behave **exactly** like the detector that is already proven on the real photos
(`examples/planogram/white_label_detector/detect_price_labels.py`: 56 candidates in 5 rows on
`image_01`).

The spec therefore fixes this module as an **adapted copy** of two functions of that script —
`candidates()` (L15-52) and `group_rows()` (L55-107) — with type hints and docstrings added and
*no numeric change*, plus a new `detect_tags()` wrapper that returns the feature's Pydantic models
(`Tag`, `TagRow`) in **original-image pixels**.

The reference script is adopted into git by TASK-3336 (repo-tracking). This task depends on
TASK-3337, which itself depends on TASK-3336, so the script is present transitively; the parity
test nevertheless `pytest.skip`s when the file is absent so the suite stays green anywhere.

---

## Scope

- Implement `find_candidates(image, min_width=0.025, max_width=0.09)` — same thresholds, geometric
  filters and cross-threshold/nested suppression as the source `candidates()`.
- Implement `group_rows(items, image_width, min_row_labels=4, max_slope=0.12)` — same line-consensus
  algorithm as the source `group_rows()`.
- Implement `detect_tags(image, image_id, *, work_width=2048, roi=None)`: downscale to `work_width`
  (`cv2.INTER_AREA`, only when wider), detect, apply the optional normalised ROI to candidate
  centres, group rows, rescale boxes **and** the fitted row line to original pixels, build `Tag` /
  `TagRow` models, return `(rows, unassigned_boxes)`.
- Write `examples/planogram/tests/test_plancheck_detection.py` with the three M3 tests of spec §4.

**NOT in scope**: slot boxes (`plancheck/grid.py`, TASK-3341); OCR/price reading
(`plancheck/prices.py`, TASK-3343); writing crops or annotated images (`plancheck/report.py`,
TASK-3348); any change to `white_label_detector/detect_price_labels.py` (left untouched);
the `shelf_image` fixture (owned by `examples/planogram/tests/conftest.py`, TASK-3337).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/planogram/plancheck/detection.py` | CREATE | `find_candidates`, `group_rows`, `detect_tags` |
| `examples/planogram/tests/test_plancheck_detection.py` | CREATE | Unit tests for Module 3 (spec §4) incl. parity with the reference script |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified 2026-09-17 on `dev` (primary checkout). Use these exact imports and names.

### Verified Imports
```python
import importlib.util            # stdlib — tests only (load the reference script by path)
import logging                   # stdlib
from pathlib import Path         # stdlib — tests only
from typing import Any           # stdlib
import cv2                       # verified by execution: opencv 4.10.0
import numpy as np               # verified by execution: numpy 2.4.6
import pytest                    # tests only
```

### Existing Signatures to Use
```python
# examples/planogram/white_label_detector/detect_price_labels.py  (adopted into git by TASK-3336; left untouched)
def candidates(image, min_width, max_width):                                   # :15-52  (verified)
    # thresholds (130,150,170,190,210,230); cv2.RETR_LIST + CHAIN_APPROX_SIMPLE;
    # keep when  min_width*w < bw < max_width*w  and  .014*h < bh < .06*h  and  1.65 < bw/bh < 4.4
    # rectangularity = contourArea / (minAreaRect w*h + 1e-6) >= .75 ; gray[y:y+bh, x:x+bw].std() >= 25
    # suppression: sort by rectangularity desc; drop when overlap/min(area_a, area_b) > .5
    # returns list[{"box": [x1, y1, x2, y2], "rectangularity": float, "contrast": float}]
def group_rows(items, image_width, min_row_labels=4, max_slope=.12):            # :55-107 (verified)
    # returns (rows, available) ; row = {"members": [item idx, left→right], "slope": float, "intercept": float}
    # rows sorted top→bottom by  slope*image_width/2 + intercept ; ``available`` = unassigned item indexes
def detect(path, output, args):                                                 # :110-182 (reference for the wrapper)
    # :114-119  scale = min(1., work_width/ow); resize with cv2.INTER_AREA only if scale < 1; sx, sy = ow/w, oh/h
    # :123-126  ROI: keep d when  l <= cx/w <= r  and  t <= cy/h <= b   (centres normalised on the PROCESSING image)
    # :135-137  full_box = [round(x1*sx), round(y1*sy), round(x2*sx), round(y2*sy)]
    # :146-147  px, py = max(2, round((x2-x1)*.12)), max(2, round((y2-y1)*.18))
    #           crop_box = [max(0,x1-px), max(0,y1-py), min(ow,x2+px), min(oh,y2+py)]
    # :164-165  line in original pixels: slope*sy/sx , intercept*sy
# The module has an ``if __name__ == "__main__":`` guard (:213) → safe to load with importlib.
```

### Created by dependency tasks (exist only after they land)
```python
# examples/planogram/plancheck/models.py — TASK-3337 (models-core). Inside the package:  from .models import Box, Tag, TagRow
Box = tuple[int, int, int, int]          # x1, y1, x2, y2 — ORIGINAL image pixels
class Tag(StrictModel):                  # extra="forbid"
    tag_id: str; image_id: str; row: int; position: int
    box: Box; crop_box: Box; rectangularity: float
class TagRow(StrictModel):
    image_id: str; row: int; slope: float; intercept: float   # line through tag CENTRES, original pixels
    tags: list[Tag]; synthesized: bool = False

# examples/planogram/tests/conftest.py — TASK-3337. USE, never redefine:
#   shelf_image() -> np.ndarray  BGR uint8, 1200 (h) × 1600 (w), background 30; 3 rows × 6 tags; tag = white (245)
#       70×30 rectangle with a dark (40) 40×10 inner bar; tag left x = 150 + 220*i, tag top y = 300 / 650 / 1000.
#   constants: TAG_W=70, TAG_H=30, TAG_X0=150, TAG_DX=220, TAG_ROWS_Y=(300, 650, 1000), TAGS_PER_ROW=6
#   (MIRROR these numbers locally in the test file with a comment — NEVER ``from conftest import …``: the repo root
#    also has a conftest.py, so the bare module name is ambiguous.)
# Verified while writing this task: the reference script on exactly that synthetic image yields 18 candidates,
# rows [6, 6, 6], 0 unassigned, first boxes [150,300,220,330], [370,300,440,330], … ; row-1 line slope≈0, intercept 315.0.
```

### Does NOT Exist
- ~~`import detect_price_labels`~~ / ~~`from white_label_detector import …`~~ — a standalone script in a directory without `__init__.py`; load it by path with `importlib.util.spec_from_file_location` (tests only), never import it from `plancheck/`.
- ~~`from inkcheck.detector import …`~~ — inkcheck is not a package on the path and is absent from worktrees.
- ~~a trained model / weights~~ — geometry + contrast heuristics only.
- ~~`Tag.price`~~, ~~`Tag.status`~~, ~~`Tag.crop`~~ — those are keys of the script's `labels.json`, not fields of the `Tag` model.
- ~~`TagRow.members`~~ / ~~`TagRow.count`~~ — the model has `tags`; counts are `len(row.tags)`.
- ~~`from parrot… import …`~~ — pure module: no `parrot`, no network, no `print`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "examples/planogram/plancheck/detection.py",
      "action": "CREATE"
    },
    {
      "path": "examples/planogram/tests/test_plancheck_detection.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:examples/planogram/white_label_detector/detect_price_labels.py#candidates",
    "sym:examples/planogram/white_label_detector/detect_price_labels.py#group_rows",
    "sym:examples/planogram/white_label_detector/detect_price_labels.py#detect"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
A faithful port: keep every literal (`0.014`, `0.06`, `1.65`, `4.4`, `0.75`, `25`, `0.5`, `0.2`, `0.40`,
`0.6`, `1.6`, `0.25`) and the evaluation order of the source. The parity test compares outputs with
the original on the same image — any "improvement" makes it fail by design.

### Key Constraints
- Pure, synchronous, CPU-bound module (the pipeline calls it through `asyncio.to_thread`); no
  `parrot`, no I/O, no `print` — `logger = logging.getLogger(__name__)`.
- `find_candidates` / `group_rows` work in the pixel space of the image they are given;
  only `detect_tags` converts to original pixels.
- Rows are 1-based top→bottom, tag `position` is 1-based left→right (same as the script's
  `enumerate(..., 1)`); `tag_id = f"{image_id}_r{row:02d}_p{position:02d}"`.
- `TagRow.slope` / `.intercept` are in **original** pixels: `slope*sy/sx`, `intercept*sy`.
- The detector never invents tags: a gap in a row stays a gap (gap filling is the grid's job).
- Strict type hints, Google-style docstrings, black line length 120.

### References in Codebase
- `examples/planogram/white_label_detector/detect_price_labels.py` — the source being adapted.
- `examples/planogram/plancheck/models.py` (TASK-3337) — `Tag`, `TagRow`, `Box`.
- `examples/planogram/tests/conftest.py` (TASK-3337) — `shelf_image`.

---

## Implementation Blueprint

> Write each block to its path nearly verbatim, then complete every `# FILL IN:` marker.
> Never change a signature, name or path fixed here (spec §3 Module 3).

### Steps (in order)
1. Create `detection.py` part 1 with `find_candidates` exactly as below — *why*: it is a line-for-line port of `candidates()`; keeping literals and order is what the parity test checks.
2. Add part 2 with `group_rows` exactly as below — *why*: same reason; the greedy "best line, consume members, repeat" loop is order-sensitive.
3. Add part 3 `detect_tags` and complete its FILL INs — *why*: this is the only new logic: scaling, ROI, model construction.
4. Keep ROI filtering on **normalised centres of the processing image** and run it *after* `find_candidates` — *why*: the source does so deliberately so the relative-size filters see the full image (script comment :121-122).
5. Convert the row line with `slope*sy/sx` and `intercept*sy` — *why*: the line was fitted in processing pixels; the grid (TASK-3341) evaluates it in original pixels.
6. Write the tests; load the reference script by path and `pytest.skip` when it is absent — *why*: the script is tracked only after TASK-3336; the suite must not fail in a checkout without it.
7. Run the validation command and `ruff check` on both files.

### `examples/planogram/plancheck/detection.py` (CREATE) — part 1/3
```python
"""Price-tag candidate detection and row grouping (FEAT-565).

Faithful port of ``white_label_detector/detect_price_labels.py`` (``candidates`` L15-52, ``group_rows`` L55-107).
Geometry/contrast heuristics only — no model weights. Pure, synchronous, CPU-bound.
"""
from __future__ import annotations

import logging
from typing import Any

import cv2
import numpy as np

from .models import Box, Tag, TagRow

logger = logging.getLogger(__name__)

_THRESHOLDS: tuple[int, ...] = (130, 150, 170, 190, 210, 230)


def find_candidates(image: np.ndarray, min_width: float = 0.025, max_width: float = 0.09) -> list[dict[str, Any]]:
    """Return contrasting, approximately rectangular components found at several gray thresholds.

    Args:
        image: BGR image; all returned boxes are in this image's pixel space.
        min_width: Minimum tag width as a fraction of the image width.
        max_width: Maximum tag width as a fraction of the image width.

    Returns:
        ``[{"box": [x1, y1, x2, y2], "rectangularity": float, "contrast": float}, ...]`` after suppression of
        duplicates across thresholds and of nested screen/frame contours, best rectangularity first.
    """
    h, w = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    found: list[dict[str, Any]] = []
    for threshold in _THRESHOLDS:
        mask = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY)[1]
        contours, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            x, y, bw, bh = cv2.boundingRect(contour)
            if not (min_width * w < bw < max_width * w and 0.014 * h < bh < 0.06 * h and 1.65 < bw / bh < 4.4):
                continue
            (_, _), (rw, rh), _ = cv2.minAreaRect(contour)
            rectangularity = cv2.contourArea(contour) / (rw * rh + 1e-6)
            if rectangularity < 0.75:
                continue
            contrast = float(gray[y : y + bh, x : x + bw].std())
            if contrast < 25:
                continue
            found.append(
                {"box": [x, y, x + bw, y + bh], "rectangularity": float(rectangularity), "contrast": contrast}
            )
    kept: list[dict[str, Any]] = []
    for item in sorted(found, key=lambda d: d["rectangularity"], reverse=True):
        x1, y1, x2, y2 = item["box"]
        area = (x2 - x1) * (y2 - y1)
        duplicate = False
        for other in kept:
            a, b, c, d = other["box"]
            overlap = max(0, min(x2, c) - max(x1, a)) * max(0, min(y2, d) - max(y1, b))
            if overlap / min(area, (c - a) * (d - b)) > 0.5:
                duplicate = True
                break
        if not duplicate:
            kept.append(item)
    return kept
```
**Why this shape**: identical control flow and literals to `candidates()` (:15-52). `sorted(..., reverse=True)` is
stable, so ties keep discovery order exactly as in the source — required for index-level parity. Nothing here is a
FILL IN: it is existing, verified behaviour being relocated.

### `examples/planogram/plancheck/detection.py` (CREATE) — part 2/3
```python
def group_rows(
    items: list[dict[str, Any]], image_width: int, min_row_labels: int = 4, max_slope: float = 0.12
) -> tuple[list[dict[str, Any]], list[int]]:
    """Deterministic line consensus: at least ``min_row_labels`` aligned, similarly sized boxes per row.

    Groups *visible* label rows, not planogram shelf identities. A row may contain a gap; missing labels are
    never invented here.

    Returns:
        ``(rows, unassigned)`` — ``rows`` sorted top→bottom, each ``{"members": [item index, left→right],
        "slope": float, "intercept": float}`` (line through box centres); ``unassigned`` = leftover item indexes.
    """
    if not items:
        return [], []
    boxes = np.array([d["box"] for d in items], dtype=float)
    centers = (boxes[:, :2] + boxes[:, 2:]) / 2
    widths = boxes[:, 2] - boxes[:, 0]
    heights = boxes[:, 3] - boxes[:, 1]
    available = list(range(len(items)))
    rows: list[dict[str, Any]] = []
    while len(available) >= min_row_labels:
        best: tuple[tuple[int, float], np.ndarray] | None = None
        for offset, i in enumerate(available):
            for j in available[offset + 1 :]:
                dx = centers[j, 0] - centers[i, 0]
                if abs(dx) < 0.2 * image_width:
                    continue
                a = (centers[j, 1] - centers[i, 1]) / dx
                if abs(a) > max_slope:
                    continue
                b = centers[i, 1] - a * centers[i, 0]
                indexes = np.array(available)
                residuals = np.abs(centers[indexes, 1] - (a * centers[indexes, 0] + b))
                med_height = np.median(heights[[i, j]])
                med_width = np.median(widths[[i, j]])
                keep = (
                    (residuals < 0.40 * med_height)
                    & (heights[indexes] > 0.6 * med_height)
                    & (heights[indexes] < 1.6 * med_height)
                    & (widths[indexes] > 0.6 * med_width)
                    & (widths[indexes] < 1.6 * med_width)
                )
                members = indexes[keep]
                if len(members) < min_row_labels:
                    continue
                span = np.ptp(centers[members, 0])
                if span < 0.25 * image_width:
                    continue
                score = (len(members), -float(np.median(residuals[keep])))
                if best is None or score > best[0]:
                    best = (score, members)
        if best is None:
            break
        members = best[1]
        a, b = np.polyfit(centers[members, 0], centers[members, 1], 1)
        ordered = sorted(members.tolist(), key=lambda i: centers[i, 0])
        rows.append({"members": ordered, "slope": float(a), "intercept": float(b)})
        consumed = set(ordered)
        available = [i for i in available if i not in consumed]
    rows.sort(key=lambda row: row["slope"] * image_width / 2 + row["intercept"])
    return rows, available
```
**Why this shape**: line-for-line port of `group_rows()` (:55-107): greedy best-line selection with the score
`(member count, −median residual)`, members consumed, repeat. The strict `score > best[0]` keeps the *first* best
pair on ties, as in the source — do not change it to `>=`.

### `examples/planogram/plancheck/detection.py` (CREATE) — part 3/3
```python
def _scale_box(box: list[int], sx: float, sy: float) -> Box:
    """Processing-pixel box → original-pixel ``Box`` (same rounding as the reference ``full_box``)."""
    return (round(box[0] * sx), round(box[1] * sy), round(box[2] * sx), round(box[3] * sy))


def detect_tags(
    image: np.ndarray,
    image_id: str,
    *,
    work_width: int = 2048,
    roi: tuple[float, float, float, float] | None = None,
) -> tuple[list[TagRow], list[Box]]:
    """Detect price-tag rows in one image.

    Args:
        image: Original BGR image.
        image_id: Id used to build ``tag_id`` = ``f"{image_id}_r{row:02d}_p{position:02d}"``.
        work_width: Maximum processing width; the image is downscaled (``cv2.INTER_AREA``) only when wider.
        roi: Optional ``(left, top, right, bottom)`` fixture bounds normalised to 0..1; candidates whose centre
            falls outside are dropped. Detection itself always runs on the full image.

    Returns:
        ``(rows, unassigned)`` — rows top→bottom with tags left→right, every coordinate in ORIGINAL pixels
        (boxes, crop boxes and the row line); ``unassigned`` = boxes of candidates that joined no row.
    """
    oh, ow = image.shape[:2]
    scale = min(1.0, work_width / ow)
    work = (
        cv2.resize(image, (round(ow * scale), round(oh * scale)), interpolation=cv2.INTER_AREA) if scale < 1 else image
    )
    h, w = work.shape[:2]
    sx, sy = ow / w, oh / h
    raw = find_candidates(work)
    if roi is not None:
        left, top, right, bottom = roi
        # FILL IN: keep d when left <= cx/w <= right and top <= cy/h <= bottom, cx/cy = box centre in PROCESSING
        #   pixels — bounded by the reference ROI filter (detect_price_labels.py:123-126) and test_detect_roi_filters.
        raise NotImplementedError
    grouped, unassigned_idx = group_rows(raw, w)
    rows: list[TagRow] = []
    for row_number, row in enumerate(grouped, 1):
        tags: list[Tag] = []
        for position, index in enumerate(row["members"], 1):
            x1, y1, x2, y2 = _scale_box(raw[index]["box"], sx, sy)
            # FILL IN: crop_box with px = max(2, round((x2-x1)*0.12)), py = max(2, round((y2-y1)*0.18)), clipped to
            #   [0, ow] × [0, oh] — bounded by detect_price_labels.py:146-147.
            # FILL IN: append Tag(tag_id=f"{image_id}_r{row_number:02d}_p{position:02d}", image_id=image_id,
            #   row=row_number, position=position, box=(x1, y1, x2, y2), crop_box=..., rectangularity=round(..., 4)).
            raise NotImplementedError
        # FILL IN: rows.append(TagRow(image_id=image_id, row=row_number, slope=row["slope"] * sy / sx,
        #   intercept=row["intercept"] * sy, tags=tags)) — bounded by detect_price_labels.py:164-165.
    unassigned = [_scale_box(raw[i]["box"], sx, sy) for i in unassigned_idx]
    logger.info("%s: %d tag rows, %d tags, %d unassigned", image_id, len(rows), sum(len(r.tags) for r in rows), len(unassigned))
    # FILL IN: when no row was formed, log a warning (the photo will be reported unregistered upstream) and
    #   still return ([], unassigned) — bounded by spec §2 "A photo with no tag rows is reported unregistered".
    return rows, unassigned
```
**Why this shape**: mirrors the scaling/ROI/box-conversion part of the script's `detect()` (:114-137, :146-147,
:164-165) but returns models instead of writing files. The `raise NotImplementedError` lines are placeholders that
must disappear when the FILL INs are completed — the surrounding loop structure is final.

### `examples/planogram/tests/test_plancheck_detection.py` (CREATE)
```python
"""Unit tests for plancheck.detection (FEAT-565, spec §4 — Module 3). Synthetic image only."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pytest

from plancheck.detection import detect_tags, find_candidates, group_rows

REFERENCE_SCRIPT = Path(__file__).resolve().parents[1] / "white_label_detector" / "detect_price_labels.py"


def _load_reference():
    """Load the original detector script by path; skip when it is not in this checkout."""
    if not REFERENCE_SCRIPT.exists():
        pytest.skip(f"reference detector not present: {REFERENCE_SCRIPT}")
    spec = importlib.util.spec_from_file_location("ref_detect_price_labels", REFERENCE_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_detect_synthetic_rows(shelf_image: np.ndarray) -> None:
    # FILL IN: rows, unassigned = detect_tags(shelf_image, "img"); assert 3 rows, 6 tags each (18 total),
    #   unassigned == []; rows ordered top→bottom (row numbers 1,2,3, intercept increasing), tags left→right
    #   (box x1 strictly increasing); first tag box == (150, 300, 220, 330); tag_id "img_r01_p01";
    #   crop_box contains box and is clipped to the image; abs(slope) < 1e-6.
    raise NotImplementedError


def test_detect_roi_filters(shelf_image: np.ndarray) -> None:
    # FILL IN: roi=(0.0, 0.0, 1.0, 0.45) keeps only the first row (centres y=315 → 0.2625 of 1200) → 1 row of 6;
    #   roi=(0.0, 0.0, 0.5, 1.0) leaves 3 tags per row (< min_row_labels=4) → rows == [] and nothing crashes.
    raise NotImplementedError


def test_detect_matches_reference_script(shelf_image: np.ndarray) -> None:
    ref = _load_reference()
    # FILL IN: ref_raw = ref.candidates(shelf_image, 0.025, 0.09); raw = find_candidates(shelf_image);
    #   assert [d["box"] for d in raw] == [d["box"] for d in ref_raw] (same order).
    #   ref_rows, ref_un = ref.group_rows(ref_raw, shelf_image.shape[1]); rows, un = group_rows(raw, shelf_image.shape[1]);
    #   assert members equal row by row, slopes/intercepts equal with pytest.approx, un == ref_un.
    raise NotImplementedError


def test_detect_downscales_and_rescales() -> None:
    # FILL IN: build the same synthetic layout at 2× size (3200×2400, tags 140×60 at x=300+440*i, y=600/1300/2000)
    #   with cv2/numpy locally; detect_tags(..., work_width=1600) → 3×6 tags whose boxes are within ±3 px of the
    #   original-pixel rectangles and whose row intercepts are ≈ 630 / 1330 / 2030 (±3) — proves sx/sy handling.
    raise NotImplementedError
```
**Why this shape**: the first three names are the spec §4 rows for M3. The fourth covers the only behaviour the
fixture cannot (the 1600-px fixture is never downscaled), i.e. the original-pixel rescale of boxes **and** line.
Expected numbers in the comments were measured by running the reference script on the agreed fixture layout.

### FILL IN checklist
- [ ] `detection.py::detect_tags` — ROI filter on normalised processing-pixel centres (script :123-126).
- [ ] `detection.py::detect_tags` — `crop_box` padding 12 % / 18 %, min 2 px, clipped (script :146-147).
- [ ] `detection.py::detect_tags` — `Tag` and `TagRow` construction; line rescale `slope*sy/sx`, `intercept*sy`.
- [ ] `detection.py::detect_tags` — warning + `([], unassigned)` when no row is formed; remove every placeholder `raise`.
- [ ] `test_plancheck_detection.py` — four test bodies per their FILL IN comments.

---

## Acceptance Criteria

- [ ] `find_candidates` and `group_rows` return exactly what the reference script returns on the synthetic image (`test_detect_matches_reference_script`).
- [ ] `detect_tags` returns rows top→bottom and tags left→right, all coordinates (boxes, crop boxes, row line) in original pixels, also when the image was downscaled.
- [ ] ROI drops candidates by normalised centre; an ROI leaving fewer than 4 tags per row yields no rows without raising.
- [ ] `white_label_detector/detect_price_labels.py` is unchanged; `plancheck/detection.py` does not import it, `inkcheck`, or `parrot`; no `print`.
- [ ] All tests pass: `pytest examples/planogram/tests/test_plancheck_detection.py -q` (the parity test may only *skip* when the reference script is absent).
- [ ] `ruff check examples/planogram/plancheck/detection.py examples/planogram/tests/test_plancheck_detection.py` is clean.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest examples/planogram/tests/test_plancheck_detection.py -q`

---

## Test Specification

The scaffold is the test-file blueprint block above. Required tests (spec §4, Module 3):

| Test | Asserts |
|---|---|
| `test_detect_synthetic_rows` | 3 rows × 6 tags on the `shelf_image` fixture, ordered, original-pixel boxes, ids |
| `test_detect_roi_filters` | tags outside the ROI are dropped; too few tags → no rows, no exception |
| `test_detect_matches_reference_script` | same candidates and rows as the original script (skips if the script is absent) |
| `test_detect_downscales_and_rescales` | `work_width` smaller than the image → coordinates and row line still in original pixels |

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** (§2 Overview stage 1, §3 Module 3, §4, §6, §7).
2. **Check dependencies** — TASK-3337 must be in `sdd/tasks/completed/`; confirm `examples/planogram/plancheck/models.py` has `Tag`, `TagRow`, `Box` and `examples/planogram/tests/conftest.py` has `shelf_image`.
3. **Verify the Codebase Contract** — open `examples/planogram/white_label_detector/detect_price_labels.py` and confirm `candidates` (:15) and `group_rows` (:55) still match the blueprint blocks line for line. If the script is absent in your worktree, the port below is still authoritative; the parity test will skip.
4. **Update status** in `sdd/tasks/index/new-planogram-compliance-algo.json` → `"in-progress"`.
5. **Implement** from the blueprint blocks; parts 1 and 2 are written verbatim; complete the FILL INs of part 3 and the tests.
6. **Verify** every acceptance criterion; run the validation command (no `PYTHONPATH` prefix needed — no parrot import).
7. **Move this file** to `sdd/tasks/completed/TASK-3340-detection.md` and set the index entry to `"done"`.
8. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
