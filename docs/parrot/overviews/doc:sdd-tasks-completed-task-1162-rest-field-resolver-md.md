---
type: Wiki Overview
title: 'TASK-1162: `RestFieldSpec` discriminated union + `RestFieldResolver`'
id: doc:sdd-tasks-completed-task-1162-rest-field-resolver-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Phase 1 core service. Owns the discriminated-union spec model and the
---

# TASK-1162: `RestFieldSpec` discriminated union + `RestFieldResolver`

**Feature**: FEAT-170 — FormDesigner `FieldType.REST`
**Spec**: `sdd/specs/new-formdesigner-field-rest.spec.md` (Module 3)
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1160, TASK-1161
**Assigned-to**: unassigned

---

## Context

Phase 1 core service. Owns the discriminated-union spec model and the
3-mode resolver (remote / internal / callback). Mirrors — does NOT
subclass — `RemoteResponseResolver` (FEAT-167). Applies
`response_path` via `jsonpath-ng` and `display_template` via Jinja2's
`SandboxedEnvironment`. Returns `RestFieldResult` — **never raises**.

Resolution rules carry the Q2/Q3/Q5 refinements from spec §8.

---

## Scope

- Implement `parrot_formdesigner/services/rest_field_resolver.py`:
  - `RestFieldMode = Literal["remote", "internal", "callback"]`.
  - `_RestFieldSpecBase` + three concrete shapes:
    `RemoteRestFieldSpec`, `InternalRestFieldSpec`,
    `CallbackRestFieldSpec`. All `ConfigDict(extra="forbid")`.
  - `RestFieldSpec = Annotated[Union[...], Field(discriminator="mode")]`.
  - `RestCallbackInput` / `RestCallbackOutput` / `RestFieldResult`.
    `RestFieldResult.warnings: list[str]` — NOT `RenderWarning`
    (see spec §7 patterns + §8 Q5 resolution).
  - `RestFieldResolver` with constructor
    `(*, timeout=30, internal_base_url=None)` and `async resolve(spec,
    payload, *, auth_context=None, tenant=None) -> RestFieldResult`.
  - Internal-mode URL composition: validate leading `/`, resolve
    `internal_base_url` in order (arg → `PARROT_INTERNAL_BASE_URL` env
    → `request.host` only if request-bound is wired via the handler →
    `ConfigurationError`). SSRF guard: resolved host must be loopback
    or in `PARROT_INTERNAL_ALLOWED_HOSTS` (comma-separated env).
  - JSONPath extraction via `jsonpath-ng>=1.6.1`. Miss appends
    `"jsonpath_miss: <expr>"` to `result.warnings`.
  - Jinja2 `display_template` rendering via a private
    `SandboxedEnvironment` (NOT the html5 renderer's
    `Environment(autoescape=True)`).
  - `response_schema` validation via `jsonschema` (already a test-extra
    dep). Miss appends `"response_schema_mismatch: <detail>"` AND
    `logger.warning(...)`. Does NOT reject.
- Unit tests under
  `tests/unit/services/test_rest_field_resolver.py` covering all rows
  named `…Module 3` in spec §4 Unit Tests.

**NOT in scope**: blob persistence (TASK-1160), upload route
(TASK-1170), validator branch (TASK-1166).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/rest_field_resolver.py` | CREATE | Module |
| `packages/parrot-formdesigner/tests/unit/services/test_rest_field_resolver.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from collections.abc import Awaitable, Callable
from typing import Annotated, Any, Literal, Union
import logging
import os

import aiohttp
import jsonpath_ng                    # TASK-1169 adds to pyproject
from jinja2.sandbox import SandboxedEnvironment
from pydantic import BaseModel, ConfigDict, Field, field_validator

