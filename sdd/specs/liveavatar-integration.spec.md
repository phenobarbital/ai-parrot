---
type: feature
base_branch: dev
---

# Feature Specification: LiveAvatar Integration (talking avatar for AgentChat)

**Feature ID**: FEAT-242
**Date**: 2026-06-18
**Author**: Jesus Lara
**Status**: draft
**Target version**: TBD

> Input brainstorm: `sdd/proposals/liveavatar-integration.brainstorm.md`
> (Recommended Option: A — Phase 1 → C — Phase 2, both on BYO + LiveKit Cloud).

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

`AgentChat` answers users with text, structured data, charts and canvas, but has no
**spoken, lip-synced face**. We want to give the agent a **talking avatar** that
verbalizes its responses, increasing presence and accessibility for voice-first
scenarios (kiosks, concierge, sales demos).

The avatar is a **voice/video presentation layer, NOT a second brain**. ai-parrot
already owns the agent, tools, structured outputs and persistence. LiveAvatar (HeyGen)
in **LITE Mode** provides only the real-time video + lip-sync; STT/LLM/TTS are ours.
LITE Mode has no "speak text" command — it plays **PCM 16-bit, 24 kHz, mono** pushed
over a WebSocket, so we must produce that PCM ourselves.

### Goals
- Give AgentChat a lip-synced talking avatar that speaks the agent's response aloud.
- **Phase A** — Avatar as the "mouth": ai-parrot resolves the full turn; its plain
  (speakable) text is synthesized with Supertonic (PCM 24 kHz mono 16-bit) and pushed by
  the **backend** to the avatar; structured outputs keep rendering in the UI as today.
- **Phase C** — Voice-native hybrid: keep the LiveKit Agents voice pipeline (STT/VAD/
  turn-detection/TTS/avatar) but override `llm_node` so ai-parrot is the brain; bifurcate
  plain text → spoken, structured outputs → AgentChat UI.
- Unified media transport for both phases: **BYO + LiveKit Cloud** (one room/token layer,
  no migration between phases).
- TTS pluggable: Supertonic default in Phase A; Kokoro and others addable without touching
  the orchestrator.
- Per-program/tenant **opt-in**; one avatar session = one `tenant_id` + one `agent_name`
  + one `session_id`.
- Robust session lifecycle: `keep_alive` < 5 min, guaranteed `stop_session` on every exit
  path, `max_session_duration` safety net.

### Non-Goals (explicitly out of scope)
- **FULL Mode + Custom LLM** (LiveAvatar runs the whole pipeline, calls an OpenAI-compatible
  ai-parrot endpoint) was rejected as the primary path — see
  `sdd/proposals/liveavatar-integration.brainstorm.md` Option B. It remains a documented
  fallback only.
- **Self-hosted LiveKit SFU** — out of scope; we use LiveKit Cloud (managed).
- Replacing or redefining the existing `AgentVoiceTalk` / streaming / WS handlers — they are
  extended, not rewritten.
- Avatar appearance/branding customization beyond selecting an `avatar_id`.

---

## 2. Architectural Design

### Overview

We build a talking-avatar presentation layer in two phases sharing one media transport
(**BYO + LiveKit Cloud**).

**Phase A — Avatar as "mouth".** ai-parrot resolves the entire turn through the existing
path (text typed, browser STT, or `AgentVoiceTalk` STT). A new backend **avatar session
orchestrator** opens the LiveAvatar session (LITE, with `livekit_config` so the avatar joins
*our* LiveKit Cloud room), consumes `ask_stream()`, segments the stream into sentences,
flattens markdown to speakable text incrementally, synthesizes each sentence with Supertonic
(`synthesize_pcm()` → PCM int16 LE mono 24 kHz — the exact LITE format, no resampling), and
pushes PCM frames to the avatar over the ported `AvatarWebSocket`. The browser joins the same
room with a `client_token` and renders `<video>`/`<audio>`; structured outputs (charts/data/
canvas) keep flowing to the AgentChat UI unchanged. The avatar agent token and the avatar WS
stay server-side.

