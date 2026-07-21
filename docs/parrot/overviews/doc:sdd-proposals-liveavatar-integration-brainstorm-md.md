---
type: Wiki Overview
title: 'Brainstorm: LiveAvatar Integration (talking avatar for AgentChat)'
id: doc:sdd-proposals-liveavatar-integration-brainstorm-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: verbalizes its responses, increasing presence and accessibility for voice-first
relates_to:
- concept: mod:parrot.voice.transcriber.transcriber
  rel: mentions
- concept: mod:parrot.voice.tts.backend
  rel: mentions
- concept: mod:parrot.voice.tts.synthesizer
  rel: mentions
---

---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: LiveAvatar Integration (talking avatar for AgentChat)

**Date**: 2026-06-18
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: A (Phase 1) → C (Phase 2), both on BYO LiveKit Cloud

---

## Problem Statement

`AgentChat` answers users with text, structured data, charts and canvas, but has no
**spoken, lip-synced face**. We want to give the agent a **talking avatar** that
verbalizes its responses, increasing presence and accessibility for voice-first
scenarios (kiosks, concierge, sales demos).

The avatar is a **voice/video presentation layer**, NOT a second brain. ai-parrot
already owns the agent, tools, structured outputs and persistence. LiveAvatar (HeyGen)
in **LITE Mode** provides only the real-time video + lip-sync; STT/LLM/TTS are ours.

Affected: end users of AgentChat (new spoken modality), and backend/frontend
developers who must wire a stateful media session into an otherwise
request/response system.

## Constraints & Requirements

- **LITE Mode only** — LiveAvatar has no "speak text" command; it plays **PCM
  16-bit, 24 kHz, mono** pushed over a WebSocket. We must produce that PCM ourselves.
- **PCM format is non-negotiable**: chunks ~1 s, ≤1 MB/packet, first chunk ~400 ms to
  lower TTFB. Wait for `session.state_updated == "connected"` before sending commands.
- **Session lifecycle**: 5-min inactivity timeout → must send `keep_alive`
  periodically; always `stop_session` (incl. error paths); set `max_session_duration`
  as a safety net for SIGKILL/abandoned sessions.
- **Stateful, long-lived process** — a media session (LiveKit room + avatar WS +
  streams) does not fit classic request/response. Deployment must host a long-lived process.
- **Multi-tenant, opt-in** — the avatar is enabled per program/tenant, aligned with
  the existing `programs_user` / auth pattern. One avatar session = one `tenant_id` +
  one `agent_name` + one `session_id`.
- **Reuse existing voice stack** — `AgentVoiceTalk`, `VoiceSynthesizer` (Supertonic)
  and `ask_stream` already exist; the avatar must build on them, not replace them.
- **Unified media transport across phases** — chosen **BYO + LiveKit Cloud** so Phase A
  and Phase C share one room/token layer (no migration between phases).
- **Pluggable TTS** — Supertonic is the default for Phase A; Kokoro and others must be
  addable without touching the orchestrator.
- **No secrets in code** — LiveAvatar `X-API-KEY` and LiveKit Cloud API key/secret via
  environment variables only.

---

## Options Explored

### Option A: Avatar as the "mouth" of AgentChat (Phase 1)

ai-parrot resolves the **entire turn** through the existing path (text typed, or browser
STT, or the existing `AgentVoiceTalk` STT). The response's **plain (speakable) text** is
synthesized with our own TTS (Supertonic → PCM 24 kHz mono 16-bit) and **the backend
pushes that PCM to the avatar** over the avatar WebSocket. LiveKit's voice pipeline
(`AgentSession`, STT/LLM/TTS, worker) is NOT used.

Transport: **BYO + LiveKit Cloud** — we mint a room + client token, pass `livekit_config`
to `create_session_token`, and the avatar joins **our** room as a participant. The browser
joins the same room with the `client_token` and renders `<video>`/`<audio>`. The avatar
agent token and the avatar WebSocket stay server-side.

Streaming: consume `ask_stream()`, segment into sentences, flatten markdown incrementally,
synthesize per sentence and push PCM in chunks → low TTFB (avatar starts talking before the
full answer is ready). Structured outputs (charts/data/canvas) keep flowing to the
AgentChat UI exactly as today.

✅ **Pros:**
- Reuses the whole existing brain + voice stack (`AgentVoiceTalk`, `VoiceSynthesizer`,
  `ask_stream`). Smallest brain-side change.
