---
type: Wiki Overview
title: 'Feature Specification: AgentTalk Voice Support (REST round-trip: audio → STT
  → text Agent → TTS → audio + content)'
id: doc:sdd-specs-agentalk-voice-support-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The **AgentTalk** REST endpoint (`parrot.handlers.agent.AgentTalk`) implements
  the
relates_to:
- concept: mod:parrot.bots.voice
  rel: mentions
- concept: mod:parrot.handlers.agent
  rel: mentions
- concept: mod:parrot.handlers.agent_voice
  rel: mentions
- concept: mod:parrot.manager.manager
  rel: mentions
- concept: mod:parrot.voice
  rel: mentions
- concept: mod:parrot.voice.handler
  rel: mentions
- concept: mod:parrot.voice.transcriber
  rel: mentions
- concept: mod:parrot.voice.transcriber.backend
  rel: mentions
- concept: mod:parrot.voice.transcriber.faster_whisper_backend
  rel: mentions
- concept: mod:parrot.voice.transcriber.models
  rel: mentions
- concept: mod:parrot.voice.transcriber.moonshine_backend
  rel: mentions
- concept: mod:parrot.voice.transcriber.transcriber
  rel: mentions
- concept: mod:parrot.voice.tts
  rel: mentions
- concept: mod:parrot.voice.tts.backend
  rel: mentions
- concept: mod:parrot.voice.tts.models
  rel: mentions
- concept: mod:parrot.voice.tts.supertonic_backend
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

# Feature Specification: AgentTalk Voice Support (REST round-trip: audio → STT → text Agent → TTS → audio + content)

**Feature ID**: FEAT-231
**Date**: 2026-06-09
**Author**: Jesus Lara
**Status**: approved
**Target version**: TBD

> **Source**: research proposal `sdd/proposals/agentalk-voice-support.proposal.md`
> (rev4, overall confidence: high). Audit trail: `sdd/state/FEAT-231/`.

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

The **AgentTalk** REST endpoint (`parrot.handlers.agent.AgentTalk`) implements the
entire *text → agent → formatted reply* cycle but accepts only **text** as the
user's question. Users want to speak to an agent: send a **voice note**, have it
transcribed (STT), routed to the agent **exactly like a normal text call**, and
hear the answer back — the agent's **text** answer (`AIMessage.response`, not the
structured payload) synthesized via a sub-second TTS model and returned as
**audio + content**.

`AgentTalk` is already **LLM-client-agnostic** (it dispatches through
`bot.ask(...)`, and the bot owns whatever client — Google / OpenAI / Claude /
Groq) and already **multipart-capable** (`handle_upload()` →
`_handle_attachments()`). It already carries the auth / PBAC / HITL / session /
output-negotiation machinery any new endpoint would otherwise re-implement. The
feature is therefore a **voice I/O adapter around the existing REST flow** — a
transcode on the way in and a transcode on the way out — **not** a greenfield
endpoint and **not** built on the Gemini-Live WebSocket `VoiceBot` /
`VoiceChatHandler` path.

### Goals

- **G1** — Add a voice-capable REST endpoint that transcribes an inbound audio
  attachment to the `query` string, then runs the **unchanged** `bot.ask()`
  text path (LLM-agnostic by construction).
- **G2** — After `bot.ask()` returns, synthesize **only** `AIMessage.response`
  (str) via a TTS backend and attach `audio_base64` + `audio_format` to the
  existing JSON envelope; `output` / `data` / `media` continue to ride along as
  structured `content`.
- **G3** — Reuse `AgentTalk` by **subclassing** (`AgentVoiceTalk(AgentTalk)`),
  inheriting agent resolution, PBAC, HITL, auth envelopes, session handling and
  output negotiation — overriding only the two voice seams. No code duplication.
- **G4** — Ship a new **`SupertonicTTSBackend`** (sub-second TTS) and a new
  **`MoonshineSTTBackend`** (opt-in sub-second STT) behind the **existing**
  `AbstractTTSBackend` / `AbstractTranscriberBackend` seams. FasterWhisper stays
  the default STT backend; Google stays the default TTS backend.
- **G5** — Degrade gracefully to **text-only** (omit `audio_base64`) when the
  voice stack or the selected backend is unavailable (extras not installed).

### Non-Goals (explicitly out of scope)

