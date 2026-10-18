# TASK-4361: Accept and validate `appearance` rule bindings

**Feature**: FEAT-683 — Planogram appearance rule
**Spec**: `sdd/specs/planogram-appearance-rule.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4359
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3. `RuleKind` must accept `"appearance"`, and `validate_bindings` (which `check_row`
runs as the preflight before any row is used) must reject malformed `appearance` params, so a typo
in a config row fails at preflight instead of producing an always-unassessed rule at run time.

---

## Scope

- Add `"appearance"` to `RuleKind`.
- In `validate_bindings`, add a per-kind check loop for `appearance` (next to the existing
  `fact_tag_present` loop) that raises `SlotsDefinitionError` when the binding:
  1. targets a facing;
  2. has no attribute in `params`;
  3. names an attribute that is not a key of `APPEARANCE_VALUES`;
  4. lists a value outside that attribute's set (this includes `unknown` / `not_visible`).
  Scalar values are accepted as one-item lists.
- Update the `validate_bindings` docstring `Raises:` section.
- Write `tests/planogram_cycle/test_appearance_validation.py`, including `check_row` integration.

**NOT in scope**: evaluation (TASK-4362); normalising the params in place (evaluation reads both
scalar and list forms itself).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py` | MODIFY | `RuleKind`, validation loop, docstring |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_appearance_validation.py` | CREATE | unit + `check_row` tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# definition.py has no planogram-internal import today (lines 3-10). contracts.py imports nothing from the
# planogram package, so this import introduces no cycle (verified: python -c "import ...definition, ...contracts"):
from parrot_pipelines.planogram.contracts import APPEARANCE_VALUES   # created by TASK-4359
# tests:
from parrot_pipelines.planogram.comparison.definition import (
    SlotsDefinitionError, load_slots_definition, validate_bindings,
)
from parrot_pipelines.planogram.migration import check_row           # migration.py:698
```

### Existing Signatures to Use
```python
# comparison/definition.py
RuleKind = Literal["illumination", "text_requirements", "visual_features", "zone_present", "fact_tag_present"]  # line 14
class SlotsDefinitionError(ValueError): ...                                     # line 42
class RuleBinding(BaseModel): rule_id; kind: RuleKind; target_id; params; mandatory  # line 162
def validate_bindings(definition: SlotsDefinition, planogram_config: Dict[str, Any]) -> List[RuleBinding]:  # line 433
    # namespaces = {"facing": ..., "zone": ..., "shelf": ...}   built at lines 468-472
    # fact_tag_present loop at lines 480-488 — pattern to mirror
    # line 490: mandatory_targets = {b.target_id for b in bindings if b.mandatory}

# migration.py:698
def check_row(row: Dict[str, Any]) -> PreflightRow   # .ok, .problems; problems contain "invalid rule_bindings: <msg>"
```

### Does NOT Exist
- ~~`RuleBinding` per-kind params models~~ — `params` is a plain `Dict[str, Any]`; validate by hand.
- ~~`APPEARANCE_ATTRIBUTES`~~ — use `APPEARANCE_VALUES` keys.

---

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
      "path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_appearance_validation.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py#validate_bindings",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py#RuleBinding",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/migration.py#check_row"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Import `APPEARANCE_VALUES` after the pydantic import — *why*: the vocabulary is the single source of truth.
2. Extend `RuleKind` — *why*: `RuleBinding.model_validate` rejects unknown kinds today.
3. Add the validation loop before `mandatory_targets` — *why*: same place and style as the `fact_tag_present` checks.
4. Write the tests — *why*: every rejection case is an acceptance criterion.

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF 'from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator' definition.py)
# AFTER — insert below that line (definition.py:10), separated by a blank line
from parrot_pipelines.planogram.contracts import APPEARANCE_VALUES
```
```python
# occurrences: 1 (verified: grep -cF 'RuleKind = Literal["illumination", "text_requirements", "visual_features", "zone_present", "fact_tag_present"]' definition.py)
# REPLACE definition.py:14
RuleKind = Literal[
    "illumination", "text_requirements", "visual_features", "zone_present", "fact_tag_present", "appearance"
]
```
```python
# occurrences: 1 (verified: grep -cF '    mandatory_targets = {b.target_id for b in bindings if b.mandatory}' definition.py)
# BEFORE — insert above that line (definition.py:490)
    for binding in bindings:
        if binding.kind != "appearance":
            continue
        if binding.target_id in namespaces["facing"]:
            raise SlotsDefinitionError(f"rule {binding.rule_id}: appearance must target a zone or shelf")
        if not binding.params:
            raise SlotsDefinitionError(f"rule {binding.rule_id}: appearance needs at least one attribute")
        for attribute, expected in binding.params.items():
            # FILL IN: unknown attribute -> SlotsDefinitionError naming it and listing sorted(APPEARANCE_VALUES);
            #          normalise a scalar to [scalar]; empty list or any value not in APPEARANCE_VALUES[attribute]
            #          -> SlotsDefinitionError naming the attribute and the bad value — bounded by spec §3 M3
            ...
