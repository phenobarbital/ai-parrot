---
type: Wiki Overview
title: 'Feature Specification: LiveAvatar + Voice — Consolidation & Mode Unification'
id: doc:sdd-specs-liveavatar-voice-consolidation-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Eight overlapping specs (FEAT-231 → 248) grew three different "brains", two
relates_to:
- concept: mod:parrot.integrations.liveavatar
  rel: mentions
---

---
type: feature
base_branch: dev
---

# Feature Specification: LiveAvatar + Voice — Consolidation & Mode Unification

**Feature ID**: FEAT-249
**Date**: 2026-06-19
**Author**: Jesus Lara
**Status**: approved
**Target version**: (next minor)

> **Supersedes / consolidates**: FEAT-231, FEAT-242, FEAT-243, FEAT-244,
> FEAT-245, FEAT-246, FEAT-247, FEAT-248.
> **This spec is the single source of truth** for how ai-parrot talks to
> LiveAvatar + LiveKit going forward. It does NOT add a new avatar capability —
> it **defines the canonical mode taxonomy**, confirms what already works,
> closes the small remaining gaps, and **deletes the unused intermediate
> stack** (LiveKit Agents worker / Phase C) that nobody is using.
>
> No backward-compatibility or shim imports are required: none of the deleted
> code is in production.

---

## 1. Motivation

Eight overlapping specs (FEAT-231 → 248) grew three different "brains", two
avatar-drive mechanisms, two FULL-mode forks, and three duplicate Gemini-Live
implementations. The result is fragmentation, dead code, and at least one
internal contradiction (two incompatible `ask_stream` contracts; two competing
FULL-mode designs).

This spec reduces everything to **five named modes across two handlers**
(`AgentTalk` and `VoiceBot`/`VoiceHandler`), confirms which already work,
specifies the small work left, and removes the rest.

### Audit summary — what actually exists today (verified in code)

| Feat | What it is | Brain | Wired in `ai-parrot-server`? | Tests | Verdict |
|---|---|---|---|---|---|
| **231** | `AgentVoiceTalk` REST voice (`/api/v1/agents/voice/{id}`) — STT→ask→TTS | ai-parrot text | ✅ `manager.py:1749` | fakes | **KEEP** |
| **242** | LiveAvatar **LITE** — `/avatar/{id}/start\|stop` + chat→avatar "mouth" (`AvatarTurnSpeaker`, Supertonic 44100→24000) | ai-parrot text | ✅ `manager.py:1754`; mouth in `agent.py:2038,2544` | fakes | **KEEP** |
| **243** | **Phase C** LiveKit Agents worker (Deepgram/Cartesia/Silero STT/VAD/TTS), `llm_node`→`ask_stream` | ai-parrot text (in worker) | ✅ route `/voice-native/start`; worker runs as a **separate process** (`examples/`) | fakes, **no e2e** | **DELETE** |
| **244** | `voice_start`/`voice_stop` on `/bots/{id}/stream/ws` → dispatches the **Phase C worker** | — | ✅ `stream.py` | fakes | **DELETE** (depends on 243) |
| **245** | Gemini-Live PCM → LiveAvatar **LITE** mouth (`VoiceAvatarSession`, 24 kHz, no resample) | Gemini Live | ❌ only standalone `voice/server.py`; **not mounted** in `manager.py` | fakes | **KEEP + MOUNT** |
| **246** | Phase C STT/TTS adapters (`voice_adapters.py`) | — | part of 243 | fakes | **DELETE** (part of 243) |
| **247** | FULL Mode via OpenAI-compatible custom-LLM shim | avatar's built-in LLM → ai-parrot | ❌ **never implemented** (draft, 0 code, 0 tasks) | — | **DROP (rejected)** |
| **248** | FULL Mode **restricted** `avatar.speak_text` REST gateway | ai-parrot text (frontend-driven) | ✅ `manager.py:1758` | fakes | **KEEP** |

