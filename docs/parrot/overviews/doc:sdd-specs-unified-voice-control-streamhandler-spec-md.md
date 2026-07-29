---
type: Wiki Overview
title: 'Feature Specification: Unified Voice Control on the StreamHandler WebSocket'
id: doc:sdd-specs-unified-voice-control-streamhandler-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Today a browser running a LiveAvatar Phase C (FEAT-243) voice conversation
  needs
relates_to:
- concept: mod:parrot.conf
  rel: mentions
- concept: mod:parrot.handlers.stream
  rel: mentions
- concept: mod:parrot.integrations.liveavatar
  rel: mentions
- concept: mod:parrot.integrations.liveavatar.optin
  rel: mentions
- concept: mod:parrot.integrations.liveavatar.output_transport
  rel: mentions
- concept: mod:parrot.manager
  rel: mentions
- concept: mod:parrot.models.responses
  rel: mentions
---

---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: Unified Voice Control on the StreamHandler WebSocket

**Feature ID**: FEAT-244
**Date**: 2026-06-18
**Author**: Jesus Lara
**Status**: approved
**Target version**: TBD

> Builds on **FEAT-243** (`sdd/specs/liveavatar-phase-c-voice-native.spec.md`) —
> the LiveAvatar Phase C voice-native worker, dispatch, structured-output Redis
> transport and `llm_node` override. This feature consolidates the **control
> plane** of that flow onto the existing `StreamHandler` WebSocket. The worker,
> the `StructuredOutputMessage` contract, the Redis transport and the `llm_node`
> override are **NOT modified**.

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

Today a browser running a LiveAvatar Phase C (FEAT-243) voice conversation needs
**three** socket connections:

1. `POST /api/v1/agents/avatar/{agent_id}/voice-native/start` (REST) to mint a
   publish-capable LiveKit token and dispatch the worker.
2. The **LiveKit room** (WebRTC) for the media (mic ↔ avatar audio/video).
3. `/ws/user` (`UserSocketManager`) to receive the worker's **structured
   outputs** (charts/data/canvas/tool_calls) on a channel keyed by `session_id`.

Separately, text-mode chat already runs over a fourth channel: the
`StreamHandler` WebSocket at `/bots/{bot_id}/stream/ws`.

This fragmentation means the frontend juggles multiple sockets and lifecycles
for what the user experiences as **one conversation**. We want a single
control/data socket per conversation that handles text chat, voice session
start/stop, and structured-output delivery — leaving only the LiveKit media
plane as a separate (and unavoidable) WebRTC connection.

The key enabler: `StreamHandler` runs in the **same server process** as
`run_output_subscriber` (the FEAT-243 Redis consumer). Structured outputs
already arrive in that process; they merely need to be routed to the
`StreamHandler` socket in addition to `UserSocketManager`.

### Goals

- A single `StreamHandler` WebSocket (`/bots/{bot_id}/stream/ws`) carries:
  text chat (`stream_request`, unchanged), voice session start/stop
  (`voice_start` / `voice_stop`), and structured-output frames forwarded from
  the worker.
- Reuse 100% of the FEAT-243 worker, dispatch logic, Redis transport and
  structured-output contract — no worker-side changes.
- Keep the existing REST endpoint `/api/v1/agents/avatar/{agent_id}/voice-native/start`
  and the `/ws/user` delivery path working unchanged (additive, non-breaking).
- Tear down the worker dispatch automatically when the `StreamHandler` socket
  that started it closes (no orphaned workers).

### Non-Goals (explicitly out of scope)

- **Carrying avatar audio/video media over the aiohttp WebSocket.** Media stays
  on LiveKit WebRTC. This feature unifies the control/data plane only.
- Changing the LiveKit worker, the voice pipeline (STT/VAD/TTS/turn-detection),
  the `llm_node` override, or the `StructuredOutputMessage` schema.
- Removing `/ws/user`. It still serves global notifications/HITL; this feature
  only adds a parallel delivery path for the avatar conversation's structured
  outputs.
- Phase A viewer sessions (`/start`) — untouched.

---

## 2. Architectural Design

### Overview

