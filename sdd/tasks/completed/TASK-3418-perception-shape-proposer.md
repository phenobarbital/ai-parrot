# TASK-3418: Profile-driven shape proposer (ShapeProfile, ShapeCandidate, propose_shapes)

**Feature**: FEAT-574 — New Planogram Compliance Pipeline
**Spec**: `sdd/specs/new-planogram-pipeline.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 1** (first half). The new cycle starts with a deterministic
*perceive* stage: classical OpenCV proposes rectangles on the untouched
full-resolution photo — no ROI gate, no LLM. Today the only detector of that
kind is the standalone reference `examples/planogram/plancheck/detection.py`,
whose six thresholds and size/aspect constants describe exactly **one** thing: a
bright landscape price label. This task generalises it into a **profile-driven
proposer**: the constants become a `ShapeProfile`, and one call can propose
several kinds of shapes.

This task creates the `perception` subpackage and ships the one profile that is
already proven (FEAT-565): `PRICE_TAG_PROFILE`. Measuring the proposer on real
photos and deciding other profiles is the follow-up spike task (TASK-3419).

---

## Scope

- Create the `parrot_pipelines.planogram.perception` package (`__init__.py`
  re-exporting the public names of this task only).
- Implement `ShapeProfile` and `ShapeCandidate` (Pydantic v2) and the constant
  `PRICE_TAG_PROFILE`, with the field names and defaults of the spec skeleton.
- Implement `propose_shapes(image, profiles, *, work_width=2048)`: pure,
  synchronous, picklable, module-level; three polarities (`bright`, `dark`,
  `edge`); per-profile de-duplication; coordinates scaled back to the source
  image; `[]` when nothing qualifies; never raises on a valid BGR image.
- Write offline unit tests on synthetic images drawn with OpenCV/numpy.

**NOT in scope**: row grouping, shelf edges, slots, OCR, fixture membership, the
process executor, any Pydantic contract of the cycle other than the two models
above, the spike harness/report, profiles for products/boxes/backlits (the spike
decides them), importing or editing `examples/planogram/plancheck/`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/__init__.py` | CREATE | Package marker + re-exports of this task's public names |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/profiles.py` | CREATE | `ShapeProfile`, `ShapeCandidate`, `PRICE_TAG_PROFILE` |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/shapes.py` | CREATE | `propose_shapes` and its private helpers |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_shapes.py` | CREATE | Offline unit tests on synthetic images |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
import cv2                      # opencv-python-headless>=4.8 — hard dep, packages/ai-parrot-pipelines/pyproject.toml:28-32
import numpy as np              # installed (2.4.6); used transitively by the package today
from pydantic import BaseModel, Field, model_validator   # pydantic v2 (repo-wide)
from typing import List, Literal, Sequence, Tuple
```

### Existing Signatures to Use
```python
# REFERENCE ONLY — read it, re-implement it, NEVER import it.
# examples/planogram/plancheck/detection.py
_THRESHOLDS: tuple[int, ...] = (130, 150, 170, 190, 210, 230)                      # :19
def find_candidates(image: np.ndarray, min_width: float = 0.025,
                    max_width: float = 0.09) -> list[dict[str, Any]]:              # :22-65
    # per threshold (:39): cv2.threshold(gray, t, 255, cv2.THRESH_BINARY)[1]      # :40
    #   cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)             # :41
    #   size/aspect gate: min_width*w < bw < max_width*w and 0.014*h < bh < 0.06*h
    #                     and 1.65 < bw/bh < 4.4                                   # :44
    #   rectangularity = contourArea / (minAreaRect w*h + 1e-6);  keep >= 0.75     # :46-49
    #   contrast = gray[y:y+bh, x:x+bw].std();                    keep >= 25       # :50-52
    # dedup (:54-65): sort by rectangularity desc; drop when
    #   overlap / min(area_a, area_b) > 0.5