- Supertonic already emits **PCM int16 LE mono 24 kHz** — the exact LITE format, zero
  resampling needed.
- No LiveKit voice pipeline / worker to learn for Phase 1.
- Full control over what is spoken (our flattener) and over barge-in (`agent.interrupt`).
- BYO Cloud transport is reused verbatim by Phase C — no migration.

❌ **Cons:**
- No LiveKit VAD/turn-detection/barge-in for free — voice-in UX is more manual than C.
- We own the avatar WS plumbing (port `avatar_ws.py`) and the sentence segmentation /
  markdown flattening (neither exists yet).
- Still needs the stateful long-lived orchestrator + lifecycle (keep_alive/stop).

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `livekit-api` (`~=0.x`) | Mint LiveKit Cloud room + client/agent tokens (BYO) | Server SDK; needs `LIVEKIT_URL/API_KEY/API_SECRET` |
| `livekit` (client, JS `livekit-client`) | Browser viewer joins the room, renders `<video>`/`<audio>` | Frontend only |
| `aiohttp` | LiveAvatar HTTP client + avatar WebSocket (project standard) | Replaces starter's httpx/websockets |
| LiveAvatar HTTP API | `create_session_token`/`start`/`stop`/`keep-alive`/`transcript` | `X-API-KEY`; `Bearer session_token` for `start` |
| Supertonic (existing) | TTS text→PCM 24 kHz mono 16-bit | `SupertonicPipeline.synthesize_pcm()` |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot-server/src/parrot/handlers/agent_voice.py:57` — `AgentVoiceTalk`; pattern for STT-in / TTS-out around the unchanged text dispatch.
- `packages/ai-parrot-integrations/src/parrot/voice/tts/supertonic_inference.py` — `SupertonicPipeline.synthesize_pcm()` returns raw PCM (16-bit LE mono 24 kHz).
- `packages/ai-parrot-integrations/src/parrot/voice/tts/synthesizer.py:53` — `VoiceSynthesizer._get_backend()` factory (pluggable backends).
- `packages/ai-parrot/src/parrot/bots/base.py:1456` — `BaseBot.ask_stream()` for per-sentence streaming.
- Starter (to port): `src/avatar_ws.py` (`AvatarWebSocket`: resample→24 kHz, mono mixdown, 400 ms first chunk then 1 s, reconnect+replay, `start_speaking`/`send_audio_frame`/`finish_speaking`/`interrupt`); `src/liveavatar_client.py` (HTTP client).

---

### Option B: FULL Mode + Custom LLM (OpenAI-compatible)

LiveAvatar's **FULL Mode** runs the entire pipeline (STT + TTS + video) and calls **our
LLM** via its "Custom LLM Integration". If ai-parrot exposed an **OpenAI-compatible
streaming chat endpoint**, LiveAvatar would do "ai-parrot is the brain, the avatar talks"
with **no LiveKit worker, no PCM plumbing, no own TTS**.

✅ **Pros:**
- By far the least infra code: LiveAvatar manages voice + video end-to-end.
- No avatar WS plumbing, no sentence chunking, no own TTS.

❌ **Cons:**
- Far less control of the pipeline.
- Requires ai-parrot to speak **OpenAI-compatible streaming** — a new compatibility
  surface we don't have today.
- **Structured outputs (charts/data/canvas) do NOT fit the standard chat format** — they'd
  need a separate side channel anyway, so we lose A/C's clean output bifurcation.
- Vendor lock-in to LiveAvatar's pipeline choices (STT/TTS), opposite of our pluggable goal.

📊 **Effort:** Low (infra) / Medium (the OpenAI-compat shim + side channel for outputs)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| LiveAvatar FULL Mode / Custom LLM | Hosts STT+TTS+video, calls our LLM | `docs/full-mode/custom-llm` |
| (ai-parrot OpenAI-compat shim) | Expose `/v1/chat/completions`-style streaming | Does NOT exist yet |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/bots/base.py:1456` — `ask_stream()` would feed the
  OpenAI-compat shim's token stream.
- (No avatar/LiveKit code is needed in this option.)

---

### Option C: Voice-native hybrid — ai-parrot as the brain via `llm_node` (Phase 2)

