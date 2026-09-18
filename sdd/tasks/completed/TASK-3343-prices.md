# TASK-3343: Tag price reading — price grammar, local OCR, LLM contact-sheet fallback

**Feature**: FEAT-565 — New Planogram Compliance Algorithm
**Spec**: `sdd/specs/new-planogram-compliance-algo.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3337, TASK-3342
**Assigned-to**: unassigned

---

## Context

Spec §2 stage 3 and §3 **Module 5: prices**. Shelf price tags are tiny (~200×110 px): the big
dollar amount is legible, the rest is not. The brainstorm probe (RapidOCR, 4× upscale, 56 crops)
read digits in 71 % of tags with **correct whole dollars but garbled superscript cents**
(`45%` for `$45.99`, `'59"`). Decision (brainstorm, resolved): **local OCR first, vision-LLM
fallback**, and *digits are never guessed*.

This module turns every tag-bearing `Slot` into a `PriceReading` (raw text + normalised
`Decimal`). Price is **reported only** — it never influences identity or the planogram score
(spec §1 G4/G10).

Dependencies: models `Slot`, `PriceReading`, `RowPriceReading`, `TagPriceReading` from
`examples/planogram/plancheck/models.py` (TASK-3337); the backend *type* `VisionBackend` from
`examples/planogram/plancheck/vision.py` (TASK-3342, imported under `TYPE_CHECKING` only — the
call contract `ask(prompt, images, schema, *, stage, prompt_version)` is what this module relies on).
Tests use `FakeBackend` from `examples/planogram/tests/conftest.py` (TASK-3337).

---

## Scope

- Implement `examples/planogram/plancheck/prices.py`: `PRICE_PROMPT_VERSION`, `parse_price`,
  `TagOcr`, `contact_sheet`, `read_prices` (+ the private helpers in the blueprint).
- `parse_price`: `read` **only** with dollars + separator + exactly two cents digits; dollars only →
  `partial` with `amount=None` and `raw` kept; nothing numeric → `unreadable`.
- `TagOcr`: lazy RapidOCR wrapper; `available=False` when the import fails (run continues LLM-only, one warning).
- `contact_sheet`: one PNG with 1-based numbered cells, the number drawn in a header band **above** each cell.
- `read_prices`: OCR off the event loop; per row **one** LLM call (stage `"prices"`, schema
  `RowPriceReading`) containing **only** the tags that are not `read`; slots without a tag →
  `not_assessed`; an LLM failure keeps the OCR result.
- Write `examples/planogram/tests/test_plancheck_prices.py`.

**NOT in scope**: `--prices` expected-price comparison and cross-photo price conflicts (TASK-3347
scoring); tag detection (TASK-3340); slot geometry (TASK-3341); the real `VisionBackend` (TASK-3342);
currency conversion or sale-price interpretation (spec Non-Goals); `pytesseract`/`easyocr`/`paddleocr`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/planogram/plancheck/prices.py` | CREATE | Price grammar, `TagOcr`, contact sheet, `read_prices` |
| `examples/planogram/tests/test_plancheck_prices.py` | CREATE | Unit tests (stub OCR + `FakeBackend`) |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified 2026-09-17/18 on `dev` and by execution in the shared venv.

### Verified Imports
```python
import asyncio, logging, re
from decimal import Decimal
from typing import TYPE_CHECKING
import cv2                       # opencv-python 4.10.0.84 installed
import numpy as np               # numpy 2.4.6 installed

# LAZY — inside TagOcr only (import cost + optional dependency):
from rapidocr import RapidOCR    # verified by execution, rapidocr 3.9.2 (onnxruntime 1.30.0)

from plancheck.models import PriceReading, RowPriceReading, Slot   # created by TASK-3337 (see below)
if TYPE_CHECKING:
    from plancheck.vision import VisionBackend                     # created by TASK-3342 — type-only
```

### Existing Signatures to Use
```python
# rapidocr 3.9.2 — verified by running it in .venv:
#   engine = RapidOCR()                 # heavy: loads ONNX models → construct ONCE, lazily
#   result = engine(img_bgr_ndarray)    # -> RapidOCROutput
#   result.txts   -> tuple[str, ...] | None     e.g. ('$45.99',)   ;  None when nothing is found
#   result.scores -> tuple[float, ...] | None   (not used by this task)

