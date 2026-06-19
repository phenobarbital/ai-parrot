---
type: feature
base_branch: dev
---

# Feature Specification: LiveAvatar FULL Mode — speak_text Integration (Backend)

**Feature ID**: FEAT-248
**Date**: 2026-06-19
**Author**: Jesus Lara
**Status**: approved
**Target version**: (next minor)

> Input brainstorm: `sdd/proposals/liveavatar-fullmode.brainstorm.md` (Option A).
> Source proposal: `sdd/proposals/spec-liveavatar-fullmode-speaktext.md`.
> **Parallel to** FEAT-242 (Phase A, LITE), FEAT-243 (Phase C, voice-native),
> and FEAT-247 (FULL Mode custom-LLM). Does NOT modify or supersede them.

---

## 1. Motivation & Business Requirements

### Problem Statement

ai-parrot agents can talk through a LiveAvatar avatar today via two existing
modes — **LITE** (FEAT-242: own TTS via Supertonic, PCM push over WebSocket)
and **voice-native** (FEAT-243: full LiveKit Agents pipeline with STT/VAD/TTS
plugins). Both require significant infrastructure: a Supertonic ONNX runtime
or a long-lived LiveKit Agents worker, respectively.

LiveAvatar's **FULL Mode** offers a third path: LiveAvatar manages everything —
STT, TTS, lip-synced video — in a LiveKit room it controls. ai-parrot never
runs its own TTS or STT pipeline. The only command needed is
`avatar.speak_text {text}`, sent over a LiveKit data channel, which speaks
arbitrary text with no LLM involvement. This was validated by
`spike_q1_speaktext.py` against the live sandbox API (Q1 resolved).

This spec covers the **Python backend** only. The SvelteKit frontend lives
in a separate repository and will be spec'd independently.

### Goals
- Mint **FULL Mode** sessions (with `avatar.speak_text` as the only output
  command; no built-in LLM, no `llm_configuration_id`, no `context_id`).
- Expose REST endpoints so the frontend can start/stop FULL mode sessions and
  receive LiveKit room credentials.
- Provide read-only avatar and voice listing endpoints (proxy to LiveAvatar API).
- Support **per-tenant configuration** with env defaults + DB overrides for
  `avatar_id`, `voice_id`, `language`, `interactivity_type`, and optionally
  per-tenant `api_key`.
- Join the LiveKit room as a **passive backend participant** for server-side
  event logging and transcript persistence.
- Reuse existing integration infrastructure (`SpeakableFlattener`, `OutputBridge`,
  `optin.py`, handler patterns) wherever possible.

### Non-Goals (explicitly out of scope)
- Building an OpenAI-compatible API / `AbstractClient` wrapper around ai-parrot
  (that is FEAT-247).
- Running own TTS / PCM plumbing (that is FEAT-242 Phase A / LITE mode).
- Running a LiveKit Agents worker (that is FEAT-243 Phase C).
- ElevenLabs voice import (secrets management + third-party voice binding) —
  deferred to a follow-up spec.
- Frontend implementation (separate repo, separate spec).
- Programmatic creation of custom avatars (not exposed by LiveAvatar API).

---

## 2. Architectural Design

### Overview

The backend acts as a **session lifecycle gateway + passive room observer**.
The frontend (separate repo) drives the conversation loop:
`user.transcription → agent API → avatar.speak_text`.

The backend:
1. Mints a FULL mode session via the LiveAvatar API (restricted mode —
   no `context_id`, no `llm_configuration_id`).
2. Returns `livekit_url` + `livekit_client_token` to the frontend.
3. Optionally joins the LiveKit room as a non-publishing participant to log
   data-channel events (`user.transcription`, `avatar.speak_started/ended`,
   `session.stopped`) and persist transcripts.
4. Manages per-tenant config (avatar, voice, language, interactivity type).
5. Proxies avatar/voice listing from the LiveAvatar API.

