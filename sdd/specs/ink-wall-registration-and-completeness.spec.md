---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
projects: [ai-parrot-pipelines]
tags: [planogram, ink-wall, compliance, perception, registration]
---

# Feature Specification: Ink-wall slot recovery and completeness policy

**Feature ID**: FEAT-646
**Date**: 2026-10-09
**Author**: Jesus Lara
**Status**: approved
**Target version**: ai-parrot-pipelines (next minor, released in lockstep with the ai-parrot family)

> Origin: field run of flowtask `PlanogramCompliance` (config `epson_inkwall_config`, planogram_id 11)
> over `examples/planogram/images/epson_inkwall_config/2026-09-04-Kip-Kerrick-Best-Buy-560.jpeg`
> (store BBY560) right after FEAT-645 / flowtask FEAT-564 landed. No brainstorm: the root cause was
> established from a diagnostic run that dumped perception slots, identifications and position results.

---

## 1. Motivation & Business Requirements

### Problem Statement

On the BBY560 ink wall (6 shelves, 102 expected facings) the pipeline reports
`assessment_status = inconclusive`, so `overall_compliant` can never be `True`, even though
95.2 % of the facings were resolved. Three independent defects combine:

1. **Bottom shelf loses facings at perception time.** Shelf 6 expects 15 facings but perception
   builds only 11 slots for row 5 (10 after membership). The gaps between price tags are never
   filled: `_columns()` (`perception/slots.py:67`) derives the pitch from the row's own median
   anchor distance, which the missing tags inflate (row 5: 299.5 px vs ~175 px on the other rows),
   and only fills a gap when `|d/pitch − k| ≤ GAP_TOLERANCE (0.25)`. Measured gaps of 1.46×, 1.59×
   and 2.64× the pitch are all rejected. Shelf 6 holds toner boxes of very different widths, so
   **no uniform-pitch rule fixes it**: simulated on the recorded tags, a fixture-level pitch with a
   relaxed tolerance over-fills row 5 to 21 slots (rows 2 and 4 to 20 and 22), and the strict
   fixture-pitch variant reaches only 12.
   With too few observed slots, registration (`comparison/registration.py:_align_row`) anchors
   correctly on TN730 / TN760 / TN229 4PK, but the remaining facings get no slot and
   `merge_positions` reports them `not_visible` (p045–p048, p102 in the diagnostic run), although
   the shelf area is plainly visible in the photo.
2. **Completeness is all-or-nothing.** `summarize()` (`comparison/scoring.py:467`) sets
   `COMPLETE` only when *every* position is resolved, and `project_compliance()`
   (`comparison/projection.py:110`) applies the same rule per shelf. A single unresolved facing
   out of 102 makes the whole photo inconclusive. For ink walls, which are a presence/coverage
   audit over ~100 small facings photographed in one shot, a verdict should be possible when
   nearly all facings are resolved, with the unresolved ones still earning no credit.
3. **An empty on-fixture slot is classified off the fixture.** The leftmost bottom-row tag
   (x≈205–313, y≈2416) sits on the fixture above an empty facing (confirmed in the field: on the
   fixture, no product). `assign_membership` labels it `OFF_FIXTURE` with evidence `row_gap`, so
   `InkWall._registrable_slots` drops the slot and the empty facing is never reported.
   Root cause in `_row_block_votes()` (`perception/membership.py:77`): the fixture span is the union
   of each block row's *main run* only (`membership.py:127-128`). This ink wall has two bays split
   by a gap wider than `_MAX_GAP_PITCHES` (1.75) pitches, so rows whose largest cluster is the right
   bay (rows 2 and 4, which start at x=219 / 248) contribute only their right half, and the
   fixture's left edge is computed at x≈469. The lone tag's centre (259) lands outside, so it votes
   `row_gap`.

Note on the metric names, since they caused confusion in the field: `coverage` is the share of
facings that got a decision (present, empty, mismatch…), **not** product presence. In the BBY560
run presence was 65/102 (63.7 %) with 30 genuinely empty facings, so with the default per-shelf
threshold (0.8) the expected verdict is *conclusive and non-compliant*. This spec makes the run
conclusive; it does not change how presence is credited.

### Goals
- G1: On a full-height ink-wall photo, perception builds at least as many slots per row as the
  definition expects for that shelf, by filling the deficit into the widest inter-tag gaps before
  identification runs.
- G2: Rows that already have as many or more slots than expected facings are not changed (no
  over-filling).
- G3: Completeness becomes a policy (`CompletenessPolicy`): the minimum fraction of resolved facings
  for the global (`min_coverage`) and per-shelf (`min_shelf_coverage`) `COMPLETE` status. The default
  (1.0 / 1.0) keeps today's behaviour for every type; `ink_wall` defaults to 0.90 / 0.80, which can be
  overridden per configuration through `planogram_config.layout_profile.completeness`.
