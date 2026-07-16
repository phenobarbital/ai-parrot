---
type: Wiki Overview
title: 'TASK-1141: Renderer Registry — Adaptive Card'
id: doc:sdd-tasks-completed-task-1141-renderer-registry-adaptive-card-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Phase 1, Module 3. Migrate the existing if/elif dispatch chain in
---

# TASK-1141: Renderer Registry — Adaptive Card

**Feature**: FEAT-167 — FormDesigner New Field Types
**Spec**: `sdd/specs/formdesigner-new-fields.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1139
**Assigned-to**: unassigned

---

## Context

Phase 1, Module 3. Migrate the existing if/elif dispatch chain in
`renderers/adaptive_card.py` (~lines 591, 860–869) into a `_registry`
dict populated in `AdaptiveCardRenderer.__init__()`. Same pattern as
TASK-1140 for HTML5. Public `render()` stays unchanged.

---

## Scope

- Add `_registry: dict[FieldType, FieldRenderer]` to `AdaptiveCardRenderer`
- Migrate all existing FieldType branches into registered callables
- Replace dispatch with `_registry.get(field.field_type, self._fallback)`
- Public `AdaptiveCardRenderer.render()` signature remains unchanged

**NOT in scope**: New FieldType values, RenderWarning, AuthContext.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/adaptive_card.py` | MODIFY | Add `_registry` dict, migrate dispatch |
| `packages/parrot-formdesigner/tests/unit/test_renderers.py` | MODIFY | Add `test_adaptive_card_registry_dispatch_existing_types` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# From renderers/base.py (after TASK-1139):
from .base import AbstractFormRenderer, FieldRenderer, FallbackRenderer

# adaptive_card.py renders fields to Adaptive Card JSON dicts.
# The renderer outputs content: dict (JSON-serializable Adaptive Card payload)
from ..core.schema import FormField, FormSchema, RenderedForm
from ..core.types import FieldType
```

### Existing Signatures to Use
```python
# adaptive_card.py:14 — AbstractFormRenderer subclass
class AdaptiveCardRenderer(AbstractFormRenderer):
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

Same pattern as TASK-1140:
1. Read the current if/elif field type dispatch in `adaptive_card.py`
2. Extract each branch into a callable (lambda, partial, or inner method)
3. Register them in `_build_registry()` called from `__init__()`
4. Replace dispatch with `_registry.get(field.field_type, self._fallback)`

The adaptive_card renderer is 874 lines — scan for the main field dispatch
section (around line 591 per spec) and any secondary dispatch (860–869).

---

## Acceptance Criteria

- [ ] `AdaptiveCardRenderer._registry` contains all 20 existing FieldType values
- [ ] All existing `test_renderers.py` tests for Adaptive Card pass unchanged
- [ ] `test_adaptive_card_registry_dispatch_existing_types` passes
- [ ] `ruff check packages/parrot-formdesigner/` passes

---

## Test Specification

```python
@pytest.mark.asyncio
async def test_adaptive_card_registry_dispatch_existing_types():
    """All 20 existing FieldType values render via registry without error."""
    from parrot_formdesigner.renderers.adaptive_card import AdaptiveCardRenderer
    renderer = AdaptiveCardRenderer()
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
        assert result.content is not None, f"Adaptive Card returned None for {ft}"
```

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
