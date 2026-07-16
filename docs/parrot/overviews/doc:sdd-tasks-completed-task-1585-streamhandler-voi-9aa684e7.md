---
type: Wiki Overview
title: 'TASK-1585: StreamHandler voice control + per-session channel delivery'
id: doc:sdd-tasks-completed-task-1585-streamhandler-voice-control-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 2** of FEAT-244. Turns the existing text-only
relates_to:
- concept: mod:parrot.handlers.avatar
  rel: mentions
- concept: mod:parrot.handlers.stream
  rel: mentions
- concept: mod:parrot.models.responses
  rel: mentions
---

# TASK-1585: StreamHandler voice control + per-session channel delivery

**Feature**: FEAT-244 — Unified Voice Control on the StreamHandler WebSocket
**Spec**: `sdd/specs/unified-voice-control-streamhandler.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1584
**Assigned-to**: unassigned

---

## Context

Implements **Module 2** of FEAT-244. Turns the existing text-only
`StreamHandler` WebSocket (`/bots/{bot_id}/stream/ws`) into the unified
control/data plane: it gains `voice_start` / `voice_stop` message handling
(delegating to the TASK-1584 helpers), a per-`session_id` channel registry, a
`broadcast_to_channel` sink duck-typed to `UserSocketManager`, and ws-close
cleanup that tears down any worker dispatch the socket started. Media stays on
LiveKit — this task adds **no** audio/video framing.

---

## Scope

- Add instance state in `StreamHandler.__init__`:
  - `self.channel_subscriptions: dict[str, set]` — `session_id -> {ws}`.
  - `self._ws_voice_sessions: dict` — `ws -> set[session_id]` it started.
- Add `async def broadcast_to_channel(self, channel, message, exclude_ws=None)`
  mirroring `UserSocketManager.broadcast_to_channel` (`user.py:357`): iterate the
  channel's sockets, skip `exclude_ws` and `ws.closed`, `ws.send_str(json_encoder(message))`.
- In `_handle_message`, add two `msg_type` branches:
  - `voice_start`: read `session_id` (required → `error` if missing) + optional
    `tenant_id`; resolve `agent_id` from `request.match_info['bot_id']`; call
    `start_voice_native(request.app, agent_id, session_id, tenant_id)`; subscribe
    the ws to `session_id`; record `session_id` in `_ws_voice_sessions[ws]`;
    reply `{"type":"voice_session", **result}`. On `web.HTTPException` reply
    `{"type":"error","message": reason}`.
  - `voice_stop`: read `session_id`; call `stop_voice_native(request.app,
    session_id)`; unsubscribe the ws + drop from `_ws_voice_sessions[ws]`; reply
    `{"type":"voice_stopped","session_id": session_id}`.
- Add a `finally` block to `stream_websocket` that on socket close:
  - for each `session_id` in `_ws_voice_sessions.pop(ws, set())`, `await
    stop_voice_native(request.app, session_id)`;
  - remove `ws` from every `channel_subscriptions` set and delete now-empty sets;
  - discard `ws` from `active_connections` (replacing the current error-only removal).
- Add a `_subscribe`/`_unsubscribe` private helper pair OR inline — keep it small.
- Write unit tests (see Test Specification).

**NOT in scope**: the fan-out wiring of the Redis subscriber (TASK-1586) — but
`broadcast_to_channel` MUST be ready for TASK-1586 to call. No change to
`stream_request`, `auth`, `ping`, SSE/NDJSON/chunked handlers.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/stream.py` | MODIFY | Channel state, `broadcast_to_channel`, `voice_start`/`voice_stop`, ws-close cleanup |
| `packages/ai-parrot-server/tests/test_stream_voice_control.py` | CREATE | Unit tests for the new behavior |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Already at top of stream.py (keep)
from aiohttp import web                                            # stream.py:3
from datamodel.parsers.json import json_encoder, json_decoder     # stream.py:4
from parrot.models.responses import AIMessage                     # stream.py:8
# New (lazy, inside the voice_start/voice_stop branches — do NOT hard-require):
from parrot.handlers.avatar import start_voice_native, stop_voice_native  # created by TASK-1584
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/stream.py
class StreamHandler(BaseHandler):
    def __init__(self, *args, **kwargs):                          # line 18 (self.active_connections = set(), line 20)
    async def _get_bot(self, request) -> AbstractBot: ...         # line 31  (bot_id via request.match_info.get('bot_id'), line 34)
    async def stream_websocket(self, request): ...                # line 197 (ws loop 239-258; needs a finally added)
    async def _handle_message(self, ws, data, bot, request): ...  # line 292 (branch on data.get('type'); add voice_start/voice_stop)

# packages/ai-parrot-server/src/parrot/handlers/user.py — MIRROR this method exactly
async def broadcast_to_channel(self, channel, message, exclude_ws=None):  # line 357
    if channel not in self.channel_subscriptions: return          # line 371
    message_str = json_encoder(message)                           # line 374
    for ws in self.channel_subscriptions[channel]:                # line 375
        if ws != exclude_ws and not ws.closed:                    # line 376
            await ws.send_str(message_str)
# user.py cleanup pattern to mirror for empty channels: lines 747-754

