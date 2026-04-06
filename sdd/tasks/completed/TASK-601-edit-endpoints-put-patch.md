# TASK-601: Edit Endpoints (PUT/PATCH)

**Feature**: form-designer-edition
**Spec**: `sdd/specs/form-designer-edition.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-598
**Assigned-to**: unassigned

---

## Context

This is the core editing capability. Adds `PUT` and `PATCH` endpoints to `FormAPIHandler` for full replacement and partial update of registered forms. The PATCH endpoint uses JSON merge-patch (RFC 7396) semantics.

Implements Spec Module 5.

---

## Scope

- Add `update_form()` method to `FormAPIHandler`:
  - `PUT /api/v1/forms/{form_id}`
  - Accepts complete `FormSchema` JSON body
  - Validates `form_id` in URL matches body
  - Runs `FormValidator.check_schema()` before accepting
  - Bumps version automatically
  - Re-registers in `FormRegistry` with `overwrite=True`
  - Persists if storage is configured

- Add `patch_form()` method to `FormAPIHandler`:
  - `PATCH /api/v1/forms/{form_id}`
  - Accepts partial JSON (merge-patch)
  - Deep-merges onto existing `FormSchema.model_dump()`
  - Validates merged result via `FormSchema.model_validate()` + `check_schema()`
  - Bumps version automatically
  - Re-registers and persists same as PUT

- Add `_deep_merge()` utility function (module-level or static method)
- Add `_bump_version()` utility function

**NOT in scope**: Submission endpoint (TASK-602), route registration (TASK-603)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot/formdesigner/handlers/api.py` | MODIFY | Add `update_form()`, `patch_form()`, `_deep_merge()`, `_bump_version()` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Already imported in handlers/api.py:
from aiohttp import web  # line 5 of api.py
import json  # line 3
import logging  # line 4
from ..core.schema import RenderedForm  # line 20
from ..renderers.html5 import HTML5Renderer  # line 21
from ..renderers.jsonschema import JsonSchemaRenderer  # line 22
from ..services.registry import FormRegistry  # line 23
from ..services.validators import FormValidator  # line 24

# FormSchema is NOT directly imported in api.py — import it:
from ..core.schema import FormSchema  # core/schema.py:105
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot/formdesigner/handlers/api.py:29
class FormAPIHandler:
    def __init__(self, registry: FormRegistry, client: "AbstractClient | None" = None) -> None:  # line 45
        self.registry = registry  # line 50
        self._client = client  # line 51
        self.html_renderer = HTML5Renderer()  # line 52
        self.schema_renderer = JsonSchemaRenderer()  # line 53
        self.validator = FormValidator()  # line 54
        self.logger = logging.getLogger(__name__)  # line 55

# packages/parrot-formdesigner/src/parrot/formdesigner/services/registry.py:124
async def register(self, form: FormSchema, *, persist: bool = False, overwrite: bool = True) -> None

# packages/parrot-formdesigner/src/parrot/formdesigner/services/registry.py:192
async def get(self, form_id: str) -> FormSchema | None

# packages/parrot-formdesigner/src/parrot/formdesigner/services/registry.py:119
_storage: FormStorage | None  # check if storage is configured

# packages/parrot-formdesigner/src/parrot/formdesigner/services/validators.py:446
def check_schema(self, form: FormSchema) -> list[str]

# packages/parrot-formdesigner/src/parrot/formdesigner/core/schema.py:105
class FormSchema(BaseModel):
    form_id: str  # line 122
    version: str = "1.0"  # line 123
    # model_dump() and model_validate() from Pydantic BaseModel
```

### Does NOT Exist
- ~~`FormAPIHandler.update_form()`~~ — does not exist; this task creates it
- ~~`FormAPIHandler.patch_form()`~~ — does not exist; this task creates it
- ~~`FormRegistry.update()`~~ — no update method; use `register(overwrite=True)`
- ~~`_deep_merge()`~~ — does not exist; this task creates it
- ~~`_bump_version()`~~ — does not exist; this task creates it

---

## Implementation Notes

### Deep Merge Logic (RFC 7396)
```python
def _deep_merge(base: dict, patch: dict) -> dict:
    """RFC 7396 JSON merge-patch: recursively merge patch onto base.

    - dict values are merged recursively
    - None/null values remove the key
    - All other values (including lists) replace entirely
    """
    result = base.copy()
    for key, value in patch.items():
        if value is None:
            result.pop(key, None)
        elif isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result