- **Modifying `AgentTalk.post()` text path** — it is inherited unchanged
  (Option B). *Option A — in-place STT/TTS branches inside core `AgentTalk` —
  was rejected in the proposal (U7): it modifies the text hot-path. See
  `sdd/proposals/agentalk-voice-support.proposal.md` §3.*
- **The Gemini-Live `VoiceBot` / native S2S path and `VoiceChatHandler` (WS)** —
  explicitly **not** the host and **not** mirrored. The voice stack reused here
  is only `parrot.voice.transcriber` (STT) and `parrot.voice.tts` (TTS).
- **Streaming partial audio** — single buffered round-trip only for v1. The
  streaming seam (`AgentTalk._handle_stream_response`) is documented, not used.
- **Modifying `AIMessage` / `AgentResponse` models** — consumed, not modified.
- **Modifying FasterWhisper / Google TTS internals** — reused as-is; the two new
  backends are additive.
- **Telegram / MS Teams voice wiring** — unaffected.

---

## 2. Architectural Design

### Overview

A thin REST subclass, **`AgentVoiceTalk(AgentTalk)`**, registered at
`POST /api/v1/agents/voice/{agent_id}`. It **inherits** everything from
`AgentTalk` and **overrides only two seams**:

1. **Inbound (STT).** When the request carries an audio attachment, persist it to
   a tempfile and transcribe it with `VoiceTranscriber.transcribe_file(...)`
   (backend selectable: `faster_whisper` default | `moonshine`), producing the
   `query` string. Then delegate to the inherited `post()` text path unchanged.
2. **Outbound (TTS).** After `bot.ask()` returns the `AIMessage`, synthesize
   `response.response` (str) via `VoiceSynthesizer.synthesize(...)` and attach
   `audio_base64` + `audio_format` to the JSON envelope built by the inherited
   `_prepare_response`. Everything non-speakable (`output` / `data` / `media`)
   stays in `content`.

**Placement decision (corrects proposal U7).** The proposal placed the subclass
in `ai-parrot-integrations` on the premise that `AgentTalk` lives in **core**
`ai-parrot`. That premise is false — `AgentTalk` lives in **ai-parrot-server**,
and `ai-parrot-server` / `ai-parrot-integrations` are **siblings** (each depends
only on core `ai-parrot`; neither depends on the other). The verified-correct
home for the subclass is therefore **ai-parrot-server**, mirroring the existing
`InfographicTalk(AgentTalk)` precedent (same package, route registered in
`manager.py`). The server reaches the voice stack via an **extras-guarded lazy
import** of `parrot.voice.*`, exactly the pattern `manager.py` already uses to
optionally load `ai-parrot-integrations`. The new TTS/STT **backends** still live
in `ai-parrot-integrations` (`parrot/voice/...`) — only the handler moves to
server. *(Resolved with the user during /sdd-spec — see §8.)*

```
ai-parrot-server                              ai-parrot-integrations
────────────────                              ──────────────────────
AgentVoiceTalk(AgentTalk)  ──lazy import──▶   parrot.voice.transcriber.VoiceTranscriber
  POST /api/v1/agents/                          └─ MoonshineSTTBackend (new)
       voice/{agent_id}     ──lazy import──▶   parrot.voice.tts.VoiceSynthesizer
                                                 └─ SupertonicTTSBackend (new)
```

### Component Diagram