**Key facts the audit established:**
- The chat→avatar **LITE "mouth" is wired** in `AgentTalk` base (`agent.py`),
  so both `/agents/chat` and `/agents/voice` drive the avatar when a session is
  active. (Resolved the historical "mute avatar" bug.)
- **FEAT-248 needs no OpenAI-like API** — restricted mode (omitting
  `context_id` + `llm_configuration_id`) is exactly the "FULL mode without an
  OpenAI shim" the team wants. FEAT-247 is the rejected alternative.
- **Gemini-Live → LITE avatar already works** (FEAT-245): Gemini emits 24 kHz
  PCM, `AvatarWebSocket` expects 24 kHz → **no resampling**. The only gap is
  that `VoiceChatHandler` (`/ws/voice`) is **not mounted** in the deployed
  server.
- **Phase C (FEAT-243/244/246) is the unused intermediate.** It is the
  rejected "Option C" (a full LiveKit Agents STT/VAD/TTS pipeline running in a
  separate worker process). None of the five canonical modes below use it; it
  has no end-to-end run, only fake tests. → delete.
- **No production traffic** touches any of the deletion targets.
- **The server runs multi-process** (gunicorn, `(2×CPUs)+1` workers —
  `autonomous/deploy/installer.py`). `UserSocketManager.broadcast_to_channel`
  (`user.py:357`) is **in-process only** (iterates a local WS dict; its Redis
  use is just user-presence storage, not message fan-out). Therefore a
  `/ws/userinfo` WS connection and the `/agents/chat` request that produces its
  structured output can live in **different worker processes** → cross-process
  delivery **requires Redis pub/sub**. This is exactly what `output_transport.py`
  (`RedisBroadcastForwarder` → Redis channel → per-process `run_output_subscriber`
  → local `broadcast_to_channel`) provides. **The Redis structured-output
  transport is KEPT** (it is generic, not Phase-C-specific) — only the Phase C
  *worker* that happened to use it is deleted.

---

## 2. Canonical Mode Taxonomy

Two handlers, five modes. Every mode below maps to existing code; the
"Status" column states what remains.

### `AgentTalk` handler — brain = ai-parrot text agent (`ask` / `ask_stream`)

#### **Mode A — Text/Voice + LITE Avatar** *(FEAT-231 + FEAT-242)*
Endpoints: `POST /api/v1/agents/chat/{agent_id}`, `POST /api/v1/agents/voice/{agent_id}`.
Flow: optional inbound audio → **internal STT** (`VoiceTranscriber`) → `query`
→ `ask_stream()` (or `ask()` if stream off) → `AIMessage` (text **+** voice).
Avatar: ai-parrot's **own TTS** (Supertonic, 44100→24000) pushes PCM to
LiveAvatar over `AvatarWebSocket`; the avatar video is published into a LiveKit
room and a subscribe-only viewer token is returned.
**Status: DONE.** Verify-only (no real e2e exists yet).

#### **Mode B — FULL Mode (restricted `speak_text`)** *(FEAT-248)*
Endpoints: `POST /api/v1/avatar/fullmode/{agent_id}/start|stop`,
plus the conversation runs against `POST /api/v1/agents/chat/{agent_id}` in
**streaming** mode.
LiveAvatar manages STT + TTS + lip-sync (its STT is pluggable — may also be our
internal STT). ai-parrot is a **restricted** brain: no `context_id`, no
`llm_configuration_id`, so the avatar never auto-responds.
**Output bifurcation** (the core contract):
- **Speakable text** → flattened (strip markdown/code/tables via
  `SpeakableFlattener`) → `avatar.speak_text`, ideally **one event per
  sentence** as ai-parrot streams (lowers TTFB).
- **Structured outputs** (`data`, `tool_calls`, `output_mode`, `code`/`canvas`)
  → published to the AgentChat UI on the existing **`/ws/userinfo`** channel,
  keyed by the shared `session_id`.
