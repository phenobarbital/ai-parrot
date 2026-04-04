# TASK-557: Fix phantom attributes and dead code

**Feature**: FEAT-080 formdesigner-package-fixes
**Status**: done
**Priority**: critical
**Estimated effort**: small

## Context

Code review identified several AI hallucinations — code referencing attributes and imports that do not exist. These cause silent failures where features appear to work but actually do nothing.

## Tasks

### 1. Fix `trigger_phrases` phantom attribute on FormSchema (C2)

**File**: `services/registry.py` (lines ~149, 191)

`FormSchema` has no `trigger_phrases` field. The `_trigger_index`, `get_by_trigger()`, and `find_by_trigger()` methods are permanently dead code.

**Decision**: Remove the trigger-phrase subsystem from `FormRegistry` entirely. If needed later, it should be added WITH the corresponding `FormSchema` field. Remove:
- `_trigger_index` dict
- `_build_trigger_index()` calls in `register()`/`unregister()`
- `get_by_trigger()` method
- `find_by_trigger()` method

### 2. Fix wrong relative import in `load_from_directory` (C3)

**File**: `services/registry.py` (line ~308)
**Also**: `packages/ai-parrot/src/parrot/forms/registry.py` (same line)

Change:
```python
from .extractors.yaml import YamlExtractor
```
To:
```python
from ..extractors.yaml import YamlExtractor
```

### 3. Fix phantom `rendered.output` attribute (I7)

**File**: `handlers/api.py` (line ~79)

`RenderedForm` only has `.content`, not `.output`. Change:
```python
return web.json_response(rendered.output if hasattr(rendered, "output") else rendered.content)
```
To:
```python
rendered: RenderedForm = await self.schema_renderer.render(form)
return web.json_response(rendered.content)
```

### 4. Add `ValidationResult` to package `__all__` (I12)

**File**: `packages/parrot-formdesigner/src/parrot/formdesigner/__init__.py`

Add `ValidationResult` and `FormValidator` to the imports from `.services` and to `__all__`:
```python
from .services import FormCache, FormRegistry, FormStorage, FormValidator, PostgresFormStorage, ValidationResult
```

### 5. Remove dead code artifacts

- Remove `if TYPE_CHECKING: pass` no-op block in `create_form.py` (line ~39)
- Remove `# from ..forms legacy: AbstractTool, ToolResult` comments from all 3 tool files

## Acceptance Criteria

- [x] No `trigger_phrases` references remain in registry.py
- [x] `load_from_directory()` successfully imports `YamlExtractor`
- [x] `rendered.content` used directly, no `hasattr` guard
- [x] `from parrot.formdesigner import ValidationResult` works
- [x] No dead imports or legacy comments remain
- [x] Unit tests pass (73 pass; 2 pre-existing failures unrelated to this task — missing Jinja2 template)

## Completion Note

All 5 sub-tasks implemented in worktree `feat-080-formdesigner-package-fixes`.

Note on task 2 (import fix): The `packages/ai-parrot/src/parrot/forms/registry.py` import
`from .extractors.yaml import YamlExtractor` is already correct for that package (extractors is
a subdirectory of forms/). Only the `services/registry.py` in parrot-formdesigner needed fixing.

Commit: 88c18f12