Keep the LiveKit Agents voice pipeline from the starter (STT + VAD + turn-detection + TTS +
avatar), but `LiveAvatarAgent` **overrides `llm_node`** to call ai-parrot instead of
LiveKit's LLM. The response bifurcates:
- **plain text** → `yield` from `llm_node` → LiveKit TTS → avatar (what is spoken);
- **structured outputs** (charts/data/`tool_calls`/canvas) → published to the AgentChat UI
  over the existing WebSocket channel, sharing `session_id`.

Transport: the **same BYO LiveKit Cloud room** as Phase A. The LiveKit Agents worker is a
participant of our room (deployable via `lk agent deploy` because the room is ours). TTS
goes directly to **LiveKit inference** in this phase (own TTS optional later).

✅ **Pros:**
- STT, VAD, turn-detection and barge-in come **for free** from the LiveKit pipeline —
  fluent voice conversation.
- `llm_node` can `yield` plain `str`, which the TTS node consumes directly — natural
  streaming seam for ai-parrot text.
- Reuses Phase A's room/token layer (BYO Cloud) — no transport migration.

❌ **Cons:**
- The `llm_node` override calling ai-parrot does **not exist**; needs the streaming
  contract (P1) resolved to avoid high TTFB.
- The **output bifurcation bridge** (structured outputs → `/ws/userinfo`-style channel)
  does not exist — must define the message contract and channel.
