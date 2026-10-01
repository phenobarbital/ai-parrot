# TASK-3857: Own-box target OCR and per-run reference bank

**Feature**: FEAT-612 — Refactor Planogram Compliance
**Spec**: `sdd/specs/refactor-planogram-compliance.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3854, TASK-3855
**Assigned-to**: unassigned

---

## Context

Spec §2 **Stage 2: OCR, identity, references and rule evidence** and §3 **Module 3**
(skeletons `read_target_text`, `load_reference_bank`, `select_references`).

Today local OCR only reads price tags (`InkWall._read_tags`, `ink_wall.py:229`) and fact
tags/zones (`ProductOnShelves._ocr_tags_and_zones`, `product_on_shelves.py:513`); OCR of the
*slot* box (where the printed product code actually is) exists only in the ignored Nova example
(`examples/planogram/aws/nova2.py:103`). Reference images are never sent in the cycle path
(`_run_call` sends one PNG, `identify.py:363-365`).

This task creates the two pure-infrastructure helpers every later identification task
(TASK-3858 strategies, TASK-3859 shared identify stage, TASK-3871 orchestrator) builds on:

1. `identification/targets.py` — read the text inside each configured target's OWN
   source-pixel box through the bounded CPU pool.
2. `identification/references.py` — load/encode the configured reference images ONCE per run
   into `ReferenceImage` entries with stable opaque labels (`ref-0001`), and select a capped,
   expectation-free subset per call.

---

## Scope

- Create `read_target_text(image, perception, ctx) -> dict[str, OcrReading]`:
  - build a de-duplicated target list from `ctx.layout.ocr_targets` (`slot`, `tag`, `zone`);
  - crop each target by its own `box` (clamped to the image), never by its anchor tag;
  - run `read_crop` through `ctx.executor.run` in batches of `ctx.layout.ocr_batch_size`;
  - return `{}` when OCR is unavailable (`ctx.ocr is None` or `ctx.ocr.available is False`);
  - isolate engine/pool failures (error appended to `ctx.errors`, failed targets omitted);
    `asyncio.CancelledError` always propagates.
- Create `load_reference_bank(reference_images, ctx) -> list[ReferenceImage]`:
  - flatten in sorted catalogue-key order and stable list order;
  - accept `str`, `Path`, `PIL.Image.Image`, and lists/tuples of those;
  - read files with `asyncio.to_thread`, decode + PNG-encode through `ctx.executor.run`;
  - label by flattened position (`ref-0001`, `ref-0002`, …) so labels stay stable when one file
    fails; unreadable entries are skipped and reported in `ctx.errors`, never abort.
- Create `select_references(bank, readings, policy) -> (selected, diagnostics)` implementing
  `ReferencePolicy.enabled`, `selection="all"` and `selection="by_brand"` with the
  `max_per_call` cap and the documented fallback.
- Write `test_target_ocr.py` and `test_reference_images.py` (offline, synthetic data only).

**NOT in scope**:
- Sending references to the model, `reference_id` validation, the v2 prompt and the `slots`
  strategy — TASK-3858.
- Calling `read_target_text` from a stage / attaching readings to the perception — TASK-3859
  (`stages/identify.py`).
- Building the bank from `PlanogramCompliance.reference_images` at run entry and putting it on
  `CycleContext.reference_bank` — TASK-3871. Handler list hydration — TASK-3872.
- Any change to `perception/ocr.py`, `contracts.py`, `layout.py` or a planogram type.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/targets.py` | CREATE | `read_target_text` + target-list helper + picklable crop helper |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/references.py` | CREATE | `load_reference_bank`, `select_references`, picklable encoders |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_target_ocr.py` | CREATE | own-box OCR tests |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_reference_images.py` | CREATE | reference bank / selection tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from parrot_pipelines.planogram.contracts import (  # verified: planogram/contracts.py
    CycleContext,        # :322
    PerceptionResult,    # :86
    Shape,               # :50
    ShapeKind,           # :15  (PRICE_TAG, PRODUCT, BOX, FACT_TAG, ZONE, UNKNOWN)
    Slot,                # :67
)
from parrot_pipelines.planogram.perception.ocr import read_crop            # verified: perception/ocr.py:73
from parrot_pipelines.planogram.perception.membership import usable_shapes  # verified: perception/membership.py:249
from parrot_pipelines.planogram.identification.vision import encode_png    # verified: identification/vision.py:100
```

