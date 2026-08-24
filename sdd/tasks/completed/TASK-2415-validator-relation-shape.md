# TASK-2415: `FormValidator` Shape Validation for Relational Submissions

**Feature**: FEAT-456 — Relational Field Cardinality for parrot-formdesigner
**Spec**: `sdd/specs/formbuilder-fieldtype-cardinality.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2411
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6. Submissions for reference-mode relational fields must be
shape-checked: a scalar ID for `cardinality="one"`, a list of IDs for
`cardinality="many"`. **Shape only** — no existence checks, no I/O (resolved
in brainstorm; the target system verifies existence). Embed-mode values flow
through the existing ARRAY recursive path unchanged.

---

## Scope

- In `services/validators.py` (`FormValidator.validate_field`), when
  `field.relation` is set with `mode="reference"`:
  - `cardinality="one"`: reject lists/dicts; accept scalar str/int IDs
    (non-empty after str()); produce a field error otherwise.
  - `cardinality="many"`: reject scalars/dicts; accept a list of scalar
    IDs; reject lists containing non-scalars.
- Embed mode: NO new logic — assert-by-test that ARRAY recursion handles it.
- No I/O: the new paths must not touch `AuthContext`, aiohttp, or callbacks.
- Unit tests for all shape combinations.

**NOT in scope**: existence/UNIQUE/ASYNC_REMOTE checks; changes to
`validate()` orchestration or `validate_rules`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py` | MODIFY | reference shape checks in `validate_field` |
| `packages/parrot-formdesigner/tests/unit/services/test_validator_relation.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.services.validators import FormValidator  # services/validators.py:101
from parrot_formdesigner.core.relations import EntityRef, RelationSpec  # TASK-2410
```

### Existing Signatures to Use
```python
# services/validators.py (verified 2026-08-24):
class FormValidator:                                   # line 101
    def __init__(self) -> None: ...                    # line 118 (only self.logger)
    async def validate(self, form: FormSchema, data: dict[str, Any], *,
                       locale: str = "en",
                       auth_context: AuthContext | None = None,
                       location_vars: dict[str, Any] | None = None,
                       visit_context: dict[str, Any] | None = None,
                       ) -> ValidationResult:          # line 122
    async def validate_field(self, field: FormField, value: Any, *,
                             all_data: dict[str, Any] | None = None,
                             locale: str = "en",
                             auth_context: AuthContext | None = None,
                             required: bool | None = None,
                             ) -> list[str]:           # line 228
    # validate_field returns a list of error message strings (empty = valid).
```

### Does NOT Exist
- ~~`FormValidator.validate_relation()`~~ — add the logic inside
  `validate_field`'s dispatch, not as a new public method (keep the surface).
- ~~An existence-check callback for relations~~ — explicitly rejected in
  brainstorm; do not wire ASYNC_REMOTE/UNIQUE machinery to relations.
- ~~`RelationSpec.id_type`~~ — IDs are untyped scalars (str/int) in v1.

---

## Implementation Notes

### Pattern to Follow
Read `validate_field`'s existing per-type shape checks (e.g. how
MULTI_SELECT list-ness is validated) before adding the relation branch —
reuse its error-message construction/localization helpers so messages look
native.

### Key Constraints
- Relation shape errors append to the same `list[str]` return, keyed by the
  caller as usual — no new result type.
- A relational field with `relation=None`… cannot exist (it's just
  non-relational); guard only on `field.relation is not None and
  field.relation.mode == "reference"`.
- `None`/absent value handling stays governed by the existing
  required-field logic — do not duplicate requiredness checks.

---

## Acceptance Criteria

- [ ] cardinality="one": list value → error; scalar str/int → ok
- [ ] cardinality="many": scalar → error; list of scalars → ok; list with
      dict/list inside → error
- [ ] Embed mode: existing ARRAY recursion validates rows (test proves it,
      no new code path)
- [ ] No I/O in the new branches (no auth_context/aiohttp usage)
- [ ] Tests pass: `pytest packages/parrot-formdesigner/tests/unit/services/test_validator_relation.py -v`
- [ ] Existing validator suite green
- [ ] `ruff check` clean

---

## Test Specification

```python
import pytest
from parrot_formdesigner.core.schema import FormField
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.core.relations import EntityRef, RelationSpec
from parrot_formdesigner.services.validators import FormValidator

ONE = RelationSpec(cardinality="one",
                   target=EntityRef(namespace="odoo", entity="res.partner"))
MANY = RelationSpec(cardinality="many",
                    target=EntityRef(namespace="db", entity="public.tags"))


@pytest.fixture
def customer():
    return FormField(field_id="customer", field_type=FieldType.SELECT,
                     label="Customer", relation=ONE)


@pytest.fixture
def tags():
    return FormField(field_id="tags", field_type=FieldType.MULTI_SELECT,
                     label="Tags", relation=MANY)


async def test_one_accepts_scalar(customer):
    assert await FormValidator().validate_field(customer, "42") == []


async def test_one_rejects_list(customer):
    assert await FormValidator().validate_field(customer, ["42"]) != []


async def test_many_accepts_id_list(tags):
    assert await FormValidator().validate_field(tags, ["1", "2"]) == []


async def test_many_rejects_scalar(tags):
    assert await FormValidator().validate_field(tags, "1") != []
```

---

## Agent Instructions

1. Verify TASK-2411 is in `sdd/tasks/completed/`; read spec §3 Module 6.
2. Read `validate_field`'s existing dispatch BEFORE coding; verify the contract.
3. Update index → `in-progress`; implement, test, lint.
4. Move this file to `sdd/tasks/completed/`, update index → `done`, fill Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-08-24
**Notes**: Added `FormValidator._validate_relation_shape()` and called it
from `validate_field()` for `field.relation.mode == "reference"`, running
BEFORE type coercion (coercion is deliberately lossy for the
SELECT/MULTI_SELECT-family types and would mask shape mismatches).
`cardinality="one"` rejects list/dict, requires scalar str/int;
`cardinality="many"` requires a list of scalar str/int, rejecting scalars
and lists containing dict/list. No I/O in the new branch. 11 new tests
pass, including one proving embed-mode relations take no new code path
(guarded on `mode == "reference"`). Full validator-related suite (84
tests) and full unit suite show identical results to baseline (no
regressions). `ruff check` clean on new lines (14 pre-existing findings
elsewhere in validators.py, untouched by this diff, left as-is).

**Deviations from spec**: none
