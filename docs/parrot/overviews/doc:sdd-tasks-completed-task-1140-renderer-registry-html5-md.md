---
type: Wiki Overview
title: 'TASK-1140: Renderer Registry — HTML5'
id: doc:sdd-tasks-completed-task-1140-renderer-registry-html5-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Phase 1, Module 2. Migrate the existing `if/elif field_type` dispatch chain
  in
---

# TASK-1140: Renderer Registry — HTML5

**Feature**: FEAT-167 — FormDesigner New Field Types
**Spec**: `sdd/specs/formdesigner-new-fields.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1139
**Assigned-to**: unassigned

---

## Context

Phase 1, Module 2. Migrate the existing `if/elif field_type` dispatch chain in
`renderers/html5.py` (~line 217+) into a `_registry: dict[FieldType, FieldRenderer]`
attribute populated in `HTML5Renderer.__init__()`. Public `render()` stays unchanged.
Existing tests must pass byte-identical before/after migration.

---

## Scope

- Add `_registry: dict[FieldType, FieldRenderer]` attribute to `HTML5Renderer`
- Create inline `FieldRenderer`-compatible callables (or inner classes) for each
  of the existing 20 FieldType values currently in the if/elif chain
- Replace the if/elif dispatch with `_registry.get(field.field_type, self._fallback)`
- `_fallback` is a `FallbackRenderer` instance added to the renderer
- Public `HTML5Renderer.render()` signature remains unchanged
- Populate `_registry` in `__init__()`, not at module import time

**NOT in scope**: New FieldType values (Phase 2), RenderWarning emission (Module 8 not yet merged).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/html5.py` | MODIFY | Add `_registry` dict, migrate if/elif dispatch |
| `packages/parrot-formdesigner/tests/unit/test_renderers.py` | MODIFY | Add `test_html5_registry_dispatch_existing_types` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# From renderers/base.py (after TASK-1139):
from parrot_formdesigner.renderers.base import (
    AbstractFormRenderer,
    FieldRenderer,
    FallbackRenderer,
)

# html5.py existing imports (verified):
from ..core.constraints import DependencyRule
from ..core.options import FieldOption
from ..core.schema import FormField, FormSchema, RenderedForm
from ..core.style import FieldSizeHint, LayoutType, StyleSchema
from ..core.types import FieldType, LocalizedString
from .base import AbstractFormRenderer
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/renderers/html5.py
# - _render_field_html(self, field, prefilled, errors, style, locale) -> str
# - _render_input(self, field, value, locale) -> str
# - _render_select(self, field, value, locale, multiple) -> str
# - _render_textarea(self, field, value, locale) -> str
# - _render_checkbox(self, field, value) -> str
# - _render_radio_group(self, field, value, locale) -> str
# All of these MUST remain intact and callable — do NOT rename them

# _INPUT_TYPE_MAP dict at line 27 — keep as is
_INPUT_TYPE_MAP: dict[FieldType, str] = { ... }

# _resolve(value, locale) function at line 46 — keep as is
```

### Does NOT Exist
- ~~`RenderWarning`~~ — not yet; TASK-1146
- ~~`RenderedForm.warnings`~~ — not yet; TASK-1146
- ~~New FieldType values (SIGNATURE, NPS, etc.)~~ — not yet; TASK-1147
- ~~`AuthContext`~~ — not yet; TASK-1155

---

## Implementation Notes

### Registry Pattern

The registry maps `FieldType` → async callable matching `FieldRenderer.render()`.
Use `functools.partial` or lambdas to wrap existing private methods:

```python
class HTML5Renderer(AbstractFormRenderer):
    def __init__(self):
        self._fallback = FallbackRenderer()
        self._registry: dict[FieldType, FieldRenderer] = {}
        self._build_registry()

    def _build_registry(self) -> None:
        """Populate the per-type renderer registry."""
        # Each lambda wraps existing private render methods
        # The FieldRenderer protocol is structural — any callable with the
        # correct async signature satisfies it.
        # ...register all 20 existing FieldType values here...
```

### Dispatch in `_render_field_html`
Replace the if/elif chain with:
```python
renderer = self._registry.get(field.field_type, self._fallback)
result = await renderer.render(field, locale=locale, prefilled=value, error=error)
```

Note: `_render_field_html` is currently synchronous. If wrapping async renderers
in a sync context is complex, convert `_render_field_html` to `async def` and
propagate through the call chain. Verify this does not break the public `render()` test.

### Snapshot Test Approach
Generate HTML output for all 20 field types using existing test fixtures, assert
byte-identical output after migration.

---

## Acceptance Criteria

- [ ] `HTML5Renderer._registry` is populated with all 20 existing FieldType values
- [ ] `_render_field_html` dispatches via `_registry`
- [ ] All existing `test_renderers.py` tests pass unchanged
- [ ] `test_html5_registry_dispatch_existing_types` passes
- [ ] `ruff check packages/parrot-formdesigner/` passes

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/test_renderers.py

import pytest
from parrot_formdesigner.renderers.html5 import HTML5Renderer
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.core.schema import FormField, FormSection, FormSchema


@pytest.mark.asyncio
async def test_html5_registry_dispatch_existing_types():
    """All 20 existing FieldType values render via registry without error."""
    renderer = HTML5Renderer()
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
        assert result.content is not None, f"Renderer returned None for {ft}"
```

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
