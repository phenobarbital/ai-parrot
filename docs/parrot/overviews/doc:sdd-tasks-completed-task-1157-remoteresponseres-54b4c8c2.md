---
type: Wiki Overview
title: 'TASK-1157: RemoteResponseResolver Service'
id: doc:sdd-tasks-completed-task-1157-remoteresponseresolver-service-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Phase 3, Module 19. Creates `services/remote_response_resolver.py` with
---

# TASK-1157: RemoteResponseResolver Service

**Feature**: FEAT-167 — FormDesigner New Field Types
**Spec**: `sdd/specs/formdesigner-new-fields.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1155
**Assigned-to**: unassigned

---

## Context

Phase 3, Module 19. Creates `services/remote_response_resolver.py` with
`RemoteResponseResolver` and supporting Pydantic models (`RemoteResponseSpec`,
`RemoteResponseResult`). Mirrors `SubmissionForwarder` pattern. Retries on
every submission — NO memoisation across calls.

---

## Scope

- Create `services/remote_response_resolver.py`
- Define `RemoteResponseSpec` Pydantic model (embedded in `FormField.meta`)
- Define `RemoteResponseResult` Pydantic model
- Implement `RemoteResponseResolver.resolve(spec, content, *, auth_context=None)`
- Use `aiohttp.ClientSession` — NO `requests` / `httpx`
- Mirror `SubmissionForwarder` pattern from `services/forwarder.py:36`
- NO memoisation — every call hits the endpoint

**NOT in scope**: OptionsLoader (TASK-1156), validator REMOTE_RESPONSE branch (TASK-1159).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/remote_response_resolver.py` | CREATE | Resolver service + models |
| `packages/parrot-formdesigner/tests/unit/test_forwarder.py` | MODIFY | Add RemoteResponseResolver tests |

---

## Codebase Contract (Anti-Hallucination)

### Reference Pattern to Follow
```python
# services/forwarder.py:36 (verified — mirror this pattern):
class SubmissionForwarder:
    DEFAULT_TIMEOUT: int = 30

    def __init__(self, timeout: int = DEFAULT_TIMEOUT) -> None:
        self.timeout = timeout
        self.logger = logging.getLogger(__name__)

    async def forward(
        self,
        data: dict[str, Any],
        submit_action: SubmitAction,
    ) -> ForwardResult:
        # Uses aiohttp.ClientSession with ClientTimeout
        # Catches all exceptions, returns ForwardResult(success=False, error=...)
        # Never raises
```

### New Models Spec
```python
# services/remote_response_resolver.py — NEW
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict

class RemoteResponseSpec(BaseModel):
    """Embedded in FormField.meta for REMOTE_RESPONSE fields.

    Attributes:
        endpoint: URL of the external API to call.
        http_method: HTTP verb to use (default POST).
        content_field: Other field ID whose value is sent as request body.
        prompt: Optional prompt string sent alongside content.
        auth_ref: Reference to AuthContext credentials.
        timeout_seconds: Request timeout in seconds.
        response_schema: Optional JSON Schema to validate the API response.
    """
    model_config = ConfigDict(extra="forbid")

    endpoint: str
    http_method: Literal["GET", "POST"] = "POST"
    content_field: str | None = None
    prompt: str | None = None
    auth_ref: str | None = None
    timeout_seconds: int = 30
    response_schema: dict[str, Any] | None = None


class RemoteResponseResult(BaseModel):
    """Result of a RemoteResponseResolver.resolve() call.

    Attributes:
        success: True when the endpoint returned 2xx.
        value: Parsed response value from the endpoint.
        status_code: HTTP status code received.
        error: Human-readable error message when success=False.
    """
    success: bool
    value: Any | None = None
    status_code: int | None = None
    error: str | None = None
```

### Existing Imports
```python
# From TASK-1155:
from ..services.auth_context import AuthContext

# Verified from forwarder.py:
import aiohttp
from pydantic import BaseModel
```

### Does NOT Exist
- ~~`RemoteResponseResolver`~~ — THIS task creates it
- ~~`RemoteResponseSpec`~~ — THIS task creates it
- ~~`RemoteResponseResult`~~ — THIS task creates it
- ~~`services/remote_response_resolver.py`~~ — THIS task creates it
- ~~Memoisation/caching of REMOTE_RESPONSE~~ — explicitly forbidden by spec

---

## Implementation Notes

