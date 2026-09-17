# TASK-3338: Fusion, result and config models

**Feature**: FEAT-565 — New Planogram Compliance Algorithm
**Spec**: `sdd/specs/new-planogram-compliance-algo.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3337
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1 (second half). Appends to `examples/planogram/plancheck/models.py` (created by
TASK-3337) the models that carry fused evidence, registration, scoring results, the final report
and the run settings. `compliance.json` is `ComplianceReport.model_dump(mode="json")`, so these
classes ARE the output schema of the feature.

---

## Scope

- Append to `models.py`, below TASK-3337's marker comment: `SlotObservation`, `RowRegistration`,
  `ImageRegistration`, `ScoringWeights`, `PositionResult`, `ShelfScore`, `BrandShare`,
  `PriceCompliance`, `ComplianceSummary`, `ImageInfo`, `RunInfo`, `ComplianceReport`, `Settings`.
- Create `examples/planogram/tests/test_plancheck_models_results.py`.

**NOT in scope**: changing any model of part 1; any logic (status decisions live in `scoring.py`,
TASK-3347); `conftest.py` (owned by TASK-3337 — do not edit it).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/planogram/plancheck/models.py` | MODIFY | Append part 2 below the `# --- part 2 (TASK-3338)…` marker |
| `examples/planogram/tests/test_plancheck_models_results.py` | CREATE | JSON round-trip, defaults, strictness |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from __future__ import annotations
from decimal import Decimal
from typing import Literal
from pydantic import Field, ValidationError      # pydantic v2
import pytest
```

### Existing Signatures to Use
#### Created by dependency tasks (exist only after they land)
```python
# examples/planogram/plancheck/models.py  — TASK-3337
Box, Grade, PositionStatus, PriceStatus, Resolution          # type aliases
class StrictModel(BaseModel)                                  # extra="forbid"
class PlanogramFacing(StrictModel)                            # facing_id, position, shelf, segment, slot, segment_slot, facing, sku, brand, …
class Slot(StrictModel)                                       # slot_id, image_id, row, index, box, tag_id, tag_box, origin
class SlotReading(StrictModel)                                # pass-1 contract
class PriceReading(StrictModel)                               # raw, amount: Decimal | None, currency, source, status
# last line of the file after TASK-3337:
# --- part 2 (TASK-3338): fusion, result and config models ---
# examples/planogram/tests/conftest.py — TASK-3337: fixtures mini_planogram, mini_catalog (read-only for this task)
```

### Does NOT Exist
- ~~a `reviewed` / `mapping_reviewed` flag~~ — registration is always automatic; `RunInfo.registration_method` is the constant `"auto_alignment"` (design research S6).
- ~~`verify_pass: bool = True`~~ — it is `bool | None = None` (None = auto: on for cloud, off for local; spec §8 Q4).
- ~~a default for `Settings.cache_dir` / `output` / `catalog`~~ — required fields; the CLI (TASK-3350) supplies them.
- ~~status logic in models~~ — no validators computing statuses or credits here.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "examples/planogram/plancheck/models.py", "action": "MODIFY"},
    {"path": "examples/planogram/tests/test_plancheck_models_results.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- Append only; do not reorder or edit part 1. Keep the marker comment line in place (above the new code).
- One field per line, class docstrings, black line-length 120. No new imports are needed beyond what part 1 already imports (`Decimal`, `Literal`, `Field`).
- `Decimal` fields must survive `model_dump(mode="json")` → `model_validate` (pydantic serialises them as strings).

---

## Implementation Blueprint

### Steps (in order)
1. Confirm the anchor exists exactly once: `grep -c '^# --- part 2 (TASK-3338)' examples/planogram/plancheck/models.py` → `1` — *why*: a missing anchor means TASK-3337 is not merged into your base; STOP.
2. Append the two blocks below after the anchor — *why*: field names are the `compliance.json` schema and a cross-task contract.
3. Write the tests and make them pass.

### `examples/planogram/plancheck/models.py` (MODIFY — block 1/2)
```python
# occurrences: 1 (by construction — TASK-3337 writes this marker as the file's last line; re-verify with
#   grep -c '^# --- part 2 (TASK-3338)' examples/planogram/plancheck/models.py)
# AFTER — insert below `# --- part 2 (TASK-3338): fusion, result and config models ---`


class SlotObservation(StrictModel):
    """Everything known about one slot of one photo after perception, resolution and registration."""

    slot: Slot
    reading: SlotReading | None = None
    resolved_sku: str | None = None
    candidate_skus: list[str] = Field(default_factory=list)
    resolution: Resolution = "unresolved"
    price: PriceReading = Field(default_factory=PriceReading)
    facing_id: str | None = None  # None = unregistered
    registration_grade: Grade | None = None
    issues: list[str] = Field(default_factory=list)


class RowRegistration(StrictModel):
    """Alignment of one visible row to one planogram shelf."""

    image_id: str
    row: int
    shelf: int | None
    score: float
    anchors: int
    grade: Grade
    assignments: dict[str, str]  # slot_id -> facing_id


