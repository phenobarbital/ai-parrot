---
type: Wiki Overview
title: 'TASK-1159: Validator Branch Wiring for REMOTE_RESPONSE'
id: doc:sdd-tasks-completed-task-1159-validator-remote-response-branch-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Phase 3, Module 21. Completes the deferred sub-task of TASK-1150 (Module
  12):'
---

# TASK-1159: Validator Branch Wiring for REMOTE_RESPONSE

**Feature**: FEAT-167 — FormDesigner New Field Types
**Spec**: `sdd/specs/formdesigner-new-fields.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1150, TASK-1157
**Assigned-to**: unassigned

---

## Context

Phase 3, Module 21. Completes the deferred sub-task of TASK-1150 (Module 12):
adds the `REMOTE_RESPONSE` validator branch in `services/validators.py`. This
branch invokes `RemoteResponseResolver.resolve()` and stores the result as the
field value before further validation. Depends on Phase 3 services being available.

---

## Scope

- Add `REMOTE_RESPONSE` validator branch to `FormValidator` in `services/validators.py`
- Branch invokes `RemoteResponseResolver.resolve(spec, content, auth_context=auth_context)`
- Parses `RemoteResponseSpec` from `FormField.meta`
- Stores resolved value as the field submission value
- Optionally validates against `RemoteResponseSpec.response_schema` (JSON Schema)

**NOT in scope**: Other FieldType validator branches (TASK-1150), any UI changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py` | MODIFY | Add REMOTE_RESPONSE validator branch |
| `packages/parrot-formdesigner/tests/unit/test_renderers.py` | MODIFY | Add e2e remote_response test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports (after prior tasks)
```python
# services/validators.py current imports (verified):
import logging
import re
from typing import Any, Callable
from pydantic import BaseModel
from ..core.schema import FormField, FormSchema, FormSection
from ..core.types import FieldType, LocalizedString

# Add for REMOTE_RESPONSE branch:
from ..services.remote_response_resolver import (
    RemoteResponseResolver,
    RemoteResponseSpec,
    RemoteResponseResult,
)
from ..services.auth_context import AuthContext
```

### Existing Signatures to Use
```python
# services/validators.py — read the full FormValidator to understand:
# - how validate_field(field, value, ...) is structured
# - where to add the REMOTE_RESPONSE branch
# - whether auth_context is already threaded (after TASK-1150/TASK-1158)

# RemoteResponseResolver (TASK-1157):
class RemoteResponseResolver:
    async def resolve(
        self,
        spec: RemoteResponseSpec,
        content: Any,
        *,
        auth_context: AuthContext | None = None,
    ) -> RemoteResponseResult: ...

# RemoteResponseSpec (TASK-1157):
class RemoteResponseSpec(BaseModel):
    endpoint: str
    http_method: Literal["GET", "POST"] = "POST"
    content_field: str | None = None
    prompt: str | None = None
    auth_ref: str | None = None
    timeout_seconds: int = 30
    response_schema: dict[str, Any] | None = None

# RemoteResponseResult (TASK-1157):
class RemoteResponseResult(BaseModel):
    success: bool
    value: Any | None = None
    status_code: int | None = None
    error: str | None = None
```

### Does NOT Exist
- ~~REMOTE_RESPONSE validator branch~~ — THIS task adds it (was deferred from TASK-1150)

---

## Implementation Notes

### Validator Branch Logic

```python
# In FormValidator, add branch for FieldType.REMOTE_RESPONSE:
elif field.field_type == FieldType.REMOTE_RESPONSE:
    # Parse RemoteResponseSpec from field.meta
    meta = field.meta or {}
    try:
        spec = RemoteResponseSpec(**meta)
    except Exception as e:
        return ValidationResult(
            valid=False,
            errors={field.field_id: f"Invalid REMOTE_RESPONSE spec in meta: {e}"}
        )

    # Resolve the remote response
    resolver = RemoteResponseResolver()
    result = await resolver.resolve(spec, value, auth_context=auth_context)

    if not result.success:
        return ValidationResult(
            valid=False,
            errors={field.field_id: f"Remote response failed: {result.error}"}
        )

    # Store resolved value
    validated_value = result.value

    # Optional: validate against response_schema
    if spec.response_schema and result.value is not None:
        # Basic validation — check required keys if specified
        pass

    return ValidationResult(valid=True, coerced_value=validated_value)
```

Read `services/validators.py` fully to understand `ValidationResult` or
equivalent return type before implementing.

---

## Acceptance Criteria

- [ ] `REMOTE_RESPONSE` validator branch exists in `FormValidator`
- [ ] Branch invokes `RemoteResponseResolver.resolve()`
- [ ] Resolved value stored as field submission value
- [ ] Invalid `RemoteResponseSpec` in meta produces validation error
- [ ] `test_e2e_form_submission_with_remote_response` passes
- [ ] All existing validator tests pass unchanged
- [ ] `ruff check packages/parrot-formdesigner/` passes

---

## Test Specification

```python
@pytest.mark.asyncio
async def test_e2e_form_submission_with_remote_response():
    """Mock aiohttp server → form submission triggers RemoteResponseResolver
    → resolved value stored as field value."""
    from parrot_formdesigner.core.types import FieldType
    from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection

    field = FormField(
        field_id="ai_summary",
        field_type=FieldType.REMOTE_RESPONSE,
        label="AI Summary",
        meta={
            "endpoint": "https://api.test/summarize",
            "http_method": "POST",
            "prompt": "Summarize this text",
        }
    )
    form = FormSchema(
        form_id="test", title="Test",
        sections=[FormSection(section_id="s1", fields=[field])]
    )

    # Mock RemoteResponseResolver.resolve() to return a known value
    from unittest.mock import AsyncMock, patch
    from parrot_formdesigner.services.remote_response_resolver import RemoteResponseResult

    with patch(
        "parrot_formdesigner.services.validators.RemoteResponseResolver.resolve",
        new_callable=AsyncMock,
        return_value=RemoteResponseResult(success=True, value={"summary": "Short text"})
    ):
        # Use FormValidator to validate the field
        # Assert the resolved value is stored
        pass
```

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 4.6)
**Date**: 2026-05-13
**Notes**: Threaded auth_context through FormValidator.validate() and validate_field().
Added _validate_remote_response() method that parses RemoteResponseSpec from field.meta,
calls RemoteResponseResolver.resolve(), and propagates resolved value into sanitized_data
via _resolved_remote_value attribute. Added 3 new tests (e2e success, missing endpoint,
resolver failure). Fixed 4 pre-existing ruff F401 warnings in test_renderers.py.

**Deviations from spec**: none | describe if any