```python
class RemoteResponseResolver:
    """Resolve REMOTE_RESPONSE fields by calling an external API.

    Mirrors SubmissionForwarder's aiohttp + auth pattern. Every call
    hits the endpoint — no memoisation. Callers must ensure endpoint
    idempotency if needed.
    """
    DEFAULT_TIMEOUT: int = 30

    def __init__(self, timeout: int = DEFAULT_TIMEOUT) -> None:
        self.timeout = timeout
        self.logger = logging.getLogger(__name__)

    async def resolve(
        self,
        spec: RemoteResponseSpec,
        content: Any,
        *,
        auth_context: AuthContext | None = None,
    ) -> RemoteResponseResult:
        """Call the external API and return its response as the field value.

        Args:
            spec: The RemoteResponseSpec from FormField.meta.
            content: The content to send (from content_field value).
            auth_context: Optional runtime auth context.

        Returns:
            RemoteResponseResult — never raises, captures errors.
        """
        headers = {}
        if auth_context:
            headers.update(auth_context.resolve_for(spec.auth_ref))

        payload = {"content": content}
        if spec.prompt:
            payload["prompt"] = spec.prompt

        timeout = aiohttp.ClientTimeout(total=spec.timeout_seconds or self.timeout)
        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                method = getattr(session, spec.http_method.lower())
                async with method(spec.endpoint, json=payload, timeout=timeout) as resp:
                    status = resp.status
                    if 200 <= status < 400:
                        value = await resp.json()
                        return RemoteResponseResult(success=True, value=value, status_code=status)
                    else:
                        text = await resp.text()
                        return RemoteResponseResult(success=False, status_code=status, error=text[:200])
        except Exception as exc:
            self.logger.warning("RemoteResponseResolver failed: %s", exc)
            return RemoteResponseResult(success=False, error=str(exc))
```

---

## Acceptance Criteria

- [ ] `services/remote_response_resolver.py` exists
- [ ] `RemoteResponseSpec`, `RemoteResponseResult`, `RemoteResponseResolver` importable
- [ ] `resolve()` sends `{"content": ..., "prompt": ...}` to endpoint
- [ ] Two sequential `.resolve()` calls make two separate HTTP requests (no memoisation)
- [ ] Mocked 500 response yields `RemoteResponseResult(success=False, error=...)`
- [ ] `test_remote_response_resolver_posts_content` passes
- [ ] `test_remote_response_resolver_retries_on_resubmit` passes
- [ ] `test_remote_response_resolver_failure_returns_error` passes
- [ ] `ruff check packages/parrot-formdesigner/` passes

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/test_forwarder.py
# Add to existing test file:

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from parrot_formdesigner.services.remote_response_resolver import (
    RemoteResponseResolver, RemoteResponseSpec, RemoteResponseResult
)


@pytest.mark.asyncio
async def test_remote_response_resolver_posts_content():
    """Resolver sends {'content': ..., 'prompt': ...} and returns API value."""
    resolver = RemoteResponseResolver()
    spec = RemoteResponseSpec(
        endpoint="https://api.test/summarize",
        prompt="Summarize this",
    )
    # Mock aiohttp to return {"summary": "hello"}
    with patch("aiohttp.ClientSession") as mock_session_cls:
        # Configure mock for POST response
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={"summary": "hello"})
        mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=MagicMock(
            post=AsyncMock(return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_resp),
                __aexit__=AsyncMock(return_value=False),
            ))
        ))
        mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        result = await resolver.resolve(spec, "some content")
    assert result.success is True
    assert result.value == {"summary": "hello"}


@pytest.mark.asyncio
async def test_remote_response_resolver_retries_on_resubmit():
    """Two sequential resolve() calls hit the mock endpoint twice (no memoisation)."""
    resolver = RemoteResponseResolver()
    spec = RemoteResponseSpec(endpoint="https://api.test/action")
    call_count = 0

    # Configure mock to count calls
    # ... assert call_count == 2 after two awaits


@pytest.mark.asyncio
async def test_remote_response_resolver_failure_returns_error():
    """Mocked 500 yields RemoteResponseResult(success=False, error=...)."""
    resolver = RemoteResponseResolver()
    spec = RemoteResponseSpec(endpoint="https://api.test/fail")
    # Mock 500 response
    # result = await resolver.resolve(spec, "content")
    # assert result.success is False
    # assert result.error is not None
```

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
