# TASK-3347: Multi-photo merge, position statuses, credits and metrics

**Feature**: FEAT-565 — New Planogram Compliance Algorithm
**Spec**: `sdd/specs/new-planogram-compliance-algo.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3338
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 10** / §2 stage 8 — the request's steps 4 and 5: compose the as-observed
planogram from every photo of the visit, compare it with the definition and score it. This
module turns registered `SlotObservation`s (all photos together) into one `PositionResult`
per **expected facing**, then into shelf scores, brand shares, the overall summary and —
only when a prices file was supplied — a separate price-compliance block.

It is where the feature's honesty rules live: strict vs lenient side by side,
`verified_by_expectation`/`inferred` never counted as strict, unseen (`not_visible`) and
seen-but-unknown (`not_assessed`) never reported as `empty`, low-grade registrations capped
at lenient credit, reference confidence reported as its own dimension, and price never
influencing a status.

---

## Scope

- Implement `merge_positions()`, `shelf_scores()`, `brand_shares()`, `summarize()` in
  `examples/planogram/plancheck/scoring.py` with the exact spec signatures. Pure functions.
- Write `examples/planogram/tests/test_plancheck_scoring.py` with the eight spec §4 M10 tests.

**NOT in scope**: registration (`plancheck/registration.py`, TASK-3345); pass 2
(`plancheck/verify.py`, TASK-3346); loading prices/catalog
(`plancheck/reference.py`, TASK-3339 — this module receives `dict[str, Decimal] | None`);
building `RunInfo` / `ComplianceReport` and `notes` (TASK-3349); JSON/annotated output (TASK-3348);
any model change (`examples/planogram/plancheck/models.py`, TASK-3337/3338).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/planogram/plancheck/scoring.py` | CREATE | Merge, status decision list, credits, metrics |
| `examples/planogram/tests/test_plancheck_scoring.py` | CREATE | Unit tests (spec §4, M10 rows) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from __future__ import annotations
import logging
from collections import defaultdict          # stdlib
from decimal import Decimal                   # stdlib
```

#### Created by dependency tasks (exist only after they land)
```python
# examples/planogram/plancheck/models.py — TASK-3337 (part 1) / TASK-3338 (part 2)
from plancheck.models import (
    Catalog, PlanogramFacing, PlanogramRef, PriceReading, Slot, SlotReading,      # TASK-3337
    SlotObservation, ScoringWeights, PositionResult, PositionStatus, Resolution,  # TASK-3338 (aliases in part 1)
    ShelfScore, BrandShare, PriceCompliance, ComplianceSummary,
)
```
Fixtures `mini_planogram`, `mini_catalog` come from `examples/planogram/tests/conftest.py` (TASK-3337).

### Existing Signatures to Use
Nothing importable in the repository today. The merge rules are *adapted* from
`examples/planogram/inkcheck/inkcheck/compare.py:24-47` (verified 2026-09-18: `def compare` at :6, the
reliable-view filter at :26-28). **That directory is git-ignored and absent from worktrees** — do not
open or import it; every rule you need is restated below.

Model fields used (fixed by spec §3 Module 1 — re-verify in `examples/planogram/plancheck/models.py`):
```python
class PlanogramFacing: facing_id; position; shelf; slot; facing; sku; brand: str | None
                       identity_required: bool; reference_read_method: str   # "direct" | "inferred" | "partial"
class SlotReading:     occupancy: "occupied"|"empty"|"uncertain"; visibility: "full"|"partial"|"unusable"
                       brand: str | None; family: str | None
class PriceReading:    raw: str | None; amount: Decimal | None; currency: str | None
                       source: "ocr"|"llm"|"none"; status: "read"|"partial"|"unreadable"|"not_assessed"|"conflict"
class SlotObservation: slot: Slot; reading: SlotReading | None; resolved_sku: str | None
                       candidate_skus: list[str]; resolution: Resolution; price: PriceReading
                       facing_id: str | None; registration_grade: "high"|"medium"|"low" | None
