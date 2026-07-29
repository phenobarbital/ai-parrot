---
type: Wiki Overview
title: 'Feature Specification: Realtime LiveAvatar mouth driven by VoiceBot (Gemini
  Live)'
id: doc:sdd-specs-voicechat-liveavatar-gemini-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Today `VoiceChatHandler` (`/ws/voice`) runs a fully realtime voice conversation
relates_to:
- concept: mod:parrot.bots.voice
  rel: mentions
- concept: mod:parrot.clients.live
  rel: mentions
- concept: mod:parrot.integrations.liveavatar
  rel: mentions
- concept: mod:parrot.integrations.liveavatar.optin
  rel: mentions
- concept: mod:parrot.voice.handler
  rel: mentions
---

---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: Realtime LiveAvatar mouth driven by VoiceBot (Gemini Live)

**Feature ID**: FEAT-245
**Date**: 2026-06-18
**Author**: Jesus Lara
**Status**: approved
**Target version**: TBD

> Reuses the **avatar session + LiveKit room + LITE-mode "mouth"** from FEAT-242
> Phase A (`LiveKitRoomManager`, `LiveAvatarClient`, `AvatarWebSocket`) and the
> BYO-LiveKit transport pattern from FEAT-243. It does **NOT** use the FEAT-243
> LiveKit Agents *worker* (Deepgram STT / Cartesia TTS / `ask_stream` brain):
> the brain here is **Gemini Live** (speech-to-speech) via `VoiceBot`, which
> already produces output audio. See §1 Non-Goals.

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

Today `VoiceChatHandler` (`/ws/voice`) runs a fully realtime voice conversation
with `VoiceBot` → `GeminiLiveClient` (Gemini Live, speech-to-speech): browser mic
PCM in → Gemini → assistant **audio out** (PCM 24 kHz) + transcripts + tool
calls, all streamed back over the same WebSocket. There is no visual avatar.

Separately, the LiveAvatar stack (FEAT-242/243) can render a talking-head avatar
that lip-syncs raw PCM pushed to its LITE-mode "mouth" (`AvatarWebSocket`) and
publishes the avatar's video+audio into a LiveKit room the browser subscribes to.

