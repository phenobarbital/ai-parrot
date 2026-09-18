# TASK-3440: Per-image row-to-shelf registration

**Feature**: FEAT-574 — New Planogram Compliance Pipeline
**Spec**: `sdd/specs/new-planogram-pipeline.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3435
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 13** (first half). Stage 3 (*compare*) of the new cycle starts by
**registering** what one photo shows against the slots definition: each observed
row of slots is aligned to one definition shelf, and each identified slot to one
expected facing. Registration is deterministic, per image, and conservative:
an ambiguous or unsupported alignment produces **no assignments at all** — the
facings then stay `not_assessed` / `not_visible` in the scoring task. Header /
backlit / poster **zones are detected apart and take no part** in row→shelf
alignment; product rows register in **strictly increasing** shelf order
(brainstorm decision, spec §8).

Algorithmic reference (read it, never import it):
`examples/planogram/plancheck/registration.py` — `pair_score` :55, `align_row` :93
(semi-global, gap-tolerant NW-style DP), `register_image` :197 (order-preserving
shelf combinations, runner-up margin), `_grade` :188.

---

## Scope

- Implement `ImageRegistration` (Pydantic v2) and `register_image(...)` with the
  exact signature of the spec skeleton.
- Group the image's slots by `Slot.row_index`; align every row against every
  definition shelf with a gap-tolerant DP (`_align_row`); choose the best
  **strictly increasing** row→shelf combination; keep the runner-up total to
  compute a margin.
- Pair scoring uses only evidence carried by the `Identification` of the slot
  (product id, brand, descriptor family) versus the `FacingDefinition` — a
  *candidate* identity may raise a pair score but **can never force** an
  assignment: ties and low margins yield `ambiguous=True` and **empty**
  `row_to_shelf` / `assignments`.
- Join rule between identifications and slots (fixed here, reused by the scoring
  task): an `Identification` belongs to a `Slot` when
  `identification.shape_id in {slot.anchor_shape_id, slot.slot_id}`.
  `assignments` maps **`Identification.shape_id` → `facing_id`**.
- Only slots of the given `image_id` are considered; identifications flagged
  `uncertain=True` still occupy their slot position (they score neutral).
- Write offline unit tests (synthetic definition + synthetic slots, no images).

**NOT in scope**: per-facing decision, credits, multi-photo merging, shelf scores,
projection to `ComplianceResult` (next task of Module 13); fixture membership
(callers pass only on-fixture slots); zones; any LLM call; any I/O.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/registration.py` | CREATE | `ImageRegistration`, `register_image`, private DP helpers |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_registration.py` | CREATE | Offline unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from pydantic import BaseModel, Field                     # pydantic v2 (existing dependency)
from parrot.models.detections import DetectionBox         # verified: packages/ai-parrot/src/parrot/models/detections.py:37
# Created by dependencies (exist once TASK-3435 / TASK-3421 are merged — re-verify before coding):
from parrot_pipelines.planogram.contracts import Identification, Slot                      # TASK-3421
from parrot_pipelines.planogram.comparison.definition import (                             # TASK-3435
    FacingDefinition, ShelfDefinition, SlotsDefinition,
)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/models/detections.py:37-60
class DetectionBox(BaseModel):
    x1: int; y1: int; x2: int; y2: int       # :39-42
    confidence: float                         # :43 (0..1, coerced)

# ---- Created by TASK-3421 (dependency) — planogram/contracts.py, copied from spec §2 Data Models ----
class Slot(BaseModel):             # slot_id, image_id, row_index, slot_index, box: DetectionBox, anchor_shape_id, inferred
class Identification(BaseModel):   # shape_id, image_id, product, brand, text, descriptors, raw_confidence,
                                   # evidence, source, uncertain

# ---- Created by TASK-3435 (dependency) — planogram/comparison/definition.py, copied from spec §2 ----
class SlotsDefinition(BaseModel):  # version, meta, shelves: List[ShelfDefinition], zones: List[ZoneDefinition]
class ShelfDefinition(BaseModel):  # shelf_id, shelf_number, level, facings: List[FacingDefinition]
class FacingDefinition(BaseModel): # facing_id, shelf_id, slot, product, brand, facings, descriptors: Descriptors
class Descriptors(BaseModel):      # display_name, family, xl, colors, pack, identifiers, aliases, price (all optional)
```
Field **types** of the dependency models are fixed by their own tasks — open
`contracts.py` and `comparison/definition.py` and read them before coding.

