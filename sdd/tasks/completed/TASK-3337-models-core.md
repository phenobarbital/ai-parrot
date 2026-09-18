# TASK-3337: plancheck package, core models and shared test fixtures

**Feature**: FEAT-565 — New Planogram Compliance Algorithm
**Spec**: `sdd/specs/new-planogram-compliance-algo.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3336
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1 (first half). Creates the `plancheck` helper package, the **reference,
geometry and perception** Pydantic models every other module imports, and the shared pytest
fixtures (`conftest.py`) every other task's tests rely on. The second half of `models.py`
(fusion / result / config models) is TASK-3338, which appends to the same file.

The models are a **contract**: names, fields, types and defaults come from the spec skeleton and
are not renegotiable. The fixtures are a contract too — eleven sibling tasks were written against
the exact fixture shapes listed below.

---

## Scope

- Create `examples/planogram/plancheck/__init__.py` (docstring + `__version__`, no re-exports).
- Create `examples/planogram/plancheck/models.py` with: type aliases (`Box`, `SlotOrigin`,
  `OccupancyState`, `Visibility`, `Resolution`, `Grade`, `PriceStatus`, `PositionStatus`),
  `StrictModel`, `PlanogramFacing`, `PlanogramRef` (+ `shelf()`), `CatalogItem`, `Catalog`
  (+ `by_sku()`), `Tag`, `TagRow`, `Slot`, `PriceReading`, `SlotReading`, `RowReading`,
  `VerificationReading`, `RowVerification`, `TagPriceReading`, `RowPriceReading`.
- Create `examples/planogram/tests/conftest.py` with the fixtures/constants/`FakeBackend` specified below.
- Create `examples/planogram/tests/test_plancheck_models.py`.

**NOT in scope**: `SlotObservation`, registration/result/report models and `Settings` (TASK-3338);
any loader or logic (`load_planogram` is TASK-3339 — conftest builds `PlanogramRef` by hand).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/planogram/plancheck/__init__.py` | CREATE | Package marker, docstring, `__version__ = "0.1.0"` |
| `examples/planogram/plancheck/models.py` | CREATE | Core models (part 1 of 2; TASK-3338 appends part 2) |
| `examples/planogram/tests/conftest.py` | CREATE | `sys.path` bootstrap, synthetic image/planogram/catalog fixtures, `FakeBackend` |
| `examples/planogram/tests/test_plancheck_models.py` | CREATE | Strictness, helpers, fixture self-checks |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from __future__ import annotations
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal
import cv2                      # opencv 4.10.0.84 in the shared venv
import numpy as np              # numpy 2.4.6
import pytest
from pydantic import BaseModel, ConfigDict, Field   # pydantic v2
```

### Existing Signatures to Use
```python
# Pattern reference only (do NOT import it): examples/planogram/inkcheck/inkcheck/schema.py
class StrictModel(BaseModel):                       # :5-6
    model_config = ConfigDict(extra="forbid")