- G4: Unresolved facings keep earning 0 credit under a tolerant completeness policy: tolerance
  changes only `assessment_status` (and hence whether `overall_compliant` can be `True`), never the
  scores.
- G5: A cluster of a block row that lies within the fixture's real extent (including a lone tag over
  an empty facing at a fixture edge) is `ON_FIXTURE`, also on multi-bay fixtures whose rows have
  their main run in different bays. Adjacent fixtures keep voting `row_gap`.

### Non-Goals (explicitly out of scope)
- Changing the credit policy (`CreditPolicy.default()`), the per-shelf compliance threshold, or how
  `strict_compliance_score` is computed. Whether ink-wall *consumers* (flowtask markdown) should hide
  or de-emphasize the strict score is a presentation decision outside this package (§8 Q2, resolved:
  out of scope).
- A new `FacingStatus` for "unassigned facing inside a visible row". Unassigned facings stay
  `not_visible`; G1 removes the cause in the observed case.
- Changing the anchor-column, containment or LLM-hint votes of `assign_membership`; only the row-block
  span changes (Part C).
- Re-tuning `GAP_TOLERANCE` or the pitch-based fill for other types. The pitch fill stays as is and
  runs first; the definition-aware fill only adds the remaining deficit.

---

## 2. Architectural Design

### Overview

**Part A — definition-aware gap fill (perception, before identification).**
`build_slots()` gains an optional `expected_facings: Sequence[int] | None` (facings per definition
shelf, top→bottom). It applies only to the `TAG_BELOW_PRODUCT` path, and only when the number of
anchored rows equals `len(expected_facings)`, i.e. a full-height photo where row *k* is shelf *k*
(the same assumption `register_image` rewards with `PRIOR_FULL_HEIGHT`). For each anchored row,
after the existing `_columns(row, fill_gaps)` pass, the deficit
`d = expected_facings[k] − len(columns)` is computed. When `d > 0`, the `d` extra virtual columns
are distributed greedily: each one goes to the inter-column gap whose current sub-segment width
(gap width / (inserted + 1)) is largest, and every gap is then split evenly. Virtual columns become
inferred slots exactly like today's gap-filled ones (`anchor_shape_id=None`, `inferred=True`), so
the identification stage reads them like any other slot. Insertion is interior only: row ends are
never extended in this spec (§8 Q3 stays open: possibly needed, pending field evidence).

`perceive_image()` computes the per-shelf facing counts with a new `_expected_facings(ctx)` helper,
the sibling of `_expected_rows(ctx)` (`stages/perceive.py:53`), and passes them only when the layout
opts in through the new `LayoutProfile.definition_gap_fill: bool = False`. `InkWall`'s default
profile sets it to `True`.

Verified against the recorded BBY560 tags (expected facings 17/18/18/18/18/15):

| Row | Anchors | After pitch fill | Expected | Deficit fill |
|---|---|---|---|---|
| 0 | 15 | 17 | 17 | none (the pitch fill already added the same 2 slots in 2812→3390) |
| 1, 2, 4 | 19 | 19 | 18 | none (surplus is left alone) |
| 3 | 18 | 18 | 18 | none |
| 5 | 11 | 11 | 15 | +1 in 259→697, +1 in 1117→1594, +2 in 2478→3268 |

**Part B — completeness policy (comparison).**
A new `CompletenessPolicy` (`comparison/definition.py`, next to `ReportingPolicy`) holds
`min_coverage` and `min_shelf_coverage`, both in [0, 1] and defaulting to 1.0.
`LayoutProfile.completeness` carries it, so it resolves through the existing
`layout_profile` override path. `summarize()` and `project_compliance()` take it as an optional
keyword (`None` means the 1.0 / 1.0 default):

- global: `COMPLETE` iff shelf scores exist, `coverage ≥ min_coverage`, all status-relevant rule
  outcomes are assessed, and (positions or rule results) exist;
- per shelf: `complete` iff `resolved / expected_facings ≥ min_shelf_coverage` and the shelf's rules
  are complete. For a shelf with zero facings, the current rule-based completeness stays.

With the 1.0 default, both conditions reduce exactly to today's checks ("every position resolved").
`finalize_comparison()` is unchanged: `overall_compliant` still requires `COMPLETE` and every shelf
`COMPLIANT`. `compare_observations()` passes `getattr(ctx.layout, "completeness", None)` to both
calls.