Reference only (NEVER import): `examples/planogram/plancheck/registration.py`
— constants :23-38 (`SCORE_SAME_SKU = 4.0`, `SCORE_CANDIDATE = 3.0`,
`SCORE_BRAND_FAMILY = 2.0`, `SCORE_BRAND = 1.0`, `SCORE_NEUTRAL = 0.0`,
`SCORE_OTHER_BRAND = -2.0`, `GAP_INTERIOR = -1.5`, `GAP_END_PLANOGRAM = 0.0`,
`GAP_END_OBSERVED = -0.5`, `PRIOR_CONSECUTIVE = 1.0`, `PRIOR_FULL_HEIGHT = 2.0`,
`MARGIN_LOW = 1.0`), `align_row` :93, `register_image` :197.

### Does NOT Exist
- ~~`parrot_pipelines.planogram.comparison.registration`~~ — this task creates it.
- ~~`plancheck` as an importable package~~ — bare example directory; re-implement, never import.
- ~~`Slot.row` / `Slot.index` / `Slot.shelf`~~ — the contract fields are `row_index` and `slot_index`; there is no shelf on a `Slot` (that is what registration computes).
- ~~`Identification.slot_id` / `Identification.facing_id` / `Identification.resolved_sku`~~ — not contract fields; join through `shape_id` as described in Scope.
- ~~`SlotsDefinition.shelf(n)` / `.shelf_count`~~ — not in the spec skeleton; iterate `definition.shelves` (verify before using any helper).
- ~~Non-monotone row→shelf registration~~ — out of scope by decision; only strictly increasing combinations.
- ~~A catalog object~~ — descriptors live on `FacingDefinition.descriptors`; there is no `Catalog`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/registration.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_registration.py",
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

### Pattern to Follow
Pure functions, module-level `logger = logging.getLogger(__name__)`, no I/O, no
LLM, no `parrot` client import — same input ⇒ identical output (this is what makes
stage 3 auditable). Mirror the structure of the reference `align_row` /
`register_image`, written against the package contracts.

### Key Constraints
- Synchronous and CPU-light: ≤ 6 shelves × ≤ 6 rows ⇒ `itertools.combinations`
  is fine. Do not add an executor here.
- **Ambiguity rule** (spec Module 13 skeleton): when the best total does not beat
  the runner-up by at least `MARGIN_LOW`, or the best combination has **zero
  anchors** (no pair reached the same-product score), return
  `ambiguous=True` with `row_to_shelf={}` and `assignments={}`.
- More observed rows than definition shelves ⇒ no strictly increasing
  combination exists ⇒ ambiguous (do not drop rows silently).
- Partial view is normal: 3 rows against 6 shelves must register when evidence
  supports it; uncovered shelves simply get no assignments.
- Google-style docstrings, strict type hints, 120 columns, no `print`.
- Run tests inside the worktree with
  `PYTHONPATH=packages/ai-parrot-pipelines/src:packages/ai-parrot/src`.

### References in Codebase
- `examples/planogram/plancheck/registration.py` — algorithm to re-implement
- `examples/planogram/tests/` — style of offline synthetic tests

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Never change a
> signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Open `planogram/contracts.py` and `planogram/comparison/definition.py` and confirm the field names listed in the Codebase Contract — *why*: they are created by dependency tasks; this blueprint copied them from the spec, not from code.
2. Write `registration.py` from the block below — *why*: signatures are fixed by the spec skeleton and consumed verbatim by the scoring task.
3. Implement `_pair_score`, then `_align_row`, then the combination search — *why*: each layer is unit-testable on its own and the tests below target them in that order.
4. Write the tests; make them pass; run `ruff check` on the new module — *why*: TID251 import bans are a merge gate.

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/registration.py` (CREATE)
```python
"""Deterministic per-image registration of observed slot rows against the slots definition (FEAT-574).

Pure functions: no I/O, no LLM. Same input, identical output.
"""
from __future__ import annotations

