# TASK-554: Package Exports & Re-export Shim

**Feature**: formdesigner-package
**Feature ID**: FEAT-079
**Spec**: `sdd/specs/formdesigner-package.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-548, TASK-549, TASK-550, TASK-551, TASK-552, TASK-553
**Assigned-to**: unassigned

---

## Context

Implements Module 7 of FEAT-079. Defines the clean public API for `parrot.formdesigner`
and updates `parrot.forms.__init__` in `ai-parrot` to re-export everything from
`parrot.formdesigner` for backward compatibility.

This is the integration task — all previous modules must be complete before this runs.

---

## Scope

### `packages/parrot-formdesigner/src/parrot/formdesigner/__init__.py` (finalize)
Export the complete public API:
```python
from parrot.formdesigner.core import FormSchema, FormField, FieldType, ...
from parrot.formdesigner.extractors import PydanticExtractor, ToolExtractor, YAMLExtractor, JSONSchemaExtractor
from parrot.formdesigner.renderers import HTML5Renderer, AdaptiveCardRenderer, JSONSchemaRenderer
from parrot.formdesigner.services import FormValidator, FormRegistry, FormCache, PostgresFormStorage
from parrot.formdesigner.tools import CreateFormTool, DatabaseFormTool, RequestFormTool
from parrot.formdesigner.handlers import setup_form_routes, FormAPIHandler, FormPageHandler

__all__ = [...]
```

### `packages/ai-parrot/src/parrot/forms/__init__.py` (update re-export shim)
Replace existing imports with lazy re-exports from `parrot.formdesigner`:
```python
# Backward-compatible re-exports from parrot.formdesigner
# No deprecation warnings per spec decision.
try:
    from parrot.formdesigner import *  # noqa: F401, F403
    from parrot.formdesigner import __all__  # noqa: F401
except ImportError:
    # parrot-formdesigner not installed — keep existing definitions as fallback
    pass
```
Use lazy imports to avoid circular dependency at module load time.

- Create backward compat test: `packages/parrot-formdesigner/tests/unit/test_backward_compat.py`

**NOT in scope**: updating `examples/` or MS Teams integration (that's TASK-555).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot/formdesigner/__init__.py` | MODIFY | Finalize full public API exports |
| `packages/ai-parrot/src/parrot/forms/__init__.py` | MODIFY | Replace with re-export shim from parrot.formdesigner |
| `packages/parrot-formdesigner/tests/unit/test_backward_compat.py` | CREATE | Verify old import paths still work |

---

## Implementation Notes

### Circular Import Risk
`parrot.forms` (in ai-parrot) re-exports from `parrot.formdesigner` (in parrot-formdesigner),
which optionally depends on `AbstractTool` from ai-parrot. To avoid circular imports at
module load time:

1. In `parrot/formdesigner/tools/create_form.py`, use lazy import:
   ```python
   def _get_abstract_tool():
       try:
           from parrot.tools import AbstractTool
           return AbstractTool
       except ImportError:
           return object
   ```

2. In `parrot/forms/__init__.py`, use the try/except pattern shown in Scope above.

### __all__ must be explicit
Define `__all__` explicitly in `parrot/formdesigner/__init__.py` so that
`from parrot.formdesigner import *` in the shim only re-exports the intended public API.

---

## Acceptance Criteria

- [ ] `from parrot.formdesigner import FormSchema` works
- [ ] `from parrot.formdesigner import CreateFormTool` works
- [ ] `from parrot.formdesigner import setup_form_routes` works
- [ ] `from parrot.forms import FormSchema` still works (backward compat)
- [ ] `from parrot.forms import CreateFormTool` still works (backward compat)
- [ ] `from parrot.forms import FormRegistry` still works (backward compat)
- [ ] No circular import errors at module load
- [ ] All tests pass: `pytest packages/parrot-formdesigner/tests/unit/test_backward_compat.py -v`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/test_backward_compat.py
"""Verify that old parrot.forms import paths remain functional."""
import pytest


class TestBackwardCompatImports:
    def test_import_form_schema(self):
        from parrot.forms import FormSchema
        assert FormSchema is not None

    def test_import_create_form_tool(self):
        from parrot.forms import CreateFormTool
        assert CreateFormTool is not None

    def test_import_form_registry(self):
        from parrot.forms import FormRegistry
        assert FormRegistry is not None

    def test_import_form_validator(self):
        from parrot.forms import FormValidator
        assert FormValidator is not None

    def test_import_html5_renderer(self):
        from parrot.forms.renderers.html5 import HTML5Renderer
        assert HTML5Renderer is not None

    def test_import_style_schema(self):
        from parrot.forms import StyleSchema
        assert StyleSchema is not None

    def test_import_field_type(self):
        from parrot.forms.types import FieldType
        assert FieldType is not None

    def test_no_circular_import(self):
        """Importing both packages together should not raise."""
        import parrot.formdesigner  # noqa: F401
        import parrot.forms  # noqa: F401


class TestMSTeamsCompatibility:
    def test_msteams_dialog_imports(self):
        """MS Teams integration imports form types unchanged via shim."""
        # This mirrors what parrot/integrations/msteams/ imports
        from parrot.forms import FormSchema, FormField, FieldType
        schema = FormSchema(
            form_id="msteams-test",
            title="Test",
            fields=[FormField(name="q", field_type=FieldType.TEXT, label="Q")],
        )
        assert schema.form_id == "msteams-test"
```

---

## Agent Instructions

1. **Verify** TASK-548 through TASK-553 are all in `sdd/tasks/completed/`
2. **Read** `packages/ai-parrot/src/parrot/forms/__init__.py` before modifying
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** scope above
5. **Test for circular imports** explicitly
6. **Verify** acceptance criteria
7. **Move** to `sdd/tasks/completed/`
8. **Update index** → `"done"`
9. **Commit**: `sdd: implement TASK-554 exports and re-export shim for parrot-formdesigner`

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none