```

### Version Bumping
```python
def _bump_version(version: str) -> str:
    """Increment minor version: '1.0' -> '1.1', '1' -> '1.1'."""
    parts = version.split(".")
    if len(parts) >= 2:
        parts[-1] = str(int(parts[-1]) + 1)
    else:
        parts.append("1")
    return ".".join(parts)
```

### PUT Flow
```python
async def update_form(self, request: web.Request) -> web.Response:
    form_id = request.match_info["form_id"]
    existing = await self.registry.get(form_id)
    if existing is None:
        return web.json_response({"error": f"Form '{form_id}' not found"}, status=404)

    body = await request.json()  # handle JSONDecodeError
    if body.get("form_id") != form_id:
        return web.json_response({"error": "form_id in URL and body must match"}, status=400)

    body["version"] = _bump_version(existing.version)
    form = FormSchema.model_validate(body)  # handle ValidationError → 422

    schema_errors = self.validator.check_schema(form)
    if schema_errors:
        return web.json_response({"errors": schema_errors}, status=422)

    persist = self.registry._storage is not None
    await self.registry.register(form, persist=persist, overwrite=True)
    return web.json_response(form.model_dump())
```

### PATCH Flow
Same but with merge step:
```python
existing_dict = existing.model_dump()
merged = _deep_merge(existing_dict, body)
merged["version"] = _bump_version(existing.version)
# Prevent form_id change via patch
merged["form_id"] = form_id
form = FormSchema.model_validate(merged)
```

### Key Constraints
- Follow the existing handler pattern: try/except for JSON parsing, 404 for missing form, 422 for validation errors
- `form_id` cannot be changed via PATCH (force it back to URL value after merge)
- Empty PATCH body → 400
- Access `self.registry._storage` to determine if persist should be True (existing pattern in the codebase)
- Use `from pydantic import ValidationError` for catching model validation failures

### References in Codebase
- `packages/parrot-formdesigner/src/parrot/formdesigner/handlers/api.py` — existing handler methods as pattern
- `packages/parrot-formdesigner/src/parrot/formdesigner/services/validators.py:446` — `check_schema()`

---

## Acceptance Criteria

- [ ] `PUT /api/v1/forms/{form_id}` replaces form entirely
- [ ] `PATCH /api/v1/forms/{form_id}` merges partial JSON onto existing form
- [ ] Both endpoints return 404 for non-existent form
- [ ] Both endpoints return 422 for validation failures
- [ ] PUT returns 400 for form_id mismatch
- [ ] PATCH returns 400 for empty body
- [ ] Version is automatically bumped on both PUT and PATCH
- [ ] form_id cannot be changed via PATCH
- [ ] Persists to storage when FormRegistry has a storage backend
- [ ] `check_schema()` runs before every save

---

## Test Specification

```python
# tests/test_edit_endpoints.py
import pytest
from parrot.formdesigner.handlers.api import _deep_merge, _bump_version


class TestDeepMerge:
    def test_simple_override(self):
        assert _deep_merge({"a": 1}, {"a": 2}) == {"a": 2}

    def test_nested_merge(self):
        base = {"a": {"b": 1, "c": 2}}
        patch = {"a": {"b": 3}}
        assert _deep_merge(base, patch) == {"a": {"b": 3, "c": 2}}

    def test_null_removes_key(self):
        assert _deep_merge({"a": 1, "b": 2}, {"a": None}) == {"b": 2}

    def test_list_replaces_entirely(self):
        base = {"items": [1, 2, 3]}
        patch = {"items": [4, 5]}
        assert _deep_merge(base, patch) == {"items": [4, 5]}


class TestBumpVersion:
    def test_minor_bump(self):
        assert _bump_version("1.0") == "1.1"
        assert _bump_version("1.5") == "1.6"

    def test_no_minor(self):
        assert _bump_version("1") == "1.1"

    def test_three_parts(self):
        assert _bump_version("1.2.3") == "1.2.4"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/form-designer-edition.spec.md`
2. **Check dependencies** — verify TASK-598 is in `tasks/completed/`
3. **Verify the Codebase Contract** — read `handlers/api.py` in full before modifying
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** the two new methods + utility functions
6. **Run tests**: `pytest packages/parrot-formdesigner/tests/test_edit_endpoints.py -v`
7. **Move this file** to `tasks/completed/`
8. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