import logging
from itertools import combinations
from typing import Dict, List, Optional, Sequence, Tuple

from pydantic import BaseModel, Field

from parrot_pipelines.planogram.contracts import Identification, Slot
from parrot_pipelines.planogram.comparison.definition import FacingDefinition, ShelfDefinition, SlotsDefinition

logger = logging.getLogger(__name__)

SCORE_SAME_PRODUCT = 4.0
SCORE_BRAND_FAMILY = 2.0
SCORE_BRAND = 1.0
SCORE_NEUTRAL = 0.0
SCORE_OTHER_BRAND = -2.0
GAP_INTERIOR = -1.5
GAP_END_DEFINITION = 0.0
GAP_END_OBSERVED = -0.5
PRIOR_CONSECUTIVE = 1.0
PRIOR_FULL_HEIGHT = 2.0
MARGIN_LOW = 1.0


class ImageRegistration(BaseModel):
    """Result of registering ONE image against the slots definition."""

    image_id: str
    row_to_shelf: Dict[int, str] = Field(default_factory=dict, description="row_index -> shelf_id")
    assignments: Dict[str, str] = Field(default_factory=dict, description="Identification.shape_id -> facing_id")
    ambiguous: bool = False


def _norm(text: Optional[str]) -> Optional[str]:
    """Casefold/strip a token; None stays None."""
    return text.casefold().strip() if text else None


def _identification_for(slot: Slot, by_shape: Dict[str, Identification]) -> Optional[Identification]:
    """Join rule: identification.shape_id in {slot.anchor_shape_id, slot.slot_id}."""
    for key in (slot.anchor_shape_id, slot.slot_id):
        if key and key in by_shape:
            return by_shape[key]
    return None