We want the **realtime, native** experience: the avatar's mouth speaks the Gemini
Live conversation as it happens. The decisive enabler is a **sample-rate match** —
Gemini Live emits PCM at **24 kHz**, exactly what `AvatarWebSocket.send_audio_frame`
expects (`AVATAR_PCM_SAMPLE_RATE = 24_000`), so the audio tees in with **no
resampling** (unlike FEAT-242's 44.1 kHz Supertonic path).

Because `VoiceChatHandler` and `VoiceBot`/Gemini Live run **in the same process**,
there is no separate worker and **no Redis bridge** is needed — transcripts and
tool calls keep flowing back over `/ws/voice` as they do today.

### Goals

- When avatar mode is enabled on a `/ws/voice` session, bring up a LiveAvatar
  session (LiveKit room + `LiveAvatarClient` + `AvatarWebSocket`) and **tee the
  Gemini Live output audio into the avatar's mouth** in realtime.
- Return **viewer credentials** (LiveKit `livekit_url` + subscribe-only
  `client_token`) to the browser in the `session_started` reply so it can join
  the room and see/hear the avatar.
- **Dual audio** (per product decision): keep streaming raw Gemini audio over
  `/ws/voice` (`response_chunk`) **and** drive the avatar via LiveKit. Signal
  avatar activity to the client so it can mute one source and avoid echo.
- Handle **barge-in**: when Gemini reports an interruption, clear the avatar's
  scheduled audio (`AvatarWebSocket.interrupt()`).
- **Graceful degradation**: if the avatar session fails to start or drops, the
  voice conversation continues unaffected over `/ws/voice` (avatar is additive).

### Non-Goals (explicitly out of scope)

- **Using the FEAT-243 LiveKit Agents worker** (STT/VAD/TTS + `ask_stream`
  brain). Gemini Live replaces that pipeline; the worker is not dispatched here.
  *(Driving the avatar from the text `ask_stream` brain is FEAT-244's path — see
  `sdd/specs/unified-voice-control-streamhandler.spec.md`.)*
- **Publishing the browser mic to LiveKit.** The mic stays on `/ws/voice`
  (Gemini Live consumes it as today). LiveKit carries only the avatar's
  downstream video+audio.
- **Resampling.** Gemini output is already 24 kHz mono 16-bit LE — the avatar's
  exact input format.
- Changing Gemini Live behavior, the `LiveVoiceResponse` contract, or the
  `/ws/voice` message protocol beyond the additive `avatar` fields.
- New REST endpoints — everything rides the existing `/ws/voice` socket.

---

## 2. Architectural Design

### Overview

`VoiceChatHandler` keeps its existing audio-in / Gemini / audio-out loop. Two
additive hooks bring in the avatar:

1. **Session start** (`_handle_start_session`): if the client requests avatar
   mode (and the tenant is opted in), construct a new `VoiceAvatarSession` helper
   that mints LiveKit room tokens (`LiveKitRoomManager.mint_room_tokens`), creates
   and starts a `LiveAvatarClient` LITE session with the BYO `livekit_config`,
   opens an `AvatarWebSocket`, and awaits its connected gate. The viewer
   credentials (`livekit_url`, `client_token`) are added to the `session_started`
   reply, plus an `avatar` block telling the client avatar audio is active.
2. **Per-response tee** (`_send_voice_response`): after sending the existing
   browser `response_chunk`, push `response.audio_data` into the avatar via
   `VoiceAvatarSession.speak(pcm)`; on `response.is_complete` call
   `finish_turn()`; on `response.is_interrupted` call `interrupt()`. Every avatar
   call is best-effort — failures are logged and never break the voice stream.

On cleanup (`_cleanup_connection`), the avatar session is finished and torn down.

The new `VoiceAvatarSession` (in the liveavatar package) encapsulates the
tokens + client + `AvatarWebSocket` lifecycle and exposes a small PCM-stream
API (`speak` / `finish_turn` / `interrupt` / `aclose` / `viewer_credentials`).
It is the reusable "drive the avatar mouth from an arbitrary realtime PCM source"
abstraction (decoupled from Supertonic TTS).

### Component Diagram

```
Browser                         VoiceChatHandler (one process)            External
───────                         ─────────────────────────────            ────────
 mic PCM 16k ──/ws/voice──────►  connection.audio_queue
                                       │
                                       ▼
                                 VoiceBot.ask_stream ──► GeminiLiveClient ──► Gemini Live API
                                       │  LiveVoiceResponse (audio 24k, text, tool_calls, is_complete/interrupted)
                                       ▼
                          ┌─ _send_voice_response ─┐
   response_chunk ◄───────┤ (existing: browser)    │
   (audio 24k b64)        │                        │
                          └─ VoiceAvatarSession.speak(pcm) ─► AvatarWebSocket.send_audio_frame
                                                                   │ agent.speak (base64 PCM 24k, NO resample)
                                                                   ▼
                                                            LiveAvatar media server
                                                                   │ renders lip-sync
                                                                   ▼
   avatar video+audio ◄═══════════ LiveKit room (mint_room_tokens) ◄══ avatar participant
   (browser subscribes via client_token)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `VoiceChatHandler._handle_start_session` (`voice/handler.py:666`) | extends | Start `VoiceAvatarSession` when avatar requested; add viewer creds + `avatar` block to `session_started` |
| `VoiceChatHandler._send_voice_response` (`voice/handler.py:1194`) | extends | Tee `response.audio_data` to the avatar; map `is_complete`/`is_interrupted` |
| `VoiceChatHandler._cleanup_connection` (`voice/handler.py:1301`) | extends | Tear down the avatar session |
| `WebSocketConnection` (`voice/handler.py:104`) | extends | Hold optional `avatar_session: VoiceAvatarSession | None` |
| `LiveKitRoomManager.mint_room_tokens` (`room_manager.py:78`) | reuse | Viewer (`client_token`) + avatar (`agent_token`) — Phase A pattern |
| `LiveAvatarClient` (`client.py`) | reuse | `aopen` / `create_session_token(livekit_config=)` / `start_session` / `stop_session` / `aclose` |
| `AvatarWebSocket` (`avatar_ws.py`) | reuse | `start_speaking` / `send_audio_frame` / `finish_speaking` / `interrupt` |
| `is_avatar_enabled` (`liveavatar/optin.py`) | reuse | Per-tenant opt-in gate (same as FEAT-242/243) |
| `LiveVoiceResponse` (`clients/live.py:156`) | reuse | Source of `audio_data` / `is_complete` / `is_interrupted` |

### Data Models

No new persisted models. One new helper class + additive wire fields.

```python
# parrot/integrations/liveavatar/voice_session.py  (NEW)
class VoiceAvatarSession:
    """Drives a LiveAvatar mouth from a realtime PCM (24 kHz mono 16-bit) stream."""
    @classmethod
    async def start(cls, *, agent_id: str, session_id: str,
                    tenant_id: str | None, avatar_id: str | None = None
                    ) -> "VoiceAvatarSession": ...
    @property
    def viewer_credentials(self) -> dict: ...   # {"livekit_url", "client_token", "room"}
    async def speak(self, pcm: bytes) -> None:  # tee one Gemini audio chunk
    async def finish_turn(self) -> None:        # AvatarWebSocket.finish_speaking()
    async def interrupt(self) -> None:          # AvatarWebSocket.interrupt()
    async def aclose(self) -> None:             # stop_session + ws close (idempotent)
```

```jsonc
// inbound — start_session gains an optional avatar request
{ "type": "start_session", "streaming_mode": "streaming",
  "avatar": true, "avatar_id": "<optional override>", "tenant_id": "<optional>" }

// outbound — session_started gains viewer creds + avatar status (additive)
{ "type": "session_started", "session_id": "...", "streaming_mode": "...",
  "input_format": "audio/pcm;rate=16000", "output_format": "audio/pcm;rate=24000",
  "avatar": { "active": true, "livekit_url": "wss://…", "client_token": "<JWT>",
              "room": "<session_id>", "audio": "dual" } }
// when avatar requested but failed to start (graceful degradation):
//   "avatar": { "active": false, "reason": "<short message>" }
```

### New Public Interfaces

```python
# Exported from parrot.integrations.liveavatar
from parrot.integrations.liveavatar import VoiceAvatarSession
```

---

## 3. Module Breakdown

### Module 1: `VoiceAvatarSession` helper
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/voice_session.py` (+ export in `__init__.py`)
- **Responsibility**: Encapsulate avatar session lifecycle for a realtime PCM
  source: mint room tokens, create+start the LITE `LiveAvatarClient` session with
  `livekit_config`, open `AvatarWebSocket`, await connected gate. Expose
  `speak(pcm)`, `finish_turn()`, `interrupt()`, `aclose()` (idempotent), and a
  `viewer_credentials` property. No resampling (input is 24 kHz). Reuses
  `LiveKitRoomManager`, `LiveAvatarClient`, `AvatarWebSocket`, `is_avatar_enabled`.
- **Depends on**: existing FEAT-242 code only.

### Module 2: Wire `VoiceAvatarSession` into `VoiceChatHandler`
- **Path**: `packages/ai-parrot-integrations/src/parrot/voice/handler.py`
- **Responsibility**: Add `avatar_session` to `WebSocketConnection`; in
  `_handle_start_session` start the avatar (opt-in gated) when requested and add
  viewer creds + `avatar` block to `session_started` (degrade gracefully on
  failure); in `_send_voice_response` tee `response.audio_data` →
  `avatar_session.speak`, map `is_complete` → `finish_turn`, `is_interrupted` →
  `interrupt` (all best-effort); in `_cleanup_connection` tear down. Lazy-import
  the liveavatar stack so `/ws/voice` works without the optional extra.
- **Depends on**: Module 1.

### Module 3: Tests
- **Path**: `packages/ai-parrot-integrations/tests/voice/test_voice_avatar.py`
- **Responsibility**: Unit-test `VoiceAvatarSession` (start/speak/finish/interrupt/
  aclose with mocked room manager + client + ws) and the handler wiring (tee on
  `_send_voice_response`, graceful degradation, cleanup). See §4.
- **Depends on**: Modules 1–2.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_voice_avatar_session_start` | M1 | Mints tokens, starts client session with `livekit_config`, opens ws, awaits connected; `viewer_credentials` returns `livekit_url`+`client_token`+`room` |
| `test_voice_avatar_speak_no_resample` | M1 | `speak(pcm)` forwards bytes unchanged to `AvatarWebSocket.send_audio_frame` (24 kHz, no transform) |
| `test_voice_avatar_finish_and_interrupt` | M1 | `finish_turn`→`finish_speaking`; `interrupt`→`interrupt` |
| `test_voice_avatar_aclose_idempotent` | M1 | `aclose` stops session + closes ws; safe to call twice |
| `test_start_session_avatar_active` | M2 | `start_session` with `avatar:true` adds `avatar.active=true` + creds to reply |
| `test_start_session_avatar_optin_denied` | M2 | Tenant not opted in → `avatar.active=false` with reason; voice still starts |
| `test_start_session_avatar_failure_degrades` | M2 | Avatar start raises → `avatar.active=false`; session still usable for voice |
| `test_send_voice_response_tees_audio` | M2 | `_send_voice_response` with `audio_data` calls `avatar_session.speak` AND still sends browser `response_chunk` |
| `test_send_voice_response_interrupt` | M2 | `response.is_interrupted` triggers `avatar_session.interrupt()` |
| `test_cleanup_closes_avatar` | M2 | `_cleanup_connection` calls `avatar_session.aclose()` |

### Integration Tests
| Test | Description |
|---|---|
| `test_gemini_audio_to_avatar_end_to_end` | A fake `VoiceBot.ask_stream` yielding `LiveVoiceResponse(audio_data=…, is_complete=True)` drives both a browser `response_chunk` and `AvatarWebSocket.send_audio_frame` (mocked), proving the dual path |

### Test Data / Fixtures
```python
@pytest.fixture
def fake_avatar_ws(mocker):
    ws = mocker.Mock()
    ws.start_speaking = mocker.AsyncMock()
    ws.send_audio_frame = mocker.AsyncMock()
    ws.finish_speaking = mocker.AsyncMock()
    ws.interrupt = mocker.AsyncMock()
    return ws

@pytest.fixture
def pcm_24k():
    return b"\x00\x01" * 4800  # 0.2s of 24kHz mono int16
```

---

## 5. Acceptance Criteria

- [ ] `start_session` with `avatar:true` (opted-in tenant) starts a LiveAvatar
      session and returns `avatar.active=true` with `livekit_url` + `client_token` + `room`.
- [ ] Gemini Live output audio (`LiveVoiceResponse.audio_data`, 24 kHz) is pushed
      to the avatar via `AvatarWebSocket.send_audio_frame` with **no resampling**.
- [ ] Dual audio: the browser still receives `response_chunk` audio over `/ws/voice`,
      and `session_started.avatar.audio == "dual"` signals the client to mute one.
- [ ] Barge-in: `response.is_interrupted` clears avatar audio via `interrupt()`.
- [ ] Turn end: `response.is_complete` flushes the avatar via `finish_speaking()`.
- [ ] Graceful degradation: any avatar failure (opt-in denied, start error, ws
      drop) leaves the `/ws/voice` voice conversation fully functional;
      `avatar.active=false` with a reason is returned.
- [ ] `_cleanup_connection` tears down the avatar session (no orphan LiveAvatar session).
- [ ] The FEAT-243 LiveKit worker is **not** dispatched; no Redis bridge is used.
- [ ] `/ws/voice` still works with the liveavatar extra absent (lazy import).
- [ ] All tests pass: `pytest packages/ai-parrot-integrations/tests/voice/ -v`.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**

### Verified Imports
```python
# VoiceChatHandler + VoiceBot side
from parrot.voice.handler import VoiceChatHandler            # voice/handler.py (class ~line 164)
from parrot.bots.voice import VoiceBot                       # bots/voice.py:80
from parrot.clients.live import LiveVoiceResponse            # clients/live.py:156

# LiveAvatar reuse (all exported from the package __init__)
from parrot.integrations.liveavatar import (
    AvatarWebSocket,         # __init__ re-export (avatar_ws.py:60)
    LiveAvatarClient,        # __init__ re-export (client.py:57)
    LiveAvatarConfig,        # __init__ re-export (models.py)
    LiveKitRoomManager,      # __init__ re-export (room_manager.py:66)
    AvatarSessionHandle,     # __init__ re-export (models.py)
)
from parrot.integrations.liveavatar.optin import is_avatar_enabled   # used by avatar.py:339 today
# NEW (this feature):
from parrot.integrations.liveavatar import VoiceAvatarSession         # created by M1
```

### Existing Signatures to Use
```python
# packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/avatar_ws.py
class AvatarWebSocket:
    def __init__(self, handle: AvatarSessionHandle, *, session: aiohttp.ClientSession | None = None)  # line 83
    async def __aenter__(self) -> "AvatarWebSocket"                  # line 102
    async def start_speaking(self) -> None                          # line 121 (awaits connected gate, 30s timeout)
    async def send_audio_frame(self, pcm: bytes) -> None            # line 136 (base64 agent.speak; NO resample; 24k mono 16-bit)
    async def finish_speaking(self) -> None                         # line 175 (agent.speak_end)
    async def interrupt(self) -> None                               # line 189 (agent.interrupt)

# packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/client.py
class LiveAvatarClient:
    def __init__(self, cfg: LiveAvatarConfig, ...)                  # line 57
    async def aopen(self) -> "LiveAvatarClient"                     # line 85
    async def create_session_token(self, cfg, *, livekit_config: dict | None = None) -> AvatarSessionHandle  # line 116
    async def start_session(self, handle: AvatarSessionHandle) -> dict  # line 187 (starts keep-alive loop)
    async def stop_session(self, handle: AvatarSessionHandle) -> None   # line 216 (idempotent)
    async def aclose(self) -> None                                  # line 101

# packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/room_manager.py
class LiveKitRoomManager:                                           # line 66 (reads LIVEKIT_* from env)
    def mint_room_tokens(self, room: str, identity: str) -> LiveKitRoomTokens  # line 78
    #   -> .livekit_url, .room, .client_token (subscribe-only viewer), .agent_token (publish; avatar)

# packages/ai-parrot/src/parrot/clients/live.py
@dataclass
class LiveVoiceResponse:                                            # line 156
    text: str = ""                                                  # line 164
    audio_data: Optional[bytes] = None                             # line 165 (PCM 24 kHz mono 16-bit LE)
    audio_format: str = "audio/pcm;rate=24000"                     # line 166
    is_complete: bool = False                                      # line 169
    is_interrupted: bool = False                                   # line 170
    tool_calls: List[LiveToolCall]                                 # line 173

# packages/ai-parrot-integrations/src/parrot/voice/handler.py
class WebSocketConnection:                                          # dataclass (session_id:104, streaming_mode:131, audio_buffer:141, audio_queue:144)
async def _handle_start_session(self, connection, message) -> None # line 666 (sends session_started with input/output_format ~731-732)
async def _run_voice_session(self, connection) -> None             # line 1142 (consumes audio_queue → VoiceBot.ask_stream)
async def _send_voice_response(self, connection, response) -> None # line 1194 (sends response_chunk audio_base64 ~1217-1219)
async def _cleanup_connection(self, connection) -> None            # line 1301
def setup_routes(self, app, prefix="") -> None                     # line 269 (mounts /ws/voice; stores app["voice_handler"])

# packages/ai-parrot/src/parrot/bots/voice.py
class VoiceBot(A2AEnabledMixin, BaseBot):                          # line 80
    async def ask_stream(self, audio_input, session_id=None, user_id=None, **kwargs) -> AsyncIterator[LiveVoiceResponse]  # line 353
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `VoiceAvatarSession.start` | `LiveKitRoomManager.mint_room_tokens` | method (Phase A pattern) | `room_manager.py:78` |
| `VoiceAvatarSession.start` | `LiveAvatarClient.create_session_token(livekit_config=)` + `start_session` | method | `client.py:116,187` |
| `VoiceAvatarSession.speak` | `AvatarWebSocket.send_audio_frame` | method (no resample) | `avatar_ws.py:136` |
| `VoiceAvatarSession.finish_turn` / `.interrupt` | `AvatarWebSocket.finish_speaking` / `.interrupt` | method | `avatar_ws.py:175,189` |
| handler tee | `VoiceAvatarSession.speak/finish_turn/interrupt` | best-effort calls in `_send_voice_response` | `voice/handler.py:1194` |

### Does NOT Exist (Anti-Hallucination)
- ~~`VoiceAvatarSession`~~ — created by M1.
- ~~A resampler in this path~~ — Gemini output is already 24 kHz; `send_audio_frame` does no resampling (`avatar_ws.py:18,146`). Do NOT add `_resample_pcm_int16` here (that is the Supertonic 44.1k path).
- ~~`LiveKitRoomManager.mint_browser_token` / `.dispatch_worker`~~ — those are FEAT-243 voice-native (mic-over-LiveKit + worker). NOT used here; the mic stays on `/ws/voice` and there is no worker. Use `mint_room_tokens` (viewer + avatar) instead.
- ~~`AvatarTurnSpeaker` / `AvatarVoiceProvider` / Supertonic~~ — those drive the mouth from **text → TTS**. Gemini already gives audio; bypass them and feed `AvatarWebSocket` directly.
- ~~A Redis output bridge / `RedisBroadcastForwarder`~~ — single-process; transcripts/tool_calls return over `/ws/voice` directly.
- ~~A new aiohttp route~~ — everything rides the existing `/ws/voice`.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Follow the FEAT-242 Phase A orchestrator's session lifecycle (mint tokens →
  `create_session_token(livekit_config=)` → `start_session` → `AvatarWebSocket`
  context → `start_speaking`), but **feed raw PCM** from Gemini instead of
  `synthesize_pcm_fn` text→TTS. Do NOT `async with` the client in a way that
  stops the session early (see `avatar.py:157-176` for the keep-alive caveat).