```
**Why this shape**: spec §3 Module 3 fixes the four rejection cases. Messages start with `rule <id>:` like
every other error of this function, so `check_row` surfaces them as `invalid rule_bindings: rule <id>: ...`.

### `packages/ai-parrot-pipelines/tests/planogram_cycle/test_appearance_validation.py` (CREATE)
```python
"""FEAT-683: appearance bindings are validated at preflight."""

import pytest

from parrot_pipelines.planogram.comparison.definition import (
    SlotsDefinitionError,
    load_slots_definition,
    validate_bindings,
)
from parrot_pipelines.planogram.migration import check_row

SLOTS = {
    "version": "1",
    "meta": {"planogram_type": "endcap_no_shelves_promotional"},
    "shelves": [],
    "zones": [{"zone_id": "zone-base-1", "kind": "graphic", "shelf_id": None, "required": True}],
}


def _config(params):
    return {
        "rule_bindings": [
            {"rule_id": "zone_present:zone-base-1", "kind": "zone_present", "target_id": "zone-base-1"},
            {"rule_id": "appearance:zone-base-1", "kind": "appearance", "target_id": "zone-base-1", "params": params},
        ]
    }


@pytest.mark.parametrize("params", [{"background_color": "white"}, {"border_color": ["blue", "none"], "finish": ["matte"]}])
def test_valid_appearance_binding(params):
    bindings = validate_bindings(load_slots_definition(SLOTS), _config(params))
    assert bindings[1].kind == "appearance"


@pytest.mark.parametrize(
    "params, message",
    [
        ({}, "at least one attribute"),
        ({"colour": ["white"]}, "colour"),
        ({"background_color": ["off-white"]}, "off-white"),
        ({"background_color": ["unknown"]}, "unknown"),
        ({"base_surface_color": "not_visible"}, "not_visible"),
        ({"background_color": []}, "background_color"),
    ],
)
def test_invalid_appearance_binding(params, message):
    with pytest.raises(SlotsDefinitionError, match=message):
        validate_bindings(load_slots_definition(SLOTS), _config(params))


def test_appearance_cannot_target_a_facing():
    # FILL IN: a slots definition with one shelf + one facing; an appearance binding on the facing id
    #          raises SlotsDefinitionError "must target a zone or shelf"
    ...


def test_check_row_reports_invalid_appearance():
    # FILL IN: check_row({"config_name": "t", "planogram_type": "endcap_no_shelves_promotional",
    #          "slots_definition": SLOTS, "planogram_config": _config(...)}) -> ok for a valid binding,
    #          not ok with "invalid rule_bindings" for {"background_color": ["off-white"]}
    ...
```

### FILL IN checklist
- [ ] `validate_bindings` attribute/value loop (definition.py)
- [ ] `test_appearance_cannot_target_a_facing`
- [ ] `test_check_row_reports_invalid_appearance`

---

## Acceptance Criteria

- [ ] `RuleBinding(kind="appearance", ...)` validates
- [ ] `validate_bindings` rejects the four malformed cases; scalar and list values accepted
- [ ] `check_row` reports an invalid appearance binding as a problem
- [ ] Existing `test_slots_definition.py` and `test_fact_tag_contracts.py` still pass; `ruff check` clean

---

## Validation Commands

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_appearance_validation.py -q`
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_slots_definition.py -q`
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_fact_tag_contracts.py -q`

---

## Test Specification

See the CREATE block above.

---

## Agent Instructions

1. Work in the feature worktree; TASK-4359 must be `done`.
2. Verify every anchor with `grep -cF`; set `in-progress`; implement; complete every `FILL IN`.
3. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-pipelines/src`.
4. Commit only the two listed files; close with `scripts/sdd/close_task.sh TASK-4361 planogram-appearance-rule verified`.

---

## Completion Note

Seat: gpt-5.6-luna · Backend: codex · Attempts: 1 · Duration: 58s

**Completed by**: sdd-worker (coder gpt-5.6-luna)
**Date**: 2026-10-15
**Notes**: task tests pass; planogram_cycle suite green except pre-existing missing-examples errors.

**Deviations from spec**: none
