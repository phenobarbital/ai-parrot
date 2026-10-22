# TASK-4177: Row-block span over multi-bay fixtures (membership)

**Feature**: FEAT-646 — Ink-wall slot recovery and completeness policy
**Spec**: `sdd/specs/ink-wall-registration-and-completeness.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §1 defect 3, §2 Part C, §3 Module 3. The BBY560 ink wall has two bays separated by a gap wider than
`_MAX_GAP_PITCHES` (1.75) pitches. In `_row_block_votes()` the fixture span is the union of each block row's
*main run* only; rows 2 and 4 have their main run in the right bay, so the span's left edge lands at x≈469
and the lone bottom-row tag over an empty facing (x≈205–313) votes `row_gap` → `OFF_FIXTURE`, and the empty
facing is never reported. This task replaces the two span lines with a pure helper `_block_span` that also
counts every block-row cluster overlapping another block row's main run.

---

## Scope

- Add private `_block_span(block_rows, main_runs, row_clusters) -> Tuple[int, int]` to `perception/membership.py`.
- Replace `block_lo` / `block_hi` (membership.py:127-128) with `block_lo, block_hi = _block_span(...)`; update
  the comment above them and the `_row_block_votes` docstring sentence about the span.
- Tests in `test_membership.py` (spec §4 M3 rows).

**NOT in scope**: anchor-column, containment and LLM-hint votes (Non-Goal); `_MAX_GAP_PITCHES` /
`_BLOCK_OVERLAP` values; the BBY560 image integration test (TASK-4178).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/membership.py` | MODIFY | `_block_span` + use it |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_membership.py` | MODIFY | M3 tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# membership.py:9 already has: from typing import Dict, List, Optional, Sequence, Tuple
# membership.py:11: from ..contracts import FixtureMembership, Shape
from parrot_pipelines.planogram.perception.membership import assign_membership  # membership.py:192
from parrot_pipelines.planogram.contracts import FixtureMembership, Shape, ShapeKind  # test_membership.py:7
```

### Existing Signatures to Use
```python
# perception/membership.py
_MAX_GAP_PITCHES = 1.75                                                # :15
def _centre(shape: Shape) -> Tuple[float, float]                       # :22
def _clusters(row: List[Shape], pitch: float) -> List[List[Shape]]     # :61
def _extent(group: Sequence[Shape]) -> Tuple[int, int]                 # :72  (min x1, max x2)
def _row_block_votes(shapes, image_size) -> Dict[str, _Vote]           # :77
#   row_clusters = {index: _clusters(members, pitch) ...}              # :110
#   main_runs = {index: max(groups, key=lambda g: (len(g), -_extent(g)[0])) ...}  # :111
#   block_rows: List[int]                                              # :115
#   block_lo = min(_extent(main_runs[i])[0] for i in block_rows)       # :127
#   block_hi = max(_extent(main_runs[i])[1] for i in block_rows)       # :128
#   inside = block_lo <= (lo + hi) / 2 <= block_hi                     # :134 — unchanged
def assign_membership(shapes, zones, image_size, *, llm_hints=None) -> List[Shape]  # :192

# tests/planogram_cycle/test_membership.py
SIZE = (2000, 1500)                                                    # :10
def _shape(shape_id, x, y, w=120, h=120, *, kind=ShapeKind.PRODUCT, row_index=None) -> Shape  # :14
def _by_id(shapes)                                                     # :28
def _tag_rows(start_x=100, count=8, pitch=150, rows=3, prefix="t")     # :36
# Shape.membership / Shape.membership_evidence (see test_hole_inside_the_block_is_not_a_row_gap :147)
```

### Does NOT Exist
- ~~`_block_span`~~ — created here
- ~~`assign_membership(..., layout=...)`~~ — the rule is not gated by layout (spec §2 Part C)
- ~~a new vote reason~~ — reasons stay `row_block` / `row_gap`

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/membership.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_membership.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/membership.py#_row_block_votes",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/membership.py#_extent",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/membership.py#_clusters",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/membership.py#assign_membership"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Single pass (no fixed-point iteration): a cluster widens the span only if it overlaps a *main run* of a
  *different* block row, with strictly positive intersection (`min(hi_a, hi_b) - max(lo_a, lo_b) > 0`).
- A neighbouring fixture overlaps no main run ⇒ still `row_gap` (G5). Single-bay fixtures: every non-main
  cluster either already lies inside the main-run union or overlaps nothing new ⇒ votes unchanged.
- Expected BBY560 effect (spec §2): only `price_tag:205-2416-313-2469` flips to `(True, "row_block")`
  (row 2's left-bay cluster 219..1819 overlaps row 1's main run, so the span starts at 219 ≤ 259).

---

## Implementation Blueprint