- During long `tool_calls` the avatar may go silent → need filler utterances / "thinking" state.
- Pinned `livekit-agents` version determines the exact `llm_node` signature (P5).

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `livekit-agents` (`~=1.5`) | Voice pipeline (`AgentSession`, STT/VAD/turn/TTS) + `llm_node` override | Pin version; validate `llm_node` signature |
| `livekit-plugins-*` | Deepgram STT, Cartesia TTS, Silero VAD, MultilingualModel turn-detection | Per starter `pipeline.py` |
| `livekit-api` | Room/token minting (shared with Phase A) | BYO Cloud |
| LiveKit inference gateway | STT/LLM/TTS billing through LiveKit Cloud credits | TTS here, not Supertonic |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/bots/base.py:1456` — `ask_stream()` consumed inside `llm_node`.
- `packages/ai-parrot-server/src/parrot/handlers/user.py:357` — `UserSocketManager.broadcast_to_channel()` to push structured outputs to the UI.
- `packages/ai-parrot-server/src/parrot/handlers/web_hitl.py` — `ws_channel_id` / `current_web_session` ContextVar pattern for routing to the right UI channel.
- Starter (to adapt): `src/agent.py` (`tts_node` tee pattern → replicate for `llm_node`), `src/pipeline.py` (`build_session`), `src/worker.py` (job metadata → inject `tenant_id`/`agent_name`/`session_id`).

---

## Recommendation

**Phased: Option A first (Phase 1), then Option C (Phase 2) — both on BYO + LiveKit Cloud.**

- **A is the fastest, lowest-risk way to a talking avatar** because it reuses the entire
  existing brain and voice stack (`AgentVoiceTalk`, `VoiceSynthesizer`, `ask_stream`), and
  Supertonic already emits the exact PCM format LITE Mode requires (24 kHz mono 16-bit) — no
  resampling, no new TTS. The brain path is untouched; we add a presentation layer.
- **C is the destination for fluent voice conversation** (STT/VAD/turn-detection/barge-in
  for free), but it carries the unresolved streaming contract (P1) and the output-bifurcation
  bridge (P4), so it should follow A rather than block it.
- **BYO + LiveKit Cloud is chosen for both phases** so the room/token layer is written once.
  Incremental cost in A is one `LiveKitRoomManager` module + three env vars; the payoff is no
  transport migration at C and easier C deployment (`lk agent deploy` applies because the room
  is ours). We trade a little extra setup in A for zero rework in C.
- **FULL Mode (Option B) is rejected as the primary path** because structured outputs don't
  fit the OpenAI chat format (we'd need a side channel anyway, losing A/C's clean bifurcation)
  and it requires an OpenAI-compat surface we don't have. It remains a documented fallback if
  infra cost ever dominates.

What we trade off: A's voice-in UX is more manual than C until Phase 2 lands; we accept that
because A delivers a spoken avatar quickly and C reuses A's transport wholesale.

---

## Feature Description

### User-Facing Behavior
- A tenant/program with the avatar **opt-in enabled** sees an avatar viewer embedded in
  `AgentChat`. When the agent answers, a lip-synced video face **speaks the answer aloud**
  while charts/data/canvas continue to render in the existing UI.
- **Phase A**: the user types (or uses browser/`AgentVoiceTalk` STT); the agent's spoken
  reply starts within a sentence or two (streaming TTFB), and the avatar can be interrupted.
- **Phase C**: the user **talks** to the avatar; the pipeline detects turns and barge-in
  natively, and the same avatar speaks ai-parrot's answer.
- Tenants without the opt-in see today's text-only AgentChat, unchanged.

### Internal Behavior
- **Session lifecycle (both phases)**: `create_session_token` (LITE, with `livekit_config`
  for BYO) → `start_session` → conversation → `stop_session`. A `LiveKitRoomManager` mints the
  room + client/agent tokens; the backend keeps the avatar agent token and the avatar WS.
  A background task sends `keep_alive` < 5 min; `stop_session` runs on every exit path;
  `max_session_duration` is set as a safety net.
- **Phase A flow**: browser/STT text → `POST /api/v1/agents/...` (a flag enables avatar mode)
  → `ask_stream()` yields chunks → sentence segmenter + markdown flattener → Supertonic
  `synthesize_pcm()` per sentence → `AvatarWebSocket.send_audio_frame()` (`agent.speak` → …
  → `agent.speak_end`) → LiveAvatar media-server lip-syncs → browser viewer renders. Structured
  outputs flow to the AgentChat UI as today.
- **Phase C flow**: browser mic → our LiveKit room → `AgentSession` STT → `llm_node` override
  calls ai-parrot (streamed) → plain text `yield` → LiveKit TTS → avatar; structured outputs →
  `broadcast_to_channel()` on the shared `session_id` channel.
- **Multi-tenancy**: `tenant_id` propagated via the LiveKit job metadata (Phase C `worker.py`)
  and on each ai-parrot call; opt-in resolved per program.

### Edge Cases & Error Handling
- **Commands before `connected`**: queue/await `session.state_updated == "connected"`.
- **Inactivity timeout / abandoned session**: periodic `keep_alive` + `max_session_duration`
  backstop; `stop_session` in `finally`/shutdown callbacks.
- **WS disconnect**: reconnect with `start` replay (already handled by `avatar_ws.py`).
- **PCM limits**: enforce ≤1 MB/packet and ~1 s chunking; first chunk ~400 ms for TTFB.
- **Markdown that shouldn't be spoken** (code fences, tables): the flattener strips them.
- **Long `tool_calls` (Phase C)**: filler utterance / "thinking" state to avoid dead air.
- **TTS failure**: graceful degradation to text-only (mirrors `AgentVoiceTalk` behavior).
- **Barge-in**: `agent.interrupt` clears scheduled audio.

---

## Capabilities

### New Capabilities
- `liveavatar-session-lifecycle`: HTTP client + session manager for LiveAvatar LITE
  (`create_session_token`/`start`/`stop`/`keep-alive`/`transcript`) with keep-alive task and
  guaranteed teardown.
- `liveavatar-audio-bridge`: ported `AvatarWebSocket` (PCM push, chunking, reconnect,
  interrupt) wired to Supertonic PCM output.
- `livekit-room-manager`: BYO LiveKit Cloud room + token minting (`livekit-api`), shared by
  Phase A and Phase C.
- `speakable-text-flattener`: markdown→speakable plaintext (strip code/tables/md syntax),
  incremental + sentence segmentation for streaming TTS.
- `avatar-session-endpoint`: backend endpoint(s) to start/stop an avatar session and a flag
  to enable avatar mode on the chat/voice path; returns viewer `livekit_url` + `client_token`.
- `avatar-viewer-frontend`: Svelte 5 LiveKit viewer embedded in AgentChat, sharing `session_id`.
- `avatar-tenant-optin`: per-program/tenant gating for the avatar.
- `llm-node-aiparrot-bridge` (Phase C): `llm_node` override calling ai-parrot + output
  bifurcation bridge to the AgentChat WS channel.

### Modified Capabilities
- (none confirmed — `AgentVoiceTalk` and the streaming/WS handlers are extended, not
  redefined; confirm at spec time.)

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/agent_voice.py` (`AgentVoiceTalk`) | extends | Add avatar-mode flag; reuse STT-in/TTS-out pattern. |
| `packages/ai-parrot-integrations/src/parrot/voice/tts/` (`VoiceSynthesizer`, Supertonic) | depends on | Use `synthesize_pcm()`; add Kokoro later via the factory. |
| `packages/ai-parrot-server/src/parrot/handlers/stream.py` (`StreamHandler`) | depends on / extends | Per-sentence streaming source for avatar speech. |
| `packages/ai-parrot-server/src/parrot/handlers/user.py` (`UserSocketManager`) | depends on | `broadcast_to_channel()` for Phase C structured-output bridge. |
| `packages/ai-parrot/src/parrot/bots/base.py` (`ask_stream`) | depends on | Token stream feeding TTS / `llm_node`. |
| New module: `parrot/integrations/liveavatar/` (client, ws bridge, session mgr) | new | Ported + adapted from starter to `aiohttp`/async. |
| New module: LiveKit room manager (`livekit-api`) | new | BYO Cloud tokens; env: `LIVEKIT_URL/API_KEY/API_SECRET`, `LIVEAVATAR_API_KEY`. |
| Frontend AgentChat (Svelte 5) | new | LiveKit viewer component, opt-in aware. |
| Deployment | new | Long-lived stateful process (spawn-per-session or warm pool). |
| Config / secrets | new | LiveAvatar + LiveKit Cloud keys via env. |
| `pyproject.toml` | modifies | Add `livekit-api` (+ `livekit-agents`/plugins in Phase C) as an optional extra. |

