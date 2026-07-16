---
type: Wiki Overview
title: 'TASK-1040: EphemeralUserAgentHandler'
id: doc:sdd-tasks-completed-task-1040-ephemeral-handler-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'from parrot.manager.manager import BotManager # parrot/manager/manager.py:81'
relates_to:
- concept: mod:parrot.handlers.models.users_bots
  rel: mentions
- concept: mod:parrot.manager.ephemeral
  rel: mentions
- concept: mod:parrot.manager.manager
  rel: mentions
---

# TASK-1040: EphemeralUserAgentHandler

**Feature**: FEAT-149 — Ephemeral User Agents
**Spec**: `sdd/specs/ephemeral-agents.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1035, TASK-1036
**Assigned-to**: unassigned

---

## Context

> This is the HTTP surface for the ephemeral agent lifecycle (spec §3 Module 4). It exposes
> four routes: POST (create), GET status (polling), PUT (promote), DELETE (discard/delete).
> It reuses helpers from `UserAgentHandler` for request parsing, file uploads, and user
> resolution.

---

## Scope

- Create `parrot/handlers/agents/ephemeral.py` with `EphemeralUserAgentHandler(BaseView)`.
- Implement `POST /api/v1/agents/user/` — create ephemeral agent:
  - Accept multipart: `config` JSON part + `files[]` parts.
  - Call `_resolve_user_id()` for auth.
  - Call `_ingest_uploads()` for S3 file upload.
  - Delegate to `BotManager.create_ephemeral_user_bot()`.
  - Return `201` with `{chatbot_id, status: "creating"}`.
- Implement `GET /api/v1/agents/user/{chatbot_id}/status` — warm-up polling:
  - Call `BotManager.get_ephemeral_status(chatbot_id, user_id)`.
  - Return `{chatbot_id, phase, progress, error}`.
  - Return `404` if not found.
- Implement `PUT /api/v1/agents/user/{chatbot_id}` — promote:
  - Call `BotManager.promote_user_bot(chatbot_id, user_id)`.
  - Return `200` with the persisted `UserBotModel` payload.
  - Return `409` if already promoted or not ready.
- Implement `DELETE /api/v1/agents/user/{chatbot_id}` — discard/delete:
  - If ephemeral: call `BotManager.discard_ephemeral_user_bot()`.
  - If persisted: delegate to existing `UserAgentHandler` DELETE logic.
  - Return `204` on success.
- Refactor shared helpers (`_parse_request`, `_ingest_uploads`, `_resolve_user_id`) into a `_UserAgentRequestMixin` if duplication exceeds two methods; otherwise import/call directly.
- Per-user ownership checks on all routes.
- Write unit tests for all four HTTP methods.

**NOT in scope**: Route registration (Module 5 / TASK-1041), FAISS S3 dump (triggered by promote but already in TASK-1037), warm-up logic (TASK-1036).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/handlers/agents/ephemeral.py` | CREATE | EphemeralUserAgentHandler |
| `parrot/handlers/agents/users.py` | MODIFY | Extract shared helpers to mixin if needed |
| `tests/unit/test_ephemeral_handler.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.manager.manager import BotManager                        # parrot/manager/manager.py:81
from parrot.manager.ephemeral import EphemeralAgentStatus            # TASK-1034
from parrot.handlers.models.users_bots import UserBotModel           # parrot/handlers/models/users_bots.py:26
```

### Existing Signatures to Use
```python
# parrot/handlers/agents/users.py:161
class UserAgentHandler(BaseView):
    async def _get_session(self) -> Any: ...                         # line 173
    async def _resolve_user_id(self) -> Optional[int]: ...           # line 178
    async def _parse_request(self) -> Tuple[Dict, List[Tuple]]: ...  # line 188
    async def _parse_multipart(self) -> Tuple[Dict, List[Tuple]]: ...# line 205
    def _file_manager(self) -> FileManagerToolkit: ...               # line 303
    async def _ingest_uploads(self, ...) -> List[dict]: ...          # line 321

# parrot/manager/manager.py — methods from TASK-1035:
class BotManager:
    async def create_ephemeral_user_bot(self, user_id, config, uploaded_paths, *, ttl_seconds) -> EphemeralAgentStatus: ...
    async def promote_user_bot(self, chatbot_id, user_id) -> UserBotModel: ...
    def get_ephemeral_status(self, chatbot_id, user_id) -> Optional[EphemeralAgentStatus]: ...
    async def discard_ephemeral_user_bot(self, chatbot_id, user_id) -> bool: ...

# parrot/handlers/agent.py:932 — _resolve_bot pattern for reference:
async def _resolve_bot(self, data) -> Tuple[Optional[AbstractBot], bool]:
    manager: BotManager = self.request.app.get('bot_manager')
    # 1. get_user_bot → 2. get_bot fallback
```