**Phase C — Voice-native hybrid.** The LiveKit Agents pipeline (STT/VAD/turn-detection/TTS/
avatar) runs in a long-lived worker that is a participant of the **same** LiveKit Cloud room.
`LiveAvatarAgent` overrides `llm_node` to call ai-parrot (`ask_stream`) instead of LiveKit's
LLM; it `yield`s plain text → LiveKit TTS → avatar, and publishes structured outputs to the
AgentChat UI channel via `UserSocketManager.broadcast_to_channel()` keyed by `session_id`.

A `LiveKitRoomManager` (`livekit-api`) mints the room + client/agent tokens for both phases.
A `speakable-text flattener` (new) strips markdown/code/tables and segments sentences for
streaming TTS. The whole avatar layer is opt-in per program/tenant.

### Component Diagram

```
Phase A (Avatar as "mouth"):

[Browser] text / STT ──→ AgentVoiceTalk (avatar-mode flag)
                              │
                              ▼
                     AvatarSessionOrchestrator
        ┌───────────────────────┼─────────────────────────────┐
        ▼                       ▼                               ▼
  LiveAvatarClient        ask_stream() ──→ SpeakableFlattener   LiveKitRoomManager
  (create/start/stop/        (chunks)        + sentence seg          (livekit-api:
   keep-alive)                              │                     room + tokens)
        │                                   ▼
        │                          VoiceSynthesizer (Supertonic
        │                          synthesize_pcm → PCM 24k mono 16-bit)
        │                                   │
        ▼                                   ▼
  LiveAvatar media-server  ◄──  AvatarWebSocket (agent.speak / speak_end / interrupt)
        │                                                       structured outputs
        ▼                                                              │
   our LiveKit Cloud room  ──────────────────────────────────────────┐│
        │                                                             ││
        ▼                                                             ▼▼
   [Browser viewer] <video>/<audio>                    AgentChat UI (existing WS)

Phase C (Voice-native hybrid):

[Browser] mic ──→ LiveKit room ──→ AgentSession(STT/VAD/turn) ──→ llm_node override
                                                                       │
                                          ai-parrot ask_stream() ◄─────┘
                                          │                    │
                                  plain text (yield)     structured outputs
                                          │                    │
                                   LiveKit TTS ──→ avatar   broadcast_to_channel(session_id)
                                                                │
                                                                ▼
                                                          AgentChat UI
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AgentVoiceTalk` (`agent_voice.py:57`) | extends | Add avatar-mode flag; reuse STT-in/TTS-out pattern around unchanged text dispatch. |
| `VoiceSynthesizer` / Supertonic (`synthesizer.py:53`, `supertonic_inference.py:528`) | uses | `synthesize_pcm()` → PCM 24 kHz mono 16-bit; add Kokoro via `_get_backend()` factory. |
| `BaseBot.ask_stream` (`base.py:1456`) | uses | Per-sentence streaming source for avatar speech / `llm_node`. |
| `UserSocketManager.broadcast_to_channel` (`user.py:357`) | uses | Phase C structured-output bridge to AgentChat UI keyed by `session_id`. |
| `StreamHandler` (`stream.py:197`) | uses | Existing streaming surface; reference for the avatar speech consumer. |
| `web_hitl.py` (`ws_channel_id` / `current_web_session`) | uses | Channel-routing pattern for the output bridge. |
| `AIMessage` (`responses.py:72`) | uses | Final stream sentinel; carries structured outputs / `tool_calls` / `artifact_id`. |
| AgentChat frontend (Svelte 5) | new | LiveKit viewer component, opt-in aware, shares `session_id`. |
| Deployment | new | Long-lived stateful process (spawn-per-session or warm pool). |

### Data Models