---

## Credentials & Environment Variables

BYO + LiveKit Cloud means **two separate accounts/credentials** — register in both before
Phase A. All values are read from the environment (never committed).

**1. LiveKit Cloud** (the media room / SFU) — sign up at `https://cloud.livekit.io`
(free tier covers development), create a project, copy the three values:

| Env var | Purpose | Example |
|---|---|---|
| `LIVEKIT_URL` | SFU WebSocket URL of your project | `wss://<project>.livekit.cloud` |
| `LIVEKIT_API_KEY` | Used by `LiveKitRoomManager` (`livekit-api`) to mint tokens | — |
| `LIVEKIT_API_SECRET` | Secret for token minting (room + client/agent tokens) | — |

**2. LiveAvatar / HeyGen** (the avatar video + lip-sync):

| Env var | Purpose | Notes |
|---|---|---|
| `LIVEAVATAR_API_KEY` | HTTP auth header `X-API-KEY` for `create_session_token`/`stop`/`keep-alive` | `Bearer session_token` is used for `start_session` (obtained at runtime) |
| `LIVEAVATAR_AVATAR_ID` | Which avatar to render | per `create_session_token` body (LITE) |
| `LIVEAVATAR_BASE_URL` | API base (default `https://api.liveavatar.com`) | optional override |

**Phase C only** — LiveKit inference plugins (STT/VAD/TTS) may need their own provider keys
per `pipeline.py` (e.g. Deepgram STT, Cartesia TTS), or be billed through LiveKit Cloud credits.
To be pinned at Phase C spec time.

**Cost/billing notes (briefing §1.4):**
- **Phase A**: media plane is LiveKit room + LiveAvatar avatar only — the LiveKit *inference*
  gateway (STT/LLM/TTS) is NOT used (brain = ai-parrot, TTS = Supertonic). You pay LiveKit room
  usage + LiveAvatar avatar minutes.
- **Phase C**: LiveKit inference (STT/TTS) is used and billed through LiveKit Cloud credits.
- Use LiveAvatar `is_sandbox=true` during development to avoid burning avatar minutes
  (duration-capped).

---

## Code Context

### User-Provided Code
The user provided the briefing `sdd/proposals/liveavatar-ai-parrot-briefing.md`, including
the illustrative `llm_node` override pseudocode (Phase C, §3.4) and the verified LiveAvatar
HTTP/WS protocol tables (§1.2–1.5). Treat that pseudocode as **illustrative, not literal** —
validate against the pinned `livekit-agents` version.

```python
# Source: sdd/proposals/liveavatar-ai-parrot-briefing.md §3.4 (ILLUSTRATIVE — do not copy blindly)
class LiveAvatarAgent(Agent):
    async def llm_node(self, chat_ctx, tools, model_settings):
        user_text = _last_user_text(chat_ctx)        # last ChatMessage role=user
        async for piece in ai_parrot_stream(agent_name=..., query=user_text,
                                             session_id=..., tenant_id=...):
            if piece.kind == "speakable":
                yield piece.text                     # str → TTS → avatar
            elif piece.kind == "structured":
                await self._publish_to_agentchat(piece)   # charts/data/canvas → UI
```

