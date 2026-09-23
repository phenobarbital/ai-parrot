# TASK-3643: CLI, Stage-1 perception and run outputs

**Feature**: FEAT-592 — Amazon Nova 2 Lite slot identification for planogram images
**Spec**: `sdd/specs/nova-image-planogram.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3640, TASK-3641, TASK-3642
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 5 (code half) — the entry point a user actually runs.

It wires the three preceding modules together: perceive the image (or load a
validated `--boxes` override), build the closed-set vocabulary, construct a
`VisionAdapter` around `NovaVisionClient`, run the strip loop, and write
`detections.json`, `annotated.jpg` and `run.json`.

Two design-research findings shape it (spec §9): perception must mirror the
**complete** InkWall tail, not three bare calls (S4), and `--boxes` must be
validated against the decoded image because `from_strip_norm` trusts
`PerceptionResult.image_size` (S7).

---

## Scope

- Implement `perceive()`, `load_perception()`, `annotate()` and `main()`.
- Wire the adapter: `NovaVisionClient` → `VisionAdapter` → `identify_strips_closed_set`.
- Write `detections.json`, `annotated.jpg` and `run.json` under `--output`.
- Implement the exit-code contract (0 / 1 / 2).
- Write unit tests for `load_perception`'s fail-fast validation — pure, no AWS.

**NOT in scope**: anything under `packages/` (spec G3 / AC6); the README
(TASK-3644); any change to the three modules this task imports.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/planogram/aws/nova2.py` | CREATE | CLI entry point, perception, annotation, outputs |
| `examples/planogram/tests/test_nova2_cli.py` | CREATE | Unit tests for `load_perception` validation |

---

## Codebase Contract (Anti-Hallucination)

> **CORRECTION-1 (post-TASK-3640/3641 review, applied by the orchestrator):**
> `from examples.planogram.aws.<module> import ...` **never resolves** — a
> third-party `examples` distribution is installed in the shared `.venv`
> (`.venv/lib/python3.12/site-packages/examples/`, with its own
> `__init__.py`), and a regular package found anywhere on `sys.path` always
> wins over a same-named repo-local namespace directory, regardless of
> `sys.path` order. Confirmed by running TASK-3640/3641's own declared
> `pytest` validation commands, which failed with
> `ModuleNotFoundError: No module named 'examples.planogram'`. The fix
> (already applied and merged): `examples/planogram/tests/conftest.py` now
> also inserts `examples/planogram/aws/` onto `sys.path`, and every
> cross-module reference inside `examples/planogram/aws/` — including this
> task's `nova2.py` and its test — uses a **bare sibling import**
> (`from identify import ...`, `from nova_vision import ...`, `from prompt
> import ...`, `from nova2 import ...`) instead of the dotted
> `examples.planogram.aws.` path shown anywhere below. This also matches how
> `python examples/planogram/aws/nova2.py` resolves its own sibling imports
> when run directly (Python auto-adds the script's own directory to
> `sys.path[0]`).

### Verified Imports
```python
from parrot.models.detections import DetectionBox                                  # verified: identify.py:14
from parrot_pipelines.planogram.backend import ResolvedBackend                      # verified: vision.py:17
from parrot_pipelines.planogram.contracts import (                                  # verified: identify.py:16-25
    ObservationSource, PerceptionResult, Shape, ShapeKind, Slot,
)
from parrot_pipelines.planogram.identification.vision import VisionAdapter, VisionError  # verified: vision.py:31,131
from parrot_pipelines.planogram.perception import PRICE_TAG_PROFILE, propose_shapes      # verified: perception/__init__.py:3-6
from parrot_pipelines.planogram.perception.executor import CpuExecutor              # verified: executor.py:17
from parrot_pipelines.planogram.perception.membership import assign_membership      # verified: membership.py:192
from parrot_pipelines.planogram.perception.ocr import read_crop                     # verified: ocr.py:73
from parrot_pipelines.planogram.perception.rows import group_rows                   # verified: rows.py:20
from parrot_pipelines.planogram.perception.slots import (                           # verified: slots.py:27,34,115
    AnchorRule, build_slots, candidate_shape_id,
)
from identify import (                                       # TASK-3642 — bare sibling import (CORRECTION-1)
    FlatDetection, RunStats, flatten, identify_strips_closed_set,
)
from nova_vision import NovaVisionClient                     # TASK-3640 — bare sibling import
from prompt import load_planogram_vocabulary                 # TASK-3641 — bare sibling import
```

