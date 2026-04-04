# TASK-560: Fix tool layer issues

**Feature**: FEAT-080 formdesigner-package-fixes
**Status**: done
**Priority**: critical
**Estimated effort**: medium

## Context

Code review found 7 issues in the tools layer: a broken cross-package import, private method access, fragile CPython-specific hacks, missing connection pooling, wrong Pydantic sentinel comparison, unhelpful import fallbacks, and per-request tool construction.

## Files

- `packages/parrot-formdesigner/src/parrot/formdesigner/tools/create_form.py`
- `packages/parrot-formdesigner/src/parrot/formdesigner/tools/database_form.py`
- `packages/parrot-formdesigner/src/parrot/formdesigner/tools/request_form.py`
- `packages/parrot-formdesigner/src/parrot/formdesigner/services/validators.py`
- `packages/parrot-formdesigner/src/parrot/formdesigner/extractors/pydantic.py`
- `packages/parrot-formdesigner/src/parrot/formdesigner/handlers/api.py`

## Tasks

### 1. Fix DSN import — env var fallback with clear error (C7)

**File**: `database_form.py` (line ~183)

The `from ...conf import default_dsn` exits the package. Replace with:
```python
def _get_dsn(self) -> str:
    if self._dsn:
        return self._dsn
    import os
    dsn = os.environ.get("PARROT_DB_DSN")
    if dsn:
        return dsn
    try:
        from parrot.conf import default_dsn
        return default_dsn
    except ImportError:
        raise RuntimeError(
            "No DSN provided and parrot.conf is not available. "
            "Pass dsn= to DatabaseFormTool or set PARROT_DB_DSN."
        )
```

### 2. Add public `check_schema()` method to FormValidator (I4)

**File**: `validators.py`

Add public method so `CreateFormTool` doesn't reach into private `_detect_circular_dependencies`:
```python
def check_schema(self, form: FormSchema) -> list[str]:
    """Check the form schema for structural issues without submitted data."""
    return self._detect_circular_dependencies(form)
```

**File**: `create_form.py` (line ~281) — Update caller:
```python
circular_errors = self._validator.check_schema(form)
```

### 3. Replace `"json_str" in dir()` with pre-initialized variables (I5)

**File**: `create_form.py` (line ~442)

Initialize variables before the retry loop:
```python
raw: str = ""
json_str: str = ""

for attempt in range(self.MAX_RETRIES + 1):
    try:
        raw = await self._call_llm(current_messages)
        json_str = _extract_json(raw)
        ...
```

Then the retry prompt can reference `json_str` and `raw` directly.

### 4. Accept injected AsyncDB / connection pool (I6)

**File**: `database_form.py`

Accept an `AsyncDB` instance in the constructor:
```python
def __init__(
    self,
    registry: FormRegistry,
    db: AsyncDB | None = None,
    dsn: str | None = None,
    **kwargs: Any,
) -> None:
    ...
    self._db = db
    self._dsn = dsn
```

Use `self._db` when available, only create a new one as fallback.

### 5. Fix `PydanticUndefinedType` → `PydanticUndefined` comparison (I10)

**File**: `extractors/pydantic.py` (line ~176)

```python
# BEFORE
from pydantic_core import PydanticUndefinedType
if field_info.default is not None and not isinstance(field_info.default, PydanticUndefinedType):

# AFTER (at module top level)
from pydantic_core import PydanticUndefined

# In method:
if field_info.default is not PydanticUndefined:
    default = field_info.default
```

### 6. Replace bare ImportError fallback with actionable error (S1)

**All 3 tool files** — Change:
```python
try:
    from parrot.tools.abstract import AbstractTool, ToolResult
except ImportError:
    AbstractTool = object
    ToolResult = dict
```
To:
```python
try:
    from parrot.tools.abstract import AbstractTool, ToolResult
except ImportError as exc:
    raise ImportError(
        "parrot-formdesigner tools require the 'ai-parrot' package. "
        "Install it with: uv add ai-parrot"
    ) from exc
```

### 7. Move tool construction to handler `__init__` (I9)

**File**: `handlers/api.py`

Move imports and tool instantiation from per-request handler methods to `FormAPIHandler.__init__`:
```python
class FormAPIHandler:
    def __init__(self, *, registry, client=None):
        ...
        from ..tools.create_form import CreateFormTool
        from ..tools.database_form import DatabaseFormTool
        self._create_tool = CreateFormTool(client=self.client, registry=self.registry)
        self._db_tool = DatabaseFormTool(registry=self.registry)
```

## Acceptance Criteria

- [x] `DatabaseFormTool` works standalone (without `ai-parrot` co-installed) via env var DSN
- [x] No private method access across class boundaries
- [x] No `dir()` hacks — all variables pre-initialized
- [x] Connection pooling supported via constructor injection
- [x] `PydanticUndefined` sentinel compared with `is not`, not `isinstance`
- [x] ImportError gives clear message with install instructions
- [x] Tools constructed once at handler init, not per-request
- [x] Unit tests pass (94 passing, 0 failing)

## Completion Note

All 7 sub-tasks implemented. 94 tests pass (previously 88; TASK-558 XSS template
tests are also passing in this worktree). Commit: f3b799c4
