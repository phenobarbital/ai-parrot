---
type: Wiki Overview
title: 'TASK-1158: API Handler — Build AuthContext from Request'
id: doc:sdd-tasks-completed-task-1158-api-handler-authcontext-integration-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Phase 3, Module 20. Extends `api/handlers.py` to construct `AuthContext`
relates_to:
- concept: mod:parrot.clients.base
  rel: mentions
---

# TASK-1158: API Handler — Build AuthContext from Request

**Feature**: FEAT-167 — FormDesigner New Field Types
**Spec**: `sdd/specs/formdesigner-new-fields.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1155, TASK-1156, TASK-1157
**Assigned-to**: unassigned

---

## Context

Phase 3, Module 20. Extends `api/handlers.py` to construct `AuthContext`
from the inbound aiohttp request (Authorization header, session, or
middleware-provided attribute) and pass it explicitly to `FormValidator`
and renderers via kwarg. AuthContext then cascades automatically into
nested GROUP/ARRAY field renders.

---

## Scope

- Extend `FormAPIHandler` with a `_build_auth_context(request)` private method
- Call `_build_auth_context` in render/validate aiohttp handler methods
- Pass `auth_context` kwarg to `FormValidator` and renderer calls
- Do NOT change any public HTTP endpoint paths or response formats

**NOT in scope**: OptionsLoader integration in renderers (renderers call
OptionsLoader themselves when they encounter DYNAMIC_SELECT — that wiring
is renderer-specific and out of this task's scope). This task only wires
`AuthContext` construction and propagation.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` | MODIFY | Add _build_auth_context + pass auth_context to renderer/validator |
| `packages/parrot-formdesigner/tests/unit/test_renderers.py` | MODIFY | Add test_e2e_authcontext_cascade_into_group |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# api/handlers.py current imports (verified):
from __future__ import annotations
import json
import logging
from typing import TYPE_CHECKING
from aiohttp import web
from pydantic import ValidationError
from ..core.schema import FormSchema, RenderedForm
from ..renderers.jsonschema import JsonSchemaRenderer
from ..services.registry import FormRegistry
from ..services.validators import FormValidator
from ._utils import _bump_version, _deep_merge, _loc_to_str

if TYPE_CHECKING:
    from parrot.clients.base import AbstractClient
    from ..services.forwarder import SubmissionForwarder
    from ..services.submissions import FormSubmissionStorage

# Add (after TASK-1155):
from ..services.auth_context import AuthContext
```

### Existing Signatures to Use
```python
# api/handlers.py:32 — FormAPIHandler (verified):
class FormAPIHandler:
    def __init__(
        self,
        registry: FormRegistry,
        # ... other args — read full __init__ to see all params
    ) -> None: ...
    # aiohttp handlers are async methods that receive web.Request
    # and return web.Response
```

### Does NOT Exist
- ~~`AuthContext` in handlers.py~~ — THIS task adds it
- ~~Renderer `render()` accepting `auth_context` kwarg~~ — renderers' public
  signature is BYTE-IDENTICAL; pass `auth_context` only to internal
  dispatch helpers, not to the public `render()` call

---

## Implementation Notes

### AuthContext Construction

```python
def _build_auth_context(self, request: web.Request) -> AuthContext:
    """Build AuthContext from the inbound aiohttp request.

    Checks (in order):
    1. request['auth_context'] (set by navigator-auth middleware if present)
    2. Authorization header (Bearer token)
    3. Defaults to scheme='none'

    Args:
        request: The incoming aiohttp web.Request.

    Returns:
        AuthContext for this request.
    """
    # Check if middleware already resolved auth
    if "auth_context" in request:
        existing = request["auth_context"]
        if isinstance(existing, AuthContext):
            return existing

    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        return AuthContext(
            scheme="bearer",
            token=token,
            headers={"Authorization": auth_header},
        )
    if auth_header.startswith("ApiKey "):
        token = auth_header[7:]
        return AuthContext(
            scheme="api_key",
            token=token,
            headers={"X-API-Key": token},
        )
    return AuthContext(scheme="none")
```

### Passing auth_context
Read `handlers.py` fully to understand which handler methods call renderers
or validators. In those methods, add:
```python
auth_context = self._build_auth_context(request)
# Pass to any internal calls that need it (validator, options-fetching helpers)
# NOTE: Do NOT pass auth_context to renderer.render() — its public signature is unchanged
# Instead, store it on the request or pass to internal methods
```

### Cascade Into Nested Fields
The cascade is automatic once `AuthContext` is threaded into renderer
dispatch helpers. The `_registry.get()` dispatch already passes kwargs —
as long as the auth_context kwarg is forwarded to nested field renders,
it cascades without re-resolution.

---

## Acceptance Criteria

- [ ] `FormAPIHandler._build_auth_context(request)` exists
- [ ] Bearer token from `Authorization: Bearer <token>` is extracted correctly
- [ ] `AuthContext(scheme="none")` returned when no auth header present
- [ ] Existing handler tests pass unchanged
- [ ] `test_e2e_authcontext_cascade_into_group` passes
- [ ] `ruff check packages/parrot-formdesigner/` passes

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/test_renderers.py (or integration/)
import pytest
from unittest.mock import MagicMock


def test_build_auth_context_from_bearer_header():
    """Bearer token in Authorization header → AuthContext(scheme='bearer')."""
    from parrot_formdesigner.api.handlers import FormAPIHandler
    from parrot_formdesigner.services.registry import FormRegistry
    handler = FormAPIHandler(registry=FormRegistry())
    # Mock request with Authorization header
    mock_request = MagicMock()
    mock_request.headers = {"Authorization": "Bearer my-token"}
    mock_request.__contains__ = MagicMock(return_value=False)  # no pre-resolved context
    ctx = handler._build_auth_context(mock_request)
    assert ctx.scheme == "bearer"
    assert ctx.token == "my-token"


def test_build_auth_context_no_header():
    """No Authorization header → AuthContext(scheme='none')."""
    from parrot_formdesigner.api.handlers import FormAPIHandler
    from parrot_formdesigner.services.registry import FormRegistry
    handler = FormAPIHandler(registry=FormRegistry())
    mock_request = MagicMock()
    mock_request.headers = {}
    mock_request.__contains__ = MagicMock(return_value=False)
    ctx = handler._build_auth_context(mock_request)
    assert ctx.scheme == "none"


@pytest.mark.asyncio
async def test_e2e_authcontext_cascade_into_group():
    """Nested GROUP field's child resolves via parent's AuthContext."""
    # This test verifies that when a GROUP field contains a DYNAMIC_SELECT child,
    # the renderer threads auth_context down to the nested field renderer.
    # Implementation: render a form with a GROUP containing a DYNAMIC_SELECT,
    # verify no KeyError/AttributeError when auth_context is present.
    pass  # Implement after reviewing GROUP field rendering in html5.py
```

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