### Existing Signatures to Use
```python
# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/ocr.py
class OcrReader:                                   # :16
    available: bool                                # :26  (False when rapidocr cannot be imported)
def read_crop(crop: np.ndarray) -> Tuple[str, float]:   # :73  picklable, per-process singleton;
    # returns ("", 0.0) for empty crop / no text / engine exception (it logs, never raises ImportError)

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/executor.py
class CpuExecutor:                                 # :17
    async def run(self, fn: Callable[..., T], *args: Any) -> T:   # :62 positional args only, fn module-level

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/vision.py
def encode_png(image: np.ndarray) -> bytes:        # :100 raises ValueError when cv2.imencode fails

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/membership.py
def usable_shapes(shapes: Sequence[Shape]) -> List[Shape]:   # :249  ON_FIXTURE subset, order kept

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py
class PerceptionResult(BaseModel):   # :86 image_id, image_size (w, h), shapes, slots, zones, ..., errors
class Shape(BaseModel):              # :50 shape_id, kind: ShapeKind, box: DetectionBox, ...
class Slot(BaseModel):               # :67 slot_id, row_index, slot_index, box, anchor_shape_id, inferred
class CycleContext(BaseModel):       # :322 vision, executor, ocr, definition, bindings, ..., errors: List[str]

# Pattern to mirror (do not import, do not edit): ink_wall.py:229-239 `_read_tags` — batches of 16,
# `asyncio.gather(*(ctx.executor.run(read_crop, crop) for crop in crops))`, crop = bgr[y1:y2, x1:x2].
# PIL -> BGR pattern: ink_wall.py:149-151 `np.asarray(image.convert("RGB"))[:, :, ::-1].copy()`.

# packages/ai-parrot-pipelines/src/parrot_pipelines/models.py:65 (input shape of reference_images)
reference_images: Dict[str, Union[str, Path, List[str], List[Path], Image.Image]]
```

### Symbols created by dependency tasks (not yet on dev)
```python
# TASK-3854 — planogram/contracts.py (spec §3 Module 1 skeleton)
class OcrReading(BaseModel):
    text: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
class ReferenceImage(BaseModel):
    label: str
    image: bytes
    catalog_key: str
    brand: str | None = None
# CycleContext.layout: Any = None   (a validated LayoutProfile)
# CycleContext.reference_bank: list[ReferenceImage]

# TASK-3855 — planogram/layout.py
class ReferencePolicy(BaseModel):
    enabled: bool = True
    selection: Literal["all", "by_brand"] = "all"
    max_per_call: int = 5
    brand_by_reference: dict[str, str] = Field(default_factory=dict)   # catalogue key -> brand
class LayoutProfile(BaseModel):
    ocr_batch_size: int = 16
    ocr_targets: list[Literal["slot", "tag", "zone"]] = ["slot", "tag", "zone"]
    references: ReferencePolicy = Field(default_factory=ReferencePolicy)
    # ... other fields not used here
```

### Does NOT Exist
- ~~`parrot_pipelines.planogram.identification.targets` / `.references`~~ — this task creates them.
- ~~an OCR of slot boxes in the package~~ — only in `examples/planogram/aws/nova2.py:103` (ignored example; never import it).
- ~~`CycleContext.diagnostics`~~ — there is no diagnostics sink; use `ctx.errors` for unreadable references (see Implementation Notes).
- ~~`aiofiles`~~ — not a dependency; file reads use `asyncio.to_thread` (pattern: `plan.py:222`, `vision.py:309`).
- ~~`OcrReader.read` inside the pool~~ — never submit the bound method; submit the module-level `read_crop`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/targets.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/references.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_target_ocr.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_reference_images.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/ocr.py#read_crop",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/ocr.py#OcrReader",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/executor.py#CpuExecutor.run",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/membership.py#usable_shapes",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/vision.py#encode_png",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py#PerceptionResult",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py#CycleContext",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py#Shape",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py#Slot",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py#ShapeKind"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
- OCR batching: copy the shape of `InkWall._read_tags` (`ink_wall.py:229-239`) but make the batch
  size `ctx.layout.ocr_batch_size` and key results by target id.
- CPU work: only module-level functions go to `ctx.executor.run` with positional arguments
  (spec §7 "Patterns to Follow"). Never submit a lambda, a bound method or the `OcrReader`.
- Reference `read_crop` through the module global at call time (`ctx.executor.run(read_crop, crop)`)
  so tests can `monkeypatch.setattr(targets, "read_crop", fake)`.