**Part C — row-block span over multi-bay fixtures (membership).**
In `_row_block_votes()` the block span stops being the union of main runs only. It becomes the
union of the main runs **plus every cluster of a block row whose x-extent overlaps (strictly
positive intersection) the main run of a different block row**. The existing "inside" rule then
applies unchanged: a cluster whose centre lies within the span votes `row_block` (on), otherwise
`row_gap` (off). A row's left-bay cluster overlaps another row's left-bay main run, so both bays
count. A neighbouring fixture's tags overlap no main run of the block, so they keep voting
`row_gap`. The rule applies to every type that uses row-block votes; it is not gated by layout.

Verified on the recorded BBY560 shapes (all 109): exactly one vote changes, the tag
`price_tag:205-2416-313-2469` from `(False, "row_gap")` to `(True, "row_block")`. Every other
shape, including the nine `UNCERTAIN` tags without `row_index` outside the fixture, is unchanged.
Combined with Part A, row 5 then keeps 15 registrable slots for 15 facings.

### Component Diagram
```
assign_membership ──→ _row_block_votes (block span: main runs + overlapping clusters)
      ▼
perceive_image ──(expected_facings if layout.definition_gap_fill)──→ build_slots
      │                                                                 └─ _columns → _fill_deficit (new)
      ▼
identify_image (unchanged; reads the extra inferred slots)
      ▼
compare_observations ──→ register / merge / score_shelves (unchanged)
      ├──→ summarize(..., completeness=layout.completeness)            → assessment_status
      └──→ project_compliance(..., completeness=layout.completeness)   → per-shelf assessment
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `build_slots()` `perception/slots.py:145` | modifies | new kw-only `expected_facings`; TAG_BELOW_PRODUCT path only |
| `perceive_image()` `stages/perceive.py:246-254` | modifies | passes `expected_facings` when `profile.definition_gap_fill` |
| `LayoutProfile` `layout.py:66` | extends | `definition_gap_fill: bool = False`, `completeness: CompletenessPolicy` |
| `InkWall.default_layout_profile()` `types/ink_wall.py:64` | modifies | `definition_gap_fill=True`, `completeness=CompletenessPolicy(min_coverage=0.9, min_shelf_coverage=0.8)` |
| `summarize()` `comparison/scoring.py:430` | modifies | kw `completeness` |
| `project_compliance()` `comparison/projection.py:56` | modifies | kw `completeness` |
| `compare_observations()` `stages/compare.py:188` | modifies | forwards `ctx.layout.completeness` |
| `_row_block_votes()` `perception/membership.py:77` | modifies | block span includes clusters overlapping another block row's main run (`:127-128`) |
| flowtask `PlanogramCompliance` | consumer, unchanged | already surfaces `assessment_status` / `coverage` |

### Data Models
```python
class CompletenessPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    min_coverage: float = Field(default=1.0, ge=0.0, le=1.0)
    min_shelf_coverage: float = Field(default=1.0, ge=0.0, le=1.0)
```

Configuration override (JSONB `planogram_config` of the row):
```json
{"layout_profile": {"completeness": {"min_coverage": 0.95, "min_shelf_coverage": 0.85}}}
```

### New Public Interfaces
`CompletenessPolicy` (exported from `parrot_pipelines.planogram.comparison.definition`); the new
keyword arguments listed above. Nothing else.

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: definition-aware gap fill | yes | greedy split rule, full-height guard, interior-only, opt-in flag; signatures below | — |
| M2: completeness policy | yes | model, defaults, exact COMPLETE conditions, keyword plumbing; signatures below | — |
| M3: multi-bay row-block span | yes | exact span rule (main runs + clusters overlapping another block row's main run); private helper only | — |

### Module 1: Definition-aware gap fill
- **Path**: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/slots.py`,
  `stages/perceive.py`, `layout.py`, `types/ink_wall.py`
- **Responsibility**: give every full-height ink-wall row at least as many slots as its shelf expects,
  before identification.
