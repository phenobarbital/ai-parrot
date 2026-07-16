---
type: Wiki Overview
title: 'TASK-1139: FieldRenderer Protocol + Registry Skeleton'
id: doc:sdd-tasks-completed-task-1139-fieldrenderer-protocol-registry-skeleton-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Phase 1, Module 1. Introduces `FieldRenderer` protocol and `FallbackRenderer`
---

# TASK-1139: FieldRenderer Protocol + Registry Skeleton

**Feature**: FEAT-167 — FormDesigner New Field Types
**Spec**: `sdd/specs/formdesigner-new-fields.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Phase 1, Module 1. Introduces `FieldRenderer` protocol and `FallbackRenderer`
base class into `renderers/base.py`. This is the foundation that all subsequent
renderer registry tasks (TASK-1140 through TASK-1145) depend on. No changes to
`AbstractFormRenderer.render()` public signature.

Implements spec §2 (New Public Interfaces) and §3 Module 1.

---

## Scope

- Add `FieldRenderer` Protocol class to `renderers/base.py`
- Add `FallbackRenderer` abstract base class to `renderers/base.py`
- Do NOT modify `AbstractFormRenderer.render()` signature in any way
- Do NOT add `RenderWarning` (that is TASK-1146 / Module 8)
- Do NOT add `AuthContext` (that is Phase 3)

**NOT in scope**: Any renderer migration, new FieldType values, RenderWarning model.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/base.py` | MODIFY | Add `FieldRenderer` Protocol and `FallbackRenderer` base |
| `packages/parrot-formdesigner/tests/unit/test_renderers.py` | MODIFY | Add `test_field_renderer_protocol_minimal` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# renderers/base.py currently imports:
from abc import ABC, abstractmethod
from typing import Any
from ..core.schema import FormSchema, RenderedForm
from ..core.style import StyleSchema
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/renderers/base.py:14
class AbstractFormRenderer(ABC):
    @abstractmethod
    async def render(
        self,
        form: FormSchema,
        style: StyleSchema | None = None,
        *,
        locale: str = "en",
        prefilled: dict[str, Any] | None = None,
        errors: dict[str, str] | None = None,
    ) -> RenderedForm: ...
# SIGNATURE MUST STAY BYTE-IDENTICAL — do NOT modify

# packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py:145
class RenderedForm(BaseModel):
    content: Any
    content_type: str
    style_output: Any | None = None
    metadata: dict[str, Any] | None = None
    # NOTE: warnings field does NOT exist yet — added by TASK-1146

# packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py:21
class FormField(BaseModel):
    field_id: str
    field_type: FieldType  # from core/types.py
    label: LocalizedString
    meta: dict[str, Any] | None = None
```

### Does NOT Exist
- ~~`RenderWarning`~~ — does not exist yet; added in TASK-1146 (Module 8)
- ~~`RenderedForm.warnings`~~ — does not exist yet; added in TASK-1146
- ~~`AuthContext`~~ — does not exist; Phase 3 TASK-1155
- ~~`FieldRenderer` protocol~~ — does not exist yet; THIS task creates it
- ~~`FallbackRenderer`~~ — does not exist yet; THIS task creates it

---

## Implementation Notes

### New Protocol Definition
```python
# Add after existing imports in renderers/base.py
from typing import Protocol, runtime_checkable
from ..core.schema import FormField  # add to imports

@runtime_checkable
class FieldRenderer(Protocol):
    """Per-target field renderer. One concrete impl per (FieldType, output target).

    The render() signature uses keyword-only args so callers can pass optional
    context without breaking positional compatibility. Return type is Any
    because each output target uses a different representation (str for HTML5,
    dict for Adaptive Card/JSON Schema, bytes for PDF, etc.).
    """

    async def render(
        self,
        field: FormField,
        *,
        locale: str = "en",
        prefilled: Any = None,
        error: str | None = None,
    ) -> Any: ...
```

Note: `auth_context` is intentionally NOT in this signature at this stage —
Phase 3 adds it. Keep it out to avoid forward-referencing non-existent classes.

### FallbackRenderer Base
```python
class FallbackRenderer:
    """Concrete fallback emitter — degraded representation.

    Each renderer subclasses or instantiates this to define what 'degraded'
    means for its target. The base implementation returns None — subclasses
    must override render() to emit target-appropriate content.

    Warning appending is the renderer's responsibility (it has access to
    RenderedForm.warnings once Module 8 is merged).
    """

    async def render(
        self,
        field: FormField,
        *,
        locale: str = "en",
        prefilled: Any = None,
        error: str | None = None,
    ) -> Any:
        """Return None as placeholder. Override in renderer-specific subclasses."""
        return None
```

### Key Constraints
- `FieldRenderer` must be a `typing.Protocol` (structural typing, not ABC)
- `FallbackRenderer` is a concrete class (not abstract) — it has a default `render()` impl
- Do not add `from __future__ import annotations` if not already present

---

## Acceptance Criteria

- [ ] `FieldRenderer` Protocol class exists in `renderers/base.py`
- [ ] `FallbackRenderer` class exists in `renderers/base.py`
- [ ] `AbstractFormRenderer.render()` signature is byte-identical to pre-task state
- [ ] `from parrot_formdesigner.renderers.base import FieldRenderer, FallbackRenderer` resolves
- [ ] `test_field_renderer_protocol_minimal` passes
- [ ] `ruff check packages/parrot-formdesigner/` passes with zero warnings

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/test_renderers.py
# Add to existing file:

import pytest
from parrot_formdesigner.renderers.base import FieldRenderer, FallbackRenderer
from parrot_formdesigner.core.schema import FormField
from parrot_formdesigner.core.types import FieldType


def test_field_renderer_protocol_minimal():
    """FieldRenderer is a Protocol; FallbackRenderer satisfies it."""
    # FallbackRenderer must be a concrete, instantiable class
    fb = FallbackRenderer()
    assert fb is not None
    # FallbackRenderer must satisfy the FieldRenderer protocol (runtime-checkable)
    assert isinstance(fb, FieldRenderer)


@pytest.mark.asyncio
async def test_fallback_renderer_returns_none():
    """FallbackRenderer.render() returns None as placeholder."""
    fb = FallbackRenderer()
    field = FormField(field_id="x", field_type=FieldType.TEXT, label="X")
    result = await fb.render(field)
    assert result is None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/formdesigner-new-fields.spec.md` §2 and §3 Module 1
2. **Check dependencies** — none
3. **Verify the Codebase Contract** — read `renderers/base.py` to confirm current state
4. **Implement** only the two new classes in `renderers/base.py`
5. **Verify** `AbstractFormRenderer` signature is unchanged with `inspect.signature`
6. **Run tests**: `pytest packages/parrot-formdesigner/tests/unit/test_renderers.py -v`
7. **Run lint**: `ruff check packages/parrot-formdesigner/`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
