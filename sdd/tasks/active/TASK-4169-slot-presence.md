# TASK-4169: Add tri-state slot-presence contracts and aggregation

**Feature**: FEAT-645 — Planogram Ink Wall — model-based labels and slot presence
**Spec**: `sdd/specs/planogram-ink-wall-slot-presence.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4167
**Assigned-to**: unassigned

## Context

Implement spec §3 M4 and §2 truth table. Presence is a reporting projection over existing decisions and never re-scores them.

## Scope

- Add SlotPresence and a fresh ComparisonResult.products_found list.
- Implement facing_presence and build_slot_presence as pure functions.
- Test all statuses, confidence boundaries, grouping and representative selection.

**NOT in scope**: scoring/credit/status changes, vision identification improvements, database writes,
flowtask persistence, dependencies, or files outside the table below.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py` | MODIFY | SlotPresence and additive comparison result field |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/presence.py` | CREATE | Pure presence helpers |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_slot_presence.py` | CREATE | Presence truth table and aggregation tests |

---

## Codebase Contract (Anti-Hallucination)

Verified on `dev` during decomposition, 2026-10-08. Recheck anchors after dependencies land.
Existing imports below are verified in their source modules or installed dependencies.
Imports explicitly tagged with a task ID are planned dependency interfaces, not existing symbols at planning time.
Retain unrelated existing imports in MODIFY targets.

### Verified Imports

```python
from typing import List, Optional, Sequence, Tuple
from pydantic import BaseModel, Field
import pytest
from parrot_pipelines.planogram.comparison.definition import ReportingPolicy, SlotsDefinition  # ReportingPolicy: TASK-4167
from parrot_pipelines.planogram.contracts import FacingStatus, PositionResult, ObservationRef, ComparisonResult
# Created by this task:
from parrot_pipelines.planogram.contracts import SlotPresence
from parrot_pipelines.planogram.comparison.presence import facing_presence, build_slot_presence
```

### Existing Signatures to Use

- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py:131` — `SlotsDefinition`: shelves and all_facings retain definition order
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py:78` — `FacingDefinition`: facing_id, shelf_id, slot, position, product, brand, descriptors, expected_occupancy
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py:100` — `ShelfDefinition`: level provides shelf_level; facings list is ordered
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py:170` — `FacingStatus`: twelve statuses listed in spec §2
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py:218` — `PositionResult`: status, identity, observations and notes; no deciding_view attribute
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py:195` — `ObservationRef`: raw_confidence defaults to 0.0; image_id, shape_id and source are required
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py:325` — `ComparisonResult`: all additive collections use Field(default_factory=list)
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/scoring.py:160` — `merge_positions`: deciding observation first when one exists; notes include deciding:image/shape at 214
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/scoring.py:80` — `_decide`: NOT_VISIBLE, NOT_ASSESSED and CONFLICT have no deciding view even if observations exist

### Does NOT Exist

- `SlotPresence`, `products_found`, and comparison/presence.py are new.
- PositionResult has no confidence or deciding_view field; use observations and the verified deciding contract.
- Do not add a confidence gate to _decide or mutate credits.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/presence.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_slot_presence.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py#SlotsDefinition",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py#FacingDefinition",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py#ShelfDefinition",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py#FacingStatus",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py#PositionResult",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py#ObservationRef",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py#ComparisonResult",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/scoring.py#merge_positions",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/scoring.py#_decide"
  ]
}
```

## Implementation Notes

The spec excerpt may use sparse slot numbers 10–12 and 4. For pure builder tests construct SlotsDefinition directly; the public loader separately requires contiguous slots 1..n. Never weaken loader validation to fit a test excerpt. For synthetic PositionResult tests, set observations[0] to the deciding view for resolved statuses; no notes marker is required from hand-built fixtures. EXPECTED_EMPTY/UNEXPECTED_OCCUPIED are excluded upstream from aggregation; facing_presence may return neutral (None, False, confidence) for these non-product states.