```
HTTP POST (multipart: audio note)
        │
        ▼
AgentVoiceTalk.post  (ai-parrot-server)
        │ handle_upload() ─▶ audio attachment? ──no──▶ inherited AgentTalk text path
        │ yes
        ▼
  tempfile.persist(audio)
        │
        ▼
  VoiceTranscriber.transcribe_file(Path)  ─▶ query: str   [faster_whisper | moonshine]
        │
        ▼
  inherited bot.ask(question=query, …) ─▶ AIMessage   (LLM-agnostic, UNCHANGED)
        │
        ▼
  try: VoiceSynthesizer.synthesize(AIMessage.response) ─▶ SynthesisResult(audio, mime_format)
        │                                                  [google | supertonic]
        │ except (ValueError|RuntimeError|ImportError) ─▶ text-only (omit audio_base64)
        ▼
  inherited _prepare_response(...) JSON envelope
        + audio_base64 = b64(result.audio)
        + audio_format = result.mime_format
        │ content: output/data/media (unchanged)
        ▼
HTTP 200 (audio + content)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot.handlers.agent.AgentTalk` | **subclass** | `AgentVoiceTalk(AgentTalk)` inherits post/_resolve_bot/_handle_attachments/_check_pbac_agent_access/_prepare_response/auth+HITL envelopes. Mirrors `InfographicTalk(AgentTalk)`. |
| `AgentTalk.handle_upload()` (inherited `BaseView`) | uses | Inbound audio enters here — no new transport. |
| `AgentTalk.post` `query = data.pop('query', None)` | injects | Transcript injected here; rest of `post()` untouched. |
| `bot.ask(...) -> AIMessage` | uses | The single LLM-agnostic dispatch. TTS reads `AIMessage.response`. |
| `AgentTalk._prepare_response` | extends | Adds `audio_base64` + `audio_format` fields to the JSON envelope. |
| `parrot.manager.manager` route table | adds route | `router.add_view('/api/v1/agents/voice/{agent_id}', AgentVoiceTalk)` beside the existing `chat`/`infographic` routes, under the existing optional-integration guard. |
| `parrot.voice.transcriber.VoiceTranscriber` | uses (lazy) | STT service. New `MoonshineSTTBackend` plugs into its `_get_backend` dispatch. |
| `parrot.voice.tts.VoiceSynthesizer` / `AbstractTTSBackend` | uses + extends | TTS service. New `SupertonicTTSBackend` plugs into its `_get_backend` dispatch. |

### Data Models

No new Pydantic models are required. **Existing** models are extended by one
enum/Literal member each:

```python
# parrot/voice/tts/models.py — extend the Literal
backend: Literal["google", "elevenlabs", "openai", "supertonic"]  # add "supertonic"

# parrot/voice/transcriber/models.py — extend the Enum
class TranscriberBackend(str, Enum):
    FASTER_WHISPER = "faster_whisper"
    OPENAI_WHISPER = "openai_whisper"
    MOONSHINE = "moonshine"            # new

# Reused unchanged:
#   SynthesisResult(audio: bytes, mime_format: str, duration_s: Optional[float])
#   TranscriptionResult(text, language, duration_seconds, confidence, processing_time_ms)
```

The reply envelope is the **existing AgentTalk JSON envelope** plus two fields
(no model change — the envelope is assembled in `_prepare_response`):

```jsonc
{
  "...": "existing AgentTalk envelope (content, output, data, media, ...)",
  "audio_base64": "<base64 of result.audio>",   // present only when TTS succeeded
  "audio_format": "audio/wav"                    // result.mime_format, truthful
}
```

### New Public Interfaces

```python
# ai-parrot-integrations: parrot/voice/tts/supertonic_backend.py
class SupertonicTTSBackend(AbstractTTSBackend):
    async def synthesize(
        self,
        text: str,
        *,
        voice: Optional[str] = None,
        mime_format: str = "audio/ogg",   # exact AbstractTTSBackend signature (incl. language)
        language: Optional[str] = None,
    ) -> SynthesisResult: ...
    # MUST return a browser-playable container (default target audio/wav) and set
    # SynthesisResult.mime_format truthfully — mime_format is a LABEL, not a converter.

# ai-parrot-integrations: parrot/voice/transcriber/moonshine_backend.py
class MoonshineSTTBackend(AbstractTranscriberBackend):
    async def transcribe(
        self,
        audio_path: Path,                 # input is a Path, NOT bytes
        language: Optional[str] = None,
    ) -> TranscriptionResult: ...
    # CPU/GPU-bound work runs under asyncio.to_thread (mirror FasterWhisperBackend).

# ai-parrot-server: parrot/handlers/agent_voice.py
@is_authenticated()
@user_session()
class AgentVoiceTalk(AgentTalk):
    async def post(self): ...             # STT inbound, bot.ask unchanged, TTS outbound
```

---

## 3. Module Breakdown

> These map directly to Task Artifacts in Phase 2.

### Module 1: Supertonic TTS backend
- **Path**: `packages/ai-parrot-integrations/src/parrot/voice/tts/supertonic_backend.py` (new)
- **Also edits**:
  - `packages/ai-parrot-integrations/src/parrot/voice/tts/models.py` — add `"supertonic"` to `TTSConfig.backend` Literal.
  - `packages/ai-parrot-integrations/src/parrot/voice/tts/synthesizer.py` — add a `"supertonic"` branch in `VoiceSynthesizer._get_backend` (lazy import inside the branch, mirroring the `google` branch).
  - `packages/ai-parrot-integrations/pyproject.toml` — add `voice-supertonic` extra and reference it from the `voice` aggregate.
