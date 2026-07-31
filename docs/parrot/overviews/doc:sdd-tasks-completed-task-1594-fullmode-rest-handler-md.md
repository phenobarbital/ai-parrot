---
type: Wiki Overview
title: 'TASK-1594: FULL Mode REST Handler (Start / Stop)'
id: doc:sdd-tasks-completed-task-1594-fullmode-rest-handler-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The FULL mode needs its own handler endpoints separate from the existing
  LITE
relates_to:
- concept: mod:parrot.integrations.liveavatar.client
  rel: mentions
- concept: mod:parrot.integrations.liveavatar.models
  rel: mentions
- concept: mod:parrot.integrations.liveavatar.optin
  rel: mentions
- concept: mod:parrot.integrations.liveavatar.tenant_config
  rel: mentions
---

# TASK-1594: FULL Mode REST Handler (Start / Stop)

**Feature**: FEAT-248 — LiveAvatar FULL Mode speak_text Integration (Backend)
**Spec**: `sdd/specs/liveavatar-fullmode-speaktext.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1592, TASK-1593
**Assigned-to**: unassigned

---

## Context

The FULL mode needs its own handler endpoints separate from the existing LITE
handler. This task creates `avatar_fullmode.py` with start/stop endpoints that
use the new `create_full_session_token()` and `resolve_fullmode_config()`.

The handler follows the same lazy-import + opt-in + session-store pattern as
the existing `avatar.py` handler.

Implements spec §3 Module 4.

---

## Scope

- Create `avatar_fullmode.py` with two handlers:
  - `POST /api/v1/avatar/fullmode/start` → `_start_fullmode_session(request)`
  - `POST /api/v1/avatar/fullmode/stop` → `_stop_fullmode_session(request)`
- Start handler flow: opt-in gate → resolve config → create client → create_full_session_token →
  start_session → store `{client, handle}` in app session store → return viewer-only creds
  (`livekit_url`, `livekit_client_token`, `session_id`).
- Stop handler: idempotent stop (same pattern as existing `_stop_avatar_session`).
- Security: `session_token`, `agent_token`, `ws_url` NEVER returned to client.
- Register routes in server route setup.
- Write unit tests with mocked client.

**NOT in scope**: Avatar/voice listing (TASK-1595), room observer (TASK-1596),
package wiring (TASK-1597).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/avatar_fullmode.py` | CREATE | FULL mode start/stop handlers |
| `packages/ai-parrot-server/src/parrot/handlers/__init__.py` | MODIFY | Register new handler if needed |
| `packages/ai-parrot-server/tests/handlers/test_avatar_fullmode.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# From TASK-1591 / TASK-1592:
from parrot.integrations.liveavatar.client import LiveAvatarClient
from parrot.integrations.liveavatar.models import FullModeConfig, FullModeSessionHandle
# From TASK-1593:
from parrot.integrations.liveavatar.tenant_config import resolve_fullmode_config
# Existing opt-in gate:
from parrot.integrations.liveavatar.optin import is_avatar_enabled  # optin.py:58
```

### Existing Signatures to Use (Pattern Reference)
```python
# packages/ai-parrot-server/src/parrot/handlers/avatar.py
AVATAR_SESSIONS_KEY = "avatar_sessions"  # line 52
AVATAR_VOICE_SESSIONS_KEY = "avatar_voice_sessions"  # line 57

async def _start_avatar_session(request):  # line 77
    # Pattern: lazy imports → opt-in gate → build config → aopen() client
    # → create_session_token + start_session → store in app[SESSIONS_KEY]
    # → return viewer creds only

async def _stop_avatar_session(request):  # line 223
    # Pattern: lookup session in app store → client.stop_session(handle) → remove from store
    # Idempotent: returns 200 even if already stopped
```

### Does NOT Exist
- ~~`avatar_fullmode.py`~~ — does not exist yet; this task creates it
- ~~`FULLMODE_SESSIONS_KEY`~~ — does not exist yet; define it in this task
- ~~`_start_fullmode_session()`~~ — does not exist yet
- ~~`_stop_fullmode_session()`~~ — does not exist yet

