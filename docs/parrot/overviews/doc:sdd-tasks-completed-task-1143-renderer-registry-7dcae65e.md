---
type: Wiki Overview
title: 'TASK-1143: Renderer Registry — XForms'
id: doc:sdd-tasks-completed-task-1143-renderer-registry-xforms-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Phase 1, Module 5. Migrate the existing if/elif dispatch in `renderers/xforms.py`
---

# TASK-1143: Renderer Registry — XForms

**Feature**: FEAT-167 — FormDesigner New Field Types
**Spec**: `sdd/specs/formdesigner-new-fields.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1139
**Assigned-to**: unassigned

---

## Context

Phase 1, Module 5. Migrate the existing if/elif dispatch in `renderers/xforms.py`
into a `_registry` dict. Same pattern as Modules 2–4.

---

## Scope

- Add `_registry: dict[FieldType, FieldRenderer]` to `XFormsRenderer`
- Migrate all existing FieldType branches into registered callables
- Replace dispatch with `_registry.get(field.field_type, self._fallback)`
- Public `XFormsRenderer.render()` signature remains unchanged

**NOT in scope**: New FieldType values, RenderWarning, AuthContext.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/xforms.py` | MODIFY | Add `_registry` dict, migrate dispatch |
| `packages/parrot-formdesigner/tests/unit/test_renderers.py` | MODIFY | Add `test_xforms_registry_dispatch_existing_types` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from .base import AbstractFormRenderer, FieldRenderer, FallbackRenderer
from ..core.schema import FormField, FormSchema, RenderedForm
from ..core.types import FieldType
```

### Existing Signatures to Use
```python
# xforms.py — AbstractFormRenderer subclass
class XFormsRenderer(AbstractFormRenderer):
    async def render(
        self,
        form: FormSchema,
        style: StyleSchema | None = None,
        *,
        locale: str = "en",
        prefilled: dict[str, Any] | None = None,
        errors: dict[str, str] | None = None,
    ) -> RenderedForm: ...  # SIGNATURE MUST STAY BYTE-IDENTICAL
```

### Does NOT Exist
- ~~`RenderWarning`~~ — TASK-1146
- ~~New FieldType values~~ — TASK-1147
- ~~`AuthContext`~~ — TASK-1155

---

## Implementation Notes

XForms renderer is 342 lines. Same migration pattern:
1. Find the field type dispatch section
2. Extract each branch into a callable
3. Register in `_build_registry()` from `__init__()`
4. Replace dispatch with registry lookup

For XForms, unsupported types emit `<xf:input>` with a help note — wrap this
in a `_XFormsFallbackRenderer` that inherits `FallbackRenderer`.

---

## Acceptance Criteria

- [ ] `XFormsRenderer._registry` contains all 20 existing FieldType values
- [ ] All existing XForms renderer tests pass unchanged
- [ ] `test_xforms_registry_dispatch_existing_types` passes
- [ ] `ruff check packages/parrot-formdesigner/` passes

---

## Test Specification

```python
@pytest.mark.asyncio
async def test_xforms_registry_dispatch_existing_types():
    """All 20 existing FieldType values render via XForms registry without error."""
    from parrot_formdesigner.renderers.xforms import XFormsRenderer
    renderer = XFormsRenderer()
    existing_types = [
        FieldType.TEXT, FieldType.TEXT_AREA, FieldType.NUMBER, FieldType.INTEGER,
        FieldType.BOOLEAN, FieldType.DATE, FieldType.DATETIME, FieldType.TIME,
        FieldType.SELECT, FieldType.MULTI_SELECT, FieldType.FILE, FieldType.IMAGE,
        FieldType.COLOR, FieldType.URL, FieldType.EMAIL, FieldType.PHONE,
        FieldType.PASSWORD, FieldType.HIDDEN, FieldType.GROUP, FieldType.ARRAY,
    ]
    for ft in existing_types:
        field = FormField(field_id="f1", field_type=ft, label="Test")
        form = FormSchema(
            form_id="test", title="T",
            sections=[FormSection(section_id="s1", fields=[field])]
        )
        result = await renderer.render(form)
        assert result is not None, f"XForms renderer returned None for {ft}"
```

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
