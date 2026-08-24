# TASK-2433: `services/unknown_fields.py` — extras computation and cap enforcement

**Feature**: FEAT-458 — Unknown-Field Capture Policy for Form Submissions
**Spec**: `sdd/specs/formdesigner-unknown-fields-capture.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned
**Implements**: Spec section 3 Module 2

---

## Context

The two functions that carry all the subtle logic in FEAT-458, deliberately
isolated in a new module with no form, no handler, and no database — so the cases
that would otherwise be hard to reach (a declared-but-empty answer, a nested
GROUP child, a payload one byte over the cap) are plain unit tests.

This task is fully independent of FEAT-457 and can start immediately.

Implements spec section 3 Module 2.

---

## Scope

- Create `services/unknown_fields.py`.
- Define `MAX_EXTRA_KEYS: int = 256` and `MAX_EXTRA_BYTES: int = 256 * 1024`
  (256 KiB). **Module-level constants only** — resolved: no per-form override and
  no `FormAPIHandler` constructor knob.
- Define `ExtrasCapExceeded(ValueError)` carrying `limit: Literal["keys", "bytes"]`,
  `actual: int`, `maximum: int`, and a message naming which cap was exceeded.
- Implement `compute_extra_data(payload, declared_field_ids) -> dict[str, Any]`:
  return the entries of `payload` whose key is not in `declared_field_ids`.
  Pure, synchronous, order-preserving, and it must NOT mutate `payload`.
- Implement `enforce_extras_cap(extras, *, max_keys=MAX_EXTRA_KEYS,
  max_bytes=MAX_EXTRA_BYTES) -> None`: raise `ExtrasCapExceeded` when
  `len(extras) > max_keys` or `len(json.dumps(extras).encode("utf-8")) > max_bytes`.
  It MUST NOT truncate and MUST NOT mutate its argument.
- Write unit tests in `packages/parrot-formdesigner/tests/unit/services/test_unknown_fields.py`.

**NOT in scope**: Reading `form.unknown_fields` — this module is policy-blind and
must not import `FormSchema`. Calling either function from the validator
(TASK-2434) or the handler (TASK-2436). Any storage or HTTP concern.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/unknown_fields.py` | CREATE | Constants, exception, two pure functions |
| `packages/parrot-formdesigner/tests/unit/services/test_unknown_fields.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references. Do NOT invent an import or attribute.

### Verified Imports

```python
# Standard library only — this module intentionally has NO parrot_formdesigner imports.
import json
from typing import Any, Literal
```

### Existing Signatures to Use

```python
# None. This is a new leaf module with no dependencies on the package.
#
# For CONTEXT ONLY — the caller that will consume it (TASK-2434) builds the
# declared-field_id set from this existing recursive traversal:
#   services/validators.py:944  def _collect_fields(self, section: FormSection) -> list[FormField]
#   services/validators.py:961  def _collect_nested_fields(self, field: FormField) -> list[FormField]
# Do NOT import or call them from this module.
```

### Does NOT Exist

- ~~`services/unknown_fields.py`~~ — this task creates it.
- ~~`ExtrasCapExceeded`~~, ~~`MAX_EXTRA_KEYS`~~, ~~`MAX_EXTRA_BYTES`~~,
  ~~`compute_extra_data`~~, ~~`enforce_extras_cap`~~ — none exist anywhere.
- ~~A shared "extras" helper elsewhere in the package~~ — there is no existing
  module for this; do not try to extend `services/_db_utils.py` or
  `services/validators.py` instead.
- ~~`RestCallbackInput.extra_fields`~~ — unrelated
  (`services/rest_field_resolver.py:235`); do not import or mirror it.

---

## Implementation Notes

### Pattern to Follow

```python
def compute_extra_data(
    payload: dict[str, Any],
    declared_field_ids: set[str],
) -> dict[str, Any]:
    """Return the payload's top-level keys that no declared field_id covers.

    Args:
        payload: The submitted answers, AFTER `visit_context` extraction and
            AFTER the `onBeforeSubmit` hook may have replaced them.
        declared_field_ids: Every `field_id` the schema declares, from the
            RECURSIVE traversal (GROUP `children` and ARRAY `item_template`
            included). MUST NOT be derived from `sanitized_data.keys()`.

    Returns:
        A new dict of the undeclared entries. Empty dict when there are none.
    """
    return {k: v for k, v in payload.items() if k not in declared_field_ids}
