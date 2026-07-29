---
type: Wiki Overview
title: 'TASK-007: Avatar session endpoint + avatar-mode flag (M6)'
id: doc:sdd-tasks-completed-task-007-avatar-session-endpoint-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Implements **Module 6** (spec §3): the HTTP surface. Add a start/stop avatar'
relates_to:
- concept: mod:parrot.integrations.liveavatar
  rel: mentions
- concept: mod:parrot.integrations.liveavatar.models
  rel: mentions
- concept: mod:parrot.integrations.liveavatar.optin
  rel: mentions
---

# TASK-007: Avatar session endpoint + avatar-mode flag (M6)

**Feature**: FEAT-242 — LiveAvatar Phase A (avatar as the "mouth" of AgentChat)
**Spec**: `sdd/specs/liveavatar-phase-a-mouth.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-006
**Assigned-to**: unassigned

---

## Context

Implements **Module 6** (spec §3): the HTTP surface. Add a start/stop avatar
session endpoint and an avatar-mode flag on the chat/voice path. The endpoint
returns the viewer's `livekit_url` + `client_token` ONLY — never the agent token
or the avatar WS URL. Extends `AgentVoiceTalk` (no breaking changes). Capability:
`avatar-session-endpoint`.

---

## Scope

- Extend `AgentVoiceTalk` (`agent_voice.py`) with an avatar-mode flag (per-request
  selector) that, when set, drives the turn through `AvatarSessionOrchestrator`
  instead of the plain TTS-out path.
- Add a new route to start/stop an avatar session that returns
  `{ livekit_url, client_token, session_id }` for the browser viewer.
- The agent/avatar token and avatar WS URL stay server-side — never serialized
  into any client response.
- Reuse the existing STT-in / TTS-out structure; do NOT rewrite it.

**NOT in scope**: opt-in/tenant gating (TASK-008 — wire a hook point but the
gating logic lands there), frontend viewer (TASK-009), orchestrator internals
(TASK-006).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/agent_voice.py` | MODIFY | Avatar-mode flag; drive orchestrator |
| `packages/ai-parrot-server/src/parrot/handlers/<avatar route module>.py` | CREATE | Start/stop avatar session endpoint (confirm route module + registration at impl) |
| `packages/ai-parrot-server/tests/handlers/test_avatar_endpoint.py` | CREATE | Endpoint tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-06-18.

### Verified Imports
```python
from aiohttp import web
from parrot.integrations.liveavatar import AvatarSessionOrchestrator   # from TASK-006
from parrot.integrations.liveavatar.models import LiveKitRoomTokens, AvatarSessionHandle
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/agent.py
class AgentTalk(BaseView):                                  # line 100
    async def post(self): ...                               # line 1523 (POST /api/v1/agents/chat/{agent_id})
    async def _handle_stream_response(self, bot, query, ...) -> web.StreamResponse: ...  # line 2365

# packages/ai-parrot-server/src/parrot/handlers/agent_voice.py
class AgentVoiceTalk(AgentTalk):                            # line 57 (POST /api/v1/agents/voice/{agent_id})
    async def handle_upload(self, *args, **kwargs) -> Tuple[Dict[str, Any], dict]: ...  # line 84 (STT-in)
    async def post(self) -> web.Response: ...               # line 268 (TTS-out, attaches audio_base64)
    # per-request selectors already exist: tts_backend, stt_backend, audio_format
```

### Does NOT Exist (do NOT reference)
- ~~`tenant_id` threaded through the chat endpoint~~ — the chat path threads
  `user_id`/`session_id` only (spec §6). Add an explicit hook for TASK-008; do NOT
  assume `tenant_id` already flows.
- ~~an existing avatar route / avatar-mode flag~~ — clean slate; this task adds them.
- ~~returning the agent token to the client~~ — FORBIDDEN; viewer gets `client_token` only.

---

## Implementation Notes

