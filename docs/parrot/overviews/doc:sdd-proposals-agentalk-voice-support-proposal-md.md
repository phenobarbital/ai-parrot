---
type: Wiki Overview
title: 'FEAT-231 — AgentTalk voice support (REST round-trip: audio → STT → text Agent
  → TTS → audio + content)'
id: doc:sdd-proposals-agentalk-voice-support-proposal-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The original request, preserved verbatim. Full source at
relates_to:
- concept: mod:parrot.bots.voice
  rel: mentions
- concept: mod:parrot.handlers.agent
  rel: mentions
- concept: mod:parrot.handlers.csp
  rel: mentions
- concept: mod:parrot.voice
  rel: mentions
- concept: mod:parrot.voice.handler
  rel: mentions
- concept: mod:parrot.voice.transcriber.backend
  rel: mentions
- concept: mod:parrot.voice.transcriber.faster_whisper_backend
  rel: mentions
- concept: mod:parrot.voice.tts.backend
  rel: mentions
- concept: mod:parrot.voice.tts.google_backend
  rel: mentions
- concept: mod:parrot.voice.tts.models
  rel: mentions
- concept: mod:parrot.voice.tts.synthesizer
  rel: mentions
---

---
id: FEAT-231
title: "AgentTalk voice support — REST round-trip: audio in → STT → text Agent → TTS (Supertonic) → audio + content"
slug: agentalk-voice-support
type: feature
mode: enrichment
status: review
source:
  kind: inline
  jira_key: null
  jira_url: null
  fetched_at: 2026-06-08
  summary_oneline: "Voice support for AgentTalk — multipart audio in, STT → LLM-agnostic Agent → sub-second TTS (Supertonic), return audio + content over the existing REST endpoint"
overall_confidence: high
base_branch: dev
research_state: sdd/state/FEAT-231/
created: 2026-06-08
updated: 2026-06-09
revision: "rev4 — U8 resolved via direct read of parrot.voice TTS+transcriber: STT seam (AbstractTranscriberBackend) confirmed, Moonshine = 1 new backend; C6–C8 promoted to high. rev3 — U6/U7 resolved (Option B + Moonshine in scope). rev2 — re-localized onto AgentTalk REST; decoupled from Gemini-Live WS path"
---

# FEAT-231 — AgentTalk voice support (REST round-trip: audio → STT → text Agent → TTS → audio + content)

> **Mode**: enrichment
> **Confidence**: high (host, transport, handler shape, and the full STT+TTS
> backend set are all verified against source; only the Supertonic latency claim
> stays low, and it is non-blocking — the backend is swappable)
> **Source**: `inline`
> **Audit**: [`sdd/state/FEAT-231/`](../state/FEAT-231/)

> **rev2 correction note.** rev1 localized this feature on
> `parrot.voice.handler.VoiceChatHandler` — the aiohttp **WebSocket** handler
> hard-wired to the Gemini-Live `VoiceBot` — and proposed a *sibling of that WS
> handler*. That is the wrong host. The capability requested is a voice I/O
> wrapper around the **existing AgentTalk REST endpoint**
> (`parrot.handlers.agent.AgentTalk`, a navigator `BaseView`), whose `bot.ask()`
> dispatch is already **LLM-client-agnostic** and already accepts multipart
> uploads. rev2 re-localizes the work there, keeps the (correct) Supertonic /
> `AbstractTTSBackend` parts, and drops WS entirely. The Gemini-Live S2S
> `VoiceBot` remains a genuinely separate, deferred feature.

---

## 0. Origin

The original request, preserved verbatim. Full source at
`sdd/state/FEAT-231/source.md`.