```python
# New Pydantic models (parrot/integrations/liveavatar/models.py — to create)

class LiveAvatarConfig(BaseModel):
    api_key: str                      # from LIVEAVATAR_API_KEY (env)
    avatar_id: str                    # from LIVEAVATAR_AVATAR_ID (env)
    base_url: str = "https://api.liveavatar.com"
    is_sandbox: bool = True
    max_session_duration: Optional[int] = None
    quality: str = "..."              # video_settings.quality — confirm enum at impl
    encoding: str = "..."             # video_settings.encoding — confirm enum at impl

class LiveKitRoomTokens(BaseModel):
    livekit_url: str                  # wss://<project>.livekit.cloud
    room: str
    client_token: str                 # browser viewer
    agent_token: str                  # avatar participant (server-side only)

class AvatarSessionHandle(BaseModel):
    session_id: str                   # ai-parrot session_id (shared with AgentChat)
    liveavatar_session_id: str
    session_token: str                # Bearer for start_session
    ws_url: str                       # avatar media-server WS
    tenant_id: Optional[str] = None
    agent_name: str

class SpeakablePiece(BaseModel):
    kind: Literal["speakable", "structured"]
    text: Optional[str] = None        # for kind="speakable"
    payload: Optional[dict] = None    # for kind="structured" (charts/data/canvas)
```

### New Public Interfaces

```python
# parrot/integrations/liveavatar/ (to create) — signatures illustrative, confirm at impl

class LiveAvatarClient:               # ported from starter src/liveavatar_client.py → aiohttp
    async def create_session_token(self, cfg: LiveAvatarConfig,
                                    livekit_config: Optional[dict] = None) -> AvatarSessionHandle: ...
    async def start_session(self, handle: AvatarSessionHandle) -> dict: ...
    async def stop_session(self, handle: AvatarSessionHandle) -> None: ...
    async def keep_alive(self, handle: AvatarSessionHandle) -> None: ...

class AvatarWebSocket:                # ported from starter src/avatar_ws.py → aiohttp
    async def start_speaking(self) -> None: ...
    async def send_audio_frame(self, pcm: bytes) -> None: ...   # PCM 24k mono 16-bit
    async def finish_speaking(self) -> None: ...
    async def interrupt(self) -> None: ...

class LiveKitRoomManager:             # livekit-api
    def mint_room_tokens(self, room: str, identity: str) -> LiveKitRoomTokens: ...

class SpeakableFlattener:             # new
    def feed(self, chunk: str) -> list[str]: ...   # incremental → complete sentences
    def flush(self) -> list[str]: ...

class AvatarSessionOrchestrator:      # new — Phase A glue
    async def run(self, agent_name: str, session_id: str,
                  tenant_id: Optional[str]) -> AvatarSessionHandle: ...
```

---

## 3. Module Breakdown

> One module per brainstorm capability as a starting point. Phase A = Modules 1–7;
> Phase C = Modules 8–9.

### Module 1: LiveAvatar HTTP client + session lifecycle
- **Path**: `parrot/integrations/liveavatar/client.py`
- **Responsibility**: `create_session_token`/`start`/`stop`/`keep-alive`/`transcript` over
  `aiohttp`; auth header `X-API-KEY` (and `Bearer session_token` for `start_session`); keep-alive
  background task; guaranteed teardown. (capability `liveavatar-session-lifecycle`)
- **Depends on**: existing `aiohttp` patterns.

### Module 2: Avatar audio bridge (WebSocket PCM push)
- **Path**: `parrot/integrations/liveavatar/avatar_ws.py`
- **Responsibility**: port `AvatarWebSocket` — resample→24 kHz, mono mixdown, 400 ms first
  chunk then 1 s, ≤1 MB/packet, reconnect+replay, `agent.speak`/`speak_end`/`interrupt`; wait for
  `session.state_updated == "connected"`. (capability `liveavatar-audio-bridge`)
- **Depends on**: Module 1.

### Module 3: LiveKit room manager (BYO Cloud)
- **Path**: `parrot/integrations/liveavatar/room_manager.py`
- **Responsibility**: mint room + client/agent tokens via `livekit-api`; env
  `LIVEKIT_URL/API_KEY/API_SECRET`. (capability `livekit-room-manager`)