```

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/registration.py` (CREATE) — continued, part 2/2 (same file: append directly below the previous block)
```python
def _pair_score(identification: Optional[Identification], facing: FacingDefinition) -> float:
    """Score one observed slot against one expected facing."""
    if identification is None or identification.uncertain:
        return SCORE_NEUTRAL
    # FILL IN: same product id (normalised) -> SCORE_SAME_PRODUCT; same brand + same descriptors.family ->
    #   SCORE_BRAND_FAMILY; same brand -> SCORE_BRAND; both brands known and different -> SCORE_OTHER_BRAND;
    #   otherwise SCORE_NEUTRAL — bounded by: only evidence carried by the Identification, never the
    #   expected SKU itself (spec §2 "Observation validity").
    raise NotImplementedError


def _align_row(row_slots: Sequence[Slot], facings: Sequence[FacingDefinition],
               by_shape: Dict[str, Identification]) -> Tuple[float, Dict[str, str], int]:
    """Semi-global, gap-tolerant alignment of one row against one shelf.

    Returns:
        (score, {Identification.shape_id: facing_id}, anchors) — anchors counts SCORE_SAME_PRODUCT pairs.
        Slots without an identification never appear in the mapping.
    """
    if not row_slots or not facings:
        return 0.0, {}, 0
    ordered = sorted(row_slots, key=lambda s: s.slot_index)
    # FILL IN: NW-style DP over (len(ordered)+1) x (len(facings)+1) with match / skip-facing / skip-slot moves,
    #   end gaps cheaper than interior gaps (constants above), then traceback — bounded by: deterministic
    #   tie-breaking (prefer match, then skip-facing, then skip-slot); reference plancheck/registration.py:93.
    raise NotImplementedError


def register_image(image_id: str, slots: Sequence[Slot], identifications: Sequence[Identification],
                   definition: SlotsDefinition) -> ImageRegistration:
    """Register every slot row of one image to a shelf and every identified slot to a facing.

    Ambiguous or unsupported alignment => ``ambiguous=True`` and NO assignments (facings stay
    not_assessed / not_visible). Candidate identity can never force a facing assignment.

    Args:
        image_id: Image whose slots/identifications are considered; others are ignored.
        slots: On-fixture slots (membership already applied by the caller).
        identifications: Identifications of any image; filtered by ``image_id``.
        definition: Validated slots definition.

    Returns:
        The best strictly-increasing row->shelf assignment, or an ambiguous empty registration.
    """
    rows: Dict[int, List[Slot]] = {}
    for slot in slots:
        if slot.image_id == image_id:
            rows.setdefault(slot.row_index, []).append(slot)
    by_shape = {i.shape_id: i for i in identifications if i.image_id == image_id}
    shelves: List[ShelfDefinition] = [s for s in definition.shelves if s.facings]
    row_ids = sorted(rows)
    if not row_ids or not shelves or len(row_ids) > len(shelves):
        logger.debug("register_image(%s): nothing to register or more rows than shelves", image_id)
        return ImageRegistration(image_id=image_id, ambiguous=bool(row_ids))
    # FILL IN: cache _align_row per (row, shelf index); iterate combinations(range(len(shelves)), len(row_ids))
    #   (strictly increasing by construction); add PRIOR_CONSECUTIVE / PRIOR_FULL_HEIGHT; track best and
    #   runner-up totals — bounded by: reference plancheck/registration.py:197-263.
    # FILL IN: ambiguity gate — margin < MARGIN_LOW (when a runner-up exists) OR total anchors == 0
    #   => return ImageRegistration(image_id=image_id, ambiguous=True) with EMPTY mappings — bounded by AC-3/AC-4.
    raise NotImplementedError
```
**Why this shape**: `ImageRegistration` fields and the `register_image` signature are the spec Module 13
skeleton — the scoring task consumes them verbatim. `assignments` is keyed by `Identification.shape_id`
because identifications, not slots, carry identity evidence into scoring. The ambiguity gate returns an
empty registration instead of a low-grade one because the spec forbids a candidate identity from forcing
an assignment; "not assessed" is an honest result, a guessed shelf is not.

### `packages/ai-parrot-pipelines/tests/planogram_cycle/test_registration.py` (CREATE)
```python
"""Offline tests for per-image registration (FEAT-574, Module 13)."""
from __future__ import annotations

import pytest

from parrot.models.detections import DetectionBox
from parrot_pipelines.planogram.contracts import Identification, Slot
from parrot_pipelines.planogram.comparison.definition import load_slots_definition
from parrot_pipelines.planogram.comparison.registration import ImageRegistration, register_image


def _definition(shelves: int = 6, per_shelf: int = 4):
    """Synthetic definition: product ids 'P<shelf>-<slot>', brand alternates per shelf."""
    # FILL IN: build the dict accepted by load_slots_definition (read its docstring) — bounded by:
    #   stable ids, slot sequence 1..n, every facing described.
    raise NotImplementedError


def _slot(image_id: str, row: int, idx: int) -> Slot:
    # FILL IN: Slot with slot_id f"{image_id}:r{row}:s{idx}", anchor_shape_id f"{image_id}:t{row}:{idx}",
    #   a 50x50 DetectionBox placed by (row, idx) — bounded by the Slot contract fields.
    raise NotImplementedError


def _ident(slot: Slot, product: str | None, brand: str | None = None, uncertain: bool = False) -> Identification:
    # FILL IN: Identification(shape_id=slot.anchor_shape_id, image_id=slot.image_id, ...) — bounded by contract.
    raise NotImplementedError


def test_full_view_registers_rows_in_increasing_shelf_order(): ...
def test_registration_partial_view_not_visible(): ...           # spec §4: 3 of 6 shelves visible
def test_registration_ambiguous_stays_unassessed(): ...          # spec §4: tie => no assignments
def test_zero_anchor_alignment_is_ambiguous(): ...
def test_more_rows_than_shelves_is_ambiguous(): ...
def test_other_image_inputs_are_ignored(): ...
def test_gap_in_row_keeps_neighbours_aligned(): ...
def test_register_image_is_deterministic(): ...
```
**Why**: the two tests named in spec §4 (`test_registration_partial_view_not_visible`,
`test_registration_ambiguous_stays_unassessed`) must exist under exactly those names; the others pin
the ambiguity gate and the join rule.

