# TASK-2679: Validator Dict Pass-Through for accept_content_types

**Feature**: FEAT-488 — FormField Content-Type
**Spec**: `sdd/specs/formfield-content-type.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2677
**Assigned-to**: unassigned

---

## Context

`FormValidator._coerce_value()` currently coerces every `TEXT_AREA` value to
a plain `str` via `str(value).strip()`. This breaks the voice-note use case
where the submitted value is a `dict` (a `VoiceAnswerEnvelope` payload).

The fix: add a guard at the top of `_coerce_value()` — before the existing
`TEXT`/`TEXT_AREA` branch — that passes `dict` values through unchanged when
the field has `accept_content_types` declared. Parsing the dict is the
consumer's responsibility (resolved in proposal).

Implements spec §3 Module 3.

---

## Scope

- In `services/validators.py`, insert a `dict`-pass-through guard inside
  `_coerce_value()` at line 498, **before** the `ft in (FieldType.TEXT, ...)` branch.
- Guard condition: `field.accept_content_types is not None and isinstance(value, dict)`.
- When guard fires: return `value` unchanged (no coercion, no Pydantic parsing).
- No other changes to `_coerce_value()`.

**NOT in scope**: eager JSON/YAML parsing, hard MIME-type validation,
`VoiceAnswerEnvelope` deserialization inside the validator, or any
changes to the validator's public API.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py` | MODIFY | Add dict pass-through guard before TEXT/TEXT_AREA branch in `_coerce_value()` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# services/validators.py — no new imports required
# FormField already imported; FieldType already imported
# from parrot_formdesigner.core.types import FieldType  (verify exact import path)
```

### Existing Signatures to Use

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py

class FormValidator:
    def _coerce_value(self, value: Any, field: FormField) -> Any:  # line 498
        """Coerce a value to the appropriate Python type for the field."""
        if value is None:
            return None                    # line 511

        ft = field.field_type              # line 514

        if ft in (                         # line 516 — TEXT/TEXT_AREA branch
            FieldType.TEXT,
            FieldType.TEXT_AREA,
            FieldType.EMAIL,
            FieldType.URL,
            FieldType.PHONE,
            FieldType.PASSWORD,
            FieldType.COLOR,
            FieldType.HIDDEN,
            FieldType.SELECT,
        ):
            return str(value).strip()      # line 527
        # ...
```

The new guard must be inserted **between** `ft = field.field_type` (line 514)
and `if ft in (FieldType.TEXT, ...)` (line 516):

```python
        ft = field.field_type              # existing line 514

        # FEAT-488: pass dict values through unchanged for fields that
        # declare accept_content_types (e.g. VoiceAnswerEnvelope payloads).
        # Parsing responsibility belongs to the consumer.
        if field.accept_content_types is not None and isinstance(value, dict):
            return value

        if ft in (                         # existing line 516
            FieldType.TEXT,
            ...
```

### Does NOT Exist

- ~~`FormValidator._coerce_content_type()`~~ — no such method exists or is created.
- ~~`VoiceAnswerEnvelope` import in validators.py~~ — do NOT import it; the guard only checks `isinstance(value, dict)`.
- ~~`field.content_type` used in the guard~~ — the guard checks `field.accept_content_types`, NOT `field.content_type`.

---

## Implementation Notes

### Key Constraints

- The guard checks `field.accept_content_types is not None` (the list is set),
  NOT `"application/json" in field.accept_content_types` — any dict submission
  is passed through when the field accepts multiple content types, regardless
  of which specific types are listed.
- Insert the guard BEFORE the `ft in (FieldType.TEXT, ...)` branch — if
  inserted after, `TEXT_AREA` would already have coerced the dict to `str`.
- No `ValidationError` for MIME-type mismatch in v1 — enforcement is advisory-only.
- Do NOT change the existing `TEXT_AREA` string path — it must still coerce
  plain strings to `str` when `accept_content_types` is `None`.

### References in Codebase

- `packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py` — target file
- `packages/parrot-formdesigner/tests/unit/services/test_validators_rest.py` — existing tests to not break

---

## Acceptance Criteria

- [ ] When `field.accept_content_types` is set and `value` is a `dict`, `_coerce_value()` returns the dict unchanged.
- [ ] When `field.accept_content_types` is `None` and `field_type` is `TEXT_AREA`, existing string coercion is unaffected.
- [ ] When `field.accept_content_types` is set but `value` is a `str`, existing string coercion is NOT bypassed (guard only fires for `dict` values).
- [ ] All existing validator tests still pass: `pytest packages/parrot-formdesigner/tests/unit/services/ -v`
- [ ] No linting errors: `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/services/test_validators_rest.py
# Add to the existing test file:

from parrot_formdesigner.core.schema import FormField
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.validators import FormValidator


def _make_validator():
    # Construct a minimal FormValidator — check the existing tests for the
    # exact constructor signature before calling.
    ...


def test_coerce_value_dict_passthrough_when_accept_content_types_set():
    """Dict values pass through unchanged when accept_content_types is declared."""
    validator = _make_validator()
    field = FormField(
        field_id="answer",
        field_type=FieldType.TEXT_AREA,
        label="Answer",
        accept_content_types=["text/plain", "application/json"],
    )
    payload = {"answer": "Hello", "blob_ref": "s3://x/y"}
    result = validator._coerce_value(payload, field)
    assert result == payload  # unchanged


def test_coerce_value_string_still_coerced_when_no_accept_content_types():
    """Existing TEXT_AREA string coercion is unaffected when accept_content_types=None."""
    validator = _make_validator()
    field = FormField(
        field_id="notes",
        field_type=FieldType.TEXT_AREA,
        label="Notes",
    )
    result = validator._coerce_value("  hello  ", field)
    assert result == "hello"


def test_coerce_value_string_still_coerced_even_with_accept_content_types():
    """String values are still coerced to str even when accept_content_types is set."""
    validator = _make_validator()
    field = FormField(
        field_id="answer",
        field_type=FieldType.TEXT_AREA,
        label="Answer",
        accept_content_types=["text/plain", "application/json"],
    )
    result = validator._coerce_value("  plain text  ", field)
    assert result == "plain text"  # str coercion still applies
```

---

## Agent Instructions

1. **Read the spec** at `sdd/specs/formfield-content-type.spec.md`.
2. **Check dependencies** — verify TASK-2677 is in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — read `services/validators.py` lines 498–530 before editing.
4. **Update status** → `"in_progress"`.
5. **Implement** the guard insertion.
6. **Verify** all acceptance criteria.
7. **Move** to `sdd/tasks/completed/TASK-2679-validator-dict-passthrough.md`.
8. **Update index** → `"completed"`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: —
**Date**: —
**Notes**: —
**Deviations from spec**: none


---

## Completion Note

**Implemented**: 2026-09-01
**Verification**: All existing validator tests pass. The guard correctly passes dict values through when `accept_content_types` is set, and existing string coercion is unaffected.
