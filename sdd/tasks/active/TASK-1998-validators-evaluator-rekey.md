# TASK-1998: Re-key FormValidator rule checks + RuleEvaluator graphs on field_uid

**Feature**: FEAT-393 — Stable UUID-Based Field Identity (field_uid)
**Spec**: `sdd/specs/formdesigner-field-uid.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1997
**Assigned-to**: unassigned

---

## Context

Implements Module 4 of FEAT-393 (spec §3, blueprint §9). Rule integrity
checks, cycle detection, and runtime rule evaluation move their internal
maps/graphs onto `field_uid`; the `answers` dict and all result maps STAY
keyed by `field_id` (client-facing surface).

---

## Scope

- `services/validators.py` — `validate_rules` (:791): `field_map`/`field_order`
  keyed by `str(f.field_uid)`; reference reads use `cond.field_uid`;
  `_validate_operation` (:910) operand/target checks against UID keys;
  `_detect_circular_dependencies` (:974) graph keyed by UID, cycle paths
  reported as `field_id` chains (human-readable).
- `services/rule_evaluator.py` — condition read (:124) via
  `resolve_answer(form, condition.field_uid, answers)`; `_topo_order` (:355)
  keyed by UID string. Keep warn-and-degrade on cycle.
- Result maps (`visible`, `required`, `computed`, `cleared`) and
  `FormValidator.validate` output: UNCHANGED (`field_id`-keyed).
- Update affected tests; add spec §4 Module 4 tests.

**NOT in scope**: `FormValidator.validate`/`validate_field` data validation
(stays field_id-keyed, untouched); resolution pass itself (TASK-1997).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py` | MODIFY | validate_rules, _validate_operation, cycle detection |
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/rule_evaluator.py` | MODIFY | condition reads, _topo_order |
| `packages/parrot-formdesigner/tests/unit/services/` | MODIFY/CREATE | re-key + evaluation tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.services.validators import FormValidator
from parrot_formdesigner.core.resolution import resolve_answer, find_field_by_uid  # TASK-1997
```

### Existing Signatures to Use
```python
# services/validators.py — class FormValidator (:92)
def validate_rules(self, form: FormSchema) -> list[str]      # :791
#   BEFORE (:819-820):
#     field_map: dict[str, FormField] = {f.field_id: f for f in all_fields}
#     field_order: dict[str, int] = {f.field_id: i for i, f in enumerate(all_fields)}
#   ref reads: ref = cond.field_id (:830, :882); post target (:866-877)
#   ordering rule: depends_on → earlier only (:839); post_depends → later only (:873)
#   numeric-operator compat checks (:848-856, :890-898) — keep, they use field objects
def _validate_operation(self, op, owner_fid, field_map, field_order, pos)  # :910-957
def check_schema(self, form: FormSchema) -> list[str]        # :959-972
def _detect_circular_dependencies(self, form) -> list[str]   # :974; graph {f.field_id: set()} (:1000)
# _collect_fields (:736) — builds all_fields ordered list; KEEP for ordering semantics

# services/rule_evaluator.py
# condition read (:118-124): raw = answers.get(condition.field_id)
# _topo_order(fields) (:355-410): field_map (:369), edges (:371), DFS (:404);
#   cycle → logger.warning + declaration order (DO NOT change to error)
# post-dep owner read: answers.get(field.field_id) (:574) — owner is a field OBJECT here;
#   read stays via field.field_id (owner is not a reference)
```

### Does NOT Exist
- ~~UID-keyed maps in validators/evaluator~~ — created HERE
- ~~`FieldCondition.field_id` as required str~~ — after TASK-1997 it is `str | None`; never assume non-None
- ~~an error-on-cycle path in rule_evaluator~~ — evaluator degrades with a warning; only the VALIDATOR errors (intentional asymmetry, spec §7)

---

## Implementation Notes

### Pattern to Follow
Spec §9 "Module 4" blueprint — exact before/after for the map builds and
condition reads.

### Key Constraints
- Human-facing error strings keep using `field_id` (`fid = field.field_id`);
  only the LOOKUP keys switch to UID.
- A condition with `field_uid=None` and `source="field"` means an unresolved
  form reached validation — report it as an error ("unresolved rule
  reference"), do not crash.
- Declaration-order semantics (`field_order`) are positional — unchanged
  logic, just UID keys.
- `resolve_answer` already handles missing fields (returns None) — rely on it.

### References in Codebase
- Spec §6 contract for exact line anchors

---

## Acceptance Criteria

- [ ] `validate_rules` catches unknown UID refs, ordering violations, numeric-compat issues — errors phrased with field_ids
- [ ] `_detect_circular_dependencies` finds cycles through UID references; cycle path readable as field_ids
- [ ] Rule evaluation reads answers correctly through UID → field_id mapping
- [ ] Evaluator cycle behavior still warn-and-degrade (test asserts no raise)
- [ ] Result maps still keyed by field_id
- [ ] `pytest packages/parrot-formdesigner/tests/ -v` passes; `ruff check` clean

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/services/test_rules_uid_rekey.py
def test_validate_rules_unknown_uid_reference(form_with_rules): ...
def test_validate_rules_ordering_still_enforced(form_with_rules): ...
def test_cycle_detection_uid_keyed(form_with_rules): ...
def test_cycle_report_names_field_ids(form_with_rules): ...
def test_evaluator_reads_answers_via_uid(form_with_rules):
    # resolve form, evaluate with answers={"field_a": 5}; condition on field_a fires
def test_evaluator_cycle_degrades_with_warning(caplog): ...
def test_unresolved_condition_reported_not_crash(): ...
def test_result_maps_keyed_by_field_id(form_with_rules): ...
```

---

## Agent Instructions

1. **Read the spec** §9 Module 4; verify TASK-1997 completed.
2. **Verify the contract** anchors (validators.py is large; re-grep line numbers).
3. **Update status** in `sdd/tasks/index/formdesigner-field-uid.json` → `"in-progress"`.
4. **Implement**, run tests, verify acceptance criteria.
5. **Move this file** to `sdd/tasks/completed/`, update index → `"done"`, fill Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