The `StreamHandler` WebSocket becomes the unified control/data plane. Three
planes coexist after this change:

- **Control + text + structured outputs** → `StreamHandler` WS
  (`/bots/{bot_id}/stream/ws`), in the server process.
- **Media** (mic → STT, avatar A/V → browser) → LiveKit room (WebRTC),
  **unchanged**.
- **Worker → server transport** for structured outputs → Redis pub/sub
  (`liveavatar:structured-outputs`), **unchanged**.

On `voice_start`, `StreamHandler` calls a request-agnostic helper extracted from
`avatar.py` that mints the publish-capable browser token and dispatches the
worker (exactly what `VoiceNativeAvatarView` does today), then subscribes the
calling socket to the `session_id` channel and returns the LiveKit credentials
over the same socket. The existing single `run_output_subscriber` is fanned out
to deliver each structured-output envelope to **both** `UserSocketManager` and
`StreamHandler`, so structured outputs reach whichever socket(s) subscribed to
that `session_id`.

### Component Diagram

```
Browser                          Server (one process)                 Worker (separate process)
───────                          ────────────────────                 ─────────────────────────
StreamHandler WS  ──voice_start──►  start_voice_native() ──dispatch──► LiveKit Agents worker
/bots/{id}/stream/ws                  (mint_browser_token                (STT → ask_stream → TTS)
   ▲   │                               + dispatch_worker)                        │
   │   └──voice_stop──────────────►  stop_voice_native()                         │ structured
   │                                                                             ▼
   │  structured frames          ┌─ UserSocketManager.broadcast_to_channel ◄─ run_output_subscriber
   └◄──────────────  fan-out sink ┤                                              ▲
                                  └─ StreamHandler.broadcast_to_channel          │ Redis
                                                                  liveavatar:structured-outputs
LiveKit room (WebRTC) ◄═══════════════ media (mic ↔ avatar A/V) ═══════════════► worker
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `StreamHandler` (`handlers/stream.py`) | extends | New `voice_start`/`voice_stop` message types, per-session channel registry, `broadcast_to_channel` duck-type, ws-close cleanup |
| `_start_voice_native_session` / `_stop_avatar_session` (`handlers/avatar.py`) | refactor | Extract request-agnostic `start_voice_native(app, …)` / `stop_voice_native(app, …)`; REST views call them unchanged |
| `run_output_subscriber` (`liveavatar/output_transport.py`) | reuse (unchanged) | Still the single Redis consumer; now passed a fan-out sink |
| `configure_liveavatar_output_subscriber` (`handlers/liveavatar_output.py`) | extends | Build a fan-out sink over `user_socket_manager` + `stream_handler` |
| `UserSocketManager` (`handlers/user.py`) | reuse (unchanged) | Remains a `broadcast_to_channel` sink; existing `/ws/user` path intact |
| `BotManager.get_bot` (`manager/manager.py`) | reuse (unchanged) | `bot_id` resolves the same registry name the worker resolves |

### Data Models

No new persisted models. Two in-process structures added to `StreamHandler`:

```python
# StreamHandler instance state (handlers/stream.py)
self.channel_subscriptions: dict[str, set[web.WebSocketResponse]]  # session_id -> sockets
self._ws_voice_sessions: dict[web.WebSocketResponse, set[str]]      # ws -> session_ids it started
```

Wire-level message contracts (JSON over the existing socket):

```jsonc
// inbound
{ "type": "voice_start", "session_id": "<id>", "tenant_id": "<optional>" }
{ "type": "voice_stop",  "session_id": "<id>" }

// outbound (voice_start ack)
{ "type": "voice_session", "livekit_url": "wss://…", "token": "<JWT>", "session_id": "<id>" }
// outbound (voice_stop ack)
{ "type": "voice_stopped", "session_id": "<id>" }
// outbound (forwarded from worker, shape = StructuredOutputMessage.model_dump())
{ "type": "tool_call" | "canvas" | "data" | "<output_mode>", "session_id": "<id>", "payload": { … }, "turn_id": "<id|null>" }
```

### New Public Interfaces

```python
# handlers/avatar.py — request-agnostic helpers (extracted, no behavior change)
async def start_voice_native(
    app: web.Application, agent_id: str, session_id: str, tenant_id: str | None
) -> dict:  # -> {"livekit_url", "token", "session_id"}
    ...

