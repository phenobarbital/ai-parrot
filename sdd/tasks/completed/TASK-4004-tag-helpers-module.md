# TASK-4004: Move fact-tag helpers to comparison/tags.py

**Feature**: FEAT-624 — Planogram `fact_tag_present` rule
**Spec**: `sdd/specs/planogram-fact-tag-rule.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2. The rule evaluator in `comparison/rules.py` needs the two helpers that find a
tag's slot and read its text. They are private functions in `types/product_on_shelves.py`, and
`comparison/` cannot import from `types/` (types → `stages.compare` → `comparison.rules` would be
a cycle). They move to a new `comparison/tags.py`, plus a small price reader.

---

## Scope

- Create `comparison/tags.py` with `tag_text`, `slot_above` (bodies moved verbatim) and `tag_price`.
- In `types/product_on_shelves.py`, delete `_tag_text` and `_slot_above` and import the public
  names; update the two call sites in `_corroborate_with_fact_tags`.
- Write the tests listed below.

**NOT in scope**: any behaviour change in `_corroborate_with_fact_tags`; touching `ink_wall.py`
(its `_PRICE` / `_parse_price` stay where they are).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/tags.py` | CREATE | public tag helpers |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py` | MODIFY | use the moved helpers |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_fact_tag_helpers.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.models.detections import DetectionBox  # verified: packages/ai-parrot/src/parrot/models/detections.py:37 (x1, y1, x2, y2: int; confidence: float 0..1)
from parrot_pipelines.planogram.contracts import Identification, OcrReading, Shape, ShapeKind, Slot  # verified: contracts.py:123,80,51,15,68
```

### Existing Signatures to Use
```python
# types/product_on_shelves.py
def _tag_text(tag: Shape, readings: Mapping[str, object], reads: Mapping[str, Identification]) -> Optional[str]:  # line 96
    """Return own-box OCR of a fact tag, falling back to shape or vision text."""
def _slot_above(tag: Shape, slots: Sequence[Slot]) -> Optional[Slot]:  # line 105
    """Return the slot whose lower area is labelled by a fact tag."""
#   only callers: ProductOnShelves._corroborate_with_fact_tags, lines 211-212:
#       text = _tag_text(tag, readings, reads)
#       slot = _slot_above(tag, perception.slots) if text else None
#   imports: `from typing import ClassVar, Dict, List, Mapping, Optional, Sequence` (line 9),
#            `from ..comparison.definition import SlotsDefinition` (line 15)

# types/ink_wall.py
_PRICE = re.compile(r"(\d+)[.,](\d{2})")  # line 37 — pattern to reuse (do not import from types/)

# contracts.py
class Shape(BaseModel):  # line 51 — shape_id, image_id, kind, box: DetectionBox, ocr_text, membership
class Slot(BaseModel):   # line 68 — slot_id, image_id, row_index, slot_index, box, anchor_shape_id
class OcrReading(BaseModel):  # line 80 — text, confidence
```

### Does NOT Exist
- ~~`parrot_pipelines.planogram.comparison.tags`~~ — created by this task.
- ~~`parrot_pipelines.planogram.types.ink_wall.tag_price`~~ — no shared price helper exists.
- ~~`test_product_on_shelves_*` tests calling `_tag_text` / `_slot_above`~~ — verified: no test imports them (only `product_on_shelves.py` uses them).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/tags.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_fact_tag_helpers.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py#_tag_text",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py#_slot_above",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py#ProductOnShelves._corroborate_with_fact_tags"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- This is a MOVE: copy the two bodies unchanged — the existing product-on-shelves tests are the
  regression net for `_corroborate_with_fact_tags`.
- `tags.py` imports only from `contracts` (never from `types/` or `stages/`).
- After the move, drop `Mapping` from the `typing` import of `product_on_shelves.py` only if ruff
  reports it unused.

---

## Implementation Blueprint

### Steps (in order)
1. Create `tags.py` and paste the two bodies — *why*: the rule evaluator (TASK-4005) imports them from here.
2. Add `tag_price` — *why*: `price_required` needs a legible-amount check; same pattern as InkWall.
3. Replace the private functions in `product_on_shelves.py` with an import — *why*: one implementation, no drift.
4. Write the tests.

