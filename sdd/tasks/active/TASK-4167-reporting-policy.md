# TASK-4167: Validate and resolve reporting policy overrides

**Feature**: FEAT-645 — Planogram Ink Wall — model-based labels and slot presence
**Spec**: `sdd/specs/planogram-ink-wall-slot-presence.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4166
**Assigned-to**: unassigned

## Context

Implement spec §3 M2. Reporting must be configurable without introducing a definition/layout import cycle.

## Scope

- Add ReportingPolicy and REPORTING_META_KEY.
- Validate partial metadata during SlotsDefinition construction.
- Resolve defaults, layout policy and metadata in precedence order.
- Test the user-confirmed exception convention.

**NOT in scope**: scoring/credit/status changes, vision identification improvements, database writes,
flowtask persistence, dependencies, or files outside the table below.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py` | MODIFY | Policy model, metadata validator and effective_reporting |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_reporting_policy.py` | CREATE | Policy precedence and error-boundary tests |

---

## Codebase Contract (Anti-Hallucination)

Verified on `dev` during decomposition, 2026-10-08. Recheck anchors after dependencies land.
Existing imports below are verified in their source modules or installed dependencies.
Imports explicitly tagged with a task ID are planned dependency interfaces, not existing symbols at planning time.
Retain unrelated existing imports in MODIFY targets.

### Verified Imports

```python
from typing import Any, Dict, Literal, Optional
from types import SimpleNamespace  # Python stdlib; layout-like test input avoids dependency on TASK-4168
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
import pytest
from parrot_pipelines.planogram.comparison.definition import SlotsDefinition, SlotsDefinitionError, load_slots_definition
# Created by this task in definition.py:
from parrot_pipelines.planogram.comparison.definition import ReportingPolicy, effective_reporting
```

### Existing Signatures to Use

- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py:131` — `SlotsDefinition`: meta: Dict[str, Any]; currently has no model validator
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py:41` — `SlotsDefinitionError`: ValueError subclass; wrapped by Pydantic during model validation
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py:280` — `load_slots_definition`: model_validate at 312; converts ValidationError to SlotsDefinitionError at 314-315

### Does NOT Exist

- `ReportingPolicy`, `REPORTING_META_KEY`, `effective_reporting`, and `_check_reporting_meta` are new.
- Do not import LayoutProfile here: layout.py already imports definition.py.
- No custom construction API bypasses Pydantic validation.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_reporting_policy.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py#SlotsDefinition",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py#SlotsDefinitionError",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py#load_slots_definition"
  ]
}
```

## Implementation Notes

**User clarification (2026-10-08): preserve the convention.** This supersedes the spec wording that direct SlotsDefinition construction exposes SlotsDefinitionError. Direct model calls raise Pydantic ValidationError; the existing loader translates it to SlotsDefinitionError. Keep that boundary and add no custom constructor. Dependencies may shift line numbers, so locate by anchors.

**Parallelism**: TASK-4166 must land first because both tasks modify comparison/definition.py; preserve its SKU field and validator. All mutations stay within declared files; `parallel: true`.
Do not change shared conftest files, rebuild extensions, or alter the environment.
Use the already-installed Pydantic v2 and pytest dependencies. No new dependency is needed.
Use strict type hints, Google-style docstrings, black (120 columns), and ruff on touched files.
Pure comparison helpers remain synchronous and perform no I/O.
Blueprint gaps are planning scaffolds only: completed implementation must contain no placeholders.

## Implementation Blueprint

### Steps (in order)
1. Add the strict policy model before its consumers — because both layout and definition validation depend on it.
2. Validate meta without replacing the partial payload — because omitted keys must inherit the profile, not policy defaults.
3. Implement effective_reporting and verify both exception boundaries — because the user explicitly chose the existing convention.

---

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py` (MODIFY)