def detect_tags(image, image_id, *, work_width: int = 2048, roi=None)              # :136
    #   downscales to work_width before detection and scales boxes back (_scale_box :131)

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/__init__.py:12-22
#   lazy __getattr__ only — importing the new subpackage does NOT import plan.py.
```

### Does NOT Exist
- ~~`parrot_pipelines/planogram/perception/`~~ — does not exist; this task creates it.
- ~~any importable `plancheck` package~~ — `examples/planogram/plancheck/` is a bare directory, not installed; never `import plancheck`.
- ~~generic shape detection (Canny, adaptive threshold, morphology, Hough) anywhere in `examples/planogram/`~~ — only bright-label thresholding exists; the `dark` and `edge` polarities are new code.
- ~~a `ShapeKind` enum available to this task~~ — the cycle enums belong to another root task (TASK-3421); here `kind` is a plain `str` on purpose.
- ~~`numpy` declared in `ai-parrot-pipelines/pyproject.toml`~~ — transitive today; do **not** edit `pyproject.toml` (another task owns it).
- ~~an `__init__.py` in `packages/ai-parrot-pipelines/tests/planogram_cycle/`~~ — do not create one; test basenames are unique by design.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/__init__.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/profiles.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/shapes.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_shapes.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Pattern to Follow
The algorithm of `examples/planogram/plancheck/detection.py:22-65`, with every
literal replaced by a `ShapeProfile` field:

| Reference literal | Profile field |
|---|---|
| `_THRESHOLDS` (:19) | `thresholds` |
| `0.025` / `0.09` of width (:22, :44) | `min_width` / `max_width` |
| `0.014` / `0.06` of height (:44) | `min_height` / `max_height` |
| `1.65` / `4.4` aspect (:44) | `min_aspect` / `max_aspect` |
| `0.75` rectangularity (:48) | `min_rectangularity` |
| `25` gray std (:51) | `min_contrast_std` |
| `0.5` overlap (:62) | `dedup_overlap` |

### Key Constraints
- `propose_shapes` and every helper are **module-level, synchronous and
  picklable**: they will run inside a process pool. No closures, no lambdas
  stored on models, no logger handlers created at call time, no PIL.
- Input is a **BGR `np.ndarray`** (`H×W×3`, `uint8`). A 2-D gray image is also
  accepted (skip the colour conversion). Anything else → `ValueError`.
- Downscale to `work_width` only when the image is wider; scale boxes back with
  the inverse factor and clip to the source bounds. Fractions in a profile are
  relative to the image they are evaluated on, so they are scale-invariant.
- De-duplicate **within one profile** only. Two profiles may legitimately
  propose overlapping rectangles (a tag inside a box); later stages decide.
- `score` is in `[0, 1]`; use rectangularity (clipped) so ordering matches the
  reference ("best rectangularity first").
- Use `logging.getLogger(__name__)` at module level for debug counts only; never `print`.
- Google-style docstrings and full type hints; 120 columns; `ruff check` clean.
- Inside a worktree run tests with
  `PYTHONPATH=packages/ai-parrot-pipelines/src:packages/ai-parrot/src` (the shared
  `.venv` is editable-installed against the main checkout). Never `uv sync`.

### References in Codebase
- `examples/planogram/plancheck/detection.py:19-65` — algorithm to generalise (reference only)
- `examples/planogram/plancheck/detection.py:131-160` — work-width downscale / scale-back idea

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. This is NOT the full
> implementation. Never change a signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Create `profiles.py` first — *why*: `shapes.py` and the tests import its models.
2. Create `shapes.py` with the helpers in the order given — *why*: each helper is
   unit-testable alone and `propose_shapes` only composes them.
3. Create `__init__.py` last, re-exporting exactly five names — *why*: a stable
   import surface for the follow-up tasks; nothing else may be exported yet.
4. Write the tests, run them with the `PYTHONPATH` prefix, then `ruff check` the three source files.

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/profiles.py` (CREATE)
```python
"""Shape profiles: what the classical-CV proposer should look for (FEAT-574)."""
from __future__ import annotations

from typing import Literal, Tuple

from pydantic import BaseModel, Field, model_validator


class ShapeProfile(BaseModel):
    """Geometric/photometric description of one kind of shape to propose.

    All size bands are fractions of the evaluated image (width for widths, height for heights),
    so a profile is independent of the photo resolution.
    """

    name: str
    kind: str = Field(description="ShapeKind value; a plain str so this module has no cycle-contract import")
    min_width: float = Field(gt=0.0, le=1.0)
    max_width: float = Field(gt=0.0, le=1.0)
    min_height: float = Field(gt=0.0, le=1.0)
    max_height: float = Field(gt=0.0, le=1.0)
    min_aspect: float = Field(gt=0.0)
    max_aspect: float = Field(gt=0.0)
    polarity: Literal["bright", "dark", "edge"]
    min_rectangularity: float = Field(default=0.75, ge=0.0, le=1.0)
    min_contrast_std: float = Field(default=25.0, ge=0.0)
    thresholds: Tuple[int, ...] = (130, 150, 170, 190, 210, 230)
    dedup_overlap: float = Field(default=0.5, gt=0.0, le=1.0)

    @model_validator(mode="after")
    def _check_bands(self) -> "ShapeProfile":
        """Reject inverted bands and out-of-range gray thresholds."""
        # FILL IN: raise ValueError naming the field when min_* >= max_* (width, height, aspect)
        #          or any threshold is outside 0..255 — bounded by: message must contain the field name.
        return self


class ShapeCandidate(BaseModel):
    """One proposed rectangle in SOURCE-image pixels."""

    profile: str
    kind: str
    x1: int
    y1: int
    x2: int
    y2: int
    score: float = Field(ge=0.0, le=1.0)


PRICE_TAG_PROFILE = ShapeProfile(
    name="price_tag",
    kind="price_tag",
    min_width=0.025,
    max_width=0.09,
    min_height=0.014,
    max_height=0.06,
    min_aspect=1.65,
    max_aspect=4.4,
    polarity="bright",
)
```
**Why this shape**: field names, defaults and order are fixed by the spec skeleton
(Module 1) and are consumed by four follow-up tasks — do not rename or reorder.
`kind` is a `str` because this task must stay independent of the cycle-contracts
task so both can run concurrently. `PRICE_TAG_PROFILE` carries the reference
constants verbatim (`detection.py:19,22,44,48,51,62`), the only proven profile.

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/shapes.py` (CREATE)
```python
"""Profile-driven classical-CV shape proposer (FEAT-574). Pure and picklable."""
from __future__ import annotations