Session creation payload (FULL mode, restricted):
```json
{
  "mode": "FULL",
  "avatar_id": "<avatar_id>",
  "interactivity_type": "CONVERSATIONAL",
  "avatar_persona": {
    "voice_id": "<voice_id>",
    "language": "en"
  },
  "video_settings": { "quality": "high", "encoding": "H264" },
  "max_session_duration": 600
}
```
Critically: `llm_configuration_id` and `context_id` are **omitted**, which
puts the avatar in restricted mode — it will never auto-respond with its
built-in LLM (Q1 confirmed by spike).

### Component Diagram

```
Frontend (separate repo)           Backend (this spec)           LiveAvatar API
        │                                │                            │
        │  POST /fullmode/start          │                            │
        │  {session_id, tenant_id,       │                            │
        │   agent_id}                    │                            │
        │──────────────────────────────>│                            │
        │                                │  resolve_tenant_config()  │
        │                                │  ──────────────────────>  │
        │                                │                            │
        │                                │  POST /v1/sessions/token  │
        │                                │  {mode:"FULL", ...}       │
        │                                │──────────────────────────>│
        │                                │  {session_id, token}      │
        │                                │<──────────────────────────│
        │                                │                            │
        │                                │  POST /v1/sessions/start  │
        │                                │──────────────────────────>│
        │                                │  {livekit_url,            │
        │                                │   livekit_client_token}   │
        │                                │<──────────────────────────│
        │                                │                            │
        │                                │  [Start observer task]    │
        │                                │  [Start keep-alive loop]  │
        │                                │                            │
        │  {livekit_url,                 │                            │
        │   livekit_client_token,        │                            │
        │   session_id}                  │                            │
        │<──────────────────────────────│                            │
        │                                │                            │
        │  [join room, render video,     │  [observer logs events]   │
        │   drive speak_text loop]       │  [keep-alive pings]       │
        │                                │                            │
        │  POST /fullmode/stop           │                            │
        │──────────────────────────────>│                            │
        │                                │  POST /v1/sessions/stop   │
        │                                │──────────────────────────>│
        │  204                           │                            │
        │<──────────────────────────────│                            │
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `LiveAvatarClient` (client.py) | extends | Add `create_full_session_token()` method |
| `LiveAvatarConfig` (models.py) | extends | Subclass as `FullModeConfig` with voice/language/interactivity |
| `AvatarSessionHandle` (models.py) | extends | Subclass as `FullModeSessionHandle` with livekit fields |
| `SpeakableFlattener` (speakable.py) | reused unchanged | Frontend uses it; backend may expose it as a utility endpoint |
| `OutputBridge` (output_bridge.py) | reused unchanged | Observer can publish session events to AgentChat UI |
| `StructuredOutputMessage` (livekit_agent/models.py) | reused unchanged | Event envelope for the bridge |
| `is_avatar_enabled` (optin.py) | extends | Add FULL mode variant env var |
| `_start_avatar_session` (handlers/avatar.py) | pattern reference | Follow same handler pattern for FULL mode endpoints |
| `AVATAR_SESSIONS_KEY` (handlers/avatar.py) | extends | Add `FULLMODE_SESSIONS_KEY` for FULL mode session store |

### Data Models

```python
class FullModeConfig(LiveAvatarConfig):
    """FULL mode configuration (extends LITE config)."""
    voice_id: Optional[str] = None
    language: str = "en"
    interactivity_type: str = "CONVERSATIONAL"  # or "PUSH_TO_TALK"


class FullModeSessionHandle(AvatarSessionHandle):
    """FULL mode session handle (extends LITE handle)."""
    livekit_url: str = ""
    livekit_client_token: str = ""
    # ws_url from parent is unused in FULL mode (LITE-only)


class TenantAvatarConfig(BaseModel):
    """Per-tenant avatar configuration (DB override layer)."""
    tenant_id: str
    avatar_id: Optional[str] = None
    voice_id: Optional[str] = None
    language: Optional[str] = None
    interactivity_type: Optional[str] = None
    api_key: Optional[str] = None  # per-tenant API key override
    fullmode_enabled: bool = False