from parrot_formdesigner.services.auth_context import AuthContext       # verified: services/auth_context.py:20
from parrot_formdesigner.services.callback_registry import get_form_callback  # TASK-1161
```

### Existing Signatures to Use

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/services/auth_context.py:20
class AuthContext(BaseModel):
    scheme: Literal["none", "bearer", "api_key", "custom"]
    token: str | None = None
    headers: dict[str, str] = {}
    claims: dict[str, Any] = {}
    def resolve_for(self, auth_ref: str | None) -> dict[str, str]: ...  # line 44

# packages/parrot-formdesigner/src/parrot_formdesigner/services/remote_response_resolver.py:66
class RemoteResponseResolver:
    DEFAULT_TIMEOUT: int = 30           # line 81
    def __init__(self, timeout: int = DEFAULT_TIMEOUT) -> None: ...
    async def resolve(self, spec, content, *, auth_context=None): ...  # line 92
# MIRROR the aiohttp ClientSession + ClientTimeout + try/except skeleton
# from lines 122-145. DO NOT subclass.
```

### Does NOT Exist

- ~~`parrot_formdesigner.services.rest_field_resolver`~~ — new.
- ~~`RestFieldSpec` / `RestFieldResolver` / `RestFieldResult` /
  `RestCallbackInput` / `RestCallbackOutput` /
  `RemoteRestFieldSpec` / `InternalRestFieldSpec` /
  `CallbackRestFieldSpec`~~ — all new.
- ~~Subclassing `RemoteResponseResolver` or
  `RemoteResponseSpec`~~ — forbidden (spec §7 + §6).
- ~~Using `RenderWarning` for resolver warnings~~ — that model is
  renderer-scoped (`renderer: "html5"|"pdf"|...`). Use `list[str]`
  on `RestFieldResult.warnings` with convention `"code: detail"`.
- ~~`PARROT_INTERNAL_BASE_URL` env reading at module import~~ — read
  at *resolve* time, not import time (testability).

---

## Implementation Notes

### Model shapes (from spec §2 + Q5 refinement)

```python
RestFieldMode = Literal["remote", "internal", "callback"]

class _RestFieldSpecBase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    timeout_seconds: int = 30
    response_path: str | None = None
    display_template: str | None = None
    persist_binary: bool = True
    response_schema: dict[str, Any] | None = None

class RemoteRestFieldSpec(_RestFieldSpecBase):
    mode: Literal["remote"] = "remote"
    endpoint: str
    http_method: Literal["GET", "POST", "PUT", "PATCH"] = "POST"
    auth_ref: str | None = None

class InternalRestFieldSpec(_RestFieldSpecBase):
    mode: Literal["internal"] = "internal"
    endpoint: str
    http_method: Literal["GET", "POST", "PUT", "PATCH"] = "POST"

    @field_validator("endpoint")
    @classmethod
    def _leading_slash(cls, v):
        if not v.startswith("/"):
            raise ValueError("internal endpoint must start with '/'")
        return v

class CallbackRestFieldSpec(_RestFieldSpecBase):
    mode: Literal["callback"] = "callback"
    callback_ref: str

RestFieldSpec = Annotated[
    Union[RemoteRestFieldSpec, InternalRestFieldSpec, CallbackRestFieldSpec],
    Field(discriminator="mode"),
]

class RestFieldResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    success: bool
    raw_value: Any | None = None
    answer: Any | None = None
    blob_ref: str | None = None
    display: str | None = None
    status_code: int | None = None
    warnings: list[str] = []           # NOT RenderWarning
    error: str | None = None
```

### Internal-mode resolution (spec §7 Q2)

```python
def _resolve_internal_base_url(self, *, request_host: str | None) -> str:
    if self._internal_base_url:                       # constructor arg
        return self._internal_base_url
    env = os.environ.get("PARROT_INTERNAL_BASE_URL")
    if env:
        return env
    if request_host:                                  # request-bound path
        return f"http://{request_host}"  # scheme threading is handler concern
    raise ConfigurationError(
        "internal-mode field invoked without an internal_base_url. "
        "Set PARROT_INTERNAL_BASE_URL or pass internal_base_url to "
        "RestFieldResolver()."
    )

def _check_ssrf(self, host: str) -> None:
    allowed = set(["localhost", "127.0.0.1", "::1"])
    extra = os.environ.get("PARROT_INTERNAL_ALLOWED_HOSTS", "")
    allowed.update(h.strip() for h in extra.split(",") if h.strip())
    if host not in allowed:
        raise ValueError(f"internal host {host!r} not in allow-list")
```