> Idea is implementing a feature so the **AgentTalk** handler (the REST API used
> to talk to AI agents) can receive a **voice note** as the user's question,
> transcribe it with a speech-to-text model (Whisper or Moonshine), send the
> question to the agent **exactly like a normal text agent call**, and then take
> the agent's **text** answer (`response.response`, not the structured payload)
> and pass it through a sub-second text-to-speech model (e.g. Supertonic),
> returning **audio + content** to the frontend. It does not matter if it ends up
> being a "clone" of AgentTalk, but cloning would duplicate code; the feature
> must stay **agnostic to the LLM client** and centered on the cycle
> *speech-to-text → agent → text-to-speech*, not on reusing the Gemini-Live voice
> agent.

**Initial signals** (extracted, not interpreted):
- Verbs: receive, transcribe, send, take, return → net-new capability, positive polarity.
- Named entities: AgentTalk, REST API, voice note, speech-to-text, Whisper, Moonshine, agent, `response.response`, Supertonic, text-to-speech, audio + content.
- Explicit constraints: **LLM-client agnostic**; **do not duplicate AgentTalk**; **do not build on the Gemini-Live voice agent**.
- Acceptance criteria provided: no.

---

## 1. Synthesis Summary

`AgentTalk` (`parrot.handlers.agent.AgentTalk`) already implements the entire
*text → agent → formatted reply* cycle this feature needs; it is missing only the
two audio transducers. It is a navigator **`BaseView`** (REST), **not** a
WebSocket handler and **not** coupled to any LLM client: it resolves the agent
via `BotManager` and calls `await bot.ask(question=query, …, output_mode=…)`,
which returns an `AIMessage`. The bot owns whatever client (Google / OpenAI /
Claude / Groq), so the endpoint is **agnostic by construction**. AgentTalk
*already* accepts multipart uploads (`handle_upload` → `_handle_attachments` →
`bot.handle_files`), and already carries the auth/PBAC/HITL/session/streaming
machinery any new endpoint would otherwise have to re-implement.

The work is therefore a **voice I/O adapter around the existing REST flow**:
(1) on the way **in**, transcribe an audio attachment to `query` via STT, then
fall through to the unchanged `bot.ask()` path; (2) on the way **out**, after
`bot.ask()` returns, synthesize the *speakable* field `AIMessage.response` (str)
with a new Supertonic TTS backend and attach `audio_base64` to the JSON envelope,
while `output` / `data` / `media` continue to ride along as structured `content`.

This is **enrichment, not greenfield**, and crucially it reuses **AgentTalk**
(not `VoiceChatHandler`). From `parrot.voice` we reuse only the model-level
primitives — `VoiceTranscriber` (STT) and `VoiceSynthesizer` + `AbstractTTSBackend`
(TTS). No WebSocket, no Gemini session routing, no base64-in-JSON WS framing.

---

## 2. Codebase Findings

> Entries under §2.1.a were verified by **direct read of the uploaded
> `agent.py`** during rev2. Entries under §2.1.b (the `parrot.voice` stack) are
> **carried over from rev1 findings F001–F009 and have NOT been re-read** in this
> revision — they are marked `⚠️ VERIFY` and must be re-confirmed before spec.

### 2.1.a Localization — host handler (verified, `agent.py`)

