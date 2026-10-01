# TASK-4003: fact_tag_present kind, info_results fields and binding validation

**Feature**: FEAT-624 — Planogram `fact_tag_present` rule
**Spec**: `sdd/specs/planogram-fact-tag-rule.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1. Declares the new rule kind and the two informative result lists every later
task writes to, and makes `validate_bindings` reject a `fact_tag_present` binding that is
mandatory or that does not target a facing. Informative-only (spec §2) relies on these checks:
a non-mandatory binding never enters the mandatory-rule paths.

---

## Scope

- Add `"fact_tag_present"` to `RuleKind`.
- In `validate_bindings`, reject a `fact_tag_present` binding whose target is not a facing, or
  whose `mandatory` is true, with the exact messages below.
- Add `info_results: List[RuleOutcome]` to `ShelfScore` and `info_results: List[Dict[str, Any]]`
  to the core `ShelfAssessment`.
- Write the tests listed under Test Specification.

**NOT in scope**: evaluating the rule (TASK-4005), routing outcomes in scoring/projection
(TASK-4006), converter changes (TASK-4007). Do NOT extend `RuleObservation.kind`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py` | MODIFY | new literal; kind-specific validation |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py` | MODIFY | `ShelfScore.info_results` |
| `packages/ai-parrot/src/parrot/models/compliance.py` | MODIFY | `ShelfAssessment.info_results` |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_fact_tag_contracts.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_pipelines.planogram.comparison.definition import (
    RuleBinding, SlotsDefinitionError, load_slots_definition, validate_bindings,
)  # verified: comparison/definition.py:118,41,277,348
from parrot_pipelines.planogram.contracts import RuleOutcome, ShelfScore  # verified: contracts.py:206,231
from parrot.models.compliance import ShelfAssessment  # verified: packages/ai-parrot/src/parrot/models/compliance.py:38
```

### Existing Signatures to Use
```python
# comparison/definition.py
RuleKind = Literal["illumination", "text_requirements", "visual_features", "zone_present"]  # line 14
class RuleBinding(BaseModel):  # line 118 — rule_id, kind: RuleKind, target_id, params, mandatory: bool = True
def validate_bindings(definition: SlotsDefinition, planogram_config: Dict[str, Any]) -> List[RuleBinding]:  # line 348
    # namespaces = {"facing": ..., "zone": ..., "shelf": ...}            line 380
    # for binding in bindings: (dangling / ambiguous checks)           line 385
    # mandatory_targets = {b.target_id for b in bindings if b.mandatory}  line 394

# contracts.py
class ShelfScore(BaseModel):  # line 231
    rule_results: List[RuleOutcome] = Field(default_factory=list)  # line 245

# packages/ai-parrot/src/parrot/models/compliance.py
class ShelfAssessment(BaseModel):  # line 38 — all fields optional
    rule_results: List[Dict[str, Any]] = Field(default_factory=list)  # line 48
```

### Does NOT Exist
- ~~`RuleObservation(kind="fact_tag_present")`~~ — `RuleObservation.kind` (contracts.py:101) is NOT extended.
- ~~`ShelfScore.info_results`~~ / ~~`ShelfAssessment.info_results`~~ — created by this task.
- ~~`FacingDefinition.fact_tag`~~ — the definition carries no tag field.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/models/compliance.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_fact_tag_contracts.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py#validate_bindings",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py#RuleBinding",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py#ShelfScore",
    "sym:packages/ai-parrot/src/parrot/models/compliance.py#ShelfAssessment"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Error messages are fixed by the spec (§3 M1); tests match them.
- Both new fields are additive with `default_factory=list`; nothing else changes.
- Inside the feature worktree, run tests with `PYTHONPATH=packages/ai-parrot-pipelines/src` only.
  The core `ai-parrot` package resolves to the MAIN checkout (its Cython `parrot.utils.types`
  exists only there), so `ShelfAssessment.info_results` is not importable from the worktree until
  merge. The `ShelfAssessment` test therefore skips when the field is absent — do not add
  `packages/ai-parrot/src` to `PYTHONPATH`.

---

## Implementation Blueprint

### Steps (in order)
1. Extend `RuleKind` — *why*: `RuleBinding.kind` is validated against it.
2. Add the kind-specific loop in `validate_bindings` before `mandatory_targets` — *why*: an invalid informative binding must fail at construction, before any inference.
3. Add the two `info_results` fields — *why*: TASK-4006 writes them; they must exist first.
4. Write the tests.

### `comparison/definition.py` (MODIFY — literal)
```python
# occurrences: 1 (verified: grep -c 'RuleKind = Literal\["illumination", "text_requirements", "visual_features", "zone_present"\]' comparison/definition.py)
# REPLACE line 14 (verified: comparison/definition.py:14)
RuleKind = Literal["illumination", "text_requirements", "visual_features", "zone_present", "fact_tag_present"]
```

### `comparison/definition.py` (MODIFY — validation)
```python
# occurrences: 1 (verified: grep -c '    mandatory_targets = {b.target_id for b in bindings if b.mandatory}' comparison/definition.py)
# BEFORE — insert above `    mandatory_targets = {b.target_id for b in bindings if b.mandatory}` (verified: comparison/definition.py:394)
    for binding in bindings:
        if binding.kind != "fact_tag_present":
            continue
        if binding.target_id not in namespaces["facing"]:
            raise SlotsDefinitionError(f"rule {binding.rule_id}: fact_tag_present must target a facing")
        if binding.mandatory:
            raise SlotsDefinitionError(f"rule {binding.rule_id}: fact_tag_present is informative and cannot be mandatory")
```
**Why**: the dangling/ambiguous loop above already guarantees the target exists in exactly one
namespace, so membership in `namespaces["facing"]` is the facing check. Update the
`validate_bindings` docstring `Raises:` section with both messages.