**Status: gateway DONE; bifurcation is currently 100% frontend-driven.** This
spec adds an **optional backend streaming helper** (see §4 M-B1) and makes the
structured-output `/ws/userinfo` path first-class & documented.

#### **Mode C — Multi-viewer LITE over LiveKit** *(uses `AgentVoiceTalk`, FEAT-231 + FEAT-242)*
Same brain + TTS + avatar mouth as Mode A, but the LiveKit room is treated as a
**broadcast room**: because we control the room, we can mint **N subscribe-only
viewer tokens** so multiple people watch the same agent stream.
**Status: ~90% there.** `mint_room_tokens` already mints a subscribe-only
viewer token per call; the only gap is an endpoint to mint **additional**
viewer tokens for an existing session (see §4 M-C1).

### `VoiceBot` / `VoiceHandler` — brain = Gemini Live (realtime speech-to-speech)

#### **Mode D — Gemini Live + LITE Avatar** *(FEAT-245)*
Transport: `/ws/voice` WebSocket → `VoiceChatHandler` → `VoiceBot` →
`GeminiLiveClient`. The PCM that Gemini Live generates is teed into a
`VoiceAvatarSession` (LiveAvatar LITE mouth) — **24 kHz native match, no
resampling**. `"audio":"dual"` so browser audio never breaks if the avatar
errors.
**Status: code DONE, but `/ws/voice` is NOT mounted in `ai-parrot-server`.**
This spec **mounts it** (see §4 M-D1).

#### **Mode E — FULL Mode inside VoiceHandler** — **REJECTED**
FULL mode is text-only (`speak_text`, no PCM, no Gemini). Implementing it
inside the Gemini-Live audio handler means bypassing `VoiceBot`/
`GeminiLiveClient` entirely — i.e. it would not be "inside VoiceHandler" in any
meaningful way. FULL mode's correct home is the `AgentTalk` Mode B REST path.
**Decision: do NOT implement. Documented here so it is not re-attempted.**

### Mode → code map

| Mode | Handler | Endpoint(s) | Brain | Avatar drive | State |
|---|---|---|---|---|---|
| A | AgentTalk | `/agents/chat`, `/agents/voice` | ai-parrot text | LITE PCM push (Supertonic) | DONE (verify) |
| B | AgentTalk + FULL gateway | `/avatar/fullmode/{id}/start\|stop` + `/agents/chat` (stream) | ai-parrot text (restricted) | LiveAvatar TTS via `speak_text` | gateway DONE; bifurcation work |
| C | AgentVoiceTalk | `/agents/voice` + new viewer-token endpoint | ai-parrot text | LITE PCM push, multi-viewer room | small gap |
| D | VoiceChatHandler | `/ws/voice` | Gemini Live | LITE PCM tee (24 kHz) | mount + e2e |
| E | — | — | — | — | **rejected** |

---

## 3. Deletion Plan (dead / intermediate code — no backward-compat)

> All targets below are **unwired or unused**. Deleting them requires removing
> their `__init__.py` re-exports and their tests. No shim imports.

### 3.1 Phase C / LiveKit Agents worker stack (FEAT-243 / 244 / 246)
The whole "Option C" pipeline — the rejected intermediate mode.

- `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/livekit_agent/`
  — entire subpackage: `agent.py` (`LiveAvatarAgent.llm_node`), `worker.py`,
  `pipeline.py` (`build_session`), `voice_adapters.py` (FEAT-246), `models.py`
  (`AvatarJobMetadata`; **keep `StructuredOutputMessage`** — see §3.4),
  `__init__.py`, `VOICE_ADAPTERS.md`.
- `packages/ai-parrot-server/src/parrot/handlers/avatar.py` — the Phase C
  parts only: `_start_voice_native_session`, `VoiceNativeAvatarView`,
  `start_voice_native` / `stop_voice_native` (≈ `avatar.py:286-486`) and the
  `/voice-native/start` route registration. **Keep** the LITE parts
  (`_start_avatar_session` / `_stop_avatar_session` / `AvatarSessionView`).