### Existing Signatures to Use
```python
# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/ink_wall.py — THE REFERENCE TAIL
#   line 181: candidates = await ctx.executor.run(propose_shapes, bgr, [PRICE_TAG_PROFILE])
#   line 182: rows = group_rows(candidates, image.width)
#   line 183-184: slots = build_slots(rows, size, image_id=image_id,
#                     rule=AnchorRule.TAG_BELOW_PRODUCT, fill_gaps=True, untagged_bottom_row=True)
#   line 191: shape_id = candidate_shape_id(image_id, candidate)
#   line 214: shapes = assign_membership(shapes, [], size)
#   line 235: results.extend(await asyncio.gather(*(ctx.executor.run(read_crop, crop) for crop in crops)))

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/shapes.py
def propose_shapes(image: np.ndarray, profiles: Sequence[ShapeProfile], *,   # line 128
                   work_width: int = 2048) -> List[ShapeCandidate]: ...
    # Pure, synchronous, picklable — runs inside a process pool. Raises ValueError
    # on a non-uint8 / empty image. Returns [] when nothing qualifies.

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/rows.py
def group_rows(candidates: Sequence[ShapeCandidate], image_width: int, *,    # line 20
               min_row_items: int = 4, max_slope: float = 0.12) -> List[List[ShapeCandidate]]: ...
    # Returns [] when fewer than min_row_items candidates are given.

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/slots.py
class AnchorRule(str, Enum):                                                 # line 27
    TAG_BELOW_PRODUCT = "tag_below_product"; SHAPE_IS_SLOT = "shape_is_slot"
def candidate_shape_id(image_id: str, candidate: ShapeCandidate) -> str: ... # line 34
def build_slots(rows, image_size, *, image_id, rule,                         # line 115
                fill_gaps: bool = True, untagged_bottom_row: bool = False) -> List[Slot]: ...
def from_strip_norm(norm: Sequence[int], strip: DetectionBox) -> DetectionBox: ...  # line 263
    # TRUSTS PerceptionResult.image_size — the reason --boxes must be validated (§9 S7)

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/executor.py
class CpuExecutor:                                                           # line 17
    def __init__(self, max_workers: int = 2) -> None: ...                    # line 26
    async def run(self, fn: Callable[..., T], *args: Any) -> T: ...          # line 62
    async def __aenter__(self) -> "CpuExecutor": ...                         # line 99
    async def __aexit__(self, *exc: Any) -> None: ...                        # line 103

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/vision.py
class VisionAdapter:                                                         # line 131
    def __init__(self, client: Any, backend: ResolvedBackend, *,             # line 134
                 semaphore: asyncio.Semaphore, cache_dir: Optional[Path] = None,
                 max_tokens: int = 8192, timeout: float = 120.0,
                 repair_retries: int = 1) -> None: ...
    #   line 157-161: raises VisionError when the client has no ask_to_image

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/backend.py
class ResolvedBackend(BaseModel):                                            # line 28
    provider: str; model: Optional[str] = None; origin: BackendOrigin
    def as_string(self) -> str: ...                                          # line 34
BackendOrigin = Literal["llm_instance", "llm_string", "constructor", "config", "package_default"]

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py
class PerceptionResult(BaseModel):                                           # line 86
    image_id: str = "img0"
    image_size: Tuple[int, int] = (0, 0)   # (width, height)
    shapes: List[Shape]; slots: List[Slot]; zones: List[Shape]
    row_count: int = 0; detection_source: str = "cv"; ocr_available: bool = False
    errors: List[str]
class ShapeKind(str, Enum): PRICE_TAG, PRODUCT, BOX, FACT_TAG, ZONE, UNKNOWN  # line 15
```