# examples/planogram/white_label_detector/detect_price_labels.py:146-147  (crop padding to reuse for tag crops)
#   px, py = max(2, round((x2-x1)*.12)), max(2, round((y2-y1)*.18))
#   crop_box = [max(0,x1-px), max(0,y1-py), min(ow,x2+px), min(oh,y2+py)]

# cv2 (all standard): cv2.resize(img, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC),
#   cv2.imencode(".png", img) -> (ok, buf), cv2.putText, cv2.copyMakeBorder, cv2.FONT_HERSHEY_SIMPLEX
```

### Created by dependency tasks (exist only after they land)
```python
# examples/planogram/plancheck/models.py  (TASK-3337) — field names are fixed by spec §3 Module 1
Box = tuple[int, int, int, int]            # x1, y1, x2, y2 — ORIGINAL image pixels
PriceStatus = Literal["read", "partial", "unreadable", "not_assessed", "conflict"]
class Slot(StrictModel):
    slot_id: str; image_id: str; row: int; index: int; box: Box
    tag_id: str | None = None; tag_box: Box | None = None; origin: SlotOrigin
class PriceReading(StrictModel):
    raw: str | None = None; amount: Decimal | None = None; currency: str | None = None
    source: Literal["ocr", "llm", "none"] = "none"; status: PriceStatus = "not_assessed"
class TagPriceReading(StrictModel): cell: int; price_text: str | None
class RowPriceReading(StrictModel): tags: list[TagPriceReading]

# examples/planogram/plancheck/vision.py  (TASK-3342)
class VisionBackend:
    async def ask(self, prompt: str, images: Sequence[bytes], schema: type[T], *, stage: str, prompt_version: str) -> T
# examples/planogram/tests/conftest.py  (TASK-3337): shelf_image, FakeBackend / fake_backend,
#   constants TAG_W=70, TAG_H=30, TAG_X0=150, TAG_DX=220, TAG_ROWS_Y=(300, 650, 1000), TAGS_PER_ROW=6
```

### Does NOT Exist
- ~~`tesseract` binary~~ — not installed; never use `pytesseract`.
- ~~`RapidOCR().txts` always a tuple~~ — it is `None` when no text is found; guard with `or ()`.
- ~~`Slot.crop_box`~~ — only `Tag` has `crop_box`; a `Slot` carries `tag_box` only → pad it here (12 % / 18 %).
- ~~an error channel in the spec signature of `read_prices`~~ — see "Additive parameters" below.
- ~~prices in the planogram JSON~~ — there are none; this module never reads the planogram.
- ~~`VisionError` in conftest~~ — `FakeBackend` raises `RuntimeError`; treat **any** `Exception` from `backend.ask` as a row failure.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "examples/planogram/plancheck/prices.py",
      "action": "CREATE"
    },
    {
      "path": "examples/planogram/tests/test_plancheck_prices.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:examples/planogram/white_label_detector/detect_price_labels.py#detect"
  ]
}
```

---

## Implementation Notes

### Decided grammar (do not re-decide)
1. Normalise: strip; a run of superscript digits (`⁰¹²³⁴⁵⁶⁷⁸⁹`) becomes `"." + ascii digits`; collapse whitespace.
   Nothing else is rewritten — `O`→`0`, `%`→`99`, `"`→digits are **forbidden** (that would invent digits).
2. `read` ⇔ `\$?\s*(\d{1,4})\s*[.,\s]\s*(\d{2})(?!\d)` matches — a **separator is mandatory** (`.`, `,` or
   whitespace). `4599` is *not* `45.99`. The OCR box joiner `" | "` is **not** a separator (`"45 | 99"` → partial).
3. Else the first `\d{1,4}` run → `partial`: `raw` = the input text, `amount=None`.
4. Else → `unreadable` (`raw` = the input text or `None` when empty).
5. `currency="USD"` only when a `$` was seen in a `read` result; `source` stays `"none"` — **callers** set
   `"ocr"`/`"llm"` with `model_copy(update=...)`.
Spec cases: `$45.99` read · `45 99` read · `45⁹⁹` read · `'59"` partial · `45%` partial · `口` unreadable.

