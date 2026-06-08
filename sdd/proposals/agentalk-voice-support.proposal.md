---
id: FEAT-231
title: "AgentTalk voice support — WS round-trip: STT → text Agent → TTS (Supertonic) → audio + content"
slug: agentalk-voice-support
type: feature
mode: enrichment
status: review
source:
  kind: inline
  jira_key: null
  jira_url: null
  fetched_at: 2026-06-08
  summary_oneline: "Voice support for AgentTalk — WS audio in, STT → LLM → sub-second TTS (Supertonic), return audio + content"
overall_confidence: medium
base_branch: dev
research_state: sdd/state/FEAT-231/
created: 2026-06-08
updated: 2026-06-08
---

# FEAT-231 — AgentTalk voice support (WS round-trip: STT → text Agent → TTS → audio + content)

> **Mode**: enrichment
> **Confidence**: medium (localization high; latency claim + a few impl choices were open)
> **Source**: `inline`
> **Audit**: [`sdd/state/FEAT-231/`](../state/FEAT-231/)

---

## 0. Origin

The original request, preserved verbatim. Full source at
`sdd/state/FEAT-231/source.md`.

> Idea is implementing a feature for receiving (maybe via websockets) an audio
> from the frontend — that's the user's question — transform it to text
> (speech-to-text), send the question to the LLM, then take the text answer
> (under `response.response`), then pass it through a sub-second ML model for
> text-to-speech like Supertonic and return the **audio + content** to the
> frontend. I don't think it is easy to use stream-transfer to send the
> "AIMessage" object to the frontend, because `response.data` or
> `response.output` sometimes are objects, markdown data or JSON structures that
> cannot be transferred in a stream fashion — but more importantly, cannot be
> used for text-to-speech transform.

**Initial signals** (extracted, not interpreted):
- Verbs: receiving, transform, send, take, return → net-new capability, positive polarity.
- Named entities: AgentTalk, WebSocket, speech-to-text, LLM, `response.response`, Supertonic, text-to-speech, AIMessage, `response.data`, `response.output`.
- Components / labels: none (inline source).
- Acceptance criteria provided: no.

---

## 1. Synthesis Summary

AI-Parrot already ships **every primitive this request needs** — they are just
not assembled for AgentTalk. A shared, symmetric voice stack lives in
`parrot.voice`: STT (`VoiceTranscriber` / FasterWhisper, FEAT-039) and a
**decoupled** TTS layer (`VoiceSynthesizer` + `AbstractTTSBackend`, FEAT-213).
The canonical `AIMessage` already separates the speakable text
(`response: str`) from non-speakable payloads (`output`/`data`/`media`),
directly validating the requester's concern about not streaming the raw
`AIMessage`. A full aiohttp WebSocket shell with auth, sessions, and base64
audio framing already exists (`VoiceChatHandler`), and
`LiveVoiceResponse.to_websocket_message` defines the `audio_base64` reply
convention. The work is therefore **enrichment, not greenfield**: add a
Supertonic TTS backend, and wire STT → a text Agent → `synthesize(response)` →
reply `{audio_base64 + content}` in a **new sibling handler** that reuses the
existing transport. This is distinct from the Gemini-Live `VoiceBot`, which
FEAT-213 explicitly deferred.

---

## 2. Codebase Findings

> All entries are grounded in `sdd/state/FEAT-231/findings/`. No fabricated
> paths or symbols.

### 2.1 Localization

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `packages/ai-parrot-integrations/src/parrot/voice/tts/synthesizer.py` | `VoiceSynthesizer._get_backend` | 71-91 | Lazy TTS backend dispatch — **add a `supertonic` branch** | F002, F008 |
| 2 | `packages/ai-parrot-integrations/src/parrot/voice/tts/backend.py` | `AbstractTTSBackend.synthesize` | 17-80 | Abstract TTS contract `SupertonicTTSBackend` must implement | F008 |
| 3 | `packages/ai-parrot-integrations/src/parrot/voice/tts/models.py` | `TTSConfig.backend` | 42-56 | `Literal` enum + `mime_format` to extend for `"supertonic"` | F008 |
| 4 | `packages/ai-parrot-integrations/src/parrot/voice/transcriber/transcriber.py` | `VoiceTranscriber` | — | Existing STT entrypoint for the inbound WS audio buffer | F002, F006 |
| 5 | `packages/ai-parrot-integrations/src/parrot/voice/handler.py` | `VoiceChatHandler` | 293-1024 | Reusable aiohttp WS shell (auth, sessions, `_handle_audio_data`); currently hard-wired to Gemini `VoiceBot` | F007 |
| 6 | `packages/ai-parrot/src/parrot/models/responses.py` | `AIMessage` | 72-110 | Source of speakable `.response` (str) vs non-speakable `.output`/`.data`/`.media` | F003 |
| 7 | `packages/ai-parrot/src/parrot/models/responses.py` | `AgentResponse` | 1022-1056 | Wrapper Agents return — `response: AIMessage`, `data`, `output` | F003 |
| 8 | `packages/ai-parrot/src/parrot/clients/live.py` | `LiveVoiceResponse.to_websocket_message` | 189-213 | Precedent for the `audio_base64` WS reply payload | F004 |
| 9 | `packages/ai-parrot/src/parrot/bots/voice.py` | `VoiceBot` | 76-571 | Native Gemini-Live S2S bot — the path this feature is **NOT** (out of scope) | F001 |

