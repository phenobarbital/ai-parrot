# TASK-5529: Model loader — selectors, resolved natures and hashing

**Feature**: FEAT-713 — Accounting Metrics Layer
**Spec**: `sdd/specs/accounting-metrics-layer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5528
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 (loader half), §2 Overview step 1, AC3/AC4/AC5. `load_model` turns a model YAML plus a
`ChartSnapshot` into a frozen `AccountingModel`: it resolves selectors into explicit sorted account lists, keeps
the resolved account natures (revision 0.3 — compilation never fetches the snapshot again), runs `validate`, and
hashes everything into `model_hash`.

---

## Scope

- `loader.py`: `load_spec`, `load_model`, `canonical_json`, `detect_drift`.
- Selector resolution: `accounts` ∪ `select` (`prefix`, `range` inclusive by string order, `tag`) minus `except`;
  result sorted.
- Nature resolution: `nature.from_column` ⇒ natures from `ChartSnapshot.accounts[*].nature` (the name identifies
  the account-master column, not a journal column); `nature.accounts` ⇒ explicit map, conflicts with snapshot
  natures are problems (raised by `validate`); `natural_balance` ⇒ natures optional. Keep sorted unique
  `(account, nature)` pairs for every selected account in `AccountingModel.natures`.
- `model_hash = sha256(canonical_json(resolved model without model_hash) + snapshot_hash)`.
- `tests/accounting/test_loader_validation.py`: `test_all_problems_reported`, `test_model_hash_changes_with_snapshot`,
  `test_resolved_natures_round_trip` (load + JSON round-trip half), `test_fixture_model_loads_cleanly`,
  `test_detect_drift`.

**NOT in scope**: compiling (TASK-5530/5531); the compile-without-snapshot half of `test_resolved_natures_round_trip`
(TASK-5531 covers it in golden tests).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-semantic/src/parrot/semantic/accounting/loader.py` | CREATE | loader + hashing |
| `packages/ai-parrot-semantic/tests/accounting/test_loader_validation.py` | CREATE | loader tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.semantic.accounting.errors import ModelValidationError, Problem          # TASK-5524
from parrot.semantic.accounting.models import (AccountingModel, AccountingModelSpec,  # TASK-5525
    ChartSnapshot, ResolvedSet)