### Additive parameters (flagged to the spec owner, defaults keep the spec call valid)
`read_prices(image, slots, ocr, backend, *, semaphore=None, errors=None)`:
- `semaphore`: the pipeline's shared `asyncio.Semaphore`; row LLM calls acquire it when given (the spec
  signature has no way to honour `--concurrency`).
- `errors`: optional out-list; one string is appended per failed row call ("records an issue upstream").

### Key Constraints
- RapidOCR is CPU-bound and the engine is not documented thread-safe → run **all** crops of an image in
  **one** `asyncio.to_thread` call that loops sequentially. Never call `ocr.read` inline in a coroutine.
- Fallback flow per row: only tags whose OCR status is not `read` go on the sheet; an LLM answer replaces the
  OCR reading **only** when `parse_price(price_text).status == "read"`; otherwise the OCR reading (incl. a
  `partial` raw) is kept. Unknown/duplicate cell numbers are ignored.
- `backend is None` or nothing pending → zero LLM calls. `ocr.available is False` → every tagged slot is pending.
- Coordinates are ORIGINAL pixels; clip padded crops to the image.
- `logging.getLogger(__name__)`; no `print`; black 120; strict type hints; Google-style docstrings.

### References in Codebase
- `examples/planogram/white_label_detector/detect_price_labels.py:146-147` — tag crop padding.
- `examples/planogram/inkcheck/README.md` §7 — price semantics this keeps (raw kept, nothing inferred).

---

## Implementation Blueprint

### Steps (in order)
1. Write `parse_price` and its table-driven test first — *why*: it is pure and every other function depends on its three-way outcome.
2. Write `TagOcr` with the import guarded in `__init__` and the engine built on first `read` — *why*: `available` must be known before any crop is processed, but the ONNX models should load only when needed.
3. Write `contact_sheet` — *why*: the fallback prompt refers to cell numbers, so the numbering rule (1-based, header band) must exist before `read_prices`.
4. Write `read_prices` following the 4-phase flow in the block — *why*: the "LLM only for unread tags, one call per row" rule is an acceptance criterion.
5. Complete the tests with a stub OCR and `FakeBackend`; run the validation command and `ruff check`.

### `examples/planogram/plancheck/prices.py` (CREATE) — part 1/2
```python
"""Tag price reading for the planogram compliance check (FEAT-565, Module 5).

Local OCR first, vision-LLM contact-sheet fallback. Digits are never inferred.
"""
from __future__ import annotations

import asyncio
import logging
import re
from decimal import Decimal
from typing import TYPE_CHECKING

import cv2
import numpy as np

from plancheck.models import PriceReading, RowPriceReading, Slot

if TYPE_CHECKING:
    from plancheck.vision import VisionBackend

logger = logging.getLogger(__name__)

PRICE_PROMPT_VERSION: str = "prices-v1"
PRICE_STAGE: str = "prices"
_SUPERSCRIPTS = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")
_READ = re.compile(r"(\$)?\s*(\d{1,4})\s*[.,\s]\s*(\d{2})(?!\d)")
_DOLLARS = re.compile(r"\d{1,4}")


def parse_price(text: str) -> PriceReading:
    """Parse OCR/LLM text into a PriceReading (``source`` is left ``"none"`` for the caller to set).

    ``read`` needs dollars + separator + two cents digits; dollars only -> ``partial`` (amount None);
    otherwise ``unreadable``. Only whitespace and the cents superscript are normalised.
    """
    # FILL IN: implement "Decided grammar" steps 1-5 of Implementation Notes verbatim
    #          — bounded by test_parse_price_cases (six spec cases + "4599" and "45 | 99" -> partial)
    raise NotImplementedError


class TagOcr:
    """Lazy RapidOCR wrapper. ``available`` is False when ``rapidocr`` cannot be imported."""

    available: bool

    def __init__(self) -> None:
        self._engine: object | None = None
        try:
            import rapidocr  # noqa: F401  (availability probe only)

            self.available = True
        except ImportError:
            self.available = False
            logger.warning("rapidocr is not installed: every price tag goes to the LLM fallback")

    def read(self, crop: np.ndarray) -> str:
        """4x bicubic upscale -> OCR -> texts joined with ' | '. Synchronous and CPU-bound."""
        # FILL IN: return "" when not available or crop is empty; build RapidOCR() once (lazy);
        #          result.txts may be None -> use `or ()`; join with " | "
        raise NotImplementedError


def contact_sheet(crops: list[np.ndarray], cell_height: int = 240) -> bytes:
    """One PNG with numbered cells (1-based) for the LLM fallback."""
    # FILL IN: resize each crop to cell_height (keep aspect, INTER_CUBIC); 40-px white header band
    #          ABOVE each cell with its number (never over the tag pixels); white 12-px gutters;
    #          wrap at 6 cells per line; cv2.imencode(".png"); raise ValueError on empty `crops`
    #          — bounded by test_contact_sheet_is_png_with_cells
    raise NotImplementedError
```
**Why this shape**: `parse_price`, `TagOcr.read` and `contact_sheet` signatures are fixed by the spec skeleton. `_READ`
is given complete because the *mandatory separator* is a decision, not an implementation detail — relaxing it turns
`4599` into an invented price. `TagOcr.__init__` probes the import only; the expensive engine is built on first read.