class ImageRegistration(StrictModel):
    """Best row→shelf assignment of one photo, with the runner-up for auditability."""

    image_id: str
    rows: list[RowRegistration]
    total_score: float
    runner_up_shelves: list[int | None] | None = None
    margin: float | None = None


class ScoringWeights(StrictModel):
    """Lenient-score partial credits (spec §8 Q2)."""

    misplaced: float = 0.5
    variant_unresolved: float = 0.5
    inferred_present: float = 0.5
    verified_by_expectation: float = 1.0


class PositionResult(StrictModel):
    """Merged verdict for one expected facing."""

    facing: PlanogramFacing
    status: PositionStatus
    resolution: Resolution | None = None
    strict_credit: float
    lenient_credit: float
    observed_sku: str | None = None
    observed_brand: str | None = None
    price: PriceReading | None = None
    price_expected: Decimal | None = None
    price_match: bool | None = None
    slot_ids: list[str] = Field(default_factory=list)


class ShelfScore(StrictModel):
    """Per-shelf metrics. ``*_pct`` are percentages 0–100 (2 dp); ``None`` when the denominator is 0."""

    shelf: int
    expected: int
    covered: int
    decided: int
    strict_pct: float | None
    lenient_pct: float | None
    occupancy_pct: float | None
    empty_facing_ids: list[str]


class BrandShare(StrictModel):
    """Expected vs observed share of one brand (facings and linear)."""

    brand: str
    expected_facings: int
    expected_share: float
    observed_facings: int
    observed_share: float | None
    linear_share: float | None
    occupancy_pct: float | None
```
**Why this shape**: verbatim from spec §3 Module 1. `anchors`, `margin`, `runner_up_shelves` exist so an
automatic registration is auditable (S6). Units (spec §2 Metrics): every `*_pct` is a percentage 0–100 rounded to
2 decimals; `coverage` and every `*_share` are fractions 0–1 rounded to 4 decimals. Models do not enforce this —
`scoring.py` (TASK-3347) produces the values.

### `examples/planogram/plancheck/models.py` (MODIFY — block 2/2, append below block 1)
```python
class PriceCompliance(StrictModel):
    """Only present when ``--prices`` was supplied."""

    compared: int
    matched: int
    match_pct: float | None
    mismatches: list[str]
    skus_missing_from_prices: list[str]
    unknown_price_skus: list[str]


class ComplianceSummary(StrictModel):
    """Headline numbers; the ``*_direct_reference`` fields restrict to facings read ``direct`` in the planogram."""

    strict_pct: float | None
    lenient_pct: float | None
    coverage: float
    occupancy_pct: float | None
    products_expected: int
    products_present: int
    unexpected_skus: list[str]
    price: PriceCompliance | None = None
    reference_direct_facings: int
    strict_pct_direct_reference: float | None
    lenient_pct_direct_reference: float | None


class ImageInfo(StrictModel):
    """One input photo and what was found in it."""

    image_id: str
    path: str
    sha256: str
    width: int
    height: int
    tag_rows: int
    tags: int
    slots: int
    registration: ImageRegistration | None = None


class RunInfo(StrictModel):
    """Run metadata."""

    visit_id: str
    planogram_id: str
    llm: str
    ocr_llm: str
    verify_pass: bool
    started_at: str
    finished_at: str
    errors: list[str]
    catalog_missing_skus: list[str]
    registration_method: Literal["auto_alignment"] = "auto_alignment"
    reference_provisional: bool = True
    local_ocr_available: bool = True


class ComplianceReport(StrictModel):
    """The ``compliance.json`` document."""

    run: RunInfo
    images: list[ImageInfo]
    slots: list[SlotObservation]
    positions: list[PositionResult]
    shelves: list[ShelfScore]
    brands: list[BrandShare]
    compliance: ComplianceSummary
    notes: list[str]


class Settings(StrictModel):
    """Resolved run settings (all paths absolute by the time this is built)."""

    images: list[str]
    planogram: str
    catalog: str
    output: str
    cache_dir: str
    prices: str | None = None
    llm: str = "google:gemini-3.8-flash"
    ocr_llm: str | None = None
    base_url: str | None = None
    roi: tuple[float, float, float, float] | None = None
    verify_pass: bool | None = None  # None = auto: True for cloud backends, False when the backend is local
    marks: bool = True
    concurrency: int = Field(default=4, ge=1, le=16)
    visit_id: str = "visit"
    work_width: int = Field(default=2048, ge=256)
    weights: ScoringWeights = Field(default_factory=ScoringWeights)