- `packages/ai-parrot-server/src/parrot/handlers/stream.py` — the FEAT-244
  voice extensions: `voice_start` / `voice_stop` handlers, `_ws_voice_sessions`,
  and the avatar-specific `channel_subscriptions` / `broadcast_to_channel`
  plumbing **iff** not reused by Mode B (see §3.4). Keep plain SSE/WS/NDJSON
  text streaming.
- `room_manager.py` — `dispatch_worker` / `delete_dispatch` / `mint_browser_token`
  (publish-audio token) — Phase-C-only. **Keep `mint_room_tokens`** (LITE +
  Mode C viewer tokens).
- `examples/liveavatar_voice_worker.py` and
  `packages/ai-parrot-server/src/parrot/manager/bot_resolver.py`'s
  `build_standalone_bot_resolver` (Phase-C worker launcher) — delete if not used
  elsewhere (verify `bot_resolver` has no other consumer first).
- Manager wiring: the `_register_*` calls that mount `/voice-native/start`.
  (Keep the structured-output subscriber wiring — see §3.4 — just rename its
  gate and drop the Phase-C coupling.)
- Tests: `test_livekit_worker.py`, `test_livekit_agent.py`, Phase-C pipeline /
  adapter tests.

### 3.2 FEAT-245 duplicates & abandoned Gemini POCs
- `packages/ai-parrot-integrations/src/parrot/voice/server.py` (`VoiceChatServer`)
  — standalone POC that re-implements the Gemini-Live loop against `google.genai`
  directly, bypassing `VoiceBot`. Superseded by `VoiceChatHandler`. **Delete**
  (or demote to `examples/`) after confirming no entrypoint imports
  `create_voice_server`/`VoiceChatServer` from `server.py`.