| # | Module · Symbol | Anchor (grep) | Role |
|---|------------------|---------------|------|
| H1 | `parrot.handlers.agent` · `AgentTalk(BaseView)` | `class AgentTalk(BaseView):` | The REST host. `@is_authenticated()` `@user_session()`. **This is where the feature belongs.** |
| H2 | `AgentTalk.post` | `async def post(self):` | Main chat dispatch — extracts `query`, resolves bot, calls `bot.ask`, formats reply. **Voice-in / voice-out branch points.** |
| H3 | `AgentTalk._resolve_bot` | `async def _resolve_bot(` → `await manager.get_bot(agent_name)` | Agent resolution via `BotManager` (`self.request.app.get('bot_manager')`). LLM-agnostic. Reuse as-is. |
| H4 | `AgentTalk.handle_upload` (inherited `BaseView`) | `attachments, data = await self.handle_upload()` | **Multipart already supported.** Inbound voice note enters here — no new transport needed. |
| H5 | `AgentTalk._handle_attachments` | `async def _handle_attachments(` → `bot.handle_files(attachments)` | Existing attachment→bot path; reference for how an audio attachment is routed. |
| H6 | `query` extraction | `query = data.pop('query', None)` | After STT, the transcript is injected here; the rest of `post()` is untouched. |
| H7 | `bot.ask(...) -> AIMessage` | `response: AIMessage = await bot.ask(` | The single agnostic dispatch. TTS reads `response.response` from this. |
| H8 | `AgentTalk._prepare_response` / `OutputMode` / `OutputFormatter` | `def _prepare_response(`, `from ..outputs import OutputMode, OutputFormatter` | Existing output negotiation. **TTS output = one extra `audio_base64` field on the JSON envelope**, not a new transport. |
| H9 | `AgentTalk._handle_stream_response` | `async def _handle_stream_response(` → `web.StreamResponse` (`text/plain`) | Existing chunked text streaming; out of scope for v1 (single buffered round-trip) but documents the streaming seam. |
| H10 | `AgentTalk._check_pbac_agent_access` | `action="agent:chat"` | PBAC guard — **inherited free** by a subclass. No re-implementation. |
| H11 | HITL / auth envelopes | `class PausedEnvelope`, `except HumanInteractionInterrupt`, `AuthRequiredEnvelope(` | SUSPEND/auth paths — **inherited free** by a subclass. |
| H12 | Speakable vs non-speakable | `from ..models.responses import AIMessage, AgentResponse` | `AIMessage.response` (str) → TTS; `output`/`data`/`media` → structured `content`. |

> **Package path of `agent.py`**: relative imports (`from ..models.responses`,
> `from parrot.handlers.csp import …`, `from .web_hitl import …`) place it at
> `packages/ai-parrot/src/parrot/handlers/agent.py` (module `parrot.handlers.agent`).
> `⚠️ VERIFY` the exact distribution path; the module name is high-confidence.
> **Route registration** (`/api/v1/agents/chat/{agent_id}`) is wired outside this
> file (navigator `BaseView` routing). `⚠️ VERIFY` where routes are registered so
> the voice route can be added there.

### 2.1.b Localization — voice primitives (verified rev4, direct read)

> Verified by direct read of the uploaded TTS files (`tts/backend.py`,
> `tts/synthesizer.py`, `tts/google_backend.py`) and transcriber files
> (`transcriber/backend.py`, `transcriber/faster_whisper_backend.py`).

| # | Module · Symbol | Anchor (grep) | Role | Status |
|---|------------------|---------------|------|--------|
| V1 | `parrot.voice.tts.synthesizer` · `VoiceSynthesizer._get_backend` | `if backend_name == "google":` | Lazy TTS dispatch: `google` impl; `elevenlabs`/`openai` are `ValueError` stubs. **Add a `supertonic` branch.** | verified |
| V2 | `parrot.voice.tts.backend` · `AbstractTTSBackend.synthesize` | `async def synthesize(self, text, *, voice=..., mime_format="audio/ogg", language=...)` → `SynthesisResult` | The contract `SupertonicTTSBackend` implements. **Signature includes `language`** (rev1 omitted it). | verified |
| V3 | `parrot.voice.tts.google_backend` · `GoogleTTSBackend` | `return SynthesisResult(audio=audio_bytes, mime_format=mime_format)` | Reference impl. **Returns raw PCM**; `mime_format` is a *label*, no container conversion — caller's job. | verified |
| V4 | `parrot.voice.transcriber.backend` · `AbstractTranscriberBackend.transcribe` | `async def transcribe(self, audio_path: Path, language=None)` → `TranscriptionResult` | **The STT seam already exists.** `MoonshineSTTBackend` plugs in here. **Input is a `Path`, not bytes.** | verified |
| V5 | `parrot.voice.transcriber.faster_whisper_backend` · `FasterWhisperBackend(AbstractTranscriberBackend)` | `await asyncio.to_thread(self._transcribe_sync, ...)` | Default STT backend; lazy model load + `asyncio.to_thread` for CPU-bound work. | verified |
| V6 | second STT backend already shipped | `transcriber/backend.py` docstring: "Both FasterWhisperBackend and OpenAIWhisperBackend implement this interface" | Proves the `VoiceTranscriber` service **already has a config-driven backend selector** (≥2 impls). | verified (impl), `⚠️ VERIFY` config field name |
| V7 | `parrot.voice.tts.models` · `TTSConfig.backend` (`Literal`) | referenced as `self.config.backend` in V1 | Extend the `Literal` with `"supertonic"`. `models.py` not uploaded; dispatch site confirmed via V1. | `⚠️ VERIFY` Literal members |

