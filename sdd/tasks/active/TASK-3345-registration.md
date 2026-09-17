# TASK-3345: Deterministic registration (rows→shelves, slots→facings)

**Feature**: FEAT-565 — New Planogram Compliance Algorithm
**Spec**: `sdd/specs/new-planogram-compliance-algo.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3338
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 8** / §2 stage 6. inkcheck's autonomous mode scored 0 % because nothing
ever assigned a planogram position to a detected slot. This module is that missing piece:
given the pass-1 observations of ONE photo, it decides which planogram shelf each visible
row is and which expected facing each slot is — **deterministically, with no LLM and no
I/O** (spec G6: "the LLM never assigns planogram positions"; §5: "same observations →
byte-identical `ImageRegistration`").

Brand sequences alone cannot register a photo (shelves 1–5 of the real planogram all start
with 9 HP positions), so the alignment scores SKU/family anchors, tolerates gaps, accepts
partial views, and is cross-checked by slot pitch and a vertical-order prior.

---

## Scope

- Implement `pair_score()` — the §2 score table (restated verbatim below).
- Implement `align_row()` — semi-global, gap-tolerant alignment of one row's observed
  slots against one shelf's facings, with the §2 gap costs and pitch check; returns
  `(score, slot_id→facing_id, direct-anchor count)`.
- Implement `register_image()` — enumerate order-preserving injective row→shelf maps,
  add the vertical prior, pick the best (ties → lowest shelf numbers), record runner-up
  and margin, grade each row.
- Implement `apply_registration()` — write `facing_id` / `registration_grade` into the
  observations in place.
- Write `examples/planogram/tests/test_plancheck_registration.py` with the five spec §4 tests.

**NOT in scope**: multi-photo merge and statuses (TASK-3347, `plancheck/scoring.py`);
computing pitches (`row_pitch` lives in `plancheck/grid.py`, TASK-3341 — this
module only *receives* `pitches: dict[int, float]` keyed by row number); catalog resolution
(TASK-3339); any LLM call; any model change (`examples/planogram/plancheck/models.py` is owned by
TASK-3337 / TASK-3338).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/planogram/plancheck/registration.py` | CREATE | Pure alignment/registration functions |
| `examples/planogram/tests/test_plancheck_registration.py` | CREATE | Unit tests (spec §4, M8 rows) |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: use these exact imports and names. Do not invent anything not listed.

### Verified Imports
```python
from __future__ import annotations
import logging
from itertools import combinations          # stdlib
```

#### Created by dependency tasks (exist only after they land)
```python
# examples/planogram/plancheck/models.py — part 1 by TASK-3337, part 2 by TASK-3338
from plancheck.models import (
    Catalog, CatalogItem, PlanogramFacing, PlanogramRef,          # TASK-3337
    Slot, SlotReading,                                             # TASK-3337 (tests only)
    SlotObservation, RowRegistration, ImageRegistration, Grade,    # TASK-3338
)
```
Tests import `from plancheck.registration import …`; `examples/planogram/tests/conftest.py`
(TASK-3337) puts `examples/planogram/` on `sys.path` and provides the `mini_planogram` and
`mini_catalog` fixtures.

### Existing Signatures to Use
Nothing in the repository today. The model fields this module reads/writes (fixed by spec §3
Module 1 — re-verify in `examples/planogram/plancheck/models.py` once TASK-3338 has landed):
```python
class PlanogramFacing: facing_id: str; shelf: int; slot: int; facing: int; sku: str
                       brand: str | None; identity_required: bool
class PlanogramRef:    shelf_count: int; facings: list[PlanogramFacing]
                       def shelf(self, number: int) -> list[PlanogramFacing]   # ordered by (slot, facing)
class CatalogItem:     sku: str; brand: str; family: str | None
class Catalog:         def by_sku(self, sku: str) -> CatalogItem | None
class Slot:            slot_id: str; image_id: str; row: int; index: int; box: tuple[int, int, int, int]
class SlotReading:     occupancy: "occupied"|"empty"|"uncertain"; brand: str | None; family: str | None
class SlotObservation: slot: Slot; reading: SlotReading | None; resolved_sku: str | None
                       candidate_skus: list[str]; resolution: Resolution
                       facing_id: str | None; registration_grade: Grade | None
class RowRegistration: image_id: str; row: int; shelf: int | None; score: float
                       anchors: int; grade: Grade; assignments: dict[str, str]   # slot_id -> facing_id
class ImageRegistration: image_id: str; rows: list[RowRegistration]; total_score: float
                       runner_up_shelves: list[int | None] | None; margin: float | None
```