- **Responsibility**: Implement `AbstractTTSBackend.synthesize` against Supertonic
  (ONNX runtime + weights), returning a browser-playable container with a truthful
  `mime_format`. Extras-gated; missing deps raise `ImportError`/`ValueError`.
- **Depends on**: existing `AbstractTTSBackend`, `SynthesisResult`, `TTSConfig`.

### Module 2: Moonshine STT backend
- **Path**: `packages/ai-parrot-integrations/src/parrot/voice/transcriber/moonshine_backend.py` (new)
- **Also edits**:
  - `packages/ai-parrot-integrations/src/parrot/voice/transcriber/models.py` — add `MOONSHINE = "moonshine"` to `TranscriberBackend`.
  - `packages/ai-parrot-integrations/src/parrot/voice/transcriber/transcriber.py` — add a `TranscriberBackend.MOONSHINE` branch in `VoiceTranscriber._get_backend`.
  - `packages/ai-parrot-integrations/pyproject.toml` — add `voice-moonshine` extra and reference it from the `voice` aggregate.
- **Responsibility**: Implement `AbstractTranscriberBackend.transcribe(audio_path: Path, …)`
  against Moonshine, CPU/GPU work under `asyncio.to_thread`. Opt-in; FasterWhisper
  stays the default.
- **Depends on**: existing `AbstractTranscriberBackend`, `TranscriptionResult`, `VoiceTranscriberConfig`.

### Module 3: AgentVoiceTalk handler
- **Path**: `packages/ai-parrot-server/src/parrot/handlers/agent_voice.py` (new)
- **Responsibility**: `AgentVoiceTalk(AgentTalk)`. Override `post()` to (a) detect an
  audio attachment after `handle_upload()`, persist it to a tempfile, transcribe via
  a lazily-imported `VoiceTranscriber`, inject the transcript as `query`, then run the
  inherited text dispatch; (b) after `bot.ask()`, synthesize `AIMessage.response` via a
  lazily-imported `VoiceSynthesizer`, wrapped in try/except → text-only degradation;
  attach `audio_base64` + `audio_format` to the inherited `_prepare_response` envelope.
- **Depends on**: Module 1, Module 2 (runtime, via lazy import), `AgentTalk`.

### Module 4: Route registration + extras-guarded wiring
- **Path**: `packages/ai-parrot-server/src/parrot/manager/manager.py` (edit)
- **Responsibility**: Register `router.add_view('/api/v1/agents/voice/{agent_id}', AgentVoiceTalk)`
  beside the `chat`/`infographic` routes, under the existing optional-integration
  guard (the pattern around `manager.py:1848`). If `parrot.voice.*` / the handler
  cannot be imported, log the "install ai-parrot-integrations[voice]" warning and
  skip the route — never crash server boot.
- **Depends on**: Module 3.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_supertonic_synthesize_returns_playable_container` | 1 | `synthesize()` returns `SynthesisResult` with truthful `mime_format` (default `audio/wav`) and non-empty `audio`. |
| `test_supertonic_signature_matches_abstract` | 1 | `synthesize` honours the exact `AbstractTTSBackend` signature (`voice`, `mime_format`, `language` kwargs). |
| `test_ttsconfig_accepts_supertonic` | 1 | `TTSConfig(backend="supertonic")` validates; `VoiceSynthesizer._get_backend()` builds `SupertonicTTSBackend`. |
| `test_supertonic_missing_extra_raises` | 1 | Missing ONNX/weights raises `ImportError`/`ValueError` (does not silently degrade — degradation is the handler's job). |
| `test_moonshine_transcribe_returns_result` | 2 | `transcribe(Path)` returns `TranscriptionResult` with `text`/`language`/`processing_time_ms`. |
| `test_transcriberbackend_has_moonshine` | 2 | `TranscriberBackend.MOONSHINE == "moonshine"`; `VoiceTranscriber._get_backend()` builds `MoonshineSTTBackend`. |
| `test_faster_whisper_still_default` | 2 | Default `VoiceTranscriberConfig().backend == TranscriberBackend.FASTER_WHISPER`. |
| `test_voice_in_persists_tempfile_and_transcribes` | 3 | Audio attachment → tempfile → `transcribe_file` → `query` injected; tempfile cleaned up. |
| `test_voice_out_synthesizes_response_field_only` | 3 | TTS reads `AIMessage.response` (str); `output`/`data`/`media` never pass through the synthesizer. |
| `test_voice_out_attaches_audio_base64` | 3 | Envelope gains `audio_base64` + `audio_format` when TTS succeeds. |
| `test_degrades_to_text_only_when_tts_unavailable` | 3 | `synthesize` raising `ValueError`/`RuntimeError`/`ImportError` → envelope omits `audio_base64`, still 200 with `content`. |
| `test_no_audio_attachment_falls_through_to_text` | 3 | A text-only request to the voice endpoint behaves like the inherited text path. |
| `test_voice_route_registered` | 4 | `POST /api/v1/agents/voice/{agent_id}` resolves to `AgentVoiceTalk`. |
| `test_missing_voice_stack_skips_route_without_crash` | 4 | Import failure of the voice stack logs a warning and skips the route; server still boots. |

### Integration Tests
| Test | Description |
|---|---|
| `test_voice_round_trip_end_to_end` | multipart audio in → STT → `bot.ask` (stub LLM) → TTS → JSON `{content, audio_base64, audio_format}`. |
| `test_inherited_pbac_and_auth_apply_to_voice` | PBAC denial / auth envelope behave identically to `AgentTalk` (inherited, no re-impl). |

### Test Data / Fixtures
```python
@pytest.fixture
def short_wav_bytes() -> bytes:
    """Tiny valid WAV payload for STT-in fixtures."""
    ...