```

### New Public Interfaces

```python
# New method on LiveAvatarClient
async def create_full_session_token(
    self,
    cfg: FullModeConfig,
) -> FullModeSessionHandle:
    """Create a FULL mode session (restricted — no LLM, no context)."""
    ...

# New methods on LiveAvatarClient for provisioning
async def list_avatars(self, cfg: LiveAvatarConfig) -> List[Dict[str, Any]]:
    """List available avatars (stock + user)."""
    ...

async def list_voices(self, cfg: LiveAvatarConfig) -> List[Dict[str, Any]]:
    """List available voices."""
    ...

async def get_session_transcript(
    self, cfg: LiveAvatarConfig, session_id: str
) -> Dict[str, Any]:
    """Retrieve server-side transcript for a completed session."""
    ...
```

```python
# New REST endpoints
POST /api/v1/avatar/fullmode/{agent_id}/start
POST /api/v1/avatar/fullmode/{agent_id}/stop
GET  /api/v1/avatar/avatars
GET  /api/v1/avatar/voices
GET  /api/v1/avatar/session/{session_id}/transcript
```

---

## 3. Module Breakdown

### Module 1: FULL Mode Data Models
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/models.py`
- **Responsibility**: Add `FullModeConfig`, `FullModeSessionHandle`, `TenantAvatarConfig`
  Pydantic models. `FullModeConfig` extends `LiveAvatarConfig` with `voice_id`,
  `language`, `interactivity_type`. `FullModeSessionHandle` extends
  `AvatarSessionHandle` with `livekit_url` and `livekit_client_token`.
- **Depends on**: None (existing models only)

### Module 2: FULL Mode Client Extension
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/client.py`
- **Responsibility**: Add `create_full_session_token()` to `LiveAvatarClient`.
  Sends `mode: "FULL"` with `avatar_persona` (voice_id, language),
  `interactivity_type`, `video_settings`, `max_session_duration`. Omits
  `llm_configuration_id` and `context_id` (restricted mode). Also add
  `list_avatars()`, `list_voices()`, `get_session_transcript()` GET methods.
- **Depends on**: Module 1 (new models)

### Module 3: Per-Tenant Config Resolver
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/tenant_config.py` (new file)
- **Responsibility**: `resolve_fullmode_config(tenant_id) -> FullModeConfig`.
  Loads env defaults, then overlays any per-tenant DB overrides. Returns a
  fully resolved `FullModeConfig` ready for session creation.
  Interim implementation: env-only (matching the `optin.py` pattern).
  DB override layer is gated by Q-tenant-config-store.
- **Depends on**: Module 1

### Module 4: FULL Mode REST Handler
- **Path**: `packages/ai-parrot-server/src/parrot/handlers/avatar_fullmode.py` (new file)
- **Responsibility**: Two authenticated endpoints:
  - `POST /api/v1/avatar/fullmode/{agent_id}/start` — resolve tenant config,
    opt-in gate, create FULL session, start it, store live client, start
    keep-alive, optionally start room observer, return viewer credentials.
  - `POST /api/v1/avatar/fullmode/{agent_id}/stop` — stop session, cancel
    keep-alive, stop observer, close client. Idempotent.
  Follows the exact pattern of `handlers/avatar.py` (`_start_avatar_session` /
  `_stop_avatar_session`) but for FULL mode.
- **Depends on**: Module 2, Module 3

### Module 5: Avatar/Voice Listing Handler
- **Path**: `packages/ai-parrot-server/src/parrot/handlers/avatar_fullmode.py` (same file)
- **Responsibility**: Read-only proxy endpoints:
  - `GET /api/v1/avatar/avatars` — list public + user avatars.
  - `GET /api/v1/avatar/voices` — list available voices.
  - `GET /api/v1/avatar/session/{session_id}/transcript` — retrieve transcript.
  All authenticated, all use `LiveAvatarClient` with `X-API-KEY` auth.
