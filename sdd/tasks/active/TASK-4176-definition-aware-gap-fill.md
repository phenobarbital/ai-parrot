# TASK-4176: Definition-aware deficit fill in build_slots

**Feature**: FEAT-646 — Ink-wall slot recovery and completeness policy
**Spec**: `sdd/specs/ink-wall-registration-and-completeness.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §1 defect 1 and §2 Part A / §3 Module 1. On the BBY560 ink wall the bottom row has 11 tags for 15
expected facings; `_columns()` only fills gaps that are near-integer multiples of the row's own (inflated)
pitch, so 4 facings never get a slot. This task adds a pure helper `_fill_deficit` and a kw-only
`expected_facings` argument to `build_slots()` that tops each full-height row up to its shelf's facing count
by splitting the widest inter-column gaps. Perception wiring (`perceive.py`) is TASK-4178.

---

## Scope

- Add `_fill_deficit(columns, deficit)` to `perception/slots.py` (greedy widest-sub-segment insertion,
  interior only, ties → leftmost, output sorted by centre).
- Add `expected_facings: Optional[Sequence[int]] = None` (kw-only, last) to `build_slots()`; apply it only on
  the `TAG_BELOW_PRODUCT` path and only when `len(anchored) == len(expected_facings)`.
- Unit tests in `test_rows_slots.py` (spec §4 M1 rows except `test_ink_wall_profile_defaults`).

**NOT in scope**: `_expected_facings(ctx)` / `perceive.py` wiring and the BBY560 image tests (TASK-4178);
`LayoutProfile.definition_gap_fill` (TASK-4174); extending row ends (spec §8 Q3, open); changing
`GAP_TOLERANCE` or `_columns` (Non-Goal).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/slots.py` | MODIFY | `_fill_deficit` + `expected_facings` kw |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_rows_slots.py` | MODIFY | M1 unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# perception/slots.py already has: from typing import List, Optional, Sequence, Tuple   (:8)
from parrot_pipelines.planogram.perception.slots import AnchorRule, build_slots  # slots.py:145
from parrot_pipelines.planogram.perception.profiles import ShapeCandidate        # test_rows_slots.py:11
```

### Existing Signatures to Use
```python
# perception/slots.py
GAP_TOLERANCE = 0.25                                                   # :20
def _cx(c: ShapeCandidate) -> float                                    # :40
def _row_pitch(row: Sequence[ShapeCandidate]) -> float                 # :60
def _columns(row, fill_gaps: bool) -> List[Tuple[float, Optional[ShapeCandidate]]]  # :67
#   returns (centre_x, anchor-or-None) left→right; None = virtual (gap-filled) column
def _x_bounds(centres: Sequence[float], j: int, median_width: float) -> Tuple[float, float]  # :83
def _slot(image_id, row_index, slot_index, box, anchor_id) -> Slot     # :132 (inferred = anchor_id is None)
def build_slots(rows, image_size, *, image_id, rule, fill_gaps=True,
                untagged_bottom_row=False, max_rows=None) -> List[Slot]  # :145
#   SHAPE_IS_SLOT branch returns early (:183-199) — must ignore expected_facings
#   anchored = [r for r, row in enumerate(rows) if row]                 # :201
#   for r, row in enumerate(rows): if not row: continue                 # :203-205
#       columns = _columns(row, fill_gaps)                              # :206
#       centres = [cx for cx, _ in columns]                             # :207
#   virtual columns get bottom from the row line (_line_y) and median tag height — no anchor needed

# tests/planogram_cycle/test_rows_slots.py
def _tag(x: int, y: int, w: int = 120, h: int = 50) -> ShapeCandidate  # :27
W, H = 2000, 1500                                                       # :22
```

