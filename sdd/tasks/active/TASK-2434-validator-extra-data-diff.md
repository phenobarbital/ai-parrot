# TASK-2434: `ValidationResult.extra_data` + the validator's payload-side diff

**Feature**: FEAT-458 — Unknown-Field Capture Policy for Form Submissions
**Spec**: `sdd/specs/formdesigner-unknown-fields-capture.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2433
**Assigned-to**: unassigned
**Implements**: Spec section 3 Module 3

---

## Context

`FormValidator.validate()` has never looked at the payload. It iterates the
schema's fields and *pulls* each declared answer out (`services/validators.py:190`,
`data.get(field.field_id)`) — which is precisely why undeclared keys vanish today
without a trace. This task gives the validator the reverse view.

The validator **reports, it does not decide**. It reads no policy field, so it
stays platform-agnostic as its own docstring claims (`services/validators.py:101-115`)
and remains usable outside HTTP. The policy branch is TASK-2436's job.

Independent of FEAT-457.

Implements spec section 3 Module 3.

---

## Scope

- Add `extra_data: dict[str, Any] = Field(default_factory=dict)` to
  `ValidationResult` (`services/validators.py:87`), documented in its `Attributes:`
  block as the undeclared top-level payload keys — reported, never judged.
- In `validate()` (`:122`), after the per-field loop, build the declared-`field_id`
  set from the `all_fields` list already assembled at `:169-171` and call
  `compute_extra_data(data, declared_ids)`; pass the result into the
  `ValidationResult` returned at `:220-224`.
- Add a comment at the computation site recording the two ordering rules and the
  `sanitized_data.keys()` trap (see Key Constraints).
- Extend `packages/parrot-formdesigner/tests/unit/services/` with tests for the new
  behaviour (new file `test_validator_extra_data.py`).

**NOT in scope**: Reading `form.unknown_fields` — the validator MUST stay
policy-blind (spec AC16). Enforcing caps (TASK-2433 owns the function; TASK-2436
calls it). Any change to the two early returns at `:156-166`, to `validate_field`,
or to coercion. Any handler change.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py` | MODIFY | `ValidationResult.extra_data` + diff in `validate()` |
| `packages/parrot-formdesigner/tests/unit/services/test_validator_extra_data.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references. Do NOT invent an import or attribute.

### Verified Imports

```python
# Already present at services/validators.py:16-21 — do not re-add:
from ..core.schema import FormField, FormSchema, FormSection
from ..core.types import FieldType, LocalizedString
from .auth_context import AuthContext

# Already present at :10-14:
from typing import Any, Callable
from pydantic import BaseModel

# NEW import this task adds (created by TASK-2433):
from .unknown_fields import compute_extra_data

# `Field` is NOT currently imported in validators.py — the file imports only
# `BaseModel` from pydantic (verified :14). Add `Field` to that import.
```

### Existing Signatures to Use

```python
# services/validators.py:87 — exactly three fields today
class ValidationResult(BaseModel):
    is_valid: bool                    # line 96
    errors: dict[str, list[str]]      # line 97
    sanitized_data: dict[str, Any]    # line 98

# services/validators.py:101
class FormValidator:
    def __init__(self) -> None: ...   # line 118 — sets self.logger
    async def validate(              # line 122
        self,
        form: FormSchema,
        data: dict[str, Any],
        *,
        locale: str = "en",
        auth_context: AuthContext | None = None,
        location_vars: dict[str, Any] | None = None,
        visit_context: dict[str, Any] | None = None,
    ) -> ValidationResult: ...

# The exact structure inside validate() that this task edits:
#   :152-153  errors: dict[str, list[str]] = {} ; sanitized: dict[str, Any] = {}
#   :156-160  circular check -> early return with errors["__circular__"]
#   :162-166  rule-integrity check -> early return with errors["__rules__"]
#   :169-171  all_fields: list[FormField] = []
#             for section in form.sections:
#                 all_fields.extend(self._collect_fields(section))
#   :184-187  resolution = await RuleEvaluator().resolve(form, data, ...)
#   :190      for field in all_fields:          <- the PULL loop
#   :216-218  coerced = self._coerce_value(data.get(field.field_id), field)
#             if coerced is not None:
#                 sanitized[field.field_id] = coerced
#   :220-224  return ValidationResult(is_valid=len(errors) == 0, errors=errors,
#                                     sanitized_data=sanitized)