- **Depends on**: Module 2

### Module 6: Room Observer (Optional)
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/fullmode_observer.py` (new file)
- **Responsibility**: `FullModeRoomObserver` — connects to the LiveKit room
  using `livekit-rtc` as a non-publishing participant. Subscribes to
  `agent-response` data channel. Logs events: `user.transcription`,
  `avatar.speak_started`, `avatar.speak_ended`, `avatar.transcription`,
  `session.stopped`. Persists transcript entries. Publishes `session.stopped`
  events to the AgentChat UI channel via `OutputBridge`.
  **Gated by Q-room-token** — if the backend cannot obtain a participant
  token for LiveAvatar's managed room, this module falls back to post-session
  transcript retrieval via `get_session_transcript()`.
- **Depends on**: Module 1, Module 2, Q-room-token resolution

### Module 7: Package Wiring + Opt-in Extension
- **Path**: Multiple files:
  - `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/__init__.py` — re-export new symbols
  - `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/optin.py` — add `LIVEAVATAR_FULLMODE_ENABLED_TENANTS` env var
  - `packages/ai-parrot-integrations/pyproject.toml` — optional `[liveavatar-fullmode]` extra for `livekit-rtc`
  - `packages/ai-parrot-server` route registration for the new handler
- **Responsibility**: Wire all modules together: package exports, opt-in gating
  for FULL mode, optional dependency declaration, route registration.
- **Depends on**: Modules 1–6

### Module 8: Tests
- **Path**: `packages/ai-parrot-integrations/tests/integrations/liveavatar/`
- **Responsibility**: Unit tests for all new modules. See §4.
- **Depends on**: Modules 1–7

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_fullmode_config_defaults` | M1 | `FullModeConfig` has correct defaults (language="en", interactivity_type="CONVERSATIONAL") |
| `test_fullmode_config_inherits_lite` | M1 | `FullModeConfig` inherits all `LiveAvatarConfig` fields |
| `test_fullmode_session_handle_fields` | M1 | `FullModeSessionHandle` has `livekit_url` + `livekit_client_token` |
| `test_create_full_session_token_payload` | M2 | Correct payload sent to `/v1/sessions/token` (mode=FULL, no context_id, no llm_configuration_id) |
| `test_create_full_session_token_restricted` | M2 | Verify `context_id` and `llm_configuration_id` are absent from payload |
| `test_start_session_populates_livekit_fields` | M2 | `/start` response populates `livekit_url` + `livekit_client_token` on the handle |
| `test_list_avatars` | M2 | GET request to `/v1/avatars` with correct X-API-KEY header |
| `test_list_voices` | M2 | GET request to `/v1/voices` with correct X-API-KEY header |
| `test_resolve_config_env_only` | M3 | Env defaults resolve to a valid `FullModeConfig` |
| `test_resolve_config_tenant_override` | M3 | Per-tenant DB values override env defaults |
| `test_fullmode_start_endpoint` | M4 | Happy path: returns `livekit_url`, `livekit_client_token`, `session_id` |
| `test_fullmode_start_optin_denied` | M4 | Returns 403 when tenant is not opted in |
| `test_fullmode_start_missing_config` | M4 | Returns 503 when LIVEAVATAR env vars are missing |
| `test_fullmode_stop_idempotent` | M4 | Returns 204 for unknown session_id |
| `test_fullmode_optin_env` | M7 | `LIVEAVATAR_FULLMODE_ENABLED_TENANTS` env var gating works |

### Integration Tests

| Test | Description |
|---|---|
| `test_fullmode_session_lifecycle` | Create + start + keep-alive + stop against LiveAvatar sandbox API (requires `LIVEAVATAR_API_KEY`) |
| `test_fullmode_restricted_mode_no_llm` | Verify avatar does not auto-respond when session has no `context_id` (sandbox) |

