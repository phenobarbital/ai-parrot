# TASK-4359: Appearance vocabulary and RuleObservation kind

**Feature**: FEAT-683 — Planogram appearance rule
**Spec**: `sdd/specs/planogram-appearance-rule.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1. Every other task of FEAT-683 needs one shared, closed vocabulary for zone
appearance: the evidence stage fills it (TASK-4360), binding validation checks configured values
against it (TASK-4361), and rule evaluation compares against it (TASK-4362). It lives in
`contracts.py` because that module imports nothing else from the planogram package, so both
`identification/` and `comparison/` can import it without an import cycle.

---

## Scope

- Add the `AppearanceColor` and `AppearanceFinish` literal types to `contracts.py`.
- Add the `ZoneAppearance` Pydantic model (four attributes, each defaulting to its undetermined value).
- Add the constants `APPEARANCE_VALUES` (attribute → values a config may expect) and
  `APPEARANCE_UNDETERMINED` (`{"unknown", "not_visible"}`).
- Widen `RuleObservation.kind` with `"appearance"` and `RuleObservation.value` with `Dict[str, str]`.
- Write `tests/planogram_cycle/test_appearance_contracts.py`.

**NOT in scope**: the evidence prompt (TASK-4360), `RuleKind` / binding validation (TASK-4361),
rule evaluation and scoring (TASK-4362).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py` | MODIFY | vocabulary, `ZoneAppearance`, constants, widened `RuleObservation` |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_appearance_contracts.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# contracts.py current imports (lines 3-12):
from __future__ import annotations
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple   # line 7 — FrozenSet and Union are NOT imported yet
from pydantic import BaseModel, ConfigDict, Field, model_validator  # line 9
```

### Existing Signatures to Use
```python
# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py:96
class RuleObservation(BaseModel):
    """Neutral crop-tied observation, not an expected-rule verdict."""

    image_id: str
    target_id: str
    kind: Literal["illumination", "visual_features", "zone_present"]   # line 101
    value: str | bool | List[str] | None = None                       # line 102
    assessed: bool = False
    source: ObservationSource
    evidence: List[str] = Field(default_factory=list)
```

### Does NOT Exist
- ~~`ZoneAppearance`~~, ~~`AppearanceColor`~~, ~~`AppearanceFinish`~~, ~~`APPEARANCE_VALUES`~~,
  ~~`APPEARANCE_UNDETERMINED`~~ — created by this task.
- ~~`contracts.APPEARANCE_ATTRIBUTES`~~ — not part of the design; use `APPEARANCE_VALUES.keys()`.
- ~~a colour enum anywhere in `parrot.models`~~ — none exists; do not look for one to reuse.

---

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
      "path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_appearance_contracts.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py#RuleObservation"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- The vocabulary is CLOSED: exactly the values listed in the blueprint, nothing more. A config that
  needs another colour is a future spec change, not a free-text field.
- `unknown` and `not_visible` mean "could not determine". They are valid model answers but never
  valid expectations, so they are in the `Literal`s yet excluded from `APPEARANCE_VALUES`.
- Keep the `from __future__ import annotations` style of the module.

### References in Codebase
- `contracts.py:96` — `RuleObservation`, the model being widened.

---

## Implementation Blueprint

### Steps (in order)
1. Extend the `typing` import on line 7 with `FrozenSet` and `Union` — *why*: the new constants and
   `ZoneAppearance` fields need them and the module does not import them today.
2. Insert the vocabulary block right above `class RuleObservation(BaseModel):` — *why*: it sits next
   to the observation that carries it, and both downstream stages already import from this module.
3. Widen `kind` and `value` of `RuleObservation` — *why*: the evidence stage records appearance as
   one observation whose value is the attribute dict.
4. Write the tests — *why*: they pin the vocabulary so a later edit cannot silently add `unknown`
   as a valid expectation.

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF 'from typing import Any, Dict, List, Literal, Optional, Tuple' contracts.py)
# REPLACE line 7 (verified: contracts.py:7)
from typing import Any, Dict, FrozenSet, List, Literal, Optional, Tuple, Union
```
```python
# occurrences: 1 (verified: grep -cF 'class RuleObservation(BaseModel):' contracts.py)
# BEFORE — insert above `class RuleObservation(BaseModel):` (verified: contracts.py:96)
AppearanceColor = Literal[
    "white",
    "black",
    "grey",
    "silver",
    "blue",
    "red",
    "green",
    "yellow",
    "orange",
    "purple",
    "brown",
    "multicolor",
    "unknown",
]
AppearanceFinish = Literal["matte", "glossy", "unknown"]

#: Values meaning "could not determine": valid model answers, never valid expectations.
APPEARANCE_UNDETERMINED: FrozenSet[str] = frozenset({"unknown", "not_visible"})

_COLOURS: FrozenSet[str] = frozenset(
    {"white", "black", "grey", "silver", "blue", "red", "green", "yellow", "orange", "purple", "brown", "multicolor"}
)

#: Attribute name -> values an ``appearance`` rule may expect.
APPEARANCE_VALUES: Dict[str, FrozenSet[str]] = {
    "background_color": _COLOURS,
    "border_color": _COLOURS | {"none"},
    "finish": frozenset({"matte", "glossy"}),
    "base_surface_color": _COLOURS,
}


class ZoneAppearance(BaseModel):
    """Closed-vocabulary appearance of one observed zone crop, as the model reads it."""

    background_color: AppearanceColor = "unknown"
    border_color: Union[AppearanceColor, Literal["none"]] = "unknown"
    finish: AppearanceFinish = "unknown"
    base_surface_color: Union[AppearanceColor, Literal["not_visible"]] = "unknown"


```
```python
# occurrences: 1 each (verified: grep -cF on contracts.py)
# REPLACE contracts.py:101 and contracts.py:102 inside RuleObservation
    kind: Literal["illumination", "visual_features", "zone_present", "appearance"]
    value: str | bool | List[str] | Dict[str, str] | None = None
```
**Why this shape**: spec §2 Data Models and §3 Module 1 fix these names and values. `APPEARANCE_VALUES`
keys are exactly the `ZoneAppearance` field names, so TASK-4361 can validate attribute names against
`APPEARANCE_VALUES` and TASK-4362 can read `observation.value[attribute]`. Do not rename anything.