### Key Constraints
- **Own box only** (spec §2 Stage 2, AC5): a slot's text comes from the slot box, never from its
  `anchor_shape_id` tag. Tag reads stay separately attributable under the tag's own shape id.
- **Target list**: `slot` → `perception.slots`, or when there are no slots the on-fixture non-zone
  shapes (`usable_shapes(...)` minus `ShapeKind.ZONE`); `tag` → shapes whose kind is
  `PRICE_TAG` or `FACT_TAG`; `zone` → `perception.zones`. De-duplicate by id, keep the first
  occurrence, keep a deterministic order (slots/shapes, then tags, then zones).
- **Absent OCR is not emptiness** (AC7): `{}` or an empty `OcrReading` never means a slot is empty;
  this module never writes occupancy.
- `ctx.layout is None` must not crash: fall back to `ocr_targets=("slot","tag","zone")` and batch 16
  (the `LayoutProfile` defaults) — callers from older tests pass a bare `CycleContext`.
- **References never inspect expected shelf products** (spec §2, AC7): `select_references` only sees
  the bank, the current call's OCR readings and the policy.
- `by_brand`: a brand is "observed" when its casefolded name occurs as a substring of the
  casefolded text of any reading passed in. No observed brand ⇒ behave as `all` and add the
  diagnostic `"references: by_brand found no observed brand; fell back to all"`.
- Cap 5 is a configurable starting bound (spec §8), not a backend guarantee — never hardcode 5
  here; always read `policy.max_per_call`.
- Do not resize reference images (the spec sets no size rule; do not invent one).
- Diagnostics: `select_references` RETURNS messages (TASK-3858 decides where they go);
  `load_reference_bank` appends one `ctx.errors` entry per unreadable reference
  (`"references: unreadable <catalog_key>[<index>]: <exc>"`) and logs it.

### References in Codebase
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/ink_wall.py:229-239` — OCR batch pattern
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py:513-526` — tag/zone OCR pattern
- `examples/planogram/aws/nova2.py:103-125` — slot-box OCR recipe being promoted (read only)
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py:222` — `asyncio.to_thread` file-read pattern

---

## Implementation Blueprint

### Steps (in order)
1. Confirm TASK-3854/TASK-3855 landed: `grep -n "class OcrReading\|class ReferenceImage" .../contracts.py` and `grep -n "class ReferencePolicy\|ocr_batch_size" .../layout.py` — *why*: both modules import those symbols; if absent, STOP (dependency not done).
2. Write `targets.py` from the block below and fill its markers — *why*: the pure crop/target helpers are needed by the tests before the async wrapper.
3. Write `references.py` from the block below — *why*: independent of targets.py; keeps load (I/O) and select (pure) separate.
4. Write both test files from the Test Specification — *why*: AC mapping to spec §4 rows "own-target OCR" and "reference bank".
5. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot-pipelines/src:packages/ai-parrot/src` — *why*: the shared venv is editable-installed against the main checkout.

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/targets.py` (CREATE)
```python
"""Own-box local OCR of identification targets (FEAT-612, spec §2 Stage 2 / Module 3)."""

from __future__ import annotations

import asyncio
import logging
from typing import Dict, List, Sequence, Tuple, Union

import numpy as np

from parrot_pipelines.planogram.contracts import CycleContext, OcrReading, PerceptionResult, Shape, ShapeKind, Slot
from parrot_pipelines.planogram.perception.membership import usable_shapes
from parrot_pipelines.planogram.perception.ocr import read_crop

logger = logging.getLogger(__name__)

_DEFAULT_OCR_TARGETS: Tuple[str, ...] = ("slot", "tag", "zone")  # LayoutProfile defaults (TASK-3855)
_DEFAULT_BATCH: int = 16
_TAG_KINDS = frozenset({ShapeKind.PRICE_TAG, ShapeKind.FACT_TAG})
OcrTarget = Union[Slot, Shape]


def target_id(target: OcrTarget) -> str:
    """``slot_id`` for slots, ``shape_id`` for shapes (same convention as identify._target_id)."""
    return target.slot_id if isinstance(target, Slot) else target.shape_id


def ocr_targets(perception: PerceptionResult, kinds: Sequence[str]) -> List[OcrTarget]:
    """De-duplicated, deterministic list of targets for the requested kinds.

    Args:
        perception: Stage-1 output of one image.
        kinds: Subset of ``("slot", "tag", "zone")``.

    Returns:
        Slots (or on-fixture non-zone shapes when there are no slots), then tags, then zones; first id wins.
    """
    # FILL IN: build the list per "Key Constraints → Target list" — bounded by AC5 (own box, tags separate)
    raise NotImplementedError


