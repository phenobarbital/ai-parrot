# TASK-2198: Typed tenant error responses

**Feature**: FEAT-421 — Client-declared tenant in the forms URL
**Spec**: `sdd/specs/forms-tenant-in-url.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec Module 2. Every later task raises these errors instead of
hand-rolling `JSONResponse({"error": ...}, status=400)` at each of the ~30
tenant-aware call sites. Landing them first means no task has to invent its
own error shape, and `navigator-svelte` gets one stable contract to branch on.

---

## Scope

- Create `api/errors.py` with three `web.HTTPException` subclasses:
  `TenantNotDeclaredError` (400), `TenantForbiddenError` (403),
  `TenantConflictError` (400).
- Each renders the stable JSON body defined in spec §2 "Data Models", with
  `content_type="application/json"`.
- Each carries a machine-readable `error` slug: `tenant_not_declared`,
  `tenant_forbidden`, `tenant_conflict`.
- Write unit tests asserting status code, `content_type`, and body keys.

**NOT in scope**: raising them anywhere (TASK-2199+ do that); touching
`handlers.py`, `routes.py`, or any existing error path.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/errors.py` | CREATE | The three exception classes |
| `packages/parrot-formdesigner/tests/unit/api/test_tenant_errors.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from aiohttp import web  # verified: api/handlers.py:17
import json              # verified: api/handlers.py:12
```

### Existing Signatures to Use

```python
# aiohttp — subclass these, they are real HTTPException subclasses:
#   web.HTTPBadRequest  (400)
#   web.HTTPForbidden   (403)
# Both accept: text=..., content_type=..., reason=...
```

The expected body shape, verbatim from spec §2:

```json
{
  "error": "tenant_not_declared",
  "message": "This endpoint requires an explicit tenant.",
  "expected": "/api/v1/t/{tenant}/forms/{form_uid}"
}
```

### Does NOT Exist

- ~~`parrot_formdesigner.api.errors`~~ — this task CREATES it. Nothing imports
  it yet.
- ~~a shared error-envelope helper in the package~~ — existing handlers build
  bodies inline with `JSONResponse({"error": str(exc)}, status=404)`
  (e.g. `api/handlers.py:1965`). There is no base error class to inherit from.
- ~~`navigator.responses.JSONResponse` as an exception~~ — it is a *response*
  object (`api/handlers.py:19`), not raisable. These classes must subclass
  `web.HTTPException` so the decorator in TASK-2199 can `raise` them.

---

## Implementation Notes

### Pattern to Follow

```python
class TenantNotDeclaredError(web.HTTPBadRequest):
    error_slug = "tenant_not_declared"

    def __init__(self, *, expected: str | None = None) -> None:
        body = {
            "error": self.error_slug,
            "message": "This endpoint requires an explicit tenant.",
        }
        if expected:
            body["expected"] = expected
        super().__init__(
            text=json.dumps(body),
            content_type="application/json",
        )
```

### Key Constraints

- Google-style docstrings + type hints on every class and `__init__`.
- Do NOT log inside the exception classes — the raising site owns logging.
- Keep `expected` optional so the decorator can pass a route-specific hint.

### References in Codebase

- `api/handlers.py:1965` — the inline error style these replace.
- `api/routes.py:69-91` — `_wrap_auth`, the consumer added in TASK-2200.

---

## Acceptance Criteria

- [ ] `from parrot_formdesigner.api.errors import TenantNotDeclaredError, TenantForbiddenError, TenantConflictError` works
- [ ] Each class raises with the correct HTTP status (400 / 403 / 400)
- [ ] Each response has `content_type == "application/json"` and a body parsing to a dict with an `error` key matching the slug
- [ ] All tests pass: `pytest packages/parrot-formdesigner/tests/unit/api/test_tenant_errors.py -v`
- [ ] No linting errors: `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/api/errors.py`

---

## Test Specification

```python
import json
import pytest
from aiohttp import web
from parrot_formdesigner.api.errors import (
    TenantConflictError,
    TenantForbiddenError,
    TenantNotDeclaredError,
)


class TestTenantErrors:
    def test_not_declared_is_400(self):
        exc = TenantNotDeclaredError(expected="/api/v1/t/{tenant}/forms")
        assert exc.status == 400
        assert exc.content_type == "application/json"
        body = json.loads(exc.text)
        assert body["error"] == "tenant_not_declared"
        assert body["expected"] == "/api/v1/t/{tenant}/forms"

    def test_forbidden_is_403(self):
        exc = TenantForbiddenError()
        assert exc.status == 403
        assert json.loads(exc.text)["error"] == "tenant_forbidden"

    def test_conflict_is_400(self):
        exc = TenantConflictError()
        assert exc.status == 400
        assert json.loads(exc.text)["error"] == "tenant_conflict"

    def test_all_are_raisable_http_exceptions(self):
        for cls in (TenantNotDeclaredError, TenantForbiddenError, TenantConflictError):
            assert issubclass(cls, web.HTTPException)
            with pytest.raises(cls):
                raise cls()
```

---

## Agent Instructions

1. **Read the spec** at `sdd/specs/forms-tenant-in-url.spec.md` (§2 Data Models)
2. **Check dependencies** — none
3. **Verify the Codebase Contract** before writing any code
4. **Update status** in `sdd/tasks/index/forms-tenant-in-url.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2198-tenant-error-responses.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