- Keep every liveavatar import **lazy inside the handler** so `/ws/voice` works
  without `ai-parrot-integrations[liveavatar]`.
- Best-effort avatar calls: wrap `speak/finish_turn/interrupt` in try/except,
  log and continue — the browser audio path must never be blocked or broken by
  an avatar hiccup (this is the whole point of dual audio).
- `async`/`await` throughout; `self.logger` for lifecycle + degradation events.

### Known Risks / Gotchas
- **Echo in dual mode.** Browser receives audio twice (raw over `/ws/voice` and
  via the avatar's LiveKit audio track). The server sends both; the **client must
  mute one**. Surface `session_started.avatar.audio == "dual"` + `active=true` so
  the client knows to mute the `/ws/voice` playback (or the avatar track). Document
  this contract clearly for the frontend.
- **Barge-in ordering.** Gemini's VAD can interrupt mid-utterance
  (`is_interrupted=True`). Must call `AvatarWebSocket.interrupt()` promptly or the
  avatar keeps speaking stale audio after the user has taken the turn.
- **Connected-gate latency.** `start_speaking` blocks up to 30 s for the avatar
  media server (`avatar_ws.py:_CONNECT_TIMEOUT`). Start the avatar concurrently
  with (not before) accepting voice input, and degrade to voice-only on timeout.
- **First-chunk sizing.** `send_audio_frame` slices the first chunk at ~400 ms;
  very small Gemini frames are fine (it sends what it has), but feeding extremely
  tiny chunks frequently increases WS overhead. Acceptable for v1; revisit if
  latency suffers.
- **Avatar minutes / sandbox.** `LIVEAVATAR_SANDBOX` defaults true; production
  avatar IDs require `LIVEAVATAR_SANDBOX=false` (see project memory). Document the
  env requirement so avatar start does not 400 in production.
- **Turn semantics.** LITE mode has no per-turn "begin" frame — only the connected
  gate. Stream `send_audio_frame` continuously and call `finish_speaking()` on
  `is_complete`; a new turn simply resumes sending. Confirm with the avatar that
  `finish_speaking` between turns does not require a fresh `start_speaking`.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `ai-parrot-integrations[liveavatar]` | existing | `AvatarWebSocket`, `LiveAvatarClient`, `LiveKitRoomManager` |

…(truncated)…