def crop_box(image: np.ndarray, box: Tuple[int, int, int, int]) -> np.ndarray:
    """Clamp ``(x1, y1, x2, y2)`` to the image and return a contiguous copy (may be empty)."""
    # FILL IN: clamp to image.shape[:2]; return image[y1:y2, x1:x2].copy() (size 0 when degenerate)
    raise NotImplementedError


async def read_target_text(
    image: np.ndarray, perception: PerceptionResult, ctx: CycleContext
) -> Dict[str, OcrReading]:
    """Read configured own-box targets through the bounded CPU pool; empty map if OCR unavailable.

    Args:
        image: Untouched full-resolution BGR image.
        perception: Stage-1 output of the image (source-pixel boxes).
        ctx: Per-run services (``ocr`` availability probe, ``executor``, ``layout``, ``errors``).

    Returns:
        ``target id -> OcrReading`` for every target read (text may be ``""``); ``{}`` when OCR is off.
    """
    if ctx.ocr is None or not getattr(ctx.ocr, "available", False):
        return {}
    layout = ctx.layout
    kinds = tuple(layout.ocr_targets) if layout is not None else _DEFAULT_OCR_TARGETS
    batch = int(layout.ocr_batch_size) if layout is not None else _DEFAULT_BATCH
    targets = ocr_targets(perception, kinds)
    readings: Dict[str, OcrReading] = {}
    for start in range(0, len(targets), batch):
        chunk = targets[start : start + batch]
        crops = [crop_box(image, (t.box.x1, t.box.y1, t.box.x2, t.box.y2)) for t in chunk]
        # FILL IN: gather ctx.executor.run(read_crop, crop) for the chunk; on a non-cancellation Exception
        #   append f"{perception.image_id}: ocr_failed: {exc}" to ctx.errors, log a warning and skip the chunk;
        #   otherwise store OcrReading(text=text, confidence=conf) under target_id(t) — bounded by AC5, AC12
    logger.debug("read_target_text[%s]: %d targets, %d readings", perception.image_id, len(targets), len(readings))
    return readings