@pytest.fixture
def stub_bot():
    """Bot whose ask() returns a fixed AIMessage(response='Hola, ¿en qué puedo ayudarte?')."""
    ...
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] **AC1 (G3)** — `AgentVoiceTalk(AgentTalk)` exists in
  `packages/ai-parrot-server/src/parrot/handlers/agent_voice.py`, inherits agent
  resolution, PBAC, HITL, auth envelopes, session and output negotiation, and
  does **not** modify `AgentTalk.post()`.
- [ ] **AC2 (G1)** — A request with an audio attachment is persisted to a
  tempfile, transcribed via `VoiceTranscriber.transcribe_file(Path)`, and the
  transcript is injected as `query` into the **unchanged** inherited dispatch
  (`bot.ask(...)`), keeping the endpoint LLM-agnostic. The tempfile is always
  cleaned up.
- [ ] **AC3 (G2)** — After `bot.ask()`, **only** `AIMessage.response` (str) is
  synthesized; the envelope gains `audio_base64` (base64 of `SynthesisResult.audio`)
  and `audio_format` (`SynthesisResult.mime_format`); `output` / `data` / `media`
  remain structured `content` and never pass through the synthesizer.
- [ ] **AC4 (G4)** — `SupertonicTTSBackend(AbstractTTSBackend)` implements the
  exact `synthesize(text, *, voice, mime_format, language)` signature, returns a
  browser-playable container (default `audio/wav`), and sets `mime_format`
  truthfully. `"supertonic"` is added to `TTSConfig.backend` Literal and dispatched
  in `VoiceSynthesizer._get_backend`.
- [ ] **AC5 (G4)** — `MoonshineSTTBackend(AbstractTranscriberBackend)` implements
  `transcribe(audio_path: Path, language)` with CPU/GPU work under
  `asyncio.to_thread`; `TranscriberBackend.MOONSHINE` is added and dispatched in
  `VoiceTranscriber._get_backend`. FasterWhisper remains the default.
- [ ] **AC6 (G5)** — When the voice stack or selected backend is unavailable, the
  handler catches `ValueError` / `RuntimeError` / `ImportError` and returns
  **text-only** (200, `content`, no `audio_base64`).
- [ ] **AC7** — `POST /api/v1/agents/voice/{agent_id}` is registered in
  `manager.py` under the existing optional-integration guard; an import failure of
  the voice stack logs a warning and skips the route without crashing boot. The
  text endpoint `/api/v1/agents/chat/{agent_id}` is untouched.
- [ ] **AC8** — `voice-supertonic` and `voice-moonshine` extras are added to
  `ai-parrot-integrations/pyproject.toml` and referenced from the `voice`
  aggregate extra.
- [ ] **AC9** — All unit tests pass (`pytest packages/ai-parrot-integrations/tests/voice/ -v`
  and the server handler tests) and integration tests pass.