from parrot.semantic.accounting.validation import partition_intervals, validate      # TASK-5528
import yaml
from pydantic import BaseModel, ValidationError
```

### Existing Signatures to Use
```python
# validation.py (TASK-5528)
def partition_intervals(sets: Mapping[str, AccountSet]) -> tuple[tuple[date | None, date | None], ...]
def validate(spec, resolved: Mapping[str, ResolvedSet], snapshot: ChartSnapshot, columns: Mapping[str, str] | None) -> list[Problem]
# errors.py (TASK-5524)
class ModelValidationError(AccountingError):  def __init__(self, problems: list[Problem], message: str | None = None)
```
- Fixtures: `chart_snapshot`, `troc_pnl_yaml` (`tests/accounting/conftest.py`).

### Does NOT Exist
- ~~`yaml.load`~~ — always `yaml.safe_load`.
- ~~a snapshot fetch in the loader~~ — the caller passes the snapshot.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-semantic/src/parrot/semantic/accounting/loader.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-semantic/tests/accounting/test_loader_validation.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- `canonical_json(obj)` = `json.dumps(obj.model_dump(mode="json", by_alias=True), sort_keys=True,
  separators=(",", ":"))`; Pydantic's JSON mode already emits Decimals as strings. The same function hashes
  models, plans and audit entries elsewhere — keep it exactly this.
- `load_spec` turns a `ValidationError` into `ModelValidationError` with one `Problem` per Pydantic error
  (code `column_missing` is wrong there — use the closest code; FILL IN decides, bounded by "never lose an error").
- `load_model` raises `ModelValidationError(problems)` when `validate` returns any problem.
- Compile-path isolation: stdlib, pyyaml, pydantic and the accounting package only.

---

## Implementation Blueprint

### Steps (in order)
1. Write `canonical_json` and `load_spec`.
2. Write selector + nature resolution helpers.
3. Write `load_model` and `detect_drift`.
4. Tests, starting with `test_fixture_model_loads_cleanly` — *why*: the shared `troc_pnl_yaml` fixture is used by
   every later task and must load with zero problems.

### `packages/ai-parrot-semantic/src/parrot/semantic/accounting/loader.py` (CREATE)
```python
"""Accounting model loader (FEAT-713 M4): selectors, resolved natures, validation, hashing."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Mapping

import yaml
from pydantic import BaseModel, ValidationError

from .errors import ModelValidationError, Problem
from .models import AccountingModel, AccountingModelSpec, ChartSnapshot, ResolvedSet
from .validation import partition_intervals, validate


def canonical_json(obj: BaseModel) -> str:
    """Sorted keys, no whitespace, Decimals as strings — the hashing representation."""
    return json.dumps(obj.model_dump(mode="json", by_alias=True), sort_keys=True, separators=(",", ":"))


def load_spec(source: Path | dict) -> AccountingModelSpec:
    """yaml.safe_load + Pydantic; raise ModelValidationError(problems) on schema errors."""
    # FILL IN: read Path with yaml.safe_load (non-mapping ⇒ ModelValidationError); validate; map ValidationError.
    raise NotImplementedError


def _resolve_sets(spec: AccountingModelSpec, snapshot: ChartSnapshot) -> dict[str, ResolvedSet]:
    # FILL IN: accounts ∪ select(prefix | range | tag) − except, sorted; keep valid_from / valid_to.
    raise NotImplementedError


def _resolve_natures(spec: AccountingModelSpec, snapshot: ChartSnapshot,
                     resolved: Mapping[str, ResolvedSet]) -> tuple[tuple[str, str], ...]:
    # FILL IN: see Scope "Nature resolution"; only selected accounts; sorted unique; skip accounts with no nature
    #   (validate reports nature_missing).
    raise NotImplementedError


def load_model(source: Path | dict, snapshot: ChartSnapshot, *,
               columns: Mapping[str, str] | None = None) -> AccountingModel:
    """Resolve selectors, partition intervals, validate (ALL problems), hash. Raises ModelValidationError."""
    spec = load_spec(source)
    resolved = _resolve_sets(spec, snapshot)
    problems = validate(spec, resolved, snapshot, columns)
    if problems:
        raise ModelValidationError(problems)
    natures = _resolve_natures(spec, snapshot, resolved)
    intervals = partition_intervals(spec.sets)
    draft = AccountingModel(spec=spec, snapshot_hash=snapshot.snapshot_hash, natures=natures,
                            intervals=intervals, sets=resolved, model_hash="")
    payload = canonical_json(draft).encode() + snapshot.snapshot_hash.encode()
    return draft.model_copy(update={"model_hash": hashlib.sha256(payload).hexdigest()})


def detect_drift(model: AccountingModel, fresh: ChartSnapshot) -> tuple[str, ...]:
    """Accounts in *fresh* that no set of *model* covers and no exclusion lists, sorted."""
    # FILL IN
    raise NotImplementedError
```
**Why**: hashing the draft with `model_hash=""` keeps the hash input independent of the hash itself.

### `packages/ai-parrot-semantic/tests/accounting/test_loader_validation.py` (CREATE)
```python
"""FEAT-713 M4 — loader."""

from __future__ import annotations


def test_fixture_model_loads_cleanly(troc_pnl_yaml, chart_snapshot) -> None:
    # FILL IN: load_model(troc_pnl_yaml, chart_snapshot) succeeds; sets resolved and sorted.


def test_all_problems_reported(chart_snapshot) -> None:
    # FILL IN: a model dict with 5 distinct defects ⇒ one ModelValidationError listing 5 problems (AC4).


def test_model_hash_changes_with_snapshot(troc_pnl_yaml, chart_snapshot) -> None:
    # FILL IN: extra account (covered by a prefix) or a changed nature ⇒ different model_hash; same input ⇒ same hash.


def test_resolved_natures_round_trip(troc_pnl_yaml, chart_snapshot) -> None:
    # FILL IN: natures present for every selected account; AccountingModel.model_validate_json(m.model_dump_json()) == m;
    #   nature map conflicting with the snapshot ⇒ ModelValidationError.


def test_detect_drift(troc_pnl_yaml, chart_snapshot) -> None:
    # FILL IN: a fresh snapshot with a new 7xxx account ⇒ ("7xxx",).
```

### FILL IN checklist
- [ ] `load_spec`, `_resolve_sets`, `_resolve_natures`, `detect_drift` — AC3/AC4/AC5.
- [ ] Five tests.

---

## Acceptance Criteria

- [ ] `troc_pnl_yaml` loads with zero problems.
- [ ] `load_model` raises one `ModelValidationError` with every problem (AC4).
- [ ] `model_hash` changes with the snapshot and with any nature (AC3, AC5); resolved natures survive JSON round-trip.
- [ ] `ruff check` passes on both files.

## Validation Commands

- `pytest packages/ai-parrot-semantic/tests/accounting/test_loader_validation.py -q`

---

## Test Specification

See blueprint.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug accounting-metrics-layer --feature-id FEAT-713`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/accounting-metrics-layer.json`
4. **Verify the Codebase Contract** before writing any code; update it first if anything moved
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`; never change a fixed signature or path
7. **Verify** — run the Validation Commands with absolute `PYTHONPATH` for both `packages/ai-parrot-semantic/src` and `packages/ai-parrot/src`
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `parrot sdd task close TASK-5529 accounting-metrics-layer verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
