---
type: Wiki Overview
title: 'TASK-002: LiveAvatar HTTP client & session lifecycle (M1)'
id: doc:sdd-tasks-completed-task-002-liveavatar-client-lifecycle-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Implements **Module 1** (spec §3): the LiveAvatar HTTP client and session'
relates_to:
- concept: mod:parrot.integrations.liveavatar
  rel: mentions
- concept: mod:parrot.integrations.liveavatar.models
  rel: mentions
---

# TASK-002: LiveAvatar HTTP client & session lifecycle (M1)

**Feature**: FEAT-242 — LiveAvatar Phase A (avatar as the "mouth" of AgentChat)
**Spec**: `sdd/specs/liveavatar-phase-a-mouth.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-001
**Assigned-to**: unassigned

---

## Context

Implements **Module 1** (spec §3): the LiveAvatar HTTP client and session
lifecycle. Ports the starter's `liveavatar_client.py` (httpx/websockets) to
`aiohttp`. Creates the session token (optionally with `livekit_config` so the
avatar joins our LiveKit Cloud room), starts/stops sessions, runs the keep-alive
loop, and guarantees teardown. Capability: `liveavatar-session-lifecycle`.

---

## Scope

- Implement `LiveAvatarClient` in `client.py` with the four async methods from
  spec §2 (New Public Interfaces): `create_session_token`, `start_session`,
  `stop_session`, `keep_alive`.
- `create_session_token` accepts an optional `livekit_config: dict` and returns
  an `AvatarSessionHandle`.
- Auth headers: `X-API-KEY` on most calls; `Bearer <session_token>` on
  `start_session`.
- Keep-alive: a background task scheduled at < 5 min inactivity (spec §7 gotcha).
- Guaranteed teardown: `stop_session` runs on every exit path (use an async
  context-manager and/or `finally`).
- `max_session_duration` is passed to `create_session_token` as a safety net.
- Use a single `aiohttp.ClientSession`; `self.logger` for logging.

**NOT in scope**: PCM WebSocket bridge (TASK-003), room-token minting (TASK-004 —
this task only *passes through* a `livekit_config` dict it is given), the
orchestrator (TASK-006).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/client.py` | CREATE | `LiveAvatarClient` |
| `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/__init__.py` | MODIFY | Re-export `LiveAvatarClient` |
| `packages/ai-parrot-integrations/tests/integrations/liveavatar/test_client.py` | CREATE | Unit tests (mocked aiohttp) |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-06-18.

### Verified Imports
```python
import aiohttp                                   # project HTTP standard (NEVER requests/httpx)
import asyncio
import logging
from typing import Optional
from parrot.integrations.liveavatar.models import (
    LiveAvatarConfig, AvatarSessionHandle,
)   # from TASK-001
```

### Existing Signatures to Use
```python
# Public interface to implement (spec §2 — confirm exact request/response shapes
# against the LiveAvatar API reference at impl time):
class LiveAvatarClient:
    async def create_session_token(self, cfg: LiveAvatarConfig,
                                   livekit_config: Optional[dict] = None) -> AvatarSessionHandle: ...
    async def start_session(self, handle: AvatarSessionHandle) -> dict: ...
    async def stop_session(self, handle: AvatarSessionHandle) -> None: ...
    async def keep_alive(self, handle: AvatarSessionHandle) -> None: ...

# Existing aiohttp.ClientSession usage pattern to mirror (verified):
#   packages/ai-parrot-integrations/src/parrot/integrations/msteams/graph.py
#   packages/ai-parrot-integrations/src/parrot/integrations/telegram/auth.py
```

### Does NOT Exist (do NOT reference)
- ~~`httpx` / `requests` / `websockets`~~ — do NOT use; port the starter to `aiohttp`.
- ~~a LiveAvatar "speak text" command~~ — LITE Mode has no such command; speaking is
  done via the PCM WebSocket (TASK-003), not this HTTP client.
- ~~any existing `LiveAvatarClient`~~ — clean slate.

---

## Implementation Notes

### Pattern to Follow
```python
class LiveAvatarClient:
    def __init__(self, cfg: LiveAvatarConfig, *, session: aiohttp.ClientSession | None = None):
        self.cfg = cfg
        self.logger = logging.getLogger(__name__)
        self._session = session
        self._keep_alive_task: asyncio.Task | None = None

    async def __aenter__(self): ...
    async def __aexit__(self, *exc):
        # guarantee stop_session + cancel keep-alive
        ...
```

### Key Constraints
- Async throughout; one `aiohttp.ClientSession`.
- `X-API-KEY: cfg.api_key` header on create/stop/keep-alive;
  `Authorization: Bearer <handle.session_token>` on `start_session`.
- `stop_session` MUST be idempotent and run in `finally` / `__aexit__`.

### Open Question to surface (do NOT guess)
- **P7 keep-alive transport**: HTTP `/v1/sessions/keep-alive` vs WS
  `session.keep_alive`. Default to the **HTTP** endpoint here and add a
  `# TODO P7` comment; the WS variant belongs to TASK-003 if chosen. Pick ONE,
  do not implement both speculatively.

### References in Codebase
- `packages/ai-parrot-integrations/src/parrot/integrations/msteams/graph.py` — aiohttp client pattern

---

## Acceptance Criteria

- [ ] `from parrot.integrations.liveavatar import LiveAvatarClient` works
- [ ] `test_liveavatar_client_auth_headers`: `X-API-KEY` on most calls; `Bearer session_token` on `start_session`
- [ ] `test_session_lifecycle_stop_on_error`: `stop_session` runs even when the body raises
- [ ] `test_keep_alive_loop_under_5min`: keep-alive scheduled at < 5 min interval
- [ ] `max_session_duration` forwarded to `create_session_token` payload when set
- [ ] Tests pass: `pytest packages/ai-parrot-integrations/tests/integrations/liveavatar/test_client.py -v`
- [ ] No lint errors: `ruff check packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/client.py`

---

## Test Specification

```python
# packages/ai-parrot-integrations/tests/integrations/liveavatar/test_client.py
import pytest
from parrot.integrations.liveavatar import LiveAvatarClient
from parrot.integrations.liveavatar.models import LiveAvatarConfig


@pytest.fixture
def cfg():
    return LiveAvatarConfig(api_key="test", avatar_id="test", is_sandbox=True)


async def test_liveavatar_client_auth_headers(cfg, monkeypatch):
    """X-API-KEY on create; Bearer session_token on start."""
    ...  # mock aiohttp; assert headers captured per call


async def test_session_lifecycle_stop_on_error(cfg):
    """stop_session runs on every exit path, including exceptions."""
    ...  # enter context, raise inside, assert stop_session called


async def test_keep_alive_loop_under_5min(cfg):
    """keep-alive scheduled at < 300s interval."""
    ...
```

---

## Agent Instructions

1. Read spec §3 Module 1, §7 (lifecycle gotchas), and the starter `liveavatar_client.py` if available.
2. Verify the Codebase Contract.
3. Implement `LiveAvatarClient` over `aiohttp`.
4. Run tests + ruff. Move file to `completed/`, update index, fill Completion Note.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-06-18
**Notes**: All 7 unit tests pass, lint clean. Keep-alive uses HTTP
``/v1/sessions/{id}/keep-alive`` (P7 unresolved — ``# TODO P7`` comment added).
``_KEEP_ALIVE_INTERVAL = 280`` (< 300 s). ``stop_session`` is idempotent (404
treated as success) and runs in ``__aexit__``. ``max_session_duration`` forwarded.
**Deviations from spec**: None. P7 deferred with TODO; HTTP is interim choice.
