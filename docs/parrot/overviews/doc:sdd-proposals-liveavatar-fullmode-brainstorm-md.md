---
type: Wiki Overview
title: 'Brainstorm: LiveAvatar FULL Mode — speak_text Integration (Backend)'
id: doc:sdd-proposals-liveavatar-fullmode-brainstorm-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: ai-parrot agents can talk through a LiveAvatar avatar today via two existing
relates_to:
- concept: mod:parrot.integrations.liveavatar
  rel: mentions
- concept: mod:parrot.integrations.liveavatar.client
  rel: mentions
- concept: mod:parrot.integrations.liveavatar.models
  rel: mentions
- concept: mod:parrot.integrations.liveavatar.optin
  rel: mentions
- concept: mod:parrot.integrations.liveavatar.output_bridge
  rel: mentions
- concept: mod:parrot.integrations.liveavatar.room_manager
  rel: mentions
- concept: mod:parrot.integrations.liveavatar.speakable
  rel: mentions
---

---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: LiveAvatar FULL Mode — speak_text Integration (Backend)

**Date**: 2026-06-19
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: A — Extend Existing Integration + REST Gateway

---

## Problem Statement

ai-parrot agents can talk through a LiveAvatar avatar today via two existing
modes — **LITE** (FEAT-242 Phase A: own TTS, PCM push over WebSocket) and
**voice-native** (FEAT-243 Phase C: full LiveKit Agents pipeline with
STT/VAD/TTS plugins). Both require significant infrastructure: a Supertonic
ONNX runtime or a long-lived LiveKit Agents worker, respectively.

LiveAvatar's **FULL Mode** offers a third path: LiveAvatar manages **everything**
— STT, TTS, lip-synced video — in a LiveKit room it controls. ai-parrot never
runs its own TTS or STT pipeline. The only command needed is
`avatar.speak_text {text}`, sent over a LiveKit data channel, which speaks
arbitrary text with no LLM involvement. This was validated by
`spike_q1_speaktext.py` against the live sandbox API.

This brainstorm covers the **Python backend** scope only. The SvelteKit frontend
lives in a separate repository and will be spec'd independently. The backend
must: mint FULL mode sessions, manage per-tenant config, list avatars/voices,
expose REST endpoints for the frontend, and optionally join the LiveKit room as
a participant for server-side event logging.

**Who is affected:** Backend developers wiring a new session mode into the
existing LiveAvatar integration package; ops managing per-tenant avatar/voice
config; frontend developers consuming the new REST endpoints.

## Constraints & Requirements

- **aiohttp only** — per project rules, no httpx. The existing `LiveAvatarClient`
  already uses aiohttp.
- **LiveAvatar API key stays server-side** — `X-API-KEY` never reaches the
  frontend; all session creation is proxied through the backend.
- **No OpenAI-compatible endpoint** — unlike FEAT-247 (FULL Mode custom-LLM),
  this approach uses only `avatar.speak_text`. No `/chat/completions` shim.
- **Restricted mode** — sessions are created without `context_id` and without
  `llm_configuration_id`, so the avatar's built-in LLM never fires (confirmed
  by spike).
- **Per-tenant config** — env defaults + DB overrides for `avatar_id`, `voice_id`,
  `interactivity_type`, `language`, and optionally per-tenant API keys.
- **Backend room participation** — the backend should join the LiveKit room for
  server-side event logging and transcript persistence.
- **ElevenLabs voice import deferred** — secrets management and third-party voice
  binding are out of scope for this brainstorm; to be covered in a follow-up spec.
- **ask_stream is production-ready** — per-sentence streaming TTS is viable now.
- **Existing integration must not break** — Phase A (LITE) and Phase C
  (voice-native) continue to work unchanged.

---

## Options Explored

### Option A: Extend Existing Integration + REST Gateway

Extend the existing `parrot/integrations/liveavatar/` package with FULL mode
support. Add a new `create_full_session_token()` method to `LiveAvatarClient`,
new Pydantic models for FULL mode config/responses, new REST endpoints on
`ai-parrot-server`, and a passive `FullModeRoomObserver` that joins the
LiveAvatar-managed room for event logging.

The architecture follows the same pattern as the existing Phase A `avatar.py`
handler: backend mints the session, stores the live client, returns viewer
credentials to the frontend. The frontend drives the conversation loop
(transcript → agent API → `speak_text`). The backend participates in the room
only as a passive observer for logging/analytics.

Key additions:
- `LiveAvatarClient.create_full_session_token()` — FULL mode payload
  (`mode: "FULL"`, `avatar_persona`, `interactivity_type`, no `livekit_config`).