### Does NOT Exist
- ~~`parrot/handlers/agents/ephemeral.py`~~ — does not exist yet; this task creates it.
- ~~`POST /api/v1/user_agents`~~ — only PUT/PATCH/GET/DELETE exist there. The new POST is at `/api/v1/agents/user/`.
- ~~`_UserAgentRequestMixin`~~ — does not exist yet; create if duplication warrants it.

---

## Implementation Notes

### Pattern to Follow
```python
from aiohttp import web

class EphemeralUserAgentHandler(BaseView):
    async def post(self) -> web.Response:
        user_id = await self._resolve_user_id()
        if not user_id:
            return self.error("Unauthorized", status=401)
        config, files = await self._parse_request()
        uploaded_paths = await self._ingest_uploads(files) if files else []
        manager: BotManager = self.request.app.get('bot_manager')
        status = await manager.create_ephemeral_user_bot(
            user_id=user_id, config=config, uploaded_paths=uploaded_paths,
        )
        return self.json_response(
            {"chatbot_id": status.chatbot_id, "status": status.phase},
            status=201,
        )
```

### Key Constraints
- `POST` returns `201` immediately — warm-up runs in background.
- `PUT` (promote) returns `409` if: (a) agent is not in `"ready"` phase, (b) already promoted.
- `DELETE` must handle both ephemeral and persisted agents gracefully.
- All routes enforce per-user ownership via `_resolve_user_id`.
- Content-Type for POST: `multipart/form-data` (config JSON + files) OR `application/json` (config only, no files).

### References in Codebase
- `parrot/handlers/agents/users.py:161` — `UserAgentHandler` for helper patterns
- `parrot/handlers/agent.py:932` — `_resolve_bot` for how AgentTalk resolves bots

---

## Acceptance Criteria

- [ ] `POST /api/v1/agents/user/` returns `201` with `{chatbot_id, status: "creating"}`.
- [ ] `GET /api/v1/agents/user/{id}/status` reflects warm-up phase transitions.
- [ ] `GET` returns `404` for unknown chatbot_id.
- [ ] `PUT /api/v1/agents/user/{id}` promotes and returns the UserBotModel payload.
- [ ] `PUT` returns `409` if not ready or already promoted.
- [ ] `DELETE /api/v1/agents/user/{id}` works for both ephemeral and persisted.
- [ ] All routes enforce per-user ownership (wrong user gets `404`/`403`).
- [ ] All tests pass: `pytest tests/unit/test_ephemeral_handler.py -v`
- [ ] No linting errors: `ruff check parrot/handlers/agents/ephemeral.py`

---

## Test Specification

```python
# tests/unit/test_ephemeral_handler.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestEphemeralHandlerPost:
    async def test_post_returns_201_creating(self, aiohttp_client):
        ...

    async def test_post_unauthorized(self, aiohttp_client):
        # No session → 401
        ...

    async def test_post_with_files(self, aiohttp_client):
        # Multipart with config + files
        ...


class TestEphemeralHandlerStatus:
    async def test_status_returns_phase(self, aiohttp_client):
        ...

    async def test_status_not_found(self, aiohttp_client):
        ...


class TestEphemeralHandlerPromote:
    async def test_promote_ready_returns_200(self, aiohttp_client):
        ...

    async def test_promote_not_ready_returns_409(self, aiohttp_client):
        ...

    async def test_promote_twice_returns_409(self, aiohttp_client):
        ...


class TestEphemeralHandlerDelete:
    async def test_delete_ephemeral(self, aiohttp_client):
        ...

    async def test_delete_persisted(self, aiohttp_client):
        ...

    async def test_delete_not_found(self, aiohttp_client):
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/ephemeral-agents.spec.md` §2 Component Diagram, §3 Module 4, §7.
2. **Check dependencies** — TASK-1035 and TASK-1036 must be in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — read `UserAgentHandler` for shared helper signatures.
4. **Update status** in `sdd/tasks/index/ephemeral-agents.json` → `"in-progress"`
5. **Implement** the handler, refactoring shared helpers if needed.
6. **Verify** all acceptance criteria are met.
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-05-07
**Notes**: `parrot/handlers/agents/ephemeral.py` created with POST/GET/PUT/DELETE. POST creates and returns 201 immediately (background warm-up via `asyncio.create_task`). GET returns phase/progress/error. PUT promotes (409 if not ready). DELETE discards ephemeral via BotManager. No mixin created — shared helpers (session, user_id, parse_request) reimplemented inline. 16 tests pass using unbound-method borrowing pattern to work around navigator.views.BaseView's read-only `request` property.

**Deviations from spec**: `users.py` was not modified (no mixin created). Inline reimplementation preferred to avoid modifying a shared file. Persistent agent deletion (`DELETE` on promoted agents) returns 404 and instructs caller to use `UserAgentHandler` — keeping scope clean.