- **Depends on**: none (new dep `livekit-api`).

### Module 4: Speakable-text flattener + sentence segmenter
- **Path**: `parrot/integrations/liveavatar/speakable.py`
- **Responsibility**: markdown→speakable plaintext (strip code fences/tables/md syntax),
  incremental sentence segmentation for streaming TTS. (capability `speakable-text-flattener`)
- **Depends on**: none.

### Module 5: Avatar session orchestrator
- **Path**: `parrot/integrations/liveavatar/orchestrator.py`
- **Responsibility**: glue — open LiveAvatar session (with `livekit_config`), consume
  `ask_stream()`, run flattener+segmenter, `VoiceSynthesizer` per sentence → PCM → `AvatarWebSocket`;
  lifecycle (keep_alive/stop). (capability `avatar-audio-bridge`/orchestration)
- **Depends on**: Modules 1, 2, 3, 4; `VoiceSynthesizer`, `ask_stream`.

### Module 6: Avatar session endpoint + avatar-mode flag
- **Path**: `packages/ai-parrot-server/src/parrot/handlers/agent_voice.py` (extend) + new route
- **Responsibility**: start/stop an avatar session; a flag enabling avatar mode on the chat/voice
  path; return viewer `livekit_url` + `client_token`. (capability `avatar-session-endpoint`)
- **Depends on**: Module 5; `AgentVoiceTalk`.

### Module 7: Per-tenant opt-in gating
- **Path**: `parrot/integrations/liveavatar/optin.py` (+ wiring into the endpoint)
- **Responsibility**: resolve per-program/tenant opt-in; inject `tenant_id` into ai-parrot calls
  and (Phase C) LiveKit job metadata. (capability `avatar-tenant-optin`)
- **Depends on**: Module 6; existing auth/program pattern.

### Module 8 (Phase C): LiveKit Agents worker + `llm_node` ai-parrot bridge
- **Path**: `parrot/integrations/liveavatar/livekit_agent/` (agent.py, pipeline.py, worker.py)
- **Responsibility**: adapt starter; override `llm_node` to call ai-parrot (`ask_stream`),
  `yield` speakable text, inject `tenant_id`/`agent_name`/`session_id` via job metadata.
  (capability `llm-node-aiparrot-bridge`)
- **Depends on**: Modules 3, 4; `ask_stream`; new dep `livekit-agents` (pinned).

### Module 9 (Phase C): Structured-output → AgentChat UI bridge
- **Path**: `parrot/integrations/liveavatar/output_bridge.py`
- **Responsibility**: define message contract; publish structured outputs to the AgentChat UI
  channel via `broadcast_to_channel()` keyed by `session_id`. (capability `llm-node-aiparrot-bridge`)
- **Depends on**: Module 8; `UserSocketManager.broadcast_to_channel`.

### Module 10: Frontend LiveKit viewer (Svelte 5)
- **Path**: AgentChat frontend (separate repo/package — coordinate)
- **Responsibility**: embed `livekit-client` viewer in AgentChat, opt-in aware, share
  `session_id`. (capability `avatar-viewer-frontend`)
