---
type: Wiki Overview
title: 'TASK-988: AgentTalk AuthorizationRequired Envelope Translator'
id: doc:sdd-tasks-completed-task-988-agenttalk-auth-required-envelope-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: When a tool raises `AuthorizationRequired` during agent execution, the web
relates_to:
- concept: mod:parrot.auth.exceptions
  rel: mentions
- concept: mod:parrot.integrations
  rel: mentions
---

# TASK-988: AgentTalk AuthorizationRequired Envelope Translator

**Feature**: FEAT-144 — Cross-Repository JiraToolkit OAuth2 3LO (Web AgentChat)
**Spec**: `sdd/specs/cross-repository-jiratoolkit-oauth2-3lo.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-983
**Assigned-to**: unassigned

---

## Context

When a tool raises `AuthorizationRequired` during agent execution, the web
frontend needs a structured response to render a "Connect" pill. This task
wraps the agent invocation in `AgentTalk.post` with `try/except
AuthorizationRequired` and translates the exception into an
`AuthRequiredEnvelope` JSON response (HTTP 200).

Implements spec Module 8.

---

## Scope

- Modify `AgentTalk` in `parrot/handlers/agent.py` to catch
  `AuthorizationRequired` exceptions during agent invocation.
- Build an `AuthRequiredEnvelope` from the exception's fields (`provider`,
  `auth_url`, `scopes`, `tool_name`, message) and return it as the JSON
  response body with HTTP 200.
- Other exception classes keep their existing handling.
- Write unit tests.

**NOT in scope**: Modifying `AuthorizationRequired` exception class (unchanged),
modifying `JiraToolkit._pre_execute` (unchanged), frontend pill (TASK-992).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/handlers/agent.py` | MODIFY | Add try/except around agent invocation |
| `tests/unit/integrations/oauth2/test_agenttalk_envelope.py` | CREATE | Envelope translation tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Already imported or to add in agent.py:
from parrot.auth.exceptions import AuthorizationRequired  # exceptions.py:12
from parrot.integrations.oauth2.models import AuthRequiredEnvelope  # TASK-983

# Existing in agent.py:
from aiohttp import web  # existing
from navigator.views import BaseView  # line 31
```

### Existing Signatures to Use
```python
# parrot/auth/exceptions.py:12
class AuthorizationRequired(Exception):
    def __init__(
        self,
        tool_name: str,           # line 36
        message: str,
        auth_url: Optional[str] = None,  # line 38
        provider: str = "unknown",       # line 39
        scopes: Optional[List[str]] = None,  # line 40
    ): ...
    # Public attrs: tool_name, auth_url, provider, scopes (List[str])

# parrot/handlers/agent.py:50
class AgentTalk(BaseView):
    # Agent invocation occurs around lines 979-1023
    # The exact call chain that invokes agent.ask / agent.invoke
    # needs to be wrapped with try/except AuthorizationRequired

# parrot/integrations/oauth2/models.py (from TASK-983):
class AuthRequiredEnvelope(BaseModel):
    type: Literal["auth_required"] = "auth_required"
    provider: str
    tool_name: Optional[str] = None
    auth_url: Optional[str] = None
    scopes: List[str] = Field(default_factory=list)
    message: str
```

### Does NOT Exist
- ~~`AuthorizationRequired.to_envelope()`~~ — no such method; build the envelope manually.
- ~~`AgentTalk._handle_auth_required()`~~ — no such method exists yet. Add the try/except
  inline around the invocation block, or extract to a private method.
- ~~Existing `AuthorizationRequired` catch in `AgentTalk`~~ — there is NO existing
  catch. This task adds the first one.

---

## Implementation Notes

### Modification Point
Read `agent.py` carefully around lines 979-1023 to identify the exact invocation
call. The try/except wraps the block that calls `agent.ask(...)` or
`agent.invoke(...)`. Example:

```python
try:
    # ... existing agent invocation code ...
    result = await agent.ask(prompt, **kwargs)
    # ... existing post-processing ...
except AuthorizationRequired as exc:
    envelope = AuthRequiredEnvelope(
        provider=exc.provider,
        tool_name=exc.tool_name,
        auth_url=exc.auth_url,
        scopes=exc.scopes or [],
        message=str(exc),
    )
    return web.json_response(
        envelope.model_dump(),
        status=200,
    )
```

### Key Constraints
- HTTP 200, not 401 or 403. The chat call "succeeded" — the agent's reply IS
  the structured envelope. The frontend detects `type === "auth_required"` to
  render the pill.
- `exc.scopes` may be `None` (default in exception is `None`); the envelope
  field defaults to `[]`.
- `str(exc)` provides the human-readable message.
- Do NOT catch any other exception types in this handler — only
  `AuthorizationRequired`. Other exceptions keep their existing handling.

---

## Acceptance Criteria

- [ ] When `agent.ask(...)` raises `AuthorizationRequired(provider="jira", auth_url="https://...", tool_name="jira_create_issue")`,
      AgentTalk returns HTTP 200 with body `{"type": "auth_required", "provider": "jira", "auth_url": "https://...", "tool_name": "jira_create_issue", ...}`.
- [ ] Non-AuthorizationRequired exceptions are NOT caught by this handler.
- [ ] `scopes` defaults to `[]` when exception has `scopes=None`.
- [ ] Response content type is `application/json`.
- [ ] All tests pass: `pytest tests/unit/integrations/oauth2/test_agenttalk_envelope.py -v`
- [ ] No lint errors.

---

## Test Specification

```python
# tests/unit/integrations/oauth2/test_agenttalk_envelope.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from parrot.auth.exceptions import AuthorizationRequired


class TestAgentTalkAuthRequiredEnvelope:
    @pytest.mark.asyncio
    async def test_translates_exception_to_envelope(self):
        """AuthorizationRequired → 200 with AuthRequiredEnvelope body."""
        ...

    @pytest.mark.asyncio
    async def test_scopes_none_becomes_empty_list(self):
        """When exception.scopes is None, envelope.scopes is []."""
        ...

    @pytest.mark.asyncio
    async def test_other_exceptions_not_caught(self):
        """Non-AuthorizationRequired exceptions propagate normally."""
        ...

    @pytest.mark.asyncio
    async def test_envelope_schema(self):
        """Response body matches AuthRequiredEnvelope schema exactly."""
        exc = AuthorizationRequired(
            tool_name="jira_create_issue",
            message="Jira not connected",
            auth_url="https://auth.atlassian.com/authorize?...",
            provider="jira",
            scopes=["read:jira-work", "write:jira-work"],
        )
        from parrot.integrations.oauth2.models import AuthRequiredEnvelope
        envelope = AuthRequiredEnvelope(
            provider=exc.provider,
            tool_name=exc.tool_name,
            auth_url=exc.auth_url,
            scopes=exc.scopes or [],
            message=str(exc),
        )
        data = envelope.model_dump()
        assert data["type"] == "auth_required"
        assert data["provider"] == "jira"
        assert data["tool_name"] == "jira_create_issue"
```

---

## Agent Instructions

When you pick up this task:

1. **Read** `parrot/handlers/agent.py` lines 950-1050 carefully to understand the
   invocation flow and identify exactly where to add the try/except.
2. **Check dependencies** — verify TASK-983 is complete (need `AuthRequiredEnvelope`).
3. **Verify** that `AuthorizationRequired` is not already caught anywhere in AgentTalk.
4. **Implement** the minimal change — just the try/except + envelope construction.
5. **Verify** all acceptance criteria.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