### `packages/ai-parrot-pipelines/tests/planogram_cycle/test_appearance_contracts.py` (CREATE)
```python
"""FEAT-683: closed appearance vocabulary shared by evidence, validation and evaluation."""

import pytest
from pydantic import ValidationError

from parrot_pipelines.planogram.contracts import (
    APPEARANCE_UNDETERMINED,
    APPEARANCE_VALUES,
    ObservationSource,
    RuleObservation,
    ZoneAppearance,
)


def test_zone_appearance_defaults_unknown():
    appearance = ZoneAppearance()
    assert appearance.model_dump() == {
        "background_color": "unknown",
        "border_color": "unknown",
        "finish": "unknown",
        "base_surface_color": "unknown",
    }


def test_appearance_values_exclude_undetermined():
    # FILL IN: assert no value set in APPEARANCE_VALUES intersects APPEARANCE_UNDETERMINED,
    #          and that the keys equal ZoneAppearance.model_fields — bounded by spec §5 AC "vocabulary"
    ...


def test_zone_appearance_rejects_free_text():
    with pytest.raises(ValidationError):
        ZoneAppearance(background_color="off-white")


def test_rule_observation_accepts_appearance_dict():
    # FILL IN: build RuleObservation(kind="appearance", value=ZoneAppearance(...).model_dump(),
    #          source=ObservationSource.LLM, ...) and assert the dict round-trips — bounded by spec §3 M1
    ...
```
**Why**: the first and third tests pin the closed vocabulary; the FILL IN tests pin the two invariants
downstream tasks rely on.

### FILL IN checklist
- [ ] `test_appearance_values_exclude_undetermined` — disjointness + key set equality
- [ ] `test_rule_observation_accepts_appearance_dict` — dict value round-trip

---

## Acceptance Criteria

- [ ] `ZoneAppearance`, `APPEARANCE_VALUES`, `APPEARANCE_UNDETERMINED` importable from
      `parrot_pipelines.planogram.contracts`
- [ ] `RuleObservation(kind="appearance", value={...})` validates; existing kinds unchanged
- [ ] `APPEARANCE_VALUES` keys equal `ZoneAppearance` field names and contain no undetermined value
- [ ] `ruff check` clean on both files
- [ ] Existing `test_contracts.py` still green

---

## Validation Commands

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_appearance_contracts.py -q`
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_contracts.py -q`

---

## Test Specification

See the CREATE block above; all four tests must pass.

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug planogram-appearance-rule --feature-id FEAT-683`), never on `dev`.
2. Read the spec; verify the Codebase Contract anchors with `grep -cF`.
3. Set this task `in-progress` in `sdd/tasks/index/planogram-appearance-rule.json` and commit only the index.
4. Implement from the blueprint; complete every `FILL IN`.
5. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-pipelines/src`.
6. Commit only the two listed files; close with `scripts/sdd/close_task.sh TASK-4359 planogram-appearance-rule verified`.
7. Fill in the Completion Note and commit the SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
