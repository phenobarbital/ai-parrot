# TASK-3437: Evidence-based fixture membership (on/off/uncertain)

**Feature**: FEAT-574 — New Planogram Compliance Pipeline
**Spec**: `sdd/specs/new-planogram-pipeline.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3418, TASK-3421
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 11**, goal **G13** and §2 *Fixture membership*. The old pipeline
scoped everything to an LLM-found ROI — a single point of failure. The new cycle
proposes shapes over the **whole image**, which also catches neighbouring
fixtures (the reference photo has printers with price tags on the left aisle and
unrelated products on the right). Something must decide which observations
belong to the fixture under assessment **without re-introducing a hard ROI gate**.

This task is that step: a pure, deterministic function that labels every shape
`on_fixture`, `off_fixture` or `uncertain` from *spatial evidence only* — fixture
anchors (header/backlit, box stack), shelf/row continuity and spatial
relationships — and records the evidence. Two rules are non-negotiable:

1. **Expected-SKU agreement never establishes membership** and never selects
   among neighbouring fixtures. The function does not even receive the planogram
   definition.
2. **Anchors are evidence, not gates.** Missing anchors never stop perception:
   shapes become `uncertain`, identification continues, and the affected facings
   are later reported as unassessed.

Only `on_fixture` shapes reach registration and scoring; everything else stays in
the audit output. `usable_shapes()` is the count the LLM-detector fallback
threshold is compared against — so off-fixture distractors can never suppress it.

---

## Scope

- `assign_membership(shapes, zones, image_size, *, llm_hints=None)` — returns
  **copies** with `membership` and `membership_evidence` set.
- `usable_shapes(shapes)` — the `on_fixture` subset.
- Offline tests, including adjacent fixtures, missing anchors, partial view and
  ambiguous cases.

**NOT in scope**: proposing shapes, grouping rows or building slots (inputs
arrive with `row_index` already set when structure exists); calling an LLM (hints
arrive as a plain dict); registration/scoring; the fallback decision itself;
editing `perception/__init__.py` (single owner — import by full module path).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/membership.py` | CREATE | `assign_membership`, `usable_shapes` + private evidence helpers |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_membership.py` | CREATE | Offline unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references. **DO NOT** invent imports, attributes or methods not listed here.

### Verified Imports
```python
from statistics import median
from typing import Dict, List, Optional, Sequence, Tuple
from parrot.models.detections import DetectionBox       # verified: packages/ai-parrot/src/parrot/models/detections.py:37
# Created by TASK-3421 (dependency):
from parrot_pipelines.planogram.contracts import FixtureMembership, Shape, ShapeKind
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/models/detections.py:37-60
class DetectionBox(BaseModel):
    x1: int; y1: int; x2: int; y2: int          # :39-42   source-image pixels
    confidence: float                            # :43     REQUIRED, 0..1

# Created by TASK-3421 (dependency) — planogram/contracts.py  (spec §2 Data Models)
class ShapeKind(str, Enum):         PRICE_TAG, PRODUCT, BOX, FACT_TAG, ZONE, UNKNOWN
class FixtureMembership(str, Enum): ON_FIXTURE, OFF_FIXTURE, UNCERTAIN
class Shape(BaseModel):
    shape_id; image_id; kind; box: DetectionBox; profile; row_index; slot_index
    ocr_text; ocr_confidence; source; membership; membership_evidence
    # Field TYPES/defaults are fixed by TASK-3421 — open contracts.py and read them first
    # (in particular whether membership_evidence is List[str] and what membership defaults to).