### Test Data / Fixtures
```python
@pytest.fixture
def fullmode_config():
    return FullModeConfig(
        api_key="test-key",
        avatar_id="test-avatar",
        voice_id="test-voice",
        language="en",
        interactivity_type="CONVERSATIONAL",
        is_sandbox=True,
    )

@pytest.fixture
def fullmode_session_handle():
    return FullModeSessionHandle(
        session_id="test-session",
        liveavatar_session_id="la-session-id",
        session_token="test-token",
        ws_url="",  # unused in FULL mode
        agent_name="test-agent",
        livekit_url="wss://test.livekit.cloud",
        livekit_client_token="eyJ...",
    )
```

---

## 5. Acceptance Criteria

- [ ] A FULL mode session can be created and started via `POST /api/v1/avatar/fullmode/{agent_id}/start`, returning `livekit_url`, `livekit_client_token`, and `session_id` to the frontend. The `api_key`, `session_token`, and any server-side secrets are NEVER returned.
- [ ] The session is created in **restricted mode** — no `context_id`, no `llm_configuration_id` in the payload — so the avatar's built-in LLM never fires.
- [ ] `POST /api/v1/avatar/fullmode/{agent_id}/stop` tears down the session (stop_session + cancel keep-alive + close client). Idempotent (returns 204 for unknown sessions).
- [ ] Keep-alive pings run automatically while the session is active (< 5 min interval).
- [ ] `max_session_duration` is set on session creation as a safety net for abandoned sessions.
- [ ] Per-tenant configuration resolves correctly: env defaults are used when no DB override exists; per-tenant DB values override env defaults.
- [ ] Opt-in gating: `POST /fullmode/start` returns 403 when the tenant is not enabled for FULL mode.
- [ ] `GET /api/v1/avatar/avatars` and `GET /api/v1/avatar/voices` return data from the LiveAvatar API (authenticated, X-API-KEY server-side).
- [ ] All new Pydantic models validate correctly and `FullModeConfig` / `FullModeSessionHandle` properly inherit from their LITE parents.
- [ ] Existing Phase A (LITE) and Phase C (voice-native) endpoints are unaffected — no breaking changes.
- [ ] All unit tests pass (`pytest packages/ai-parrot-integrations/tests/integrations/liveavatar/ -v`)
- [ ] No secrets are exposed in any client-facing response.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.

### Verified Imports
```python
# These imports have been confirmed to work:
from parrot.integrations.liveavatar.client import LiveAvatarClient  # __init__.py:10
from parrot.integrations.liveavatar.models import (
    AvatarSessionHandle,   # __init__.py:11
    LiveAvatarConfig,      # __init__.py:11
    LiveKitRoomTokens,     # __init__.py:11
)
from parrot.integrations.liveavatar.speakable import SpeakableFlattener  # __init__.py:14
from parrot.integrations.liveavatar.output_bridge import OutputBridge  # direct import
from parrot.integrations.liveavatar.optin import is_avatar_enabled  # direct import
from parrot.integrations.liveavatar.livekit_agent.models import StructuredOutputMessage  # output_bridge.py:18
from parrot.integrations.liveavatar.room_manager import LiveKitRoomManager  # __init__.py:13
```

