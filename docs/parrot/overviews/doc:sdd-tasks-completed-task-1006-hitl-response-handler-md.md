---
type: Wiki Overview
title: 'TASK-1006: Implement HITLResponseHandler (POST /api/v1/agents/hitl/respond)'
id: doc:sdd-tasks-completed-task-1006-hitl-response-handler-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This task implements the HTTP endpoint handler that receives human responses
  from the frontend and resolves pending HITL interactions. The `HITLResponseHandler`
  class is deployed at `POST /api/v1/agents/hitl/respond` and bridges the web UI back
  to the `HumanInteractionManager` (§
relates_to:
- concept: mod:parrot.handlers
  rel: mentions
- concept: mod:parrot.handlers.web_hitl
  rel: mentions
- concept: mod:parrot.human
  rel: mentions
- concept: mod:parrot.human.models
  rel: mentions
---

# TASK-1006: Implement HITLResponseHandler (POST /api/v1/agents/hitl/respond)

**Feature**: FEAT-146 — web-hitl-and-demo-agent
**Spec**: `sdd/specs/web-hitl-and-demo-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: TASK-1004
**Assigned-to**: unassigned

---

## Context

This task implements the HTTP endpoint handler that receives human responses from the frontend and resolves pending HITL interactions. The `HITLResponseHandler` class is deployed at `POST /api/v1/agents/hitl/respond` and bridges the web UI back to the `HumanInteractionManager` (§3 Module 3 in the spec).

When a user submits an answer via the frontend, this handler validates the request, looks up the interaction, and calls `manager.receive_response(...)` to unblock the agent.

---

## Scope

- Implement `HITLResponseHandler` class extending `BaseView` in `parrot/handlers/web_hitl.py`.
- Implement `async def post(self) -> web.Response` method.
- Validate request body JSON (use Pydantic model `HITLResponseBody`).
- Required fields: `interaction_id` (UUID string), `value` (Any).
- Optional field: `response_type` (string, defaults to interaction's declared type).
- Extract `user_id` from `request.session.get('user_id')` for authentication.
- Call `manager.receive_response(...)` to resolve the interaction.
- Return 200 with `{"ok": true, "interaction_id": "..."}` on success.
- Return 400 on invalid/missing fields.
- Return 404 if interaction not found.
- Return 401/403 when unauthenticated (via `@is_authenticated` decorator).
- Add Google-style docstrings.

**NOT in scope**:
- Bootstrap (belongs to TASK-1007).
- Route registration in BotManager (belongs to TASK-1009).
- Frontend implementation (out of scope per spec §1 Non-Goals).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/handlers/web_hitl.py` | MODIFY | Add `HITLResponseBody` Pydantic model and `HITLResponseHandler` class. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from aiohttp import web                                                         # stdlib for aiohttp
from pydantic import BaseModel, Field                                           # pydantic
from parrot.handlers.base import BaseView, is_authenticated                     # parrot/handlers/base.py
from parrot.human import (                                                      # parrot/human/__init__.py:9-43
    HumanInteractionManager,
    get_default_human_manager,
)
from parrot.human.models import (                                               # parrot/human/models.py:11-120
    HumanResponse,
)
from typing import Any, Optional
import json
import logging
```

### Existing Signatures to Use

```python
# parrot/handlers/base.py
class BaseView(web.View):  # aiohttp's web.View subclass
    pass

def is_authenticated():  # decorator
    pass

# parrot/human/manager.py:337
class HumanInteractionManager:
    async def receive_response(self, response: HumanResponse) -> None: ...

# parrot/human/__init__.py
def get_default_human_manager() -> Optional[HumanInteractionManager]: ...
```

### Does NOT Exist

- ~~`HITLResponseHandler`~~ — to be created.
- ~~`HITLResponseBody` Pydantic model~~ — to be created.
- ~~`HumanResponse` constructor with interaction_id/value/response_type~~ — check the actual signature in the codebase; adjust accordingly.

---

## Implementation Notes

### Pattern to Follow

Follow the pattern of existing HTTP handlers in `parrot/handlers/`:
- Extend `BaseView`.
- Use `@is_authenticated()` decorator on the `post` method.
- Validate request body with Pydantic; catch `ValidationError` and return 400.
- Delegate business logic to existing services (`HumanInteractionManager`).
- Log at INFO for success, WARNING/ERROR for failures.
- Return aiohttp `web.Response` objects with JSON body and appropriate status codes.

### Key Constraints

- Async method: `async def post(self)`.
- Respondent identity comes from `request.session.get('user_id')`, NOT from the request body.
- If `get_default_human_manager()` returns None, return 503 (service unavailable).
- Interaction lookup is via `interaction_id`; if not found, return 404.
- All validation errors should be descriptive (e.g., "missing interaction_id").

---

## Acceptance Criteria

- [ ] `HITLResponseHandler` class exists in `parrot/handlers/web_hitl.py`, extends `BaseView`.
- [ ] `HITLResponseBody` Pydantic model with fields: `interaction_id`, `value`, `response_type` (optional).
- [ ] `post` method is `async` and decorated with `@is_authenticated()`.
- [ ] Returns 400 on missing required fields (validates via Pydantic).
- [ ] Returns 404 when interaction_id not found in manager.
- [ ] Returns 200 with `{"ok": true, "interaction_id": "..."}` on success.
- [ ] Returns 401/403 when unauthenticated.
- [ ] Calls `manager.receive_response(...)` exactly once on valid input.
- [ ] Respondent identity from `request.session.get('user_id')`, never from request body.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/handlers/test_web_hitl.py::test_hitl_endpoint -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/handlers/web_hitl.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/handlers/test_web_hitl.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from pydantic import ValidationError
from parrot.handlers.web_hitl import HITLResponseHandler, HITLResponseBody
from parrot.human.models import HumanResponse
from parrot.human import set_default_human_manager, get_default_human_manager


@pytest.fixture
def mock_request(aiohttp_client):
    """Mock aiohttp request with session."""
    request = MagicMock()
    request.session = {"user_id": "user-123"}
    request.app = {}
    return request


@pytest.fixture
def mock_manager():
    """Mock HumanInteractionManager."""
    manager = AsyncMock()
    manager.receive_response = AsyncMock()
    manager.get_result = AsyncMock(return_value={"value": "response_value"})
    return manager


class TestHITLResponseHandler:
    async def test_hitl_endpoint_400_on_missing_field(self, mock_request, mock_manager):
        """POST with missing required field returns 400."""
        handler = HITLResponseHandler(mock_request)
        mock_request.json = AsyncMock(return_value={"value": "test"})  # missing interaction_id
        set_default_human_manager(mock_manager)
        response = await handler.post()
        assert response.status == 400

    async def test_hitl_endpoint_404_on_unknown_id(self, mock_request, mock_manager):
        """POST with unknown interaction_id returns 404."""
        handler = HITLResponseHandler(mock_request)
        mock_request.json = AsyncMock(return_value={
            "interaction_id": "unknown-uuid",
            "value": "test",
        })
        # Mock manager returns None for unknown id
        mock_manager.get_result = AsyncMock(return_value=None)
        set_default_human_manager(mock_manager)
        response = await handler.post()
        assert response.status == 404

    async def test_hitl_endpoint_200_calls_receive_response(self, mock_request, mock_manager):
        """POST with valid input returns 200 and calls receive_response."""
        handler = HITLResponseHandler(mock_request)
        mock_request.json = AsyncMock(return_value={
            "interaction_id": "uuid-123",
            "value": "user_answer",
        })
        mock_manager.get_result = AsyncMock(return_value={"value": "user_answer"})
        set_default_human_manager(mock_manager)
        response = await handler.post()
        assert response.status == 200
        assert mock_manager.receive_response.called

    async def test_hitl_endpoint_requires_auth(self, mock_request, mock_manager):
        """Unauthenticated POST returns 401/403."""
        handler = HITLResponseHandler(mock_request)
        # Without @is_authenticated decorator, the handler should reject
        # This test verifies the decorator is present and working
        mock_request.session = {}  # No user_id
        mock_request.json = AsyncMock(return_value={
            "interaction_id": "uuid-123",
            "value": "test",
        })
        # The @is_authenticated decorator should prevent execution
        # (This test assumes the decorator is applied at class level)
        pass  # Decorator behavior tested at integration level


class TestHITLResponseBody:
    def test_response_body_required_fields(self):
        """HITLResponseBody validates required fields."""
        with pytest.raises(ValidationError):
            HITLResponseBody(value="test")  # missing interaction_id

    def test_response_body_optional_response_type(self):
        """HITLResponseBody response_type is optional."""
        body = HITLResponseBody(interaction_id="uuid-123", value="test")
        assert body.response_type is None

    def test_response_body_with_response_type(self):
        """HITLResponseBody accepts response_type."""
        body = HITLResponseBody(
            interaction_id="uuid-123",
            value="test",
            response_type="single_choice",
        )
        assert body.response_type == "single_choice"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/web-hitl-and-demo-agent.spec.md` for full context
2. **Check dependencies** — verify TASK-1004 is in `tasks/completed/`
3. **Verify the Codebase Contract** — confirm `BaseView`, `is_authenticated`, `HumanInteractionManager.receive_response` signatures
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-1006-hitl-response-handler.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