- `FullModeConfig` — extends `LiveAvatarConfig` with `voice_id`, `language`,
  `interactivity_type`.
- `FullModeSessionHandle` — extends `AvatarSessionHandle` with `livekit_url`,
  `livekit_client_token` (from `/start` response).
- `FullModeRoomObserver` — uses `livekit-rtc` Python SDK to join the room as a
  non-publishing participant; subscribes to data channels (`agent-response`) and
  logs events + transcriptions.
- REST endpoints: `POST /api/v1/avatar/fullmode/start`,
  `POST /api/v1/avatar/fullmode/stop`.
- Avatar/voice listing: `GET /api/v1/avatar/avatars`, `GET /api/v1/avatar/voices`
  (proxy to LiveAvatar API).
- Per-tenant config store (env defaults + DB overrides).

Reuses: `SpeakableFlattener` (shared), `OutputBridge` + `StructuredOutputMessage`
(for structured output bifurcation), `optin.py` (tenant gating), handler pattern
from `avatar.py`.

**Does NOT reuse**: `LiveKitRoomManager` (FULL mode rooms are LiveAvatar-managed;
no BYO transport), `AvatarWebSocket` (LITE-only PCM bridge), `AvatarTurnSpeaker`
(LITE-only PCM synthesis pipeline).

✅ **Pros:**
- Minimal code duplication — reuses the existing client, models, and handler patterns
- Cleanest separation of concerns: backend = session lifecycle + config + logging;
  frontend = conversation loop
- No new process or worker — lighter ops footprint than Phase C
- Existing test infrastructure (`tests/integrations/liveavatar/`) extends naturally

❌ **Cons:**
- Backend room observer requires `livekit-rtc` SDK (new dependency) and a
  participant token — may require LiveKit API credentials for LiveAvatar's managed
  room (open question)
- Conversation loop logic is in the frontend (separate repo, separate spec)
- Two codebases to coordinate for the full feature

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `aiohttp` | HTTP client for LiveAvatar API | Already used, no new dep |
| `livekit-api` | Already installed (Phase A/C) | Token minting, room service |
| `livekit-rtc` | Room participant for logging | New dependency (optional extra) |
| `pydantic` | Config/response models | Already used |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/client.py` — extend `LiveAvatarClient`
- `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/models.py` — extend config/handle models
- `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/speakable.py` — `SpeakableFlattener` (shared)
- `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/output_bridge.py` — `OutputBridge`
- `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/optin.py` — `is_avatar_enabled`
- `packages/ai-parrot-server/src/parrot/handlers/avatar.py` — handler pattern and session store

---

### Option B: Backend-Driven Orchestrator (Server-Side Loop)

All of Option A, plus a `FullModeOrchestrator` that joins the room as an
**active** participant. The backend subscribes to `user.transcription` events on
the `agent-response` data channel, calls the ai-parrot agent via `bot.ask_stream()`,
runs the `SpeakableFlattener`, and sends `avatar.speak_text` commands on
`agent-control`. The frontend only renders the video stream and basic controls
(mute, PTT button, end session).

The orchestrator is a long-lived asyncio task per session, similar in spirit to
the Phase C `LiveAvatarAgent` but without the LiveKit Agents worker — it
connects directly via `livekit-rtc`.

Key additions (beyond Option A):
- `FullModeOrchestrator` — connects to room, subscribes to data channels, drives
  the `transcription → ask_stream → speak_text` loop.
- Barge-in handling: on `user.speak_started` while avatar is speaking, send
  `avatar.interrupt` and cancel the in-flight agent call.
- Per-session asyncio task management with cleanup guarantees.

✅ **Pros:**
- All conversation logic in Python — natural fit for `bot.ask_stream()` and
  existing agent infrastructure
- Frontend is trivially simple (just video + controls)
- Structured output bifurcation happens in-process (no cross-repo coordination)
- Direct `bot.ask_stream()` call avoids an HTTP round-trip through the REST API

❌ **Cons:**
- Higher latency path: user speech → LiveAvatar STT → LiveKit data channel →
  backend → ai-parrot agent → backend → LiveKit data channel → LiveAvatar TTS.
  Every hop adds latency.
- Requires the backend to maintain a persistent LiveKit room connection per
  session (memory + connection overhead)
- More complex lifecycle management (long-lived tasks, cancellation, reconnects)
- Tighter coupling between the integration layer and the agent/bot layer
- Requires solving the room token problem (see Open Questions)

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `aiohttp` | HTTP client for LiveAvatar API | Already used |
| `livekit-api` | Token minting | Already installed |
| `livekit-rtc` | Active room participant | New dependency (required, not optional) |
| `pydantic` | Models | Already used |

🔗 **Existing Code to Reuse:**
- Everything from Option A, plus:
- `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/orchestrator.py` — pattern reference for the Phase A orchestrator
- `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/speaker.py` — queue-based sentence speaker pattern
- `packages/ai-parrot-server/src/parrot/handlers/agent.py` — `AgentTalk` pattern for resolving bots

---

### Option C: Thin Session Proxy (No Room Participant)

Minimal backend: only session lifecycle management (create/start/stop), config
store, and avatar/voice listing. No room participant at all. Server-side logging
is deferred — transcripts are retrieved after session end via LiveAvatar's
`GET /v1/sessions/{id}/transcript` endpoint.

The backend's role is purely administrative: mint sessions, return credentials,
stop sessions, manage config. All conversation logic and data channel interaction
happens in the frontend.

Key additions:
- `LiveAvatarClient.create_full_session_token()` — same as Option A.
- `FullModeConfig` — same as Option A.
- REST endpoints for session lifecycle and config.
- `GET /api/v1/avatar/session/{id}/transcript` — proxy to LiveAvatar transcript API.
- No `livekit-rtc` dependency.

✅ **Pros:**
- Simplest possible backend — fastest to ship
- No new LiveKit SDK dependency beyond what's already installed
- No persistent room connections to manage
- Clean separation: backend = API gateway + config; frontend = all real-time logic
- Avoids the room token problem entirely

❌ **Cons:**
- No real-time server-side event logging (only post-session transcript retrieval)
- Cannot react to session events server-side (e.g., `session.stopped` with
  `NO_CREDITS` won't trigger server-side alerts in real time)
- Frontend must handle all real-time concerns alone
- Transcripts are only available after session end, not during

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `aiohttp` | HTTP client for LiveAvatar API | Already used |
| `pydantic` | Models | Already used |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/client.py` — extend `LiveAvatarClient`
- `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/models.py` — extend models
- `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/optin.py` — tenant gating
- `packages/ai-parrot-server/src/parrot/handlers/avatar.py` — handler pattern