> **NOT reused (rev1 mistake):** `parrot.voice.handler.VoiceChatHandler` and
> `parrot.bots.voice.VoiceBot` (the Gemini-Live WS / native S2S path). Not the
> host; not mirrored.

### 2.2 Constraints Discovered

- **Only `AIMessage.response` is speakable.** `output`/`data` are `Any`
  (dataframes / markdown / JSON); `media`/`images`/`files` are paths. The TTS
  path reads `.response` (str); everything else travels as a separate structured
  `content` block, never through the synthesizer. *This is exactly the
  requester's stated concern.* *Evidence*: H7, H12.

- **AgentTalk is already LLM-agnostic and already multipart-capable.** No new
  transport, no new auth, no new session model is required. The voice feature is
  a transcode on the way in and a transcode on the way out. *Evidence*: H3, H4,
  H7.

- **Dependency direction is the real architectural fork.** `AgentTalk` lives in
  the **core** `ai-parrot` package; the voice stack lives in
  **`ai-parrot-integrations`**. Importing `parrot.voice.*` *from* core inverts the
  dependency. The clean resolution is to host the voice-capable view **in the
  integrations package as a subclass** (`AgentVoiceTalk(AgentTalk)`):
  integrations → core is the allowed direction, and the subclass may import
  `parrot.voice.*` freely. *Evidence*: §2.1.a vs §2.1.b. — *(rev1 detected this
  risk but mis-resolved it by placing a WS sibling next to `VoiceChatHandler`.)*

- **STT seam exists; Moonshine is one new backend.** `AbstractTranscriberBackend`
  already abstracts transcription and already has ≥2 impls (FasterWhisper,
  OpenAIWhisper), so the `VoiceTranscriber` service has a config-driven selector.
  **FasterWhisper stays the default**; `MoonshineSTTBackend(AbstractTranscriberBackend)`
  is a new opt-in backend + one dispatch entry — symmetric to `SupertonicTTSBackend`,
  **no new abstraction required**. *Evidence*: V4, V5, V6.

- **STT input is a file `Path`, not bytes.** `transcribe(audio_path: Path, …)`.
  The inbound audio attachment must be persisted to a tempfile before transcription
  (`tempfile` is already imported in `agent.py`). CPU-bound work runs under
  `asyncio.to_thread` in the backend. *Evidence*: V4, V5; H4.

- **TTS returns bytes whose container is the caller's responsibility.**
  `GoogleTTSBackend` emits raw PCM; `mime_format` is only a label. For the web
  player default (`audio/wav`), `AgentVoiceTalk` (or `SupertonicTTSBackend`) must
  emit a browser-playable container. `SupertonicTTSBackend.synthesize` must
  therefore return audio in (or be wrapped to) a playable format and set
  `SynthesisResult.mime_format` truthfully. *Evidence*: V2, V3.