class ScoringWeights:  misplaced=0.5; variant_unresolved=0.5; inferred_present=0.5; verified_by_expectation=1.0
class PositionResult:  facing; status; resolution: Resolution | None; strict_credit: float; lenient_credit: float
                       observed_sku; observed_brand; price: PriceReading | None
                       price_expected: Decimal | None; price_match: bool | None; slot_ids: list[str]
class ShelfScore:      shelf; expected; covered; decided; strict_pct; lenient_pct; occupancy_pct; empty_facing_ids
class BrandShare:      brand; expected_facings; expected_share; observed_facings; observed_share; linear_share; occupancy_pct
class PriceCompliance: compared; matched; match_pct; mismatches; skus_missing_from_prices; unknown_price_skus
class ComplianceSummary: strict_pct; lenient_pct; coverage; occupancy_pct; products_expected; products_present
                       unexpected_skus; price: PriceCompliance | None
                       reference_direct_facings; strict_pct_direct_reference; lenient_pct_direct_reference
```

### Does NOT Exist
- ~~`import inkcheck` / `from inkcheck.compare import compare`~~ — not a package on the path; ignored directory.
- ~~`mapping_reviewed` / `reviewed` flags~~ — inkcheck semantics, deliberately NOT carried over; every registered observation counts.
- ~~`PositionStatus` values `identity_unknown` / `unknown`~~ — inkcheck names; the FEAT-565 literals are the ten listed below.
- ~~price influencing `status` or credits~~ — price never changes a position status (spec §5).
- ~~`weights` parameter on `summarize`/`shelf_scores`~~ — credits are already stored on each `PositionResult`.
- ~~`parrot`, `cv2`, `numpy`, `rapidfuzz` imports~~ — pure module: stdlib + `plancheck.models` only.
- ~~float arithmetic on prices~~ — compare `Decimal` amounts only, never raw strings.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "examples/planogram/plancheck/scoring.py",
      "action": "CREATE"
    },
    {
      "path": "examples/planogram/tests/test_plancheck_scoring.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Normative rules (spec §2 "Decided semantics" — verbatim; do NOT re-decide)

> **Position status** for facing F expecting SKU S (after multi-photo merge):
> - `not_visible` — no registered slot maps to F in any photo (**unseen** fixture area).
> - `not_assessed` — a slot maps to F but every view is `uncertain`/`unusable` or its
>   row call failed (**seen but unknown**). Unseen and unknown are never reported as `empty`.
> - `conflict` — reliable views disagree (occupied vs empty, or two different
>   `direct` SKUs). An `uncertain`/unresolved view never erases a positive one;
>   agreeing views count once.
> - `empty` — slot empty with `visibility = full` (an `empty` claim with partial
>   visibility is downgraded to `uncertain` → treated as not assessed).
> - `match` — slot resolved to S (`direct` or `verified_by_expectation`).
> - `misplaced` — F's own slot is not a match, but S is observed `direct` in
>   another registered slot of the **same shelf** whose own facing it does not match.
> - `variant_unresolved` — occupied, `ambiguous` with S ∈ candidates, or brand +
>   family equal to S's catalog entry with the variant unread.
> - `mismatch` — occupied and resolved to a different SKU, or observed brand
>   differs from the expected brand.
> - `inferred_present` — occupied, registered, unresolved, brand absent or equal.
> - `occupied_unassigned` — occupied facing with `identity_required = false` (CLOSEOUT).
>
> **Credits.** Strict: `match` via `direct` = 1, everything else 0. Lenient:
> `match` (`direct`) 1 · `match` (`verified_by_expectation`) `w.verified_by_expectation`
> (default 1.0) · `misplaced` `w.misplaced` (0.5) · `variant_unresolved` (0.5) ·
> `inferred_present` (0.5) · others 0. Rows graded `low` contribute 0 to strict.
> Weights live in `ScoringWeights` and are overridable from the CLI settings.
>
> **Metrics.** `coverage` = facings not in {`not_visible`, `not_assessed`, `conflict`} / all
> facings. `strict_pct`, `lenient_pct` = Σ credits / decided SKU-specific facings
> (decided = `identity_required` and covered). `occupancy_pct` = occupied /
> (occupied + empty). Undefined ratios are `null`. Brand share: expected facings
> share vs observed facings share (observed brand; unknown bucket kept) vs
> **linear share** (slot widths normalised by their row's total slot width).
> Price compliance (only with `--prices`): over facings with `match` and a `read`
> price — equal `Decimal` amounts = match; SKUs missing from either side are listed.
> Cross-photo price agreement compares **normalised amounts**, never raw strings;
> different amounts → price `conflict` with every raw reading retained.
> **Reference confidence** is a separate dimension: `strict_pct_direct_reference` /
> `lenient_pct_direct_reference` repeat the two scores over facings whose planogram
> entry was read `direct` […].

### Operational reading (fixed for this task)

**Views.** Views of F = every observation (any photo) with `obs.facing_id == F.facing_id`;
`PositionResult.slot_ids` lists ALL of them (sorted), whatever their quality. A view is *reliable*
when `reading is not None`, `visibility != "unusable"`, and (`occupancy == "occupied"` or
(`occupancy == "empty"` and `visibility == "full"`)). Everything else is an unknown view.

**Decision list — evaluate in this order, first hit wins:**
1. no views → `not_visible`.
2. no reliable view → `not_assessed`.
3. reliable views contain both occupied and empty, **or** ≥ 2 distinct `resolved_sku` among views with `resolution == "direct"` → `conflict`.
4. all reliable views empty → `empty`.
5. (occupied from here) `not F.identity_required` → `occupied_unassigned`.
6. a `direct` view resolved to S → `match`, `resolution="direct"`; else, if **no** view is `direct` to another SKU and a `verified_by_expectation` view resolved to S → `match`, `resolution="verified_by_expectation"` (direct evidence outranks expectation-assisted evidence).
7. S is resolved `direct` by an observation registered to a **different facing of the same shelf** whose own expected SKU ≠ S → `misplaced`.
8. a view is `ambiguous` with S ∈ `candidate_skus`, **or** an unresolved/ambiguous/inferred view has observed brand == expected brand and observed family == `catalog.by_sku(S).family` (both non-null) → `variant_unresolved`.
9. a view resolved (`direct` or `verified_by_expectation`) to a SKU ≠ S, **or** observed brand present and ≠ expected brand → `mismatch`.
10. otherwise (occupied, `resolution in {"unresolved", "inferred", "ambiguous"}`, brand absent or equal) → `inferred_present`.

`PositionResult.resolution` = the resolution of the view that decided the status (None for statuses 1–5).
`observed_sku` = the deciding view's `resolved_sku` (None when unresolved). `observed_brand` = catalog
brand of `observed_sku` when known, else the deciding view's `reading.brand`. Brands/families compare
with `.casefold().strip()`.

**Credits.** `lenient_credit` per the table using `weights`. `strict_credit = 1.0` only when status is
`match`, resolution is `direct`, **and at least one `direct` matching view has
`registration_grade != "low"`**; else `0.0`. Low-grade rows still earn lenient credit.
Facings with `identity_required == False` always have both credits `0.0` (they are outside the SKU denominators).

**Price merge per facing.** Among views whose `price.status == "read"`: one distinct `amount` →
that `PriceReading` (first by sorted `slot_id`); several distinct amounts →
`PriceReading(raw=" | ".join(all raws, sorted by slot_id), amount=None, currency=None, source=<first's>, status="conflict")`.
No `read` view: the best of `partial` > `unreadable` > `not_assessed` (first by `slot_id`); no views → `None`.
`price_expected = prices.get(F.sku)` when `prices` is given. `price_match = (amount == price_expected)`
only when status is `match`, price status is `read` and `price_expected is not None`; otherwise `None`.

**Units.** Every `*_pct` field is a percentage `0.0–100.0` rounded to 2 decimals. `coverage` and every
`*_share` field are fractions `0.0–1.0` rounded to 4 decimals. Undefined ratio (zero denominator) → `None`
(`coverage` with zero facings → `0.0`).

**Sets.** covered = status ∉ {`not_visible`, `not_assessed`, `conflict`}. decided = covered ∧ `identity_required`.
occupied = status ∈ {`match`, `misplaced`, `variant_unresolved`, `mismatch`, `inferred_present`, `occupied_unassigned`}.

**`shelf_scores`** — one `ShelfScore` per shelf number present in `positions`, ascending:
`expected` = facings on the shelf; `strict_pct`/`lenient_pct` = 100·Σcredits/decided; `occupancy_pct` =
100·occupied/(occupied+empty); `empty_facing_ids` sorted.

**`brand_shares`** — brands sorted by name; `None` brand → bucket `"unknown"`.
`expected_facings`/`expected_share` from **all** planogram facings by `F.brand`.
`observed_facings` = occupied positions grouped by `observed_brand` (None → `"unknown"`);
`observed_share` = that / all occupied positions. `linear_share`: for each occupied position take its
first `slot_id` (sorted) → `w = slot_width / Σ widths of every slot observed in the same (image_id, row)`;
brand linear share = Σw(brand) / Σw(all occupied positions) (using one slot per position avoids double
counting overlapping photos). `occupancy_pct` per brand = 100·occupied/(occupied+empty) over the
positions whose **expected** brand is that brand. A brand only observed (not expected) still gets a row
with `expected_facings = 0`.

**`summarize`** — `coverage`; `strict_pct`/`lenient_pct` over decided; `occupancy_pct`;
`products_expected` = distinct identity-required SKUs; `products_present` = distinct expected SKUs with a
position in {`match`, `misplaced`}; `unexpected_skus` = sorted SKUs resolved `direct`/`verified_by_expectation`
by ANY observation (registered or not) that are not expected anywhere in the planogram;
`reference_direct_facings` = facings with `reference_read_method == "direct"`; the two
`*_direct_reference` percentages = same formulas over decided ∩ direct-reference facings.
`price` is `None` when `prices is None`; else `PriceCompliance`: `compared` = positions with
`price_match is not None`; `matched`; `match_pct`; `mismatches` = sorted facing_ids with
`price_match is False`; `skus_missing_from_prices` = identity-required planogram SKUs absent from
`prices` (sorted); `unknown_price_skus` = keys of `prices` not in the planogram (sorted).

### Key Constraints
- Pure functions; deterministic output order (positions in `planogram.facings` order; sorted lists everywhere).
- Do not mutate inputs. No `print`. Strict type hints, Google-style docstrings, black 120.
- Signatures are fixed by spec §3 Module 10.

### References in Codebase
- `sdd/specs/new-planogram-compliance-algo.spec.md` §2 "Decided semantics", §5 (scoring criteria), §7 "Multi-facing CLOSEOUT", "Price conflicts".

---

## Implementation Blueprint

### Steps (in order)
1. Confirm part 2 of `examples/planogram/plancheck/models.py` (TASK-3338) is present — *why*: all result models come from it.
2. Create `scoring.py` from parts 1–2 — *why*: the status sets, helper names and public signatures are fixed; decision logic is yours.
3. Implement `_is_reliable`, `_merge_price`, then `_decide` strictly as the 10-step list — *why*: order IS the semantics (e.g. `empty` precedes `misplaced`, so `misplaced` implies occupied).
4. Build the same-shelf "direct elsewhere" index once in `merge_positions` before looping facings — *why*: `misplaced` needs a global view of the shelf, and doing it per facing would be O(n²).
5. Implement credits incl. the low-grade strict cap — *why*: §5 requires `verified_by_expectation`/`inferred`/low rows to contribute 0 to strict.
6. Implement `shelf_scores`, `brand_shares`, `summarize` using the shared `_pct`/`_share` helpers — *why*: one rounding/None policy for every metric.
7. Write the tests, run the validation command, `ruff check` both files.

### `examples/planogram/plancheck/scoring.py` (CREATE) — part 1/2
```python
"""Multi-photo merge, position statuses, credits and metrics (FEAT-565, Module 10).

Pure functions — no I/O, no LLM, no ``parrot`` import. Price never influences a status.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from decimal import Decimal

from plancheck.models import (
    BrandShare,
    Catalog,
    ComplianceSummary,
    PlanogramFacing,
    PlanogramRef,
    PositionResult,
    PositionStatus,
    PriceCompliance,
    PriceReading,
    Resolution,
    ScoringWeights,
    ShelfScore,
    SlotObservation,
)

logger = logging.getLogger(__name__)

UNCOVERED: frozenset[str] = frozenset({"not_visible", "not_assessed", "conflict"})
OCCUPIED: frozenset[str] = frozenset(
    {"match", "misplaced", "variant_unresolved", "mismatch", "inferred_present", "occupied_unassigned"}
)
UNKNOWN_BRAND = "unknown"


def _pct(numerator: float, denominator: float) -> float | None:
    """Percentage 0–100 rounded to 2 decimals; ``None`` when the denominator is 0."""
    return round(100.0 * numerator / denominator, 2) if denominator else None


def _share(numerator: float, denominator: float) -> float | None:
    """Fraction 0–1 rounded to 4 decimals; ``None`` when the denominator is 0."""
    return round(numerator / denominator, 4) if denominator else None


def _norm(text: str | None) -> str | None:
    """Casefold/strip a brand or family token; ``None`` stays ``None``."""
    return text.casefold().strip() if text else None


def _is_reliable(obs: SlotObservation) -> bool:
    """Occupied with usable visibility, or empty with FULL visibility."""
    # FILL IN: bounded by "Views" — reading None / unusable / uncertain / empty+partial are NOT reliable.
    raise NotImplementedError


def _merge_price(views: list[SlotObservation]) -> PriceReading | None:
    """Merge tag prices of one facing across photos by normalised Decimal amount."""
    # FILL IN: bounded by "Price merge per facing" — conflict keeps every raw, joined with " | ".
    raise NotImplementedError


def _decide(
    facing: PlanogramFacing,
    views: list[SlotObservation],
    catalog: Catalog,
    direct_elsewhere_on_shelf: bool,
) -> tuple[PositionStatus, Resolution | None, SlotObservation | None]:
    """Apply the 10-step decision list. Returns (status, deciding resolution, deciding view)."""
    # FILL IN: steps 1-10 in order, first hit wins — bounded by "Decision list".
    raise NotImplementedError


def _credits(status: PositionStatus, resolution: Resolution | None, facing: PlanogramFacing,
             views: list[SlotObservation], weights: ScoringWeights) -> tuple[float, float]:
    """Return (strict_credit, lenient_credit)."""
    # FILL IN: bounded by "Credits" — strict needs a direct matching view with registration_grade != "low";
    # identity_required False → (0.0, 0.0).
    raise NotImplementedError
```
**Why this shape**: the status sets and the two rounding helpers are complete because the
units/denominators are decided; keeping them as module constants lets `report.py` and tests reuse
them. `_decide` returns the deciding view so `observed_sku`/`observed_brand`/`resolution` are
derived in one place.

### `examples/planogram/plancheck/scoring.py` (CREATE) — part 2/2
```python
def merge_positions(
    planogram: PlanogramRef,
    observations: list[SlotObservation],
    catalog: Catalog,
    weights: ScoringWeights,
    prices: dict[str, Decimal] | None,
) -> list[PositionResult]:
    """One result per expected facing using the §2 status decision list and credits.

    Args:
        planogram: Expected facings (output keeps this order).
        observations: Registered and unregistered observations of ALL photos of the visit.
        catalog: Catalog for brand/family lookups.
        weights: Lenient partial-credit weights.
        prices: Optional ``sku → expected price``; only fills ``price_expected`` / ``price_match``.

    Returns:
        ``len(planogram.facings)`` results; ``slot_ids`` lists every contributing view.
    """
    # FILL IN: group views by facing_id; index {(shelf, sku)} of skus resolved "direct" by observations whose
    #   own facing (same shelf) expects a different sku → direct_elsewhere_on_shelf; loop facings; build
    #   PositionResult with _decide/_credits/_merge_price — bounded by steps 3-5 and "Price merge".
    raise NotImplementedError


def shelf_scores(positions: list[PositionResult]) -> list[ShelfScore]:
    """Per-shelf expected/covered/decided counts, strict %, lenient %, occupancy %, empty facings."""
    # FILL IN: bounded by "shelf_scores" notes (ascending shelf, _pct, sorted empty_facing_ids).
    raise NotImplementedError


def brand_shares(
    planogram: PlanogramRef, positions: list[PositionResult], observations: list[SlotObservation]
) -> list[BrandShare]:
    """Expected share vs observed facings share vs linear share, and occupancy %, per brand."""
    # FILL IN: bounded by "brand_shares" notes — UNKNOWN_BRAND bucket, one slot per position for linear share,
    #   row total width = Σ widths of every observed slot with the same (image_id, row).
    raise NotImplementedError


def summarize(
    positions: list[PositionResult],
    observations: list[SlotObservation],
    planogram: PlanogramRef,
    prices: dict[str, Decimal] | None,
) -> ComplianceSummary:
    """Overall strict/lenient %, coverage, occupancy, products, unexpected SKUs, reference-confidence
    metrics and (only when ``prices`` is given) the price-compliance block."""
    # FILL IN: bounded by "summarize" notes — price is None when prices is None.
    raise NotImplementedError
```
**Why this shape**: the four public signatures are copied from spec §3 Module 10 and must not
change. Everything inside is bounded by the operational notes; no new public names are needed.

### `examples/planogram/tests/test_plancheck_scoring.py` (CREATE)
```python
"""Unit tests for plancheck.scoring (FEAT-565, spec §4 — M10)."""
from __future__ import annotations

from decimal import Decimal

from plancheck.models import (Catalog, PlanogramRef, PriceReading, ScoringWeights, Slot, SlotObservation,
                              SlotReading)
from plancheck.scoring import brand_shares, merge_positions, shelf_scores, summarize


def _obs(image_id: str, row: int, index: int, facing_id: str | None, *, occupancy: str = "occupied",
         visibility: str = "full", sku: str | None = None, resolution: str = "unresolved",
         candidates: tuple[str, ...] = (), brand: str | None = None, family: str | None = None,
         grade: str | None = "high", price: PriceReading | None = None) -> SlotObservation:
    """Build one observation with a 160-px-wide slot box."""
    left = (index - 1) * 220
    slot = Slot(slot_id=f"{image_id}_r{row:02d}_s{index:02d}", image_id=image_id, row=row, index=index,
                box=(left, 0, left + 160, 200), origin="tag_anchored")
    reading = SlotReading(slot_id=slot.slot_id, occupancy=occupancy, visibility=visibility, brand=brand, family=family)
    return SlotObservation(slot=slot, reading=reading, resolved_sku=sku, candidate_skus=list(candidates),
                           resolution=resolution, facing_id=facing_id, registration_grade=grade,
                           price=price or PriceReading())


def test_status_decision_table(mini_planogram: PlanogramRef, mini_catalog: Catalog) -> None:
    # FILL IN: one facing per status — all ten PositionStatus values appear exactly as the decision list says
    #   (incl. CLOSEOUT → occupied_unassigned, misplaced on the same shelf only).
    raise NotImplementedError


def test_merge_conflict_and_agreeing_views(mini_planogram: PlanogramRef, mini_catalog: Catalog) -> None:
    # FILL IN: two photos: occupied vs empty(full) → conflict; two different direct skus → conflict;
    #   two agreeing direct views → one match with both slot_ids retained; unknown view does not erase a match.
    raise NotImplementedError


def test_merge_price_conflict_uses_amounts(mini_planogram: PlanogramRef, mini_catalog: Catalog) -> None:
    # FILL IN: raws "$45.99" and "45.99" (both amount Decimal("45.99")) agree → status "read";
    #   45.99 vs 46.99 → price.status == "conflict", amount None, both raws in price.raw; position status unchanged.
    raise NotImplementedError


def test_not_assessed_vs_not_visible_vs_empty(mini_planogram: PlanogramRef, mini_catalog: Catalog) -> None:
    # FILL IN: uncertain/unusable view → not_assessed; no view → not_visible; empty+partial → not_assessed;
    #   none of them is "empty" and none enters coverage/occupancy/compliance denominators.
    raise NotImplementedError


def test_direct_reference_metrics(mini_planogram: PlanogramRef, mini_catalog: Catalog) -> None:
    # FILL IN: fixture shelf 2 is read "inferred": matches only on shelf 2 → strict_pct > 0 while
    #   strict_pct_direct_reference == 0.0; reference_direct_facings counts shelves 1 and 3 only.
    raise NotImplementedError


def test_strict_vs_lenient_credits(mini_planogram: PlanogramRef, mini_catalog: Catalog) -> None:
    # FILL IN: verified_by_expectation match → strict 0 / lenient 1.0; direct match on a "low" row → strict 0 /
    #   lenient 1.0; misplaced / variant_unresolved / inferred_present → 0.5 each; custom ScoringWeights honoured.
    raise NotImplementedError


def test_coverage_excludes_not_visible(mini_planogram: PlanogramRef, mini_catalog: Catalog) -> None:
    # FILL IN: observe one shelf only → coverage == observed_facings/total (fraction 0–1), strict_pct computed over
    #   decided facings only (0–100), shelf_scores of unobserved shelves have None percentages.
    raise NotImplementedError


def test_price_compliance_optional(mini_planogram: PlanogramRef, mini_catalog: Catalog) -> None:
    # FILL IN: prices=None → summary.price is None and every price_match is None; with prices → compared/matched,
    #   mismatches (facing ids), skus_missing_from_prices, unknown_price_skus; statuses identical in both runs.
    raise NotImplementedError


def test_brand_shares_linear_and_unknown_bucket(mini_planogram: PlanogramRef, mini_catalog: Catalog) -> None:
    # FILL IN: shares sum to 1.0 (±1e-3); brand None → "unknown"; overlapping photos do not double-count linear share.
    raise NotImplementedError
```
**Why this shape**: the eight spec §4 M10 tests plus one for brand shares; `_obs` is complete so
bodies only describe scenarios. Fixture facts (TASK-3337 conftest): 3 shelves × 6 slots, slots 1–3
"Acme" `AC-<shelf><slot>` (family `"10"/"20"/"30"`), slots 4–6 "Bolt" `BO-<shelf><slot>`
(`"11"/"21"/"31"`), shelf 3 slot 6 = `CLOSEOUT` ×2 (brand None), facing ids `p{position:03d}_f{k}`,
shelf 2 `reference_read_method = "inferred"`, others `"direct"`; 19 facings.

### FILL IN checklist
- [ ] `scoring.py::_is_reliable` — bounded by "Views"
- [ ] `scoring.py::_merge_price` — Decimal amounts, conflict keeps all raws; bounded by "Price merge per facing"
- [ ] `scoring.py::_decide` — 10 steps in order; bounded by "Decision list"
- [ ] `scoring.py::_credits` — strict cap for low-grade rows, CLOSEOUT → 0/0; bounded by "Credits"
- [ ] `scoring.py::merge_positions` — grouping, same-shelf direct index, result assembly
- [ ] `scoring.py::shelf_scores` / `brand_shares` / `summarize` — bounded by their notes and "Units"
- [ ] nine test bodies — bounded by the comment in each stub

---

## Acceptance Criteria

- [ ] `merge_positions` returns exactly one `PositionResult` per planogram facing, in planogram order, with every contributing `slot_id`.
- [ ] All ten statuses are produced per the decision list; `not_visible` and `not_assessed` are distinct, never `empty`, and excluded from coverage / occupancy / compliance denominators.
- [ ] Conflicting reliable views → `conflict`; agreeing views count once; an unknown view never erases a positive one.
- [ ] Strict credit only for `direct` matches on non-`low` rows; `verified_by_expectation`, `inferred`, `misplaced`, `variant_unresolved` contribute 0 to strict; lenient uses `ScoringWeights`.
- [ ] `*_pct` are 0–100 (2 dp), `coverage`/`*_share` are 0–1 (4 dp), undefined ratios are `None`.
- [ ] Direct-reference metrics restrict the same formulas to `reference_read_method == "direct"` facings.
- [ ] Price: amounts compared as `Decimal`; differing amounts → price `conflict` with all raws; `summary.price is None` without prices; price never changes a status or credit.
- [ ] Module imports only stdlib + `plancheck.models`; inputs are not mutated; no `print`.
- [ ] `pytest examples/planogram/tests/test_plancheck_scoring.py -q` passes; `ruff check` on both files is clean.

---

## Validation Commands

- `pytest examples/planogram/tests/test_plancheck_scoring.py -q`

---

## Test Specification

See the test blueprint block above; the nine functions are the required minimum. Synthetic SKUs
from the conftest fixtures only.

---

## Agent Instructions

1. **Read the spec** §2 "Decided semantics" (Position status, Credits, Metrics), §3 Module 10, §5, §7.
2. **Check dependencies** — TASK-3338 must be in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — confirm the model fields in `examples/planogram/plancheck/models.py`; update this contract first if they differ.
4. **Update status** in `sdd/tasks/index/new-planogram-compliance-algo.json` → `"in-progress"`.
5. **Implement** from the blueprint; complete every `# FILL IN:`; never change a fixed signature.
6. **Verify** all acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/TASK-3347-scoring.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note**.

---

## Completion Note

**Completed by**: sdd-coder (backend nova, model qwen.qwen3-coder-480b-a35b-instruct, attempt_uid aed98fd46ded4b4ba0fb49a4458648ed)
**Date**: 2026-09-17
**Notes**: Created `examples/planogram/plancheck/scoring.py` (10-step position-status
decision list, strict/lenient credit calculations, merge_positions, shelf scores,
brand shares, summary stats) and `examples/planogram/tests/test_plancheck_scoring.py`.
A prior attempt on this task (mistral, attempt_uid ce80b352b7d442aa8a1651c3fd12b1c8)
failed with an API timeout before producing files; this seat's retry completed cleanly.
`ruff check` clean, engine lint autofix commit `5d6888f44`. Post-merge full suite →
64 passed. Review recorded: `coder-review:4465ab5d2c807f9fa1f6f9de`, no corrections
needed.

**Seat**: qwen · Backend: nova · Model: qwen.qwen3-coder-480b-a35b-instruct · Attempts: 2 (1 timeout retry) · Duration: 256.7s · Tokens: 1161296/22469

**Deviations from spec**: none