- `packages/ai-parrot-integrations/src/parrot/voice/session.py`
  (`VoiceSession` / `VoiceSessionManager`) — third unused realtime impl, has a
  latent bug (`session.close()` doesn't exist). **Delete.**

### 3.3 FULL-mode dead bits (FEAT-247 / 248 leftovers)
- `sdd/specs/liveavatar-full-mode-custom-llm.spec.md` (FEAT-247) — mark
  **superseded/rejected** (keep for provenance, do not implement).
- `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/fullmode_observer.py`
  (`FullModeRoomObserver`) — runtime-dead stub: `connect()` never connects,
  not wired into the start handler, `livekit-rtc` extra never declared,
  Q-room-token unresolved. **Delete** (+ `__init__.py` export +
  `test_fullmode_observer.py`). Server-side transcript persistence, if ever
  needed, uses the already-implemented `get_session_transcript()` polling.
- `TenantAvatarConfig` (`models.py:187`) — defined, **consumed nowhere**.
  Delete until Q-tenant-config-store is actually scoped.

### 3.4 Shared infra — keep, but scope-check
- **`StructuredOutputMessage`** (`livekit_agent/models.py:42`) — relocate to a
  non-Phase-C module (e.g. `liveavatar/models.py`) since Mode B's structured
  output uses the same envelope. Do not delete.
- **`OutputBridge`** (`output_bridge.py`) — Redis-agnostic, duck-typed sink.
  **Keep**; Mode B publishes structured outputs through it directly to
  `UserSocketManager.broadcast_to_channel` (in-process, **no Redis needed**).
- **`output_transport.py`** (`RedisBroadcastForwarder`, `run_output_subscriber`)
  and `handlers/liveavatar_output.py` — **KEEP** (Q-redis-transport resolved).
  These are the **generic cross-process structured-output transport**, required
  because the server is multi-process and `UserSocketManager.broadcast_to_channel`
  is in-process only. Modes A/B/C all generate structured outputs in a request
  worker that may differ from the worker holding the `/ws/userinfo` connection,
  so the Redis hop is mandatory. **Decouple from Phase C**: rename the gate from
  `ENABLE_LIVEAVATAR_VOICE` to a transport-neutral flag (e.g.
  `ENABLE_STRUCTURED_OUTPUT_TRANSPORT`), drop any `AvatarJobMetadata`/worker
  coupling, and keep `_FanOutSink` fanning to `UserSocketManager` (drop the
  `StreamHandler` arm if FEAT-244 `StreamHandler` voice bits are removed).
- **`AvatarSessionOrchestrator`** (`orchestrator.py`) + `make_supertonic_pcm_fn`
  — dead one-shot LITE predecessor, never instantiated. **Delete** (+ export +
  `test_orchestrator.py`).
- **`SpeakableFlattener`**, `client.py`, `avatar_ws.py`, `voice_provider.py`,
  `speaker.py`, `optin.py`, `models.py` (minus `TenantAvatarConfig`),
  `tenant_config.py`, `voice_session.py`, internal STT/TTS backends — **keep**
  (live foundation for A/B/C/D).
- **Stale sample-rate constants** — fix (not delete):
  `supertonic_backend.py:41` `_SAMPLE_RATE=24000` and the "24 kHz" docstrings
  contradict the real 44100 Hz; `avatar_ws.py` 24000 is correct.
- **`msteams/voice/`** duplicate STT copy — consolidation candidate onto the
  shared `voice/transcriber` (low priority; out of strict scope).

---

## 4. Work Items (what's left to finish each mode)

### M-A1 — Mode A end-to-end validation (verify-only)
Real sandbox run of `/agents/chat` + `/agents/voice` with a live avatar
(`LIVEAVATAR_SANDBOX=false`, production avatar `5761a14c`). No new code expected;
fixes if the e2e surfaces gaps. Add at least one non-fake integration test
behind a `LIVEAVATAR_API_KEY` marker.

### M-B1 — Mode B backend output-bifurcation helper (optional but recommended)
Add a thin, **opt-in** server-side path so the frontend can choose to let the
backend split the stream instead of doing it itself:
- In/near `AgentTalk` streaming, when a FULL-mode session is active for the
  `session_id`: run each `ask_stream` chunk through `SpeakableFlattener`;
  emit speakable sentences back to the client (which forwards them as
  `avatar.speak_text`), and publish structured payloads
  (`StructuredOutputMessage{type, session_id, payload, turn_id}`) through
  `OutputBridge` → `RedisBroadcastForwarder` → (per-process)
  `run_output_subscriber` → local `UserSocketManager.broadcast_to_channel` on
  the `session_id` channel. **Redis is on the path by design** (multi-process
  server, §1) — the chat worker and the `/ws/userinfo` worker may differ.
- Keep it **frontend-overridable**: the frontend may still drive `speak_text`
  itself (today's behavior).

### M-B3 — Pluggable STT for Mode B (Q-internal-stt-full resolved)
The transcription source is **selectable per session**:
- **LiveAvatar STT** (default): the frontend consumes `user.transcription`
  events from the LiveKit data channel (LiveAvatar's managed room mic).
- **ai-parrot internal STT**: the frontend captures the mic locally and posts
  audio to the existing internal transcriber (`VoiceTranscriber`) — local
  `FasterWhisperBackend` **or** cloud `OpenAIWhisperBackend` — then sends the
  resulting text to `/agents/chat`. Expose this via the existing
  `/agents/voice` path or a lightweight transcribe-only endpoint.
> Note: **Silero is VAD, not STT** — it lives in the (deleted) Phase C pipeline.
> The internal STT backends are the Whisper family (`FasterWhisper` local /
> `OpenAIWhisper` cloud / `Moonshine` local-ONNX). "Internal + cloud" = those.

### M-B2 — Document & test the `/ws/userinfo` structured-output contract
Make the `session_id`-keyed structured-output channel a documented, tested
first-class contract for Mode B (the frontend guide
`docs/frontend/liveavatar-fullmode-sveltekit-guide.md` already assumes it).

### M-C1 — Multi-viewer token endpoint
Add `POST /api/v1/avatar/{agent_id}/viewers` (or a `viewers=N` option on
`/start`) that mints additional **subscribe-only** tokens (distinct identities)
for an existing session's LiveKit room via `mint_room_tokens`. Return the list
of viewer tokens. No new transport — pure token minting.

### M-D1 — Mount Gemini-Live + avatar (`/ws/voice`) in the server
Call `VoiceChatHandler.setup_routes(app)` from `BotManager.setup()` under the
optional-integration guard (mirrors `_register_avatar_routes`). Confirm JWT auth
(`parrot/core/ws_auth.py`) and the `avatar:true` start path. Add an e2e test
(fakes acceptable for CI, plus one real-sandbox marker).

### M-X — Execute the deletion plan (§3)
Remove dead/intermediate code, drop re-exports, delete obsolete tests, relocate
`StructuredOutputMessage`, fix stale sample-rate constants. Update
`pyproject.toml` extras: drop `liveavatar-voice` (Phase C plugins:
livekit-agents / deepgram / cartesia / silero / turn-detector) unless a kept
mode needs them — **none of A/B/C/D do**.

---

## 5. Acceptance Criteria

- [ ] The five modes (A–E) are documented with their exact endpoints, brains,
      and avatar-drive mechanism; E is explicitly recorded as rejected.
- [ ] Mode A: `/agents/chat` and `/agents/voice` drive the LITE avatar
      end-to-end against the sandbox (one real integration test green).
- [ ] Mode B: FULL-mode session works restricted (no `context_id`/
      `llm_configuration_id`); structured outputs reach `/ws/userinfo` keyed by
      `session_id` **even when the chat request and the WS connection are on
      different gunicorn workers** (verified via the Redis transport); speakable
      text is flattened per sentence. Backend helper is opt-in and
      frontend-overridable.
- [ ] Mode B STT is pluggable: a session can use LiveAvatar STT (default) or
      ai-parrot internal STT (FasterWhisper local / OpenAI Whisper cloud).
- [ ] The Redis structured-output transport survives the Phase C deletion,
      decoupled and re-gated (no `AvatarJobMetadata`/worker references); a
      two-worker test confirms cross-process delivery.
- [ ] Mode C: an endpoint mints ≥2 valid subscribe-only viewer tokens for one
      live session's room; multiple browsers can subscribe to the same stream.
- [ ] Mode D: `/ws/voice` is mounted in `ai-parrot-server`; a Gemini-Live turn
      is teed to the LITE avatar (24 kHz, no resample) without breaking browser
      audio.
- [ ] Phase C (FEAT-243/244/246) is fully removed: no `livekit_agent/` package,
      no `/voice-native/start` route, no `voice_start`/`voice_stop`, no
      `dispatch_worker`. `import parrot.integrations.liveavatar` still succeeds.
- [ ] `orchestrator.py`, `fullmode_observer.py`, `voice/server.py`,
      `voice/session.py`, `TenantAvatarConfig` removed; `StructuredOutputMessage`
      relocated; their tests deleted/updated.
- [ ] `pyproject.toml` extras pruned (no Phase-C-only deps); `[liveavatar]` +
      `[voice-supertonic]` (+`[voice-local]`) remain the install surface for
      A/B/C; `[liveavatar]` + `[google]` for D.
- [ ] Full test suite green after deletions (`pytest packages/ -q`); no dangling
      imports (`python -c "import parrot.integrations.liveavatar"`).
- [ ] No secrets exposed in any client-facing response (start/stop/viewers).

---

## 6. Codebase Contract (anchors verified during audit)

### Keep — live foundation
```
packages/ai-parrot-server/src/parrot/handlers/agent.py
  AgentTalk (BaseView)                          # chat; LITE mouth wired :2038,:2544
packages/ai-parrot-server/src/parrot/handlers/agent_voice.py
  AgentVoiceTalk(AgentTalk)                      # /agents/voice (FEAT-231)
packages/ai-parrot-server/src/parrot/handlers/avatar.py
  _start_avatar_session / _stop_avatar_session / AvatarSessionView   # LITE (keep)
packages/ai-parrot-server/src/parrot/handlers/avatar_fullmode.py
  FULL gateway (FEAT-248) — start/stop/avatars/voices/transcript
packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/
  client.py (create_session_token, create_full_session_token, start/stop, list_*)
  avatar_ws.py (AvatarWebSocket, 24 kHz mouth)
  voice_provider.py (AvatarVoiceProvider, 44100→24000)
  speaker.py (AvatarTurnSpeaker — active chat bridge)
  speakable.py (SpeakableFlattener)
  voice_session.py (VoiceAvatarSession — Gemini→LITE tee, FEAT-245)
  room_manager.py (mint_room_tokens — keep; dispatch_worker/mint_browser_token — delete)
  optin.py (is_avatar_enabled, is_fullmode_enabled)
  models.py (LiveAvatarConfig, AvatarSessionHandle, FullModeConfig, FullModeSessionHandle)
  tenant_config.py (resolve_fullmode_config — env-only)
  output_bridge.py (OutputBridge — structured output publish)
  output_transport.py (RedisBroadcastForwarder, run_output_subscriber — KEEP: cross-process transport)
packages/ai-parrot-server/src/parrot/handlers/liveavatar_output.py
  configure_..._subscriber / _FanOutSink   # KEEP (rename gate; drop StreamHandler arm)
packages/ai-parrot-integrations/src/parrot/voice/handler.py
  VoiceChatHandler  (mount this — M-D1)
packages/ai-parrot/src/parrot/bots/voice.py        VoiceBot (Gemini Live brain)
packages/ai-parrot/src/parrot/clients/live.py      GeminiLiveClient (24 kHz out)
packages/ai-parrot/src/parrot/models/responses.py  AIMessage (.response/.to_text vs is_structured/structured_output/data/code/tool_calls)
packages/ai-parrot-integrations/src/parrot/voice/transcriber/*  internal STT (FasterWhisper default)
packages/ai-parrot-integrations/src/parrot/voice/tts/*          internal TTS (Supertonic 44100 / Google 24000)
```

### Delete — dead / intermediate (see §3 for full list)
```
.../liveavatar/livekit_agent/**           (Phase C worker — FEAT-243/246)
.../liveavatar/orchestrator.py            (dead LITE predecessor)
.../liveavatar/fullmode_observer.py       (dead stub)
packages/ai-parrot-server/.../handlers/avatar.py  voice-native parts only
packages/ai-parrot-server/.../handlers/stream.py  voice_start/voice_stop only
packages/ai-parrot-integrations/.../voice/server.py      (Gemini POC dup)
packages/ai-parrot-integrations/.../voice/session.py     (unused realtime dup)
models.py: TenantAvatarConfig
```

### Does NOT exist (do not hallucinate)
- No OpenAI-compatible endpoint / `openai_compat.py` / `/v1/chat/completions`
  (FEAT-247 never implemented).
- No backend `speak_text` sender (that command is frontend-side over the
  LiveKit data channel `agent-control`).
- No live `FullModeRoomObserver` connection (stub only).
- No per-agent `/ws/voice` path (it's a single route; the bot is built per
  connection).

---

## 7. Resolved Questions

- [x] **Q-redis-transport** — **KEEP the Redis transport.** The server is
  multi-process (gunicorn) and `UserSocketManager.broadcast_to_channel` is
  in-process only, so structured outputs must cross processes via Redis pub/sub.

…(truncated)…