- **Depends on**: —
- **Interface Skeleton**:
  ```python
  # perception/slots.py  (modifies perception/slots.py:145)
  def _fill_deficit(
      columns: List[Tuple[float, Optional[ShapeCandidate]]], deficit: int
  ) -> List[Tuple[float, Optional[ShapeCandidate]]]:
      """Insert ``deficit`` virtual columns into the widest inter-column gaps.

      Greedy: each insertion goes to the gap whose current sub-segment width
      ``(right_cx - left_cx) / (inserted + 1)`` is largest (ties: leftmost); each gap is then split evenly.
      Never inserts before the first or after the last column. ``deficit <= 0`` or fewer than two
      columns ⇒ ``columns`` returned unchanged. Output stays sorted by centre.
      """

  def build_slots(  # verified: perception/slots.py:145
      rows: Sequence[Sequence[ShapeCandidate]],
      image_size: Tuple[int, int],
      *,
      image_id: str,
      rule: AnchorRule,
      fill_gaps: bool = True,
      untagged_bottom_row: bool = False,
      max_rows: Optional[int] = None,
      expected_facings: Optional[Sequence[int]] = None,
  ) -> List[Slot]:
      """... expected_facings: facings per definition shelf, top→bottom. TAG_BELOW_PRODUCT only, and
      only when the anchored rows count equals ``len(expected_facings)``: after ``_columns`` each row's
      deficit against its shelf is filled by ``_fill_deficit``. Ignored otherwise."""

  # stages/perceive.py  (sibling of stages/perceive.py:53)
  def _expected_facings(ctx: CycleContext) -> Optional[List[int]]:
      """Facing count of every definition shelf that carries facings, top→bottom; None without a definition."""

  # layout.py  (modifies LayoutProfile, layout.py:66; next to untagged_bottom_row, layout.py:74)
  definition_gap_fill: bool = False

  # types/ink_wall.py  (modifies InkWall.default_layout_profile, types/ink_wall.py:64)
  #   LayoutProfile(..., definition_gap_fill=True, completeness=CompletenessPolicy(min_coverage=0.9, min_shelf_coverage=0.8))
  ```

### Module 2: Completeness policy
- **Path**: `comparison/definition.py`, `layout.py`, `comparison/scoring.py`,
  `comparison/projection.py`, `stages/compare.py`
- **Responsibility**: make the resolved-fraction requirement of `COMPLETE` configurable, global and per shelf.
- **Depends on**: — (M1 sets the ink-wall default through the same profile, so M2 must land first or together)
- **Interface Skeleton**:
  ```python
  # comparison/definition.py  (new, next to ReportingPolicy at comparison/definition.py:49)
  class CompletenessPolicy(BaseModel):
      """Minimum resolved-facing fractions for a COMPLETE assessment (1.0 = every facing resolved)."""
      model_config = ConfigDict(extra="forbid")
      min_coverage: float = Field(default=1.0, ge=0.0, le=1.0)
      min_shelf_coverage: float = Field(default=1.0, ge=0.0, le=1.0)

  # layout.py  (LayoutProfile, next to reporting at layout.py:97)
  completeness: CompletenessPolicy = Field(default_factory=CompletenessPolicy)

  # comparison/scoring.py  (modifies comparison/scoring.py:430)
  def summarize(
      shelf_scores: Sequence[ShelfScore],
      positions: Sequence[PositionResult],
      definition: SlotsDefinition,
      weights: EvidenceWeights,
      *,
      completeness: Optional[CompletenessPolicy] = None,
  ) -> ComparisonResult:
      """... COMPLETE iff shelf scores exist, coverage >= completeness.min_coverage, every
      status-relevant rule outcome is assessed, and positions or rule results exist."""

  # comparison/projection.py  (modifies comparison/projection.py:56)
  def project_compliance(
      shelf_scores, positions, definition, description, *,
      policy: Optional[ReportingPolicy] = None,
      completeness: Optional[CompletenessPolicy] = None,
  ) -> List[ComplianceResult]:
      """... a shelf is complete iff (expected_facings - len(unresolved)) / expected_facings >=
      completeness.min_shelf_coverage and its rules are complete (zero-facing shelves: rules only)."""

  # stages/compare.py  (modifies stages/compare.py:219 and :227-228)
  #   summarize(..., completeness=getattr(ctx.layout, "completeness", None))
  #   project_compliance(..., policy=policy, completeness=getattr(ctx.layout, "completeness", None))
  ```