### `examples/planogram/plancheck/prices.py` (CREATE) — part 2/2
```python
def _tag_crop(image: np.ndarray, tag_box: tuple[int, int, int, int]) -> np.ndarray:
    """Tag pixels padded 12 % horizontally / 18 % vertically (min 2 px), clipped to the image."""
    # FILL IN: same arithmetic as detect_price_labels.py:146-147; image.shape[:2] is (height, width)
    raise NotImplementedError


def _ocr_all(ocr: TagOcr, crops: dict[str, np.ndarray]) -> dict[str, str]:
    """Sequential OCR of every crop (runs inside ONE worker thread)."""
    return {slot_id: ocr.read(crop) for slot_id, crop in crops.items()}


def _price_prompt(cells: int) -> str:
    """Instructions for the contact-sheet call."""
    # FILL IN: state that the image holds `cells` numbered shelf price tags; ask for the price text
    #          exactly as printed (dollars AND cents, with "$" when visible) per cell number; null when
    #          not fully legible; forbid guessing digits; one entry per cell
    raise NotImplementedError


async def read_prices(image: np.ndarray, slots: list[Slot], ocr: TagOcr, backend: "VisionBackend | None", *,
                      semaphore: asyncio.Semaphore | None = None,
                      errors: list[str] | None = None) -> dict[str, PriceReading]:
    """Return slot_id -> PriceReading for every slot.

    OCR runs via ``asyncio.to_thread``; per row, tags that are not ``read`` go to ONE contact-sheet
    LLM call (schema ``RowPriceReading``). Slots without a tag -> ``not_assessed``. An LLM failure
    keeps the OCR result, logs a warning and appends one message to ``errors`` when given.
    """
    # FILL IN — four phases, bounded by the read_prices tests:
    #   1. result = {slot_id: PriceReading()} for slots with tag_box None (status not_assessed, source none).
    #   2. crops = {slot_id: _tag_crop(...)} for tagged slots; texts = await asyncio.to_thread(_ocr_all, ocr, crops)
    #      when ocr.available else {}; reading = parse_price(text).model_copy(update={"source": "ocr"});
    #      with OCR unavailable the reading is PriceReading(status="unreadable").
    #   3. group tagged slots by `row` (sorted by index); pending = status != "read". Skip the row when
    #      backend is None or pending is empty. Else sheet = await asyncio.to_thread(contact_sheet, [...]),
    #      then (under `semaphore` when given) answer = await backend.ask(_price_prompt(n), [sheet],
    #      RowPriceReading, stage=PRICE_STAGE, prompt_version=PRICE_PROMPT_VERSION).
    #      Rows may run concurrently with asyncio.gather.
    #   4. cell k (1-based) -> pending[k-1]; replace ONLY when parse_price(price_text).status == "read"
    #      (source="llm"); ignore null text, out-of-range and duplicate cells. `except Exception` around the
    #      call: keep OCR readings, logger.warning, errors.append(f"prices {image_id} row {row}: {exc}").
    raise NotImplementedError
```
**Why this shape**: `_ocr_all` is complete on purpose — it is the "one thread, sequential loop" decision. The two
keyword-only parameters are additive (see Implementation Notes); calling `read_prices(image, slots, ocr, backend)` exactly
as the spec skeleton shows must keep working. Do not add a return-type error channel.