# Facing id convention to keep: f"p{position:03d}_f{index}"   — examples/planogram/inkcheck/inkcheck/catalog.py:12
# Detector filters the synthetic image must satisfy — examples/planogram/white_label_detector/detect_price_labels.py:25-34
#   min_width*w < bw < max_width*w  (defaults .025/.09)  ;  .014*h < bh < .06*h  ;  1.65 < bw/bh < 4.4
#   rectangularity >= .75  ;  gray[y:y+bh, x:x+bw].std() >= 25   ← a uniformly white tag FAILS this → inner dark bar
# group_rows needs >= 4 aligned tags, pair dx >= .2*image_width, row span >= .25*image_width  (:74, :93)
```

### Does NOT Exist
- ~~`plancheck` on `sys.path` by default~~ — tests get it only through `conftest.py`'s `sys.path.insert`.
- ~~`asyncio_mode = "auto"`~~ — not configured; `FakeBackend.ask` is a coroutine, tests using it need `@pytest.mark.asyncio`.
- ~~`from inkcheck.schema import …`~~ — inkcheck is reference-only and not importable.
- ~~real SKUs in fixtures~~ — the repo is public; fixtures use the synthetic `AC-…`/`BO-…` scheme only.
- ~~`plancheck.vision.VisionError` in conftest~~ — conftest must not import any `plancheck` module except `plancheck.models`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "examples/planogram/plancheck/__init__.py", "action": "CREATE"},
    {"path": "examples/planogram/plancheck/models.py", "action": "CREATE"},
    {"path": "examples/planogram/tests/conftest.py", "action": "CREATE"},
    {"path": "examples/planogram/tests/test_plancheck_models.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:examples/planogram/white_label_detector/detect_price_labels.py#candidates",
    "sym:examples/planogram/white_label_detector/detect_price_labels.py#group_rows"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- One field per line, black line-length 120, Google-style class docstrings. `models.py` imports nothing but stdlib + pydantic.
- End `models.py` part 1 with the marker comment `# --- part 2 (TASK-3338): fusion, result and config models ---` so TASK-3338 has a unique anchor.
- `Box` is `tuple[int, int, int, int]` = x1, y1, x2, y2 in ORIGINAL image pixels.
- `PlanogramRef.shelf(n)` sorts by `(slot, facing)` — never by `position` (spec §2 stage 4).
- Fixture geometry is fixed (sibling tasks hard-code expectations): image 1200 (h) × 1600 (w); tag 70×30 at
  x = 150 + 220·i, y ∈ (300, 650, 1000); inner dark bar 40×10 centred; product block 160×200 ending 10 px above the tag top, horizontally centred on the tag.

---

## Implementation Blueprint

### Steps (in order)
1. Create `plancheck/__init__.py` — *why*: makes `plancheck` importable once conftest adds its parent to `sys.path`.
2. Write `models.py` part 1 from the two blocks below, verbatim — *why*: field names are a cross-task contract.
3. Write `conftest.py` from its two blocks — *why*: sibling tasks' tests consume these exact fixtures.
4. Write the test file and make it pass — *why*: it also self-checks that `shelf_image` satisfies the detector's filters numerically (no detector import needed).

### `examples/planogram/plancheck/__init__.py` (CREATE)
```python
"""plancheck — label-anchored planogram compliance check (FEAT-565 example helper package)."""

__version__ = "0.1.0"
```
**Why this shape**: no re-exports — modules import each other explicitly, which keeps the pure modules free of `parrot`.

### `examples/planogram/plancheck/models.py` (CREATE — part 1/2 of this task)
```python
"""Shared Pydantic v2 models for the planogram compliance check (FEAT-565)."""
from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Box = tuple[int, int, int, int]  # x1, y1, x2, y2 — ORIGINAL image pixels
SlotOrigin = Literal["tag_anchored", "gap_filled", "untagged_row"]
OccupancyState = Literal["occupied", "empty", "uncertain"]
Visibility = Literal["full", "partial", "unusable"]
Resolution = Literal["direct", "verified_by_expectation", "inferred", "ambiguous", "unresolved"]
Grade = Literal["high", "medium", "low"]
PriceStatus = Literal["read", "partial", "unreadable", "not_assessed", "conflict"]
PositionStatus = Literal[
    "match", "misplaced", "variant_unresolved", "mismatch", "empty", "inferred_present",
    "occupied_unassigned", "conflict", "not_assessed", "not_visible",
]


class StrictModel(BaseModel):
    """Base model: unknown fields are rejected."""

    model_config = ConfigDict(extra="forbid")


class PlanogramFacing(StrictModel):
    """One expected physical facing. ``facing_id`` is ``f"p{position:03d}_f{facing}"``."""

    facing_id: str
    position: int
    shelf: int
    segment: str
    slot: int  # physical left→right axis of the shelf (NOT ``position``)
    segment_slot: int
    facing: int
    sku: str
    brand: str | None
    identity_required: bool
    source_confidence: str = "unknown"
    reference_read_method: str = "unknown"  # direct | inferred | partial
    notes: str | None = None


class PlanogramRef(StrictModel):
    """The reference planogram as an ordered list of facings."""

    planogram_id: str
    source: str
    shelf_count: int
    facings: list[PlanogramFacing]

    def shelf(self, number: int) -> list[PlanogramFacing]:
        """Return the facings of one shelf ordered by ``(slot, facing)``."""
        return sorted((f for f in self.facings if f.shelf == number), key=lambda f: (f.slot, f.facing))


class CatalogItem(StrictModel):
    """User-supplied bridge between a part number and what the package shows."""

    sku: str
    brand: str
    display_name: str
    family: str | None = None
    xl: bool = False
    colors: list[str] = Field(default_factory=list)
    pack: int = 1
    identifiers: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    provenance: str | None = None


class Catalog(StrictModel):
    """All catalog items."""

    items: list[CatalogItem]

    def by_sku(self, sku: str) -> CatalogItem | None:
        """Return the item with this SKU, or ``None``."""
        return next((item for item in self.items if item.sku == sku), None)
```
**Why this shape**: copied from spec §3 Module 1; `segment_slot`, `reference_read_method` and `provenance`
come from design-research S3/S7/S4. `shelf()` and `by_sku()` are the only behaviour allowed in this file.