### Module 3: Multi-bay row-block span
- **Path**: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/perception/membership.py`
- **Responsibility**: keep a fixture-edge cluster (e.g. a lone tag over an empty facing) on the fixture
  when the block rows have their main runs in different bays.
- **Depends on**: — (independent of M1/M2)
- **Interface Skeleton**:
  ```python
  # perception/membership.py  (new private helper; replaces the span lines at membership.py:127-128)
  def _block_span(
      block_rows: Sequence[int],
      main_runs: Dict[int, List[Shape]],
      row_clusters: Dict[int, List[List[Shape]]],
  ) -> Tuple[int, int]:
      """Horizontal span of the fixture block: the union of every block row's main run plus every cluster
      of a block row whose x-extent overlaps (strictly positive intersection) the main run of a different
      block row. Pure and deterministic."""

  # _row_block_votes  (verified: membership.py:77) — unchanged signature and vote reasons:
  #   block_lo, block_hi = _block_span(block_rows, main_runs, row_clusters)
  #   inside = block_lo <= (lo + hi) / 2 <= block_hi     # unchanged rule, membership.py:134
  ```

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_fill_deficit_widest_gaps` | M1 | row-5 centres + deficit 4 ⇒ inserts 1 in 259→697, 1 in 1117→1594, 2 in 2478→3268 |
| `test_fill_deficit_noop` | M1 | deficit ≤ 0, or < 2 columns ⇒ unchanged |
| `test_fill_deficit_interior_only` | M1 | no inserted centre < first or > last column centre |
| `test_build_slots_expected_facings_full_height` | M1 | 6 recorded rows + `[17,18,18,18,18,15]` ⇒ per-row slot counts 17,19,19,18,19,15 |
| `test_build_slots_expected_facings_not_full_height` | M1 | anchored rows ≠ `len(expected_facings)` ⇒ identical output to `expected_facings=None` |
| `test_build_slots_expected_facings_shape_is_slot` | M1 | `SHAPE_IS_SLOT` ignores `expected_facings` |
| `test_ink_wall_profile_defaults` | M1/M2 | `definition_gap_fill is True`; completeness 0.9 / 0.8 |
| `test_layout_completeness_override` | M2 | `layout_profile.completeness` override resolves; unknown key / out-of-range value ⇒ `ValueError` |
| `test_summarize_default_completeness_unchanged` | M2 | one unresolved position + default policy ⇒ `INCONCLUSIVE` (regression) |
| `test_summarize_tolerant_completeness` | M2 | 97/102 resolved, `min_coverage=0.9` ⇒ `COMPLETE`; same scores as with default policy |
| `test_summarize_tolerant_rules_still_required` | M2 | coverage ≥ threshold but an unassessed mandatory rule ⇒ `INCONCLUSIVE` |
| `test_project_shelf_completeness` | M2 | 14/15 resolved, `min_shelf_coverage=0.8` ⇒ shelf `assessment_status == "complete"`; at 11/15 ⇒ `"inconclusive"` |
| `test_overall_compliant_requires_complete_and_all_compliant` | M2 | tolerant COMPLETE + one NON_COMPLIANT shelf ⇒ `overall_compliant False` |
| `test_row_block_multi_bay_edge_cluster_on` | M3 | two-bay rows (gap > 1.75 pitches), some rows' main run in the right bay, a lone left-edge tag within the left bay's extent ⇒ `ON_FIXTURE` (`row_block`) |
| `test_row_block_adjacent_fixture_still_off` | M3 | a cluster beyond every block row's extent (neighbour fixture) ⇒ still `OFF_FIXTURE` (`row_gap`) |
| `test_row_block_single_bay_unchanged` | M3 | single-bay rows ⇒ votes identical to the current implementation |

Existing suites that must keep passing unchanged: `tests/planogram_cycle/test_rows_slots.py`,
`test_registration.py`, `test_scoring_projection.py`, `test_reporting_projection.py`,
`test_ink_wall.py`, `test_ink_wall_example.py`, `test_membership.py`.

### Integration Tests
| Test | Description |
|---|---|
| `test_ink_wall_bby560_full_height_slots` | CV-only perception (no LLM) of the BBY560 example image ⇒ row 5 has ≥ 15 slots before membership; rows 0–4 unchanged vs `definition_gap_fill=False` |
| `test_ink_wall_bby560_membership_edge_tag` | CV-only perception of the BBY560 image ⇒ `price_tag:205-2416-313-2469` is `ON_FIXTURE`; every other shape keeps its current membership; row 5 keeps 15 registrable slots |

### Test Data / Fixtures
Recorded price-tag centres (x, px) of the BBY560 image, `perception_mode="cv"`:
```python
ROW0 = [670, 851.5, 1040.5, 1229.5, 1420.5, 1589, 1752.5, 1928, 2177.5, 2395, 2596, 2812, 3390, 3609.5, 3808.5]
ROW5 = [259, 697, 814, 1117, 1594, 1784, 1947, 2168, 2478, 3268, 3564]  # 259: on fixture, empty facing (§8 Q1)
# Row extents (x1 of first tag, x2 of last tag) and the bay gap (> 1.75 pitches) for M3 fixtures:
ROW_EXTENTS = {0: (616, 3886), 1: (469, 3790), 2: (219, 3841), 3: (516, 3495), 4: (248, 3640), 5: (205, 3621)}
# rows 2 and 4 split at x≈1819→2101 / 1762→2077: their main run is the RIGHT bay
EXPECTED_FACINGS = [17, 18, 18, 18, 18, 15]
```
The full per-row candidate boxes can be regenerated from the example image with the CV perception
path, which is deterministic.

---

## 5. Acceptance Criteria