import logging
from typing import List, Sequence, Tuple

import cv2
import numpy as np

from .profiles import ShapeCandidate, ShapeProfile

logger = logging.getLogger(__name__)

_RawBox = Tuple[int, int, int, int, float]  # x1, y1, x2, y2, score — in WORK-image pixels


def _to_gray(image: np.ndarray) -> np.ndarray:
    """Return a uint8 gray image. Raises ValueError for anything that is not HxW or HxWx3 uint8."""
    # FILL IN: validate ndim/dtype/non-empty, cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) for 3 channels
    #          — bounded by: ValueError message starts with "propose_shapes:".
    raise NotImplementedError


def _masks(gray: np.ndarray, profile: ShapeProfile) -> List[np.ndarray]:
    """Binary masks to contour for one profile, one per threshold (or one edge mask)."""
    # FILL IN: "bright" -> cv2.THRESH_BINARY per profile.thresholds (reference detection.py:40);
    #          "dark"   -> cv2.THRESH_BINARY_INV per threshold;
    #          "edge"   -> ONE mask: blur + cv2.Canny + cv2.morphologyEx(MORPH_CLOSE) so outlines close.
    #          bounded by: no global state, deterministic, returns uint8 masks of gray.shape.
    raise NotImplementedError


def _qualifies(contour: np.ndarray, gray: np.ndarray, profile: ShapeProfile) -> _RawBox | None:
    """Apply the size/aspect/rectangularity/contrast gates of one profile to one contour."""
    # FILL IN: boundingRect -> fractions vs gray.shape -> bands (strict < as in detection.py:44);
    #          rectangularity = contourArea / (minAreaRect w*h + 1e-6) >= min_rectangularity;
    #          gray crop std >= min_contrast_std; score = min(1.0, rectangularity).
    #          For polarity "edge" the contour is an outline: use the bounding-rect fill ratio of the
    #          convex hull instead of raw contourArea — bounded by AC "edge profile finds a low-contrast box".
    raise NotImplementedError


def _dedup(boxes: List[_RawBox], overlap: float) -> List[_RawBox]:
    """Keep best-score-first boxes; drop one whose intersection / min(area) exceeds ``overlap``."""
    # FILL IN: port of detection.py:54-65 — bounded by: stable for equal scores (sort is stable).
    raise NotImplementedError


