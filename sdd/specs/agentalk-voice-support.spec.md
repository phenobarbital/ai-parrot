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
                     language: Optional[str] = None) -> TranscriptionResult:   # lines 38-43

# parrot.voice.transcriber.transcriber.VoiceTranscriber          # voice/transcriber/transcriber.py
SUPPORTED_FORMATS = {".ogg",".mp3",".wav",".m4a",".webm",".mp4",".flac"}   # line 62
def __init__(self, config: VoiceTranscriberConfig):              # line 64
def _get_backend(self) -> AbstractTranscriberBackend:            # line 70  (add MOONSHINE branch)
    if self.config.backend == TranscriberBackend.FASTER_WHISPER: ...   # line 84  (mirror this branch)
async def transcribe_file(self, file_path: Path, language=None) -> TranscriptionResult:   # line 106
async def transcribe_url(self, url, auth_token=None, language=None) -> TranscriptionResult:   # line 149

# parrot.voice.transcriber.models                                # voice/transcriber/models.py
class TranscriberBackend(str, Enum):                             # line 16
    FASTER_WHISPER = "faster_whisper"; OPENAI_WHISPER = "openai_whisper"   # (ADD MOONSHINE = "moonshine")
class VoiceTranscriberConfig(BaseModel):                         # line 28
    backend: TranscriberBackend = FASTER_WHISPER                 # line 39  (default unchanged)
    model_size="small"; language; max_audio_duration_seconds=60; ...
class TranscriptionResult(BaseModel):                            # line 87
    text; language; duration_seconds; confidence; processing_time_ms

# parrot.voice.transcriber.faster_whisper_backend.FasterWhisperBackend  # pattern to mirror for Moonshine
class FasterWhisperBackend(AbstractTranscriberBackend):          # line 21
async def transcribe(self, audio_path: Path, language=None):     # line 83
    result = await asyncio.to_thread(self._transcribe_sync, audio_path, language)   # line 111