- **Depends on**: Module 6.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_liveavatar_client_auth_headers` | M1 | `X-API-KEY` on most calls; `Bearer session_token` on `start_session` |
| `test_session_lifecycle_stop_on_error` | M1 | `stop_session` runs on every exit path (incl. exceptions) |
| `test_keep_alive_loop_under_5min` | M1 | keep-alive scheduled < 5 min inactivity timeout |
| `test_avatar_ws_chunking` | M2 | first chunk ~400 ms, then ~1 s; ≤1 MB/packet |
| `test_avatar_ws_waits_for_connected` | M2 | no commands before `session.state_updated == "connected"` |
| `test_avatar_ws_reconnect_replay` | M2 | reconnect replays `start` |
| `test_room_manager_mints_tokens` | M3 | valid client/agent tokens for a room (env-driven) |
| `test_flattener_strips_markdown` | M4 | code fences/tables/md syntax removed from speakable text |
| `test_sentence_segmenter_incremental` | M4 | partial chunks accumulate into complete sentences |
| `test_orchestrator_streams_per_sentence` | M5 | `ask_stream` chunks → PCM frames per sentence |
| `test_supertonic_pcm_format` | M5 | output is PCM int16 LE mono 24 kHz (no resampling) |
| `test_avatar_mode_flag_optin` | M6/M7 | avatar mode only when tenant opt-in enabled |
| `test_endpoint_returns_viewer_token` | M6 | response carries `livekit_url` + `client_token`, not agent token |
| `test_llm_node_yields_speakable` | M8 | `llm_node` yields plain str from ai-parrot stream |
| `test_output_bridge_contract` | M9 | structured outputs published with the agreed schema to `session_id` channel |

### Integration Tests
| Test | Description |
|---|---|
| `test_phase_a_end_to_end_sandbox` | text in → ai-parrot → Supertonic PCM → avatar speaks (LiveAvatar `is_sandbox=true`) |
| `test_phase_a_barge_in` | `agent.interrupt` clears scheduled audio |
| `test_phase_c_voice_roundtrip_sandbox` | mic → STT → `llm_node`→ai-parrot → TTS → avatar; outputs to UI |
| `test_session_teardown_on_disconnect` | abandoned session closes via `max_session_duration` backstop |

### Test Data / Fixtures
```python
@pytest.fixture
def liveavatar_config():
    return LiveAvatarConfig(api_key="test", avatar_id="test", is_sandbox=True)

@pytest.fixture
def fake_avatar_ws():
    # records send_audio_frame calls; asserts chunking + connected-gate
    ...
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] **Phase A** unit tests pass (`pytest packages/.../tests/integrations/liveavatar -v`)
- [ ] **Phase A** integration test passes end-to-end in LiveAvatar sandbox (`is_sandbox=true`)
- [ ] Supertonic output verified as **PCM 16-bit, 24 kHz, mono** with no resampling
- [ ] Avatar WS never sends commands before `session.state_updated == "connected"`
- [ ] PCM chunking respects ~400 ms first chunk, ~1 s thereafter, ≤1 MB/packet
- [ ] `keep_alive` sent < 5 min inactivity; `stop_session` runs on every exit path
- [ ] `max_session_duration` set as a safety net on `create_session_token`
- [ ] Transport is **BYO + LiveKit Cloud**: `LiveKitRoomManager` mints tokens; avatar joins our room
- [ ] Avatar mode is **opt-in per program/tenant**; disabled tenants see unchanged text-only AgentChat
- [ ] TTS is pluggable: adding Kokoro needs only a new `AbstractTTSBackend` subclass + `_get_backend()` elif
- [ ] Backend orchestrates the PCM push; the agent/avatar token and avatar WS never reach the client
- [ ] Per-sentence streaming reduces TTFB (avatar starts speaking before the full answer)
- [ ] Speakable flattener strips markdown/code/tables before TTS
- [ ] Secrets (`LIVEAVATAR_API_KEY`, `LIVEKIT_API_KEY/SECRET/URL`, `LIVEAVATAR_AVATAR_ID`) read from env only
- [ ] **Phase C** (when implemented): `llm_node` override calls ai-parrot; structured outputs bridged to AgentChat UI via `broadcast_to_channel()` keyed by `session_id`
- [ ] No breaking changes to existing `AgentVoiceTalk` / streaming / WS public API

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** Verified in this session (2026-06-18) by reading
> the source. Implementation agents MUST NOT reference imports/attributes/methods not listed
> here without verifying first.

### Verified Imports
```python
from parrot.voice.tts.synthesizer import VoiceSynthesizer            # ai-parrot-integrations
from parrot.voice.tts.backend import AbstractTTSBackend              # ai-parrot-integrations
from parrot.voice.transcriber.transcriber import VoiceTranscriber    # ai-parrot-integrations
# AgentVoiceTalk / AgentTalk live in the ai-parrot-server handlers (HTTP layer).
```