# Created by TASK-3418 (dependency): the `perception` package directory this module is added to.
# Pydantic v2: `shape.model_copy(update={...})` returns a modified copy (never mutate the input).
```

### Does NOT Exist
- ~~a planogram / slots definition parameter on `assign_membership`~~ — deliberately absent: expected SKUs are **not** an input (spec Module 11). Do not add one.
- ~~an ROI / endcap bounding box input~~ — the ROI gate is what this feature removes; zones are *evidence*.
- ~~`Shape.on_fixture` / `Shape.is_usable`~~ — no such attributes; use `membership == FixtureMembership.ON_FIXTURE`.
- ~~LLM access from this module~~ — `llm_hints` is a plain `Dict[shape_id, FixtureMembership]` produced elsewhere.
- ~~any existing fixture-scoping helper to reuse~~ — `compute_roi` / `_find_poster` are the legacy LLM ROI path, not reusable here.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/membership.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_membership.py",
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

### Evidence policy (decided here; the spike validates it later)
Evidence sources, each producing an `(on | off | none, reason)` vote per shape:

| Source | Vote |
|---|---|
| **Zone anchors** — `zones` (kind `ZONE`: header/backlit/poster, box stack). Their union gives a *fixture column* `[x_lo, x_hi]`, expanded by `_COLUMN_MARGIN` of its width. | centre inside the column ⇒ **on** (`"anchor_column"`); centre outside the column by more than `_OFF_MARGIN` of the column width ⇒ **off** (`"outside_anchor_column"`); in between ⇒ none |
| **Row block** — shapes with a `row_index`. A *coherent block* = ≥ 2 rows whose x-extents overlap by ≥ 50 %, or a single row spanning ≥ 50 % of the image width. | member of the block and contiguous with its row neighbours (gap ≤ `_MAX_GAP_PITCHES` × median pitch) ⇒ **on** (`"row_block"`); same row but separated by a larger gap ⇒ **off** (`"row_gap"`) |
| **Containment** — a shape whose centre lies inside an `on` shape's box expanded by 10 % (tag on a product, fact tag on a box). | **on** (`"contained_in:<shape_id>"`) |

Combination, in order:
1. any **on** and no **off** ⇒ `ON_FIXTURE`; any **off** and no **on** ⇒ `OFF_FIXTURE`.
2. both **on** and **off** ⇒ `UNCERTAIN` (evidence lists both — never pick the convenient one).
3. no vote at all (no anchors, no row structure) ⇒ `UNCERTAIN` with `"no_anchor_evidence"`.
4. `llm_hints`: recorded as `"llm_hint:<value>"` for every hinted shape. A hint
   may only **resolve a shape that is `UNCERTAIN` after steps 1-3**; it never
   flips a deterministic `ON`/`OFF`. When it resolves, evidence also gets
   `"resolved_by:llm_hint"` so the provenance is auditable.

### Key Constraints
- **Pure and deterministic**: no I/O, no randomness, no logging side effects
  required for correctness; same input ⇒ same output. Module-level and picklable.
- **Never mutate inputs**: return `model_copy(update=...)` copies, same order and
  same length as `shapes`. `zones` are not returned.
- **No planogram knowledge**: the signature is fixed by the spec; do not add
  parameters carrying expected products.
- Empty `shapes` ⇒ `[]`. Shapes with a degenerate box ⇒ `UNCERTAIN` (`"degenerate_box"`).
- Thresholds are module constants (`_COLUMN_MARGIN = 0.10`, `_OFF_MARGIN = 0.25`,
  `_MAX_GAP_PITCHES = 1.75`) — provisional, to be revisited with the spike report.
- Google-style docstrings, full type hints, `ruff check` clean.
- Inside a worktree: `PYTHONPATH=packages/ai-parrot-pipelines/src:packages/ai-parrot/src`.

### References in Codebase
- Spec §2 "Fixture membership and observation validation" (carried from the brainstorm) — the policy source
- Spec §6 "Reference photo for the spike" — the adjacent-fixture scenario the tests imitate

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write the block nearly verbatim, then
> complete every `# FILL IN:`. Never change a signature, function name, or path fixed here.

### Steps (in order)
1. Open `planogram/contracts.py` (TASK-3421) and read `Shape`, `ShapeKind`,
   `FixtureMembership` — *why*: you construct/copy `Shape` by keyword; field types
   are owned by that task.
2. Write the three vote helpers, then `_combine`, then the two public functions —
   *why*: each evidence source is testable alone and the policy table maps 1:1 to helpers.
3. Write the tests from the scaffold; build shapes with a small local factory.
4. Run with the `PYTHONPATH` prefix; `ruff check` the module.

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/membership.py` (CREATE)
```python
"""Evidence-based fixture membership: on / off / uncertain (FEAT-574). Pure and deterministic.

Expected-SKU agreement is deliberately NOT an input: membership comes from spatial evidence only.
"""
from __future__ import annotations

from statistics import median
from typing import Dict, List, Optional, Sequence, Tuple

from ..contracts import FixtureMembership, Shape

_COLUMN_MARGIN = 0.10     # anchor column is widened by this fraction of its width (each side)
_OFF_MARGIN = 0.25        # beyond this fraction of the column width outside it => off
_MAX_GAP_PITCHES = 1.75   # larger x-gap between row neighbours breaks continuity
_Vote = Tuple[Optional[bool], str]   # (True=on | False=off | None=no vote, reason)


def _centre(shape: Shape) -> Tuple[float, float]:
    """Box centre in source pixels."""
    box = shape.box
    return (box.x1 + box.x2) / 2.0, (box.y1 + box.y2) / 2.0


def _anchor_votes(shapes: Sequence[Shape], zones: Sequence[Shape]) -> Dict[str, _Vote]:
    """Votes from the fixture column spanned by zone anchors. {} when there are no zones."""
    # FILL IN — bounded by: policy table row "Zone anchors"; zones with degenerate boxes are ignored.
    raise NotImplementedError