### 2.2 Constraints Discovered

- **Only `AIMessage.response` is speakable.** `output`/`data` are `Any`
  (dataframes/markdown/JSON); `media`/`images`/`files` are paths. The TTS path
  must read `.response` (str); everything else travels as a separate structured
  `content` block, never through the synthesizer. *This is exactly the
  requester's stated concern, confirmed in the model.* *Evidence*: F003

- **The voice stack lives in `ai-parrot-integrations`, not core.** A generic
  AgentTalk voice endpoint that imports `parrot.voice.*` introduces a
  core→integrations dependency. Host the new handler **in the integrations
  distribution** (alongside `VoiceChatHandler`) or guard the import behind an
  extra, mirroring how the integrations themselves are optional. *Evidence*: F002, F007

- **`VoiceChatHandler.bot_factory` is typed `Callable[[], VoiceBot]`** and routes
  audio into a native Gemini session (`audio_queue` / `gemini_responding`). A
  text-Agent + synthesizer pipeline cannot reuse that routing directly — hence a
  **sibling handler** that reuses the auth/session/recording scaffolding.
  *Evidence*: F007

- **FEAT-213 reserved `elevenlabs`/`openai` as `ValueError` stubs** and built the
  TTS layer mirroring the transcriber; faster-whisper (STT) is an optional
  extras dependency. Supertonic (ONNX + model weights) should be an
  **extras-gated** backend with **graceful degradation** (text-only) if
  unavailable — FEAT-213's G5. *Evidence*: F005, F008

- **Audio crosses the WS as base64-in-JSON in both directions** (`_handle_audio_data`
  decodes inbound; `to_websocket_message` encodes outbound). Keep the same
  envelope. *Evidence*: F004, F007

### 2.3 Recent History (Relevant)

| Commit | When | Message | Touched files |
|--------|------|---------|---------------|
| `49536110` | monorepo migration | `feat(monorepo-migration): TASK-398 — Workspace Scaffolding` | `bots/voice.py` |

`bots/voice.py` is untouched since the monorepo move — `VoiceBot` is stable and
not under active churn, so building the new path *beside* it (not on top of it)
carries low regression risk. *Evidence*: F001

---

## 3. Probable Scope  *(mode = enrichment)*

### What's New

- **`SupertonicTTSBackend(AbstractTTSBackend)`** at
  `parrot/voice/tts/supertonic_backend.py` — extras-gated optional dependency
  (ONNX model + weights), implementing `synthesize(text, *, voice, mime_format)`.
- **`AgentTalkVoiceHandler`** (sibling of `VoiceChatHandler`) — a new aiohttp WS
  endpoint that, per turn: base64-decode inbound audio → `VoiceTranscriber` →
  resolve the Agent by `agent_id` (BotManager) and `await agent.invoke(...)` →
  take `AIMessage.response` → `VoiceSynthesizer.synthesize(...)` → reply a single
  `{type: "voice_response", audio_base64, audio_format, content}` message where
  `content` carries `output`/`data`/`media` for display.

### What Changes

- **`TTSConfig.backend`** `Literal[...]` extended to include `"supertonic"`;
  **`VoiceSynthesizer._get_backend`** gains a `"supertonic"` dispatch branch.
  *Evidence*: F008
- (Optional, decided against) generalizing `VoiceChatHandler` — **not** chosen;
  the Gemini path stays untouched (sibling handler instead).

### What's Untouched (Non-Goals)

- The **Gemini-Live `VoiceBot` / native speech-to-speech** path (explicitly
  deferred by FEAT-213).
- **STT internals** (`VoiceTranscriber` / FasterWhisper) — reused as-is.
- **`AIMessage` / `AgentResponse` models** — consumed, not modified.
- **Telegram / MSTeams voice wiring** (FEAT-213 / FEAT-039) — unaffected.
- **Streaming partial audio** — out of scope; single buffered round-trip only.

### Patterns to Follow

- Mirror **FEAT-213**: decoupled `AbstractTTSBackend` + lazy `VoiceSynthesizer`
  dispatch; degrade to text-only on TTS failure (G5). *Evidence*: F005, F008
- Mirror **`LiveVoiceResponse.to_websocket_message`** for the outbound
  `audio_base64` envelope. *Evidence*: F004
- Mirror the **msteams/telegram** `transcribe → _process_transcribed_message →
  agent` flow. *Evidence*: F006
- Mirror **`VoiceChatHandler.setup_routes`** (`app.router.add_get(...)`) for
  endpoint registration. *Evidence*: F007, F009

### Integration Risks

- **Supertonic deps + weights.** Gate behind an extra; degrade gracefully if the
  model/runtime is missing. *Evidence*: F005, F008
- **core→integrations dependency** for a generic web voice endpoint — keep the
  handler in the integrations package. *Evidence*: F002