- **Graceful degradation is the handler's job, not the synthesizer's.**
  `VoiceSynthesizer._get_backend` *raises* `ValueError` for missing/unknown
  backends; it does not degrade. `AgentVoiceTalk` must wrap `synthesize(...)` in
  try/except (`ValueError`/`RuntimeError`/`ImportError`) and fall back to
  **text-only** (omit `audio_base64`) when Supertonic is unavailable. *Evidence*: V1.

- **Supertonic is extras-gated.** ONNX runtime + model weights behind an optional
  extra; degrade per the constraint above. Mirrors rev1's G5. *Evidence*: V1, V2.

### 2.3 Recent History (Relevant)

| Commit | When | Message | Touched files |
|--------|------|---------|---------------|
| `49536110` | monorepo migration | `feat(monorepo-migration): TASK-398 — Workspace Scaffolding` | `bots/voice.py` |

`bots/voice.py` (the Gemini path) is untouched since the monorepo move and is
**out of scope** here, so building beside it carries no regression risk.

---

## 3. Probable Scope  *(mode = enrichment)*

### Decided shape — Option B: `AgentVoiceTalk(AgentTalk)` subclass in integrations *(locked, U7)*

A thin REST subclass that **inherits** agent resolution, PBAC, HITL, auth
envelopes, session handling, and output negotiation, and **overrides only two
seams**:

1. **Inbound (STT).** If the request carries an audio attachment (or
   `input_mode=voice` / `Content-Type: audio/*`), persist the audio attachment to
   a tempfile and run it through STT (`VoiceTranscriber`, backend selectable:
   `faster_whisper` default | `moonshine`) to produce the `query` string, then
   delegate to the inherited `post()` text path unchanged.
2. **Outbound (TTS).** After `bot.ask()` returns the `AIMessage`, synthesize
   `response.response` via `VoiceSynthesizer.synthesize(...)` and attach
   `audio_base64` + `audio_format` to the JSON envelope built by the inherited
   `_prepare_response`; `output`/`data`/`media` stay in `content`.

New route: `POST /api/v1/agents/voice/{agent_id}`. The text endpoint
`/api/v1/agents/chat/{agent_id}` is untouched.

### What's New

- **`SupertonicTTSBackend(AbstractTTSBackend)`** at
  `parrot/voice/tts/supertonic_backend.py` — extras-gated (ONNX + weights),
  implementing `synthesize(text, *, voice=None, mime_format="audio/ogg",
  language=None) -> SynthesisResult` (full verified V2 signature). Must return a
  browser-playable container (or be wrapped to one) and set `mime_format`
  truthfully — `mime_format` is a label, not a converter (V2, V3).
- **`MoonshineSTTBackend(AbstractTranscriberBackend)`** (new, U6) at
  `parrot/voice/transcriber/moonshine_backend.py` `⚠️ VERIFY filename` —
  extras-gated, implementing `transcribe(audio_path: Path, language=None) ->
  TranscriptionResult` (verified V4 contract). Plugs into the **existing** STT
  seam (V4–V6); CPU/GPU work under `asyncio.to_thread` (mirror V5). Default
  transcriber stays **FasterWhisper**; Moonshine is opt-in for sub-second STT.
- **`AgentVoiceTalk(AgentTalk)`** in `ai-parrot-integrations` (e.g.
  `parrot/voice/handlers/agent_voice.py` `⚠️ VERIFY package layout`) — the REST
  subclass: tempfile-persist + STT inbound, `bot.ask()` unchanged, synthesize
  `AIMessage.response` outbound with try/except → text-only degradation,
  registering `POST /api/v1/agents/voice/{agent_id}`.

### What Changes

- **`TTSConfig.backend`** `Literal[...]` extended with `"supertonic"`;
  **`VoiceSynthesizer._get_backend`** gains a `"supertonic"` dispatch branch
  (verified site V1; `⚠️ VERIFY` the `Literal` members in `tts/models.py`, V7).
- **STT config** gains a `"moonshine"` selector value + dispatch entry on the
  `VoiceTranscriber` service, mirroring the TTS dispatch and the existing
  FasterWhisper/OpenAIWhisper selection (`⚠️ VERIFY` the config field name on the
  transcriber service, V6).