def propose_shapes(
    image: np.ndarray, profiles: Sequence[ShapeProfile], *, work_width: int = 2048
) -> List[ShapeCandidate]:
    """Propose rectangles for every profile on a BGR image.

    Pure, synchronous and picklable (runs inside a process pool). Coordinates are scaled back to the
    source image and clipped to it.

    Args:
        image: BGR ``uint8`` array (HxWx3) or gray (HxW).
        profiles: Profiles to evaluate; each is de-duplicated independently.
        work_width: Detection runs on a copy downscaled to this width when the image is wider.

    Returns:
        Candidates grouped by profile order, best score first inside a profile. ``[]`` when nothing
        qualifies or ``profiles`` is empty. Never raises on a valid image.

    Raises:
        ValueError: ``image`` is not a non-empty uint8 HxW / HxWx3 array, or ``work_width`` < 1.
    """
    gray = _to_gray(image)
    height, width = gray.shape[:2]
    # FILL IN: scale = work_width / width if width > work_width else 1.0; cv2.resize(INTER_AREA) —
    #          bounded by: detection.py:136-160 behaviour (never upscale).
    # FILL IN: per profile -> masks -> findContours(RETR_LIST, CHAIN_APPROX_SIMPLE) -> _qualifies ->
    #          _dedup(profile.dedup_overlap) -> scale back by 1/scale, round, clip to [0,width]x[0,height],
    #          skip boxes that become degenerate — bounded by: x2 > x1 and y2 > y1 always.
    # FILL IN: logger.debug one line per profile with the kept count.
    raise NotImplementedError
```
**Why this shape**: one public function with the exact skeleton signature; four
private helpers so each gate is testable and the public body stays small. The
helpers mirror the reference line-for-line (`_masks` ↔ `:40`, `_qualifies` ↔
`:42-52`, `_dedup` ↔ `:54-65`) so behaviour for `PRICE_TAG_PROFILE` matches
FEAT-565. Everything is module-level because the function is shipped to worker
processes by pickle.

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/__init__.py` (CREATE)
```python
"""Deterministic perception building blocks of the planogram cycle (FEAT-574)."""
from .profiles import PRICE_TAG_PROFILE, ShapeCandidate, ShapeProfile
from .shapes import propose_shapes

__all__ = ["PRICE_TAG_PROFILE", "ShapeCandidate", "ShapeProfile", "propose_shapes"]
```
**Why**: later tasks add sibling modules to this package and import them by full
module path; keep `__init__` limited to these four names so no later task needs
to edit this file (avoids a shared-file conflict).

### `packages/ai-parrot-pipelines/tests/planogram_cycle/test_shapes.py` (CREATE)
See **Test Specification** below — write that scaffold to this path and complete the bodies.

### FILL IN checklist
- [ ] `profiles.py::ShapeProfile._check_bands` — inverted band / threshold range errors; message names the field
- [ ] `shapes.py::_to_gray` — input validation + colour conversion
- [ ] `shapes.py::_masks` — three polarities; deterministic
- [ ] `shapes.py::_qualifies` — gates of `detection.py:44-52`; edge-polarity fill ratio
- [ ] `shapes.py::_dedup` — port of `detection.py:54-65`
- [ ] `shapes.py::propose_shapes` — downscale, per-profile loop, scale-back, clipping, debug log
- [ ] `test_shapes.py` — every test body

---

## Acceptance Criteria

- [ ] AC-1: `from parrot_pipelines.planogram.perception import PRICE_TAG_PROFILE, ShapeCandidate, ShapeProfile, propose_shapes` works.
- [ ] AC-2: on a synthetic dark wall with bright landscape labels, `PRICE_TAG_PROFILE` proposes every label once (IoU ≥ 0.7 with the drawn rectangle) and proposes no blob that violates the size/aspect band.
- [ ] AC-3: with a 4096-px-wide image and `work_width=2048`, returned coordinates are in **source** pixels (within ±3 px of the drawn rectangles) and inside the image bounds.
- [ ] AC-4: a `dark`-polarity profile finds dark rectangles on a bright wall; an `edge`-polarity profile finds a low-contrast outlined box that the `bright` profile misses.
- [ ] AC-5: empty `profiles`, or an image with nothing qualifying, returns `[]`; a non-image input raises `ValueError`.
- [ ] AC-6: `pickle.dumps(propose_shapes)` and `pickle.dumps(PRICE_TAG_PROFILE)` succeed.
- [ ] AC-7: `ShapeProfile(min_width=0.2, max_width=0.1, ...)` raises a validation error naming the field.
- [ ] AC-8: `examples/planogram/plancheck/` is untouched and never imported.
- [ ] No linting errors: `ruff check packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/`
- [ ] All tests pass (see Validation Commands).

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_shapes.py -q`

---

## Test Specification

```python
# packages/ai-parrot-pipelines/tests/planogram_cycle/test_shapes.py
"""Offline tests for the profile-driven shape proposer (synthetic images only)."""
import pickle