async def stop_voice_native(app: web.Application, session_id: str) -> None:
    ...

# handlers/stream.py — UserSocketManager-compatible sink (duck-typed)
async def broadcast_to_channel(
    self, channel: str, message: Any, exclude_ws: web.WebSocketResponse | None = None
) -> None:
    ...
```

---

## 3. Module Breakdown

> These map directly to Task Artifacts in Phase 2.

### Module 1: Extract request-agnostic voice-native helpers
- **Path**: `packages/ai-parrot-server/src/parrot/handlers/avatar.py`
- **Responsibility**: Extract the body of `_start_voice_native_session` into
  `start_voice_native(app, agent_id, session_id, tenant_id) -> dict` and the
  voice-native portion of `_stop_avatar_session` into
  `stop_voice_native(app, session_id) -> None`. Keep the opt-in gate
  (`is_avatar_enabled`), token mint (`mint_browser_token`), dispatch
  (`dispatch_worker`) and the `app[AVATAR_VOICE_SESSIONS_KEY]` bookkeeping inside
  the helpers. Rewire `VoiceNativeAvatarView` / `_stop_avatar_session` to call
  them. Pure refactor — REST behavior is byte-for-byte identical.
- **Depends on**: existing FEAT-243 code only.

### Module 2: StreamHandler voice control + channel delivery
- **Path**: `packages/ai-parrot-server/src/parrot/handlers/stream.py`
- **Responsibility**: Add `channel_subscriptions` + `_ws_voice_sessions` state;
  add `broadcast_to_channel()` (mirror of `UserSocketManager`); handle
  `voice_start` (call `start_voice_native`, subscribe ws to `session_id`, reply
  `voice_session`, record ws→session) and `voice_stop` (call
  `stop_voice_native`, unsubscribe, reply `voice_stopped`) in `_handle_message`;
  add a `finally` in `stream_websocket` that, on socket close, calls
  `stop_voice_native` for every session this socket started and removes it from
  all channel subscriptions.
- **Depends on**: Module 1.

### Module 3: Fan-out the structured-output subscriber
- **Path**: `packages/ai-parrot-server/src/parrot/handlers/liveavatar_output.py`
  (and one line in `packages/ai-parrot-server/src/parrot/manager/manager.py`)
- **Responsibility**: In `configure_liveavatar_output_subscriber`, build a small
  fan-out sink implementing `broadcast_to_channel(channel, message,
  exclude_ws=None)` that forwards to every present manager among
  `app['user_socket_manager']` and `app['stream_handler']`, and pass that sink
  to `run_output_subscriber`. In `manager.py`, store the constructed
  `StreamHandler` instance as `self.app['stream_handler'] = st` next to its
  existing `configure_routes` call so the subscriber can reach it.
- **Depends on**: Module 2 (needs `StreamHandler.broadcast_to_channel`).

### Module 4: Tests
- **Path**: `packages/ai-parrot-server/tests/test_stream_voice_control.py`,
  extend `packages/ai-parrot-server/tests/test_liveavatar_output.py`
- **Responsibility**: Unit-test the new message types, channel subscription /
  cleanup, the extracted helpers, and the fan-out sink. See §4.
- **Depends on**: Modules 1–3.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_start_voice_native_helper` | M1 | Mints token + dispatches worker + records `AVATAR_VOICE_SESSIONS_KEY`; returns `{livekit_url, token, session_id}` (mock `LiveKitRoomManager`) |
| `test_stop_voice_native_helper` | M1 | Pops the dispatch record and calls `delete_dispatch`; idempotent on unknown `session_id` |
| `test_rest_view_still_works` | M1 | `VoiceNativeAvatarView.post` returns the same JSON as before the refactor |
| `test_voice_start_message` | M2 | `voice_start` subscribes the ws to `session_id` and replies `voice_session` with credentials |
| `test_voice_stop_message` | M2 | `voice_stop` unsubscribes and calls `stop_voice_native`; replies `voice_stopped` |
| `test_broadcast_to_channel` | M2 | Sends only to sockets subscribed to that channel; skips closed/excluded sockets |
| `test_ws_close_cleanup` | M2 | Closing a socket that started a session triggers `stop_voice_native` and removes all its channel subscriptions |
| `test_unknown_session_id_voice_start` | M2 | `voice_start` without `session_id` replies `error` (no dispatch) |
| `test_fanout_sink_both_managers` | M3 | Fan-out sink calls `broadcast_to_channel` on both `user_socket_manager` and `stream_handler` when both present |
| `test_fanout_sink_missing_manager` | M3 | Fan-out tolerates a missing `stream_handler` (delivers to whichever exists) |