```

### Key Constraints

- **Never truncate.** `enforce_extras_cap` raises or returns `None`; it has no
  "trim to fit" branch. Truncation would reintroduce the silent-loss defect
  FEAT-458 exists to remove.
- **Measure bytes on the encoded JSON**, `len(json.dumps(extras).encode("utf-8"))`,
  not `len(str(extras))` — a multi-byte payload must not slip past the cap.
- Check the key-count cap BEFORE serializing, so a 100k-key payload is rejected
  without paying for `json.dumps`.
- If `extras` is not JSON-serializable, let `TypeError` propagate — the payload
  came from `request.json()` and cannot contain non-JSON types, so a `TypeError`
  here means a programming error upstream, not user input.
- Google-style docstrings and full type hints. No logger needed (pure functions).

### References in Codebase

- `services/_identifiers.py` — precedent for a small, dependency-free helper
  module under `services/`.
- `services/validators.py:944,961` — the traversal whose output feeds
  `declared_field_ids` (context only; do not import).

---

## Acceptance Criteria

- [ ] `compute_extra_data({"a":1,"b":2}, {"a"}) == {"b": 2}`.
- [ ] `compute_extra_data` returns `{}` (not `None`) for an exact-match payload.
- [ ] `compute_extra_data` does not mutate its `payload` argument.
- [ ] `enforce_extras_cap` accepts exactly 256 keys and exactly 256 KiB (spec AC6).
- [ ] 257 keys raises `ExtrasCapExceeded` with `limit == "keys"`, `actual == 257`,
      `maximum == 256`.
- [ ] 256 KiB + 1 byte serialized raises `ExtrasCapExceeded` with `limit == "bytes"`.
- [ ] The input dict is unmodified after a raise — no truncation (spec AC5).
- [ ] Byte measurement uses UTF-8 encoded length (a multi-byte string counts its
      real byte cost).
- [ ] The module imports nothing from `parrot_formdesigner` — verified by
      `grep -c "parrot_formdesigner" services/unknown_fields.py` returning 0.
- [ ] Tests pass: `pytest packages/parrot-formdesigner/tests/unit/services/test_unknown_fields.py -v`
- [ ] No linting errors: `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/services/unknown_fields.py`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/services/test_unknown_fields.py
import json
import pytest
from parrot_formdesigner.services.unknown_fields import (
    MAX_EXTRA_BYTES,
    MAX_EXTRA_KEYS,
    ExtrasCapExceeded,
    compute_extra_data,
    enforce_extras_cap,
)


class TestComputeExtraData:
    def test_basic(self):
        assert compute_extra_data({"name": "Ana", "legacy_id": 42}, {"name"}) == {"legacy_id": 42}

    def test_exact_match_returns_empty_dict(self):
        assert compute_extra_data({"name": "Ana"}, {"name"}) == {}

    def test_declared_but_absent_field_is_not_an_extra(self):
        """A declared field missing from the payload contributes nothing."""
        assert compute_extra_data({}, {"name", "email"}) == {}

    def test_declared_but_empty_value_is_not_an_extra(self):
        """The sanitized_data.keys() trap: a declared field whose value is None
        is DECLARED, so it must never be reported as caller junk (spec AC8)."""
        assert compute_extra_data({"name": None}, {"name"}) == {}

    def test_nested_field_ids_are_known(self):
        """GROUP children / ARRAY item_template ids count as declared (spec AC9)."""
        declared = {"address", "address_street", "address_city"}
        assert compute_extra_data({"address_street": "x", "junk": 1}, declared) == {"junk": 1}

    def test_does_not_mutate_payload(self):
        payload = {"a": 1, "b": 2}
        compute_extra_data(payload, {"a"})
        assert payload == {"a": 1, "b": 2}


class TestEnforceExtrasCap:
    def test_under_key_limit_passes(self):
        enforce_extras_cap({f"k{i}": i for i in range(MAX_EXTRA_KEYS - 1)})

    def test_at_key_limit_passes(self):
        """Exactly at the cap is accepted (spec AC6)."""
        enforce_extras_cap({f"k{i}": i for i in range(MAX_EXTRA_KEYS)})

    def test_over_key_limit_raises(self):
        extras = {f"k{i}": i for i in range(MAX_EXTRA_KEYS + 1)}
        with pytest.raises(ExtrasCapExceeded) as exc:
            enforce_extras_cap(extras)
        assert exc.value.limit == "keys"
        assert exc.value.actual == MAX_EXTRA_KEYS + 1
        assert exc.value.maximum == MAX_EXTRA_KEYS

    def test_over_byte_limit_raises(self):
        extras = {"blob": "x" * (MAX_EXTRA_BYTES + 1)}
        with pytest.raises(ExtrasCapExceeded) as exc:
            enforce_extras_cap(extras)
        assert exc.value.limit == "bytes"

    def test_multibyte_counted_as_utf8_bytes(self):
        """A 2-byte-per-char string must not slip past the byte cap."""
        extras = {"blob": "\u00f1" * MAX_EXTRA_BYTES}
        assert len(json.dumps(extras).encode("utf-8")) > MAX_EXTRA_BYTES
        with pytest.raises(ExtrasCapExceeded):
            enforce_extras_cap(extras)

    def test_never_truncates(self):
        """The input is untouched after a raise (spec AC5)."""
        extras = {f"k{i}": i for i in range(MAX_EXTRA_KEYS + 5)}
        snapshot = dict(extras)
        with pytest.raises(ExtrasCapExceeded):
            enforce_extras_cap(extras)
        assert extras == snapshot

    def test_empty_extras_passes(self):
        enforce_extras_cap({})
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