- [ ] AC1: For a `TAG_BELOW_PRODUCT` photo with anchored rows == definition shelves, every row ends with
  `≥ expected_facings[k]` slots; rows that already had `≥` keep their exact slot list.
- [ ] AC2: Inserted slots are `inferred=True`, `anchor_shape_id=None`, interior only, and sorted with
  consecutive `slot_index` 1..n per row.
- [ ] AC3: `definition_gap_fill=False` (default for every non-ink-wall type) produces byte-identical
  slots to the current implementation.
- [ ] AC4: With `CompletenessPolicy()` defaults, `summarize` and `project_compliance` return the same
  `assessment_status` as today for every existing test.
- [ ] AC5: With a tolerant policy, `overall_compliance_score`, `strict_compliance_score`, `coverage`,
  per-shelf scores and credits are identical to the default-policy run; only `assessment_status` (and
  hence `overall_compliant`) may differ.
- [ ] AC6: `ink_wall` defaults: `definition_gap_fill=True`, `min_coverage=0.9`,
  `min_shelf_coverage=0.8`; both completeness values are overridable through
  `planogram_config.layout_profile.completeness` and validated (`extra="forbid"`, range [0, 1]).
- [ ] AC7: On the BBY560 example (live LLM, manual check), the run is `assessment_status = complete`;
  `overall_compliant` is decided by the per-shelf thresholds (expected `False`: genuinely empty facings).
- [ ] AC8: A block-row cluster that overlaps another block row's main run widens the block span; the lone
  BBY560 edge tag becomes `ON_FIXTURE` (`row_block`) and no other shape of that image changes membership;
  single-bay fixtures vote exactly as today.
- [ ] AC9: All tests in §4 pass; `ruff` clean on touched files.

---

## 6. Codebase Contract

> Verified against `d78d6268b` (ai-parrot `dev`), paths relative to
> `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/`.

### Verified Imports
```python
from parrot_pipelines.planogram.comparison.definition import ReportingPolicy, SlotsDefinition, effective_reporting  # definition.py:49, :183
from parrot_pipelines.planogram.perception.slots import AnchorRule, build_slots  # slots.py:145
from parrot_pipelines.planogram.layout import LayoutProfile, resolve_layout_profile, LAYOUT_KEY  # layout.py:66, :151, :18
from parrot_pipelines.planogram.comparison.scoring import summarize, score_shelves, merge_positions  # scoring.py:430
from parrot_pipelines.planogram.comparison.projection import project_compliance, finalize_comparison  # projection.py:56, :169
from parrot_pipelines.planogram.contracts import AssessmentStatus, FacingStatus, CycleContext, Slot
from parrot_pipelines.planogram.perception.membership import assign_membership  # membership.py:192
```

