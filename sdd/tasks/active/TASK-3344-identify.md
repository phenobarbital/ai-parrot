# TASK-3344: Pass 1 — area-constrained open-set identification (row strips + Set-of-Marks)

**Feature**: FEAT-565 — New Planogram Compliance Algorithm
**Spec**: `sdd/specs/new-planogram-compliance-algo.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3338, TASK-3339, TASK-3341, TASK-3342
**Assigned-to**: unassigned

---

## Context

Spec §2 stage 5 and §3 **Module 7: identify**. This is the *unbiased* half of Option D: for each
visible shelf row the vision model receives **one full-resolution strip** plus the **JSON list of
slot areas** and answers **per supplied slot id only**. It is deliberately **not told what the
planogram expects** — its confident reads become the identity *anchors* that the deterministic
registration (TASK-3345) aligns. Confirmation bias is confined to pass 2 (TASK-3346).

inkcheck's per-crop approach (≈230 calls per visit, no neighbour context, 94/117 graded `low`)
is what this replaces: ~6 calls per photo, neighbour context preserved, and the area constraint
enforced in Python (answers for ids we did not send are dropped and reported).

Resolved decisions this task implements: Set-of-Marks **on by default** with `marks=False` as
the A/B switch (§8 Q6); the local model is LFM2.5-VL-1.6B so **every** row is split into
sub-strips of ≤ 8 slots on local backends (§8 Q4).

Dependencies (by file):
- `examples/planogram/plancheck/models.py` — `Slot`, `SlotReading`, `RowReading`, `Catalog`, `Box`
  (TASK-3337) and `SlotObservation` (TASK-3338).
- `examples/planogram/plancheck/reference.py` — `resolve_identity` (TASK-3339).
- `examples/planogram/plancheck/grid.py` — `strip_box`, `to_strip_norm` (TASK-3341).
- `examples/planogram/plancheck/vision.py` — `VisionBackend` type + `cache_key` for one test (TASK-3342).

---

## Scope

- Implement `examples/planogram/plancheck/identify.py`: `IDENTIFY_PROMPT_VERSION`, `render_strip`,
  `build_identify_prompt`, `identify_rows` (+ the private helpers in the blueprint).
- `render_strip`: native-resolution PNG of one row (or sub-strip); with `marks=True` a 2-px outline per
  slot and the slot `index` as its number, **drawn over the tag area, never over the product**.
- `build_identify_prompt`: instructions + JSON `[{"slot_id","mark","box_2d"}]` with `box_2d` =
  `[ymin, xmin, ymax, xmax]` 0–1000 relative to the strip; **no planogram, no expected products**.
- `identify_rows`: call planning (cloud: one call per row, split only above 20 slots; local: always
  sub-strips ≤ 8), response filtering, downgrade rule, failure handling, catalog resolution.
- Write `examples/planogram/tests/test_plancheck_identify.py`.

**NOT in scope**: registration / `facing_id` (TASK-3345 — this module **never** sets `facing_id`);
pass 2 (TASK-3346, which reuses `render_strip` from here); price reading (TASK-3343); the catalog
rules themselves (TASK-3339); caching and lane dispatch (TASK-3342); deciding the Set-of-Marks
default by measurement (first real run, README — TASK-3350).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/planogram/plancheck/identify.py` | CREATE | Strip rendering, prompt, pass-1 orchestration |
| `examples/planogram/tests/test_plancheck_identify.py` | CREATE | Unit tests with `FakeBackend` and synthetic slots |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: this module touches **no existing repo code** — only OpenCV/numpy and sibling FEAT-565 modules.

### Verified Imports
```python
import asyncio, json, logging, math
from typing import TYPE_CHECKING
import cv2            # opencv-python 4.10.0.84 installed — cv2.rectangle, cv2.putText, cv2.getTextSize, cv2.imencode
import numpy as np    # numpy 2.4.6 installed

from plancheck.grid import strip_box, to_strip_norm                                   # TASK-3341
from plancheck.models import Box, Catalog, RowReading, Slot, SlotObservation, SlotReading   # TASK-3337 / TASK-3338
from plancheck.reference import normalize_brand, resolve_identity                     # TASK-3339
if TYPE_CHECKING:
    from plancheck.vision import VisionBackend                                        # TASK-3342 — type-only
```

