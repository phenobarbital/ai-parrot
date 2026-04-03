# TASK-561: Fix handler robustness and service hardening

**Feature**: FEAT-080 formdesigner-package-fixes
**Status**: done
**Priority**: important
**Estimated effort**: medium

## Context

Code review identified several robustness issues in handlers and services: unguarded dictionary access, missing type annotations, inconsistent error responses, N+1 queries, ReDoS vulnerability, missing Pydantic constraints, and inefficient serialization.

## Files

- `packages/parrot-formdesigner/src/parrot/formdesigner/handlers/api.py`
- `packages/parrot-formdesigner/src/parrot/formdesigner/handlers/forms.py`
- `packages/parrot-formdesigner/src/parrot/formdesigner/handlers/routes.py`
- `packages/parrot-formdesigner/src/parrot/formdesigner/services/validators.py`
- `packages/parrot-formdesigner/src/parrot/formdesigner/core/constraints.py`
- `packages/parrot-formdesigner/src/parrot/formdesigner/services/storage.py`

## Tasks

### 1. Add `.get()` guards on result metadata access (I8)

**File**: `handlers/api.py` (lines ~171, 225)

```python
# BEFORE
form_id = result.metadata["form"]["form_id"]
title = result.result["title"]

# AFTER
form_data = result.metadata.get("form", {})
form_id = form_data.get("form_id")
title = (result.result or {}).get("title", "")
if not form_id:
    return web.json_response(
        {"error": "Form creation succeeded but form_id missing"},
        status=500,
    )
```

### 2. Add type annotations for `client` parameter (S7)

**File**: `handlers/routes.py` (line ~19):
```python
def setup_form_routes(
    app: web.Application,
    *,
    registry: FormRegistry | None = None,
    client: "AbstractClient | None" = None,
    prefix: str = "",
) -> None:
```

**File**: `handlers/api.py` (line ~19) — same for `FormAPIHandler.__init__`.

### 3. Fix inconsistent 404 in `submit_form`

**File**: `handlers/forms.py` (line ~140)

```python
# BEFORE
return web.Response(text="Form not found", status=404)

# AFTER
return web.Response(
    text=page_shell("Not Found", error_page("Form not found.")),
    status=404,
    content_type="text/html",
)
```

### 4. Use `list_forms()` instead of N+1 `get()` calls in gallery (S3)

**File**: `handlers/forms.py` (line ~74)

```python
# BEFORE
form_ids = await self.registry.list_form_ids()
for fid in form_ids:
    form = await self.registry.get(fid)  # N lock acquisitions

# AFTER
forms = await self.registry.list_forms()
for form in forms:
    fid = form.form_id
    title = form.title if isinstance(form.title, str) else form.title.get("en", fid)
    ...
```

### 5. Add ReDoS protection — validate regex at FieldConstraints construction (I2)

**File**: `core/constraints.py`

Add a Pydantic field validator that compiles the pattern at model construction time:
```python
import re
from pydantic import field_validator

class FieldConstraints(BaseModel):
    ...

    @field_validator("pattern")
    @classmethod
    def _validate_pattern(cls, v: str | None) -> str | None:
        if v is not None:
            try:
                re.compile(v)
            except re.error as exc:
                raise ValueError(f"Invalid regex pattern: {exc}") from exc
        return v
```

**File**: `services/validators.py` (line ~195) — use `re.fullmatch` instead of `re.match`:
```python
if not re.fullmatch(c.pattern, str(coerced)):
    errors.append(f"{label} does not match required pattern")
```

### 6. Add `Field(ge=0)` constraints on numeric fields (S5)

**File**: `core/constraints.py`

```python
min_length: int | None = Field(default=None, ge=0, description="Minimum string length")
max_length: int | None = Field(default=None, ge=0, description="Maximum string length")
min_items: int | None = Field(default=None, ge=0, description="Minimum number of items")
max_items: int | None = Field(default=None, ge=0, description="Maximum number of items")
max_file_size_bytes: int | None = Field(default=None, ge=0, description="Maximum file size in bytes")
```

### 7. Use `model_dump_json()` in storage (S8)

**File**: `services/storage.py` (line ~141)

```python
# BEFORE
schema_json = json.dumps(form.model_dump())

# AFTER
schema_json = form.model_dump_json()
```

### 8. Narrow `except Exception` for JSON parsing in API

**File**: `handlers/api.py` (lines ~128, 154)

```python
# BEFORE
except Exception:
    return web.json_response({"error": "Invalid JSON body"}, status=400)

# AFTER
except (json.JSONDecodeError, ValueError):
    return web.json_response({"error": "Invalid JSON body"}, status=400)
```

## Acceptance Criteria

- [x] No unguarded `dict["key"]` access on tool results
- [x] `client` parameter typed as `AbstractClient | None` everywhere
- [x] All 404 responses use consistent styled HTML
- [x] Gallery handler uses single `list_forms()` call
- [x] Invalid regex patterns rejected at model construction
- [x] `re.fullmatch` used instead of `re.match` for pattern validation
- [x] Numeric constraints have `ge=0` guards
- [x] `model_dump_json()` used for storage serialization
- [x] JSON parse errors catch specific exceptions, not bare `Exception`
- [x] Unit tests pass (94 passing, 0 failing)

## Completion Note

All changes were already present on `dev` at task start — implemented as part of
the broader FEAT-080 package creation effort. Verified all 9 criteria against live
code on `dev` and confirmed 94 tests pass. No code changes needed.