```python
# MODIFY — add ConfigDict to import `from pydantic import BaseModel, Field, ValidationError, model_validator`
# occurrences: 1 (verified: rg -n -F; packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py:10)
# BEFORE — insert policy constant and model at module scope `class Descriptors(BaseModel):`
# occurrences: 1 (verified: rg -n -F; packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py:45)
# BEFORE — insert SlotsDefinition validator `    def all_facings(self) -> List[FacingDefinition]:`
# occurrences: 1 (verified: rg -n -F; packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py:139)
# BEFORE — insert effective_reporting at module scope `def _normalise_page1(data: Dict[str, Any]) -> Dict[str, Any]:`
# occurrences: 1 (verified: rg -n -F; packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py:144)
# Replace the existing pydantic import; retain TASK-4166's separate field_validator import.
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

REPORTING_META_KEY = "reporting"


class ReportingPolicy(BaseModel):
    """Control product labels and optional slot-presence reporting."""

    model_config = ConfigDict(extra="forbid")
    product_label: Literal["display_name", "product"] = "display_name"
    slot_presence: bool = False
    misplaced_min_confidence: float = Field(default=0.9, ge=0.0, le=1.0)


# Insert inside SlotsDefinition before all_facings (there is no existing after validator):
    @model_validator(mode="after")
    def _check_reporting_meta(self) -> "SlotsDefinition":
        """Validate a partial reporting object using normal Pydantic error handling."""
        # FILL IN: absent key is valid; present non-dict/null or invalid policy fails (AC-2).
        # Preserve the original partial dict: do not materialize missing defaults into meta.
        return self


# Insert at module scope before _normalise_page1:
def effective_reporting(layout: Optional[Any], definition: Optional[SlotsDefinition]) -> ReportingPolicy:
    """Merge default/layout reporting with explicitly provided definition overrides."""
    # FILL IN: merge validated explicit keys only; no mutation or layout import (AC-3).
    # Use existing module logger.debug for resolution diagnostics; never log the whole definition.
    pass
```

**Why**: Partial overrides must not reset unrelated profile fields. Pydantic validates the model; the loader owns the domain-error boundary.

### `packages/ai-parrot-pipelines/tests/planogram_cycle/test_reporting_policy.py` (CREATE)

```python
"""Reporting policy validation and precedence for FEAT-645."""
from types import SimpleNamespace
from typing import Any
import pytest
from pydantic import ValidationError
from parrot_pipelines.planogram.comparison.definition import (
    ReportingPolicy, SlotsDefinition, SlotsDefinitionError, effective_reporting, load_slots_definition,
)


@pytest.mark.parametrize("reporting", [{"unknown": True}, {"product_label": "x"}, {"misplaced_min_confidence": 1.5}, {"misplaced_min_confidence": -0.1}, None, []])
def test_reporting_meta_override_validated(reporting: Any) -> None:
    """Direct validation uses ValidationError; the loader exposes SlotsDefinitionError."""
    # FILL IN: assert both boundaries using otherwise-valid definition input (AC-2).
    pass


def test_effective_reporting_precedence() -> None:
    """Only explicit meta keys override a profile; no source object is mutated."""
    # FILL IN: None layout/definition, defaults, custom profile and partial override (AC-3).
    pass


def test_reporting_policy_defaults_and_bounds() -> None:
    """Default labels/presence remain legacy and threshold endpoints are accepted."""
    # FILL IN: defaults; 0 and 1 valid; unknown fields and bad labels invalid (AC-1).
    pass
```

**Why**: A SimpleNamespace layout stub isolates this task from the later LayoutProfile field addition.

---

### FILL IN checklist

- [ ] Implement metadata validation including present-null rejection (AC-2).
- [ ] Implement explicit-key merge and no-mutation assertions (AC-3).
- [ ] Fill error-boundary and bounds tests (AC-1/2).

---

## Acceptance Criteria

- [ ] AC-1: Policy forbids extra keys, defaults to display_name/False/0.9, and constrains threshold to [0, 1].
- [ ] AC-2: Malformed reporting fails during direct construction/model_validate with ValidationError; load_slots_definition raises SlotsDefinitionError before a run. Unknown keys, invalid labels, threshold out of bounds and non-dicts are tested.
- [ ] AC-3: Defaults < layout.reporting < explicit meta keys; layout=None and definition=None are supported; no input mutation; partial overrides retain untouched fields.

## Validation Commands

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_reporting_policy.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_slots_definition.py -q`

---

## Test Specification

Test metadata overrides for product_label, slot_presence=False and a custom threshold independently. Empty metadata and an empty reporting dict must preserve the profile. Verify the public loader on native and page1 inputs.

---

## Agent Instructions

1. Use `$sdd-start TASK-4167` to provision the feature worktree; never implement on `dev`.
2. Read the spec and this task; confirm dependencies are done in `sdd/tasks/index/planogram-ink-wall-slot-presence.json`.
3. Reverify imports, signatures and anchors; refresh the contract first if code moved.
4. Implement only the declared files from the blueprint, completing every FILL IN item.
5. Run Validation Commands; store test logs under `artifacts/logs/`. Run black and ruff on touched Python files.
6. Commit scoped code, then finalize using `scripts.sdd.finalize_task` with real
   `TaskCompletionEvidence` and the exact implementation HEAD, per the Codex adaptation contract.
   Do not use the legacy close_task.sh path or manually move this task/change its Completion Note.

## Completion Note

Populated by the task finalizer after implementation and verification.