### Existing Signatures to Use
None from the current repository. OpenCV calls used: `cv2.rectangle(img, (x1,y1), (x2,y2), color, 2)`,
`cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, color, thickness, cv2.LINE_AA)`,
`cv2.getTextSize(text, font, scale, thickness) -> ((w, h), baseline)`, `cv2.imencode(".png", img) -> (ok, buf)`.

### Created by dependency tasks (exist only after they land)
```python
# examples/planogram/plancheck/models.py  (TASK-3337)
Box = tuple[int, int, int, int]                       # x1, y1, x2, y2 — ORIGINAL image pixels
class Slot(StrictModel):
    slot_id: str            # f"{image_id}_r{row:02d}_s{index:02d}"
    image_id: str; row: int; index: int; box: Box
    tag_id: str | None = None; tag_box: Box | None = None
    origin: Literal["tag_anchored", "gap_filled", "untagged_row"]
class SlotReading(StrictModel):                       # pass-1 LLM contract, one per slot
    slot_id: str; occupancy: Literal["occupied", "empty", "uncertain"]
    visibility: Literal["full", "partial", "unusable"]
    brand: str | None = None; family: str | None = None; xl: bool | None = None
    colors: list[str] = []   # max 8
    pack: int | None = None
    visible_text: list[str] = []   # max 20
    evidence: str = ""             # max 400 chars
class RowReading(StrictModel): slots: list[SlotReading]
class Catalog(StrictModel): items: list[CatalogItem]

# examples/planogram/plancheck/models.py  (TASK-3338)
class SlotObservation(StrictModel):
    slot: Slot; reading: SlotReading | None = None
    resolved_sku: str | None = None; candidate_skus: list[str] = []
    resolution: Literal["direct", "verified_by_expectation", "inferred", "ambiguous", "unresolved"] = "unresolved"
    price: PriceReading = PriceReading()
    facing_id: str | None = None; registration_grade: Grade | None = None
    issues: list[str] = []

# examples/planogram/plancheck/grid.py  (TASK-3341)
def strip_box(slots: list[Slot], image_size: tuple[int, int], pad: float = 0.04) -> Box   # image_size = (width, height)
def to_strip_norm(box: Box, strip: Box) -> list[int]                                     # [ymin, xmin, ymax, xmax] in 0–1000

# examples/planogram/plancheck/reference.py  (TASK-3339)
def resolve_identity(reading: SlotReading, catalog: Catalog) -> tuple[str | None, list[str], Resolution]
#   -> (sku, candidate_skus, "direct" | "ambiguous" | "unresolved"); never uses planogram expectations

# examples/planogram/plancheck/vision.py  (TASK-3342)
class VisionBackend:
    is_local: bool   # property
    async def ask(self, prompt: str, images: Sequence[bytes], schema: type[T], *, stage: str, prompt_version: str) -> T
def cache_key(llm, base_url, max_tokens, stage, prompt_version, prompt, schema, images) -> str   # pure, no parrot import

# examples/planogram/tests/conftest.py  (TASK-3337): shelf_image, mini_planogram, mini_catalog, FakeBackend / fake_backend
```