# services/validators.py:944 — RECURSIVE: flattens subsections AND nested GROUP/ARRAY children
def _collect_fields(self, section: FormSection) -> list[FormField]: ...
# services/validators.py:961
def _collect_nested_fields(self, field: FormField) -> list[FormField]: ...

# services/unknown_fields.py (TASK-2433)
def compute_extra_data(payload: dict[str, Any], declared_field_ids: set[str]) -> dict[str, Any]: ...
```

### Does NOT Exist

- ~~`ValidationResult.extra_data`~~ / ~~`ValidationResult.unknown_keys`~~ — the
  model has exactly three fields (`:96-98`).
- ~~Any payload-key iteration in `validate()`~~ — it only ever pulls by declared
  `field_id`. There is no existing loop over `data.keys()` to extend.
- ~~`FormValidator.unknown_fields_policy`~~ or any policy attribute on the
  validator — does not exist and must NOT be added (spec AC16).
- ~~`Field` imported in `validators.py`~~ — only `BaseModel` is imported from
  pydantic today (`:14`). You must add `Field`.
- ~~`FormSchema.iter_all_fields()` as the traversal to use~~ — it exists
  (`core/schema.py:376`) but its docstring says it is **layout order only** and
  does NOT recurse into GROUP `children` or ARRAY `item_template`. Using it would
  misclassify declared nested fields as extras. Use `all_fields` from `:169-171`.
- ~~`walk_fields`~~ — exists (`core/schema.py:175`) and is the canonical recursive
  traversal, but `validators.py` is not yet re-keyed onto it (its own docstring
  says TASK-1998/1999 will do that, not this task). Use `all_fields`.

---

## Implementation Notes

### Pattern to Follow

```python
# services/validators.py — inside validate(), after the `for field in all_fields:` loop
# and immediately before the return at :220.
#
# Two ordering rules the caller guarantees and this comment must record:
#   1. `data` arrives AFTER _extract_visit_context (api/handlers.py:390), so the
#      reserved `visit_context` envelope key is already gone and is never an extra.
#   2. `data` arrives AFTER the onBeforeSubmit hook, which may replace the payload
#      wholesale (api/handlers.py:1540), so a hook injecting declared fields is
#      not punished.
#
# And the trap this MUST avoid: derive the id set from `all_fields`, NEVER from
# `sanitized.keys()`. The loop above omits a declared field whose coerced value is
# None (:216-218); keying off `sanitized` would reclassify every empty optional
# answer as caller junk.
declared_ids = {f.field_id for f in all_fields}
extra_data = compute_extra_data(data, declared_ids)