**Parallelism**: Consumes ReportingPolicy from TASK-4167 and Descriptors.sku from its TASK-4166 ancestor (comparison/definition.py); independent of TASK-4168 layout defaults. All mutations stay within declared files; `parallel: true`.
Do not change shared conftest files, rebuild extensions, or alter the environment.
Use the already-installed Pydantic v2 and pytest dependencies. No new dependency is needed.
Use strict type hints, Google-style docstrings, black (120 columns), and ruff on touched files.
Pure comparison helpers remain synchronous and perform no I/O.
Blueprint gaps are planning scaffolds only: completed implementation must contain no placeholders.

## Implementation Blueprint

### Steps (in order)
1. Add SlotPresence and the default list — because downstream consumers need a stable typed contract.
2. Implement facing_presence from the truth table — because label and slot reporting must agree independently of credits.
3. Group in definition order and choose representative evidence — because duplicate facings must not become duplicate slots.
4. Test threshold equality, missing views and input immutability — because absence of evidence must remain unknown.

---

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py` (MODIFY)

```python
# BEFORE — insert SlotPresence `class ShelfScore(BaseModel):`
# occurrences: 1 (verified: rg -n -F; packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py:231)
# AFTER — insert products_found `    position_results: List[PositionResult] = Field(default_factory=list)`
# occurrences: 1 (verified: rg -n -F; packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py:329)
# Insert at module scope before ShelfScore:
class SlotPresence(BaseModel):
    """Presence of the expected model in one logical shelf slot."""

    shelf_id: str
    shelf_level: Optional[str] = None
    slot: int
    position: Optional[int] = None
    facing_ids: List[str]
    model: str
    sku: Optional[str] = None
    brand: Optional[str] = None
    display_name: Optional[str] = None
    found: Optional[bool] = None
    misplaced: bool = False
    status: FacingStatus
    confidence: Optional[float] = None
    facings: int = 1
    facings_found: int = 0
    observed: Optional[str] = None


# Inside ComparisonResult after position_results:
    products_found: List[SlotPresence] = Field(default_factory=list)
```

**Why**: The additive typed list defaults to empty without altering any existing fields or statuses.

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/presence.py` (CREATE)

```python
"""Pure reporting of expected model presence; scoring is intentionally unchanged."""
from typing import List, Optional, Sequence, Tuple

from parrot_pipelines.planogram.comparison.definition import ReportingPolicy, SlotsDefinition
from parrot_pipelines.planogram.contracts import FacingStatus, PositionResult, SlotPresence


def facing_presence(
    position: Optional[PositionResult], policy: ReportingPolicy
) -> Tuple[Optional[bool], bool, Optional[float]]:
    """Return found, misplaced and deciding confidence for one facing."""
    # FILL IN: implement the exact §2 truth table (AC-2), None -> (None, False, None).
    # No deciding confidence for NOT_VISIBLE/NOT_ASSESSED/CONFLICT, even with observations.
    # Otherwise observations[0] supplies raw_confidence when present; never search/max all views.
    pass


def build_slot_presence(
    positions: Sequence[PositionResult], definition: SlotsDefinition, policy: ReportingPolicy
) -> List[SlotPresence]:
    """Group occupied-expected facings by shelf and position, preserving definition order."""
    # FILL IN: exclude expected-empty; key (shelf_id, position if not None else slot).
    # Apply True > None > False, count true facings, choose first facing matching aggregate.
    # Populate every contract field, without mutating inputs (AC-3/4).
    pass
```

**Why**: One helper supplies identical reporting semantics to slot aggregation and model-label projection; definition order determines stable output.

### `packages/ai-parrot-pipelines/tests/planogram_cycle/test_slot_presence.py` (CREATE)