---

## Implementation Notes

### Pattern to Follow
```python
# Follow avatar.py's pattern exactly. Key differences:
# 1. Use resolve_fullmode_config() instead of manual env-var reads
# 2. Use create_full_session_token() instead of create_session_token()
# 3. Return livekit_url + livekit_client_token (not ws_url)
# 4. Use a separate session store key: FULLMODE_SESSIONS_KEY

import logging
from aiohttp import web

logger = logging.getLogger(__name__)

FULLMODE_SESSIONS_KEY = "avatar_fullmode_sessions"


async def _start_fullmode_session(request: web.Request) -> web.Response:
    # Lazy imports (same pattern as avatar.py)
    from parrot.integrations.liveavatar.client import LiveAvatarClient
    from parrot.integrations.liveavatar.optin import is_avatar_enabled
    from parrot.integrations.liveavatar.tenant_config import resolve_fullmode_config

    data = await request.json()
    tenant_id = data.get("tenant_id")
    agent_name = data.get("agent_name", "default")

    if not is_avatar_enabled(tenant_id=tenant_id, agent_name=agent_name):
        return web.json_response({"error": "Avatar not enabled"}, status=403)

    cfg = resolve_fullmode_config(tenant_id=tenant_id)
    async with LiveAvatarClient(cfg) as client:
        handle = await client.create_full_session_token(cfg)
        await client.start_session(handle)
        # Store for later stop
        sessions = request.app.setdefault(FULLMODE_SESSIONS_KEY, {})
        sessions[handle.session_id] = {"client": client, "handle": handle}
        # Return viewer-only creds
        return web.json_response({
            "session_id": handle.session_id,
            "livekit_url": handle.livekit_url,
            "livekit_client_token": handle.livekit_client_token,
        })
```

### Key Constraints
- **Security**: NEVER return `session_token`, `agent_token`, or `ws_url` to the client
- **Idempotent stop**: `_stop_fullmode_session` must not raise if the session is already stopped
- **Lazy imports**: All LiveAvatar imports must be inside the handler function body
  (same pattern as `avatar.py`) to avoid import errors when the package is not installed
- The handler must work with the existing aiohttp-based server infrastructure

---

## Acceptance Criteria

- [ ] `POST /api/v1/avatar/fullmode/start` creates a FULL mode session and returns viewer creds
- [ ] Response contains `session_id`, `livekit_url`, `livekit_client_token` only
- [ ] Response does NOT contain `session_token`, `agent_token`, `ws_url`
- [ ] `POST /api/v1/avatar/fullmode/stop` stops the session idempotently
- [ ] Opt-in gate rejects disabled tenants with 403
- [ ] Config resolver errors return 500 with a safe error message
- [ ] Tests pass: `pytest packages/ai-parrot-server/tests/handlers/test_avatar_fullmode.py -v`

---

## Test Specification

```python
import pytest
from aiohttp import web
from unittest.mock import AsyncMock, MagicMock, patch


class TestStartFullmodeSession:
    async def test_returns_viewer_creds(self, aiohttp_client):
        """Response contains session_id, livekit_url, livekit_client_token."""
        ...

    async def test_no_sensitive_fields(self, aiohttp_client):
        """Response does NOT contain session_token, agent_token, ws_url."""
        ...

    async def test_rejects_disabled_tenant(self, aiohttp_client):
        """Returns 403 when is_avatar_enabled returns False."""
        ...


class TestStopFullmodeSession:
    async def test_stops_existing_session(self, aiohttp_client):
        """Stops the session and removes from store."""
        ...

    async def test_idempotent_stop(self, aiohttp_client):
        """Returns 200 even if session already stopped."""
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** §3 Module 4
2. **Check dependencies** — TASK-1592 and TASK-1593 must be completed
3. **Read `avatar.py`** at `packages/ai-parrot-server/src/parrot/handlers/avatar.py` — follow the same pattern exactly
4. **Create** `avatar_fullmode.py` as a new handler file
5. **Register routes** in the server's route configuration
6. **Write tests** and verify all acceptance criteria

---

## Completion Note

*(Agent fills this in when done)*
