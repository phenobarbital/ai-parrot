---
type: Wiki Overview
title: 'TASK-1155: AuthContext Model'
id: doc:sdd-tasks-completed-task-1155-authcontext-model-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Phase 3, Module 17. Creates the `AuthContext` Pydantic model in a new
---

# TASK-1155: AuthContext Model

**Feature**: FEAT-167 — FormDesigner New Field Types
**Spec**: `sdd/specs/formdesigner-new-fields.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1146
**Assigned-to**: unassigned

---

## Context

Phase 3, Module 17. Creates the `AuthContext` Pydantic model in a new
`services/auth_context.py` module. `AuthContext` is the runtime auth context
constructed per-request by the aiohttp handler. It is distinct from the
schema-side `AuthConfig` (`core/auth.py`).

---

## Scope

- Create `services/auth_context.py` with `AuthContext` Pydantic model
- Implement `AuthContext.resolve_for(auth_ref: str | None) -> dict[str, str]`
- Document cascade behaviour (parent flows into nested GROUP/ARRAY fields)

**NOT in scope**: OptionsLoader (TASK-1156), API handler wiring (TASK-1158).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/auth_context.py` | CREATE | AuthContext model |
| `packages/parrot-formdesigner/tests/unit/test_auth_config.py` | MODIFY | Add AuthContext tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# services/ existing modules (verified):
# - cache.py, forwarder.py, _identifiers.py, registry.py, storage.py,
#   submissions.py, validators.py
# auth_context.py does NOT exist yet — this task creates it

# core/auth.py (verified — distinct from AuthContext):
# AuthConfig = NoAuth | BearerAuth | ApiKeyAuth  (line 145)
# NoAuth.resolve() -> dict[str, str]  (line 68)
# BearerAuth.resolve() -> dict[str, str] (line 95)
# ApiKeyAuth.resolve() -> dict[str, str] (line 131)
```

### New Module Spec
```python
# services/auth_context.py — NEW
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict

class AuthContext(BaseModel):
    """Runtime auth context constructed by the aiohttp handler per request.

    Distinct from core.auth.AuthConfig which is the schema-side declaration.
    AuthContext carries resolved credentials and is passed explicitly to
    OptionsLoader.fetch() / RemoteResponseResolver.resolve() / renderers.

    Cascade: the same AuthContext flows into nested GROUP / ARRAY field
    rendering without re-resolution.

    Attributes:
        scheme: Auth scheme identifier.
        token: Bearer token or API key value.
        headers: Raw outbound HTTP headers (pre-built).
        claims: Parsed JWT claims if available.
    """
    model_config = ConfigDict(extra="forbid")

    scheme: Literal["none", "bearer", "api_key", "custom"]
    token: str | None = None
    headers: dict[str, str] = {}
    claims: dict[str, Any] = {}

    def resolve_for(self, auth_ref: str | None) -> dict[str, str]:
        """Return outbound HTTP headers for the given auth_ref.

        If auth_ref matches one of the known token env-var references
        in self.claims, returns the appropriate header. Falls back to
        self.headers if auth_ref is None or unrecognized.

        Args:
            auth_ref: Optional string key identifying which auth credentials to use.

        Returns:
            Dict of HTTP headers to include in outbound requests, or {} if no auth.
        """
        if auth_ref is None or self.scheme == "none":
            return {}
        if self.scheme == "bearer" and self.token:
            return {"Authorization": f"Bearer {self.token}"}
        if self.scheme == "api_key" and self.token:
            return {"X-API-Key": self.token}
        # For "custom" scheme, return pre-built headers
        return dict(self.headers)
```

### Does NOT Exist
- ~~`AuthContext`~~ in the codebase — THIS task creates it
- ~~`services/auth_context.py`~~ — THIS task creates it
- ~~`core.auth.AuthContext`~~ — does NOT exist; `AuthConfig` is at `core.auth`

---

## Acceptance Criteria

- [ ] `services/auth_context.py` exists and is importable
- [ ] `from parrot_formdesigner.services.auth_context import AuthContext` resolves
- [ ] `AuthContext(scheme="bearer", token="tok").resolve_for("MY_API")` returns Bearer header
- [ ] `AuthContext(scheme="none").resolve_for(None)` returns `{}`
- [ ] Unknown `auth_ref` with bearer scheme returns `{"Authorization": "Bearer <token>"}`
- [ ] `test_auth_context_resolve_for_known_ref` passes
- [ ] `test_auth_context_resolve_for_unknown_ref` passes
- [ ] `ruff check packages/parrot-formdesigner/` passes

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/test_auth_config.py
# Add AuthContext tests (alongside existing AuthConfig tests):

import pytest
from parrot_formdesigner.services.auth_context import AuthContext


def test_auth_context_resolve_for_bearer():
    """AuthContext with bearer scheme returns Authorization header."""
    ctx = AuthContext(scheme="bearer", token="my-token")
    headers = ctx.resolve_for("SOME_REF")
    assert headers == {"Authorization": "Bearer my-token"}


def test_auth_context_resolve_for_none_scheme():
    """AuthContext with 'none' scheme returns empty dict."""
    ctx = AuthContext(scheme="none")
    assert ctx.resolve_for(None) == {}
    assert ctx.resolve_for("ANY_REF") == {}


def test_auth_context_resolve_for_unknown_ref():
    """Unknown auth_ref with bearer still returns Bearer header — no raise."""
    ctx = AuthContext(scheme="bearer", token="test-token")
    headers = ctx.resolve_for("UNKNOWN_REF")
    assert "Authorization" in headers  # does not raise


def test_auth_context_custom_headers():
    """Custom scheme returns pre-built headers."""
    ctx = AuthContext(
        scheme="custom",
        headers={"X-Custom-Auth": "secret", "X-Tenant": "acme"}
    )
    headers = ctx.resolve_for("CUSTOM_REF")
    assert headers["X-Custom-Auth"] == "secret"


def test_auth_context_default_values():
    """AuthContext defaults are correct."""
    ctx = AuthContext(scheme="none")
    assert ctx.token is None
    assert ctx.headers == {}
    assert ctx.claims == {}
```

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