### `contracts.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    rule_results: List\[RuleOutcome\] = Field(default_factory=list)' contracts.py)
# AFTER — insert below `    rule_results: List[RuleOutcome] = Field(default_factory=list)` (verified: contracts.py:245)
    info_results: List[RuleOutcome] = Field(default_factory=list)  # informative outcomes; never read by scoring/status
```

### `packages/ai-parrot/src/parrot/models/compliance.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    rule_results: List\[Dict\[str, Any\]\] = Field(default_factory=list)' compliance.py)
# AFTER — insert below `    rule_results: List[Dict[str, Any]] = Field(default_factory=list)` (verified: compliance.py:48)
    info_results: List[Dict[str, Any]] = Field(default_factory=list)
```

### `tests/planogram_cycle/test_fact_tag_contracts.py` (CREATE)
```python
"""FEAT-624 — fact_tag_present kind and informative result fields."""

from __future__ import annotations

import pytest

from parrot.models.compliance import ShelfAssessment
from parrot_pipelines.planogram.comparison.definition import (
    RuleBinding,
    SlotsDefinitionError,
    load_slots_definition,
    validate_bindings,
)
from parrot_pipelines.planogram.contracts import RuleOutcome, ShelfScore


@pytest.fixture
def definition():
    """One shelf with two described facings and one zone on a second, zone-only shelf."""
    return load_slots_definition(
        {
            "shelves": [
                {
                    "shelf_id": "s1",
                    "shelf_number": 1,
                    "facings": [
                        {"facing_id": "s1:1", "shelf_id": "s1", "slot": 1, "product": "A", "descriptors": {"display_name": "A"}},
                        {"facing_id": "s1:2", "shelf_id": "s1", "slot": 2, "product": "B", "descriptors": {"display_name": "B"}},
                    ],
                },
                {"shelf_id": "s2", "shelf_number": 2, "facings": []},
            ],
            "zones": [{"zone_id": "z1", "kind": "header", "shelf_id": "s2"}],
        }
    )


def _binding(target: str, mandatory: bool = False) -> dict:
    return {"rule_id": f"fact_tag_present:{target}", "kind": "fact_tag_present", "target_id": target,
            "params": {"price_required": True}, "mandatory": mandatory}


def _zone_rule() -> dict:
    return {"rule_id": "zone_present:z1", "kind": "zone_present", "target_id": "z1", "mandatory": True}


def test_fact_tag_kind_is_accepted(definition):
    bindings = validate_bindings(definition, {"rule_bindings": [_binding("s1:1"), _zone_rule()]})
    assert [b.kind for b in bindings] == ["fact_tag_present", "zone_present"]


@pytest.mark.parametrize("target", ["z1", "s1"])
def test_fact_tag_binding_must_target_a_facing(definition, target):
    with pytest.raises(SlotsDefinitionError, match="must target a facing"):
        validate_bindings(definition, {"rule_bindings": [_binding(target), _zone_rule()]})


def test_fact_tag_binding_cannot_be_mandatory(definition):
    with pytest.raises(SlotsDefinitionError, match="informative and cannot be mandatory"):
        validate_bindings(definition, {"rule_bindings": [_binding("s1:1", mandatory=True), _zone_rule()]})


def test_fact_tag_binding_does_not_satisfy_zone_only_shelf(definition):
    # FILL IN: bindings = only _binding("s1:1") (no zone_present for z1); assert SlotsDefinitionError
    #          is still raised (zone-only shelf / required zone checks) — bounded by spec §2 "informative"
    ...


def test_shelf_score_has_info_results():
    score = ShelfScore(shelf_id="s1", shelf_level="s1", info_results=[RuleOutcome(rule_id="r")])
    assert score.info_results[0].rule_id == "r" and score.rule_results == []


@pytest.mark.skipif(
    "info_results" not in ShelfAssessment.model_fields,
    reason="core ai-parrot resolves to the main checkout inside a worktree; runs after merge",
)
def test_shelf_assessment_has_info_results():
    assert ShelfAssessment(info_results=[{"rule_id": "r"}]).info_results == [{"rule_id": "r"}]
```

### FILL IN checklist
- [ ] `test_fact_tag_binding_does_not_satisfy_zone_only_shelf` — body; bounded by spec §2 (a non-mandatory binding never satisfies a mandatory-rule check).

---

## Acceptance Criteria

- [ ] `RuleBinding(kind="fact_tag_present", ...)` validates.
- [ ] Zone or shelf target raises `rule <id>: fact_tag_present must target a facing`.
- [ ] `mandatory: true` raises `rule <id>: fact_tag_present is informative and cannot be mandatory`.
- [ ] `ShelfScore.info_results` and `ShelfAssessment.info_results` exist, default `[]`.
- [ ] `ruff check` clean on the touched files.

---

## Validation Commands

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_fact_tag_contracts.py -q`
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_config_migration.py -q`

---

## Test Specification

See the CREATE block above: acceptance of the kind, both rejection paths (parametrized over zone
and shelf targets), the zone-only-shelf check, and both new fields.

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug planogram-fact-tag-rule --feature-id FEAT-624`).
2. Read the spec; check `Depends-on` in `sdd/tasks/index/planogram-fact-tag-rule.json`.
3. Verify the Codebase Contract (`grep -c` every anchor) before editing.
4. Mark the task `in-progress`, implement from the blueprint, run the Validation Commands.
5. Commit only the listed files; close with `scripts/sdd/close_task.sh TASK-4003 planogram-fact-tag-rule verified`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