### `examples/planogram/plancheck/models.py` (CREATE — part 2/2 of this task, append directly below)
```python
class Tag(StrictModel):
    """A detected price tag. ``tag_id`` is ``f"{image_id}_r{row:02d}_p{position:02d}"``."""

    tag_id: str
    image_id: str
    row: int
    position: int
    box: Box
    crop_box: Box
    rectangularity: float


class TagRow(StrictModel):
    """One visible tag row; the fitted line is in ORIGINAL pixels (y = slope * x + intercept)."""

    image_id: str
    row: int
    slope: float
    intercept: float
    tags: list[Tag]
    synthesized: bool = False


class Slot(StrictModel):
    """A product area. ``slot_id`` is ``f"{image_id}_r{row:02d}_s{index:02d}"``."""

    slot_id: str
    image_id: str
    row: int
    index: int
    box: Box
    tag_id: str | None = None
    tag_box: Box | None = None
    origin: SlotOrigin


class PriceReading(StrictModel):
    """A price read from a tag. ``amount`` is only set when dollars AND cents were read."""

    raw: str | None = None
    amount: Decimal | None = None
    currency: str | None = None
    source: Literal["ocr", "llm", "none"] = "none"
    status: PriceStatus = "not_assessed"


class SlotReading(StrictModel):
    """Pass-1 LLM contract: what the model sees in one slot."""

    slot_id: str
    occupancy: OccupancyState
    visibility: Visibility
    brand: str | None = None
    family: str | None = None
    xl: bool | None = None
    colors: list[str] = Field(default_factory=list, max_length=8)
    pack: int | None = None
    visible_text: list[str] = Field(default_factory=list, max_length=20)
    evidence: str = Field(default="", max_length=400)


class RowReading(StrictModel):
    """Pass-1 response for one row strip."""

    slots: list[SlotReading]


class VerificationReading(StrictModel):
    """Pass-2 LLM contract. ``choice`` is an offered SKU, ``"other"`` or ``"cannot_tell"``."""

    slot_id: str
    choice: str
    evidence: str = Field(default="", max_length=400)


class RowVerification(StrictModel):
    """Pass-2 response for one row strip."""

    slots: list[VerificationReading]


class TagPriceReading(StrictModel):
    """Price-fallback LLM contract: one numbered contact-sheet cell (1-based)."""

    cell: int
    price_text: str | None


class RowPriceReading(StrictModel):
    """Price-fallback response for one row."""

    tags: list[TagPriceReading]


# --- part 2 (TASK-3338): fusion, result and config models ---
```
**Why this shape**: these are the geometry models and the three LLM response schemas. The trailing marker
comment is TASK-3338's unique insertion anchor — keep it as the last line of the file, exactly as written.