### What's Untouched (Non-Goals)

- **`AgentTalk.post()` text path** — inherited, not modified (Option B).
- The **Gemini-Live `VoiceBot` / native S2S** path and **`VoiceChatHandler`**
  (WS) — explicitly **not** the host and not mirrored.
- **`AIMessage` / `AgentResponse` models** — consumed, not modified.
- **STT model internals** — FasterWhisper reused as-is; a new `MoonshineSTTBackend`
  is added behind the same seam (in scope, U6), not a modification of Whisper.
- **Telegram / MSTeams voice wiring** — unaffected.
- **Streaming partial audio** — out of scope; single buffered round-trip only.

### Rejected alternative — Option A: in-place branches in `AgentTalk.post()`

Add the STT/TTS branches directly inside core `AgentTalk`, gated by a lazy,
extras-guarded import of `parrot.voice.*` with text-only graceful degradation.
**Rejected (U7)** in favour of Option B: it inverts the package dependency
(core→integrations) and modifies the text hot-path. Kept here only as the record
of the trade-off considered.

| | Option A (in-place, core) | **Option B (subclass, integrations) — recommended** |
|---|---|---|
| Code duplication | none | none (inherits) |
| Dependency direction | core → integrations (lazy import; *smell*) | integrations → core (correct) |
| Text hot-path | modified | pristine |
| Endpoints | one (negotiated) | two (`/chat`, `/voice`) |
| LLM-agnostic | yes (`bot.ask`) | yes (`bot.ask`) |
| Failure isolation | shared with text path | isolated |

Option A is acceptable if a single endpoint is a hard product requirement;
otherwise Option B is cleaner on the monorepo boundary the team already guards.

### Patterns to Follow

- Reuse **`AgentTalk`** (resolution, PBAC, HITL, output negotiation, multipart),
  **not** `VoiceChatHandler`. *Evidence*: §2.1.a.
- Mirror **FEAT-213**: decoupled `AbstractTTSBackend` + lazy `VoiceSynthesizer`
  dispatch (verified V1, V2). Text-only degradation is implemented in the
  **handler** (the synthesizer raises, it does not degrade).
- Reply envelope = the **existing AgentTalk JSON envelope** + an `audio_base64`
  field (REST), *not* a WS message. *Evidence*: H8.

### Integration Risks

- **Dependency direction** — resolved by Option B (subclass in integrations).
- **Supertonic deps + weights** — extras-gate; handler degrades to text-only.
- **Browser audio format** — outbound default `audio/wav`; `GoogleTTSBackend`
  returns raw PCM and `mime_format` does not convert (V3), so `SupertonicTTSBackend`
  must emit/​wrap a playable container and label it truthfully. Negotiable per request.
- **STT latency vs Supertonic latency** — Moonshine keeps the round-trip
  sub-second; both STT and TTS backends are swappable.

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | `AgentTalk` is a REST `BaseView` whose `bot.ask()` dispatch is LLM-client-agnostic | H1, H3, H7 | high | Direct read of `agent.py` |
| C2 | `AgentTalk` already accepts multipart uploads (inbound audio needs no new transport) | H4, H5 | high | Direct read (`handle_upload`, `_handle_attachments`) |
| C3 | `AIMessage.response` (str) is the isolated TTS source; `output`/`data` non-speakable | H7, H12 | high | Direct read of fields + usage |
| C4 | PBAC / HITL / auth / session / output negotiation are inheritable from `AgentTalk` (no re-impl) | H8, H10, H11 | high | Direct read |
| C5 | A subclass in integrations resolves the core→integrations dependency cleanly | §2.1.a/b | high | Dependency direction is integrations→core |
| C6 | Adding Supertonic is one new `AbstractTTSBackend` impl + one `_get_backend`/`Literal` entry | V1, V2 | high | Direct read: dispatch site + abstract contract |
| C7 | STT seam exists; Moonshine = one new `AbstractTranscriberBackend` impl + selector entry | V4, V5, V6 | high | Abstract + ≥2 existing impls; no new abstraction |
| C8 | The voice stack lives in `parrot.voice` (TTS/STT), separate from core `AgentTalk` | V1–V6 | high | Direct read of both subpackages |
| C9 | `VoiceChatHandler` / Gemini-Live `VoiceBot` is the wrong host and must NOT be mirrored | source, §2.1.a | high | Explicit requester constraint + host found in `agent.py` |
| C10 | Supertonic delivers sub-second TTS on target hardware | — | low | Upstream claim; not verified in-repo. Backend is swappable, so non-blocking |