```
**Why this shape**: spec §3 fixes the `read_target_text` signature; `ocr_targets`/`crop_box` are
public-but-helper functions so TASK-3858/TASK-3859 reuse the SAME target order and crops rather
than re-deriving them. The availability probe uses `ctx.ocr.available` exactly as
`ink_wall.py:211` does; `enabled_ocr=False` is enforced upstream by the orchestrator leaving
`ctx.ocr=None` (TASK-3871).

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/references.py` (CREATE)
```python
"""Per-run reference-image bank and expectation-free selection (FEAT-612, spec §2 Stage 2 / Module 3)."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, List, Mapping, Sequence, Tuple

import cv2
import numpy as np
from PIL import Image

from parrot_pipelines.planogram.contracts import CycleContext, OcrReading, ReferenceImage
from parrot_pipelines.planogram.identification.vision import encode_png
from parrot_pipelines.planogram.layout import ReferencePolicy

logger = logging.getLogger(__name__)

LABEL_FORMAT: str = "ref-{:04d}"


def reference_label(index: int) -> str:
    """Opaque, stable label of the ``index``-th (1-based) flattened reference."""
    return LABEL_FORMAT.format(index)


def flatten_references(reference_images: Mapping[str, Any]) -> List[Tuple[str, Any]]:
    """``(catalog_key, source)`` pairs in sorted-key, stable-list order (str / Path / PIL / lists of those)."""
    # FILL IN: sorted(keys); a list/tuple value expands in its own order; anything else is one entry
    raise NotImplementedError


def encode_reference_bytes(data: bytes) -> bytes:
    """Decode encoded file bytes and re-encode as PNG. Module-level and picklable (CPU executor).

    Raises:
        ValueError: the bytes are not a decodable image.
    """
    decoded = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if decoded is None:
        raise ValueError("not a decodable image")
    return encode_png(decoded)


async def load_reference_bank(reference_images: Mapping[str, Any], ctx: CycleContext) -> List[ReferenceImage]:
    """Load stable labels once per run; record file/encoding failures and retain valid entries.

    Args:
        reference_images: ``PlanogramConfig.reference_images`` (catalogue key -> path / list / PIL image).
        ctx: Per-run services (``executor``, ``layout.references.brand_by_reference``, ``errors``).

    Returns:
        Valid references in flattened order; the label index counts failed entries too.
    """
    policy = ctx.layout.references if ctx.layout is not None else ReferencePolicy()
    bank: List[ReferenceImage] = []
    for index, (catalog_key, source) in enumerate(flatten_references(reference_images), start=1):
        try:
            # FILL IN: str/Path -> data = await asyncio.to_thread(Path(source).read_bytes), then
            #   png = await ctx.executor.run(encode_reference_bytes, data);
            #   PIL image -> bgr = np.asarray(source.convert("RGB"))[:, :, ::-1].copy(); png = await ctx.executor.run(encode_png, bgr);
            #   any other type -> raise TypeError(...) — bounded by spec §2 "path, path-list and PIL-image forms"
            png = b""
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - one unreadable reference never aborts identification
            message = f"references: unreadable {catalog_key}[{index}]: {exc}"
            logger.warning(message)
            ctx.errors.append(message)
            continue
        bank.append(
            ReferenceImage(
                label=reference_label(index),
                image=png,
                catalog_key=catalog_key,
                brand=policy.brand_by_reference.get(catalog_key),
            )
        )
    return bank


def select_references(
    bank: Sequence[ReferenceImage], readings: Mapping[str, OcrReading], policy: ReferencePolicy
) -> Tuple[List[ReferenceImage], List[str]]:
    """Return stable capped images and diagnostic messages; never inspect expected shelf products.

    Args:
        bank: The run's reference bank (flattened order).
        readings: OCR readings of the CURRENT call's targets only.
        policy: The layout's reference policy.

    Returns:
        ``(selected, diagnostics)``; ``selected`` keeps bank order and has at most ``policy.max_per_call`` items.
    """
    # FILL IN: disabled or empty bank -> ([], ["references: disabled"] / ["references: none configured"]);
    #   "all" -> first max_per_call; "by_brand" -> brands observed in readings (see Key Constraints),
    #   fallback to "all" with its diagnostic; always add "references: selected <labels>" and, when capped,
    #   "references: omitted <labels> (cap <n>)" — bounded by AC6, AC7
    raise NotImplementedError
```
**Why this shape**: spec §3 fixes the three public signatures. Labels are position-based so the
same config always yields the same label for the same file even if another file is missing
(spec: "retain a stable opaque label"). `VisionAdapter.ask` needs `bytes` (`vision.py:173`), so
the bank stores PNG bytes once per run and later calls only slice the list — the adapter cache
key already includes ordered image bytes (`vision.py:204`), so adding references invalidates old
cache entries naturally.

### FILL IN checklist
- [ ] `targets.py::ocr_targets` — slot/shape/tag/zone list, de-dup, order; bounded by AC5
- [ ] `targets.py::crop_box` — clamp + copy; bounded by picklability (spec §7)
- [ ] `targets.py::read_target_text` — batched gather, failure isolation, CancelledError propagates; bounded by AC5, AC12
- [ ] `references.py::flatten_references` — sorted keys, stable list order; bounded by spec §2
- [ ] `references.py::load_reference_bank` — per-type load branch; bounded by spec §2 input forms
- [ ] `references.py::select_references` — all / by_brand / fallback / cap diagnostics; bounded by AC6, AC7

---

## Acceptance Criteria

- [ ] AC5: slot, tag and zone targets are cropped from their own boxes; confidence is preserved; `{}` when `ctx.ocr` is None or unavailable.
- [ ] AC5/AC12: an executor exception for one batch is recorded in `ctx.errors` and does not abort the other batches; `CancelledError` propagates.
- [ ] AC6: path, path-list and PIL inputs load in sorted-key/stable-list order with labels `ref-0001…`; a missing file is reported and skipped.
- [ ] AC6: `select_references` never returns more than `max_per_call`; capped labels appear in diagnostics.
- [ ] AC7: `select_references` uses only readings actually passed in; no expected product is an input.
- [ ] No module-level lambda/closure is submitted to the pool; `ruff check` and `black --check` pass on touched files.

---
- [ ] Lint/format clean: `ruff check packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/targets.py packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/references.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_target_ocr.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_reference_images.py`
- [ ] Lint/format clean: `black --check --line-length 120 packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/targets.py packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/references.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_target_ocr.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_reference_images.py`

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_target_ocr.py -q`
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_reference_images.py -q`
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_ocr_reader.py -q`

---

## Test Specification

```python
# packages/ai-parrot-pipelines/tests/planogram_cycle/test_target_ocr.py
import numpy as np
import pytest