### `examples/planogram/tests/conftest.py` (CREATE — part 1/2)
```python
"""Shared fixtures for the plancheck tests (FEAT-565). Synthetic data only — the repo is public."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # → ``import plancheck``

from plancheck.models import Catalog, CatalogItem, PlanogramFacing, PlanogramRef  # noqa: E402

IMG_H, IMG_W = 1200, 1600
TAG_W, TAG_H, TAG_X0, TAG_DX = 70, 30, 150, 220
TAG_ROWS_Y = (300, 650, 1000)
TAGS_PER_ROW = 6
PRODUCT_W, PRODUCT_H, PRODUCT_GAP = 160, 200, 10
SHELF1_POSITIONS = (1, 2, 5, 3, 4, 6)  # deliberately NON-monotone vs slots 1..6


@pytest.fixture
def shelf_image() -> np.ndarray:
    """Dark canvas with 3 rows x 6 white tags (inner dark bar) and a coloured product block above each."""
    image = np.full((IMG_H, IMG_W, 3), 30, dtype=np.uint8)
    for r, top in enumerate(TAG_ROWS_Y):
        for i in range(TAGS_PER_ROW):
            x = TAG_X0 + TAG_DX * i
            cv2.rectangle(image, (x, top), (x + TAG_W - 1, top + TAG_H - 1), (245, 245, 245), -1)
            cv2.rectangle(image, (x + 15, top + 10), (x + 54, top + 19), (40, 40, 40), -1)
            cx = x + TAG_W // 2
            colour = (40 + 35 * i, 200 - 50 * r, 90 + 25 * ((i + r) % 4))
            cv2.rectangle(
                image,
                (cx - PRODUCT_W // 2, top - PRODUCT_GAP - PRODUCT_H),
                (cx + PRODUCT_W // 2 - 1, top - PRODUCT_GAP - 1),
                colour,
                -1,
            )
    return image


def _sku(shelf: int, slot: int) -> tuple[str, str | None]:
    """Return (sku, brand) of the synthetic planogram."""
    if shelf == 3 and slot == 6:
        return "CLOSEOUT", None
    return (f"AC-{shelf}{slot}", "Acme") if slot <= 3 else (f"BO-{shelf}{slot}", "Bolt")


def _position(shelf: int, slot: int) -> int:
    return SHELF1_POSITIONS[slot - 1] if shelf == 1 else (shelf - 1) * 6 + slot


@pytest.fixture
def mini_planogram_data() -> dict[str, Any]:
    """Raw source-schema planogram dict (same keys as the real file, synthetic values)."""
    shelves = []
    for shelf in (1, 2, 3):
        products = {}
        for slot in range(1, 7):
            sku, brand = _sku(shelf, slot)
            products[f"pos {shelf}:{slot}"] = {
                "position": _position(shelf, slot), "segment": "left" if slot <= 3 else "right",
                "segment_number": 1 if slot <= 3 else 2, "slot": slot,
                "segment_slot": slot if slot <= 3 else slot - 3, "product": sku, "brand": brand,
                "shelf": shelf, "facings": 2 if sku == "CLOSEOUT" else 1, "confidence": "high",
                "read_method": "inferred" if shelf == 2 else "direct", "notes": None,
            }
        shelves.append({"shelf": f"Shelf {shelf}", "shelf_number": shelf, "product_count": 6,
                        "facing_count": 7 if shelf == 3 else 6, "products": products})
    meta = {"product_count": 18, "physical_facing_count": 19, "source": "synthetic fixture", "shelves": 3,
            "segments": 2, "planogram": "Mini", "fixture": "test", "option": "A"}
    return {"planogram": meta, "shelves": shelves}
```
**Why this shape**: complete on purpose — sibling tasks assert against these exact pixels and ids. Colours are
saturated so product blocks never pass the white-tag threshold filters.