(`ConfigurationError` is a new minor exception class defined in this
module — keep it local; do not invent a new shared exceptions module.)

### Never-raise contract

Every public exception path inside `resolve()` MUST be caught and
turned into `RestFieldResult(success=False, error="...")`. The only
exceptions that surface are programmer errors (e.g., calling with a
wrong-typed spec — a Pydantic validation failure during construction,
which happens *outside* `resolve`).

### Key constraints

- Async; `aiohttp.ClientSession` per-call (or per-resolver lifecycle —
  mirror `RemoteResponseResolver` exactly).
- `self.logger = logging.getLogger(__name__)`.
- `display_template` rendered with `SandboxedEnvironment()` —
  templates accessing `os`/filesystem raise `SecurityError`. Use a
  per-render timeout via `signal.alarm` is overkill — accept that the
  sandbox itself is the V1 guard.

---

## Acceptance Criteria

(All spec §5 criteria that name Module 3, plus:)

- [ ] `from parrot_formdesigner.services.rest_field_resolver import (RestFieldSpec, RestFieldResolver, RestFieldResult, RemoteRestFieldSpec, InternalRestFieldSpec, CallbackRestFieldSpec, RestCallbackInput, RestCallbackOutput)` succeeds.
- [ ] `RestFieldSpec.model_validate({"mode":"internal","endpoint":"api/x"})` raises (must start with `/`).
- [ ] `RestFieldSpec.model_validate({"mode":"remote","endpoint":"https://x","unknown":1})` raises (extra=forbid).
- [ ] `await resolver.resolve(spec, payload)` on an unknown callback_ref returns `success=False` and does NOT raise.
- [ ] aiohttp timeout returns `success=False, status_code=None, error="..."`.
- [ ] jsonpath miss → `answer=None, "jsonpath_miss: <expr>" in warnings`.
- [ ] `response_schema` miss → `success=True, "response_schema_mismatch: ..." in warnings`, logger.warning called.
- [ ] `display_template="{{ ''.__class__ }}"` raises a sandbox SecurityError at render.
- [ ] Internal-mode without env nor constructor + no request_host → `ConfigurationError` (first invocation).
- [ ] SSRF: internal host `evil.com` (with no allow-list override) → `success=False`.
- [ ] `ruff check` clean.

---

## Test Specification

Mirror spec §4 Unit Tests rows labelled Module 3, plus:

```python
import pytest, os
from parrot_formdesigner.services.rest_field_resolver import (
    RestFieldSpec, RestFieldResolver, RestFieldResult,
    RestCallbackInput, ConfigurationError,
)

def test_discriminated_remote():
    spec = RestFieldSpec.model_validate({
        "mode": "remote", "endpoint": "https://api.test/x"})
    assert spec.mode == "remote"

def test_internal_requires_leading_slash():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        RestFieldSpec.model_validate({"mode":"internal","endpoint":"api/x"})

async def test_resolver_callback_missing_returns_error():
    resolver = RestFieldResolver()
    spec = RestFieldSpec.model_validate({"mode":"callback","callback_ref":"nope"})
    payload = RestCallbackInput(form_id="f", field_id="x",
        session_id=None, user_id=None, tenant=None,
        content_type="text/plain", content=b"")
    result = await resolver.resolve(spec, payload)
    assert result.success is False and result.error

async def test_internal_no_base_url_raises_config_error():
    os.environ.pop("PARROT_INTERNAL_BASE_URL", None)
    resolver = RestFieldResolver()
    spec = RestFieldSpec.model_validate({"mode":"internal","endpoint":"/x"})
    with pytest.raises(ConfigurationError):
        await resolver.resolve(spec, RestCallbackInput(
            form_id="f", field_id="x", session_id=None, user_id=None,
            tenant=None, content_type="text/plain", content=b""))

async def test_jsonpath_miss_warning():
    # mocked aiohttp returns {"score": 0.86}; spec uses $.missing
    # asserts result.warnings contains "jsonpath_miss: $.missing"
    ...
```

---

## Completion Note

*(Agent fills this in when done)*