# parrot.manager.manager (route table)
from ..handlers.agent import AgentTalk                           # manager.py:28
from ..handlers.infographic import InfographicTalk               # manager.py:30
router.add_view('/api/v1/agents/chat/{agent_id}', AgentTalk)     # manager.py:1489
# InfographicTalk routes registered manager.py:1570-1586
# optional ai-parrot-integrations loading with graceful warning: manager.py:1848-1857
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `AgentVoiceTalk` | `AgentTalk` | subclass (mirror `InfographicTalk`) | `agent.py:102`, `infographic.py:57` |
| `AgentVoiceTalk.post` | `handle_upload()` / `query` inject / `bot.ask` | inherited seams | `agent.py:1580,1635,1847` |
| `AgentVoiceTalk` | `VoiceTranscriber.transcribe_file(Path)` | lazy import + call | `transcriber.py:106` |
| `AgentVoiceTalk` | `VoiceSynthesizer.synthesize(str)` | lazy import + call (try/except) | `synthesizer.py:93` |
| `SupertonicTTSBackend` | `VoiceSynthesizer._get_backend` | new dispatch branch | `synthesizer.py:73` |
| `MoonshineSTTBackend` | `VoiceTranscriber._get_backend` | new dispatch branch | `transcriber.py:84` |
| voice route | `manager.py` route table | `router.add_view(...)` under integration guard | `manager.py:1489,1848` |

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.voice.tts.supertonic_backend.SupertonicTTSBackend`~~ — **to be created** (Module 1).
- ~~`parrot.voice.transcriber.moonshine_backend.MoonshineSTTBackend`~~ — **to be created** (Module 2).
- ~~`parrot.handlers.agent_voice.AgentVoiceTalk`~~ — **to be created** (Module 3).
- ~~`TTSConfig.backend == "supertonic"`~~ — Literal is currently `["google","elevenlabs","openai"]` only; must be added.
- ~~`TranscriberBackend.MOONSHINE`~~ — enum currently has only `FASTER_WHISPER`, `OPENAI_WHISPER`.
- ~~`VoiceSynthesizer` graceful degradation~~ — it **raises** `ValueError` for missing/unknown backends; degradation is the **handler's** responsibility (try/except).
- ~~`VoiceTranscriber.transcribe(bytes)`~~ — input is a **`Path`** (`transcribe_file(file_path: Path)` / backend `transcribe(audio_path: Path)`), not bytes. Persist to tempfile first.
- `parrot.voice.handler.VoiceChatHandler` / `parrot.bots.voice.VoiceBot` — **exist but are the WRONG host** (Gemini-Live WS / native S2S). Must **not** be subclassed, imported, or mirrored.
- `AgentTalk` is **not** in core `ai-parrot` — it lives in **ai-parrot-server** (`packages/ai-parrot-server/src/parrot/handlers/agent.py`). The voice backends are in **ai-parrot-integrations**; the two packages are siblings off core.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- **Subclass, don't duplicate.** Mirror `InfographicTalk(AgentTalk)` exactly:
  re-apply `@is_authenticated()` / `@user_session()`, set `_logger_name`,
  override only `post()`.
- **Lazy, extras-guarded voice imports.** Import `parrot.voice.*` *inside* the
  voice code path (not at module top) so server boot never hard-requires
  `ai-parrot-integrations`. Mirror the existing optional-integration guard at
  `manager.py:1848-1857`.
- **STT input is a `Path`.** Persist the inbound audio attachment to a tempfile
  (`tempfile`, already imported in `agent.py`) before calling
  `transcribe_file(Path)`; always `unlink()` in a `finally`.
- **TTS reads only `AIMessage.response`.** Never feed `output`/`data`/`media`
  (which are `Any` / paths) into `synthesize`.
- **Mirror the backend dispatch pattern.** New backends follow the lazy
  `_get_backend` branch shape (TTS `synthesizer.py:73`, STT `transcriber.py:84`)
  and run CPU/GPU work under `asyncio.to_thread` (FasterWhisper `:111`).
- Async-first, `self.logger`, Pydantic for structured data.

### Known Risks / Gotchas
- **`mime_format` is a label, not a converter** (verified: `GoogleTTSBackend`
  returns raw PCM). `SupertonicTTSBackend` must itself emit/wrap a
  browser-playable container (default target `audio/wav`) and label
  `SynthesisResult.mime_format` truthfully. *(Resolved U5: default `audio/wav`,
  negotiable per request.)*
- **Synthesizer raises, it does not degrade.** Wrap `synthesize(...)` in
  try/except `(ValueError, RuntimeError, ImportError)` and fall back to text-only.
- **Sibling packages.** The handler (server) reaching the backends (integrations)
  is a runtime lazy import, **not** a build-time dependency — do not add a hard
  `ai-parrot-integrations` dependency to `ai-parrot-server`; degrade at runtime.
- **Supertonic sub-second latency is an upstream claim (proposal C10, low
  confidence), not verified in-repo.** It is the *motivation* for Supertonic, not
  a load-bearing dependency: `TTSConfig.backend` can fall back to `google` with no
  design change. Do not block on it.
- **Audio duration guard.** `VoiceTranscriber.transcribe_file` enforces
  `max_audio_duration_seconds` (default 60) and needs `pydub` (`voice-tts` extra)
  to measure duration; surface its `ValueError` as a clean 4xx.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `onnxruntime` (+ Supertonic weights) | TBD | `SupertonicTTSBackend` inference — new `voice-supertonic` extra |
| Moonshine STT runtime | TBD | `MoonshineSTTBackend` inference — new `voice-moonshine` extra |
| `faster-whisper` | existing `voice-local` | default STT (unchanged) |
| `pydub>=0.25` | existing `voice-tts` | audio duration measurement (unchanged) |

> New extras mirror the existing `voice-local` / `voice-openai` / `voice-tts`
> convention in `ai-parrot-integrations/pyproject.toml` and are added to the
> `voice` aggregate. Pin exact versions during implementation (R-deps below).

---

## 8. Open Questions

> Resolved items carried forward from the proposal (`[x]`) and during /sdd-spec.

### Resolved
- [x] **Host — WS `VoiceChatHandler` vs REST `AgentTalk`** — *Resolved in proposal (U1)*: **`AgentTalk` (REST)**. The WS/Gemini path is the wrong host.
- [x] **Reuse axis** — *Resolved in proposal (U2)*: subclass `AgentTalk` (Option B); from `parrot.voice` reuse only `VoiceTranscriber` + `VoiceSynthesizer`/`AbstractTTSBackend`.
- [x] **Single round-trip vs streamed audio** — *Resolved in proposal (U3)*: single buffered round-trip for v1; streaming seam (`_handle_stream_response`) noted for later.
- [x] **Which Agent answers** — *Resolved in proposal (U4)*: per `agent_id` via inherited `_resolve_bot`/`BotManager`; `bot.ask(...)` unchanged.
- [x] **Output audio format** — *Resolved in proposal (U5)*: default **`audio/wav`** for the web player; negotiable per request.
- [x] **STT default + selector** — *Resolved in proposal (U6)*: FasterWhisper default, **Moonshine opt-in** built in this feature as a new `MoonshineSTTBackend`.
- [x] **Option A vs Option B** — *Resolved in proposal (U7)*: **Option B** (subclass, no hot-path edit). Option A rejected.
- [x] **Voice-stack seams + STT abstraction** — *Resolved in proposal (U8) and re-verified here*: `AbstractTTSBackend`/`VoiceSynthesizer._get_backend` and `AbstractTranscriberBackend`/`VoiceTranscriber._get_backend` confirmed; new backends are one impl + one dispatch entry each, no new abstraction.
- [x] **R1 — `TTSConfig.backend` Literal members** — *Resolved during /sdd-spec*: `Literal["google","elevenlabs","openai"]` (`tts/models.py:41`); add `"supertonic"`.
- [x] **R2 — STT backend selector field** — *Resolved during /sdd-spec*: `VoiceTranscriberConfig.backend: TranscriberBackend` enum (`transcriber/models.py:16,39`); add `MOONSHINE = "moonshine"`.
- [x] **Subclass package placement (corrects proposal U7's location)** — *Resolved with the user during /sdd-spec*: **ai-parrot-server**, mirroring `InfographicTalk`, route registered in `manager.py` under the existing optional-integration guard. The proposal's "integrations" placement rested on the false premise that `AgentTalk` is in core; server and integrations are siblings.

### Residual (decide during implementation — non-blocking)
- [ ] **R-deps** — Pin exact `onnxruntime` version + Supertonic weight source for `voice-supertonic`, and the Moonshine runtime package/version for `voice-moonshine`. *Owner: implementer*
- [ ] **R-format** — Whether `SupertonicTTSBackend` emits a playable container natively or wraps via `pydub`; confirm `audio/wav` is the right web-player default vs `audio/ogg`. *Owner: implementer*

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` — all tasks run sequentially in one
  worktree (`feat-231-agentalk-voice-support`).
- **Parallelism note**: Module 1 (Supertonic TTS) and Module 2 (Moonshine STT)
  are independent and *could* be done in parallel, but both are small additive
  backends in the same package; Module 3 (handler) depends on both and Module 4
  (route wiring) depends on Module 3. The dependency chain (1,2 → 3 → 4) makes a
  single sequential worktree the simplest correct choice.
- **Cross-feature dependencies**: none. Builds beside the untouched Gemini-Live
  `VoiceBot` path with no regression risk.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-06-09 | Jesus Lara | Initial draft from proposal rev4. Corrects U7 placement to ai-parrot-server (verified: AgentTalk lives in server, sibling of integrations; mirrors InfographicTalk). Resolves R1/R2 via direct read. |