def _row_block_votes(shapes: Sequence[Shape], image_size: Tuple[int, int]) -> Dict[str, _Vote]:
    """Votes from a coherent block of rows (shapes with row_index). {} when no coherent block exists."""
    # FILL IN — bounded by: policy table row "Row block"; pitch = median centre distance of row neighbours.
    raise NotImplementedError


def _containment_votes(shapes: Sequence[Shape], on_ids: Sequence[str]) -> Dict[str, _Vote]:
    """'on' votes for shapes whose centre lies inside an already-on shape expanded by 10 %."""
    # FILL IN — bounded by: never votes for the container itself; one pass only (no transitive closure).
    raise NotImplementedError


def _combine(votes: Sequence[_Vote]) -> Tuple[FixtureMembership, List[str]]:
    """Apply combination rules 1-3 of the task's evidence policy."""
    # FILL IN — bounded by: on+off => UNCERTAIN with both reasons; no votes => UNCERTAIN + "no_anchor_evidence".
    raise NotImplementedError


def assign_membership(
    shapes: Sequence[Shape],
    zones: Sequence[Shape],
    image_size: Tuple[int, int],
    *,
    llm_hints: Optional[Dict[str, FixtureMembership]] = None,
) -> List[Shape]:
    """Label every shape on_fixture / off_fixture / uncertain from spatial evidence.

    Args:
        shapes: Observations of ONE image (row_index set when row structure exists).
        zones: Zone anchors of the same image (header/backlit/poster, box stack). May be empty —
            anchors are evidence, not gates.
        image_size: ``(width, height)`` of the source image.
        llm_hints: Optional ``shape_id -> membership`` suggestions. Recorded as evidence; may only
            resolve shapes that are still uncertain, never flip a deterministic decision.

    Returns:
        Copies of ``shapes`` (same order) with ``membership`` and ``membership_evidence`` set.
        Pure and deterministic; inputs are never mutated.
    """
    # FILL IN: anchor votes + row-block votes -> provisional on set -> containment votes -> _combine
    #          -> apply llm_hints (rule 4) -> model_copy(update=...) — bounded by AC-1..AC-8.
    raise NotImplementedError


def usable_shapes(shapes: Sequence[Shape]) -> List[Shape]:
    """on_fixture only — the count the fallback threshold is compared against.

    Distractor (off-fixture or uncertain) counts can never suppress the fallback.
    """
    return [s for s in shapes if s.membership == FixtureMembership.ON_FIXTURE]
```
**Why this shape**: the two public signatures are the spec skeleton verbatim —
note there is **no** definition/planogram argument, which makes rule 1
("expected SKUs never establish membership") structurally impossible to break.
One helper per evidence source keeps the policy auditable: every reason string
written to `membership_evidence` names the helper that produced it.
`usable_shapes` is complete as written; do not add `uncertain` shapes to it.

### `packages/ai-parrot-pipelines/tests/planogram_cycle/test_membership.py` (CREATE)
Write the **Test Specification** scaffold to this path and complete the bodies.

### FILL IN checklist
- [ ] `membership.py::_anchor_votes` — fixture column from zones, margins
- [ ] `membership.py::_row_block_votes` — coherent block detection, gap rule
- [ ] `membership.py::_containment_votes`
- [ ] `membership.py::_combine` — rules 1-3
- [ ] `membership.py::assign_membership` — orchestration + hint rule 4 + copies
- [ ] `test_membership.py` — every body

---

## Acceptance Criteria

- [ ] AC-1: header zone + 3 shapes under it + 2 shapes far left (adjacent fixture) ⇒ the 3 are `ON_FIXTURE` (`"anchor_column"`), the 2 are `OFF_FIXTURE` (`"outside_anchor_column"`).
- [ ] AC-2: no zones and no `row_index` on any shape ⇒ every shape `UNCERTAIN` with `"no_anchor_evidence"`; the call does not raise (perception continues).
- [ ] AC-3: no zones, but 3 rows × 8 tags forming a coherent block ⇒ all `ON_FIXTURE` (`"row_block"`); 3 tags of the same rows separated by a gap > 1.75 pitches ⇒ `OFF_FIXTURE` (`"row_gap"`).
- [ ] AC-4: a shape with conflicting votes (inside the anchor column **and** across a row gap) ⇒ `UNCERTAIN`, evidence lists both reasons.
- [ ] AC-5: `llm_hints` resolves an `UNCERTAIN` shape (evidence contains `"llm_hint:on_fixture"` and `"resolved_by:llm_hint"`), but does **not** flip a deterministic `OFF_FIXTURE` shape (hint still recorded).
- [ ] AC-6: inputs are not mutated; output has the same length and order as `shapes`; `[]` in ⇒ `[]` out.
- [ ] AC-7: `inspect.signature(assign_membership)` has exactly the parameters `shapes, zones, image_size, llm_hints` — nothing that could carry expected products.
- [ ] AC-8: `usable_shapes` returns only `ON_FIXTURE` shapes; adding any number of `OFF_FIXTURE`/`UNCERTAIN` shapes does not change its length.
- [ ] AC-9: partial view (header zone cut off at the top edge, shapes below) still yields `ON_FIXTURE` for shapes inside the visible column.
- [ ] No linting errors: `ruff check packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/membership.py`
- [ ] All tests pass (see Validation Commands).

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_membership.py -q`