- **Browser audio format.** `TTSConfig.mime_format` defaults to `audio/ogg`
  (Telegram-oriented); the web player will default to `audio/wav` (see U5).
  *Evidence*: F008

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | A decoupled STT+TTS stack (`parrot.voice.transcriber` + `parrot.voice.tts`) already exists and is reusable | F002, F005 | high | Direct read of package `__init__` + FEAT-213 spec |
| C2 | `AIMessage.response` (str) is the correct, isolated TTS source; `output`/`data` are non-speakable | F003 | high | Direct read of field definitions + docstrings |
| C3 | A full aiohttp WS handler (`VoiceChatHandler`) with auth/sessions/base64 audio already exists | F007 | high | Direct read of class + `_handle_audio_data` |
| C4 | `VoiceChatHandler` is hard-wired to the Gemini-Live `VoiceBot` and must be mirrored for a text-Agent pipeline | F007, F001 | high | `bot_factory` typed `Callable[[], VoiceBot]`; audio routed into native Gemini session |
| C5 | Adding Supertonic is one new `AbstractTTSBackend` + one `Literal`/dispatch entry | F008 | high | Read of synthesizer dispatch + abstract contract + `TTSConfig` |
| C6 | The audio-over-WS envelope is base64-in-JSON in both directions | F004, F007 | high | `to_websocket_message` + `_handle_audio_data` both b64 |
| C7 | Gemini-Live native S2S is out of scope (deferred by FEAT-213) | F005, F001 | high | Spec text explicitly postpones it |
| C8 | Supertonic delivers sub-second TTS latency on-device | — | low | Upstream claim; not verified in-repo (no web fetch). Latency is hardware/ONNX-runtime dependent |

Distribution: **7** high, **0** medium, **1** low.

> The single `low` claim (C8) is the *motivation* for choosing Supertonic, not a
> blocker for the architecture — the backend is swappable, so if Supertonic
> misses sub-second on target hardware, `TTSConfig.backend` falls back to Google.
> Overall confidence is held at **medium** because the latency premise and a few
> implementation choices (now resolved in §5) were genuinely open.

---

## 5. Open Questions

### Resolved (during proposal phase)

- [x] **U1 — Transport: extend `VoiceChatHandler` vs sibling handler?** —
  *Resolved*: **Sibling handler** — a new `AgentTalkVoiceHandler` reuses
  `VoiceChatHandler`'s auth/session/recording code, leaving the Gemini path
  untouched. *Resolves*: C4
- [x] **U2 — Supertonic now or later?** — *Resolved*: **Supertonic from day one**
  — add `SupertonicTTSBackend` now, extras-gated, with graceful degradation to
  text-only on failure/unavailability. *Resolves*: C5, C8
- [x] **U3 — Single round-trip vs streamed audio?** — *Resolved*: **Single
  buffered round-trip** — audio in → one `{audio_base64 + content}` reply.
- [x] **U4 — Which Agent answers?** — *Resolved*: **Per `agent_id` via
  BotManager** — resolve the agent from `agent_id` (URL/auth), call
  `agent.invoke(...)`, consume the returned `AgentResponse`/`AIMessage`.
  *Resolves*: C2
- [x] **U5 — Output audio format?** — *Resolved (agent default, non-blocking)*:
  default **`audio/wav`** for the web player (broadest browser support),
  negotiable via the `start_session` message.

### Unresolved (defer to spec / implementation)

- _None._ All material unknowns were resolved during the proposal phase.

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-231`** — *Rationale*: localization is high-confidence and every
building block already exists; this is bounded enrichment with all design forks
resolved in §5. A spec can pin the `AgentTalkVoiceHandler` surface, the
`SupertonicTTSBackend` contract + extras packaging, the WS message schema, and
the BotManager agent resolution.

### Alternatives

- **`/sdd-brainstorm FEAT-231`** — only if you later want to revisit the
  transport fork (sibling vs extend) or single-round-trip vs streaming as
  competing architectures. Given §5, this is likely unnecessary.
- **`/sdd-task FEAT-231`** — not recommended; the feature spans ≥3 files
  (backend, handler, config/packaging) and warrants a spec first.

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-231/state.json` |
| Source (raw) | `sdd/state/FEAT-231/source.md` |
| Research plan | `sdd/state/FEAT-231/research_plan.json` |
| Findings (digests) | `sdd/state/FEAT-231/findings/F001..F009-*.md` |
| Synthesis (JSON) | `sdd/state/FEAT-231/synthesis.json` |

**Budget consumed**:
- Files read: 9 / 40
- Grep calls: 7 / 25
- Git calls: 1 / 10
- Truncated: **no**

**Mode determination**: `auto` → resolved to **enrichment** (net-new capability,
but built almost entirely on existing `parrot.voice` STT/TTS + `VoiceChatHandler`
transport).

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal` |
| Synthesis prompt | `sdd/templates/synthesis.prompt.md` |
| Plan prompt | `sdd/templates/research_plan.prompt.md` |
| Schema versions | state=1.0, synthesis=1.0, research_plan=1.0 |
| Operator | jesuslarag (via Claude) |