### Integration Tests
| Test | Description |
|---|---|
| `test_end_to_end_structured_output_to_stream_ws` | A structured-output envelope published to Redis reaches a `StreamHandler` socket subscribed to that `session_id` (via the real subscriber + fan-out sink) |
| `test_text_and_voice_same_socket` | One socket handles a `stream_request` (text) and a `voice_start` (voice) in the same session without interference |

### Test Data / Fixtures
```python
@pytest.fixture
def fake_room_manager(mocker):
    rm = mocker.Mock()
    rm.url = "wss://test.livekit.cloud"
    rm.mint_browser_token.return_value = "browser-jwt"
    rm.dispatch_worker = mocker.AsyncMock(return_value="dispatch-123")
    rm.delete_dispatch = mocker.AsyncMock()
    return rm

@pytest.fixture
def structured_envelope():
    return {"channel": "sess-1",
            "message": {"type": "data", "session_id": "sess-1",
                        "payload": {"data": {"x": 1}}, "turn_id": None}}
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] A single `/bots/{bot_id}/stream/ws` socket accepts `stream_request`
      (text, unchanged), `voice_start`, and `voice_stop`.
- [ ] `voice_start` mints a publish-capable LiveKit token and dispatches the
      FEAT-243 worker by reusing the extracted `start_voice_native` helper (no
      logic duplicated from `avatar.py`).
- [ ] `voice_start` replies `{type:"voice_session", livekit_url, token, session_id}`
      and subscribes the socket to the `session_id` channel.
- [ ] Structured outputs published by the worker to Redis reach the
      `StreamHandler` socket subscribed to that `session_id`.
- [ ] The existing `/ws/user` (`UserSocketManager`) delivery path for structured
      outputs still works (fan-out, not replacement).
- [ ] The REST endpoint `/api/v1/agents/avatar/{agent_id}/voice-native/start`
      returns identical output to pre-refactor (no breaking change).
- [ ] Closing a `StreamHandler` socket tears down every worker dispatch it
      started (verified no orphan in `AVATAR_VOICE_SESSIONS_KEY`).
- [ ] No worker-side files changed (`livekit_agent/`, `output_transport.py`,
      `output_bridge.py`, `client.py`, `room_manager.py` untouched except where
      reused).
- [ ] All unit + integration tests pass: `pytest packages/ai-parrot-server/tests/ -v`.
- [ ] No avatar audio/video is sent over the aiohttp WebSocket (media stays on
      LiveKit).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**

### Verified Imports
```python
# StreamHandler (server)
from parrot.handlers.stream import StreamHandler                 # handlers/stream.py:11
from parrot.models.responses import AIMessage                    # handlers/stream.py:8
from datamodel.parsers.json import json_encoder, json_decoder    # handlers/stream.py:4

# Avatar helpers (server)
from parrot.integrations.liveavatar import LiveKitRoomManager    # avatar.py:314 (lazy import inside handler)
from parrot.integrations.liveavatar.livekit_agent.models import AvatarJobMetadata  # avatar.py:315
from parrot.integrations.liveavatar.optin import is_avatar_enabled                 # avatar.py:318

# Output subscriber (server)
from parrot.integrations.liveavatar.output_transport import (
    DEFAULT_OUTPUT_CHANNEL, run_output_subscriber,               # liveavatar_output.py:63
)
from parrot.conf import REDIS_URL                                # liveavatar_output.py:23