### Does NOT Exist
- ~~`build_slots(expected_facings=...)`~~, ~~`_fill_deficit`~~ — created here
- ~~`_expected_facings`~~ — TASK-4178 (stages/perceive.py), not in this file
- ~~`ShapeCandidate.cx`~~ — use the module's `_cx(c)`
- ~~`Slot.virtual`~~ — the flag is `inferred` (set by `_slot` when `anchor_id is None`)

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/slots.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_rows_slots.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/slots.py#build_slots",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/slots.py#_columns",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/slots.py#_x_bounds",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/slots.py#_slot"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Pure and deterministic; no I/O, no logging needed (module has no logger).
- `expected_facings=None` (and every guard miss) ⇒ byte-identical output to today (AC3).
- Rows with `len(columns) >= expected` keep their exact column list — no removal (G2).
- Shelf index of row `r` is its position in `anchored` (`anchored.index(r)`), not `r`, because empty rows are skipped.
- Verified expectation (spec §2 table): ROW5 centres + deficit 4 ⇒ +1 in 259→697, +1 in 1117→1594, +2 in 2478→3268.

---

## Implementation Blueprint

### Steps (in order)
1. Add `_fill_deficit` just above `_x_bounds` — *why*: it is a column-level helper like `_columns`.
2. Add the kw-only parameter + Args docstring entry to `build_slots` — *why*: spec §3 M1 skeleton fixes the signature.
3. Compute the guard once after `anchored`, then top up `columns` right after `_columns` — *why*: the existing slot loop then builds inferred slots for the new virtual columns with no other change.
4. Write the tests; run the Validation Commands.

### `.../perception/slots.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def _x_bounds(' perception/slots.py)
# BEFORE — insert above `def _x_bounds(` (verified: perception/slots.py:83)
def _fill_deficit(
    columns: List[Tuple[float, Optional[ShapeCandidate]]], deficit: int
) -> List[Tuple[float, Optional[ShapeCandidate]]]:
    """Insert ``deficit`` virtual columns into the widest inter-column gaps.

    Greedy: each insertion goes to the gap whose current sub-segment width
    ``(right_cx - left_cx) / (inserted + 1)`` is largest (ties: leftmost); each gap is then split evenly.
    Never inserts before the first or after the last column. ``deficit <= 0`` or fewer than two
    columns ⇒ ``columns`` returned unchanged. Output stays sorted by centre.
    """
    if deficit <= 0 or len(columns) < 2:
        return columns
    inserted = [0] * (len(columns) - 1)
    # FILL IN: `deficit` times, pick gap g maximising (columns[g+1][0] - columns[g][0]) / (inserted[g] + 1),
    #   ties → smallest g (use max over range with key=(width, -g)); inserted[g] += 1 — bounded by spec §3 M1
    result: List[Tuple[float, Optional[ShapeCandidate]]] = []
    for g, (cx, anchor) in enumerate(columns):
        result.append((cx, anchor))
        if g < len(inserted) and inserted[g]:
            step = (columns[g + 1][0] - cx) / (inserted[g] + 1)
            result.extend((cx + j * step, None) for j in range(1, inserted[g] + 1))
    return result


# occurrences: 1 (verified: grep -c '    max_rows: Optional\[int\] = None,' perception/slots.py)
# AFTER — insert below `    max_rows: Optional[int] = None,` (verified: perception/slots.py:153)
    expected_facings: Optional[Sequence[int]] = None,

# occurrences: 1 (verified: grep -c 'synthesized once that many anchored rows are visible' perception/slots.py)
# AFTER — insert below the `max_rows` Args entry ending at perception/slots.py:167
        expected_facings: Facings per definition shelf, top→bottom. ``TAG_BELOW_PRODUCT`` only, and only when
            the anchored rows count equals ``len(expected_facings)`` (a full-height photo): after the pitch
            fill each row's deficit against its shelf is filled into its widest inter-tag gaps. Ignored otherwise.

# occurrences: 1 (verified: grep -c 'anchored = \[r for r, row in enumerate(rows) if row\]' perception/slots.py)
# AFTER — insert below `    anchored = [r for r, row in enumerate(rows) if row]` (verified: perception/slots.py:201)
    full_height = expected_facings is not None and len(anchored) == len(expected_facings)

# occurrences: 1 (verified: grep -c '        columns = _columns(row, fill_gaps)' perception/slots.py)
# AFTER — insert below `        columns = _columns(row, fill_gaps)` (verified: perception/slots.py:206)
        if full_height:
            columns = _fill_deficit(columns, expected_facings[anchored.index(r)] - len(columns))  # type: ignore[index]