### Does NOT Exist
- ~~any planogram/expectation input to this module~~ — `identify_rows` takes a `Catalog` (for resolution) and **no** `PlanogramRef`.
- ~~`Slot.mark`~~ — the mark number **is** `Slot.index`.
- ~~`facing_id` set here~~ — registration is the only writer (spec §5: "The LLM never sets `facing_id`").
- ~~per-crop LLM calls~~ — rejected Option A; one call per row / sub-strip only.
- ~~`VisionError` importable in tests via conftest~~ — `FakeBackend` raises `RuntimeError`; catch **`Exception`** around `backend.ask`.
- ~~`plancheck.vision` real backend in these tests~~ — use `FakeBackend`; only the pure `cache_key` function is imported for `test_identify_marks_flag`.
- ~~matplotlib / PIL drawing~~ — cv2 only.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "examples/planogram/plancheck/identify.py",
      "action": "CREATE"
    },
    {
      "path": "examples/planogram/tests/test_plancheck_identify.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Decided behaviour (do not re-decide)
- **Call planning** (`_plan_calls`): group slots by `row`, order by `index`. `limit = 8`.
  Local backend (`backend.is_local`): **always** chunk. Cloud: chunk **only when the row has > 20 slots**.
  Chunks are contiguous and **balanced**: `n_chunks = ceil(n / 8)`, sizes differ by at most 1 (12 → 6+6, 17 → 6+6+5).
  Each chunk gets its own strip (`strip_box` over the chunk's slots), so sub-strips keep native resolution.
- **Marks**: outline = 2-px rectangle on `slot.box`; number = `str(slot.index)`. Number placement: centred on
  `slot.tag_box` when present (filled dark label, light text); otherwise in a band **just below** `slot.box`
  (where the tag would be), clipped to the strip. Never inside `slot.box` beyond the 2-px border. `marks=False`
  → the PNG is the plain crop.
- **Prompt** must: list the areas as JSON; say that only those areas may be reported, one entry per `slot_id`,
  echoing `slot_id` verbatim; define `occupancy` / `visibility` vocab; ask for brand, family (cartridge/model
  number as printed), `xl`, colours, pack size, `visible_text` lines and one-sentence `evidence`; say "use null /
  empty when not legible — do not guess". It must **not** contain the words `planogram`, `expected`, any SKU or
  any catalog display name. Mention that numbered outlines, *when visible*, equal `mark` (the function has no `marks` argument).
- **Response filtering**, in this order: unknown `slot_id` → dropped, and one error string per call listing them;
  duplicate `slot_id` → first wins; missing `slot_id` → `SlotReading(occupancy="uncertain", visibility="unusable")`
  + issue `missing_in_response`; `occupancy == "empty"` with `visibility != "full"` → `occupancy="uncertain"` +
  issue `empty_downgraded_partial_visibility`.
- **Resolution**: only `occupied` readings go through `resolve_identity`; others stay `unresolved` with no SKU.
- **Failure**: any `Exception` from `backend.ask` → every slot of that call `uncertain`/`unusable` + issue
  `identify_failed` + **one** error string `identify <image_id> row <row> [s<first>-s<last>]: <exc>`. Never raise.
- **Output order**: observations sorted by `(row, index)`; errors in call order.
- Rendering/encoding is CPU work → `asyncio.to_thread`; the LLM call is made while holding `semaphore`.
- Stage name `"identify"`; `IDENTIFY_PROMPT_VERSION` must be bumped whenever prompt wording changes (it is part of the cache key).

### Key Constraints
- Coordinates in models are ORIGINAL pixels; translate to strip space only for drawing / `to_strip_norm`.
- Never mutate the input `image` (draw on a copy of the crop).
- `logging.getLogger(__name__)`; no `print`; black 120; strict type hints; Google-style docstrings.
- Fixtures/prompts/tests use **synthetic** brands and SKUs only (public repo — nothing from `planogram_page1.json`).

### References in Codebase
- `examples/planogram/white_label_detector/detect_price_labels.py:158-161` — overlay drawing style (rectangle + `putText`), reference only.
- Spec §2 stage 5, §5 (three identify criteria), §7 "Confirmation bias" / "Local model" gotchas.

---

## Implementation Blueprint

### Steps (in order)
1. Write `_plan_calls` and its test first — *why*: the local/cloud split rule is an acceptance criterion and everything else iterates over its output.
2. Write `render_strip` — *why*: TASK-3346 imports it, so its signature and the "never over the product" rule must be stable early.
3. Write `build_identify_prompt` with the JSON area list and the no-expectation wording — *why*: `test_prompt_has_no_expectations` guards the unbiasedness of pass 1.
4. Write `_apply_reading_rules` (filtering + downgrade) as a pure function, then `identify_rows` around it — *why*: keeping the rules pure makes the four filtering tests trivial and keeps the coroutine about orchestration only.
5. Complete the tests; run the validation command and `ruff check`.

### `examples/planogram/plancheck/identify.py` (CREATE) — part 1/2
```python
"""Pass 1 — area-constrained open-set identification (FEAT-565, Module 7).

One full-resolution row strip + JSON of slot areas per call; answers are keyed by supplied slot id.
The model is never told what the planogram expects.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
from typing import TYPE_CHECKING

import cv2
import numpy as np

from plancheck.grid import strip_box, to_strip_norm
from plancheck.models import Box, Catalog, RowReading, Slot, SlotObservation, SlotReading
from plancheck.reference import normalize_brand, resolve_identity

if TYPE_CHECKING:
    from plancheck.vision import VisionBackend

logger = logging.getLogger(__name__)

IDENTIFY_PROMPT_VERSION: str = "identify-v1"
IDENTIFY_STAGE: str = "identify"
SUBSTRIP_MAX_SLOTS: int = 8
CLOUD_SPLIT_ABOVE: int = 20


def _plan_calls(slots: list[Slot], *, is_local: bool) -> list[list[Slot]]:
    """Group slots into LLM calls: rows ordered by ``row``; chunks contiguous, balanced, ordered by ``index``."""
    # FILL IN: per row: if is_local or len(row) > CLOUD_SPLIT_ABOVE -> ceil(n / SUBSTRIP_MAX_SLOTS) balanced
    #          chunks (sizes differ by <= 1), else one chunk — bounded by test_identify_substrips_on_local
    raise NotImplementedError


def render_strip(image: np.ndarray, slots: list[Slot], *, marks: bool = True) -> tuple[bytes, Box]:
    """PNG of one row at native resolution with 2-px numbered outlines; returns (png, strip box).

    The mark number is the slot ``index``; labels are drawn over the TAG area, never the product.
    """
    height, width = image.shape[:2]
    strip = strip_box(slots, (width, height))
    x1, y1, x2, y2 = strip
    crop = image[y1:y2, x1:x2].copy()
    if marks:
        for slot in slots:
            # FILL IN: 2-px rectangle on slot.box translated by (-x1, -y1); number = str(slot.index) centred on
            #          slot.tag_box when present, else in a band just below slot.box (clipped to the crop);
            #          filled dark label + light text; NEVER paint inside slot.box beyond the 2-px border
            #          — bounded by test_render_strip_marks_never_cover_product
            raise NotImplementedError
    ok, buffer = cv2.imencode(".png", crop)
    if not ok:
        raise ValueError("strip PNG encoding failed")
    return buffer.tobytes(), strip


def build_identify_prompt(slots: list[Slot], strip: Box) -> str:
    """Instructions + JSON list ``[{"slot_id","mark","box_2d"}]``; forbids reporting anything outside the
    listed areas; does NOT mention the planogram or expected products."""
    areas = [{"slot_id": s.slot_id, "mark": s.index, "box_2d": to_strip_norm(s.box, strip)} for s in slots]
    areas_json = json.dumps(areas, separators=(",", ":"))
    # FILL IN: compose the instruction text per "Decided behaviour → Prompt" and append areas_json
    #          — bounded by test_prompt_has_no_expectations (no "planogram", no "expected", no SKU/display name)
    raise NotImplementedError
```
**Why this shape**: `render_strip` and `build_identify_prompt` signatures are fixed by the spec skeleton (TASK-3346 imports
`render_strip`). The crop/encode frame of `render_strip` is complete so `marks=False` is *by construction* the plain crop;
only the drawing is left open. `box_2d` uses Gemini's `[ymin, xmin, ymax, xmax]` 0–1000 convention through
`to_strip_norm` — do not re-derive it here.

### `examples/planogram/plancheck/identify.py` (CREATE) — part 2/2
```python
def _uncertain(slot: Slot, issue: str, evidence: str = "") -> SlotObservation:
    """Observation for a slot the model did not (usably) assess."""
    reading = SlotReading(slot_id=slot.slot_id, occupancy="uncertain", visibility="unusable", evidence=evidence[:400])
    return SlotObservation(slot=slot, reading=reading, issues=[issue])


def _apply_reading_rules(slots: list[Slot], answer: RowReading, catalog: Catalog) -> tuple[list[SlotObservation], list[str]]:
    """Filter one call's answer and resolve identities. Returns (observations for ALL ``slots``, unknown ids)."""
    # FILL IN — in this order (bounded by the four filtering tests):
    #   1. index the answer by slot_id, FIRST occurrence wins; ids not in `slots` -> unknown list (dropped).
    #   2. slot missing from the answer -> _uncertain(slot, "missing_in_response").
    #   3. occupancy == "empty" and visibility != "full" -> reading.model_copy(update={"occupancy": "uncertain"})
    #      + issue "empty_downgraded_partial_visibility".
    #   4. occupancy == "occupied" -> sku, candidates, resolution = resolve_identity(reading, catalog);
    #      anything else -> resolved_sku None, resolution "unresolved".
    #   4b. ALWAYS store the catalog-normalised brand on the reading that goes into the observation:
    #      brand = normalize_brand(reading.brand, catalog); if brand: reading = reading.model_copy(update={"brand": brand})
    #      — because registration.py / scoring.py (TASK-3345/3347) compare brands by casefold() only and do not
    #      depend on reference.py; an un-normalised "Acme Inc" would count as a different brand from "Acme".
    #   5. NEVER set facing_id / registration_grade / price here.
    raise NotImplementedError


async def identify_rows(image: np.ndarray, slots: list[Slot], backend: "VisionBackend", catalog: Catalog,
                        semaphore: asyncio.Semaphore, *, marks: bool = True) -> tuple[list[SlotObservation], list[str]]:
    """Run pass 1 over every slot of one image.

    One call per row on cloud backends. On local backends EVERY row is split into sub-strips of <= 8 slots,
    one call each; cloud rows are split the same way only above 20 slots. Unknown slot ids are dropped and
    reported; missing ids -> uncertain/unusable; an ``empty`` with visibility != full is downgraded to
    ``uncertain``. A failed call -> all its slots uncertain + one error string. Returns (observations, errors).
    """
    calls = _plan_calls(slots, is_local=backend.is_local)

    async def _one(chunk: list[Slot]) -> tuple[list[SlotObservation], list[str]]:
        # FILL IN:
        #   png, strip = await asyncio.to_thread(render_strip, image, chunk, marks=marks)
        #   prompt = build_identify_prompt(chunk, strip)
        #   async with semaphore: answer = await backend.ask(prompt, [png], RowReading,
        #                                  stage=IDENTIFY_STAGE, prompt_version=IDENTIFY_PROMPT_VERSION)
        #   except Exception as exc: logger.warning(...); return ([_uncertain(s, "identify_failed", str(exc)) ...],
        #       [f"identify {image_id} row {row} [s{first:02d}-s{last:02d}]: {exc}"])
        #   unknown ids -> one error string f"identify {image_id} row {row}: dropped unknown slot ids {unknown}"
        raise NotImplementedError

    results = await asyncio.gather(*(_one(chunk) for chunk in calls))
    observations = sorted((o for obs, _ in results for o in obs), key=lambda o: (o.slot.row, o.slot.index))
    errors = [e for _, errs in results for e in errs]
    return observations, errors
```
**Why this shape**: the rules live in a pure function so they are testable without a backend; `identify_rows` is only
planning + gather + ordering, and its tail is given complete because the output ordering and the "errors in call order"
contract are consumed by TASK-3349. `except Exception` is deliberate: the real backend raises `VisionError`, the test
double raises `RuntimeError`, and neither may abort the run (spec §5: row failure → exit code 2 with a complete report).

### `examples/planogram/tests/test_plancheck_identify.py` (CREATE)
```python
"""Unit tests for plancheck.identify (FEAT-565, TASK-3344). No network; FakeBackend only."""
from __future__ import annotations

import asyncio

import cv2
import numpy as np
import pytest

from plancheck.identify import (IDENTIFY_PROMPT_VERSION, IDENTIFY_STAGE, _plan_calls, build_identify_prompt,
                                identify_rows, render_strip)
from plancheck.models import RowReading, Slot, SlotReading
from plancheck.vision import cache_key

# Mirror of the geometry constants in examples/planogram/tests/conftest.py (TASK-3337). Do NOT
# `from conftest import ...`: the repo root also has a conftest.py, so the bare module name is ambiguous.
TAG_W, TAG_H, TAG_X0, TAG_DX, TAG_ROWS_Y, TAGS_PER_ROW = 70, 30, 150, 220, (300, 650, 1000), 6


def _row_slots(row: int, n: int = TAGS_PER_ROW, *, image_id: str = "img") -> list[Slot]:
    """`n` tag-anchored slots of 0-based conftest row `row` (n > 6 -> use a wide blank canvas in the test)."""
    # FILL IN: product box 160x200 ending 10 px above the tag top; tag_box from the constants;
    #          slot_id f"{image_id}_r{row+1:02d}_s{i+1:02d}", row=row+1, index=i+1, origin "tag_anchored"
    raise NotImplementedError


def _reading(slot_id: str, **kw) -> SlotReading:
    return SlotReading(**{"slot_id": slot_id, "occupancy": "occupied", "visibility": "full", **kw})


def test_plan_calls_cloud_and_local() -> None: ...            # FILL IN: 6 slots cloud -> 1 call; 12 local -> [6,6]; 17 local -> [6,6,5]; 21 cloud -> 3 calls; 20 cloud -> 1 call
def test_render_strip_marks_never_cover_product(shelf_image) -> None: ...   # FILL IN: decode both PNGs; pixels inside every slot.box shrunk by 3 px are IDENTICAL with marks on/off; whole images differ
def test_render_strip_does_not_mutate_input(shelf_image) -> None: ...       # FILL IN: copy before, array_equal after
def test_prompt_has_no_expectations(mini_catalog, mini_planogram) -> None: ...  # FILL IN: prompt.lower() has no "planogram"/"expected"; no catalog sku/display_name/alias and no planogram sku in it; every slot_id and a box_2d list ARE in it
@pytest.mark.asyncio
async def test_identify_substrips_on_local(fake_backend, mini_catalog) -> None: ...   # FILL IN: 12-slot row on a 600x3000 canvas; is_local=True -> 2 calls each <= 8 slots (count slot_ids in call prompts); is_local=False -> 1 call
@pytest.mark.asyncio
async def test_identify_marks_flag(shelf_image, fake_backend, mini_catalog) -> None: ...  # FILL IN: render_strip marks on/off bytes differ; marks=False equals the plain crop; cache_key(...) over the two PNGs differs
@pytest.mark.asyncio
async def test_identify_drops_unknown_ids(shelf_image, fake_backend, mini_catalog) -> None: ...  # FILL IN: answer contains "img_r09_s09" -> not in observations, errors has one string naming it
@pytest.mark.asyncio
async def test_identify_missing_ids_uncertain(shelf_image, fake_backend, mini_catalog) -> None: ...  # FILL IN: answer omits one slot -> uncertain/unusable + "missing_in_response"
@pytest.mark.asyncio
async def test_identify_downgrades_partial_empty(shelf_image, fake_backend, mini_catalog) -> None: ...  # FILL IN: empty+partial -> uncertain + issue; empty+full stays empty
@pytest.mark.asyncio
async def test_identify_failed_row(shelf_image, fake_backend, mini_catalog) -> None: ...  # FILL IN: row 1 RuntimeError, rows 2-3 ok -> 6 uncertain with "identify_failed", exactly one error string, other rows intact, no exception
@pytest.mark.asyncio
async def test_identify_resolves_only_occupied(shelf_image, fake_backend, mini_catalog) -> None: ...  # FILL IN: occupied reading with identifier == a mini_catalog sku -> resolution "direct"; empty/uncertain -> "unresolved"; facing_id is None everywhere
```
Queue the canned answers with `fake_backend.queue["identify"] = [...]`; use a callable entry
`lambda prompt, images: RowReading(...)` when the answer must depend on which slot ids the prompt contains
(calls are gathered concurrently, so do not rely on queue order across rows).

**Why this shape**: names 4–7 and 9 are the spec §4 M7 rows; the others pin decisions made here (balanced chunks, input
immutability, missing ids, failure isolation, "never sets facing_id"). `_reading` is complete to keep the bodies short.

### FILL IN checklist
- [ ] `identify.py::_plan_calls` — balanced contiguous chunks; bounded by `test_plan_calls_cloud_and_local`
- [ ] `identify.py::render_strip` (drawing only) — number over tag area / below the slot; bounded by `test_render_strip_marks_never_cover_product`
- [ ] `identify.py::build_identify_prompt` — wording; bounded by `test_prompt_has_no_expectations`
- [ ] `identify.py::_apply_reading_rules` — five ordered rules
- [ ] `identify.py::identify_rows::_one` — to_thread render, semaphore around `ask`, `except Exception`
- [ ] `test_plancheck_identify.py::_row_slots` and every `...` test body

---

## Acceptance Criteria

- [ ] `pytest examples/planogram/tests/test_plancheck_identify.py -q` passes without network.
- [ ] `ruff check examples/planogram/plancheck/identify.py examples/planogram/tests/test_plancheck_identify.py` is clean.
- [ ] Spec §5: the pass-1 prompt contains no planogram expectation; responses for unknown slot ids are dropped and logged/reported.
- [ ] Spec §5 / §8 Q4: local backends always use sub-strips of ≤ 8 slots; cloud rows are split only above 20 slots.
- [ ] Spec §5 / §8 Q6: `marks=False` sends unmarked strips (plain crop) and changes the cache key; marks never cover product pixels.
- [ ] `empty` with non-full visibility is downgraded to `uncertain`; missing ids become `uncertain`/`unusable`.
- [ ] A failed call never raises: its slots are `uncertain`, exactly one error string is returned, other rows are unaffected.
- [ ] `facing_id` is `None` on every returned observation; the input image is not mutated.
- [ ] No `print`; rendering runs in `asyncio.to_thread`; the LLM call is made under the shared semaphore.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest examples/planogram/tests/test_plancheck_identify.py -q`

---

## Test Specification

See the test-file block in the Implementation Blueprint — the listed function names are the required minimum.
Fixtures come from `examples/planogram/tests/conftest.py` (TASK-3337): `shelf_image`, `mini_catalog`,
`mini_planogram`, `fake_backend`. `fake_backend.is_local` is a plain attribute — set it per test.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** (§2 stage 5, §3 Module 7, §5, §7, §8 Q4/Q6) for full context.
2. **Check dependencies** — TASK-3338, TASK-3339, TASK-3341 and TASK-3342 must be in `sdd/tasks/completed/`
   (`examples/planogram/plancheck/models.py` with `SlotObservation`, `examples/planogram/plancheck/reference.py`,
   `examples/planogram/plancheck/grid.py`, `examples/planogram/plancheck/vision.py`).
3. **Verify the Codebase Contract** — open those four files and confirm the listed signatures/field names; fix the contract first if they drifted.
4. **Update status** in `sdd/tasks/index/new-planogram-compliance-algo.json` → `"in-progress"`.
5. **Implement** from the blueprint; complete every `# FILL IN:`; never change a fixed signature or path.
6. **Verify** all acceptance criteria; run the validation command.
7. **Move this file** to `sdd/tasks/completed/TASK-3344-identify.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
