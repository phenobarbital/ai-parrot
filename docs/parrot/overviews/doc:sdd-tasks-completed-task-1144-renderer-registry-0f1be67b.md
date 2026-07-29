---
type: Wiki Overview
title: 'TASK-1144: Renderer Registry — JSON Schema'
id: doc:sdd-tasks-completed-task-1144-renderer-registry-jsonschema-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Phase 1, Module 6. Migrate the existing if/elif dispatch in
---

# TASK-1144: Renderer Registry — JSON Schema

**Feature**: FEAT-167 — FormDesigner New Field Types
**Spec**: `sdd/specs/formdesigner-new-fields.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1139
**Assigned-to**: unassigned

---

## Context

Phase 1, Module 6. Migrate the existing if/elif dispatch in
`renderers/jsonschema.py` (~line 214+) into a `_registry` dict.
JSON Schema is the "lingua franca" for UI consumers — it must support
every type natively in Phase 2 (TASK-1151). This migration sets up that
extensibility.

---

## Scope

- Add `_registry: dict[FieldType, FieldRenderer]` to `JsonSchemaRenderer`
- Migrate all existing FieldType branches (line ~214+) into registered callables
- Replace dispatch with `_registry.get(field.field_type, self._fallback)`
- Public `JsonSchemaRenderer.render()` signature remains unchanged

**NOT in scope**: New FieldType values, RenderWarning, AuthContext.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/jsonschema.py` | MODIFY | Add `_registry` dict, migrate dispatch at line ~214+ |
| `packages/parrot-formdesigner/tests/unit/test_renderers.py` | MODIFY | Add `test_jsonschema_registry_dispatch_existing_types` |

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
# jsonschema.py — AbstractFormRenderer subclass
class JsonSchemaRenderer(AbstractFormRenderer):
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

JSON Schema renderer is 331 lines. The dispatch (~line 214+) likely maps
FieldType → JSON Schema property dict. Read the file first to understand
the current dispatch structure.

JSON Schema can represent all existing types natively, so `_fallback` here
can emit a generic `{"type": "string"}` as a safe default.

---

## Acceptance Criteria

- [ ] `JsonSchemaRenderer._registry` contains all 20 existing FieldType values
- [ ] All existing JSON Schema renderer tests pass unchanged
- [ ] `test_jsonschema_registry_dispatch_existing_types` passes
- [ ] `ruff check packages/parrot-formdesigner/` passes

---

## Test Specification

```python
@pytest.mark.asyncio
async def test_jsonschema_registry_dispatch_existing_types():
    """All 20 existing FieldType values render via JSON Schema registry without error."""
    from parrot_formdesigner.renderers.jsonschema import JsonSchemaRenderer
    renderer = JsonSchemaRenderer()
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
        assert result.content is not None, f"JSON Schema renderer returned None for {ft}"
```

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