```
**Why**: spec §2 Part A — the pitch fill stays first, the definition-aware fill only adds the remaining
deficit; the guard encodes the full-height assumption (spec §7 gotcha) so partial photos are untouched.

### `tests/planogram_cycle/test_rows_slots.py` (MODIFY — append)
```python
ROW0 = [670, 851.5, 1040.5, 1229.5, 1420.5, 1589, 1752.5, 1928, 2177.5, 2395, 2596, 2812, 3390, 3609.5, 3808.5]
ROW5 = [259, 697, 814, 1117, 1594, 1784, 1947, 2168, 2478, 3268, 3564]
EXPECTED_FACINGS = [17, 18, 18, 18, 18, 15]
BBY_W, BBY_H = 4032, 3024  # FILL IN: any size wide/tall enough for the recorded centres and 6 rows


def _centred_row(centres, y: int, w: int = 100, h: int = 50) -> list[ShapeCandidate]:
    """Tags of one row at the recorded centre x positions."""
    return [_tag(round(cx - w / 2), y, w=w, h=h) for cx in centres]


def test_fill_deficit_widest_gaps():
    # FILL IN: columns=[(cx, None) for cx in ROW5]; _fill_deficit(columns, 4) ⇒ exactly 1 new centre in (259, 697),
    #   1 in (1117, 1594), 2 in (2478, 3268); originals preserved — bounded by spec §4
    ...


def test_fill_deficit_noop():
    # FILL IN: deficit 0 / -2 and a 1-column list ⇒ returned unchanged
    ...


def test_fill_deficit_interior_only():
    # FILL IN: large deficit ⇒ no new centre < first or > last; result sorted — bounded by AC2
    ...


def test_build_slots_expected_facings_full_height():
    # FILL IN: rows = [ROW0, 19 uniform, 19 uniform, 18 uniform, 19 uniform, ROW5] at increasing y (uniform rows at a
    #   ~180 px pitch); build_slots(..., rule=TAG_BELOW_PRODUCT, untagged_bottom_row=True, max_rows=6,
    #   expected_facings=EXPECTED_FACINGS) ⇒ per-row counts [17, 19, 19, 18, 19, 15]; inserted slots inferred=True,
    #   anchor_shape_id None, slot_index 1..n consecutive; rows 0–4 identical to expected_facings=None — bounded by AC1/AC2
    ...


def test_build_slots_expected_facings_not_full_height():
    # FILL IN: same rows minus one, expected_facings of length 6 ⇒ output == expected_facings=None output — bounded by AC3
    ...


def test_build_slots_expected_facings_shape_is_slot():
    # FILL IN: SHAPE_IS_SLOT rows (reuse _shape_slots/_product helpers) ⇒ identical with and without expected_facings
    ...
```
(Replace each `...` with the test body — they are listed only to keep the stubs syntactically valid.)

### FILL IN checklist
- [ ] `_fill_deficit` greedy loop — ties leftmost; bounded by spec §3 M1
- [ ] six tests — bounded by AC1/AC2/AC3 and spec §4 M1 rows

---

## Acceptance Criteria

- [ ] AC1: full-height rows end with `>= expected_facings[k]` slots; rows already at/above keep their exact slots
- [ ] AC2: inserted slots `inferred=True`, `anchor_shape_id=None`, interior only, consecutive `slot_index`
- [ ] AC3: `expected_facings=None` / guard miss / `SHAPE_IS_SLOT` ⇒ byte-identical slots to today
- [ ] Existing `test_rows_slots.py` tests pass; `ruff check` clean

---

## Validation Commands

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_rows_slots.py -q`
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_shelf_rows.py -q`

---

## Test Specification

See the test stubs in the Implementation Blueprint (spec §4 M1 rows).

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug ink-wall-registration-and-completeness --feature-id FEAT-646`).
2. Verify the Codebase Contract; set this task `in-progress` in the per-spec index.
3. Implement from the blueprint; run the Validation Commands with
   `PYTHONPATH=packages/ai-parrot-pipelines/src:packages/ai-parrot/src`.
4. Commit only the listed files; close with `scripts/sdd/close_task.sh TASK-4176 ink-wall-registration-and-completeness verified`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