```python
"""Tri-state slot presence and representative evidence for FEAT-645."""
import pytest
from parrot_pipelines.planogram.comparison.definition import ReportingPolicy, SlotsDefinition
from parrot_pipelines.planogram.comparison.presence import build_slot_presence, facing_presence
from parrot_pipelines.planogram.contracts import ComparisonResult, FacingStatus, ObservationRef, PositionResult


@pytest.mark.parametrize("status", list(FacingStatus))
def test_facing_presence_truth_table(status: FacingStatus) -> None:
    """Every status follows the reporting table without changing score credit."""
    # FILL IN: explicit expected outcomes, no view and confidence 0.5/0.9/0.95 (AC-2).
    pass


def test_slot_presence_grouping_closeout() -> None:
    """Three facings at position 97 become one ordered entry with counted presence."""
    # FILL IN: native excerpt with CLOSEOUT x3, missing SKU and preserved metadata (AC-3).
    pass


def test_slot_presence_mixed_unknown_and_empty() -> None:
    """Unknown plus empty is unknown; all empty is absent."""
    # FILL IN: compare representative evidence and facings_found in both cases (AC-3/4).
    pass


def test_slot_presence_mismatch_observed() -> None:
    """Mismatch reports false while keeping observed identity separate from expected model."""
    # FILL IN: observed different model/brand, known and absent observation evidence (AC-4).
    pass


def test_slot_presence_excludes_expected_empty() -> None:
    """Expected-empty facings never enter a group, regardless of observed occupancy."""
    # FILL IN: both EXPECTED_EMPTY and UNEXPECTED_OCCUPIED plus missing positions (AC-3).
    pass


def test_slot_presence_defaults_and_serialization() -> None:
    """Defaults are independent and nullable presence/status serialize as JSON values."""
    # FILL IN: two ComparisonResult instances and populated SlotPresence round trip (AC-1).
    pass
```

**Why**: Table-driven cases protect tri-state semantics; aggregation cases catch false absence and unstable evidence selection.

---

### FILL IN checklist

- [ ] Implement all truth-table branches and deciding confidence (AC-2).
- [ ] Implement grouping, metadata and representative choice (AC-3/4).
- [ ] Complete all test bodies, fallback keys and shuffled-position regression (AC-1/2/3/4).

---

## Acceptance Criteria

- [ ] AC-1: SlotPresence fields match spec §2 exactly; ComparisonResult defaults to a fresh empty list and JSON serialization preserves found=null and enum values.
- [ ] AC-2: MATCH/VARIANT_UNRESOLVED/INFERRED_PRESENT are true; MISPLACED is true/true only with deciding confidence >= policy threshold, otherwise null/false; MISMATCH/EMPTY are false; unknown statuses are null. Missing position returns (None, False, None). Expected-empty statuses are excluded by the builder.
- [ ] AC-3: One output per occupied-expected (shelf_id, position), falling back to slot when position is None; preserve shelf/definition order; found precedence true then null then false; facings_found counts true facings and facings counts included members.
- [ ] AC-4: First definition-facing matching aggregate found supplies status/confidence/observed/misplaced; missing result represents NOT_VISIBLE. Identity metadata comes from the group's first expected facing and shelf level. No deciding view means confidence=None. Inputs, scores and credits are unchanged.

## Validation Commands

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_slot_presence.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_contracts.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_scoring_projection.py -q`

---

## Test Specification

Include CLOSEOUT at position 97 with three facings; distinct shelves sharing a position; position=None fallback; shuffled observed results; a missing PositionResult; custom thresholds 0 and 1; equality at 0.9; second observation higher confidence than deciding observation; CONFLICT with nonempty provenance but no deciding view. Assert representative identity and misplaced flag, not only aggregate found.

---

## Agent Instructions

1. Use `$sdd-start TASK-4169` to provision the feature worktree; never implement on `dev`.
2. Read the spec and this task; confirm dependencies are done in `sdd/tasks/index/planogram-ink-wall-slot-presence.json`.
3. Reverify imports, signatures and anchors; refresh the contract first if code moved.
4. Implement only the declared files from the blueprint, completing every FILL IN item.
5. Run Validation Commands; store test logs under `artifacts/logs/`. Run black and ruff on touched Python files.
6. Commit scoped code, then finalize using `scripts.sdd.finalize_task` with real
   `TaskCompletionEvidence` and the exact implementation HEAD, per the Codex adaptation contract.
   Do not use the legacy close_task.sh path or manually move this task/change its Completion Note.

## Completion Note

Populated by the task finalizer after implementation and verification.