# Worker-side resolver (for the bot_id == agent_name verification only — NOT modified)
from parrot.manager.bot_resolver import build_standalone_bot_resolver  # bot_resolver.py:25
```

### Existing Class Signatures
```python
# packages/ai-parrot-server/src/parrot/handlers/stream.py
class StreamHandler(BaseHandler):
    def __init__(self, *args, **kwargs):                          # line 18
        self.active_connections = set()                          # line 20
    async def _get_bot(self, request) -> AbstractBot: ...        # line 31  (bot_id from match_info, line 34)
    def _extract_stream_params(self, payload, *extra_ignored_keys): ...  # line 42
    async def stream_websocket(self, request): ...               # line 197 (JWT subprotocol auth lines 206-220; ws loop 239-258)
    async def _validate_token(self, request, token) -> bool: ... # line 261
    async def _handle_message(self, ws, data, bot, request): ... # line 292 (dispatch on data['type']: auth/stream_request/ping)
    async def broadcast(self, message: dict): ...                # line 353 (iterates active_connections)
    def configure_routes(self, app): ...                         # line 361 (add_get '/bots/{bot_id}/stream/ws', line 374)

# packages/ai-parrot-server/src/parrot/handlers/avatar.py
AVATAR_VOICE_SESSIONS_KEY = "avatar_voice_sessions"              # line 57
async def _start_voice_native_session(request) -> web.Response:  # line 287 (mint_browser_token 353; dispatch_worker 366; voice_store 382)
async def _stop_avatar_session(request) -> web.Response:         # line 223 (voice_store.pop 248; _delete_voice_dispatch 250)
async def _delete_voice_dispatch(record: dict) -> None:         # line 198
def _worker_agent_name() -> str:                                 # line 277 (env LIVEAVATAR_WORKER_AGENT_NAME, default "liveavatar-voice")
class VoiceNativeAvatarView(BaseView):                           # line 420 (@is_authenticated/@user_session; post -> _start_voice_native_session 432)
async def close_all_avatar_sessions(app) -> None:               # line 436

# packages/ai-parrot-server/src/parrot/handlers/user.py
class UserSocketManager(WebSocketManager):
    self.channel_subscriptions: Dict[str, List[web.WebSocketResponse]]  # line 97
    async def _subscribe_to_channel(self, ws, channel_name): ...        # line 323
    async def broadcast_to_channel(self, channel, message, exclude_ws=None): ...  # line 357

# packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/output_transport.py
DEFAULT_OUTPUT_CHANNEL = "liveavatar:structured-outputs"         # line 35
async def run_output_subscriber(redis_client, socket_manager, *, channel=...): ...  # line 100 (calls socket_manager.broadcast_to_channel, line 127)

# packages/ai-parrot-server/src/parrot/handlers/liveavatar_output.py
def configure_liveavatar_output_subscriber(app, *, redis_url=None, channel=None) -> web.Application:  # line 33
    # _start (line 58) looks up app['user_socket_manager'] (line 74), launches run_output_subscriber (line 85)

# packages/ai-parrot-server/src/parrot/manager/bot_resolver.py
def botmanager_bot_resolver(manager: BotManager) -> BotResolver:  # line 33 (manager.get_bot(name, request=None), line 49)
def build_standalone_bot_resolver(*, enable_registry_bots=True,
    enable_database_bots=False, enable_crews=False) -> BotResolver:  # line 54
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `start_voice_native()` | `LiveKitRoomManager.mint_browser_token` / `.dispatch_worker` | method call (extracted) | `avatar.py:353,366` |
| `stop_voice_native()` | `_delete_voice_dispatch()` | method call (extracted) | `avatar.py:198,250` |
| `StreamHandler.broadcast_to_channel` | per-`session_id` `channel_subscriptions` | direct `ws.send_str` | new (mirror of `user.py:357`) |
| fan-out sink | `UserSocketManager.broadcast_to_channel` + `StreamHandler.broadcast_to_channel` | duck-typed call from `run_output_subscriber` | `output_transport.py:127` |
| `manager.py` wiring | `app['stream_handler'] = st` | app key set | `manager.py` (near existing `st = StreamHandler(); st.configure_routes(...)`) |