---

## Test Specification

```python
# packages/ai-parrot-pipelines/tests/planogram_cycle/test_membership.py
"""Offline tests for fixture membership (pure geometry — no images needed)."""
import inspect

import pytest

from parrot.models.detections import DetectionBox
from parrot_pipelines.planogram.contracts import FixtureMembership, Shape, ShapeKind
from parrot_pipelines.planogram.perception.membership import assign_membership, usable_shapes

SIZE = (2000, 1500)


def _shape(shape_id: str, x: int, y: int, w: int = 120, h: int = 120, *, kind=ShapeKind.PRODUCT,
           row_index=None) -> Shape:
    """Local factory. FILL IN any other REQUIRED Shape field after reading contracts.py."""
    return Shape(shape_id=shape_id, image_id="img0", kind=kind, profile="test",
                 box=DetectionBox(x1=x, y1=y, x2=x + w, y2=y + h, confidence=1.0), row_index=row_index)


def _by_id(shapes):
    return {s.shape_id: s for s in shapes}


def test_anchor_column_separates_adjacent_fixture(): ...                       # AC-1
def test_membership_ignores_expected_sku_and_handles_missing_anchors():        # AC-2 + AC-7 (spec §4 name)
    assert list(inspect.signature(assign_membership).parameters) == ["shapes", "zones", "image_size", "llm_hints"]
    ...
def test_row_block_is_evidence_without_zones(): ...                            # AC-3
def test_conflicting_votes_stay_uncertain_with_both_reasons(): ...             # AC-4
def test_llm_hint_resolves_uncertain_but_never_flips(): ...                    # AC-5
def test_inputs_not_mutated_and_order_preserved(): ...                         # AC-6
def test_usable_shapes_counts_only_on_fixture(): ...                           # AC-8
def test_partial_view_header_cut_off(): ...                                    # AC-9
```

---

## Agent Instructions

1. **Read the spec** (§2 *Fixture membership…*, §3 Module 11, goal G13)
2. **Check dependencies** — TASK-3418 and TASK-3421 are merged
3. **Verify the Codebase Contract** — read `Shape`, `ShapeKind`, `FixtureMembership`
   in `planogram/contracts.py`; adapt the test factory to any extra required field;
   update the contract FIRST if names differ
4. **Implement** from the blueprint; complete every `# FILL IN:`; never change a fixed signature
5. **Verify** all acceptance criteria
6. **Commit code only** — never touch `sdd/`, never edit `perception/__init__.py`
7. **Fill in the Completion Note** — list any threshold you had to change and why

---

## Completion Note

**Completed by**: sdd-worker (FEAT-574 orchestrator)
**Date**: 2026-09-19

Implemented in fallback sequential mode (parrot-sdd-coder server unresponsive).
perception/membership.py: assign_membership(shapes, zones, image_size, *, llm_hints) — anchor-column votes (union of zone x-extents, +10% on / beyond 25% off), row-block votes (rows split into clusters at gaps > 1.75 x the global median neighbour pitch; main run per row; block = main runs overlapping the largest by >= 50%; coherent with >= 2 rows or one row >= 50% of the image width; members 'row_block', other clusters of block rows 'row_gap'), one-pass containment votes ('contained_in:<id>', container expanded 10%), combination rules 1-3, llm hints recorded always and resolving only UNCERTAIN ('resolved_by:llm_hint'); degenerate boxes -> UNCERTAIN 'degenerate_box'; copies via model_copy, same order. usable_shapes as specified.
Tests: test_membership.py 9 passed (AC-1..AC-9 + containment); ruff clean.

Seat: orchestrator (fallback) · Backend: native · Model: claude-opus-5 · Attempts: 1

Post-completion review fix (found while integrating TASK-3444): a single missing tag inside the row block split the row and marked one side off-fixture (row_gap). Fixed in 4f7b3a13523ee89229db6cc8e5b33ee2f49ea35e — clusters whose centre lies inside the block x-span vote row_block; regression test test_hole_inside_the_block_is_not_a_row_gap. Defect was in the orchestrator fallback delivery (no coder attempt to attribute feedback to).