### Verified Codebase References

#### Classes & Signatures
```python
# packages/ai-parrot-server/src/parrot/handlers/agent.py:100
class AgentTalk(BaseView):
    async def post(self): ...                         # line 1523  (POST /api/v1/agents/chat/{agent_id})
    async def _handle_stream_response(self, bot, query, ...): ...  # line 2365  (web.StreamResponse, chunked)

# packages/ai-parrot-server/src/parrot/handlers/agent_voice.py:57
class AgentVoiceTalk(AgentTalk):                       # POST /api/v1/agents/voice/{agent_id}
    async def handle_upload(self): ...                 # line 84  (STT-in)
    async def post(self): ...                          # line 268 (TTS-out, attaches audio_base64)

# packages/ai-parrot-integrations/src/parrot/voice/tts/backend.py:17
class AbstractTTSBackend(ABC):
    async def synthesize(self, text, *, voice=None,
                         mime_format="audio/ogg", language=None) -> "SynthesisResult": ...

# packages/ai-parrot-integrations/src/parrot/voice/tts/supertonic_inference.py
class SupertonicPipeline:                              # ~line 335
    def synthesize_pcm(self, text, *, voice=None, language=None,
                       silence_duration=0.3) -> bytes: ...  # raw PCM int16 LE mono 24 kHz
class SupertonicONNXBackend(SupertonicTTSBackend): ...     # supertonic_backend.py:604

# packages/ai-parrot-integrations/src/parrot/voice/tts/synthesizer.py:22
class VoiceSynthesizer:
    def _get_backend(self) -> AbstractTTSBackend: ...  # line 53 — string-dispatch factory (add "kokoro" elif)

# packages/ai-parrot/src/parrot/bots/base.py:1456
async def ask_stream(self, question, ...) -> AsyncIterator[Union[str, AIMessage]]: ...
# (abstract decl: packages/ai-parrot/src/parrot/bots/abstract.py:3740)

# packages/ai-parrot/src/parrot/models/responses.py:72
class AIMessage(BaseModel):
    response: Optional[str]; output: Any; data: Optional[Any]; code: Optional[str]
    tool_calls: List[ToolCall]; output_mode: OutputMode; artifact_id: Optional[str]
    @property
    def to_text(self) -> str: ...                      # line 249

# packages/ai-parrot-server/src/parrot/handlers/stream.py:197
class StreamHandler:
    async def stream_websocket(self, request) -> web.WebSocketResponse: ...  # GET /bots/{bot_id}/stream/ws

# packages/ai-parrot-server/src/parrot/handlers/user.py:27
class UserSocketManager(WebSocketManager):
    async def broadcast_to_channel(self, channel, message, exclude_ws=None): ...  # line 357
```

#### Verified Imports
```python
# Confirmed to exist:
from parrot.voice.tts.synthesizer import VoiceSynthesizer           # ai-parrot-integrations
from parrot.voice.tts.backend import AbstractTTSBackend             # ai-parrot-integrations
from parrot.voice.transcriber.transcriber import VoiceTranscriber   # ai-parrot-integrations
# AgentVoiceTalk / AgentTalk live in ai-parrot-server handlers (HTTP layer).
```

#### Key Attributes & Constants
- Supertonic PCM = `_SAMPLE_RATE=24000`, `_CHANNELS=1`, `_SAMPLE_WIDTH=2` (16-bit) —
  matches LITE Mode requirement exactly (`supertonic_backend.py:40`).
- `TTSConfig.backend` Literal currently `{"google","elevenlabs","openai","supertonic"}`
  (`voice/tts/models.py`) — extend for `"kokoro"`.
- `AgentVoiceTalk` per-request selectors: `tts_backend`, `stt_backend`, `audio_format`.
- HITL routing: `ws_channel_id` + `current_web_session` ContextVar (`web_hitl.py`).

### Does NOT Exist (Anti-Hallucination)
- ~~any `livekit` / `liveavatar` / `webrtc` / `aiortc` / `avatar` code~~ — **ZERO** matches
  in the entire source tree. Clean slate.

…(truncated)…