### Does NOT Exist (Anti-Hallucination)
- ~~`StreamHandler.channel_subscriptions`~~ — does not exist yet (added by M2).
- ~~`StreamHandler.broadcast_to_channel`~~ — does not exist yet (added by M2).
- ~~`start_voice_native` / `stop_voice_native` in `avatar.py`~~ — do not exist yet
  (created by M1; today the logic is inline in `_start_voice_native_session` /
  `_stop_avatar_session`).
- ~~`app['stream_handler']`~~ — not set today; `StreamHandler` is constructed in
  `manager.py` but never stored on the app (added by M3).
- ~~A second Redis subscriber for `StreamHandler`~~ — not needed; reuse the single
  `run_output_subscriber` with a fan-out sink.
- ~~Any media (audio/video) frame type over the WS~~ — out of scope; media is
  LiveKit WebRTC only.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Mirror `UserSocketManager.broadcast_to_channel` (`user.py:357`) exactly for the
  `StreamHandler` sink so the fan-out is uniform and `exclude_ws` is honored.
- Keep all LiveAvatar imports **lazy inside the helpers** (as `avatar.py` already
  does, lines 314-318) so the server never hard-requires the optional
  `ai-parrot-integrations[liveavatar]` extra.
- `async/await` throughout; use `self.logger` for all logging.
- The extracted helpers must preserve the existing opt-in gate
  (`is_avatar_enabled`) and the `AVATAR_VOICE_SESSIONS_KEY` bookkeeping so REST
  `/stop` and `close_all_avatar_sessions` (shutdown) keep working unchanged.

### Known Risks / Gotchas
- **`bot_id` (StreamHandler) vs `agent_name` (worker resolver).** Resolved: both
  paths call `BotManager.get_bot(name)` against the `@register_agent` registry by
  name (`stream.py:35`, `bot_resolver.py:49`), so the same name resolves the same
  brain. **Caveat:** the worker's standalone resolver defaults to
  `enable_database_bots=False` (`bot_resolver.py:54`). DB-defined bots resolve in
  the server (StreamHandler) but will NOT resolve in the worker unless the worker
  entry module sets `enable_database_bots=True`. Document this; do not silently
  assume DB bots work in voice mode.
- **`ENABLE_LIVEAVATAR_VOICE` flag.** The output subscriber only runs when this
  is enabled (`manager.py` opt-in for `configure_liveavatar_output_subscriber`).
  Unified voice on `StreamHandler` requires the same flag; if off, `voice_start`
  can still dispatch but structured outputs never arrive. Reply to `voice_start`
  should succeed regardless, but document the dependency.
- **Cleanup ordering.** The `finally` in `stream_websocket` must run
  `stop_voice_native` for sockets that started sessions even on abnormal close
  (current loop only removes from `active_connections` on `WSMsgType.ERROR`,
  `stream.py:253`). Ensure the cleanup is in a single `finally`, not only the
  error branch, to avoid orphaned dispatches.
- **`session_id` is dual-purpose** — it is both the LiveKit room name and the
  structured-output channel key (FEAT-243 invariant). The client must pass the
  same `session_id` to `voice_start` as it uses for the LiveKit room and for
  text `stream_request` to keep one conversation coherent.
- **Channel registry growth.** Remove empty `session_id` entries from
  `channel_subscriptions` on unsubscribe/close to avoid unbounded growth (mirror
  `user.py:747-754`).

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `ai-parrot-integrations[liveavatar]` | existing | Worker, room manager, transport (already required by FEAT-243) |
| `redis` | existing | Structured-output pub/sub (already required by FEAT-243) |

No new external dependencies.

---

## 8. Open Questions

> Questions that must be resolved before or during implementation.

- [x] Does `bot_id` (StreamHandler) resolve the same brain as the worker's
      `bot_resolver(agent_name)`? — *Resolved during spec research*: Yes, both
      use `BotManager.get_bot(name)` against the `@register_agent` registry
      (`stream.py:35`, `bot_resolver.py:49`). Caveat: DB-defined bots need the

…(truncated)…