### Does NOT Exist
- ~~a three-call perception shortcut~~ — `propose_shapes` + `group_rows` + `build_slots` alone do NOT produce an equivalent `PerceptionResult`; the ids, membership and gap filling at `ink_wall.py:191,214` are required (spec §9 S4).
- ~~`PerceptionResult.validate_against_image()`~~ — no such method; `load_perception` must do the checks itself.
- ~~`cv2.imread` / `cv2.imwrite` as coroutine-safe calls~~ — both are blocking; route them through `CpuExecutor.run` (spec §9 S5).
- ~~`NovaClient.ask_to_image`~~ — does not exist; use `NovaVisionClient` from TASK-3640.
- ~~`SUPPORTED_KWARGS["nova"]`~~ — not registered in `vision.py:22-27`; the `_COMMON` fallback is correct and needs no edit.
- ~~`examples/planogram/aws/nova2.py`~~ — created by this task.
- ~~`rapidocr` as a hard dependency~~ — OCR is optional; when it is absent set `ocr_available=False` and continue.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "examples/planogram/aws/nova2.py",
      "action": "CREATE"
    },
    {
      "path": "examples/planogram/tests/test_nova2_cli.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/shapes.py#propose_shapes",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/rows.py#group_rows",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/slots.py#build_slots",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/membership.py#assign_membership",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/vision.py#VisionAdapter",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/backend.py#ResolvedBackend",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/executor.py#CpuExecutor"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Resolve configuration and fail fast on missing credentials BEFORE decoding the image — *why*: AC-exit-1; a user without Bedrock access should not wait for OpenCV.
2. Write `perceive()` as a line-for-line mirror of `ink_wall.py:181-214` — *why*: spec §9 S4; a partial tail yields slot ids and membership the rest of the cycle does not expect.
3. Write `load_perception()` with three fail-fast checks — *why*: spec §9 S7; `from_strip_norm` trusts `image_size`, so a stale override silently misplaces every box.
4. Build `ResolvedBackend` from `NovaVisionClient.resolved_model_id`, not from the alias — *why*: spec §9 S10; `cache_key` keys on the backend string and the two spellings would split the cache.
5. Run the loop, then `flatten`, then write the three outputs — *why*: the flat rows are the deliverable and `run.json` carries the cost evidence (G5).
6. Route `annotate` and both image I/O calls through the executor — *why*: spec §9 S5.
7. Return 2 when `IdentificationResult.errors` is non-empty — *why*: a partially failed run must be distinguishable from a clean one in a script.
8. Write the `load_perception` tests — *why*: it is the pure, testable half of this module and AC9 depends on it.

### `examples/planogram/aws/nova2.py` (CREATE)
```python
"""Identify planogram slot contents with Amazon Nova 2 Lite (FEAT-592).

Feeds real Stage-1 OpenCV boxes to Nova through the existing planogram VisionAdapter
and writes flat {bbox, brand, product, occupancy} JSON plus an annotated image.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from parrot_pipelines.planogram.backend import ResolvedBackend  # verified: backend.py:28
from parrot_pipelines.planogram.contracts import (  # verified: identify.py:16-25
    ObservationSource, PerceptionResult, Shape, ShapeKind,
)
from parrot_pipelines.planogram.identification.vision import VisionAdapter  # verified: vision.py:131
from parrot_pipelines.planogram.perception import PRICE_TAG_PROFILE, propose_shapes  # verified: perception/__init__.py:3-6
from parrot_pipelines.planogram.perception.executor import CpuExecutor  # verified: executor.py:17
from parrot_pipelines.planogram.perception.membership import assign_membership  # verified: membership.py:192
from parrot_pipelines.planogram.perception.rows import group_rows  # verified: rows.py:20
from parrot_pipelines.planogram.perception.slots import (  # verified: slots.py:27,34,115
    AnchorRule, build_slots, candidate_shape_id,
)

from identify import RunStats, flatten, identify_strips_closed_set  # bare sibling import — see CORRECTION-1
from nova_vision import NovaVisionClient  # bare sibling import — see CORRECTION-1
from prompt import load_planogram_vocabulary  # bare sibling import — see CORRECTION-1

logger = logging.getLogger("nova2")

DEFAULT_MODEL = "nova-2-lite"
DEFAULT_REGION_PREFIX = "us"


async def perceive(image_bgr: np.ndarray, image_id: str, executor: CpuExecutor) -> PerceptionResult:
    """Stage-1 perception, mirroring types/ink_wall.py:181-214 (spec §9 S4)."""
    height, width = image_bgr.shape[:2]
    size = (width, height)
    candidates = await executor.run(propose_shapes, image_bgr, [PRICE_TAG_PROFILE])
    rows = group_rows(candidates, width)
    slots = build_slots(
        rows, size, image_id=image_id,
        rule=AnchorRule.TAG_BELOW_PRODUCT, fill_gaps=True, untagged_bottom_row=True,
    )
    # FILL IN: build Shape objects from `candidates` with candidate_shape_id(image_id, c),
    #   kind=ShapeKind.PRICE_TAG, source=ObservationSource.CV; then
    #   shapes = assign_membership(shapes, [], size); optional OCR via
    #   executor.run(read_crop, crop) guarded by ImportError -> ocr_available=False
    #   — bounded by spec §9 S4: the tail must match ink_wall.py:186-235, not stop at build_slots
    raise NotImplementedError


def load_perception(path: Path, image_bgr: np.ndarray) -> PerceptionResult:
    """Deserialize a --boxes override and fail fast when it does not match the image.

    Raises:
        ValueError: image_size differs from the decoded image's (width, height), or a
            box falls outside the image, or a slot's anchor_shape_id names no shape.
    """
    perception = PerceptionResult.model_validate_json(Path(path).read_text(encoding="utf-8"))
    height, width = image_bgr.shape[:2]
    if tuple(perception.image_size) != (width, height):
        raise ValueError(
            f"{path}: image_size {tuple(perception.image_size)} does not match the "
            f"image ({width}, {height}) - the override is stale"
        )
    # FILL IN: reject any slot/shape box outside 0<=x1<x2<=width, 0<=y1<y2<=height, and
    #   any slot whose anchor_shape_id is not among the shapes' ids — bounded by AC9
    #   and spec §9 S7 (from_strip_norm trusts image_size; annotation trusts the array)
    raise NotImplementedError


def annotate(image_bgr: np.ndarray, detections: Sequence[Any]) -> np.ndarray:
    """Draw each box labelled ``brand / product``; empty slots in a distinct colour.

    Picklable and synchronous — runs in the CpuExecutor, never on the event loop.
    """
    canvas = image_bgr.copy()
    # FILL IN: per detection draw cv2.rectangle + a bottom-edge label, colouring
    #   occupied vs empty vs unknown differently — bounded by AC4 (a box must land on
    #   the product it labels) and spec §9 S5 (no I/O here, drawing only)
    raise NotImplementedError


def _build_parser() -> argparse.ArgumentParser:
    """Flags per spec §3 Module 5."""
    # FILL IN: --image (required), --boxes, --planogram, --output (required), --model,
    #   --region, --aws-id, --concurrency (default 4), --no-marks, --cache-dir
    #   — bounded by AC1 (--help lists every flag)
    raise NotImplementedError


async def main(argv: Optional[Sequence[str]] = None) -> int:
    """Parse flags, run the cycle, write outputs.

    Returns:
        0 success, 1 invalid input, 2 completed with errors.
    """
    # FILL IN: 1) parse; 2) resolve credentials via NovaVisionClient.create() and
    #   return 1 on failure BEFORE decoding the image; 3) decode via
    #   executor.run(cv2.imread, ...); 4) perception = load_perception(--boxes) or
    #   await perceive(...); return 1 when it yields zero targets (AC11, no provider
    #   call); 5) vocabulary = load_planogram_vocabulary(--planogram), return 1 on
    #   ValueError (AC10); 6) VisionAdapter(client, ResolvedBackend(provider="nova",
    #   model=client.resolved_model_id, origin="constructor"),
    #   semaphore=asyncio.Semaphore(--concurrency), cache_dir=--cache-dir);
    #   7) result, stats = await identify_strips_closed_set(...);
    #   8) rows = flatten(result, perception); write detections.json, annotated.jpg
    #   (via executor) and run.json; 9) await client.aclose();
    #   10) return 2 when result.errors else 0
    #   — bounded by AC2/AC5/AC9/AC10/AC11 and spec §9 S5/S10
    raise NotImplementedError


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
```
**Why this shape**: `perceive` is pinned to the InkWall tail because that is the
production behaviour the experiment must match — stopping at `build_slots` omits the
pipeline-owned shape ids and membership assignment, and target selection downstream
silently changes (spec §9 S4). `load_perception` raises rather than warns because a
stale override produces plausible, wrong boxes on every row (spec §9 S7). The
`ResolvedBackend` is built from `resolved_model_id` so the cache keys on the effective
route (spec §9 S10). Credentials resolve before image decode so the common failure is
instant. Do not change the exit-code contract: scripts depend on 2 meaning "partial".

### `examples/planogram/tests/test_nova2_cli.py` (CREATE)
```python
"""Unit tests for the --boxes override validation (FEAT-592, TASK-3643).

Pure-function tests: a tiny synthetic array and hand-built contracts. No AWS, no
network, no real photo.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from parrot.models.detections import DetectionBox
from parrot_pipelines.planogram.contracts import PerceptionResult, Slot

from nova2 import load_perception  # bare sibling import — see CORRECTION-1


def _image(width: int = 100, height: int = 80) -> np.ndarray:
    """A blank BGR image of the given size."""
    return np.zeros((height, width, 3), dtype=np.uint8)


def _perception(width: int = 100, height: int = 80, box: tuple = (10, 10, 40, 40)) -> PerceptionResult:
    x1, y1, x2, y2 = box
    return PerceptionResult(
        image_id="img0",
        image_size=(width, height),
        slots=[Slot(slot_id="img0:r0:s1", image_id="img0", row_index=0, slot_index=1,
                    box=DetectionBox(x1=x1, y1=y1, x2=x2, y2=y2, confidence=1.0))],
    )


def _write(tmp_path: Path, perception: PerceptionResult) -> Path:
    path = tmp_path / "boxes.json"
    path.write_text(perception.model_dump_json(), encoding="utf-8")
    return path


def test_load_perception_accepts_a_matching_override(tmp_path: Path) -> None:
    """A consistent override round-trips unchanged."""
    path = _write(tmp_path, _perception())
    loaded = load_perception(path, _image())
    assert tuple(loaded.image_size) == (100, 80)
    assert len(loaded.slots) == 1


def test_load_perception_rejects_stale_image_size(tmp_path: Path) -> None:
    """An override recorded against a different photo is refused, naming both sizes."""
    path = _write(tmp_path, _perception(width=200, height=160))
    with pytest.raises(ValueError, match="does not match"):
        load_perception(path, _image(100, 80))


def test_load_perception_rejects_out_of_bounds_box(tmp_path: Path) -> None:
    """A box outside the image is refused rather than silently clipped."""
    # FILL IN: box=(10, 10, 500, 40) against a 100x80 image -> pytest.raises(ValueError)
    #   — bounded by AC9
    raise NotImplementedError


def test_load_perception_rejects_dangling_anchor(tmp_path: Path) -> None:
    """A slot whose anchor_shape_id names no shape is refused."""
    # FILL IN: Slot(..., anchor_shape_id="img0:missing") with shapes=[] ->
    #   pytest.raises(ValueError) — bounded by the load_perception docstring
    raise NotImplementedError


def test_load_perception_rejects_malformed_json(tmp_path: Path) -> None:
    """A file that is not a PerceptionResult fails validation, not silently."""
    # FILL IN: write {"nope": 1}; expect a pydantic ValidationError (or ValueError)
    #   — bounded by AC9
    raise NotImplementedError
```
**Why**: `load_perception` is the one pure, deterministic function in this module, and
it guards the failure spec §9 S7 calls out — a stale `--boxes` file misplaces every
box while the run still reports success. A 100×80 zero array is enough; no photo and
no AWS are involved, so the suite stays fast.

### FILL IN checklist
- [ ] `nova2.py::perceive` — the shape/membership/OCR tail; bounded by `ink_wall.py:186-235` (spec §9 S4)
- [ ] `nova2.py::load_perception` — bounds and anchor checks; bounded by AC9 / spec §9 S7
- [ ] `nova2.py::annotate` — drawing and colours; bounded by AC4
- [ ] `nova2.py::_build_parser` — the ten flags; bounded by AC1
- [ ] `nova2.py::main` — the ten wiring steps; bounded by AC2/AC5/AC9/AC10/AC11 and spec §9 S5/S10
- [ ] `test_nova2_cli.py` — three test bodies; bounded by AC9

---

## Acceptance Criteria

- [ ] `python examples/planogram/aws/nova2.py --help` exits 0 and lists every flag — spec AC1.
- [ ] A live run writes `detections.json`, `annotated.jpg` and `run.json` and exits 0 — spec AC2.
- [ ] `detections.json` has one entry per perceived target with a source-pixel `bbox` and a valid `occupancy` — spec AC3.
- [ ] Every `bbox` lies inside the image bounds — spec AC4.
- [ ] `run.json` records the geo-prefixed model id, region, prompt version, target count, `strips`, `calls`, `cache_hits`, `incomplete_retries`, `image_bytes_sent`, token counts and wall time — spec AC5.
- [ ] `perceive` calls `assign_membership` and allocates ids via `candidate_shape_id` — spec §9 S4.
- [ ] A `--boxes` file whose `image_size` disagrees with the image exits 1 naming both sizes — spec AC9.
- [ ] A non-planogram `--planogram` file exits 1 naming the missing `shelves` key — spec AC10.
- [ ] Zero perceived shapes exits 1 and sends no provider call — spec AC11.
- [ ] `IdentificationResult.errors` non-empty exits 2; a clean run exits 0.
- [ ] `ResolvedBackend.model` is the geo-prefixed resolved id, not the alias — spec §9 S10.
- [ ] Every OpenCV/image-I/O call goes through `CpuExecutor.run` — spec §9 S5.
- [ ] Re-running with the same `--cache-dir` issues zero provider calls and produces byte-identical `detections.json` — spec AC14.
- [ ] No file under `packages/` is modified — spec AC6.
- [ ] `ruff check` and `black --check --line-length 120` pass — spec AC12; no banned import — spec AC13.

---

## Validation Commands

- `pytest examples/planogram/tests/test_nova2_cli.py -q`

---

## Test Specification

See the `test_nova2_cli.py` blueprint block above — five cases over
`load_perception`, using a 100×80 zero array and hand-built contracts.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above (§3 Module 5, §9 S4/S5/S7/S10).
2. **Check dependencies** — TASK-3640, TASK-3641 and TASK-3642 must all be in
   `sdd/tasks/completed/`; this module imports from all three.
3. **Verify the Codebase Contract** — re-read `ink_wall.py:174-235` before writing
   `perceive`; it is the behaviour this must match.
4. **Update status** in `sdd/tasks/index/nova-image-planogram.json` → `"in-progress"`.
5. **Implement** — start from the blueprint blocks, complete every `# FILL IN:`, and
   never change a signature, class name or file path the blueprint fixes.
6. **Verify** all acceptance criteria are met.
7. **Move this file** to `sdd/tasks/completed/TASK-3643-cli-perception-and-outputs.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note


- Task: TASK-3643
- Feature: nova-image-planogram
- Implementation SHA: 850539844787a72a1e7e6b1f8796c97d1be8e790
- Closed at (UTC): 2026-09-23T00:20:13+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| ac_verified | AC1 (--help exits 0), AC6 (no packages/ touched), AC13 (no banned imports) verified manually |
| seat_summary | Seat: gpt-5.6-terra · Backend: codex · Model: gpt-5.6-terra · Attempts: 1 · Duration: 194.05s · Tokens: n/a |
| test_command | pytest examples/planogram/tests/test_nova2_cli.py -v |
| test_result | 5 passed (after fix commit 850539844 working around a pre-existing DetectionBox round-trip defect, ledger issue:6d481170075a) |
| tests_passed | True |
