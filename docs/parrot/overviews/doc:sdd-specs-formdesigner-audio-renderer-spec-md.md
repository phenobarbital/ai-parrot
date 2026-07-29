---
type: Wiki Overview
title: 'Feature Specification: FormDesigner Audio Renderer'
id: doc:sdd-specs-formdesigner-audio-renderer-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Form Designer currently renders form definitions into visual formats (HTML,
relates_to:
- concept: mod:parrot.voice
  rel: mentions
- concept: mod:parrot.voice.handler
  rel: mentions
- concept: mod:parrot.voice.transcriber
  rel: mentions
- concept: mod:parrot.voice.transcriber.faster_whisper_backend
  rel: mentions
- concept: mod:parrot.voice.tts.models
  rel: mentions
- concept: mod:parrot.voice.tts.synthesizer
  rel: mentions
---

---
type: feature
base_branch: dev
---

# Feature Specification: FormDesigner Audio Renderer

**Feature ID**: FEAT-224
**Date**: 2026-06-04
**Author**: Jesus Lara
**Status**: approved
**Target version**: 1.x

---

## 1. Motivation & Business Requirements

### Problem Statement

Form Designer currently renders form definitions into visual formats (HTML,
Adaptive Card, JSON Schema, XML, PDF). There is no audio-first interaction
mode — users who cannot or prefer not to read/type (accessibility, field
workers, phone-based interactions) have no way to complete a form through
speech.

The feature introduces an **audio renderer** that converts a `FormSchema` into
a sequential question-by-question audio flow: each question is read aloud via
TTS, the user answers by typing or speaking (audio captured and transcribed via
Faster Whisper), and answers are collected and submitted as standard form data.

The communication channel between the frontend client and the audio renderer
is a **new WebSocket handler** inside `parrot-formdesigner`, enabling
real-time bidirectional audio streaming.

### Goals

- Provide a complete audio-driven form-filling experience over WebSocket.
- Reuse existing TTS (`VoiceSynthesizer`) and STT (`FasterWhisperBackend`)
  infrastructure from `ai-parrot-integrations`.
- Add a new `AUDIO` FieldType so individual fields in any renderer can accept
  audio input.
- Register the audio renderer via the existing `register_renderer()` mechanism
  so it is discoverable at `GET /api/v1/forms/{form_id}/render/audio`.
- Authenticate WebSocket connections using JWT tokens following the existing
  `VoiceChatHandler` / `TokenValidator` pattern.
- Keep the handler inside the `parrot-formdesigner` package since this is a
  form-rendering concern.

### Non-Goals (explicitly out of scope)

- Real-time voice conversation / dialogue agent (this is form Q&A, not free-form chat).
- Video or image capture as part of the audio flow.
- Multi-language auto-detection during a single form session (locale is set at
  session start).
- Offline/PWA audio form support.
- Gemini Live API integration (future enhancement — reuse existing
  `VoiceChatServer` pattern later).

---

## 2. Architectural Design

### Overview

The solution has two complementary parts:

1. **`AudioFormRenderer`** — A new `AbstractFormRenderer` subclass registered
   under `"audio"`. Unlike visual renderers that return a full document, this
   renderer produces a **session manifest**: a JSON object describing the
   sequential list of questions (with pre-synthesized audio URLs or inline
   base64 audio), expected answer types, and the WebSocket endpoint URL to
   connect for the interactive session.

2. **`FieldType.AUDIO`** — A new field type that any renderer can support.
   In the HTML5 renderer it produces a `<button>` to start recording + a
   hidden `<input>` to store the transcribed text. In the audio renderer it
   is natively handled as a speech-input question.

The WebSocket handler (`AudioFormWSHandler`) manages the stateful session:

```
Client                           Server (AudioFormWSHandler)
  │                                  │
  ├─ WS connect + JWT ──────────────►│  authenticate, load FormSchema
  │                                  │  split into questions
  │◄──── session_start + Q1 audio ───┤  synthesize Q1 via TTS
  │                                  │
  ├─ answer (text or audio blob) ───►│  if audio: transcribe via Whisper
  │                                  │  validate answer
  │◄──── ack + Q2 audio ────────────┤  next question
  │  ...                             │
  ├─ answer (last question) ────────►│  collect all answers
  │◄──── form_complete + summary ───┤  submit via FormAPIHandler.submit_data
  │                                  │
  └─ WS close ──────────────────────►│  cleanup
```

### Component Diagram

```
┌─────────────────────────────────────────────────────────┐
│  parrot-formdesigner                                    │
│                                                         │
│  ┌──────────────┐   ┌─────────────────────────────┐     │
│  │ FormSchema   │──►│ AudioFormRenderer            │     │
│  │ (core/schema)│   │ (renderers/audio.py)         │     │
│  └──────────────┘   │  - split_into_questions()    │     │
│                     │  - render() → session manifest│     │
│                     └──────────────┬────────────────┘     │
│                                    │                     │
│  ┌─────────────────────────────────▼──────────────────┐  │
│  │ AudioFormWSHandler (api/audio_ws.py)               │  │
│  │  - handle_websocket(request) → WebSocketResponse   │  │
│  │  - JWT auth via TokenValidator                     │  │
│  │  - Session state machine (question-by-question)    │  │
│  └────────────┬────────────────────┬──────────────────┘  │
│               │                    │                     │
│  ┌────────────▼───┐    ┌──────────▼──────────────────┐  │
│  │ VoiceSynthesizer│    │ FasterWhisperBackend        │  │
│  │ (ext. dep)     │    │ (ext. dep)                   │  │
│  │ parrot.voice   │    │ parrot.voice.transcriber     │  │
│  └────────────────┘    └─────────────────────────────┘  │
│                                                         │
│  ┌────────────────────────────────────────────────┐     │
│  │ AudioFieldRenderer (renderers/fields/audio.py) │     │
│  │  - HTML5: <button> + recorder + hidden input   │     │
│  │  - Adaptive Card: Action.Submit with mic icon  │     │
│  └────────────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────────┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractFormRenderer` | extends | `AudioFormRenderer` inherits and implements `render()` |
| `FieldRenderer` protocol | implements | `AudioFieldRenderer` for `FieldType.AUDIO` in HTML5/Adaptive |
| `register_renderer()` | call | Registers `"audio"` format key at setup time |
| `FormRegistry` | uses | Loads `FormSchema` by form_id from the registry |
| `FormValidator` | uses | Validates answers against field constraints |
| `VoiceSynthesizer` | uses | TTS for question audio (Google backend default) |
| `FasterWhisperBackend` | uses | STT for audio answer transcription |
| `TokenValidator` | uses | JWT authentication on WebSocket |
| `setup_form_api()` | extends | Adds the WebSocket route during API setup |
| `FormAPIHandler.submit_data` | delegates | Final form submission uses existing pipeline |
| `FieldType` enum | extends | Adds `AUDIO = "audio"` member |
| `HTML5Renderer._registry` | extends | Registers `AudioFieldRenderer` for `FieldType.AUDIO` |

### Data Models

```python
from pydantic import BaseModel, Field
from typing import Optional


class AudioSessionConfig(BaseModel):
    """Configuration for an audio form session."""
    form_id: str
    locale: str = "en"
    tts_voice: Optional[str] = None
    tts_mime_format: str = "audio/ogg"
    auto_advance: bool = True  # auto-advance to next question after answer


class AudioQuestion(BaseModel):
    """A single question in the audio form session."""
    index: int
    field_id: str
    field_type: str
    label: str
    description: Optional[str] = None
    required: bool = False
    audio_prompt: Optional[bytes] = None  # pre-synthesized TTS audio
    constraints: Optional[dict] = None
    options: Optional[list[dict]] = None  # for SELECT fields


class AudioFormManifest(BaseModel):
    """Session manifest returned by AudioFormRenderer.render()."""
    form_id: str
    title: str
    total_questions: int
    questions: list[AudioQuestion]
    ws_endpoint: str  # WebSocket URL for the interactive session
    locale: str


class AudioAnswer(BaseModel):
    """An answer to a single audio question."""
    field_id: str
    value: str
    source: str = "text"  # "text" | "speech"
    confidence: Optional[float] = None  # STT confidence when source="speech"
    raw_transcript: Optional[str] = None


class AudioSessionState(BaseModel):
    """Server-side state for an active audio form session."""
    session_id: str
    form_id: str
    user_id: str
    current_index: int = 0
    answers: dict[str, AudioAnswer] = Field(default_factory=dict)
    manifest: Optional[AudioFormManifest] = None
    completed: bool = False
```

### WebSocket Protocol

Messages are JSON with a `type` field:

**Client → Server:**
| Type | Payload | Description |
|---|---|---|
| `start_session` | `{form_id, locale?, tts_voice?}` | Begin audio form session |
| `answer_text` | `{field_id, value}` | Text answer to current question |
| `answer_audio` | binary frame | Raw audio bytes for STT transcription |
| `skip_question` | `{field_id}` | Skip optional question |
| `go_back` | `{to_index?}` | Navigate to previous question |
| `repeat_question` | `{}` | Re-send audio for current question |
| `end_session` | `{}` | Abort session |
| `ping` | `{}` | Keep-alive |

**Server → Client:**
| Type | Payload | Description |
|---|---|---|
| `session_started` | `{session_id, total_questions, title}` | Session initialized |
| `question` | `{index, field_id, label, audio, options?}` | Next question + TTS audio (base64) |
| `answer_accepted` | `{field_id, value, source}` | Answer validated and stored |
| `answer_rejected` | `{field_id, error}` | Validation failed |
| `transcription` | `{field_id, text, confidence}` | STT result (before validation) |
| `form_complete` | `{submission_id, answers}` | All questions answered, form submitted |
| `error` | `{code, message}` | Protocol or server error |
| `pong` | `{}` | Keep-alive response |

### New Public Interfaces

```python
class AudioFormRenderer(AbstractFormRenderer):
    """Renders a FormSchema into an audio session manifest."""

    async def render(
        self,
        form: FormSchema,
        style: StyleSchema | None = None,
        *,
        locale: str = "en",
        prefilled: dict[str, Any] | None = None,
        errors: dict[str, str] | None = None,
    ) -> RenderedForm:
        """Return RenderedForm with AudioFormManifest as content."""
        ...

    def split_into_questions(
        self,
        form: FormSchema,
        *,
        locale: str = "en",
    ) -> list[AudioQuestion]:
        """Flatten form sections/fields into sequential questions."""
        ...


class AudioFormWSHandler:
    """WebSocket handler for interactive audio form sessions."""

    def __init__(
        self,
        registry: FormRegistry,
        synthesizer: VoiceSynthesizer,
        transcriber: FasterWhisperBackend,
        validator: FormValidator,
        *,
        submission_storage: FormSubmissionStorage | None = None,
    ) -> None: ...

    async def handle_websocket(
        self,
        request: web.Request,
    ) -> web.WebSocketResponse: ...
```

---

## 3. Module Breakdown

### Module 1: FieldType.AUDIO — Core Type Extension

- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/core/types.py`
- **Responsibility**: Add `AUDIO = "audio"` to the `FieldType` enum.
- **Depends on**: None.

### Module 2: AudioFieldRenderer — Per-Field Audio Input

- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/fields/audio.py`
- **Responsibility**: Implement `FieldRenderer` protocol for `FieldType.AUDIO` in
  HTML5 (recording button + hidden input + JS for MediaRecorder API). Register
  in `HTML5Renderer._registry`.
- **Depends on**: Module 1.

### Module 3: Audio Data Models

- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/audio/models.py`
- **Responsibility**: Define `AudioSessionConfig`, `AudioQuestion`,
  `AudioFormManifest`, `AudioAnswer`, `AudioSessionState` Pydantic models.
- **Depends on**: None.

### Module 4: AudioFormRenderer — Standalone Audio Renderer

- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/audio.py`
- **Responsibility**: Implement `AbstractFormRenderer` that flattens a
  `FormSchema` into an `AudioFormManifest` — sequential list of questions
  with TTS audio per question. Register via `register_renderer("audio", ...)`.
- **Depends on**: Module 1, Module 3.

### Module 5: AudioFormWSHandler — WebSocket Handler

- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/api/audio_ws.py`
- **Responsibility**: aiohttp WebSocket handler managing the stateful audio
  form session. Handles JWT auth, question delivery, answer collection
  (text + audio), STT transcription via `FasterWhisperBackend`, validation,
  and final submission.
- **Depends on**: Module 3, Module 4.

### Module 6: Route Registration — WebSocket Mount

- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py` (modify)
- **Responsibility**: Mount the WebSocket endpoint at
  `GET /api/v1/forms/{form_id}/audio/ws` in `setup_form_api()`. Register the
  audio renderer in `_seed_default_renderers()`.
- **Depends on**: Module 4, Module 5.

### Module 7: Audio Control Metadata

- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/controls/builtin.py` (modify)
- **Responsibility**: Register `FieldType.AUDIO` metadata in the field controls
  registry (label, description, category, icon, render_hint).
- **Depends on**: Module 1.

### Module 8: Tests

- **Path**: `tests/formdesigner/test_audio_renderer.py`, `tests/formdesigner/test_audio_ws.py`
- **Responsibility**: Unit tests for the renderer, models, and WebSocket handler.
  Integration test for a full audio session over WebSocket.
- **Depends on**: All modules.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_fieldtype_audio_exists` | Module 1 | `FieldType.AUDIO` is a valid enum member |
| `test_formfield_accepts_audio_type` | Module 1 | `FormField(field_type=FieldType.AUDIO, ...)` validates |
| `test_audio_question_model` | Module 3 | `AudioQuestion` serialization/deserialization |
| `test_audio_session_state_model` | Module 3 | Session state tracks answers correctly |
| `test_split_into_questions_flat` | Module 4 | Single-section form splits correctly |
| `test_split_into_questions_nested` | Module 4 | Multi-section with subsections flattens |
| `test_split_skips_hidden_fields` | Module 4 | `FieldType.HIDDEN` fields excluded from questions |
| `test_split_handles_group_fields` | Module 4 | GROUP children become individual questions |
| `test_render_returns_manifest` | Module 4 | `render()` returns `RenderedForm` with `AudioFormManifest` content |
| `test_audio_field_html5_render` | Module 2 | HTML5 renderer produces `<button>` + recording JS |
| `test_audio_control_metadata` | Module 7 | AUDIO field appears in controls endpoint |

### Integration Tests

| Test | Description |
|---|---|
| `test_ws_session_lifecycle` | Connect → start_session → answer all → form_complete |
| `test_ws_auth_rejected` | Connection without JWT returns 401 |
| `test_ws_text_answer_flow` | Answer via `answer_text` messages |
| `test_ws_audio_answer_flow` | Send binary audio → receive transcription → accept |
| `test_ws_skip_optional` | Skip optional field, form still completes |
| `test_ws_go_back` | Navigate back and re-answer a question |
| `test_ws_validation_error` | Invalid answer triggers `answer_rejected` |
| `test_render_endpoint_audio` | `GET /api/v1/forms/{id}/render/audio` returns manifest |

### Test Data / Fixtures

```python
@pytest.fixture
def sample_audio_form() -> FormSchema:
    """A simple 3-question form for audio testing."""
    return FormSchema(
        form_id="test-audio-001",
        title="Audio Test Form",
        sections=[FormSection(
            section_id="s1",
            title="Personal Info",
            fields=[
                FormField(field_id="name", field_type=FieldType.TEXT,
                          label="What is your name?", required=True),
                FormField(field_id="age", field_type=FieldType.NUMBER,
                          label="How old are you?"),
                FormField(field_id="voice_note", field_type=FieldType.AUDIO,
                          label="Please leave a voice note"),
            ],
        )],
    )


@pytest.fixture
def mock_synthesizer():
    """Mock VoiceSynthesizer returning dummy audio bytes."""
    ...


@pytest.fixture
def mock_transcriber():
    """Mock FasterWhisperBackend returning fixed transcription."""
    ...
```

---

## 5. Acceptance Criteria

- [ ] `FieldType.AUDIO` is a valid member of the `FieldType` enum.
- [ ] `FormField` with `field_type=FieldType.AUDIO` passes Pydantic validation.
- [ ] `AudioFormRenderer` is registered under `"audio"` format key.
- [ ] `GET /api/v1/forms/{form_id}/render/audio` returns an `AudioFormManifest` JSON.
- [ ] WebSocket endpoint at `/api/v1/forms/{form_id}/audio/ws` accepts connections.
- [ ] WebSocket requires valid JWT token; unauthenticated connections are rejected.
- [ ] Questions are delivered sequentially with TTS audio (Google backend).
- [ ] Text answers (`answer_text`) are validated and accepted.
- [ ] Audio answers (binary frames) are transcribed via `FasterWhisperBackend` and the transcription is sent back to the client.
- [ ] After the last question is answered, the form is submitted via the existing submission pipeline.
- [ ] `skip_question` works for optional fields and rejects for required fields.
- [ ] `go_back` allows revisiting and re-answering previous questions.
- [ ] `repeat_question` re-sends the TTS audio for the current question.
- [ ] HTML5 renderer supports `FieldType.AUDIO` with a recording button and transcription input.
- [ ] AUDIO field metadata appears in the `/api/v1/form-controls` endpoint.
- [ ] All unit tests pass (`pytest tests/formdesigner/ -v`).
- [ ] No breaking changes to existing renderers or FieldType usage.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**

### Verified Imports

```python
# Core types and schema
from parrot_formdesigner.core.types import FieldType, LocalizedString  # verified: core/types.py:16
from parrot_formdesigner.core.schema import (
    FormField,       # verified: core/schema.py:24
    FormSchema,      # verified: core/schema.py:242
    FormSection,     # verified: core/schema.py:102
    RenderedForm,    # verified: core/schema.py:357
    RenderWarning,   # verified: core/schema.py:340
)

# Renderer base
from parrot_formdesigner.renderers.base import (
    AbstractFormRenderer,  # verified: renderers/base.py:57
    FieldRenderer,         # verified: renderers/base.py:15 (Protocol)
    FallbackRenderer,      # verified: renderers/base.py:34
)

# Render registry
from parrot_formdesigner.api.render import (
    register_renderer,       # verified: api/render.py:60
    _seed_default_renderers, # verified: api/render.py:37
    _RENDERERS,              # verified: api/render.py:34 (module-level dict)
)

# Style
from parrot_formdesigner.core.style import StyleSchema  # verified: renderers/base.py:11 import

# Handlers and routes
from parrot_formdesigner.api.handlers import FormAPIHandler  # verified: api/handlers.py:37
from parrot_formdesigner.api.routes import setup_form_api    # verified: api/routes.py:85

# Validation
from parrot_formdesigner.services.validators import FormValidator  # verified: api/handlers.py:26 import

# Auth (navigator-auth — hard dependency)
from navigator_auth.decorators import is_authenticated, user_session  # verified: api/routes.py:34

# Voice TTS (from ai-parrot-integrations)
from parrot.voice.tts.synthesizer import VoiceSynthesizer  # verified: voice/tts/synthesizer.py:21
from parrot.voice.tts.models import SynthesisResult, TTSConfig  # verified: voice/tts/synthesizer.py:18 import

# Voice STT (from ai-parrot-integrations)
from parrot.voice.transcriber.faster_whisper_backend import FasterWhisperBackend  # verified: voice/transcriber/faster_whisper_backend.py:21

# WebSocket auth pattern (from ai-parrot-integrations)
from parrot.voice.handler import TokenValidator, AuthenticatedUser  # verified: voice/handler.py:59, voice/handler.py:49

# aiohttp WebSocket
from aiohttp import web, WSMsgType  # verified: voice/handler.py:31
```

### Existing Class Signatures

```python
# parrot_formdesigner/core/types.py
class FieldType(str, Enum):  # line 16
    TEXT = "text"           # line 19
    # ... 30 members through REST = "rest"  # line 51
    # AUDIO does NOT exist yet — must be added

# parrot_formdesigner/renderers/base.py
class FieldRenderer(Protocol):  # line 15 — runtime_checkable
    async def render(
        self, field: FormField, *, locale: str = "en",
        prefilled: Any = None, error: str | None = None,
    ) -> Any: ...  # line 24

class AbstractFormRenderer(ABC):  # line 57
    @abstractmethod
    async def render(
        self, form: FormSchema, style: StyleSchema | None = None, *,
        locale: str = "en", prefilled: dict[str, Any] | None = None,
        errors: dict[str, str] | None = None,
    ) -> RenderedForm: ...  # line 68

# parrot_formdesigner/api/render.py
_RENDERERS: dict[str, AbstractFormRenderer] = {}  # line 34
def register_renderer(format_key: str, renderer: AbstractFormRenderer) -> None: ...  # line 60
def _seed_default_renderers() -> None: ...  # line 37 — seeds html, adaptive, xml, pdf

# parrot_formdesigner/api/routes.py
def setup_form_api(app, registry, *, client=None, submission_storage=None,
                   forwarder=None, base_path="/api/v1", blob_storage=None,
                   resolver=None, partial_store=None) -> None: ...  # line 85

# parrot.voice.tts.synthesizer
class VoiceSynthesizer:  # line 21
    def __init__(self, config: Optional[TTSConfig] = None) -> None: ...  # line 46
    async def synthesize(self, text: str, *, language: Optional[str] = None) -> SynthesisResult: ...

# parrot.voice.transcriber.faster_whisper_backend
class FasterWhisperBackend(AbstractTranscriberBackend):  # line 21
    def __init__(self, model_size: str = "small", device: str = "cuda",
                 compute_type: str = "float16"): ...  # line 47
    async def transcribe(self, audio_path: Path,
                         language: Optional[str] = None) -> TranscriptionResult: ...

# parrot.voice.handler
class TokenValidator:  # line 59
    def __init__(self, *, secret_key=None, algorithm="HS256",
                 validator_func=None, allow_anonymous=False): ...  # line 69

@dataclass
class AuthenticatedUser:  # line 49
    user_id: str
    username: str
    email: str = ""
    roles: list[str] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)
    raw_payload: dict[str, Any] = field(default_factory=dict)
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `AudioFormRenderer` | `AbstractFormRenderer` | inheritance | `renderers/base.py:57` |
| `AudioFormRenderer` | `register_renderer()` | function call | `api/render.py:60` |
| `AudioFormWSHandler` | `FormRegistry` | `app["form_registry"]` | `api/routes.py:123` |
| `AudioFormWSHandler` | `VoiceSynthesizer` | constructor injection | `voice/tts/synthesizer.py:21` |
| `AudioFormWSHandler` | `FasterWhisperBackend` | constructor injection | `voice/transcriber/faster_whisper_backend.py:21` |
| `AudioFormWSHandler` | `TokenValidator` | constructor injection | `voice/handler.py:59` |
| `AudioFormWSHandler` | `FormValidator` | constructor injection | `api/handlers.py:71` |
| `AudioFieldRenderer` | `FieldRenderer` protocol | implements | `renderers/base.py:15` |
| Route registration | `setup_form_api()` | modify function | `api/routes.py:85` |

### Does NOT Exist (Anti-Hallucination)

- ~~`FieldType.AUDIO`~~ — does not exist yet in `core/types.py`
- ~~`parrot_formdesigner.renderers.audio`~~ — no audio renderer module exists
- ~~`parrot_formdesigner.api.audio_ws`~~ — no WebSocket handler module exists
- ~~`parrot_formdesigner.audio`~~ — no audio subpackage exists
- ~~`parrot_formdesigner.renderers.fields.audio`~~ — no audio field renderer
- ~~`AudioFormRenderer`~~ — class does not exist anywhere

…(truncated)…
