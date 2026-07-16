---
type: Wiki Overview
title: 'TASK-1145: Renderer Registry — Telegram'
id: doc:sdd-tasks-completed-task-1145-renderer-registry-telegram-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Phase 1, Module 7. Migrate dispatch in `renderers/telegram/renderer.py`
---

# TASK-1145: Renderer Registry — Telegram

**Feature**: FEAT-167 — FormDesigner New Field Types
**Spec**: `sdd/specs/formdesigner-new-fields.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1139
**Assigned-to**: unassigned

---

## Context

Phase 1, Module 7. Migrate dispatch in `renderers/telegram/renderer.py`
to a `_registry` dict. The existing `_INLINE_FIELD_TYPES` and
`_WEBAPP_FIELD_TYPES` module-level sets remain but become inputs to
per-type renderer registration rather than dispatch logic.

---

## Scope

- Add `_registry: dict[FieldType, FieldRenderer]` to `TelegramFormRenderer`
- Keep `_INLINE_FIELD_TYPES` and `_WEBAPP_FIELD_TYPES` module-level sets
  (they will be extended in Phase 2 TASK-1151)
- Migrate existing dispatch to registered callables using those sets
- Replace dispatch with `_registry.get(field.field_type, self._fallback)`
- Public `TelegramFormRenderer.render()` signature remains unchanged

**NOT in scope**: New FieldType values, RenderWarning, AuthContext.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/telegram/renderer.py` | MODIFY | Add `_registry` dict, migrate dispatch |
| `packages/parrot-formdesigner/tests/unit/test_telegram_renderer.py` | MODIFY | Add `test_telegram_registry_dispatch_existing_types` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# telegram/renderer.py existing imports (verified):
from ...core.options import FieldOption
from ...core.schema import FormField, FormSchema, FormSection, RenderedForm
from ...core.style import StyleSchema
from ...core.types import FieldType, LocalizedString
from ..base import AbstractFormRenderer
from .models import (
    FormFieldCallback, TelegramFormPayload, TelegramFormStep, TelegramRenderMode,
)

# Add after TASK-1139:
from ..base import FieldRenderer, FallbackRenderer
```

### Existing Module-Level Sets (verified at line 28)
```python
_INLINE_FIELD_TYPES = {
    FieldType.SELECT, FieldType.MULTI_SELECT, FieldType.BOOLEAN, FieldType.HIDDEN,
}

_WEBAPP_FIELD_TYPES = {
    FieldType.TEXT, FieldType.TEXT_AREA, FieldType.NUMBER, FieldType.INTEGER,
    FieldType.DATE, FieldType.DATETIME, FieldType.TIME, FieldType.EMAIL,
    FieldType.URL, FieldType.PHONE, FieldType.PASSWORD, FieldType.COLOR,
    FieldType.FILE, FieldType.IMAGE, FieldType.GROUP, FieldType.ARRAY,
}

_FILE_FIELD_TYPES = {FieldType.FILE, FieldType.IMAGE}
_MAX_INLINE_OPTIONS = 5  # line 59
```

### Existing Signatures to Use
```python
# telegram/renderer.py — AbstractFormRenderer subclass
class TelegramFormRenderer(AbstractFormRenderer):
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

The Telegram renderer's "dispatch" is classification-based (inline vs WebApp),
not field-by-field rendering. The registry here should map each FieldType to
a callable that returns the correct `TelegramFormStep` representation.

Strategy:
- Fields in `_INLINE_FIELD_TYPES` → registered with inline keyboard renderer
- Fields in `_WEBAPP_FIELD_TYPES` → registered with WebApp redirect renderer
- `_fallback` → WebApp redirect (safe default for unknown types)

Keep `_INLINE_FIELD_TYPES` and `_WEBAPP_FIELD_TYPES` as sets for the
classification logic — they will be used in TASK-1151 to add new types.

---

## Acceptance Criteria

- [ ] `TelegramFormRenderer._registry` contains all 20 existing FieldType values
- [ ] `_INLINE_FIELD_TYPES` and `_WEBAPP_FIELD_TYPES` sets preserved at module level
- [ ] All existing `test_telegram_renderer.py` tests pass unchanged
- [ ] `test_telegram_registry_dispatch_existing_types` passes
- [ ] `ruff check packages/parrot-formdesigner/` passes

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/test_telegram_renderer.py
# Add to existing test file:

@pytest.mark.asyncio
async def test_telegram_registry_dispatch_existing_types():
    """All 20 existing FieldType values render via Telegram registry without error."""
    from parrot_formdesigner.renderers.telegram.renderer import TelegramFormRenderer
    renderer = TelegramFormRenderer()
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
        assert result is not None, f"Telegram renderer returned None for {ft}"
```

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