### FILL IN checklist
- [ ] `registration.py::_pair_score` — score table; bounded by "evidence on the Identification only"
- [ ] `registration.py::_align_row` — DP + traceback; bounded by deterministic tie-breaking, reference :93
- [ ] `registration.py::register_image` — combination search + priors; bounded by reference :197-263
- [ ] `registration.py::register_image` — ambiguity gate; bounded by AC-3 / AC-4
- [ ] `test_registration.py::_definition`, `_slot`, `_ident` — synthetic builders; bounded by dependency contracts
- [ ] `test_registration.py` — eight test bodies

---

## Acceptance Criteria

- [ ] AC-1: `register_image` and `ImageRegistration` match the spec Module 13 skeleton exactly (names, parameters, field names).
- [ ] AC-2: A full view registers rows to shelves in strictly increasing order; a partial view (3 of 6 shelves) registers only the visible shelves and leaves the rest without assignments.
- [ ] AC-3: A tie between two shelf combinations (margin < `MARGIN_LOW`) returns `ambiguous=True` with empty `row_to_shelf` and `assignments`.
- [ ] AC-4: An alignment with zero same-product anchors returns `ambiguous=True` with empty mappings — a candidate identity never forces an assignment.
- [ ] AC-5: Slots / identifications of other images are ignored; output is deterministic across repeated calls.
- [ ] AC-6: No import of `plancheck`, no I/O, no LLM call in the module.
- [ ] All tests pass: `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_registration.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/registration.py`

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_registration.py -q`

---

## Test Specification

```python
# packages/ai-parrot-pipelines/tests/planogram_cycle/test_registration.py
def test_registration_partial_view_not_visible():
    """Rows identified as shelves 2-4 of a 6-shelf definition register to exactly those shelves."""
    definition = _definition(shelves=6, per_shelf=4)
    slots, idents = [], []
    for row, shelf in enumerate((2, 3, 4)):
        for idx in range(1, 5):
            s = _slot("img0", row, idx)
            slots.append(s)
            idents.append(_ident(s, product=f"P{shelf}-{idx}"))
    reg = register_image("img0", slots, idents, definition)
    assert reg.ambiguous is False
    assert set(reg.row_to_shelf.values()) == {definition.shelves[i].shelf_id for i in (1, 2, 3)}
    assigned_shelves = {fid.split(":")[0] for fid in reg.assignments.values()}  # adapt to the real facing_id format
    assert len(reg.assignments) == 12


def test_registration_ambiguous_stays_unassessed():
    """Two shelves with identical products => tie => no assignments at all."""
    ...
    assert reg.ambiguous is True
    assert reg.row_to_shelf == {} and reg.assignments == {}
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-3440-registration.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (FEAT-574 orchestrator)
**Date**: 2026-09-19

Implemented in fallback sequential mode (parrot-sdd-coder server unresponsive).
comparison/registration.py: ImageRegistration + register_image (spec skeleton). _pair_score uses only Identification evidence (same product +4, brand+family +2, brand +1, other brand -2, else 0; uncertain/None neutral); _align_row = port of the reference semi-global DP (end gaps cheaper, deterministic tie-break match > skip-facing > skip-slot, anchors = +4 matches, mapping keyed by Identification.shape_id, slots without identification never mapped); register_image = cached alignments over strictly increasing combinations with consecutive/full-height priors, ambiguity gate (margin < MARGIN_LOW or zero anchors, and more rows than shelves) => ambiguous with empty mappings. Join rule identification.shape_id in {anchor_shape_id, slot_id}.
Tests: test_registration.py 9 passed (incl. spec names test_registration_partial_view_not_visible / test_registration_ambiguous_stays_unassessed). ruff clean.

Seat: orchestrator (fallback) · Backend: native · Model: claude-opus-5 · Attempts: 1