---

## Recommendation

**Option A** is recommended because it provides the right balance between
capability and complexity:

- It reuses the existing integration infrastructure heavily, minimizing new code
  and maintaining consistency with the Phase A/C patterns.
- The passive room observer for logging satisfies the server-side observability
  requirement without taking on the full orchestration burden of Option B.
- The frontend-driven loop (as the proposal recommends) minimizes latency — user
  speech goes directly from the LiveAvatar room to the frontend, which is already
  connected to the data channel. Adding a backend hop (Option B) would increase
  TTFB for every turn.
- Unlike Option C, it provides real-time server-side visibility into session
  events, enabling operational alerting (credit exhaustion, session drops) and
  live transcript persistence.
- The `livekit-rtc` dependency is optional (gated behind an extra) and only
  needed when room observation is enabled — deployments that don't need
  server-side logging can skip it entirely.

The main tradeoff is that conversation logic lives in the frontend (separate repo).
This is acceptable because: (a) the frontend already handles data channel
events for video rendering, so adding `speak_text` commands is incremental;
(b) the agent API call (`POST /api/v1/agents/chat/{agent_id}`) is already a
well-tested REST interface that the frontend consumes today.

---

## Feature Description

### User-Facing Behavior

From the operator's perspective:
1. Configure a FULL mode avatar per tenant: choose an avatar (stock or custom from
   LiveAvatar dashboard), select a voice (stock library or avatar clone), set
   default language and interactivity type (conversational or push-to-talk).
2. Enable FULL mode for a tenant via the opt-in gate (env or DB flag).

From the end user's perspective:
1. Open an AgentChat session with avatar mode enabled.
2. The frontend calls `POST /api/v1/avatar/fullmode/start` — the backend mints a
   FULL mode session and returns `livekit_url` + `livekit_client_token`.
3. The frontend joins the LiveKit room and renders the avatar video.
4. The user speaks; LiveAvatar's STT produces a `user.transcription` event.
5. The frontend sends the transcript to ai-parrot via the existing agent chat API.
6. ai-parrot responds with text + optional structured outputs.
7. The frontend sends the flattened text as `avatar.speak_text` commands (per
   sentence) on the `agent-control` data channel. Structured outputs render in
   the AgentChat canvas.
8. The avatar speaks the text with lip-synced video.
9. On session end, the frontend calls `POST /api/v1/avatar/fullmode/stop`.