### `examples/planogram/tests/conftest.py` (CREATE — part 2/2, append below)
```python
@pytest.fixture
def mini_planogram(mini_planogram_data: dict[str, Any]) -> PlanogramRef:
    """The same planogram built directly from models (19 facings) — no loader involved."""
    facings = []
    for shelf in mini_planogram_data["shelves"]:
        for product in sorted(shelf["products"].values(), key=lambda p: p["slot"]):
            for k in range(1, product["facings"] + 1):
                facings.append(PlanogramFacing(
                    facing_id=f"p{product['position']:03d}_f{k}", position=product["position"],
                    shelf=product["shelf"], segment=product["segment"], slot=product["slot"],
                    segment_slot=product["segment_slot"], facing=k, sku=product["product"],
                    brand=product["brand"], identity_required=product["product"] != "CLOSEOUT",
                    source_confidence=product["confidence"], reference_read_method=product["read_method"],
                ))
    return PlanogramRef(planogram_id="mini", source="synthetic fixture", shelf_count=3, facings=facings)


@pytest.fixture
def mini_catalog() -> Catalog:
    """One item per identity-required SKU; slot 1/4 std black, 2/5 XL black, 3/6 std tri-color."""
    items = []
    for shelf in (1, 2, 3):
        for slot in range(1, 7):
            sku, brand = _sku(shelf, slot)
            if brand is None:
                continue
            family = f"{shelf}{0 if brand == 'Acme' else 1}"
            variant = (slot - 1) % 3
            xl, colors = variant == 1, (["tri-color"] if variant == 2 else ["black"])
            name = f"{brand} {family}{'XL' if xl else ''} {'Tri-color' if variant == 2 else 'Black'}"
            items.append(CatalogItem(sku=sku, brand=brand, display_name=name, family=family, xl=xl,
                                     colors=colors, identifiers=[sku], aliases=[name], provenance="fixture"))
    return Catalog(items=items)


class FakeBackend:
    """Stand-in for ``plancheck.vision.VisionBackend``: canned responses per stage."""

    def __init__(self, *, is_local: bool = False) -> None:
        self.is_local = is_local
        self.calls: list[dict[str, Any]] = []
        self.queue: dict[str, list[Any]] = {"identify": [], "verify": [], "prices": []}

    async def ask(self, prompt: str, images: Any, schema: type, *, stage: str, prompt_version: str) -> Any:
        """Pop the next canned item for ``stage``: raise it, call it, or return it."""
        self.calls.append({"stage": stage, "prompt": prompt, "n_images": len(images), "schema": schema})
        assert self.queue.get(stage), f"FakeBackend: no canned response left for stage {stage!r}"
        item = self.queue[stage].pop(0)
        if isinstance(item, Exception):
            raise item
        return item(prompt, images) if callable(item) else item


@pytest.fixture
def fake_backend() -> FakeBackend:
    """A fresh cloud-like fake backend."""
    return FakeBackend()
```
**Why this shape**: `FakeBackend.ask` mirrors the keyword-only signature spec §3 Module 6 fixes for
`VisionBackend.ask`. Families: Acme `10/20/30`, Bolt `11/21/31` by shelf.

### `examples/planogram/tests/test_plancheck_models.py` (CREATE)
```python
"""TASK-3337: core models are strict; fixtures honour their contract."""
from __future__ import annotations

import numpy as np
import pytest
from pydantic import ValidationError

from plancheck.models import Catalog, PlanogramRef, PriceReading, Slot, SlotReading


def test_models_forbid_extra() -> None:
    """Unknown fields are rejected on every StrictModel."""
    with pytest.raises(ValidationError):
        PriceReading(raw="$1.00", bogus=1)  # type: ignore[call-arg]
    # FILL IN: same assertion for Slot and SlotReading — bounded by spec §2 Data Models (extra="forbid")


def test_shelf_orders_by_slot_not_position(mini_planogram: PlanogramRef) -> None:
    """Shelf 1 positions are 1,2,5,3,4,6 but ``shelf(1)`` returns slots 1..6."""
    # FILL IN: assert [f.slot for f in mini_planogram.shelf(1)] == [1..6] and positions == [1, 2, 5, 3, 4, 6]
    #   (write the literal — never `from conftest import …`: the repo root also has a conftest.py, the name is ambiguous)
    raise NotImplementedError


def test_mini_planogram_has_19_facings_and_closeout(mini_planogram: PlanogramRef) -> None:
    # FILL IN: 19 facings; exactly 2 with identity_required False, both sku "CLOSEOUT", ids end _f1/_f2
    raise NotImplementedError


def test_mini_catalog_covers_identity_skus(mini_planogram: PlanogramRef, mini_catalog: Catalog) -> None:
    # FILL IN: every identity-required sku resolves via by_sku(); by_sku("nope") is None; 17 items
    raise NotImplementedError


def test_shelf_image_tags_pass_detector_filters(shelf_image: np.ndarray) -> None:
    """Numerically re-check the detector's filters on one tag crop (no detector import)."""
    # FILL IN: shape == (1200, 1600, 3); gray crop of tag (row 0, i 0) has std >= 25, mean > 150;
    #          70/30 aspect within (1.65, 4.4); 70 within (.025*1600, .09*1600); 30 within (.014*1200, .06*1200)
    raise NotImplementedError


@pytest.mark.asyncio
async def test_fake_backend_pops_raises_and_calls(fake_backend) -> None:
    # FILL IN: queue a value, an Exception and a callable under "identify"; assert return/raise/call order,
    #          `calls` bookkeeping, and AssertionError on an empty queue
    raise NotImplementedError
```
**Why this shape**: the fixture self-checks are what protect the eleven dependent tasks from a silently
broken fixture.

