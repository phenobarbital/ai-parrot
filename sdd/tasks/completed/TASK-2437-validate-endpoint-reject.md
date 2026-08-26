# TASK-2437: Dry-run `validate` endpoint honours `reject`

**Feature**: FEAT-458 — Unknown-Field Capture Policy for Form Submissions
**Spec**: `sdd/specs/formdesigner-unknown-fields-capture.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2432, TASK-2433, TASK-2434
**Assigned-to**: unassigned
**Implements**: Spec section 3 Module 6

---

## Context

`POST /api/v1/forms/{form_uid}/validate` (`api/handlers.py:993`) exists so a client
can check a payload before committing to a submission. If it returns `200` for a
payload that `/submit` would then `422`, the endpoint is actively misleading — the
client learns about the policy only by failing the real thing.

Small and self-contained, but it shares `api/handlers.py` with TASK-2436, so it is
sequential with it rather than parallel.

Implements spec section 3 Module 6.

---

## Scope

- In `FormAPIHandler.validate` (`:993`), after the existing `validate()` call
  (`:1010`), treat a non-empty `result.extra_data` as a failure when
  `form.unknown_fields is UnknownFieldsPolicy.REJECT`: return `422` with
  `errors["__unknown__"]` listing the offending key names, merged alongside any
  field errors already in `result.errors`.
- Leave `drop` and `keep` responses byte-identical to today.
- Extend the route's docstring to mention the policy.
- Write unit tests in `packages/parrot-formdesigner/tests/unit/api/test_validate_endpoint_unknown_fields.py`.

**NOT in scope**: `submit_data` (TASK-2436). Any cap enforcement — the dry-run
route does not store anything, so `keep` needs no cap check here; the cap belongs
to the write path. `save_partial`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` | MODIFY | `reject` handling in the dry-run route |
| `packages/parrot-formdesigner/tests/unit/api/test_validate_endpoint_unknown_fields.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references. Do NOT invent an import or attribute.

### Verified Imports

```python
# NEW import (TASK-2432) — if TASK-2436 already added it, reuse it, do not duplicate:
from ..core.schema import UnknownFieldsPolicy
```

### Existing Signatures to Use

```python
# api/handlers.py:993 — the ENTIRE current method, verbatim:
async def validate(self, request: web.Request) -> web.Response:
    """POST /api/v1/forms/{form_uid}/validate — Validate form submission."""
    form_uid = extract_form_uid(request)                       # :995
    tenant = self._get_tenant(request)                         # :996
    form = await self.registry.get(form_uid, tenant=tenant)    # :997
    if form is None:
        return JSONResponse({"error": f"Form '{form_uid}' not found"}, status=404)
    self._assert_form_tenant(form, tenant)                     # :1000
    # route ALSO mounted tenant="public" (FEAT-421)
    enforce_membership_unless_public(request, form, tenant)    # :1002
    try:
        body = await request.json()                            # :1004
    except (json.JSONDecodeError, ValueError):
        return JSONResponse({"error": "Invalid JSON body"}, status=400)

    data, visit_context = self._extract_visit_context(form, body)          # :1009
    result = await self.validator.validate(form, data, visit_context=visit_context)  # :1010
    status = 200 if result.is_valid else 422                                # :1011
    return JSONResponse(
        {"is_valid": result.is_valid, "errors": result.errors},             # :1013
        status=status,
    )

# api/handlers.py:390 — already called at :1009, so `data` is envelope-free here too
def _extract_visit_context(self, form, body) -> tuple[dict[str, Any], dict[str, Any] | None]: ...

# services/validators.py:87 (after TASK-2434)
class ValidationResult(BaseModel):
    is_valid: bool
    errors: dict[str, list[str]]
    sanitized_data: dict[str, Any]
    extra_data: dict[str, Any]
```

### Does NOT Exist

- ~~A separate dry-run validator~~ — this route calls the same
  `self.validator.validate()` as `submit_data` (`:1010` vs `:1549`).
- ~~Lifecycle dispatch on this route~~ — `validate` does NOT dispatch `onError` or
  any other event (unlike `submit_data`). Do not add one; keep the route's
  behaviour minimal.
- ~~`form.unknown_fields`~~ / ~~`result.extra_data`~~ before TASK-2432/TASK-2434 land.
- ~~Cap enforcement on this route~~ — intentionally absent; `keep` stores nothing here.

---

## Implementation Notes

### Pattern to Follow

```python
# api/handlers.py — replacing :1011-1015
errors = dict(result.errors)
if (
    form.unknown_fields is UnknownFieldsPolicy.REJECT
    and result.extra_data
):
    errors["__unknown__"] = sorted(result.extra_data)

