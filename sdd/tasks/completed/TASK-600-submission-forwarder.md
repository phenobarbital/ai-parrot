# TASK-600: SubmissionForwarder

**Feature**: form-designer-edition
**Spec**: `sdd/specs/form-designer-edition.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-597
**Assigned-to**: unassigned

---

## Context

Creates the HTTP forwarding service that sends validated form submissions to the URL configured in `SubmitAction`. Uses `AuthConfig.resolve()` (TASK-597) to build authentication headers. The forwarder is used by the submission endpoint (TASK-602).

Implements Spec Module 4.

---

## Scope

- Create `services/forwarder.py` with:
  - `ForwardResult` Pydantic model (success, status_code, error)
  - `SubmissionForwarder` class with:
    - `async def forward(self, data: dict[str, Any], submit_action: SubmitAction) -> ForwardResult`
- Forward logic:
  1. Resolve auth headers via `submit_action.auth.resolve()` (if auth is set)
  2. Send HTTP request via `aiohttp.ClientSession` to `submit_action.action_ref` with `submit_action.method`
  3. Use 30-second timeout
  4. Return `ForwardResult` with status — never raise on network errors
- Export from `services/__init__.py`

**NOT in scope**: Storing submissions (TASK-599), API endpoint (TASK-602)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot/formdesigner/services/forwarder.py` | CREATE | SubmissionForwarder + ForwardResult |
| `packages/parrot-formdesigner/src/parrot/formdesigner/services/__init__.py` | MODIFY | Export new classes |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from __future__ import annotations
import logging
from typing import Any
from pydantic import BaseModel
import aiohttp  # already a dependency of the project

# From TASK-597 (must be completed first):
from ..core.auth import AuthConfig  # core/auth.py created by TASK-597
from ..core.schema import SubmitAction  # core/schema.py:89
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot/formdesigner/core/schema.py:89
class SubmitAction(BaseModel):
    action_type: Literal["tool_call", "endpoint", "event", "callback"]  # line 99
    action_ref: str  # line 100
    method: str = "POST"  # line 101
    auth: AuthConfig | None = None  # added by TASK-598, but forwarder only needs resolve()

# From TASK-597 (AuthConfig models):
# NoAuth.resolve() -> dict[str, str]  — returns {}
# BearerAuth.resolve() -> dict[str, str]  — returns {"Authorization": "Bearer <token>"}
# ApiKeyAuth.resolve() -> dict[str, str]  — returns {header_name: <key>}
```

### Does NOT Exist
- ~~`SubmissionForwarder`~~ — does not exist; this task creates it
- ~~`ForwardResult`~~ — does not exist; this task creates it
- ~~`parrot.formdesigner.services.forwarder`~~ — module does not exist; this task creates it

---

## Implementation Notes

### Pattern to Follow
```python
class SubmissionForwarder:
    """Forward form submission data to configured endpoints with auth."""

    DEFAULT_TIMEOUT = 30  # seconds

    def __init__(self, timeout: int = DEFAULT_TIMEOUT) -> None:
        self.timeout = timeout
        self.logger = logging.getLogger(__name__)

    async def forward(
        self,
        data: dict[str, Any],
        submit_action: SubmitAction,
    ) -> ForwardResult:
        if submit_action.action_type != "endpoint":
            return ForwardResult(success=False, error="action_type is not 'endpoint'")

        headers = {"Content-Type": "application/json"}
        if submit_action.auth is not None:
            try:
                auth_headers = submit_action.auth.resolve()
                headers.update(auth_headers)
            except ValueError as exc:
                return ForwardResult(success=False, error=f"Auth resolution failed: {exc}")

        try:
            timeout = aiohttp.ClientTimeout(total=self.timeout)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.request(
                    method=submit_action.method,
                    url=submit_action.action_ref,
                    json=data,
                    headers=headers,
                ) as resp:
                    return ForwardResult(
                        success=resp.status < 400,
                        status_code=resp.status,
                    )
        except Exception as exc:
            self.logger.warning("Forward to %s failed: %s", submit_action.action_ref, exc)
            return ForwardResult(success=False, error=str(exc))
```

### Key Constraints
- NEVER raise exceptions from `forward()` — always return `ForwardResult`
- Use `aiohttp.ClientSession` (not `requests` or `httpx`)
- 30-second default timeout
- Only forward when `action_type == "endpoint"`
- Log warnings on failure, not errors (caller decides severity)

### References in Codebase
- `packages/parrot-formdesigner/src/parrot/formdesigner/core/schema.py` — SubmitAction model
- TASK-597 output: `core/auth.py` — AuthConfig.resolve()

---

## Acceptance Criteria

- [ ] `ForwardResult` model with `success`, `status_code`, `error` fields
- [ ] `SubmissionForwarder.forward()` sends HTTP request with correct method, URL, JSON body, and auth headers
- [ ] Returns `ForwardResult(success=False)` on network error — does not raise
- [ ] Returns `ForwardResult(success=False)` when `action_type != "endpoint"`
- [ ] Returns `ForwardResult(success=False)` when auth resolution fails
- [ ] Uses 30s default timeout
- [ ] Classes exported from `services/__init__.py`

---

## Test Specification

```python
# tests/test_forwarder.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from parrot.formdesigner.services.forwarder import SubmissionForwarder, ForwardResult
from parrot.formdesigner.core.schema import SubmitAction


class TestForwardResult:
    def test_success_result(self):
        r = ForwardResult(success=True, status_code=200)
        assert r.success is True
        assert r.error is None

    def test_failure_result(self):
        r = ForwardResult(success=False, error="Connection refused")
        assert r.success is False


class TestSubmissionForwarder:
    @pytest.fixture
    def forwarder(self):
        return SubmissionForwarder(timeout=5)

    @pytest.fixture
    def endpoint_action(self):
        return SubmitAction(
            action_type="endpoint",
            action_ref="http://example.com/api/data",
            method="POST",
        )

    async def test_non_endpoint_action(self, forwarder):
        sa = SubmitAction(action_type="tool_call", action_ref="my_tool")
        result = await forwarder.forward({"key": "val"}, sa)
        assert result.success is False
        assert "endpoint" in result.error

    async def test_forward_does_not_raise_on_error(self, forwarder, endpoint_action):
        """Forward to unreachable host returns ForwardResult, not exception."""
        endpoint_action.action_ref = "http://localhost:19999/nonexistent"
        result = await forwarder.forward({"key": "val"}, endpoint_action)
        assert result.success is False
        assert result.error is not None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/form-designer-edition.spec.md`
2. **Check dependencies** — verify TASK-597 is in `tasks/completed/`
3. **Verify the Codebase Contract** — confirm `core/auth.py` exists with `resolve()` method
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** following the scope and notes
6. **Run tests**: `pytest packages/parrot-formdesigner/tests/test_forwarder.py -v`
7. **Move this file** to `tasks/completed/`
8. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