### Existing Class Signatures
```python
# packages/ai-parrot-server/src/parrot/handlers/agent.py
class AgentTalk(BaseView):                                  # line 100
    async def post(self): ...                               # line 1523 (POST /api/v1/agents/chat/{agent_id})
    async def _handle_stream_response(self, bot, query, ...) -> web.StreamResponse: ...  # line 2365 (chunked)

# packages/ai-parrot-server/src/parrot/handlers/agent_voice.py
class AgentVoiceTalk(AgentTalk):                            # line 57 (POST /api/v1/agents/voice/{agent_id})
    async def handle_upload(self): ...                      # line 84  (STT-in)
    async def post(self): ...                               # line 268 (TTS-out, attaches audio_base64)
    # per-request selectors: tts_backend, stt_backend, audio_format

# packages/ai-parrot-integrations/src/parrot/voice/tts/supertonic_backend.py
_SAMPLE_RATE = 24000   # line 41
_CHANNELS = 1          # line 42
_SAMPLE_WIDTH = 2      # line 43  (16-bit)

# packages/ai-parrot-integrations/src/parrot/voice/tts/supertonic_inference.py
class SupertonicPipeline:                                   # ~line 335
    def synthesize_pcm(self, text, *, voice=None, language=None,
                       silence_duration=0.3) -> bytes: ...  # line 528 — raw PCM int16 LE mono 24 kHz

# packages/ai-parrot-integrations/src/parrot/voice/tts/synthesizer.py
class VoiceSynthesizer:                                     # line 22
    def _get_backend(self) -> AbstractTTSBackend: ...       # line 53 — string-dispatch factory (add "kokoro" elif)

# packages/ai-parrot-integrations/src/parrot/voice/tts/backend.py
class AbstractTTSBackend(ABC):                              # line 17
    async def synthesize(self, text, *, voice=None,
                         mime_format="audio/ogg", language=None) -> "SynthesisResult": ...

# packages/ai-parrot/src/parrot/bots/base.py
async def ask_stream(self, question, ...) -> AsyncIterator[Union[str, AIMessage]]: ...  # line 1456
# abstract decl: packages/ai-parrot/src/parrot/bots/abstract.py:3740

# packages/ai-parrot/src/parrot/models/responses.py
class AIMessage(BaseModel):                                 # line 72
    response: Optional[str]; output: Any; data: Optional[Any]; code: Optional[str]
    tool_calls: List[ToolCall]; output_mode: OutputMode; artifact_id: Optional[str]
    @property
    def to_text(self) -> str: ...                           # line 249

# packages/ai-parrot-server/src/parrot/handlers/stream.py
class StreamHandler(BaseHandler):                           # line 11
    async def stream_websocket(self, request) -> web.WebSocketResponse: ...  # line 197 (GET /bots/{bot_id}/stream/ws)

# packages/ai-parrot-server/src/parrot/handlers/user.py
class UserSocketManager(WebSocketManager):                  # line 27
    async def broadcast_to_channel(self, channel, message, exclude_ws=None): ...  # line 357
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `AvatarSessionOrchestrator` | `BaseBot.ask_stream()` | async iteration of chunks | `base.py:1456` |
| `AvatarSessionOrchestrator` | `VoiceSynthesizer`/Supertonic | `synthesize_pcm()` | `supertonic_inference.py:528` |
| `AvatarSessionEndpoint` | `AgentVoiceTalk` | extend handler + avatar-mode flag | `agent_voice.py:57` |
| Kokoro backend (future) | `VoiceSynthesizer._get_backend()` | new `elif` + `AbstractTTSBackend` subclass | `synthesizer.py:53` |
| Output bridge (Phase C) | `UserSocketManager.broadcast_to_channel()` | publish keyed by `session_id` | `user.py:357` |
| Output bridge (Phase C) | `ws_channel_id` / `current_web_session` | channel routing pattern | `web_hitl.py` |

### Does NOT Exist (Anti-Hallucination)
- ~~any `livekit` / `liveavatar` / `webrtc` / `aiortc` / `avatar` code~~ — **ZERO** matches in
  `packages/*/src` (confirmed 2026-06-18). Clean slate; everything LiveKit/LiveAvatar is new.
- ~~a markdown→speakable-plaintext flattener~~ — does not exist (only `_flatten_adf` for Atlassian
  ADF in `bots/github_reviewer.py`, and `strip_html_text` in `utils/jsonld_extractors.py`). Build it (P2).
- ~~`tenant_id` threaded through the chat endpoint~~ — the chat path threads `user_id`/`session_id`
  only; `tenant` appears in crew Redis persistence, not in `AgentTalk`. Opt-in needs explicit wiring.
- ~~a LiveKit `llm_node` override or a structured-output→UI bridge~~ — neither exists (P4/P5).
- ~~partial-token emission over `ws_channel_id` from `/agents/chat`~~ — streaming is via
  `ask_stream()` over **HTTP chunked** and the **`StreamHandler` WebSocket** (`/bots/{id}/stream/ws`),
  NOT over the `/ws/userinfo` channel.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Async-first throughout (`aiohttp`, never `requests`/`httpx`); port starter's httpx/websockets to `aiohttp`.
- Pydantic models for all structured data (`LiveAvatarConfig`, `LiveKitRoomTokens`, `AvatarSessionHandle`, `SpeakablePiece`).
- `self.logger` for logging; no `print`.
- New code under `parrot/integrations/liveavatar/` (aligns with `parrot/integrations/` convention).
- Add `livekit-api` (Phase A) and `livekit-agents`+plugins (Phase C) as an **optional extra** in `pyproject.toml`.
- Reuse the `AbstractTTSBackend` + `_get_backend()` factory to keep TTS pluggable (Kokoro later).
- Secrets via env only: `LIVEAVATAR_API_KEY`, `LIVEAVATAR_AVATAR_ID`, `LIVEAVATAR_BASE_URL` (opt),
  `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`.

### Known Risks / Gotchas
- **Commands before `connected`** → await `session.state_updated == "connected"` before sending.
- **Inactivity timeout (5 min) / abandoned session** → periodic `keep_alive` + `max_session_duration` backstop; `stop_session` in `finally`/shutdown.
- **WS disconnect** → reconnect with `start` replay (port from starter `avatar_ws.py`).
- **PCM limits** → ≤1 MB/packet, ~1 s chunks, ~400 ms first chunk for TTFB.
- **Markdown read aloud** → flattener must strip code fences/tables/md syntax.
- **Long `tool_calls` (Phase C)** → filler utterance / "thinking" state to avoid dead air.
- **TTS failure** → graceful degradation to text-only (mirror `AgentVoiceTalk`).
- **Cost** → Phase A uses LiveKit room + LiveAvatar minutes only (no LiveKit inference); Phase C adds LiveKit inference (STT/TTS) billed to LiveKit Cloud credits; use `is_sandbox=true` in dev.
- **Deployment** → long-lived stateful process; spawn-per-session vs warm pool unresolved (Q-deploy).
- **`livekit-agents` version** → pin and validate the exact `llm_node` signature before Phase C (P5).

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `livekit-api` | `>=0.x` (pin at impl) | Mint LiveKit Cloud room + client/agent tokens (BYO) — Phase A |
| `livekit-agents` | `~=1.5` (pin at impl) | Voice pipeline + `llm_node` override — Phase C |
| `livekit-plugins-*` | pin at impl | Deepgram STT, Cartesia TTS, Silero VAD, MultilingualModel turn-detection — Phase C |
| `aiohttp` | existing | LiveAvatar HTTP client + avatar WebSocket (project standard) |
| Supertonic (existing) | existing | TTS text→PCM 24 kHz mono 16-bit (Phase A) |
| `livekit-client` (JS) | pin at impl | Browser viewer (frontend) |

---

## 8. Open Questions

> Resolved items (from brainstorm) are `[x]`; unresolved are `[ ]`.

- [x] P1 — Does ai-parrot stream partial tokens? — *Resolved in brainstorm*: Yes, via `ask_stream()` over HTTP-chunked and the `StreamHandler` WebSocket (`/bots/{id}/stream/ws`), NOT over the `/ws/userinfo` channel. Avatar speech (Phase A) consumes `ask_stream()` directly.
- [x] P2 — Is there a "speakable text" field/flattener? — *Resolved in brainstorm*: No. Build a markdown→plaintext flattener (incremental + sentence segmentation). `AIMessage.to_text` exists but does not strip markdown.
- [x] P3 — Any avatar integration code today? — *Resolved in brainstorm*: None. Clean slate.
- [x] Media transport — *Resolved in brainstorm*: BYO + LiveKit Cloud for both phases (no migration; `lk agent deploy` applies in Phase C).
- [x] TTS choice — *Resolved in brainstorm*: Supertonic in Phase A (pluggable, Kokoro later); LiveKit inference in Phase C.
- [x] Tenant model — *Resolved in brainstorm*: Avatar is opt-in per program/tenant.
- [x] Orchestration locus — *Resolved in brainstorm*: Backend orchestrates the PCM push; frontend is viewer-only.
- [x] Streaming granularity — *Resolved in brainstorm*: Per-sentence via `ask_stream` to lower TTFB.
- [ ] P4 — Phase C: define the structured-outputs → AgentChat UI bridge contract (message schema + channel; likely `broadcast_to_channel()` keyed by `session_id`). — *Owner: Jesús / Claude Code*
- [ ] P5 — Pin `livekit-agents` version and validate the exact `llm_node` signature before Phase C. — *Owner: Jesús*
- [ ] P6 — Confirm Supertonic streaming/chunked behavior (per-sentence latency on target hardware) and whether a 400 ms first chunk is achievable. — *Owner: Claude Code*
- [ ] P7 — `keep_alive`: HTTP `/v1/sessions/keep-alive` vs WS `session.keep_alive` for the BYO flow — pick one. — *Owner: Claude Code*
- [ ] Q-deploy — spawn-per-session vs warm worker pool for the long-lived stateful process. — *Owner: Jesús*
- [ ] Q-tenant — exact opt-in mechanism (program flag location) and how `tenant_id` is injected into ai-parrot calls + LiveKit job metadata. — *Owner: Jesús / Claude Code*
- [ ] Q-skills — install LiveAvatar Agent Skills (`npx skills add heygen-com/liveavatar-agent-skills`) before implementation? — *Owner: Jesús*
- [ ] Q-video-settings — confirm LITE `video_settings.quality`/`encoding` enum values against the API reference. — *Owner: Claude Code*

---

## Worktree Strategy

- **Default isolation unit**: `mixed`.
- **Phase A (parallelizable)** — these modules are decoupled libraries/adapters that only meet at
  the orchestrator/endpoint and can run in separate worktrees:
  - M1 LiveAvatar client + lifecycle
  - M2 Avatar WS PCM bridge
  - M3 LiveKit room manager
  - M4 Speakable flattener + segmenter
  Then **sequential** integration: M5 orchestrator → M6 endpoint/flag → M7 opt-in → M10 frontend viewer.
- **Phase C (sequential / per-spec)** — M8 (`llm_node` bridge) and M9 (output bridge) are a single
  integration seam; run them sequentially in one worktree after Phase A lands and P4/P5 are resolved.
- **Cross-feature dependencies**: none blocking. New top-level module `parrot/integrations/liveavatar/`
  has no overlap with in-flight specs; shared files (`AgentVoiceTalk`, `StreamHandler`, `UserSocketManager`)
  are touched only by extension — coordinate edits there to avoid conflicts.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-06-18 | Jesus Lara | Initial draft from brainstorm (Option A→C, BYO LiveKit Cloud) |