```
**Why this shape**: `RunInfo.verify_pass` is the *resolved* bool actually used; `Settings.verify_pass` is the
tri-state request. `cache_dir` is required (moved up with the other required fields — pydantic has no
ordering constraint, but keep required fields first for readability).

### `examples/planogram/tests/test_plancheck_models_results.py` (CREATE)
```python
"""TASK-3338: result models round-trip through JSON and keep their defaults."""
from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from plancheck.models import (
    ComplianceReport, ComplianceSummary, PositionResult, PriceReading, RunInfo, ScoringWeights, Settings,
    Slot, SlotObservation,
)


def _settings(**overrides) -> Settings:
    base = {"images": ["/a.jpg"], "planogram": "/p.json", "catalog": "/c.json", "output": "/out", "cache_dir": "/cache"}
    return Settings(**{**base, **overrides})


def test_settings_defaults() -> None:
    """Defaults fixed by the spec: gemini-3.8-flash, verify_pass None (auto), marks on, weights .5/.5/.5/1."""
    # FILL IN: assert llm, verify_pass is None, marks is True, concurrency == 4, work_width == 2048, weights values
    raise NotImplementedError


def test_settings_bounds() -> None:
    # FILL IN: concurrency 0 and 17 → ValidationError; work_width 100 → ValidationError; unknown field → ValidationError
    raise NotImplementedError


def test_slot_observation_defaults() -> None:
    # FILL IN: build a Slot (origin "tag_anchored"); SlotObservation(slot=…) has resolution "unresolved",
    #          price.status "not_assessed", facing_id None, empty lists that are NOT shared between instances
    raise NotImplementedError


def test_report_roundtrip_json(mini_planogram) -> None:
    """ComplianceReport → model_dump(mode='json') → model_validate keeps Decimals and literals."""
    # FILL IN: build a minimal report with one PositionResult carrying price=PriceReading(raw="$45.99",
    #          amount=Decimal("45.99"), currency="USD", source="llm", status="read") and price_expected;
    #          json.dumps the dump (must not raise), validate it back, assert equality of the Decimal values
    raise NotImplementedError


def test_run_info_constants() -> None:
    # FILL IN: registration_method defaults to "auto_alignment" and rejects any other value
    raise NotImplementedError


def test_position_status_rejects_unknown(mini_planogram) -> None:
    # FILL IN: PositionResult(status="reviewed", …) → ValidationError; "not_assessed" and "not_visible" accepted
    raise NotImplementedError
```
**Why this shape**: `test_report_roundtrip_json` is spec §4's M1 test; the rest pin the defaults that the CLI,
pipeline and scoring tasks rely on.

### FILL IN checklist
- [ ] `test_settings_defaults` — bounded by spec §3 Module 1 `Settings` and §8 Q2/Q4/Q6.
- [ ] `test_settings_bounds` — bounded by the `Field(ge=…, le=…)` constraints above.
- [ ] `test_slot_observation_defaults` — bounded by `default_factory` semantics.
- [ ] `test_report_roundtrip_json` — bounded by spec §4 `test_report_roundtrip_json`.
- [ ] `test_run_info_constants` — bounded by design research S6.
- [ ] `test_position_status_rejects_unknown` — bounded by the `PositionStatus` literal (10 values).

---

## Acceptance Criteria

- [ ] All 13 classes importable from `plancheck.models`; part 1 of the file is byte-identical to what TASK-3337 wrote.
- [ ] `ComplianceReport` JSON round-trip preserves `Decimal` amounts.
- [ ] `ruff check examples/planogram/plancheck/models.py examples/planogram/tests/test_plancheck_models_results.py` clean.

---

## Validation Commands

- `pytest examples/planogram/tests/test_plancheck_models_results.py -q`

---

## Test Specification

See the blueprint's test file (six tests, FILL IN bodies bounded above).

---

## Agent Instructions

1. Read spec §3 Module 1 and §2 "Data Models".
2. Verify the anchor (Step 1). If absent, STOP — dependency not merged.
3. Append the blocks verbatim; complete the tests.
4. Verify acceptance criteria; move this file to `sdd/tasks/completed/`; set the index entry to `done`; fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-coder (native, model sonnet, attempt_uid 0b2b6bdc1a68418da10abb2820761cee)
**Date**: 2026-09-17
**Notes**: Appended the 13 result/config model classes (SlotObservation, RowRegistration,
ImageRegistration, ScoringWeights, PositionResult, ShelfScore, BrandShare, PriceCompliance,
ComplianceSummary, ImageInfo, RunInfo, ComplianceReport, Settings) below the TASK-3337 anchor
in `models.py` — a pure append (`git diff` confirmed part 1 byte-identical). Created
`examples/planogram/tests/test_plancheck_models_results.py` with all 6 FILL IN tests.
`pytest examples/planogram/tests/test_plancheck_models_results.py -q` → 6 passed; TASK-3337
regression suite still 6 passed; `ruff check` clean. Post-merge full suite → 28 passed.
Review recorded: `coder-review:70f845327357d564b30ca991`, no corrections needed.

**Seat**: sonnet(native) · Backend: native · Model: sonnet · Attempts: 1 · Duration: n/a · Tokens: n/a

**Deviations from spec**: none
