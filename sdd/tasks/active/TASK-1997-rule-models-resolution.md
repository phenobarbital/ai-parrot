# TASK-1997: Rule models field_uid + build-time resolution pass (core/resolution.py)

**Feature**: FEAT-393 — Stable UUID-Based Field Identity (field_uid)
**Spec**: `sdd/specs/formdesigner-field-uid.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1996
**Assigned-to**: unassigned

---

## Context

Implements Module 3 of FEAT-393 (spec §3, blueprint §9). Rules keep being
AUTHORED by `field_id` (humans, YAML, LLM) but are STORED as `field_uid`
references. This task creates the shared resolution pass plus the canonical
UID lookup helpers every later task consumes.

---

## Scope

- `core/constraints.py`: `FieldCondition.field_id` becomes `str | None = None`
  (authored input); add `FieldCondition.field_uid: uuid.UUID | None = None`
  (authoritative after resolution). `DependencyOperation.operands/target` and
  `PostDependency.target` keep their `list[str]`/`str` types — update
  docstrings to "canonical UUID string after resolution".
- CREATE `core/resolution.py` with `resolve_rule_references(form)`,
  `find_field_by_uid(form, field_uid)`, `resolve_answer(form, field_uid, answers)`
  — bodies per spec §9 Module 3 (idempotent: UID-shaped refs validate-and-pass).
- Export the three helpers from `parrot_formdesigner.core` `__init__`.
- Unit tests per spec §4 (Module 3 rows).

**NOT in scope**: re-keying FormValidator/RuleEvaluator (TASK-1998); calling
the pass from extractors/APIs (TASK-1999/2001).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/constraints.py` | MODIFY | FieldCondition.field_uid; docstrings |
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/resolution.py` | CREATE | resolution pass + lookup helpers |
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/__init__.py` | MODIFY | export new helpers |
| `packages/parrot-formdesigner/tests/unit/core/test_resolution.py` | CREATE | resolution tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.core.constraints import (
    DependencyRule, FieldCondition, DependencyOperation, PostDependency,
)
from parrot_formdesigner.core.schema import FormField, FormSchema, walk_fields  # walk_fields from TASK-1996
```

### Existing Signatures to Use
```python
# core/constraints.py
class FieldCondition(BaseModel):        # :144-164
    field_id: str                       # :156 — becomes str | None here
    source: str = "field"               # :163 — location_variable/visit_context use `key`, NOT field refs
    key: str | None = None
    # NOTE :153-154 — deliberately NO extra="forbid" (forward compat). PRESERVE.
class DependencyRule(BaseModel):        # :167-188 — conditions, logic, effect, operations
class DependencyOperation(BaseModel):   # :191-271
    operands: list[str]                 # :233
    target: str                         # :234
    # _non_empty_operands (:237-253) / _non_empty_target (:255-271) — keep; shape-only
class PostDependency(BaseModel):        # :274+ — target (:282), conditions, operation
# FormField.depends_on (:85), FormField.post_depends (:86)
```

### Does NOT Exist
- ~~`core/resolution.py`~~ — created HERE
- ~~`resolve_rule_references` / `find_field_by_uid` / `resolve_answer`~~ — created HERE
- ~~a FEAT-389 "FormAssembler" module in parrot_formdesigner~~ — TASK-1968 built a
  FormAssembler in ai-parrot core (`parrot/forms/tools/create_form.py` context), NOT a
  formdesigner assembly boundary; `core/resolution.py` is the home (verify at start —
  if FEAT-389's merge added an assembly module, extend it instead and note the deviation)

---

## Implementation Notes

### Pattern to Follow
Spec §9 "Module 3" blueprint is authoritative — `resolve_rule_references`
(with `_uid_for` and `_resolve_condition` inner helpers), `find_field_by_uid`,
`resolve_answer` bodies are given verbatim.

### Key Constraints
- Idempotency is mandatory: re-running resolution on an already-resolved form
  must be a no-op (UID-shaped refs validate against known UIDs and pass).
- `source != "field"` conditions (location_variable / visit_context) have NO
  field reference — skip them.
- Empty-string references raise (this kills the YAML extractor's silent `""`
  default downstream).
- Error messages name the owning field's `field_id` and the bad reference —
  they surface to LLM retry loops (TASK-2001) and humans.
- Duplicate `field_id` in the form → `ValueError` before any rewrite.

### References in Codebase
- `services/validators.py:791-906` — current reference checks (error-message tone to match)

---

## Acceptance Criteria

- [ ] `resolve_rule_references` rewrites conditions/operands/targets for depends_on AND post_depends (incl. post.operation)
- [ ] Unknown / ambiguous / empty references → ValueError naming owner + reference
- [ ] Idempotent: `resolve_rule_references(resolve_rule_references(form))` == same refs
- [ ] `find_field_by_uid` reaches fields inside subsections, GROUP children, ARRAY item_template
- [ ] `pytest packages/parrot-formdesigner/tests/unit/core/ -v` passes
- [ ] `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/core/`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/core/test_resolution.py
import pytest
from parrot_formdesigner.core.resolution import (
    resolve_rule_references, find_field_by_uid, resolve_answer,
)

def test_resolves_depends_on_condition(form_with_rules): ...
def test_resolves_operands_and_targets(form_with_rules): ...
def test_resolves_post_depends(form_with_rules): ...
def test_unknown_reference_errors(form_with_rules):
    # pytest.raises(ValueError, match="references unknown field_id")
def test_empty_reference_errors(): ...
def test_duplicate_field_id_blocks_resolution(): ...
def test_resolution_idempotent(form_with_rules): ...
def test_non_field_sources_skipped():
    """source='location_variable' conditions keep key-based addressing, untouched."""
def test_find_field_by_uid_nested(form_with_nested_fields): ...
def test_resolve_answer_reads_by_field_id(form_with_rules): ...
```

---

## Agent Instructions

1. **Read the spec** §9 Module 3; verify TASK-1996 is completed.
2. **Verify the contract**; check whether FEAT-389's merge introduced an assembly module (see Does NOT Exist).
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