is_valid = not errors
return JSONResponse(
    {"is_valid": is_valid, "errors": errors},
    status=200 if is_valid else 422,
)
```

### Key Constraints

- Copy `result.errors` before mutating — never mutate the `ValidationResult`.
- `is_valid` in the response body and the HTTP status must agree; derive both from
  the merged `errors` dict so they cannot drift.
- Use the same reserved `__unknown__` key and the same `sorted(...)` ordering as
  TASK-2436, so a client sees one consistent shape from both routes.
- `drop` and `keep` must produce byte-identical responses to today.

### References in Codebase

- `api/handlers.py:1552-1565` — `submit_data`'s `422` shape (this route's is
  simpler: no lifecycle dispatch).
- `services/validators.py:156-166` — the reserved form-level error-key convention.

---

## Acceptance Criteria

- [ ] `reject` form + undeclared keys → `422`, `errors["__unknown__"] == sorted(keys)`
      (spec AC19).
- [ ] `reject` form + exact payload → `200`, `is_valid True`.
- [ ] `reject` form + undeclared keys AND a real field error → both appear in
      `errors`; status `422`.
- [ ] `keep` form + undeclared keys → response byte-identical to pre-FEAT-458.
- [ ] `drop` form + undeclared keys → response byte-identical to pre-FEAT-458.
- [ ] `result.errors` is not mutated (the `ValidationResult` is left intact).
- [ ] The route still dispatches no lifecycle events.
- [ ] Tests pass: `pytest packages/parrot-formdesigner/tests/unit/api/test_validate_endpoint_unknown_fields.py -v`
- [ ] No linting errors: `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/api/test_validate_endpoint_unknown_fields.py
import pytest


class TestValidateEndpointPolicy:
    async def test_reject_returns_422(self, client, reject_form):
        resp = await client.post(f"/api/v1/forms/{reject_form.form_uid}/validate",
                                 json={"name": "Ana", "junk": 1, "other": 2})
        assert resp.status == 422
        body = await resp.json()
        assert body["is_valid"] is False
        assert body["errors"]["__unknown__"] == ["junk", "other"]

    async def test_reject_clean_payload_200(self, client, reject_form):
        resp = await client.post(f"/api/v1/forms/{reject_form.form_uid}/validate",
                                 json={"name": "Ana"})
        assert resp.status == 200
        assert (await resp.json())["is_valid"] is True

    async def test_reject_merges_with_field_errors(self, client, reject_form):
        resp = await client.post(f"/api/v1/forms/{reject_form.form_uid}/validate",
                                 json={"name": "", "junk": 1})
        body = await resp.json()
        assert resp.status == 422
        assert "__unknown__" in body["errors"]
        assert "name" in body["errors"]

    @pytest.mark.parametrize("policy", ["drop", "keep"])
    async def test_non_reject_policies_unchanged(self, client, form_factory, policy):
        form = await form_factory(unknown_fields=policy)
        resp = await client.post(f"/api/v1/forms/{form.form_uid}/validate",
                                 json={"name": "Ana", "junk": 1})
        assert resp.status == 200
        assert await resp.json() == {"is_valid": True, "errors": {}}
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

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-08-26
**Notes**: Added a local `from ..core.schema import UnknownFieldsPolicy`
import inside `validate()` (mirrors `submit_data`'s local-import style; a
separate local import, not a duplicate — TASK-2436 imported it inside
`submit_data`, a different method). Replaced the `status = 200 if
result.is_valid else 422` / plain-`result.errors` response with: copy
`result.errors` into a fresh `errors` dict, add
`errors["__unknown__"] = sorted(result.extra_data)` when
`form.unknown_fields is UnknownFieldsPolicy.REJECT and result.extra_data`,
then derive both `is_valid` and the status code from the merged `errors`
dict so they cannot drift. Added a docstring paragraph documenting the
FEAT-458 behaviour. No lifecycle dispatch added (route stays minimal, per
Does-Not-Exist). 7 new unit tests in
`tests/unit/api/test_validate_endpoint_unknown_fields.py` (mocked-handler
pattern matching TASK-2436's test file), all passing, including an
explicit `test_result_errors_not_mutated` (asserts `vr.errors` is
untouched) and `test_no_lifecycle_dispatch` (spies on `dispatch`, asserts
zero calls). Full-suite regression diff (`git stash` before/after on the
complete `pytest packages/parrot-formdesigner/tests/` run): identical
failure set to the TASK-2436 baseline — zero new failures. `ruff check`
on `handlers.py`: 0 new findings (normalized before/after diff empty).

**Deviations from spec**: none.

### Post-completion addendum (adversarial code review, 2026-08-26)

Same `is` → `==` finding as TASK-2436's addendum applies to this task's
`form.unknown_fields is UnknownFieldsPolicy.REJECT` comparison in
`validate()`. Fixed in commit `d09f2ac9b` alongside TASK-2436/2439's sites.
New test: `test_reject_fires_when_policy_is_a_raw_string` in
`test_validate_endpoint_unknown_fields.py`.