### Steps (in order)
1. Add `_block_span` right above `_row_block_votes` — *why*: private, pure helper next to its only caller.
2. Replace lines 127-128 and refresh the comment above them — *why*: spec §3 M3 skeleton.
3. Update the docstring sentence "(the union of its main runs)" to describe the new span — *why*: keep docs truthful.
4. Write the tests; run the Validation Commands.

### `.../perception/membership.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def _row_block_votes(' perception/membership.py)
# BEFORE — insert above `def _row_block_votes(` (verified: perception/membership.py:77)
def _block_span(
    block_rows: Sequence[int],
    main_runs: Dict[int, List[Shape]],
    row_clusters: Dict[int, List[List[Shape]]],
) -> Tuple[int, int]:
    """Horizontal span of the fixture block.

    The union of every block row's main run plus every cluster of a block row whose x-extent overlaps
    (strictly positive intersection) the main run of a different block row. This keeps both bays of a
    multi-bay fixture when rows have their main runs in different bays. Pure and deterministic.
    """
    extents = [_extent(main_runs[i]) for i in block_rows]
    # FILL IN: for each index in block_rows, for each group in row_clusters[index] that is not main_runs[index]:
    #   if its _extent overlaps (> 0) _extent(main_runs[other]) for some other block row ≠ index, append it to
    #   extents — bounded by spec §2 Part C (single pass, strict overlap)
    return min(lo for lo, _ in extents), max(hi for _, hi in extents)


# occurrences: 1 (verified: grep -c 'block_lo = min(_extent(main_runs\[i\])\[0\] for i in block_rows)' perception/membership.py)
# REPLACE perception/membership.py:125-128 (the two comment lines + block_lo/block_hi lines) with
    # The block spans its rows' main runs plus any cluster that overlaps another block row's main run (a second bay
    # of a multi-bay fixture). A gap-separated cluster whose centre lies inside that span is a hole inside the
    # fixture (e.g. one missing tag, or a lone tag over an empty facing), not an adjacent fixture.
    block_lo, block_hi = _block_span(block_rows, main_runs, row_clusters)
```
**Why**: the vote loop below (`inside = block_lo <= (lo + hi) / 2 <= block_hi`) stays untouched, so the only
behavioural change is the span (AC8).

### `tests/planogram_cycle/test_membership.py` (MODIFY — append)
```python
def test_row_block_multi_bay_edge_cluster_on():
    """Two-bay rows, some main runs in the right bay, a lone left-edge tag ⇒ ON_FIXTURE (row_block)."""
    # FILL IN: rows 0/1 whole-width (main run spans both bays, gap ≤ 1.75 pitches), rows 2/3 with a bay gap
    #   > 1.75 pitches and a longer right bay, plus a bottom row whose leftmost tag is isolated but within the
    #   left bay's x-extent; assert that tag is ON with membership_evidence containing "row_block" — bounded by AC8
    #   (use a wider image size than SIZE if needed)


def test_row_block_adjacent_fixture_still_off():
    """A cluster beyond every block row's extent (neighbour fixture) stays OFF_FIXTURE (row_gap)."""
    # FILL IN: same layout + a cluster to the right of every row's last tag ⇒ OFF with "row_gap" — bounded by G5


def test_row_block_single_bay_unchanged():
    """Single-bay rows ⇒ the same votes as before (all row_block; existing hole test semantics)."""
    # FILL IN: _tag_rows() with one hole and one far-right off cluster ⇒ hard-coded expected memberships — bounded by AC8
```

### FILL IN checklist
- [ ] `_block_span` overlap loop — strict, single pass; bounded by spec §2 Part C
- [ ] three tests — bounded by AC8 / G5

---

## Acceptance Criteria

- [ ] AC8: a block-row cluster overlapping another block row's main run widens the span; single-bay fixtures vote as today
- [ ] Every existing test in `test_membership.py`, `test_shared_perception.py` passes unchanged
- [ ] `ruff check` clean on touched files

---

## Validation Commands

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_membership.py -q`
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_shared_perception.py -q`

---

## Test Specification

See the test stubs in the Implementation Blueprint (spec §4 M3 rows).

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug ink-wall-registration-and-completeness --feature-id FEAT-646`).
2. Verify the Codebase Contract; set this task `in-progress` in the per-spec index.
3. Implement from the blueprint; run the Validation Commands with
   `PYTHONPATH=packages/ai-parrot-pipelines/src:packages/ai-parrot/src`.
4. Commit only the listed files; close with `scripts/sdd/close_task.sh TASK-4177 ink-wall-registration-and-completeness verified`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none


**Completion Note (sdd-worker)**: merged via coder_merge; tests for touched modules pass (87 passed, PYTHONPATH-scoped). Merge-tier sweep showed pre-existing env failures (parrot.utils.types Cython .so, ocr_reader pyproject pillow) in files this feature does not touch.
