---
type: Wiki Overview
title: Spec — LiveAvatar FULL Mode as voice/face for ai-parrot (no OpenAI-compatible
  client)
id: doc:sdd-proposals-spec-liveavatar-fullmode-speaktext-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: sandbox API). Q2 resolved (`ask_stream`). Ready for `/sdd-task` pending the
  ai-parrot
---

# Spec — LiveAvatar FULL Mode as voice/face for ai-parrot (no OpenAI-compatible client)

- **Feature id:** `FEAT-<assign>` (suggested slug: `liveavatar-fullmode-speaktext`)
- **Status:** Q1 gate PASSED (validated by `spike_q1_speaktext.py` against the live LiveAvatar
  sandbox API). Q2 resolved (`ask_stream`). Ready for `/sdd-task` pending the ai-parrot
  codebase-side `⚠️ VERIFY` items.
- **Relationship to existing work:** Standalone. Does NOT supersede or modify the
  `liveavatar-ai-parrot-briefing` (LITE Mode, options A/C) already in progress. This is a
  parallel approach for evaluation/implementation.

> Conventions: grep anchors instead of line numbers; `⚠️ VERIFY` marks claims not yet
> confirmed against the live codebase or against a runtime spike; "Codebase contract"
> separates existing infrastructure from new modules to prevent implementation hallucination.

---

## 1. Summary

Give ai-parrot agents a talking avatar (lip-synced video + natural TTS) using LiveAvatar
**FULL Mode**, while keeping ai-parrot **exactly as it is** — text in, text out. The avatar's
voice comes from the `avatar.speak_text` command, which speaks arbitrary text **without invoking
any LLM**, so we never have to expose an OpenAI-compatible `/chat/completions` endpoint or build
an OpenAI-style `AbstractClient` for ai-parrot.

Input STT is **pluggable**: either consume LiveAvatar's built-in STT (`user.transcription`
events) or keep ai-parrot's own STT path (browser Web Speech API or a dedicated STT service).
Either way, the brain is the existing ai-parrot agent (`query → response`), and structured
outputs (charts, data, canvas) continue to flow to the AgentChat UI through the current
WebSocket/REST path.

---

## 2. Goals / Non-goals

### Goals
- Use LiveAvatar **avatars** (stock or custom) and **voices** (library, video-avatar clone, or
  imported ElevenLabs voices).
- Use LiveAvatar **TTS + video/lip-sync** for output.
- Use LiveAvatar **STT** for input as the default, behind a pluggable seam that also supports
  ai-parrot's own STT.
- Keep ai-parrot as the agent, unchanged at its core contract (`query → response`).
- Share `session_id` so the avatar conversation and the AgentChat canvas are one coherent session.

### Non-goals
- ❌ Building an OpenAI-compatible API / `AbstractClient` wrapper around ai-parrot.
- ❌ Using LiveAvatar's built-in LLM or its custom-LLM (`avatar.speak_response` /
  `llm_configuration_id`) path.
- ❌ LITE Mode / bringing our own TTS / PCM plumbing (that is the separate briefing).
- ❌ Programmatic creation of custom avatars (not exposed by API — see §5.1).

---

## 3. Why FULL Mode + `avatar.speak_text`

FULL Mode runs the full real-time stack (VAD, STT, LLM, TTS, video). It exposes two distinct
"make the avatar talk" commands:

| Command | LLM involved? | OpenAI-compatible endpoint needed? |
|---|---|---|
| `avatar.speak_response {text}` | Yes (LiveAvatar default LLM, or your custom LLM via `llm_configuration_id`) | **Yes**, if custom LLM (`/chat/completions`) |
| `avatar.speak_text {text}` | **No** | **No** |

We use **only** `avatar.speak_text`. ai-parrot produces the text; LiveAvatar's TTS speaks it.
The OpenAI requirement is therefore irrelevant to this design.