- [ ] **AC10** — No breaking changes to `AgentTalk`, `AIMessage`, `AgentResponse`,
  `VoiceTranscriber`, or `VoiceSynthesizer` public APIs.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** All entries below were verified by
> direct read during /sdd-spec (2026-06-09). Line numbers are from the files as
> read; treat as anchors, re-grep if the file shifted.

### Verified Imports
```python
# ai-parrot-server (host)
from parrot.handlers.agent import AgentTalk           # verified: packages/ai-parrot-server/src/parrot/handlers/agent.py:102
# precedent subclass:
#   packages/ai-parrot-server/src/parrot/handlers/infographic.py:25  -> from .agent import AgentTalk
#   packages/ai-parrot-server/src/parrot/handlers/infographic.py:57  -> class InfographicTalk(AgentTalk)

# ai-parrot-integrations (voice stack)
from parrot.voice import VoiceSynthesizer             # verified: packages/.../voice/__init__.py:12
from parrot.voice.tts import VoiceSynthesizer         # verified: voice/tts/synthesizer.py:21
from parrot.voice.tts.backend import AbstractTTSBackend          # verified: voice/tts/backend.py:17
from parrot.voice.tts.models import TTSConfig, SynthesisResult   # verified: voice/tts/models.py:16,76
from parrot.voice.transcriber.transcriber import VoiceTranscriber  # verified: voice/transcriber/transcriber.py:30
from parrot.voice.transcriber.backend import AbstractTranscriberBackend  # verified: voice/transcriber/backend.py:18
from parrot.voice.transcriber.models import (         # verified: voice/transcriber/models.py:16,28,87
    TranscriberBackend, VoiceTranscriberConfig, TranscriptionResult,
)
```

### Existing Class Signatures
```python
# packages/ai-parrot-server/src/parrot/handlers/agent.py
import tempfile                                                   # line 11  (already imported — reuse for STT tempfile)
from ..models.responses import AIMessage, AgentResponse          # line 36
from ..outputs import OutputMode, OutputFormatter                # line 37

@is_authenticated()                                              # line 100
@user_session()                                                  # line 101
class AgentTalk(BaseView):                                        # line 102
    async def _check_pbac_agent_access(self, ...):               # line 135  (PBAC — inherited free)
    def _prepare_response(self, ...):                            # line 541  (JSON envelope — extend with audio_base64)
    async def _resolve_bot(self, ...):  # -> manager.get_bot(agent_name)  # line 984 (LLM-agnostic resolution)
    async def _handle_attachments(self, ...):  # -> bot.handle_files(...)  # line 1261
    async def post(self):                                        # line 1523  (override seam)
        attachments, data = await self.handle_upload()           # line 1580  (multipart already supported)
        query = data.pop('query', None)                          # line 1635  (inject transcript here)
        response: AIMessage = await bot.ask( ... )               # line 1847  (the single agnostic dispatch)
    async def _handle_stream_response(self, ...):  # web.StreamResponse text/plain  # line 2355 (streaming seam — NOT used in v1)

# parrot.voice.tts.backend.AbstractTTSBackend                    # voice/tts/backend.py
@abstractmethod
async def synthesize(self, text: str, *, voice: Optional[str] = None,
                     mime_format: str = "audio/ogg",
                     language: Optional[str] = None) -> SynthesisResult:   # lines 37-45

# parrot.voice.tts.synthesizer.VoiceSynthesizer                  # voice/tts/synthesizer.py
def __init__(self, config: Optional[TTSConfig] = None) -> None:  # line 46
def _get_backend(self) -> AbstractTTSBackend:                    # line 52  (add "supertonic" branch)
    if backend_name == "google": ...                             # line 73  (mirror this branch)
async def synthesize(self, text: str, *, language: Optional[str] = None) -> SynthesisResult:  # line 93

# parrot.voice.tts.models                                        # voice/tts/models.py
class TTSConfig(BaseModel):
    backend: Literal["google", "elevenlabs", "openai"] = "google"   # line 41  (ADD "supertonic")
    voice: Optional[str]; language: Optional[str]
    mime_format: str = "audio/ogg"                               # line 53
class SynthesisResult(BaseModel):                                # line 76
    audio: bytes; mime_format: str; duration_s: Optional[float]

# parrot.voice.transcriber.backend.AbstractTranscriberBackend    # voice/transcriber/backend.py
@abstractmethod
async def transcribe(self, audio_path: Path,

…(truncated)…