### `examples/planogram/tests/test_plancheck_prices.py` (CREATE)
```python
"""Unit tests for plancheck.prices (FEAT-565, TASK-3343). No network, no real OCR models."""
from __future__ import annotations

import sys
from decimal import Decimal

import cv2
import numpy as np
import pytest

from plancheck.models import PriceReading, RowPriceReading, Slot, TagPriceReading
from plancheck.prices import PRICE_STAGE, TagOcr, contact_sheet, parse_price, read_prices

# Mirror of the geometry constants in examples/planogram/tests/conftest.py (TASK-3337). Do NOT
# `from conftest import ...`: the repo root also has a conftest.py, so the bare module name is ambiguous.
TAG_W, TAG_H, TAG_X0, TAG_DX, TAG_ROWS_Y, TAGS_PER_ROW = 70, 30, 150, 220, (300, 650, 1000), 6


class StubOcr:
    """Duck-typed TagOcr: returns queued texts in call order."""
    def __init__(self, texts: list[str], available: bool = True) -> None:
        self.texts, self.available, self.reads = list(texts), available, 0
    def read(self, crop: np.ndarray) -> str:
        self.reads += 1
        return self.texts.pop(0)


def _row_slots(row: int, *, untagged_last: bool = False) -> list[Slot]:
    """Six tag-anchored slots of conftest row `row` (0-based), built from the shared constants."""
    # FILL IN: slot box = 160x200 block ending 10 px above the tag; tag_box from TAG_X0/TAG_DX/TAG_W/TAG_H;
    #          slot_id f"img_r{row+1:02d}_s{i+1:02d}"; origin "tag_anchored"; when untagged_last the last
    #          slot has tag_id=None, tag_box=None, origin "gap_filled"
    raise NotImplementedError


@pytest.mark.parametrize("text,status,amount", [
    ("$45.99", "read", Decimal("45.99")), ("45 99", "read", Decimal("45.99")), ("45⁹⁹", "read", Decimal("45.99")),
    ("'59\"", "partial", None), ("45%", "partial", None), ("口", "unreadable", None),
    ("4599", "partial", None), ("45 | 99", "partial", None), ("", "unreadable", None),
])
def test_parse_price_cases(text: str, status: str, amount: Decimal | None) -> None: ...   # FILL IN: status, amount, raw kept, source == "none", currency "USD" only for "$45.99"
def test_tag_ocr_unavailable_without_rapidocr(monkeypatch: pytest.MonkeyPatch) -> None: ...  # FILL IN: monkeypatch.setitem(sys.modules, "rapidocr", None) -> TagOcr().available is False and read(...) == ""
def test_contact_sheet_is_png_with_cells() -> None: ...       # FILL IN: 3 crops -> bytes decodable by cv2.imdecode; 7 crops -> taller sheet (wrap at 6); [] -> ValueError
@pytest.mark.asyncio
async def test_read_prices_llm_only_for_unread(shelf_image, fake_backend) -> None: ...   # FILL IN: OCR texts 4x"$10.99" + "12%" + "口"; queue one RowPriceReading(cells 1,2); exactly ONE call, stage "prices", n_images 1; both become read/source "llm"; the four stay source "ocr"
@pytest.mark.asyncio
async def test_read_prices_without_rapidocr(shelf_image, fake_backend) -> None: ...      # FILL IN: StubOcr([], available=False) -> reads == 0, all six tags on the sheet, no exception
@pytest.mark.asyncio
async def test_read_prices_untagged_slot_not_assessed(shelf_image, fake_backend) -> None: ...  # FILL IN: untagged_last=True -> that slot not_assessed/source none and never on the sheet
@pytest.mark.asyncio
async def test_read_prices_llm_failure_keeps_ocr(shelf_image, fake_backend) -> None: ... # FILL IN: queue RuntimeError; partial OCR reading survives with its raw; errors list gets one message
@pytest.mark.asyncio
async def test_read_prices_llm_partial_answer_does_not_overwrite(shelf_image, fake_backend) -> None: ...  # FILL IN: LLM returns "45" or null -> OCR reading unchanged
@pytest.mark.asyncio
async def test_read_prices_no_backend(shelf_image) -> None: ...   # FILL IN: backend=None -> no error, OCR results returned
```
**Why this shape**: the first, fourth and fifth names are the spec §4 M5 rows; the rest pin the decisions taken in this
task (OCR absence, untagged slots, failure keeps OCR, no overwrite by a worse LLM answer). `StubOcr` is complete so no
test ever loads the ONNX models.