Trade-off vs LITE (briefing) and vs custom-LLM:
- vs **LITE**: no PCM plumbing, no own-TTS requirement, less infra (no LiveKit Cloud project for
  inference, no long-lived LiveKit worker). LiveAvatar bills STT/TTS/video on its credits.
- vs **custom-LLM**: no OpenAI shim; ai-parrot's structured outputs (which don't fit
  `/chat/completions`) keep flowing on our own channel.
- Cost: STT + TTS + video all run on LiveAvatar credits (FULL Mode). No LiveKit Cloud inference.

---

## 4. Architecture

FULL Mode session = a LiveAvatar-managed LiveKit room with 3 participants (end user, LiveAvatar
agent, avatar). Control is **event-driven** over LiveKit data channels; topics are
`agent-control` (we send) and `agent-response` (we receive). LiveAvatar recommends the
**frontend as the primary event controller** to minimize latency, relaying to backend for
logging/analytics. This spec adopts that: the SvelteKit frontend drives the loop and reuses the
existing AgentChat agent call; the backend only mints tokens and manages provisioning/config.

### 4.1 Runtime loop (frontend-driven)

```
                    ┌──────────────────────────────────────────────────────────┐
                    │                 LiveAvatar-managed room                    │
   user mic ───────►│  VAD + STT  ──► user.transcription {text}  (agent-response)│
                    │  TTS + video ◄── avatar.speak_text {text}  (agent-control) │
                    └───────▲───────────────────────────┬────────────────────────┘
                            │                            │ avatar video stream
        (own STT path)      │                            ▼
   browser STT ──► text ────┤                       [Frontend <video>]
                            │
                            ▼
                  [Frontend orchestrator]
                            │  final transcript (from either STT backend)
                            ▼
                  ai-parrot  POST /api/v1/agents/chat/{agent}   (existing, unchanged)
                            │                         │
              speakable text (flatten md)        structured outputs
                            │                         │
                            ▼                         ▼
                  avatar.speak_text          AgentChat UI (charts/data/canvas)
                  (per sentence)             via current WS /ws/userinfo + REST
```

### 4.2 Pluggable STT seam

`AbstractSpeechInput` (new) — normalizes "user produced a final utterance → text":

- `LiveAvatarSpeechInput` — user mic is published to the LiveAvatar room; transcripts arrive as
  `user.transcription`. Turn-taking via interactivity type (Conversational auto-VAD, or PTT).
- `LocalSpeechInput` — capture mic in the browser (Web Speech API) or a dedicated STT service;
  LiveAvatar STT is unused. The avatar runs so it never auto-responds (restricted mode, §7.1),
  and we only drive it via `avatar.speak_text`. `⚠️ VERIFY` (Q4) whether the user mic should
  still be published to the room or muted/withheld in this mode.

Both backends emit the same normalized `{ text, is_final }` to the orchestrator. This matches the
project's `Abstract*` extension-seam + registry convention; selection is per session/tenant config.

### 4.3 Output bifurcation
- **Speakable text** → flattened (strip markdown/code/tables) → `avatar.speak_text`, ideally
  one event per sentence as ai-parrot streams, to reduce TTFB.
- **Structured outputs** (`data`, `tool_calls`, `output_mode`, code/canvas) → published to the
  AgentChat UI on the existing `/ws/userinfo` channel / REST, keyed by the shared `session_id`.

---

## 5. LiveAvatar surface (verified against docs)

> Source docs in §12. Base URL `https://api.liveavatar.com`, header `X-API-KEY` (except
> `start_session`, which uses `Authorization: Bearer <session_token>`).

### 5.1 Avatars — provisioning is dashboard, not API
- Stock avatars: available to all; referenced by `avatar_id`. No slot required.
- Custom avatars: created in the LiveAvatar dashboard (`app.liveavatar.com`) as a **paid add-on**
  requiring an **avatar slot**. Two methods: **video** (2-min footage + consent recording →
  auto voice clone) or **image** (single photo → no voice clone; must supply a voice).
- API exposes only `list-public-avatars`, `list-user-avatars`, `get-avatar-by-id`,
  `update-avatar`, `delete-avatar`. **No create endpoint.**