### Existing Class Signatures
```python
# packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/client.py
class LiveAvatarClient:  # line 37
    def __init__(self, cfg: LiveAvatarConfig, *, session: Optional[aiohttp.ClientSession] = None) -> None:  # line 57
    async def __aenter__(self) -> "LiveAvatarClient":  # line 72
    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:  # line 76
    async def aopen(self) -> "LiveAvatarClient":  # line 85
    async def aclose(self) -> None:  # line 101
    async def create_session_token(self, cfg: LiveAvatarConfig, *, livekit_config: Optional[Dict[str, Any]] = None) -> AvatarSessionHandle:  # line 116
    async def start_session(self, handle: AvatarSessionHandle) -> Dict[str, Any]:  # line 187
    async def stop_session(self, handle: AvatarSessionHandle) -> None:  # line 216
    async def keep_alive(self, handle: AvatarSessionHandle) -> None:  # line 258
    # INTERNAL:
    def _api_key_headers(self, cfg: LiveAvatarConfig) -> Dict[str, str]:  # line 283
    def _bearer_headers(self, handle: AvatarSessionHandle) -> Dict[str, str]:  # line 297
    async def _post(self, url: str, *, headers: Dict[str, str], json: Dict[str, Any]) -> Dict[str, Any]:  # line 311
    def _start_keep_alive(self, handle: AvatarSessionHandle) -> None:  # line 344
    async def _keep_alive_loop(self, handle: AvatarSessionHandle) -> None:  # line 382
    _KEEP_ALIVE_INTERVAL = 280  # line 34

# packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/models.py
class LiveAvatarConfig(BaseModel):  # line 18
    api_key: str  # line 32
    avatar_id: str  # line 33
    base_url: str = "https://api.liveavatar.com"  # line 34
    is_sandbox: bool = True  # line 38
    max_session_duration: Optional[int] = None  # line 42
    quality: Optional[str] = None  # line 48
    encoding: Optional[str] = None  # line 52

class LiveKitRoomTokens(BaseModel):  # line 58
    livekit_url: str  # line 72
    room: str  # line 73
    client_token: str  # line 74
    agent_token: str  # line 78

class AvatarSessionHandle(BaseModel):  # line 86
    session_id: str  # line 101
    liveavatar_session_id: str  # line 104
    session_token: str  # line 107
    ws_url: str  # line 110
    tenant_id: Optional[str] = None  # line 117
    agent_name: str  # line 120

# packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/speakable.py
class SpeakableFlattener:  # line 79
    def __init__(self) -> None:  # line 97
    def feed(self, chunk: str) -> List[str]:  # line 100
    def flush(self) -> List[str]:  # line 116

# packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/optin.py
def is_avatar_enabled(*, tenant_id: Optional[str], agent_name: Optional[str] = None) -> bool:  # line 58

# packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/output_bridge.py
class OutputBridge:  # line 25
    def __init__(self, socket_manager: Any) -> None:  # line 35
    async def publish(self, msg: StructuredOutputMessage) -> None:  # line 39

# packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/livekit_agent/models.py
class StructuredOutputMessage(BaseModel):  # line 42
    type: str  # line 57
    session_id: str  # line 61
    payload: Dict[str, Any]  # line 65
    turn_id: Optional[str] = None  # line 69
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `FullModeConfig` | `LiveAvatarConfig` | inheritance (Pydantic subclass) | `models.py:18` |
| `FullModeSessionHandle` | `AvatarSessionHandle` | inheritance (Pydantic subclass) | `models.py:86` |
| `create_full_session_token()` | `LiveAvatarClient._post()` | method call | `client.py:311` |
| `create_full_session_token()` | `LiveAvatarClient._api_key_headers()` | method call | `client.py:283` |
| `start handler` | `LiveAvatarClient.start_session()` | method call | `client.py:187` |
| `start handler` | `is_avatar_enabled()` | function call | `optin.py:58` |
| `stop handler` | `LiveAvatarClient.stop_session()` | method call | `client.py:216` |
| `observer` | `OutputBridge.publish()` | method call | `output_bridge.py:39` |

### Handler Pattern Reference
```python
# packages/ai-parrot-server/src/parrot/handlers/avatar.py
# Key constants and patterns to follow:
AVATAR_SESSIONS_KEY = "avatar_sessions"  # line 52
AVATAR_VOICE_SESSIONS_KEY = "avatar_voice_sessions"  # line 57

# _start_avatar_session (line 77) pattern:
#   1. Lazy-import liveavatar stack (try/except ImportError → 503)
#   2. Extract agent_id from match_info, session_id + tenant_id from body
#   3. Opt-in gate: is_avatar_enabled() → 403
#   4. Build config from env
#   5. Open client via aopen() (NOT async-with — ownership transfers to session store)
#   6. create_session_token() + start_session()
#   7. Store {client, handle} in app[SESSIONS_KEY][session_id]
#   8. Return viewer credentials ONLY (never agent_token/ws_url/session_token)