### FILL IN checklist
- [ ] `test_models_forbid_extra` — extend to `Slot`, `SlotReading`; bounded by `extra="forbid"`.
- [ ] `test_shelf_orders_by_slot_not_position` — bounded by spec §2 stage 4.
- [ ] `test_mini_planogram_has_19_facings_and_closeout` — bounded by the fixture contract in Implementation Notes.
- [ ] `test_mini_catalog_covers_identity_skus` — 17 items (18 positions − CLOSEOUT).
- [ ] `test_shelf_image_tags_pass_detector_filters` — bounded by `detect_price_labels.py:25-34`.
- [ ] `test_fake_backend_pops_raises_and_calls` — bounded by the `FakeBackend.ask` docstring.

---

## Acceptance Criteria

- [ ] `from plancheck.models import …` works for all 16 classes/aliases in Scope, from within the tests.
- [ ] `models.py` imports only stdlib + pydantic; ends with the TASK-3338 marker comment.
- [ ] Fixtures match the contract (geometry constants, 19 facings, 17 catalog items, `FakeBackend` semantics).
- [ ] No real part number appears anywhere (`grep -rn "AN#140\|T212" examples/planogram/plancheck examples/planogram/tests` is empty).
- [ ] `ruff check examples/planogram/plancheck examples/planogram/tests` clean.

---

## Validation Commands

- `pytest examples/planogram/tests/test_plancheck_models.py -q`

---

## Test Specification

See the blueprint's test file: six tests, five with FILL IN bodies bounded above.

---

## Agent Instructions

1. Read spec §2 "Data Models" and §3 Module 1.
2. Confirm TASK-3336 is done: `git check-ignore -q examples/planogram/plancheck/models.py` must exit 1. If it exits 0, STOP.
3. Write the blueprint blocks nearly verbatim; complete every `# FILL IN:`.
4. Verify acceptance criteria; move this file to `sdd/tasks/completed/`; set the index entry to `done`; fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-coder (native, model sonnet, attempt_uid 15630b4cf6774fdd866bbec83e290abc)
**Date**: 2026-09-17
**Notes**: Created `examples/planogram/plancheck/__init__.py`, `examples/planogram/plancheck/models.py`
(all 16 scoped classes/aliases ending with the TASK-3338 anchor comment), `examples/planogram/tests/conftest.py`
(sys.path bootstrap + fixtures + FakeBackend) and `examples/planogram/tests/test_plancheck_models.py`
(all 5 FILL IN test bodies completed). Verified the Codebase Contract manually (cv2/numpy/pydantic/
pytest-asyncio versions, no `asyncio_mode=auto`, detector filter constants, no import from the
nonexistent `inkcheck.schema`, no real SKUs). `pytest examples/planogram/tests/test_plancheck_models.py -q`
→ 6 passed; `ruff check` clean; re-ran TASK-3336's `test_plancheck_gitignore.py` → 8 passed (no
regression). Post-merge full suite `pytest examples/planogram/tests/ -q` → 14 passed. Lint auto-fixed
by the engine (black) on merge, commit `10364c92f`.

**Seat**: sonnet(native) · Backend: native · Model: sonnet · Attempts: 1 · Duration: n/a · Tokens: n/a

**Deviations from spec**: none