return ValidationResult(
    is_valid=len(errors) == 0,
    errors=errors,
    sanitized_data=sanitized,
    extra_data=extra_data,
)
```

### Key Constraints

- `extra_data` defaults to `{}` via `Field(default_factory=dict)` so every existing
  `ValidationResult(...)` construction site keeps working unchanged.
- The two **early returns** at `:156-160` (`__circular__`) and `:162-166`
  (`__rules__`) return before `all_fields` exists. Leave them alone — they keep
  the default `{}`. Do not attempt to compute extras there.
- Extras alone MUST NOT flip `is_valid`. `is_valid` stays `len(errors) == 0`.
- Async signature unchanged; no new awaits.

### References in Codebase

- `services/validators.py:169-171` — where `all_fields` is built (reuse it, do not
  re-traverse).
- `services/validators.py:216-218` — the `coerced is not None` omission that makes
  `sanitized.keys()` the wrong source.
- `services/validators.py:87-98` — the model to extend.

---

## Acceptance Criteria

- [ ] `ValidationResult()` built with only the three original fields still works
      and yields `extra_data == {}`.
- [ ] `validate()` populates `extra_data` with every undeclared top-level payload key.
- [ ] `extra_data == {}` when the payload matches the schema exactly.
- [ ] A declared field whose coerced value is `None` is NOT reported as an extra
      (spec AC8).
- [ ] GROUP `children` and ARRAY `item_template` `field_id`s are NOT reported as
      extras (spec AC9).
- [ ] `extra_data` is identical for the same payload regardless of
      `form.unknown_fields`, and `grep -c "unknown_fields" services/validators.py`
      returns 0 (spec AC16).
- [ ] Extras alone do not change `is_valid`.
- [ ] The `__circular__` and `__rules__` early returns still return with
      `extra_data == {}`.
- [ ] Tests pass: `pytest packages/parrot-formdesigner/tests/unit/services/ -v`
- [ ] Existing validator tests still pass (no regression):
      `pytest packages/parrot-formdesigner/tests/ -k validator -v`
- [ ] No linting errors: `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/services/test_validator_extra_data.py
import pytest
from parrot_formdesigner.services.validators import FormValidator, ValidationResult


def test_validation_result_extra_data_defaults_empty():
    """Existing three-field construction sites keep working."""
    r = ValidationResult(is_valid=True, errors={}, sanitized_data={})
    assert r.extra_data == {}


class TestValidateReportsExtras:
    async def test_reports_undeclared_keys(self, simple_form):
        result = await FormValidator().validate(
            simple_form, {"name": "Ana", "legacy_id": 42, "_client_ms": 1180}
        )
        assert result.extra_data == {"legacy_id": 42, "_client_ms": 1180}
        assert "legacy_id" not in result.sanitized_data

    async def test_empty_when_payload_matches_schema(self, simple_form):
        result = await FormValidator().validate(simple_form, {"name": "Ana"})
        assert result.extra_data == {}

    async def test_declared_but_empty_is_not_an_extra(self, form_with_optional_field):
        """Spec AC8 — the sanitized_data.keys() trap."""
        result = await FormValidator().validate(form_with_optional_field, {"note": None})
        assert result.extra_data == {}

    async def test_group_and_array_children_not_extras(self, form_with_group_and_array):
        """Spec AC9 — the recursive traversal is used."""
        result = await FormValidator().validate(
            form_with_group_and_array,
            {"address_street": "Main 1", "items": [], "junk": 1},
        )
        assert result.extra_data == {"junk": 1}

    async def test_policy_blind(self, simple_form):
        """Spec AC16 — same result under every policy."""
        payload = {"name": "Ana", "junk": 1}
        results = []
        for policy in ("drop", "keep", "reject"):
            form = simple_form.model_copy(update={"unknown_fields": policy})
            results.append((await FormValidator().validate(form, payload)).extra_data)
        assert results[0] == results[1] == results[2] == {"junk": 1}

    async def test_extras_do_not_affect_is_valid(self, simple_form):
        result = await FormValidator().validate(simple_form, {"name": "Ana", "junk": 1})
        assert result.is_valid is True

    async def test_circular_early_return_has_empty_extras(self, circular_form):
        result = await FormValidator().validate(circular_form, {"junk": 1})
        assert result.is_valid is False
        assert "__circular__" in result.errors
        assert result.extra_data == {}
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/formdesigner-unknown-fields-capture.spec.md` for full context.
2. **Check dependencies** — verify every `Depends-on` task is in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** before writing ANY code: confirm each import
   still resolves and each listed signature still has the listed attributes. Line
   numbers were verified on `dev` at `72490fa14` (2026-08-24) and WILL drift once
   FEAT-456/FEAT-457 land — re-`grep` rather than trusting a number.
4. **Update status** in `sdd/tasks/index/formdesigner-unknown-fields-capture.json` → `"in-progress"`.
5. **Implement** following the scope and contract above. Nothing outside scope.
6. **Verify** every acceptance criterion.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update the index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
