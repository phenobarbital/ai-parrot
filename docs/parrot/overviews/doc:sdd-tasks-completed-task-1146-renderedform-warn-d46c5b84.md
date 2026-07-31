---
type: Wiki Overview
title: 'TASK-1146: RenderedForm.warnings + RenderWarning Model'
id: doc:sdd-tasks-completed-task-1146-renderedform-warnings-renderwarning-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Phase 1, Module 8. Adds `RenderWarning` Pydantic model and extends
---

# TASK-1146: RenderedForm.warnings + RenderWarning Model

**Feature**: FEAT-167 — FormDesigner New Field Types
**Spec**: `sdd/specs/formdesigner-new-fields.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1139
**Assigned-to**: unassigned

---

## Context

Phase 1, Module 8. Adds `RenderWarning` Pydantic model and extends
`RenderedForm` with `warnings: list[RenderWarning] = []`. The default
empty list preserves backwards compatibility. This is what enables
Phase 2 fallback renderers to surface degraded rendering information
to callers.

---

## Scope

- Add `RenderWarning` Pydantic model to `core/schema.py`
- Add `warnings: list[RenderWarning] = []` field to `RenderedForm`
- Update `RenderedForm` docstring to document the new field
- Export `RenderWarning` from `parrot_formdesigner.core.schema`

**NOT in scope**: Actual warning emission logic (done in TASK-1151 when
new types use FallbackRenderer).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py` | MODIFY | Add `RenderWarning` and `RenderedForm.warnings` |
| `packages/parrot-formdesigner/tests/unit/test_core_models.py` | MODIFY | Add `test_rendered_form_warnings_default_empty` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# core/schema.py current imports (verified):
from __future__ import annotations
from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict
from .auth import AuthConfig
from .constraints import DependencyRule, FieldConstraints
from .options import FieldOption, OptionsSource
from .types import FieldType, LocalizedString
```

### Existing Signatures to Use
```python
# core/schema.py:145 — RenderedForm current state (verified):
class RenderedForm(BaseModel):
    content: Any              # line 155
    content_type: str         # line 156
    style_output: Any | None = None    # line 157
    metadata: dict[str, Any] | None = None  # line 158
    # ADD: warnings: list[RenderWarning] = []
```

### Does NOT Exist
- ~~`RenderWarning`~~ — THIS task creates it
- ~~`RenderedForm.warnings`~~ — THIS task adds it
- ~~`AuthContext`~~ — TASK-1155

---

## Implementation Notes

### RenderWarning Model
```python
class RenderWarning(BaseModel):
    """Warning emitted when a renderer uses degraded fallback for a field type.

    Attributes:
        field_id: The ID of the field that triggered the fallback.
        field_type: The FieldType.value string (e.g. "signature").
        renderer: The renderer name ("html5" | "adaptive_card" | "pdf" |
                  "xforms" | "jsonschema" | "telegram").
        reason: Human-readable explanation (e.g. "unsupported in PDF — rendered as placeholder").
    """
    field_id: str
    field_type: str          # FieldType.value — str to avoid circular import risks
    renderer: str
    reason: str
```

Place `RenderWarning` BEFORE `RenderedForm` in `schema.py` so `RenderedForm`
can reference it without forward-reference issues.

### RenderedForm Extension
```python
class RenderedForm(BaseModel):
    """Output of a form renderer.
    ...
    Attributes:
        ...
        warnings: Degraded-rendering warnings. Empty list when all fields
            rendered natively. One entry per (field_id, renderer) pair that
            used FallbackRenderer.
    """
    content: Any
    content_type: str
    style_output: Any | None = None
    metadata: dict[str, Any] | None = None
    warnings: list[RenderWarning] = []  # NEW — default empty for backwards compat
```

### Backwards Compatibility
Existing code that creates `RenderedForm(content=..., content_type=...)` will
continue to work — `warnings` defaults to `[]`. No migration needed.

---

## Acceptance Criteria

- [ ] `RenderWarning` model exists in `core/schema.py`
- [ ] `RenderedForm.warnings` exists with default `[]`
- [ ] `from parrot_formdesigner.core.schema import RenderWarning` resolves
- [ ] `RenderedForm()` instantiates without specifying `warnings`
- [ ] `RenderedForm(content=x, content_type="text/html").warnings == []`
- [ ] `test_rendered_form_warnings_default_empty` passes
- [ ] All existing `test_core_models.py` tests pass unchanged
- [ ] `ruff check packages/parrot-formdesigner/` passes

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/test_core_models.py
# Add to existing test file:

from parrot_formdesigner.core.schema import RenderedForm, RenderWarning


def test_rendered_form_warnings_default_empty():
    """RenderedForm defaults warnings to empty list."""
    rf = RenderedForm(content="<form/>", content_type="text/html")
    assert rf.warnings == []


def test_render_warning_model():
    """RenderWarning has all required fields."""
    w = RenderWarning(
        field_id="sig1",
        field_type="signature",
        renderer="pdf",
        reason="unsupported in PDF — rendered as placeholder",
    )
    assert w.field_id == "sig1"
    assert w.renderer == "pdf"


def test_rendered_form_with_warnings():
    """RenderedForm accepts and stores warnings."""
    w = RenderWarning(field_id="f1", field_type="nps", renderer="xforms", reason="fallback")
    rf = RenderedForm(content={}, content_type="application/json", warnings=[w])
    assert len(rf.warnings) == 1
    assert rf.warnings[0].field_type == "nps"
```

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