# packages/ai-parrot-server/src/parrot/handlers/avatar.py (TASK-1584)
async def start_voice_native(app, agent_id, session_id, tenant_id) -> dict   # -> {"livekit_url","token","session_id"}
async def stop_voice_native(app, session_id) -> None
```

### Does NOT Exist
- ~~`StreamHandler.channel_subscriptions`~~ / ~~`StreamHandler._ws_voice_sessions`~~ / ~~`StreamHandler.broadcast_to_channel`~~ — this task creates them.
- ~~`ws._authenticated` gate for voice~~ — not required; the JWT subprotocol handshake (`stream.py:206-220`) already authenticated the socket. Do not add a second gate.
- ~~Any `media`/`audio`/`video` message type~~ — out of scope (Non-Goal); media is LiveKit only.
- ~~`StreamHandler` storing a LiveKit room object~~ — it stores only `session_id` strings; rooms/tokens live in `avatar.py` bookkeeping.

---

## Implementation Notes

### Pattern to Follow
`UserSocketManager` (`user.py`) is the reference for the channel registry:
`channel_subscriptions: dict[str, list/set]`, `_subscribe_to_channel`
(`user.py:323`), `_unsubscribe_from_channel` (`user.py:341`),
`broadcast_to_channel` (`user.py:357`), and empty-channel cleanup on disconnect
(`user.py:747-754`). Use a `set` (not list) for O(1) add/remove.

### Key Constraints
- The cleanup MUST live in a single `finally` around the `async for msg in ws`
  loop so abnormal closes (not just `WSMsgType.ERROR`) tear down dispatches.
- `voice_start` failures from the helper are `web.HTTPException` subclasses —
  catch and translate to an `error` frame; do NOT let them bubble and kill the ws.
- `stop_voice_native` never raises; still guard the cleanup loop defensively.
- Async throughout; use `self.logger` for start/stop/cleanup at info/debug.

### References in Codebase
- `stream.py:292-351` — `_handle_message` dispatch to extend.
- `user.py:357-380` — `broadcast_to_channel` to mirror.
- `avatar.py` — the helpers (TASK-1584).

---

## Acceptance Criteria

- [ ] `voice_start` subscribes the ws to `session_id` and replies `voice_session` with credentials.
- [ ] `voice_start` without `session_id` replies `error` and dispatches nothing.
- [ ] `voice_stop` unsubscribes and replies `voice_stopped`.
- [ ] `broadcast_to_channel` delivers only to subscribed, open, non-excluded sockets.
- [ ] Closing a socket that started a session calls `stop_voice_native` and clears its subscriptions.
- [ ] Existing `stream_request` / `auth` / `ping` behavior unchanged.
- [ ] All tests pass: `pytest packages/ai-parrot-server/tests/test_stream_voice_control.py -v`
- [ ] No lint errors: `ruff check packages/ai-parrot-server/src/parrot/handlers/stream.py`

---

## Test Specification

```python
# packages/ai-parrot-server/tests/test_stream_voice_control.py
import pytest
from parrot.handlers.stream import StreamHandler


class FakeWS:
    def __init__(self):
        self.closed = False
        self.sent = []
    async def send_str(self, s):
        self.sent.append(s)


@pytest.fixture
def handler():
    return StreamHandler()


async def test_broadcast_to_channel_only_subscribers(handler):
    a, b = FakeWS(), FakeWS()
    handler.channel_subscriptions["sess-1"] = {a}
    await handler.broadcast_to_channel("sess-1", {"type": "data", "x": 1})
    assert a.sent and not b.sent


async def test_voice_start_subscribes_and_acks(handler, mocker):
    mocker.patch("parrot.handlers.avatar.start_voice_native",
                 mocker.AsyncMock(return_value={"livekit_url": "wss://x", "token": "t", "session_id": "sess-1"}))
    ws = FakeWS()
    req = mocker.Mock()
    req.app = {}
    req.match_info = {"bot_id": "my-agent"}
    await handler._handle_message(ws, {"type": "voice_start", "session_id": "sess-1"}, bot=mocker.Mock(), request=req)
    assert ws in handler.channel_subscriptions["sess-1"]
    assert any('"voice_session"' in s for s in ws.sent)


async def test_voice_start_missing_session_id_errors(handler, mocker):
    ws = FakeWS()
    req = mocker.Mock(); req.app = {}; req.match_info = {"bot_id": "my-agent"}
    await handler._handle_message(ws, {"type": "voice_start"}, bot=mocker.Mock(), request=req)
    assert any('"error"' in s for s in ws.sent)
```

---

## Agent Instructions

1. Read the spec (§2, §6) and TASK-1584's contract.
2. Verify the Codebase Contract against `stream.py` and `user.py`.
3. Update index status → `in-progress`.
4. Implement per scope; mirror `UserSocketManager` channel semantics.
5. Run the tests + ruff; verify acceptance criteria.
6. Move this file to `sdd/tasks/completed/` and update index → `done`.
7. Fill in the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 4.6)
**Date**: 2026-06-18
**Notes**: Added `channel_subscriptions` and `_ws_voice_sessions` to `StreamHandler.__init__`.
Added `broadcast_to_channel`, `_subscribe_to_channel`, `_unsubscribe_from_channel`, and
`_cleanup_ws_voice_sessions` methods. Added `voice_start` and `voice_stop` branches to
`_handle_message`. Added a `finally` block to `stream_websocket` that calls
`_cleanup_ws_voice_sessions` on socket close. 13 unit tests pass, no ruff errors.
**Deviations from spec**: none