### Pattern to Follow
- Mirror the per-request selector pattern already used for `tts_backend`/`stt_backend`
  in `AgentVoiceTalk` for the new `avatar` flag.
- The start endpoint constructs the orchestrator, calls `run(...)`, and responds
  with viewer credentials only:
  ```python
  return web.json_response({
      "livekit_url": tokens.livekit_url,
      "client_token": tokens.client_token,
      "session_id": handle.session_id,
  })
  ```

### Key Constraints
- No breaking changes to existing `AgentVoiceTalk` / streaming / WS public API.
- Async throughout; `self.logger`.
- Confirm how routes are registered in the server (router setup) and follow it
  for the new endpoint.

### Open Question to surface (do NOT guess)
- **Q-deploy**: the orchestrator is a long-lived stateful process; spawn-per-session
  vs warm pool is unresolved (owner: Jesús). Implement the simplest correct path
  (spawn-per-request session) and add a `# TODO Q-deploy` note. Do NOT build a pool.

### References in Codebase
- `packages/ai-parrot-server/src/parrot/handlers/agent_voice.py` — extend pattern
- `packages/ai-parrot-server/tests/handlers/test_agent_voice.py` — test style

---

## Acceptance Criteria

- [ ] `test_endpoint_returns_viewer_token`: response carries `livekit_url` + `client_token` + `session_id`, and does NOT contain `agent_token` or `ws_url`
- [ ] Avatar mode is opt-in via the request flag; absent flag → unchanged text/voice behavior
- [ ] No breaking change to existing `AgentVoiceTalk.post` / `handle_upload` signatures
- [ ] Tests pass: `pytest packages/ai-parrot-server/tests/handlers/test_avatar_endpoint.py -v`
- [ ] No lint errors: `ruff check packages/ai-parrot-server/src/parrot/handlers/agent_voice.py`

---

## Test Specification

```python
# packages/ai-parrot-server/tests/handlers/test_avatar_endpoint.py
import pytest


async def test_endpoint_returns_viewer_token(client):
    resp = await client.post("/api/v1/agents/avatar/<agent_id>/start", json={...})
    body = await resp.json()
    assert "livekit_url" in body and "client_token" in body
    assert "agent_token" not in body and "ws_url" not in body


async def test_avatar_mode_opt_in_off_by_default(client):
    """No avatar flag → plain text/voice path, no avatar session opened."""
    ...
```

---

## Agent Instructions

1. Read spec §3 Module 6 and §6 contract (AgentVoiceTalk signatures).
2. Verify the Codebase Contract and the server's route registration mechanism.
3. Extend `AgentVoiceTalk` + add the endpoint; keep a hook for TASK-008 gating.
4. Run tests + ruff. Move file to `completed/`, update index, fill Completion Note.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-06-18
**Notes**: All 7 tests pass, lint clean (2 fixes applied: removed unused
``AvatarSessionOrchestrator`` import from the lazy try-block and removed unused
``question`` local variable from ``_start_avatar_session``). Two files modified/created:
``avatar.py`` (new — ``_start_avatar_session``, ``_stop_avatar_session``,
``register_avatar_routes``); ``agent_voice.py`` (extended — ``post_init`` + ``_read_voice_options``
+ ``post`` with avatar-mode gate).

Response contract enforced: ``agent_token`` and ``ws_url`` are never serialised in the
``/start`` response. ``# TODO Q-deploy`` comment placed at spawn-per-request pattern.
TASK-008 hook is called via lazy import ``from parrot.integrations.liveavatar.optin import
is_avatar_enabled``; if the import fails avatar mode silently degrades to False (graceful
fallback before TASK-008 lands).

Integration test uses ``sys.modules`` injection to avoid requiring ``ai-parrot-integrations``
installed in the test venv; the 6 unit tests for ``AgentVoiceTalk`` run without any mocking.

**Deviations from spec**: None. ``register_avatar_routes()`` placed in ``avatar.py`` (not in
``manager.py`` — manager.py was not listed as a file to modify; caller wires at startup).