### `comparison/tags.py` (CREATE)
```python
"""Fact/price tag helpers shared by type hooks and rule evaluation (FEAT-624)."""

from __future__ import annotations

import re
from typing import Mapping, Optional, Sequence

from parrot_pipelines.planogram.contracts import Identification, Shape, Slot

_PRICE = re.compile(r"(\d+)[.,](\d{2})")


def tag_text(tag: Shape, readings: Mapping[str, object], reads: Mapping[str, Identification]) -> Optional[str]:
    """Return own-box OCR of a tag, falling back to shape or vision text; None when blank."""
    # FILL IN: paste the body of product_on_shelves._tag_text (line 96) unchanged — bounded by "move, not rewrite"


def slot_above(tag: Shape, slots: Sequence[Slot]) -> Optional[Slot]:
    """Return the slot whose lower area is labelled by a tag, or None."""
    # FILL IN: paste the body of product_on_shelves._slot_above (line 105) unchanged — bounded by "move, not rewrite"


def tag_price(text: Optional[str]) -> Optional[float]:
    """First ``12.99`` / ``12,99`` amount in a text, or None."""
    match = _PRICE.search(text or "")
    return float(f"{match.group(1)}.{match.group(2)}") if match else None
```

### `types/product_on_shelves.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '^from ..comparison.definition import SlotsDefinition' types/product_on_shelves.py)
# AFTER — insert below `from ..comparison.definition import SlotsDefinition` (verified: types/product_on_shelves.py:15)
from ..comparison.tags import slot_above, tag_text

# DELETE `def _tag_text(...)` (line 96) and `def _slot_above(...)` (line 105) with their bodies.
# In _corroborate_with_fact_tags (lines 211-212) replace `_tag_text(` -> `tag_text(` and `_slot_above(` -> `slot_above(`.
```

### `tests/planogram_cycle/test_fact_tag_helpers.py` (CREATE)
```python
"""FEAT-624 — moved tag helpers."""

from __future__ import annotations

import pytest

from parrot.models.detections import DetectionBox
from parrot_pipelines.planogram.comparison.tags import slot_above, tag_price, tag_text
from parrot_pipelines.planogram.contracts import OcrReading, Shape, ShapeKind, Slot


def _box(x1: int, y1: int, x2: int, y2: int) -> DetectionBox:
    return DetectionBox(x1=x1, y1=y1, x2=x2, y2=y2, confidence=1.0)


def _tag(x1: int, y1: int, x2: int, y2: int, text: str | None = None) -> Shape:
    return Shape(shape_id="t1", image_id="img0", kind=ShapeKind.FACT_TAG, box=_box(x1, y1, x2, y2), ocr_text=text)


def _slot(slot_id: str, x1: int, x2: int) -> Slot:
    return Slot(slot_id=slot_id, image_id="img0", row_index=0, slot_index=1, box=_box(x1, 100, x2, 300))


@pytest.mark.parametrize(("text", "expected"), [("$12.99", 12.99), ("12,99 EUR", 12.99), ("no price", None), (None, None)])
def test_tag_price_reads_dot_and_comma(text, expected):
    assert tag_price(text) == expected


def test_tag_text_prefers_own_box_reading():
    tag = _tag(0, 0, 10, 10, text="shape text")
    assert tag_text(tag, {"t1": OcrReading(text=" own box ")}, {}) == "own box"
    assert tag_text(tag, {}, {}) == "shape text"


def test_slot_above_picks_the_slot_over_the_tag():
    left, right = _slot("a", 0, 100), _slot("b", 100, 200)
    assert slot_above(_tag(20, 290, 80, 320), [left, right]) is left
    # FILL IN: a tag far below every slot returns None — bounded by the moved body's height window
```

### FILL IN checklist
- [ ] `tags.py::tag_text` / `slot_above` — verbatim bodies.
- [ ] `test_slot_above_picks_the_slot_over_the_tag` — the `None` case.

---

## Acceptance Criteria

- [ ] `from parrot_pipelines.planogram.comparison.tags import slot_above, tag_price, tag_text` works.
- [ ] `product_on_shelves.py` no longer defines `_tag_text` / `_slot_above`.
- [ ] Existing product-on-shelves tests pass unchanged.
- [ ] `ruff check` clean on the touched files.

---

## Validation Commands

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_fact_tag_helpers.py -q`
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_pos_migrated_compare.py -q`
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_identify.py -q`

---

## Test Specification

See the CREATE block: price parsing (dot, comma, none), text fallback order, slot selection.

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug planogram-fact-tag-rule --feature-id FEAT-624`); run tests with `PYTHONPATH=packages/ai-parrot-pipelines/src`.
2. Verify the Codebase Contract before editing; mark `in-progress`; implement; run the Validation Commands.
3. Commit only the listed files; close with `scripts/sdd/close_task.sh TASK-4004 planogram-fact-tag-rule verified`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