- ai-parrot implication: avatar creation is an out-of-band operator workflow; ai-parrot stores
  and references `avatar_id` (per tenant). Provide a thin read/list integration only.

### 5.2 Voices — FULL Mode only; some programmable
- Voice library (stock), referenced by `voice_id`.
- Avatar-generated clone (from a video avatar's footage).
- **Imported third-party (ElevenLabs)** — programmable:
  1. `POST /v1/secrets` `{ secret_type: "ELEVENLABS_API_KEY", secret_value, secret_name }` → `secret_id`.
  2. `POST /v1/voices/third_party` `{ secret_id, voice_id: <elevenlabs_voice_id> }` → voice appears
     in your LiveAvatar voice listing; use its `voice_id` at session start.
  - Requires a **paid ElevenLabs** plan. Voice invalidates if the ElevenLabs voice or secret is removed.
- Voice management API: `list-voices`, `get-voice-by-id`, `update-voice`, `delete-voice`,
  `get-voice-preview-by-id`, `bind-third-party-voice`.

### 5.3 Session API
- `POST /v1/sessions/token` (FULL):
  ```json
  {
    "mode": "FULL",
    "avatar_id": "<avatar_id>",
    "interactivity_type": "CONVERSATIONAL | PUSH_TO_TALK",   // optional, default conversational
    "avatar_persona": { "voice_id": "<voice_id>", "context_id": "<context_id?>", "language": "es" },
    "video_settings": { "quality": "high", "encoding": "H264" },
    "max_session_duration": 600
  }
  ```
  Returns `session_id`, `session_token`. `llm_configuration_id` is **omitted on purpose**
  (we never use the built-in/custom LLM).
- `POST /v1/sessions/start` (Bearer session_token) → `livekit_url`, `livekit_client_token`, session details.
  ✅ **Verified (spike):** in FULL the response also carries `livekit_agent_token: null` and
  `ws_url: null` — there is **no separate avatar media-server WebSocket** (that is LITE only);
  all control/feedback is over LiveKit data channels (§5.4). Sandbox sessions are capped
  (`max_session_duration` came back as `60`).
- `POST /v1/sessions/stop` → end the session.
- `POST /v1/sessions/keep-alive` (and/or WS `session.keep_alive`) → defeat idle timeout. `⚠️ VERIFY` (Q5).
- `GET /v1/sessions/{id}/transcript` → server-side transcript (optional persistence aid).

### 5.4 Events (LiveKit data channels)

✅ **Verified envelope (spike).** Messages are JSON published as LiveKit data on a topic. Send on
`agent-control`, receive on `agent-response`. Confirmed shape (flat, no nesting):
```json
{ "event_id": "<uuid>", "event_type": "avatar.speak_text", "session_id": "<uuid>",
  "source_event_id": null, "text": "<arbitrary text>" }
```
Correlation: `avatar.speak_started`/`avatar.speak_ended` carry a `source_event_id` tying them to
the triggering speak command.

Send on `agent-control`:

| Event | Payload | Use |
|---|---|---|
| `avatar.speak_text` | `{text}` | **Speak ai-parrot's text (no LLM)** — primary output. ✅ verified to speak arbitrary text in restricted mode. |
| `avatar.interrupt` | — | Barge-in: stop + clear queued speech |
| `avatar.start_listening` / `avatar.stop_listening` | — | Listening-state UX cue |
| `user.start_push_to_talk` / `user.stop_push_to_talk` | — | PTT only |

Receive on `agent-response`:

| Event | Payload | Use |
|---|---|---|
| `user.transcription` | `{text}` | **STT output** (LiveAvatarSpeechInput) |
| `user.speak_started` / `user.speak_ended` | — | turn boundaries / trigger interrupt |
| `avatar.speak_started` / `avatar.speak_ended` | `{source_event_id}` | avatar speaking state (correlated to the speak command) |
| `avatar.transcription.chunk` | `{text}` | ✅ **(verified, undocumented)** the spoken text streamed **word-by-word** as the avatar talks |
| `avatar.transcription` | `{text}` | full spoken text, emitted once (for `speak_text`, immediately) |
| `session.stopped` | `{end_reason}` | teardown (`IDLE_TIMEOUT`, `MAX_DURATION_REACHED`, `NO_CREDITS`, …) |

> Streaming opportunity: pair ai-parrot `ask_stream` (per-sentence `avatar.speak_text`) with
> `avatar.transcription.chunk` for end-to-end streaming and word-level UI sync.

### 5.5 Frontend SDK
- FULL Mode ships `@heygen/liveavatar-web-sdk` — preferred over a hand-rolled LiveKit client.
  `⚠️ VERIFY` (Q6) it exposes `agent-control`/`agent-response` event send/subscribe (or fall back
  to `livekit-client` data channels directly).

---

## 6. Codebase contract (ai-parrot)

### 6.1 Existing infrastructure to reuse (do NOT reinvent)
- Agent call (REST): `src/lib/api/agent.ts` → `chatWithAgent`, `callAgentMethod`;
  `BASE_PATH = '/api/v1/agents/chat'`. Request/response types in `src/lib/types/agent.ts`
  (`AgentChatRequest`, `AgentChatResponse` with `response` markdown, `data`, `output_mode`,
  `tool_calls`, `metadata.session_id/turn_id`).
- User WebSocket: `src/lib/services/websocket-service.ts` (`wsService`, `/ws/userinfo`,
  `subscribe`/`unsubscribe`/`onMessage`) and `src/lib/stores/websocket.svelte.ts`.
- Chat UI host: `src/lib/components/agents/AgentChat.svelte` (props `agentId`, `session_id`
  handling, canvas via `CanvasPanel`).
- Persistence: `src/lib/api/chatInteraction.ts` (`/api/v1/chat/interactions`).
- Tenancy/auth: `src/lib/navauth/*`, `src/lib/api/programs.ts` (programs/domain/groups).

### 6.2 New modules to build
- **Backend (ai-parrot):**
  - `LiveAvatarClient` — async (httpx/asyncdb-style) client for sessions/secrets/voices/avatars.
    Holds `X-API-KEY` server-side; never exposed to frontend.
  - `POST` endpoint(s) to mint a FULL Mode session and return `{ livekit_url,
    livekit_client_token, session_id, avatar_id, voice_id }` to the frontend.
  - Optional provisioning endpoints: list avatars/voices for a tenant; bind ElevenLabs voice
    (secrets + `/v1/voices/third_party`).
  - Per-tenant config store: default `avatar_id`, `voice_id`, `interactivity_type`, STT backend.
- **Frontend (SvelteKit / Svelte 5 runes):**
  - `AbstractSpeechInput` + `LiveAvatarSpeechInput` + `LocalSpeechInput` (§4.2).
  - Avatar orchestrator store: connects room, subscribes `agent-response`, runs the
    transcript → `chatWithAgent` → flatten → `avatar.speak_text` loop, handles interrupts.
  - Speakable-text flattener (markdown → plain speech).
  - Avatar viewer component (Web SDK or `livekit-client`), embeddable next to `AgentChat`.
  - Bifurcation: route structured outputs to existing AgentChat rendering via shared `session_id`.

---

## 7. Cross-cutting behavior

### 7.1 Suppressing LiveAvatar's own LLM (critical) — ✅ RESOLVED
We must ensure the avatar never auto-responds with its built-in LLM (would double up with
ai-parrot). Lever: **restricted mode** — start the session with **no `context_id`**. Per docs the
avatar then won't respond to user input on its own; user transcripts are still emitted.
- ✅ **Q1 confirmed (spike `spike_q1_speaktext.py`):** in restricted mode (no `context_id`),
  `avatar.speak_text` with fully **arbitrary** text is spoken normally — `avatar.speak_started`
  → full `avatar.transcription` → `avatar.speak_ended` all fired. The "pre-set phrases" wording
  does **not** restrict `speak_text`. The approach is viable; no fallback needed.
- Implementation: never send `avatar.speak_response`; never set `llm_configuration_id`; start
  sessions without a context. (PTT is orthogonal — it controls *when* audio is captured, not
  whether the LLM fires — so restricted mode remains the lever, optionally combined with PTT.)

### 7.2 Session lifecycle
- `token → start → (loop) → stop`. Always `stop_session` on teardown incl. error paths.
- Set `max_session_duration` as a server-side safety net for abandoned sessions.
- Send keep-alive while the conversation is live (`⚠️ VERIFY` Q5: HTTP `keep-alive` vs WS
  `session.keep_alive` for FULL Mode).
- React to `session.stopped` end reasons (e.g. surface `NO_CREDITS` to the operator).

### 7.3 Barge-in / interruption
On `user.speak_started` (or local-STT speech onset) while the avatar is speaking, send
`avatar.interrupt` to stop and clear queued speech, then process the new turn.

### 7.4 Latency / streaming
- **Resolved:** ai-parrot exposes `ask_stream` (partial response streaming). Plan: consume
  `ask_stream` and send `avatar.speak_text` per sentence as text arrives, to minimize TTFB.
  Client-side sentence segmentation is only a fallback for non-streaming agent methods.
- During long `tool_calls`, the avatar is silent; consider a short `avatar.speak_text` filler or
  a listening/idle state cue.

### 7.5 Multi-tenancy
- One avatar session = one tenant + one `agent_name` + one shared `session_id`.
- Per-tenant: `avatar_id`, `voice_id`, STT backend, `interactivity_type`, ElevenLabs secret.
- API key + secrets are tenant-scoped and server-side only.

---

## 8. Open questions

### 8.1 Resolvable by spike / docs (for Claude Code)
- ~~**Q1 (blocker):** speak_text in restricted mode?~~ ✅ **RESOLVED** by `spike_q1_speaktext.py`:
  arbitrary `avatar.speak_text` works with no context. Envelope + `agent-control`/`agent-response`
  topics also confirmed (§5.4).
- ~~**Q2 (blocker):** streaming?~~ **RESOLVED** — ai-parrot has `ask_stream` (partial streaming) → speak per sentence.
- **Q4:** With `LocalSpeechInput`, should the user mic still be published to the LiveAvatar room, or muted/withheld?
- **Q5:** FULL Mode keep-alive — HTTP `/v1/sessions/keep-alive` vs WS `session.keep_alive`?
- **Q6:** Does `@heygen/liveavatar-web-sdk` expose `agent-control`/`agent-response` send/subscribe, or do we use `livekit-client` data channels?
- **Q7:** Does ai-parrot expose a clean "speakable" text field, or must the frontend flatten markdown?

### 8.2 Product / architecture decisions (for Jesús)
- Default STT backend per tenant: LiveAvatar STT vs own (Web Speech / dedicated).
- Interactivity: Conversational (auto-VAD) vs Push-to-Talk default.
- Voice strategy: stock library vs imported ElevenLabs (cost + paid ElevenLabs plan).
- Custom-avatar operator workflow (dashboard) and how `avatar_id`s map to tenants.
- Where the orchestrator lives if frontend-driven proves insufficient (fallback: backend room participant).

---

## 9. Acceptance criteria

1. A FULL Mode session can be minted by the backend (API key never reaches the client) and the
   frontend joins the LiveAvatar room and renders avatar video.
2. With `LiveAvatarSpeechInput`: speaking to the mic yields a `user.transcription`, which is sent
   to ai-parrot, and the avatar speaks ai-parrot's (flattened) response via `avatar.speak_text` —
   and the built-in LLM never produces a competing response (Q1 satisfied).
3. With `LocalSpeechInput`: the same end-to-end loop works using the browser/own STT, with
   LiveAvatar STT unused and no avatar auto-response.
4. Structured outputs (e.g. an ECharts `output`) render in the AgentChat canvas for the same
   `session_id` while the avatar narrates the text.
5. Barge-in: speaking while the avatar talks triggers `avatar.interrupt` and the new turn is processed.
6. Teardown always calls `stop_session`; `max_session_duration` closes abandoned sessions.
7. An imported ElevenLabs voice can be bound via API and selected at session start.
8. Tests: unit for the flattener (markdown → speech) and the STT-seam normalization; an
   integration/e2e test (sandbox session) covering criteria 2 and 4.

---

## 10. Build order (dependency-ordered, for `/sdd-task`)

1. ✅ **GATE PASSED — Q1 validated** (`spike_q1_speaktext.py`, run against the LiveAvatar sandbox):
   arbitrary `avatar.speak_text` is spoken in restricted mode; envelope and
   `agent-control`/`agent-response` topics confirmed (§5.4). The entire spec is cleared to proceed.
2. Backend `LiveAvatarClient` + session-mint endpoint (token/start/stop, secrets, voices/avatars list).
3. Frontend avatar viewer (Web SDK or `livekit-client`) joining the room from minted credentials.
4. Event plumbing: subscribe `agent-response`, send `agent-control` (`speak_text`, `interrupt`).
5. `AbstractSpeechInput` + `LiveAvatarSpeechInput`; wire the transcript→`chatWithAgent`→`speak_text` loop.
6. Speakable-text flattener + per-sentence speaking (apply Q2 outcome).
7. Output bifurcation to AgentChat UI on shared `session_id`.
8. `LocalSpeechInput` (browser STT) as the second STT backend (Q4 outcome).
9. Lifecycle hardening: keep-alive (Q5), `stop_session` on all paths, `max_session_duration`,
   `session.stopped` handling.
10. Multi-tenant config (avatar/voice/STT/interactivity per tenant) + ElevenLabs voice binding.
11. Tests per §9.

> Recommended first step for Claude Code: install the official LiveAvatar Agent Skills
> (`npx skills add heygen-com/liveavatar-agent-skills`) — `liveavatar-integrate` and
> `liveavatar-debug` provide current API details and common-pitfall guidance.

---

## 11. Risks
- **Q1 unresolved** would invalidate the restricted-mode lever; mitigation in §7.1.
- LiveAvatar bills STT/TTS/video on credits per minute; abandoned sessions burn credits
  (mitigated by `max_session_duration` + keep-alive discipline).
- ElevenLabs custom voice requires a paid ElevenLabs plan and ties voice validity to the secret.
- Custom avatars are operator-provisioned (dashboard), not automatable — plan the tenant workflow.

---

## 12. References
- FULL Mode overview / lifecycle / configuration / events / push-to-talk:
  `https://docs.liveavatar.com/docs/full-mode/overview`, `.../lifecycle`, `.../configuration`,
  `.../events`, `.../push-to-talk`
- Custom LLM (OpenAI requirement, not used here): `https://docs.liveavatar.com/docs/full-mode/custom-llm`
- Custom TTS / ElevenLabs voice import: `https://docs.liveavatar.com/docs/full-mode/custom-tts`
- Core concepts — avatars / voices: `https://docs.liveavatar.com/docs/core-concepts/avatars`, `.../voices`
- API reference (sessions, voices, secrets, avatars): `https://docs.liveavatar.com/api-reference/...`
- Docs index (programmatic fetch): `https://docs.liveavatar.com/llms.txt`
- Web SDK: `https://github.com/heygen-com/liveavatar-web-sdk`
- Agent Skills: `https://github.com/heygen-com/liveavatar-agent-skills`

> ai-parrot anchors (verify in repo): `src/lib/api/agent.ts` (`chatWithAgent`,
> `BASE_PATH='/api/v1/agents/chat'`), `src/lib/types/agent.ts` (`AgentChatResponse`),
> `src/lib/services/websocket-service.ts` (`wsService`, `/ws/userinfo`),
> `src/lib/components/agents/AgentChat.svelte`, `src/lib/api/chatInteraction.ts`.