# _stop_avatar_session (line 223) pattern:
#   1. Extract session_id from body
#   2. Pop record from session store
#   3. client.stop_session(handle) in try/finally client.aclose()
#   4. Return 204 (idempotent)
```

### Does NOT Exist (Anti-Hallucination)
- ~~`LiveAvatarClient.create_full_session_token()`~~ — does not exist yet; this spec creates it
- ~~`FullModeConfig`~~ — does not exist; `LiveAvatarConfig` has no `voice_id`, `language`, or `interactivity_type`
- ~~`FullModeSessionHandle`~~ — does not exist; `AvatarSessionHandle.ws_url` is LITE-only; no `livekit_url`/`livekit_client_token` fields
- ~~`TenantAvatarConfig`~~ — does not exist; no per-tenant config model
- ~~`LiveAvatarClient.list_avatars()`~~ — does not exist; no GET methods on the client
- ~~`LiveAvatarClient.list_voices()`~~ — same
- ~~`LiveAvatarClient.get_session_transcript()`~~ — same
- ~~`LiveAvatarClient._get()`~~ — no GET helper exists; only `_post()` (line 311)
- ~~`FullModeRoomObserver`~~ — does not exist; no `livekit-rtc` room participant code
- ~~`handlers/avatar_fullmode.py`~~ — does not exist; FULL mode handler is new
- ~~`tenant_config.py`~~ — does not exist; per-tenant config resolver is new
- ~~`fullmode_observer.py`~~ — does not exist; observer module is new
- ~~`FULLMODE_SESSIONS_KEY`~~ — does not exist; needs to be created in the new handler
- ~~`chatWithAgent`~~ — frontend-only term from the proposal; does not exist in Python backend
- ~~`AgentChatRequest`/`AgentChatResponse`~~ — do not exist in Python backend; the handler uses `AIMessage`
- ~~`AbstractSpeechInput`~~ — proposal term for frontend; does not exist in Python backend

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Follow `_start_avatar_session` / `_stop_avatar_session` in `handlers/avatar.py`
  as the exact pattern for the FULL mode handler (lazy imports, opt-in gate,
  session store, viewer-only response).
- Use `aopen()` (not `async with`) for the client — ownership transfers to the
  session store; `aclose()` is called by the stop handler.
- Use `LiveAvatarClient._api_key_headers()` for X-API-KEY auth and
  `_bearer_headers()` for session_token auth (same as LITE).
- All Pydantic models use `BaseModel` with `Field(...)` descriptions.
- All new async code uses `self.logger` (never print).
- Environment variables follow naming convention: `LIVEAVATAR_*`.

### Configuration Reference

| Env Variable | Required | Default | Purpose |
|---|---|---|---|
| `LIVEAVATAR_API_KEY` | Yes | — | LiveAvatar API key |
| `LIVEAVATAR_AVATAR_ID` | Yes | — | Default avatar ID |
| `LIVEAVATAR_VOICE_ID` | No | None (uses avatar default) | Default voice ID |
| `LIVEAVATAR_LANGUAGE` | No | `"en"` | Default language |
| `LIVEAVATAR_INTERACTIVITY_TYPE` | No | `"CONVERSATIONAL"` | Default interactivity |
| `LIVEAVATAR_BASE_URL` | No | `https://api.liveavatar.com` | API base URL |
| `LIVEAVATAR_SANDBOX` | No | `"true"` | Sandbox mode flag |
| `LIVEAVATAR_MAX_SESSION_DURATION` | No | None | Safety-net session cap (seconds) |
| `LIVEAVATAR_FULLMODE_ENABLED_TENANTS` | No | empty (default-deny) | Comma-separated tenant allowlist; `*` = all |

### Known Risks / Gotchas
- **Q-room-token (blocker for Module 6):** The backend may not be able to obtain
  a LiveKit participant token for LiveAvatar's managed room. If unresolvable,
  Module 6 (observer) falls back to post-session transcript retrieval, which
  loses real-time logging. Mitigation: design Module 6 as optional from the start.