### Internal Behavior

**Session lifecycle (backend):**
```
Frontend                Backend                         LiveAvatar API
   │                       │                                 │
   │ POST /fullmode/start  │                                 │
   │ {session_id,          │                                 │
   │  tenant_id,           │                                 │
   │  agent_id}            │                                 │
   │──────────────────────>│                                 │
   │                       │  POST /v1/sessions/token        │
   │                       │  {mode:"FULL", avatar_id,       │
   │                       │   avatar_persona:{voice_id,     │
   │                       │   language}, no context_id}      │
   │                       │────────────────────────────────>│
   │                       │  {session_id, session_token}    │
   │                       │<────────────────────────────────│
   │                       │                                 │
   │                       │  POST /v1/sessions/start        │
   │                       │  (Bearer session_token)         │
   │                       │────────────────────────────────>│
   │                       │  {livekit_url,                  │
   │                       │   livekit_client_token}         │
   │                       │<────────────────────────────────│
   │                       │                                 │
   │                       │  [Start room observer task]     │
   │                       │                                 │
   │ {livekit_url,         │                                 │
   │  livekit_client_token,│                                 │
   │  session_id}          │                                 │
   │<──────────────────────│                                 │
   │                       │                                 │
   │  [Join room, render   │  [Keep-alive loop running]      │
   │   video, drive loop]  │  [Observer logs events]         │
   │                       │                                 │
```

**Room observer (backend, optional):**
The `FullModeRoomObserver` connects to the LiveKit room using `livekit-rtc` as
a non-publishing participant. It subscribes to `agent-response` data channel
messages and logs: `user.transcription`, `avatar.speak_started`,
`avatar.speak_ended`, `avatar.transcription`, `session.stopped`. Events are
persisted to the conversation memory store (Redis) keyed by `session_id`.

**Per-tenant config resolution:**
1. Check DB for tenant-specific overrides (`avatar_id`, `voice_id`, `language`,
   `interactivity_type`, `api_key`).
2. Fall back to environment variables (`LIVEAVATAR_API_KEY`,
   `LIVEAVATAR_AVATAR_ID`, `LIVEAVATAR_VOICE_ID`, `LIVEAVATAR_LANGUAGE`).
3. Merge: DB values override env defaults; missing DB values use env.

### Edge Cases & Error Handling

- **LiveAvatar API failure during session creation**: Return 502 to the frontend
  with a descriptive error. No session is registered.
- **Session expires (idle timeout / max duration / no credits)**: The room
  observer receives `session.stopped {end_reason}` and publishes an event to
  the AgentChat UI channel so the frontend can show an appropriate message.
- **Observer connection failure**: Logged and skipped — session continues without
  server-side logging. The frontend is unaffected.
- **Concurrent /stop and session.stopped**: Both paths are idempotent.
  `stop_session` is safe to call on an already-closed session (404 → success).
- **Tenant has no avatar config**: Return 400 with guidance to configure avatar.
- **LiveAvatar sandbox mode**: Respect `is_sandbox` flag; sandbox sessions have
  lower `max_session_duration` (60s observed in spike).

---

## Capabilities

### New Capabilities
- `liveavatar-fullmode-session`: FULL mode session lifecycle (create/start/stop)
  with restricted mode (no built-in LLM)
- `liveavatar-fullmode-config`: Per-tenant FULL mode configuration (avatar, voice,
  language, interactivity type, API key overrides)
- `liveavatar-fullmode-observer`: Passive room participant for server-side event
  logging and transcript persistence
- `liveavatar-provisioning-api`: Avatar and voice listing endpoints (read-only
  proxy to LiveAvatar API)