import cv2
import numpy as np
import pytest
from pydantic import ValidationError

from parrot_pipelines.planogram.perception import (
    PRICE_TAG_PROFILE,
    ShapeCandidate,
    ShapeProfile,
    propose_shapes,
)


def _wall(width: int = 2000, height: int = 1500, value: int = 40) -> np.ndarray:
    """Uniform BGR wall."""
    return np.full((height, width, 3), value, dtype=np.uint8)


def _draw_label(img: np.ndarray, x: int, y: int, w: int, h: int) -> tuple[int, int, int, int]:
    """Bright label with dark 'text' strokes so the crop has contrast (std >= 25)."""
    cv2.rectangle(img, (x, y), (x + w, y + h), (245, 245, 245), -1)
    cv2.line(img, (x + 8, y + h // 2), (x + w - 8, y + h // 2), (20, 20, 20), 3)
    return x, y, x + w, y + h


def _iou(a, b) -> float:
    ...  # FILL IN


def test_price_tag_profile_finds_synthetic_tags():
    """AC-2: every drawn label proposed once; oversize/undersize blobs rejected."""


def test_propose_shapes_scales_back_to_source():
    """AC-3: 4096-wide image, work_width=2048 -> source-pixel coordinates inside bounds."""


def test_dark_and_edge_polarities():
    """AC-4."""


def test_empty_profiles_and_blank_image_return_empty_list():
    """AC-5 (first half)."""


@pytest.mark.parametrize("bad", [None, "x", np.zeros((0, 0, 3), np.uint8), np.zeros((4, 4, 3), np.float32)])
def test_invalid_image_raises_value_error(bad):
    """AC-5 (second half)."""
    with pytest.raises(ValueError):
        propose_shapes(bad, [PRICE_TAG_PROFILE])


def test_picklable_for_process_pool():
    """AC-6."""
    pickle.dumps(propose_shapes)
    pickle.dumps(PRICE_TAG_PROFILE)


def test_profile_rejects_inverted_band():
    """AC-7."""
    with pytest.raises(ValidationError, match="width"):
        ShapeProfile(name="x", kind="box", min_width=0.2, max_width=0.1, min_height=0.01,
                     max_height=0.5, min_aspect=0.5, max_aspect=2.0, polarity="bright")


def test_dedup_is_per_profile():
    """Two profiles that both match one rectangle yield two candidates (one per profile)."""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context (§3 Module 1, §6, §7)
2. **Check dependencies** — none
3. **Verify the Codebase Contract** — re-read `examples/planogram/plancheck/detection.py:19-65`
   before porting; if the line numbers moved, update the contract FIRST
4. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
5. **Verify** all acceptance criteria are met
6. **Commit code only** — never touch `sdd/`; the orchestrator moves this file and updates the index
7. **Fill in the Completion Note** in your final report

---

## Completion Note

**Completed by**: sdd-worker (FEAT-574 orchestrator)
**Date**: 2026-09-19

Implemented in fallback sequential mode (parrot-sdd-coder server unresponsive).
perception/ package: ShapeProfile (band/threshold validator naming the field), ShapeCandidate, PRICE_TAG_PROFILE (FEAT-565 constants verbatim); shapes.propose_shapes with bright/dark/edge polarities (edge = blur+Canny+close, convex-hull fill ratio), per-profile dedup port of detection.py:54-65, INTER_AREA downscale to work_width and scale-back/clip to source pixels. Module-level, picklable; examples/planogram/plancheck untouched.
Tests: test_shapes.py 11 passed (AC-1..AC-7); ruff clean.

Seat: orchestrator (fallback) · Backend: native · Model: claude-opus-5 · Attempts: 1
