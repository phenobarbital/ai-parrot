---
type: Wiki Overview
title: 'TASK-1142: Renderer Registry — PDF'
id: doc:sdd-tasks-completed-task-1142-renderer-registry-pdf-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Phase 1, Module 4. Migrate the existing if/elif dispatch in `renderers/pdf.py`
---

# TASK-1142: Renderer Registry — PDF

**Feature**: FEAT-167 — FormDesigner New Field Types
**Spec**: `sdd/specs/formdesigner-new-fields.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1139
**Assigned-to**: unassigned

---

## Context

Phase 1, Module 4. Migrate the existing if/elif dispatch in `renderers/pdf.py`
(~lines 35–40, 237–299) into a `_registry` dict. Preserve the existing
"unsupported types → placeholder textfield" behaviour via `FallbackRenderer`.

---

## Scope

- Add `_registry: dict[FieldType, FieldRenderer]` to `PdfRenderer`
- Migrate all existing FieldType branches into registered callables
- Preserve unsupported-type placeholder behaviour via `FallbackRenderer`
- Replace dispatch with `_registry.get(field.field_type, self._fallback)`
- Public `PdfRenderer.render()` signature remains unchanged

**NOT in scope**: New FieldType values, RenderWarning, AuthContext.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/pdf.py` | MODIFY | Add `_registry` dict, migrate dispatch |
| `packages/parrot-formdesigner/tests/unit/test_renderers.py` | MODIFY | Add `test_pdf_registry_dispatch_existing_types` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# From renderers/base.py (after TASK-1139):
from .base import AbstractFormRenderer, FieldRenderer, FallbackRenderer

from ..core.schema import FormField, FormSchema, RenderedForm
from ..core.types import FieldType
```

### Existing Signatures to Use
```python
# pdf.py — AbstractFormRenderer subclass
class PdfRenderer(AbstractFormRenderer):
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
- ~~`RenderedForm.warnings`~~ — TASK-1146
- ~~New FieldType values~~ — TASK-1147
- ~~`AuthContext`~~ — TASK-1155

---

## Implementation Notes

Same migration pattern as TASK-1140 and TASK-1141. The PDF renderer is 339 lines.
Scan for:
1. Any type-to-widget mapping dict (lines ~35–40)
2. The main field dispatch section (lines ~237–299)

The existing "unsupported types → placeholder textfield" path should be wrapped
in a `FallbackRenderer` subclass specific to PDF:

```python
class _PdfFallbackRenderer(FallbackRenderer):
    async def render(self, field, *, locale="en", prefilled=None, error=None):
        # Return a labelled empty textfield placeholder dict (existing behaviour)
        return {"type": "text_input", "placeholder": True, "label": ...}
```

Register this as `self._fallback` in `PdfRenderer.__init__()`.

---

## Acceptance Criteria

- [ ] `PdfRenderer._registry` contains all 20 existing FieldType values
- [ ] All existing PDF renderer tests pass unchanged
- [ ] `test_pdf_registry_dispatch_existing_types` passes
- [ ] `ruff check packages/parrot-formdesigner/` passes

---

## Test Specification

```python
@pytest.mark.asyncio
async def test_pdf_registry_dispatch_existing_types():
    """All 20 existing FieldType values render via PDF registry without error."""
    from parrot_formdesigner.renderers.pdf import PdfRenderer
    renderer = PdfRenderer()
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
        assert result is not None, f"PDF renderer returned None for {ft}"
```

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