### Modified Capabilities
- `liveavatar-client` (FEAT-242): `LiveAvatarClient` gains `create_full_session_token()`.
- `liveavatar-models` (FEAT-242): New config/handle models for FULL mode.
- `liveavatar-optin` (FEAT-242): Opt-in gate extended for FULL mode (new env var
  or flag variant).

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/integrations/liveavatar/client.py` | extends | Add `create_full_session_token()` for FULL mode |
| `parrot/integrations/liveavatar/models.py` | extends | New `FullModeConfig`, `FullModeSessionHandle` |
| `parrot/integrations/liveavatar/__init__.py` | extends | Re-export new public symbols |
| `parrot/handlers/avatar.py` | extends | New `/fullmode/start` and `/fullmode/stop` endpoints |
| `parrot/integrations/liveavatar/optin.py` | extends | FULL mode opt-in variant |
| `parrot/integrations/liveavatar/speakable.py` | reused unchanged | `SpeakableFlattener` (shared) |
| `parrot/integrations/liveavatar/output_bridge.py` | reused unchanged | Structured output bridge |
| `pyproject.toml` (ai-parrot-integrations) | modifies | New optional `[liveavatar-fullmode]` extra for `livekit-rtc` |
| Frontend (separate repo) | depends on | New REST endpoints consumed by frontend |

---

## Code Context

### User-Provided Code
```python
# Source: sdd/proposals/spec-liveavatar-fullmode-speaktext.md (§5.4)
# Verified event envelope shape from spike_q1_speaktext.py
{
    "event_id": "<uuid>",
    "event_type": "avatar.speak_text",
    "session_id": "<uuid>",
    "source_event_id": None,
    "text": "<arbitrary text>"
}
```

### Verified Codebase References

#### Classes & Signatures
```python
# From packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/client.py:37
class LiveAvatarClient:
    def __init__(self, cfg: LiveAvatarConfig, *, session: Optional[aiohttp.ClientSession] = None) -> None:  # line 57
    async def __aenter__(self) -> "LiveAvatarClient":  # line 72
    async def __aexit__(self, exc_type, exc, tb) -> None:  # line 76
    async def aopen(self) -> "LiveAvatarClient":  # line 85
    async def aclose(self) -> None:  # line 101
    async def create_session_token(self, cfg: LiveAvatarConfig, *, livekit_config: Optional[Dict[str, Any]] = None) -> AvatarSessionHandle:  # line 116
    async def start_session(self, handle: AvatarSessionHandle) -> Dict[str, Any]:  # line 187
    async def stop_session(self, handle: AvatarSessionHandle) -> None:  # line 216
    async def keep_alive(self, handle: AvatarSessionHandle) -> None:  # line 258

# From packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/models.py:18
class LiveAvatarConfig(BaseModel):
    api_key: str  # line 32
    avatar_id: str  # line 33
    base_url: str = "https://api.liveavatar.com"  # line 34
    is_sandbox: bool = True  # line 38
    max_session_duration: Optional[int] = None  # line 42
    quality: Optional[str] = None  # line 48
    encoding: Optional[str] = None  # line 52

# From packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/models.py:86
class AvatarSessionHandle(BaseModel):
    session_id: str  # line 101
    liveavatar_session_id: str  # line 104
    session_token: str  # line 107
    ws_url: str  # line 110  — LITE only; FULL mode has no ws_url
    tenant_id: Optional[str] = None  # line 117
    agent_name: str  # line 120

# From packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/speakable.py:79
class SpeakableFlattener:
    def __init__(self) -> None:  # line 97
    def feed(self, chunk: str) -> List[str]:  # line 100
    def flush(self) -> List[str]:  # line 116

# From packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/optin.py:58
def is_avatar_enabled(*, tenant_id: Optional[str], agent_name: Optional[str] = None) -> bool:  # line 58

# From packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/output_bridge.py:25
class OutputBridge:
    def __init__(self, socket_manager: Any) -> None:  # line 35
    async def publish(self, msg: StructuredOutputMessage) -> None:  # line 39

# From packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/livekit_agent/models.py:42
class StructuredOutputMessage(BaseModel):
    type: str  # line 57
    session_id: str  # line 61
    payload: Dict[str, Any]  # line 65
    turn_id: Optional[str] = None  # line 69

# From packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/room_manager.py:47
class LiveKitRoomManager:
    def __init__(self, *, url: Optional[str] = None, api_key: Optional[str] = None, api_secret: Optional[str] = None) -> None:  # line 66
    def mint_room_tokens(self, room: str, identity: str) -> LiveKitRoomTokens:  # line 78
    def mint_browser_token(self, room: str, identity: str, *, audio_only: bool = True) -> str:  # line 138
```

#### Verified Imports
```python
# These imports have been confirmed to work:
from parrot.integrations.liveavatar.client import LiveAvatarClient  # __init__.py:10
from parrot.integrations.liveavatar.models import AvatarSessionHandle, LiveAvatarConfig, LiveKitRoomTokens  # __init__.py:11
from parrot.integrations.liveavatar.speakable import SpeakableFlattener  # __init__.py:14
from parrot.integrations.liveavatar.output_bridge import OutputBridge  # (direct import)
from parrot.integrations.liveavatar.optin import is_avatar_enabled  # (direct import)
from parrot.integrations.liveavatar.livekit_agent.models import StructuredOutputMessage  # output_bridge.py:18

…(truncated)…
