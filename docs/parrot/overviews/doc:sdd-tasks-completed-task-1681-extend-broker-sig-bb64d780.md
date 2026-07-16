---
type: Wiki Overview
title: 'TASK-1681: Extend broker signal models with `device_code` kind + device-code
  fields'
id: doc:sdd-tasks-completed-task-1681-extend-broker-signal-models-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements spec §3 Module 1. The device-code resolver (TASK-1683) and the
  future chat
relates_to:
- concept: mod:parrot.auth.credentials
  rel: mentions
---

# TASK-1681: Extend broker signal models with `device_code` kind + device-code fields

**Feature**: FEAT-266 — O365 Auth Homologation
**Spec**: `sdd/specs/o365-auth-homologation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 1. The device-code resolver (TASK-1683) and the future chat
surface need `"device_code"` as a valid `AuthKind` and need to surface the Microsoft
device-login `user_code` / `verification_uri` / `expires_in`. The broker's signal models
(`NeedsAuth`, `CredentialRequired`) currently carry only a single `auth_url`. This task
makes the additive, backward-compatible model change. Foundational — TASK-1683/1684 depend
on it.

---

## Scope

- Add `"device_code"` to the `AuthKind` `Literal` in `parrot/auth/credentials.py`.
- Add three OPTIONAL fields to `NeedsAuth` (default `None`): `user_code`,
  `verification_uri`, `expires_in`.
- Add matching OPTIONAL attributes to `CredentialRequired` — new `__init__` parameters must
  be keyword-only with `None` defaults so the existing 3-positional-arg call sites
  (`provider`, `auth_url`, `auth_kind`) keep working unchanged.
- Write unit tests for the additions.

**NOT in scope**: the resolver (TASK-1683), the factory branch (TASK-1684), any refresh logic.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/credentials.py` | MODIFY | `AuthKind` += `"device_code"`; optional fields on `NeedsAuth` + `CredentialRequired` |
| `packages/ai-parrot/tests/auth/test_credentials_devicecode.py` | CREATE | Unit tests (path: mirror existing auth tests location) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.auth.credentials import (
    AuthKind, ProviderCredentialConfig, NeedsAuth, CredentialRequired,
)  # packages/ai-parrot/src/parrot/auth/credentials.py
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/auth/credentials.py
AuthKind = Literal["obo", "oauth2", "static_key", "mcp"]          # line 43

class NeedsAuth(BaseModel):                                       # line 82
    provider: str
    auth_url: str = Field(..., description="Consent URL — NEVER a secret")
    auth_kind: AuthKind = Field(..., description="Drives surface card rendering")

class CredentialRequired(Exception):                             # line 97
    def __init__(self, provider: str, auth_url: str, auth_kind: str) -> None:  # line 113
        # sets self.provider / self.auth_url / self.auth_kind

class ProviderCredentialConfig(BaseModel):                       # line 46
    provider: str; auth: AuthKind; options: Dict[str, Any]
```

### Does NOT Exist
- ~~`NeedsAuth.user_code` / `.verification_uri` / `.expires_in`~~ — added by THIS task.
- ~~`"device_code"` in `AuthKind`~~ — added by THIS task.
- Do NOT touch `CredentialResolver`, `OAuthCredentialResolver`, or any resolver here.

---

## Implementation Notes

### Key Constraints
- Purely additive: do not reorder fields, do not change existing required fields.
- `CredentialRequired` new params must be keyword-only with `None` defaults:
  `def __init__(self, provider, auth_url, auth_kind, *, user_code=None, verification_uri=None, expires_in=None)`.
- `expires_in` is an `Optional[int]` (seconds). `user_code` / `verification_uri` are `Optional[str]`.
- Keep Google-style docstrings; update the class docstrings to mention the new fields.

### References in Codebase
- `packages/ai-parrot/src/parrot/auth/credentials.py:82-120` — the two models to extend.

---

## Acceptance Criteria

- [ ] `"device_code"` is a valid `AuthKind`; `ProviderCredentialConfig(provider="o365", auth="device_code")` validates.
- [ ] `NeedsAuth(provider=..., auth_url=..., auth_kind="device_code", user_code="A1B2-C3D4", verification_uri="https://microsoft.com/devicelogin", expires_in=900)` constructs; all three default to `None` when omitted.
- [ ] `CredentialRequired("o365", "https://...", "device_code")` (3 positional args) still works unchanged; new kwargs accepted and stored as attributes.
- [ ] Existing `obo|oauth2|static_key|mcp` call sites of both models are unaffected (no breaking change).
- [ ] Tests pass: `pytest packages/ai-parrot/tests/auth/test_credentials_devicecode.py -v`.
- [ ] `ruff check packages/ai-parrot/src/parrot/auth/credentials.py` clean.

---

## Test Specification

```python
import pytest
from parrot.auth.credentials import (
    AuthKind, ProviderCredentialConfig, NeedsAuth, CredentialRequired,
)

def test_authkind_includes_device_code():
    cfg = ProviderCredentialConfig(provider="o365", auth="device_code")
    assert cfg.auth == "device_code"

def test_needsauth_optional_devicecode_fields_default_none():
    n = NeedsAuth(provider="o365", auth_url="https://x", auth_kind="device_code")
    assert n.user_code is None and n.verification_uri is None and n.expires_in is None

def test_needsauth_carries_devicecode_fields():
    n = NeedsAuth(provider="o365", auth_url="https://microsoft.com/devicelogin",
                  auth_kind="device_code", user_code="A1B2-C3D4",
                  verification_uri="https://microsoft.com/devicelogin", expires_in=900)
    assert n.user_code == "A1B2-C3D4" and n.expires_in == 900

def test_credentialrequired_backward_compatible():
    e = CredentialRequired("o365", "https://x", "device_code")
    assert e.provider == "o365" and e.auth_kind == "device_code"
    assert getattr(e, "user_code", None) is None
```

---

## Agent Instructions
Follow the standard SDD agent flow: verify the contract, implement per scope, run tests,
move this file to `sdd/tasks/completed/`, update the per-spec index status to `done`.

## Completion Note
Added `"device_code"` to `AuthKind`, and three optional fields (`user_code`,
`verification_uri`, `expires_in`, all default `None`) to both `NeedsAuth` and
`CredentialRequired` (the latter as keyword-only `__init__` params, preserving
the 3-positional-arg call signature). Created
`packages/ai-parrot/tests/auth/test_credentials_devicecode.py` with 7 tests
covering AuthKind validation, default-None behavior, field round-trip, and
backward compatibility of existing `obo`/`oauth2`/`static_key`/`mcp` call
sites. All tests pass; `ruff check` clean. No deviations from spec.