- **Sandbox session caps:** Sandbox sessions return `max_session_duration: 60`
  regardless of the requested value. Tests must account for this.
- **LiveAvatar credit consumption:** FULL mode sessions consume STT + TTS + video
  credits per minute. Abandoned sessions burn credits — `max_session_duration` and
  keep-alive discipline are essential.
- **`livekit-rtc` dependency:** Only needed for Module 6 (observer). Must be
  gated behind an optional extra to avoid bloating the base install.
- **`AvatarSessionHandle.ws_url` inherited but unused:** `FullModeSessionHandle`
  inherits `ws_url` from the parent but it is empty/unused in FULL mode (LITE
  only). This is harmless but may confuse readers — document it clearly.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `aiohttp` | (existing) | HTTP client for LiveAvatar API calls |
| `pydantic` | (existing) | Data models |
| `livekit-api` | (existing) | Already installed for Phase A/C |
| `livekit-rtc` | `>=0.10` | Room participant for Module 6 (optional extra) |

---

## 8. Open Questions

- [ ] **Q-room-token** — Can the backend obtain a LiveKit participant token for
  LiveAvatar's FULL mode room? The `/start` response returns only
  `livekit_client_token` (for the browser). The backend would need its own token
  — either from LiveAvatar (undocumented) or by minting one with our own LiveKit
  API credentials (requires the same LiveKit project). If not possible, Module 6
  falls back to post-session transcript retrieval. — *Owner: Jesús*
- [ ] **Q-tenant-config-store** — Which database table/model should hold per-tenant
  FULL mode configuration? Candidates: (a) existing programs table with a JSON
  column, (b) a dedicated `avatar_config` table, (c) NavConfig keys. — *Owner: Jesús*
- [ ] **Q-keep-alive-full** — Does `POST /v1/sessions/keep-alive` work for FULL mode
  sessions, or is the keep-alive handled internally by the LiveAvatar-managed room?
  If HTTP keep-alive works, the existing `_keep_alive_loop` pattern applies
  unchanged. — *Owner: Jesús*
- [ ] **Q-concurrent-data-channel** — In FULL mode, if the backend joins as a
  participant and subscribes to `agent-response`, does the browser also receive
  the same events? (Expected yes — LiveKit data channels are pub/sub.) — *Owner: Jesús*
- [ ] **Q-web-sdk-vs-livekit** — Does `@heygen/liveavatar-web-sdk` expose
  `agent-control`/`agent-response` event send/subscribe, or must the frontend use
  `livekit-client` data channels directly? (Frontend scope, but informs backend
  response shape.) — *Owner: Jesús*
- [x] **Q1** — `avatar.speak_text` works in restricted mode (no `context_id`).
  — *Resolved in brainstorm*: Confirmed by `spike_q1_speaktext.py`. Arbitrary
  `avatar.speak_text` is spoken normally; `avatar.speak_started` →
  `avatar.transcription` → `avatar.speak_ended` all fired. The "pre-set phrases"
  wording does NOT restrict `speak_text`.
- [x] **Q2** — ai-parrot exposes `ask_stream` for per-sentence streaming.
  — *Resolved in brainstorm*: Production-ready.

---

## Worktree Strategy

- **Isolation**: `per-spec` — all tasks run sequentially in one worktree.
- **Rationale**: The module dependency chain (M1 models → M2 client → M3 config
  → M4 handler → M5 listing → M6 observer → M7 wiring → M8 tests) means most
  tasks need the previous one. The independent modules (M3 config, M5 listing)
  are small enough that the overhead of separate worktrees isn't justified.
- **Cross-feature dependencies**: None — this spec only extends existing modules
  (no breaking changes to Phase A or Phase C). Can be developed in parallel with
  any other in-flight feature.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-06-19 | Jesus Lara | Initial draft from brainstorm Option A |