### Does NOT Exist
- ~~any registration/alignment code in `examples/planogram/inkcheck/`~~ — inkcheck's `facing_id` is only set by its manual `review.html`; there is nothing to port.
- ~~`import inkcheck`~~ — not a package on the path, and the directory is git-ignored (absent in worktrees).
- ~~`plancheck.reference.normalize_brand` inside this module~~ — do NOT import `reference.py` (no dependency edge on TASK-3339); compare brands with `str.casefold().strip()`.
- ~~`PlanogramFacing.position` as an ordering key~~ — `position` is NOT monotone; the physical axis is `slot` (use `PlanogramRef.shelf()`).
- ~~`parrot`, `cv2`, `numpy` imports here~~ — this is a pure module; stdlib + `plancheck.models` only.
- ~~`SlotObservation.row` / `.image_id`~~ — those live on `obs.slot`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "examples/planogram/plancheck/registration.py",
      "action": "CREATE"
    },
    {
      "path": "examples/planogram/tests/test_plancheck_registration.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Normative rules (spec §2 "Decided semantics" — verbatim; do NOT re-derive or tune)

> **Alignment scores** (per observed slot vs expected facing): same SKU (`direct`)
> +4 · expected SKU ∈ `candidate_skus` +3 · same brand and family +2 · same brand
> +1 · occupied with no brand 0 · empty 0 · CLOSEOUT facing vs any occupied 0 ·
> different brand −2. Gaps: interior gap −1.5 on either sequence; leading/trailing
> gaps on the **planogram** side 0 (partial view); leading/trailing gaps on the
> **observed** side −0.5 (neighbouring-fixture slots → `unregistered`).
> Pitch check: an alignment step that skips `k` facings must span `k+1` median
> pitches ±35 %, else −1 per violation. Vertical prior: +1 per pair of adjacent
> rows mapped to consecutive shelves; +2 when row count equals shelf count.
> Ties → lowest shelf numbers. Grade: `high` if margin ≥ 3 and ≥ 2 direct anchors
> in the row; `low` if margin < 1 or 0 anchors; else `medium`. `low` rows are
> capped at lenient-only credit.

### Operational reading of those rules (fixed for this task)

`pair_score` evaluation order — first matching rule wins:
1. `obs.reading is None` or `obs.reading.occupancy != "occupied"` → `0.0` (empty / uncertain).
2. `not facing.identity_required` (CLOSEOUT) → `0.0`.
3. `obs.resolution == "direct"` and `obs.resolved_sku == facing.sku` → `+4.0`.
4. `facing.sku in obs.candidate_skus` → `+3.0`.
5. observed brand == expected brand **and** observed family == expected family (both not None) → `+2.0`.
6. observed brand == expected brand → `+1.0`.
7. observed brand is None → `0.0`.
8. otherwise → `-2.0`.

Observed brand/family: from `catalog.by_sku(obs.resolved_sku)` when `resolved_sku` is set and
in the catalog, else `obs.reading.brand` / `obs.reading.family`. Expected brand = `facing.brand`;
expected family = `catalog.by_sku(facing.sku).family` (None when the SKU is not in the catalog).
Brands/families compare with `.casefold().strip()`.

`align_row`:
- Sequences: `row_obs` sorted by `obs.slot.index`; `facings` exactly as passed (`PlanogramRef.shelf(n)` order).
- A facing skipped at the start/end of the facing sequence costs 0; in the interior −1.5.
  A slot skipped at the start/end of the observed sequence costs −0.5; in the interior −1.5.
  Skipped slots get **no** entry in the returned mapping (they stay unregistered).
- Pitch check, applied on the traceback: for consecutive *matched* pairs `(slot_a→facing_i)`,
  `(slot_b→facing_j)` with `k = j − i − 1 ≥ 1` skipped facings, let `d` = distance between the two
  slots' box x-centres; violation when `abs(d − (k+1)·pitch) > 0.35·(k+1)·pitch` → −1 each.
  Skip the check when `pitch <= 0`.
- Anchor count = number of matched pairs whose `pair_score` is `+4.0`.
- Determinism: DP tie-break order is **match > skip-facing > skip-slot**; among equal-score
  end cells prefer the smallest facing index. No randomness, no set/dict iteration that
  depends on hash order (iterate lists / `sorted()`).
- Injectivity: a DP match consumes one slot and one facing, so the mapping is injective by
  construction; rows map to distinct shelves, so it is injective per image.

`register_image`:
- Rows = sorted distinct `obs.slot.row`. Only the first `planogram.shelf_count` rows (top→bottom)
  are enumerated; extra rows get `RowRegistration(shelf=None, score=0.0, anchors=0, grade="low", assignments={})`.
- Candidates = `itertools.combinations(range(1, shelf_count + 1), n_rows)` (already increasing and
  lexicographic → the first best one *is* the "lowest shelf numbers" tie-break; keep strict `>` when comparing).
- Cache `align_row` per `(row, shelf)` — it is called for every pair once (≤ 36 calls for 6×6).
- `total = Σ row scores + prior`; prior = `+1` per adjacent row pair mapped to consecutive shelves,
  `+2` when `n_rows == shelf_count`.
- `runner_up_shelves` = the second-best tuple as a list aligned with `rows` (padded with `None`
  for non-enumerated rows); `margin = best_total − second_total`. When only one candidate exists
  (`n_rows == shelf_count`), both are `None`.
- Grade per row uses the **image** margin and the **row** anchors:
  `anchors == 0` or (`margin is not None and margin < 1`) → `"low"`;
  `anchors >= 2` and (`margin is None or margin >= 3`) → `"high"`; else `"medium"`.
  (`margin is None` means no alternative assignment exists, so it never lowers the grade.)
- Scores are rounded with `round(x, 4)` before being stored so the JSON is byte-stable.
- An image with no observations → `ImageRegistration(image_id=…, rows=[], total_score=0.0)`.

### Key Constraints
- Pure functions: no I/O, no logging of data at INFO (a single `logger.debug` per image is fine), no globals mutated.
- No `print`, strict type hints, Google-style docstrings, black line length 120.
- Do not change any signature below — they are fixed by spec §3 Module 8.

### References in Codebase
- `sdd/specs/new-planogram-compliance-algo.spec.md` §2 stage 6 + "Decided semantics", §7 "Few anchors on a row", "Ambiguous registration", "Neighbouring-fixture tags".

---

## Implementation Blueprint

> Write each block to its path nearly verbatim, then complete every `# FILL IN:` marker.
> Never change a signature, constant name or file path fixed here.

### Steps (in order)
1. Confirm `examples/planogram/plancheck/models.py` contains `SlotObservation`, `RowRegistration`, `ImageRegistration` (TASK-3338 landed) — *why*: every type here comes from it; if missing, stop and report instead of redefining models.
2. Create `registration.py` from parts 1–2 below — *why*: constants and signatures are normative; only the DP/enumeration bodies are yours.
3. Implement `pair_score` exactly in the 8-rule order above — *why*: rule order decides e.g. CLOSEOUT vs brand mismatch; tests assert exact floats.
4. Implement `align_row` as an O(n·m) DP with free planogram-side end gaps, then apply the pitch check on the traceback — *why*: the pitch penalty depends on which pairs were matched, so it cannot be folded into cell scores without changing the decided semantics.
5. Implement `register_image` with the per-(row, shelf) cache and `combinations` — *why*: lexicographic enumeration + strict `>` gives the mandated tie-break for free.
6. Implement `apply_registration` — *why*: downstream (verify, scoring) read `obs.facing_id` / `obs.registration_grade`, not the registration object.
7. Write the tests, run the validation command, then `ruff check` both files — *why*: TID251/format gate at merge.

### `examples/planogram/plancheck/registration.py` (CREATE) — part 1/2
```python
"""Deterministic registration of one photo against the planogram (FEAT-565, Module 8).

Pure functions: no I/O, no LLM, no ``parrot`` import. Same observations → identical result.
"""
from __future__ import annotations

import logging
from itertools import combinations

from plancheck.models import (
    Catalog,
    Grade,
    ImageRegistration,
    PlanogramFacing,
    PlanogramRef,
    RowRegistration,
    SlotObservation,
)

logger = logging.getLogger(__name__)

SCORE_SAME_SKU = 4.0
SCORE_CANDIDATE = 3.0
SCORE_BRAND_FAMILY = 2.0
SCORE_BRAND = 1.0
SCORE_NEUTRAL = 0.0
SCORE_OTHER_BRAND = -2.0
GAP_INTERIOR = -1.5
GAP_END_PLANOGRAM = 0.0
GAP_END_OBSERVED = -0.5
PITCH_TOLERANCE = 0.35
PITCH_PENALTY = -1.0
PRIOR_CONSECUTIVE = 1.0
PRIOR_FULL_HEIGHT = 2.0
MARGIN_HIGH = 3.0
MARGIN_LOW = 1.0
ANCHORS_HIGH = 2


def _norm(text: str | None) -> str | None:
    """Casefold/strip a brand or family token; ``None`` stays ``None``."""
    return text.casefold().strip() if text else None


def _observed_brand_family(obs: SlotObservation, catalog: Catalog) -> tuple[str | None, str | None]:
    """Brand/family of what was seen: catalog entry of ``resolved_sku`` if any, else the raw reading."""
    # FILL IN: prefer catalog.by_sku(obs.resolved_sku) when set and found; else obs.reading.brand/family;
    # return normalised values — bounded by "Operational reading → Observed brand/family".
    raise NotImplementedError


def pair_score(obs: SlotObservation, facing: PlanogramFacing, catalog: Catalog) -> float:
    """Score one observed slot against one expected facing (spec §2 score table).

    Args:
        obs: Pass-1 observation of the slot.
        facing: Expected planogram facing.
        catalog: Catalog used to look up brand/family of SKUs.

    Returns:
        One of +4, +3, +2, +1, 0, -2 following the 8-rule order of the task.
    """
    # FILL IN: the 8 rules, first match wins — bounded by "pair_score evaluation order" (rules 1-8).
    raise NotImplementedError


def _center_x(obs: SlotObservation) -> float:
    """Horizontal centre of the slot box in original pixels."""
    x1, _, x2, _ = obs.slot.box
    return (x1 + x2) / 2.0
```
**Why this shape**: every number of the decided score table is a named module constant so a
reviewer can diff them against spec §2 at a glance and tests can import them. `_norm` /
`_observed_brand_family` keep brand logic in one place without importing `reference.py`
(no dependency edge on TASK-3339). Do not rename constants or change their values.

### `examples/planogram/plancheck/registration.py` (CREATE) — part 2/2
```python
def align_row(
    row_obs: list[SlotObservation], facings: list[PlanogramFacing], catalog: Catalog, pitch: float
) -> tuple[float, dict[str, str], int]:
    """Semi-global, gap-tolerant alignment of one row against one shelf.

    Args:
        row_obs: Observations of ONE row of ONE image (any order; sorted here by ``slot.index``).
        facings: Expected facings of one shelf in physical order (``PlanogramRef.shelf``).
        catalog: Catalog for brand/family lookups.
        pitch: Median tag pitch of the row in original pixels (``<= 0`` disables the pitch check).

    Returns:
        ``(score, {slot_id: facing_id}, anchors)`` — score includes gap costs and pitch penalties;
        unmatched slots are absent from the mapping; ``anchors`` counts +4 matches.
    """
    # FILL IN: DP over (slots × facings): match = pair_score; skip-facing = GAP_END_PLANOGRAM at the
    #   ends of the facing sequence else GAP_INTERIOR; skip-slot = GAP_END_OBSERVED at the ends of the
    #   observed sequence else GAP_INTERIOR — bounded by "align_row" notes.
    # FILL IN: traceback with tie-break match > skip-facing > skip-slot; smallest facing index on ties.
    # FILL IN: pitch check on consecutive matched pairs with k >= 1 (PITCH_TOLERANCE, PITCH_PENALTY).
    # FILL IN: empty row_obs or empty facings → (0.0, {}, 0).
    raise NotImplementedError


def _grade(anchors: int, margin: float | None) -> Grade:
    """Row grade from its direct anchors and the image margin (``None`` = no alternative exists)."""
    if anchors == 0 or (margin is not None and margin < MARGIN_LOW):
        return "low"
    if anchors >= ANCHORS_HIGH and (margin is None or margin >= MARGIN_HIGH):
        return "high"
    return "medium"


def register_image(
    image_id: str,
    observations: list[SlotObservation],
    planogram: PlanogramRef,
    catalog: Catalog,
    pitches: dict[int, float],
) -> ImageRegistration:
    """Register every row of one image to a shelf and every slot to a facing.

    Args:
        image_id: Image whose observations are given.
        observations: All observations of that image (other images are ignored).
        planogram: Expected facings.
        catalog: Catalog for brand/family lookups.
        pitches: Row number → median tag pitch (missing row → 0.0, check disabled).

    Returns:
        The best order-preserving assignment with runner-up, margin and per-row grades.
    """
    # FILL IN: group by obs.slot.row (sorted); first shelf_count rows are enumerated, the rest unregistered.
    # FILL IN: cache align_row per (row, shelf); enumerate combinations(range(1, shelf_count+1), n_rows);
    #   total = Σ scores + PRIOR_CONSECUTIVE per consecutive pair + PRIOR_FULL_HEIGHT when n_rows == shelf_count;
    #   keep best with strict ">" and the second best — bounded by "register_image" notes.
    # FILL IN: build RowRegistration per row (round(score, 4)), ImageRegistration (round totals/margin).
    raise NotImplementedError


def apply_registration(observations: list[SlotObservation], registration: ImageRegistration) -> None:
    """Set ``facing_id`` and ``registration_grade`` in place for the registration's image.

    Slots of that image absent from every row mapping get ``facing_id = None`` and keep the
    grade of their row (``None`` when the row is unknown to the registration).
    """
    # FILL IN: build slot_id→(facing_id, grade) and row→grade; touch only obs.slot.image_id == registration.image_id.
    raise NotImplementedError
```
**Why this shape**: signatures are copied from spec §3 Module 8 and must not change. `_grade`
is complete because its thresholds are decided semantics (including the `margin is None`
reading when only one assignment exists). The DP, enumeration and traceback are the real work
and stay as bounded FILL INs.

### `examples/planogram/tests/test_plancheck_registration.py` (CREATE)
```python
"""Unit tests for plancheck.registration (FEAT-565, spec §4 — M8)."""
from __future__ import annotations

from plancheck.models import Catalog, PlanogramRef, Slot, SlotObservation, SlotReading
from plancheck.registration import align_row, apply_registration, pair_score, register_image

PITCH = 220.0


def _obs(image_id: str, row: int, index: int, *, sku: str | None = None, brand: str | None = None,
         family: str | None = None, occupancy: str = "occupied", x0: int | None = None) -> SlotObservation:
    """Build one observation; box x-centre advances one PITCH per index unless ``x0`` is given."""
    left = (index - 1) * int(PITCH) if x0 is None else x0
    slot = Slot(slot_id=f"{image_id}_r{row:02d}_s{index:02d}", image_id=image_id, row=row, index=index,
                box=(left, 0, left + 160, 200), origin="tag_anchored")
    reading = SlotReading(slot_id=slot.slot_id, occupancy=occupancy, visibility="full", brand=brand, family=family)
    return SlotObservation(slot=slot, reading=reading, resolved_sku=sku,
                           resolution="direct" if sku else "unresolved")


def test_pair_score_table(mini_planogram: PlanogramRef, mini_catalog: Catalog) -> None:
    # FILL IN: one assert per rule 1-8 (+4, +3, +2, +1, 0 no brand, 0 empty, 0 CLOSEOUT, -2).
    raise NotImplementedError


def test_align_row_partial_view(mini_planogram: PlanogramRef, mini_catalog: Catalog) -> None:
    # FILL IN: build a 17-facing shelf (extend a copy of the fixture or construct PlanogramFacing list),
    #   observe 6 consecutive slots from its middle with 2 direct anchors → all 6 mapped to the right
    #   facing_ids, score has NO end-gap penalty on the planogram side, anchors == 2.
    raise NotImplementedError


def test_register_rows_monotone(mini_planogram: PlanogramRef, mini_catalog: Catalog) -> None:
    # FILL IN: 2 rows whose anchors point to shelves (3, 1) respectively → result shelves strictly increasing.
    raise NotImplementedError


def test_register_disambiguates_by_family(mini_planogram: PlanogramRef, mini_catalog: Catalog) -> None:
    # FILL IN: one row, brands Acme,Acme,Acme,Bolt,Bolt,Bolt (identical on every shelf) with family "20"
    #   readings and one direct AC-2x anchor → shelf == 2.
    raise NotImplementedError


def test_register_grade_low_without_anchors(mini_planogram: PlanogramRef, mini_catalog: Catalog) -> None:
    # FILL IN: occupied slots with brand only, no resolved_sku → every RowRegistration.grade == "low".
    raise NotImplementedError


def test_registration_injective_per_image(mini_planogram: PlanogramRef, mini_catalog: Catalog) -> None:
    # FILL IN: 3 rows × 6 slots; after apply_registration the non-None facing_ids are all distinct,
    #   and a second register_image call returns model_dump_json() identical to the first (determinism).
    raise NotImplementedError
```
**Why this shape**: the five spec §4 M8 tests plus one table test for `pair_score`; the `_obs`
helper is complete so test bodies only express scenarios. Fixtures `mini_planogram` /
`mini_catalog` come from `examples/planogram/tests/conftest.py` (TASK-3337): 3 shelves × 6 slots,
slots 1–3 brand "Acme" (`AC-<shelf><slot>`, family `"10"/"20"/"30"`), slots 4–6 "Bolt"
(`BO-…`, family `"11"/"21"/"31"`), shelf 3 slot 6 = `CLOSEOUT` ×2 facings.

### FILL IN checklist
- [ ] `registration.py::_observed_brand_family` — catalog-first lookup; bounded by "Observed brand/family"
- [ ] `registration.py::pair_score` — 8 rules, first match wins; bounded by the rule list
- [ ] `registration.py::align_row` — DP + traceback tie-break + pitch check + empty inputs; bounded by "align_row" notes
- [ ] `registration.py::register_image` — grouping, cache, enumeration, prior, runner-up/margin, rounding; bounded by "register_image" notes
- [ ] `registration.py::apply_registration` — in-place update limited to the registration's image
- [ ] six test bodies — bounded by the comment in each stub

---

## Acceptance Criteria

- [ ] `pair_score` returns exactly +4 / +3 / +2 / +1 / 0 / −2 per the 8-rule order (CLOSEOUT and non-occupied → 0).
- [ ] `align_row` gives free leading/trailing gaps on the planogram side, −0.5 per leading/trailing unmatched slot, −1.5 per interior gap, −1 per pitch violation; unmatched slots are absent from the mapping.
- [ ] `register_image` never maps rows to non-increasing shelves; ties resolve to the lowest shelf numbers; runner-up and margin recorded (`None` when only one assignment exists).
- [ ] Grades follow the thresholds (`high`: margin ≥ 3 or None, and ≥ 2 anchors; `low`: margin < 1 or 0 anchors).
- [ ] No two slots of one image map to the same facing; two identical calls produce identical `model_dump_json()`.
- [ ] Module imports only stdlib + `plancheck.models` (no `parrot`, `cv2`, `numpy`, `reference`); no `print`.
- [ ] `pytest examples/planogram/tests/test_plancheck_registration.py -q` passes.
- [ ] `ruff check examples/planogram/plancheck/registration.py examples/planogram/tests/test_plancheck_registration.py` is clean.

---

## Validation Commands

- `pytest examples/planogram/tests/test_plancheck_registration.py -q`

---

## Test Specification

See the test blueprint block above — the six functions there are the required minimum
(`test_pair_score_table`, `test_align_row_partial_view`, `test_register_rows_monotone`,
`test_register_disambiguates_by_family`, `test_register_grade_low_without_anchors`,
`test_registration_injective_per_image`). Add cases for the pitch penalty and for
`n_rows > shelf_count` if time allows. Synthetic SKUs only — never copy real part numbers.

---

## Agent Instructions

1. **Read the spec** §2 stage 6 + "Decided semantics", §3 Module 8, §7.
2. **Check dependencies** — TASK-3338 must be in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — open `examples/planogram/plancheck/models.py` and confirm the field names listed above; if they differ, update this contract first.
4. **Update status** in `sdd/tasks/index/new-planogram-compliance-algo.json` → `"in-progress"`.
5. **Implement** from the blueprint; complete every `# FILL IN:`; never change a fixed signature or constant.
6. **Verify** all acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/TASK-3345-registration.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note**.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