Distribution: **9** high, **0** medium, **1** low.

> Only C10 remains low — it is the *motivation* for choosing Supertonic, not an
> architectural dependency. If Supertonic misses sub-second on target hardware,
> `TTSConfig.backend` falls back to Google (or any other backend) with no design
> change. Everything load-bearing is now verified against source.

---

## 5. Open Questions

### Resolved (during rev2)

- [x] **U1 — Host: `VoiceChatHandler` (WS) vs `AgentTalk` (REST)?** — *Resolved*:
  **`AgentTalk` (REST).** The WS/Gemini path was the rev1 mistake. *Resolves*: C1, C9.
- [x] **U2 — Reuse axis: reuse `VoiceChatHandler` scaffolding vs reuse `AgentTalk`?**
  — *Resolved*: reuse **`AgentTalk`** (subclass, Option B); from `parrot.voice`
  reuse only `VoiceTranscriber` + `VoiceSynthesizer`/`AbstractTTSBackend`.
  *Resolves*: C4, C5.
- [x] **U3 — Single round-trip vs streamed audio?** — *Resolved*: **single
  buffered round-trip** for v1; streaming seam noted (H9) for later.
- [x] **U4 — Which Agent answers?** — *Resolved*: per `agent_id` via the inherited
  `_resolve_bot`/`BotManager`; call `bot.ask(...)` unchanged. *Resolves*: C1.
- [x] **U5 — Output audio format?** — *Resolved (non-blocking)*: default
  **`audio/wav`** for the web player; negotiable per request.
- [x] **U6 — STT backend default and selector.** — *Resolved*: **FasterWhisper
  default, Moonshine opt-in**; Moonshine is built **in this feature** as a new
  `MoonshineSTTBackend` (in scope), symmetric to `SupertonicTTSBackend`.
  *Resolves*: C7.
- [x] **U7 — Option A vs Option B.** — *Resolved*: **Option B** — subclass
  `AgentVoiceTalk(AgentTalk)` in `ai-parrot-integrations`, one extra route
  `/api/v1/agents/voice/{agent_id}`. Option A rejected (dependency inversion +
  hot-path edit). *Resolves*: C5.

- [x] **U8 — Voice-stack seams + STT abstraction.** — *Resolved (rev4, direct
  read)*: `AbstractTTSBackend` + `VoiceSynthesizer._get_backend` confirmed (V1,
  V2); **`AbstractTranscriberBackend` seam confirmed with ≥2 existing impls**
  (FasterWhisper, OpenAIWhisper — V4–V6), so `MoonshineSTTBackend` is one new
  backend, no new abstraction. *Resolves*: C6, C7, C8.

### Residual (non-blocking, 1-line greps during spec)

- [ ] **R1** — exact `Literal` members of `TTSConfig.backend` in
  `tts/models.py` (to add `"supertonic"`). `models.py` not uploaded. (V7)
- [ ] **R2** — the config field name on the `VoiceTranscriber` service that
  selects the STT backend (to add `"moonshine"`). Service file not uploaded;
  existence confirmed via V6. *(Neither blocks the spec — both are

…(truncated)…