### Existing Class Signatures
```python
# perception/slots.py
GAP_TOLERANCE = 0.25                                                    # :20
def _row_pitch(row: Sequence[ShapeCandidate]) -> float                  # :60  median consecutive-anchor gap
def _columns(row, fill_gaps: bool) -> List[Tuple[float, Optional[ShapeCandidate]]]  # :67
def build_slots(rows, image_size, *, image_id, rule, fill_gaps=True,
                untagged_bottom_row=False, max_rows=None) -> List[Slot]  # :145
#   TAG_BELOW_PRODUCT loop: `columns = _columns(row, fill_gaps)` at :206; `anchored` at :200
#   _slot(image_id, row_index, slot_index, box, anchor_id) sets inferred = anchor_id is None  # :132

# stages/perceive.py
def _expected_rows(ctx: CycleContext) -> Optional[int]                  # :53  shelves with facings
#   build_slots(...) call at :246-254, `max_rows=_expected_rows(ctx)` at :253

# layout.py
class LayoutProfile(BaseModel):  # :66, model_config extra="forbid" (:69)
    anchor_rule: AnchorRule = AnchorRule.SHAPE_IS_SLOT    # :72
    fill_gaps: bool = False                               # :73
    untagged_bottom_row: bool = False                     # :74
    reporting: ReportingPolicy = Field(default_factory=ReportingPolicy)  # :97
def resolve_layout_profile(defaults, config, *, config_name) -> LayoutProfile  # :151 (deep-merges config["layout_profile"])

# comparison/definition.py
class ReportingPolicy(BaseModel):  # :49, extra="forbid"
    product_label: Literal["display_name", "product"] = "display_name"
    slot_presence: bool = False
    misplaced_min_confidence: float = 0.9

# comparison/scoring.py
def summarize(shelf_scores, positions, definition, weights: EvidenceWeights) -> ComparisonResult  # :430
#   rules_complete = all(o.assessed for o in rule_results)   # :466
#   complete = (bool(shelf_scores) and len(resolved) == len(positions) and rules_complete
#               and (bool(positions) or bool(rule_results)))  # :467-472

# comparison/projection.py
def project_compliance(shelf_scores, positions, definition, description, *,
                       policy: Optional[ReportingPolicy] = None) -> List[ComplianceResult]  # :56
#   complete = not unresolved_ids and rules_complete   # :110
def finalize_comparison(comparison, compliance_results) -> ComparisonResult  # :169 (COMPLETE and all COMPLIANT)

# stages/compare.py
def compare_observations(perceptions, identifications, ctx, description) -> ComparisonResult  # :188
#   summarize(shelves, positions, definition, ctx.evidence_weights)  # :219
#   finalize_comparison(comparison, project_compliance(..., policy=policy))  # :227-228

# types/ink_wall.py
class InkWall(AbstractPlanogramType):  # :55
    @classmethod
    def default_layout_profile(cls) -> LayoutProfile  # :64; reporting=... at :77
    def _registrable_slots(self, perception, idents) -> List[Slot]  # :136 (drops OFF_FIXTURE-anchored slots)

# contracts.py
class CycleContext:  layout: Any = None  # :387 (validated LayoutProfile, typed Any)

# perception/membership.py
_MAX_GAP_PITCHES = 1.75                                          # :15
def _clusters(row: List[Shape], pitch: float) -> List[List[Shape]]  # :61
def _extent(group: Sequence[Shape]) -> Tuple[int, int]           # :72
def _row_block_votes(shapes, image_size) -> Dict[str, _Vote]     # :77
#   main_runs = {index: max(groups, key=lambda g: (len(g), -_extent(g)[0])) ...}
#   block_lo = min(_extent(main_runs[i])[0] for i in block_rows)   # :127
#   block_hi = max(_extent(main_runs[i])[1] for i in block_rows)   # :128
#   inside = block_lo <= (lo + hi) / 2 <= block_hi                  # :134
def assign_membership(shapes, zones, image_size, *, llm_hints=None) -> List[Shape]  # :192
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `_fill_deficit` | `build_slots` TAG_BELOW_PRODUCT loop | call after `_columns` | `slots.py:206` |
| `_expected_facings` | `perceive_image` | `build_slots(expected_facings=...)` | `perceive.py:246-254` |
| `CompletenessPolicy` | `LayoutProfile.completeness` | field | `layout.py:97` |
| `completeness` kw | `summarize` / `project_compliance` | `compare_observations` | `compare.py:219`, `:228` |
| `_block_span` | `_row_block_votes` | replaces the span lines | `membership.py:127-128` |

### Does NOT Exist (Anti-Hallucination)
- ~~`CompletenessPolicy`~~, ~~`LayoutProfile.completeness`~~, ~~`LayoutProfile.definition_gap_fill`~~ — created by this spec
- ~~`build_slots(expected_facings=...)`~~, ~~`_fill_deficit`~~, ~~`_expected_facings`~~, ~~`_block_span`~~ — created by this spec
- ~~`ShelfConfig.completeness_threshold`~~ — not real; the per-shelf *compliance* threshold is `ShelfConfig.compliance_threshold` (read by `_threshold`, `projection.py:48`) and is unrelated
- ~~`FacingStatus.UNOBSERVED`~~ — not real and not added (Non-Goal)
- ~~`ReportingPolicy.min_coverage`~~ — completeness does not live on `ReportingPolicy`

### Edit Sites (Blueprint Anchors)

Verified against: `d78d6268b`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `.../planogram/perception/slots.py` | MODIFY | `def build_slots(` | `slots.py:145` | 1 |
| `.../planogram/perception/slots.py` | MODIFY | `        columns = _columns(row, fill_gaps)` | `slots.py:206` | 1 |
| `.../planogram/stages/perceive.py` | MODIFY | `        max_rows=_expected_rows(ctx),` | `perceive.py:253` | 1 |
| `.../planogram/stages/perceive.py` | MODIFY | `def _expected_rows(ctx: CycleContext) -> Optional[int]:` | `perceive.py:53` | 1 |
| `.../planogram/layout.py` | MODIFY | `    untagged_bottom_row: bool = False` | `layout.py:74` | 1 |
| `.../planogram/layout.py` | MODIFY | `    reporting: ReportingPolicy = Field(default_factory=ReportingPolicy)` | `layout.py:97` | 1 |
| `.../planogram/types/ink_wall.py` | MODIFY | `            reporting=ReportingPolicy(product_label="product", slot_presence=True),` | `ink_wall.py:77` | 1 |
| `.../planogram/comparison/definition.py` | MODIFY | `class ReportingPolicy(BaseModel):` | `definition.py:49` | 1 |
| `.../planogram/comparison/scoring.py` | MODIFY | `def summarize(` | `scoring.py:430` | 1 |
| `.../planogram/comparison/scoring.py` | MODIFY | `    complete = (` | `scoring.py:467` | 1 |
| `.../planogram/comparison/projection.py` | MODIFY | `def project_compliance(` | `projection.py:56` | 1 |
| `.../planogram/comparison/projection.py` | MODIFY | `        complete = not unresolved_ids and rules_complete` | `projection.py:110` | 1 |
| `.../planogram/stages/compare.py` | MODIFY | `    comparison = summarize(shelves, positions, definition, ctx.evidence_weights)` | `compare.py:219` | 1 |
| `.../planogram/stages/compare.py` | MODIFY | `        comparison, project_compliance(shelves, positions, definition, description, policy=policy)` | `compare.py:228` | 1 |
| `.../planogram/perception/membership.py` | MODIFY | `    block_lo = min(_extent(main_runs[i])[0] for i in block_rows)` | `membership.py:127` | 1 |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_rows_slots.py` | MODIFY | (append tests) | — | — |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_scoring_projection.py` | MODIFY | (append tests) | — | — |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_ink_wall.py` | MODIFY | (append tests) | — | — |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_membership.py` | MODIFY | (append tests) | — | — |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Perception and comparison stay pure and deterministic (no I/O, no LLM); same input ⇒ same output.
- New knobs are opt-in on `LayoutProfile` with defaults that reproduce today's behaviour; the type sets
  its own defaults in `default_layout_profile()`, and configurations override them through
  `layout_profile` (the existing `resolve_layout_profile` merge).
- `CompletenessPolicy` follows `ReportingPolicy`: `extra="forbid"`, bounded `Field`s.

### Known Risks / Gotchas
- **Full-height assumption.** Row *k* ↔ shelf *k* only holds when every shelf has an anchored row. The
  guard (anchored rows == `len(expected_facings)`) skips the fill otherwise; partial photos keep today's
  behaviour.
- **Fabricated slots on genuinely sparse shelves.** If tags were removed with the products, inserted slots
  read as `empty`, which is the correct verdict for an expected facing. If a wide box spans an inserted
  slot, identification may read the same product twice; registration's `misplaced`/`mismatch` logic
  handles duplicates already, but watch `misplaced` counts on the bottom shelf.
- **Wider block span (M3) is shared by every type using row-block votes.** The overlap condition only adds
  clusters that share x-range with another block row's main run, so a neighbouring fixture (no overlap)
  stays `row_gap`; `test_row_block_single_bay_unchanged` and the existing `test_membership.py` guard it.
- **Tolerance must not inflate scores**: unresolved facings keep 0 lenient and 0 strict credit (AC5).
- `ctx.layout` is typed `Any` and may be `None` for non-cycle paths; use `getattr(..., "completeness", None)`.

### External Dependencies
None.

---

## 8. Open Questions

- [x] Q1: Is the leftmost bottom-row tag (x≈205–313, y≈2416) really off the fixture? — *Owner: Jesus Lara*:
  No. It is on the fixture and there is no product there (an empty facing). Root cause found (multi-bay
  block span, §1 defect 3) and fixed in scope by Part C / Module 3.
- [x] Q2: Should ink-wall consumers (flowtask markdown) hide or de-emphasize `strict_compliance_score`? —
  *Owner: Jesus Lara*: Out of scope for this spec (left out, as proposed).
- [ ] Q3: Should the deficit fill also extend row ends (facings beyond the first/last tag) when the row's
  extent is short of the fixture edges? — *Owner: Jesus Lara*: "possibly". Interior-only in this spec;
  revisit with field photos where an end facing is missing.
- [x] Q4: Ink-wall defaults `min_coverage=0.90` / `min_shelf_coverage=0.80`? — *Owner: Jesus Lara*: Confirmed.

---

## Worktree Strategy

- Default isolation unit: **per-spec**. M1 and M2 both touch `layout.py` and `types/ink_wall.py`, so the
  tasks run sequentially in one worktree (M2 first: it defines `CompletenessPolicy`, which the ink-wall
  defaults in M1 reference). M3 touches only `membership.py` + `test_membership.py` and is independent;
  it can run in parallel with M2/M1.
- Cross-feature dependencies: none (FEAT-645 is merged).

---

## 9. Design Research Cross-Check

> Model: — · Status: skipped (no accepted exploration document; spec scaffolded directly from a diagnostic run)

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-09 | Jesus Lara | Initial draft from the BBY560 field diagnosis |
| 0.2 | 2026-10-09 | Jesus Lara | Q1 answered (on fixture, empty facing): root cause found, Part C / M3 added; Q2 and Q4 resolved, Q3 kept open |