### FILL IN checklist
- [ ] `prices.py::parse_price` — decided grammar steps 1–5; bounded by `test_parse_price_cases`
- [ ] `prices.py::TagOcr.read` — lazy engine, `txts or ()`
- [ ] `prices.py::contact_sheet` — header band numbering, wrap at 6, PNG bytes
- [ ] `prices.py::_tag_crop` — 12 % / 18 % padding, clipped
- [ ] `prices.py::_price_prompt` — no digit guessing, null when not fully legible
- [ ] `prices.py::read_prices` — four phases; bounded by the six `read_prices` tests
- [ ] `test_plancheck_prices.py::_row_slots` and every `...` test body

---

## Acceptance Criteria

- [ ] `pytest examples/planogram/tests/test_plancheck_prices.py -q` passes without network and without loading OCR models.
- [ ] `ruff check examples/planogram/plancheck/prices.py examples/planogram/tests/test_plancheck_prices.py` is clean.
- [ ] Spec §5: OCR first; only non-`read` tags reach the LLM, **one call per row**; digits are never invented (`partial` keeps `amount = null`).
- [ ] Spec §5: with `rapidocr` absent the run still completes (LLM-only price reading, one warning).
- [ ] Slots without a tag (`gap_filled` without tag, `untagged_row`) are `not_assessed`.
- [ ] Any exception from `backend.ask` keeps the OCR readings; nothing is raised to the caller.
- [ ] `read_prices(image, slots, ocr, backend)` (spec signature, no keywords) works.
- [ ] OCR never runs on the event loop (one `asyncio.to_thread` per image); no `print`; `VisionBackend` imported under `TYPE_CHECKING` only.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest examples/planogram/tests/test_plancheck_prices.py -q`

---

## Test Specification

See the test-file block in the Implementation Blueprint — the listed function names are the required
minimum; parametrised cases for `parse_price` are given in full and must not be relaxed.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** (§2 stage 3, §3 Module 5, §5, §7) for full context.
2. **Check dependencies** — TASK-3337 and TASK-3342 must be in `sdd/tasks/completed/`
   (`examples/planogram/plancheck/models.py`, `examples/planogram/plancheck/vision.py`, `examples/planogram/tests/conftest.py` exist).
3. **Verify the Codebase Contract** — confirm the model field names in `examples/planogram/plancheck/models.py` and the
   `FakeBackend.ask` signature in `examples/planogram/tests/conftest.py` match what is listed; fix the contract first if not.
4. **Update status** in `sdd/tasks/index/new-planogram-compliance-algo.json` → `"in-progress"`.
5. **Implement** from the blueprint; complete every `# FILL IN:`; never change a fixed signature or path.
6. **Verify** all acceptance criteria; run the validation command.
7. **Move this file** to `sdd/tasks/completed/TASK-3343-prices.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: sdd-coder (native, model sonnet, attempt_uid 0167082f529046529fba0082e52ede25)
**Date**: 2026-09-18
**Notes**: Created `examples/planogram/plancheck/prices.py` (parse_price grammar, TagOcr,
contact_sheet, `_tag_crop`/`_ocr_all`/`_price_prompt`, read_prices with concurrent
per-row LLM calls) and `examples/planogram/tests/test_plancheck_prices.py` with 17
tests. `pytest examples/planogram/tests/test_plancheck_prices.py -q` → 17 passed;
`ruff check` clean. Engine lint autofix commit `0df19a689`. Post-merge full suite
(after TASK-3344's fix) → 93 passed. Review recorded:
`coder-review:c36a4ebf81d3ca1bfa388b70`, no corrections needed.

**Seat**: sonnet(native) · Backend: native · Model: sonnet · Attempts: 1 · Duration: n/a · Tokens: n/a

**Deviations from spec**: none