from parrot.models.detections import DetectionBox
from parrot_pipelines.planogram.contracts import CycleContext, FixtureMembership, PerceptionResult, Shape, ShapeKind, Slot
from parrot_pipelines.planogram.identification import targets as targets_module
from parrot_pipelines.planogram.identification.targets import ocr_targets, read_target_text
from parrot_pipelines.planogram.layout import LayoutProfile  # TASK-3855


class InlineExecutor:
    """Runs fn inline and records every submission (fn, args)."""
    def __init__(self):
        self.calls = []
    async def run(self, fn, *args):
        self.calls.append((fn, args))
        return fn(*args)


class _Ocr:
    available = True


def _fake_read(crop):
    """Text encodes the crop's mean pixel value, so each target proves its own box was read."""
    return (f"v{int(crop.mean())}", 0.87) if crop.size else ("", 0.0)


# fixture: 300x200 BGR image; slot box painted value 50, its anchor tag painted 150, one zone painted 220;
# perception with slots=[slot(anchor=tag)], shapes=[tag PRICE_TAG ON_FIXTURE], zones=[zone]


async def test_slot_text_comes_from_slot_box_not_anchor_tag(monkeypatch): ...
    # monkeypatch.setattr(targets_module, "read_crop", _fake_read)
    # readings[slot_id].text == "v50" and readings[tag_id].text == "v150"; confidence == 0.87 preserved


async def test_zone_and_tag_are_separate_targets(monkeypatch): ...
    # readings has exactly {slot_id, tag_id, zone_id}; zone text "v220"


def test_ocr_targets_respects_profile_subset(): ...
    # ocr_targets(perception, ["zone"]) == [zone]; ["slot"] with no slots -> usable non-zone shapes only


def test_ocr_targets_deduplicates_ids(): ...
    # a zone that also appears in perception.shapes is listed once


async def test_ocr_unavailable_returns_empty_map(): ...
    # ctx.ocr=None -> {} and executor never called; ctx.ocr.available False -> {}


async def test_batches_bounded_by_ocr_batch_size(monkeypatch): ...
    # 5 slots, LayoutProfile(... ocr_batch_size=2) -> 3 gather rounds; every call's fn is the module-level read_crop replacement


async def test_executor_failure_is_isolated_and_recorded(monkeypatch): ...
    # executor raising RuntimeError on the first batch -> ctx.errors has one "ocr_failed" entry, later batch still read


async def test_empty_text_is_not_empty_occupancy(monkeypatch): ...
    # fake returns ("", 0.0) -> OcrReading(text="") present; nothing about occupancy is produced


# packages/ai-parrot-pipelines/tests/planogram_cycle/test_reference_images.py
from PIL import Image
from parrot_pipelines.planogram.contracts import OcrReading, ReferenceImage
from parrot_pipelines.planogram.identification.references import (
    flatten_references, load_reference_bank, reference_label, select_references,
)
from parrot_pipelines.planogram.layout import ReferencePolicy


def test_flatten_sorted_keys_and_stable_list_order(tmp_path): ...
    # {"b": [p2, p1], "a": p3} -> [("a", p3), ("b", p2), ("b", p1)]


async def test_path_list_and_pil_inputs_load_with_stable_labels(tmp_path): ...
    # write two PNGs with PIL; pass {"a": path, "b": [path2], "c": Image.new(...)} -> labels ref-0001..ref-0003,
    # every image starts with b"\x89PNG"


async def test_missing_file_is_isolated_and_reported(tmp_path): ...
    # {"a": tmp_path/"missing.png", "b": good} -> one entry labelled ref-0002; ctx.errors mentions "a[1]"


def test_all_selection_caps_and_reports_omitted(): ...
    # 7 refs, max_per_call=5 -> 5 selected in bank order; a diagnostic lists ref-0006, ref-0007


def test_by_brand_uses_only_observed_text(): ...
    # brands {"x": "Acme", "y": "Zeta"}; readings {"s1": OcrReading(text="ACME 62XL")} -> only "x" selected


def test_by_brand_without_observed_brand_falls_back_to_all(): ...
    # readings with no brand text -> same as "all" + "fell back to all" diagnostic


def test_disabled_policy_selects_nothing(): ...
    # ReferencePolicy(enabled=False) -> ([], [...disabled...])
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
9. **Close the task** with `scripts/sdd/close_task.sh TASK-3857 refactor-planogram-compliance verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

Merged cleanly via sdd-worker orchestration; lint clean (residual style debt left to /sdd-done).

