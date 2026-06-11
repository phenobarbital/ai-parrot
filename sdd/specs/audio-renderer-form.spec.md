---
type: feature
base_branch: dev
---

# Feature Specification: Audio Renderer Form — Turn-by-Turn Voice with SuperTonic & Narration Fallbacks

**Feature ID**: FEAT-236
**Date**: 2026-06-12
**Author**: Jesus Lara
**Status**: approved
**Target version**: 1.x

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

FEAT-224 shipped the **FormDesigner Audio Renderer** — an `AudioFormRenderer`
plus an `AudioFormWSHandler` WebSocket that walk a `FormSchema` question by
question, narrating each question via TTS and accepting text or speech answers.
Two things have changed since that design, and one design gap has surfaced:

1. **Sub-second TTS now exists.** FEAT-231 (AgentTalk Voice Support) added the
   **SuperTonic** TTS backend (`SupertonicTTSBackend`) — an ONNX, sub-second
   text-to-speech model wired into `VoiceSynthesizer` via
   `TTSConfig(backend="supertonic")`. The current audio renderer hard-codes the
   Google backend, so it pays Google's round-trip latency on every question —
   exactly the latency that kills a natural turn-by-turn voice experience.

2. **`VoiceSynthesizer` moved to `ai-parrot-integrations`.** TTS/STT now live
   under `parrot.voice.*` inside the `ai-parrot-integrations` distribution
   (`parrot.voice.tts.synthesizer.VoiceSynthesizer`,
   `parrot.voice.transcriber.faster_whisper_backend.FasterWhisperBackend`). The
   renderer must depend on those paths as an optional integration, not bundle
   voice code.

3. **Not every question can be answered — or even narrated — by voice.** The
   current renderer *silently drops* `REST`, `ARRAY`, and `HIDDEN` fields from
   the question list (`renderers/audio.py:31`). For `HIDDEN` that is correct,
   but for a **required** `REST` or selection field it means the form can never
   be completed through the audio channel — the data is simply lost. Two
   distinct sub-problems hide under "drop it":
   - **Selection-style questions** (`select`, `multi_select`, `boolean`,
     `ranking`, `likert`, `nps`, …) *can* be narrated ("Choose one: red, green,
     or blue"), but the **answer cannot reliably come from free speech** — the
     user must make a direct selection on a radio/selector control.
   - **Structurally complex questions** (`rest`, `remote_response`, `file`,
     `image`, `location`, `signature`, `transfer_list`, `availability`,
     `array`) are too complex to translate into a spoken prompt at all and
     require a **visual fallback** to complete.

This feature **evolves the existing FEAT-224 modules in place** to: (a) adopt
SuperTonic as the preferred low-latency backend with a Google fallback, (b)
formalize a true turn-by-turn loop where the system asks by voice (TTS) and the
user answers by voice (STT), and (c) introduce a per-question **voice-capability
taxonomy** so that selection and complex fields are handled with an in-session
**hybrid fallback** instead of being dropped.

### Goals

- Adopt **SuperTonic** (`TTSConfig(backend="supertonic")`) as the preferred TTS
  backend for audio forms, with automatic **graceful fallback to Google** when
  SuperTonic's ONNX weights / `inference_fn` / extra are unavailable, and to
  text-only when no backend is usable.
- Classify every voiced question into a **`VoiceMode`** — `VOICE`,
  `PROMPT_SELECT`, or `VISUAL_FALLBACK` — derived from `FieldType` with a
  per-field override via `FormField.meta`.
- Stop silently dropping `REST`/`ARRAY`/selection fields: keep them in the
  session with the correct `VoiceMode` so **no required field is lost**.
- Deliver a **hybrid in-session** answer flow:
  - `VOICE` — narrate, accept speech/text, transcribe via Whisper.
  - `PROMPT_SELECT` — narrate the question (optionally enumerate options),
    collect the answer via a UI selection message (`answer_selection`).
  - `VISUAL_FALLBACK` — narrate a short bridge prompt, hand the client a
    single-field visual render to complete inline, then resume the voice flow.
- Add **low-confidence STT confirmation**: when a speech answer's confidence is
  below a configurable threshold, read the transcript back and require a
  confirm/repeat turn before storing; otherwise auto-advance.
- Preserve full backward compatibility of the existing WebSocket protocol —
  new message types and question fields are additive.

### Non-Goals (explicitly out of scope)

- Free-form voice conversation / dialogue agent (this remains structured form
  Q&A — see FEAT-224 Non-Goals; the voice talk path is FEAT-231).
- Implementing the SuperTonic ONNX graph I/O (`inference_fn`) — that remains a
  deployment concern wired per FEAT-231 §8; this feature only *selects* and
  *falls back* across backends.
- Server-side fuzzy mapping of free speech onto select options as the canonical
  answer path (the canonical `PROMPT_SELECT` answer is a UI selection; voice→
  option matching may be added later as a convenience and is **not** required
  here).
- New STT backends (Whisper remains the transcriber; Moonshine/OpenAI backends
  exist but are out of scope).
- Multi-language auto-detection mid-session (locale fixed at session start, per
  FEAT-224).

> Runtime "just drop the field" behavior for non-voiceable fields is rejected —
> see `renderers/audio.py:31` (`_SKIP_FIELD_TYPES`), which this feature
> replaces with the `VoiceMode` taxonomy so required fields are never lost.

---

## 2. Architectural Design

### Overview

The feature is an **in-place evolution** of the four FEAT-224 modules
(`audio/models.py`, `renderers/audio.py`, `api/audio_ws.py`, `api/routes.py`)
plus minor metadata. Three design pillars:

**1. SuperTonic-first synthesizer construction.** The renderer/handler build a
`VoiceSynthesizer` from `TTSConfig(backend="supertonic")` by default. A thin
helper, `build_audio_synthesizer()`, tries SuperTonic and, on any
`ImportError`/`ValueError`/`RuntimeError` raised at first synthesis (missing
extra, unconfigured weights, no `inference_fn`), transparently rebuilds a
Google-backed synthesizer. If Google is also unavailable, the session degrades
to **text-only** (questions are still delivered, just without `audio`). This
mirrors the FEAT-231 contract that *"graceful degradation to text-only is the
handler's responsibility"* (`supertonic_backend.py:19`).

**2. Voice-capability taxonomy (`VoiceMode`).** During
`split_into_questions()`, each field is classified:

| `VoiceMode` | Meaning | Default `FieldType`s |
|---|---|---|
| `VOICE` | Narrate the question **and** accept a spoken/typed answer. | `text`, `text_area`, `number`, `integer`, `email`, `phone`, `url`, `date`, `datetime`, `time`, `tags`, `password`* |
| `PROMPT_SELECT` | Narrate the question; answer comes from a UI **selection**, not free speech. | `select`, `multi_select`, `dynamic_select`, `boolean`, `ranking`, `likert`, `nps`, `color` |
| `VISUAL_FALLBACK` | Too complex to voice; render a single-field visual fallback inline. | `rest`, `remote_response`, `file`, `image`, `location`, `signature`, `transfer_list`, `availability`, `array` |

`HIDDEN` is still excluded entirely (never a question). `GROUP` is flattened to
its children (unchanged). `password` defaults to `VOICE` but **must not** be
narrated/echoed with its value — flagged `sensitive=True` so the client mutes
read-back. A form author can override the mode per field via
`FormField.meta["voice_mode"]` and customize the spoken prompt via
`FormField.meta["audio_hint"]` (resolved already in FEAT-224 §8).

**3. Hybrid turn-by-turn loop.** The WebSocket state machine drives each
question according to its `VoiceMode`:

```
Client                                 Server (AudioFormWSHandler)
  │                                        │
  ├─ start_session ──────────────────────►│ load form, classify questions,
  │                                        │ build synthesizer (supertonic→google→text)
  │◄── session_started ────────────────────┤
  │◄── question (voice_mode, render_mode,  │ synthesize prompt (SuperTonic, sub-second)
  │     audio, options?, fallback_html?) ──┤
  │                                        │
  │   VOICE:                               │
  ├─ answer_audio (binary) ───────────────►│ Whisper STT → confidence
  │◄── transcription ──────────────────────┤
  │      if confidence < threshold:        │
  │◄────── confirm_request ────────────────┤ read-back transcript
  ├─ confirm_answer {confirmed} ──────────►│ store or re-prompt
  │                                        │
  │   PROMPT_SELECT:                       │
  ├─ answer_selection {value|values} ─────►│ validate against options → store
  │                                        │
  │   VISUAL_FALLBACK:                     │
  ├─ answer_text / answer_payload ────────►│ validate → store
  │                                        │
  │◄── answer_accepted ────────────────────┤ advance
  │   ... (repeat per question) ...        │
  │◄── form_complete ──────────────────────┤ submit via FormSubmissionStorage
  └─ WS close ────────────────────────────►│ cleanup
```

### Component Diagram

```
┌──────────────────────────────────────────────────────────────┐
│  parrot-formdesigner  (evolved FEAT-224 modules)             │
│                                                              │
│  ┌──────────────┐    ┌──────────────────────────────────┐    │
│  │ FormSchema   │──► │ AudioFormRenderer                │    │
│  │ + FieldType  │    │  (renderers/audio.py)            │    │
│  │ + FormField  │    │  - classify_voice_mode(field)    │    │
│  │   .meta      │    │  - split_into_questions() ⟶ tags │    │
│  └──────────────┘    │    each AudioQuestion.voice_mode │    │
│                      └───────────────┬──────────────────┘    │
│                                      │                       │
│  ┌──────────────────────────────────▼──────────────────┐     │
│  │ AudioFormWSHandler (api/audio_ws.py)                │     │
│  │  - per-question dispatch by VoiceMode               │     │
│  │  - answer_selection / confirm_answer handlers       │     │
│  │  - low-confidence read-back gate                    │     │
│  │  - VISUAL_FALLBACK single-field render via HTML5    │     │
│  └─────────┬───────────────────┬───────────────┬───────┘     │
│            │                   │               │             │
│  ┌─────────▼────────┐  ┌───────▼────────┐  ┌───▼──────────┐  │
│  │ build_audio_     │  │ FasterWhisper  │  │ HTML5Renderer│  │
│  │ synthesizer()    │  │ Backend (STT)  │  │ (fallback    │  │
│  │ supertonic→google│  │                │  │  field HTML) │  │
│  └────────┬─────────┘  └────────────────┘  └──────────────┘  │
│           │                                                  │
│  ┌────────▼──────────────────────────┐                       │
│  │ VoiceSynthesizer (ai-parrot-       │                       │
│  │  integrations: parrot.voice.tts)   │                       │
│  │  TTSConfig(backend="supertonic")   │                       │
│  └────────────────────────────────────┘                      │
└──────────────────────────────────────────────────────────────┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AudioFormRenderer` (FEAT-224) | modify | Add `classify_voice_mode()`; stop dropping REST/ARRAY/select; build SuperTonic-first synthesizer. |
| `AudioFormWSHandler` (FEAT-224) | modify | Per-`VoiceMode` dispatch, `answer_selection`/`confirm_answer`, low-confidence gate, visual fallback. |
| `AudioQuestion` / `AudioSessionConfig` / `AudioAnswer` (FEAT-224) | extend | New fields (`voice_mode`, `render_mode`, `sensitive`, `fallback_html`); `AudioAnswer.source` adds `"selection"`. |
| `VoiceSynthesizer` | uses | `TTSConfig(backend="supertonic")`, fallback to `"google"`. |
| `TTSConfig` | uses | `backend` Literal already includes `"supertonic"` (`tts/models.py:41`). |
| `SupertonicTTSBackend` | uses (indirect) | Selected by `VoiceSynthesizer._get_backend()` (`synthesizer.py:81`). |
| `FasterWhisperBackend` | uses | STT + `TranscriptionResult.confidence` gates the read-back. |
| `HTML5Renderer` | uses | Render a single field's HTML for `VISUAL_FALLBACK` questions. |
| `FormValidator` | uses | Validates selection / fallback answers. |
| `_seed_default_renderers()` | unchanged | `"audio"` already registered (`api/render.py:59`). |
| `setup_form_api()` | unchanged signature | Already accepts `synthesizer`/`transcriber`/`token_validator` (`routes.py:99-101`). |
| `FieldType` | unchanged | `AUDIO` already exists (`core/types.py:53`); no new enum member. |

### Data Models

```python
from enum import Enum
from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict, Field


class VoiceMode(str, Enum):
    """How a question participates in the audio flow."""
    VOICE = "voice"                 # narrate + accept spoken/typed answer
    PROMPT_SELECT = "prompt_select" # narrate; answer via UI selection
    VISUAL_FALLBACK = "visual_fallback"  # render a single-field visual fallback


# AudioQuestion (extends FEAT-224 model — additive fields)
class AudioQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    index: int
    field_id: str
    field_type: str
    label: str
    description: Optional[str] = None
    required: bool = False
    audio_prompt: Optional[bytes] = None
    constraints: Optional[dict] = None
    options: Optional[list[dict]] = None
    # NEW
    voice_mode: VoiceMode = VoiceMode.VOICE
    render_mode: Literal["voice", "select", "visual"] = "voice"
    sensitive: bool = False          # mute TTS read-back (e.g. password)
    fallback_html: Optional[str] = None  # single-field HTML for VISUAL_FALLBACK


# AudioSessionConfig (extends FEAT-224 model)
class AudioSessionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    form_id: str
    locale: str = "en"
    tts_backend: Literal["supertonic", "google"] = "supertonic"  # NEW
    tts_voice: Optional[str] = None
    tts_mime_format: str = "audio/wav"   # SuperTonic emits WAV
    auto_advance: bool = True
    enumerate_options: bool = True       # NEW — read options aloud for PROMPT_SELECT
    stt_confirm_threshold: float = Field(default=0.6, ge=0.0, le=1.0)  # NEW


# AudioAnswer (extends FEAT-224 model — new source value)
class AudioAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field_id: str
    value: str
    source: Literal["text", "speech", "selection"] = "text"  # +"selection"
    confidence: Optional[float] = None
    raw_transcript: Optional[str] = None
```

### WebSocket Protocol (additive to FEAT-224)

**New / changed Client → Server:**
| Type | Payload | Description |
|---|---|---|
| `answer_selection` | `{field_id, value}` or `{field_id, values: [...]}` | Answer a `PROMPT_SELECT` question via UI selection (single or multi). |
| `answer_payload` | `{field_id, value}` | Answer a `VISUAL_FALLBACK` question after completing the inline visual render. |
| `confirm_answer` | `{field_id, confirmed: bool}` | Confirm (`true`) or reject (`false`) a low-confidence STT transcript. |

**New / changed Server → Client:**
| Type | Payload | Description |
|---|---|---|
| `question` | `{index, field_id, label, audio?, voice_mode, render_mode, sensitive, options?, fallback_html?}` | Now carries `voice_mode`/`render_mode` and (for `VISUAL_FALLBACK`) `fallback_html`. |
| `confirm_request` | `{field_id, transcript, confidence}` | Low-confidence STT — client should read back and ask the user to confirm. |

All existing FEAT-224 messages (`start_session`, `answer_text`, `answer_audio`,
`skip_question`, `go_back`, `repeat_question`, `end_session`, `ping`,
`session_started`, `transcription`, `answer_accepted`, `answer_rejected`,
`form_complete`, `error`, `pong`) are unchanged.

### New Public Interfaces

```python
# renderers/audio.py
def classify_voice_mode(field: FormField) -> VoiceMode:
    """Classify a field into a VoiceMode (meta override wins over the
    FieldType default table)."""

def build_audio_synthesizer(
    config: AudioSessionConfig | None = None,
) -> "VoiceSynthesizer | None":
    """Build a VoiceSynthesizer preferring SuperTonic, falling back to Google.
    Returns None when no TTS backend is usable (text-only session)."""
```

---

## 3. Module Breakdown

### Module 1: VoiceMode + Model Extensions
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/audio/models.py` (modify)
- **Responsibility**: Add `VoiceMode` enum; add `voice_mode`, `render_mode`,
  `sensitive`, `fallback_html` to `AudioQuestion`; add `tts_backend`,
  `enumerate_options`, `stt_confirm_threshold` and switch default
  `tts_mime_format` to `"audio/wav"` on `AudioSessionConfig`; add `"selection"`
  to `AudioAnswer.source`. All additive / backward-compatible.
- **Depends on**: None.

### Module 2: Voice-Capability Classification + SuperTonic-first Synthesizer
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/audio.py` (modify)
- **Responsibility**: Add `classify_voice_mode(field)` with the default
  `FieldType→VoiceMode` table + `FormField.meta["voice_mode"]` override. Replace
  the `_SKIP_FIELD_TYPES` drop logic: only `HIDDEN` is skipped; everything else
  becomes a question tagged with its `VoiceMode` and `render_mode`. Add
  `build_audio_synthesizer()` (supertonic→google→None). Mark `password` as
  `sensitive`.
- **Depends on**: Module 1.

### Module 3: Per-VoiceMode Session Dispatch + Fallback Handlers
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/api/audio_ws.py` (modify)
- **Responsibility**: Build the synthesizer via `build_audio_synthesizer()`.
  Add `_handle_answer_selection`, `_handle_answer_payload`,
  `_handle_confirm_answer`. Gate speech answers on
  `session.config.stt_confirm_threshold` — emit `confirm_request` below it and
  hold the answer pending until `confirm_answer`. For `VISUAL_FALLBACK`
  questions, render the single field via `HTML5Renderer` and attach
  `fallback_html` to the `question` message. Suppress TTS read-back/audio for
  `sensitive` questions. Carry an `AudioSessionConfig` on the session.
- **Depends on**: Module 1, Module 2.

### Module 4: Routes / Wiring Defaults
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py` (modify)
- **Responsibility**: When a caller passes no explicit `synthesizer`, allow the
  handler to lazily build a SuperTonic-first synthesizer (so audio works out of
  the box where weights are configured). Keep `setup_form_api()` signature
  backward-compatible (no new required args). Document the SuperTonic env
  (`SUPERTONIC_MODEL_PATH`) requirement in the route docstring.
- **Depends on**: Module 2, Module 3.

### Module 5: Tests
- **Path**: `packages/parrot-formdesigner/tests/formdesigner/test_audio_renderer.py`,
  `.../test_audio_ws_handler.py`, `.../test_audio_integration.py` (modify/extend)
- **Responsibility**: Unit tests for `classify_voice_mode`, the SuperTonic→Google
  fallback in `build_audio_synthesizer`, and the new model fields; WS tests for
  selection answers, low-confidence confirmation, and visual fallback flow.
- **Depends on**: Modules 1–4.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_voice_mode_enum_values` | M1 | `VoiceMode` has `VOICE`/`PROMPT_SELECT`/`VISUAL_FALLBACK`. |
| `test_audio_question_voice_fields_default` | M1 | `AudioQuestion` defaults: `voice_mode=VOICE`, `render_mode="voice"`, `sensitive=False`. |
| `test_audio_answer_source_selection` | M1 | `AudioAnswer(source="selection")` validates. |
| `test_session_config_supertonic_default` | M1 | `AudioSessionConfig.tts_backend == "supertonic"`, threshold default `0.6`. |
| `test_classify_text_is_voice` | M2 | `text`/`number`/`email` → `VOICE`. |
| `test_classify_select_is_prompt_select` | M2 | `select`/`multi_select`/`boolean`/`nps` → `PROMPT_SELECT`. |
| `test_classify_rest_is_visual_fallback` | M2 | `rest`/`file`/`location`/`signature`/`array` → `VISUAL_FALLBACK`. |
| `test_classify_meta_override` | M2 | `FormField.meta["voice_mode"]="visual_fallback"` overrides default. |
| `test_password_marked_sensitive` | M2 | `password` question has `sensitive=True`. |
| `test_split_keeps_rest_field` | M2 | REST field is NOT dropped; appears as a `VISUAL_FALLBACK` question. |
| `test_split_skips_hidden_only` | M2 | Only `HIDDEN` excluded from questions. |
| `test_build_synth_prefers_supertonic` | M2 | `build_audio_synthesizer()` returns a SuperTonic-config synthesizer when configured. |
| `test_build_synth_falls_back_to_google` | M2 | SuperTonic synth raising at first synthesize → Google synth used. |
| `test_build_synth_none_when_no_backend` | M2 | No usable backend → returns `None` (text-only). |

### Integration Tests
| Test | Description |
|---|---|
| `test_ws_prompt_select_flow` | `PROMPT_SELECT` question delivered with options; `answer_selection` accepted; advances. |
| `test_ws_multi_select_values` | `answer_selection {values:[...]}` stored for `multi_select`. |
| `test_ws_visual_fallback_flow` | REST question delivered with `fallback_html`; `answer_payload` accepted; required REST field completes the form. |
| `test_ws_low_confidence_confirm` | Speech answer below threshold → `confirm_request`; `confirm_answer{confirmed:true}` stores it. |
| `test_ws_low_confidence_reject_reprompts` | `confirm_answer{confirmed:false}` re-sends the question, no answer stored. |
| `test_ws_high_confidence_auto_advance` | Speech answer ≥ threshold auto-advances (no `confirm_request`). |
| `test_ws_sensitive_no_audio` | `password` question carries no TTS audio / read-back. |
| `test_ws_supertonic_to_google_degradation` | SuperTonic unavailable → session still delivers questions (Google audio or text-only). |

### Test Data / Fixtures
```python
@pytest.fixture
def mixed_mode_form() -> FormSchema:
    """A form exercising all three VoiceModes: a TEXT (VOICE), a SELECT
    (PROMPT_SELECT), and a required REST (VISUAL_FALLBACK)."""
    ...

@pytest.fixture
def mock_synthesizer():
    """VoiceSynthesizer stub returning WAV bytes; configurable to raise on
    first synthesize to exercise the SuperTonic→Google fallback."""
    ...

@pytest.fixture
def mock_transcriber():
    """FasterWhisperBackend stub returning a fixed TranscriptionResult with a
    parametrizable .confidence."""
    ...
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `VoiceMode` enum exists with `VOICE`, `PROMPT_SELECT`, `VISUAL_FALLBACK`.
- [ ] `AudioQuestion` carries `voice_mode`, `render_mode`, `sensitive`,
      `fallback_html` (additive, defaulted; existing fields unchanged).
- [ ] `AudioSessionConfig` defaults `tts_backend="supertonic"`,
      `stt_confirm_threshold=0.6`, `enumerate_options=True`,
      `tts_mime_format="audio/wav"`.
- [ ] `AudioAnswer.source` accepts `"selection"` in addition to `"text"`/`"speech"`.
- [ ] `classify_voice_mode()` maps field types per the §2 table and honors a
      `FormField.meta["voice_mode"]` override.
- [ ] The renderer **no longer drops** `REST`/`ARRAY`/selection fields; only
      `HIDDEN` is excluded. A required `REST` field can be completed via the
      `VISUAL_FALLBACK` path and the form submits successfully.
- [ ] `build_audio_synthesizer()` prefers SuperTonic and falls back to Google,
      then to text-only (`None`), without raising to the caller.
- [ ] Audio prompts are synthesized via SuperTonic when configured/available
      (sub-second backend), Google otherwise.
- [ ] `PROMPT_SELECT` questions are narrated (with option enumeration when
      `enumerate_options=True`) and answered via `answer_selection`.
- [ ] `VISUAL_FALLBACK` questions deliver a single-field `fallback_html` and are
      answered via `answer_payload`.
- [ ] Speech answers with confidence `< stt_confirm_threshold` trigger
      `confirm_request`; `confirm_answer{confirmed:true}` stores, `false`
      re-prompts. High-confidence answers auto-advance.
- [ ] `sensitive` questions (e.g. `password`) are delivered without TTS
      read-back of their value.
- [ ] `setup_form_api()` keeps its current signature; existing FEAT-224 WS
      messages still work unchanged (no breaking change).
- [ ] All tests pass: `pytest packages/parrot-formdesigner/tests/formdesigner/ -v`.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods not
> listed here without first verifying them via `grep`/`read`.

### Verified Imports

```python
# Core types & schema (formdesigner)
from parrot_formdesigner.core.types import FieldType, LocalizedString  # verified: core/types.py:13,16
from parrot_formdesigner.core.schema import FormField, FormSchema, RenderedForm  # verified: renderers/audio.py:18

# Audio models (FEAT-224 — to be EXTENDED, already exist)
from parrot_formdesigner.audio.models import (
    AudioQuestion,        # verified: audio/models.py:37
    AudioFormManifest,    # verified: audio/models.py:67
    AudioAnswer,          # verified: audio/models.py:92
    AudioSessionState,    # verified: audio/models.py:113
    AudioSessionConfig,   # verified: audio/models.py:16
)

# Audio renderer & handler (FEAT-224 — to be EXTENDED, already exist)
from parrot_formdesigner.renderers.audio import AudioFormRenderer  # verified: renderers/audio.py:65
from parrot_formdesigner.api.audio_ws import AudioFormWSHandler    # verified: api/audio_ws.py:56

# Render registry (audio already seeded)
from parrot_formdesigner.api.render import register_renderer, _seed_default_renderers  # verified: api/render.py:62,37

# Routes (already accepts voice deps)
from parrot_formdesigner.api.routes import setup_form_api  # verified: api/routes.py (signature 95-102)

# Validation & HTML5 fallback render
from parrot_formdesigner.services.validators import FormValidator  # verified: api/audio_ws.py:47 (TYPE_CHECKING)
from parrot_formdesigner.renderers.html5 import HTML5Renderer      # verified: api/render.py:53

# Voice TTS/STT (ai-parrot-integrations — PEP 420 namespace under parrot.voice)
from parrot.voice.tts.synthesizer import VoiceSynthesizer  # verified: voice/tts/synthesizer.py:21
from parrot.voice.tts.models import TTSConfig, SynthesisResult  # verified: voice/tts/models.py:16,79
from parrot.voice.tts.supertonic_backend import SupertonicTTSBackend  # verified: voice/tts/supertonic_backend.py:50
from parrot.voice.transcriber.faster_whisper_backend import FasterWhisperBackend  # verified: voice/transcriber/faster_whisper_backend.py:21
from parrot.voice.transcriber.models import TranscriptionResult  # verified: voice/transcriber/models.py:90
from parrot.voice.handler import TokenValidator, AuthenticatedUser  # verified: api/audio_ws.py:42 (TYPE_CHECKING)

from aiohttp import web, WSMsgType  # verified: api/audio_ws.py:31
```

### Existing Class Signatures

```python
# parrot_formdesigner/core/types.py
class FieldType(str, Enum):  # line 16 — AUDIO = "audio" exists (line 53); NO new member needed
LocalizedString = str | dict[str, str]  # line 13

# parrot_formdesigner/audio/models.py  (extra="forbid" — adding fields is safe; clients sending unknown keys still rejected)
class AudioQuestion(BaseModel):     # line 37  (index, field_id, field_type, label, description, required, audio_prompt, constraints, options)
class AudioSessionConfig(BaseModel):# line 16  (form_id, locale, tts_voice, tts_mime_format="audio/ogg", auto_advance=True)
class AudioAnswer(BaseModel):       # line 92  (source: Literal["text","speech"] — line 108)
class AudioSessionState(BaseModel): # line 113 (session_id, form_id, user_id, current_index, answers, manifest, completed)

# parrot_formdesigner/renderers/audio.py
class AudioFormRenderer(AbstractFormRenderer):  # line 65
    def __init__(self, synthesizer: Optional["VoiceSynthesizer"] = None) -> None: ...  # line 87
    def split_into_questions(self, form, *, locale="en") -> list[AudioQuestion]: ...   # line 100
    def _field_to_questions(self, field, *, locale="en") -> list[AudioQuestion]: ...   # line 141
    async def render(self, form, style=None, *, locale="en", prefilled=None, errors=None) -> RenderedForm: ...  # line 204
_SKIP_FIELD_TYPES = frozenset({FieldType.HIDDEN, FieldType.ARRAY, FieldType.REST})  # line 31 — REPLACE: skip HIDDEN only
_SELECT_TYPES = frozenset({FieldType.SELECT, FieldType.MULTI_SELECT, FieldType.DYNAMIC_SELECT})  # line 36

# parrot_formdesigner/api/audio_ws.py
class AudioFormWSHandler:  # line 56
    def __init__(self, registry, synthesizer, transcriber, validator, *,
                 token_validator=None, submission_storage=None,
                 max_msg_size=10*1024*1024) -> None: ...  # line 90
    async def handle_websocket(self, request) -> web.WebSocketResponse: ...  # line 115
    async def _dispatch_text(self, ws, msg_type, data, session, request, audio_cache): ...  # line 258 — extend handlers dict (line 277)
    async def _handle_answer_text(...): ...     # line 375
    async def _handle_answer_audio(self, ws, audio_bytes, session, audio_cache): ...  # line 394 (confidence at result.confidence)
    async def _accept_answer(...): ...          # line 573
    async def _send_question(self, ws, question, audio_cache): ...  # line 718 — extend message dict (line 744)
MAX_QUESTIONS = 10  # line 53

# parrot.voice.tts.synthesizer
class VoiceSynthesizer:  # line 21
    def __init__(self, config: Optional[TTSConfig] = None) -> None: ...  # line 46
    def _get_backend(self) -> AbstractTTSBackend: ...  # line 52 — dispatches "google"/"supertonic" (lines 73,81)
    async def synthesize(self, text, *, language=None) -> SynthesisResult: ...  # line 102
    async def close(self) -> None: ...  # line 147

# parrot.voice.tts.models
class TTSConfig(BaseModel):  # line 16
    backend: Literal["google","elevenlabs","openai","supertonic"] = "google"  # line 41
    voice: Optional[str] = None        # line 48
    language: Optional[str] = None     # line 52
    mime_format: str = "audio/ogg"     # line 56
class SynthesisResult(BaseModel):  # line 79  — .audio: bytes (line 100), .mime_format: str (line 108)

# parrot.voice.tts.supertonic_backend
class SupertonicTTSBackend(AbstractTTSBackend):  # line 50
    # emits WAV (audio/wav); raises ImportError/ValueError/RuntimeError when the
    # voice-supertonic extra / SUPERTONIC_MODEL_PATH weights / inference_fn are
    # missing (lines 150,124,262). Graceful degradation is the handler's job (line 19).
    async def synthesize(self, text, *, voice=None, mime_format="audio/ogg", language=None) -> SynthesisResult: ...  # line 163

# parrot.voice.transcriber.faster_whisper_backend
class FasterWhisperBackend(AbstractTranscriberBackend):  # line 21
    async def transcribe(self, audio_path, language=None) -> TranscriptionResult: ...  # line 83

# parrot.voice.transcriber.models
class TranscriptionResult(BaseModel):  # line 90 — .text (line 98), .confidence: Optional[float] (line 111)

# parrot_formdesigner/api/render.py
def _seed_default_renderers() -> None: ...  # line 37 — seeds "audio" via AudioFormRenderer() (line 59)

# parrot_formdesigner/api/routes.py — setup_form_api already accepts:
#   synthesizer: VoiceSynthesizer | None = None   # line 99
#   transcriber: FasterWhisperBackend | None = None  # line 100
#   token_validator: TokenValidator | None = None    # line 101
# and mounts GET {bp}/forms/{form_id}/audio/ws when any is provided (lines 247-263)
```

### Integration Points

| New / Changed Component | Connects To | Via | Verified At |
|---|---|---|---|
| `classify_voice_mode()` | `FieldType` + `FormField.meta` | default table + override | `core/types.py:16`, schema meta |
| `build_audio_synthesizer()` | `VoiceSynthesizer(TTSConfig(backend="supertonic"))` | constructor + lazy backend | `synthesizer.py:46,81` |
| Synthesizer fallback | `SupertonicTTSBackend` raises → rebuild with `backend="google"` | try/except around first `synthesize()` | `supertonic_backend.py:150,262` |
| Low-confidence gate | `TranscriptionResult.confidence` vs `stt_confirm_threshold` | comparison in `_handle_answer_audio` | `transcriber/models.py:111`, `audio_ws.py:435` |
| Visual fallback | `HTML5Renderer` single-field render → `fallback_html` | render call in `_send_question` | `audio_ws.py:744`, `api/render.py:53` |
| `answer_selection`/`confirm_answer` | `AudioFormWSHandler._dispatch_text` handlers dict | new keys | `audio_ws.py:277` |

### Does NOT Exist (Anti-Hallucination)

- ~~`VoiceMode`~~ — enum does not exist yet; add to `audio/models.py`.
- ~~`AudioQuestion.voice_mode` / `.render_mode` / `.sensitive` / `.fallback_html`~~ — not present; add (additive).
- ~~`AudioSessionConfig.tts_backend` / `.stt_confirm_threshold` / `.enumerate_options`~~ — not present; add.
- ~~`AudioAnswer.source == "selection"`~~ — current `Literal["text","speech"]` only (`audio/models.py:108`); extend.
- ~~`classify_voice_mode` / `build_audio_synthesizer`~~ — functions do not exist; add to `renderers/audio.py`.
- ~~`AudioFormWSHandler._handle_answer_selection` / `_handle_answer_payload` / `_handle_confirm_answer`~~ — do not exist; add.
- ~~`VoiceSynthesizer.synthesize_to_base64()`~~ — no such method; use `synthesize()` → `result.audio`, then `base64.b64encode`.
- ~~`SupertonicTTSBackend` returning OGG~~ — it always returns `audio/wav` (`supertonic_backend.py:38`); do not assume OGG.
- ~~`FasterWhisperBackend.transcribe_bytes()`~~ — does not exist; `transcribe()` takes a `Path`; write bytes to a temp file first (as `audio_ws.py:419-431` already does).
- ~~A new `FieldType` member for audio forms~~ — `FieldType.AUDIO` already exists (`core/types.py:53`); this feature adds **no** enum member.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Renderer/handler are evolved in place** — do not create parallel
  `audio2`/`v2` modules. Keep existing public symbols
  (`AudioFormRenderer`, `AudioFormWSHandler`) stable; additions only.
- **SuperTonic graceful degradation** — never let a missing weight/extra crash
  the session. Wrap the first `synthesize()` in try/except and rebuild with
  Google; if Google also fails, deliver questions text-only (audio omitted).
  This is the explicit FEAT-231 contract (`supertonic_backend.py:19`).
- **Temp-file STT** — Whisper takes a `Path`; reuse the existing
  `tempfile.NamedTemporaryFile` pattern (`audio_ws.py:419-461`). Note SuperTonic
  output is WAV; the inbound *answer* audio format is independent (client-set,
  default OGG) and unchanged.
- **Pydantic `extra="forbid"`** on the audio models means new optional fields
  are safe to add server-side, but the client must not send unknown keys — keep
  new client→server messages to the documented shapes.
- **Async throughout** — TTS and STT are async; never block the loop.
- **Localized strings** — reuse `_resolve()` (`renderers/audio.py:41`) for
  labels, options, and `audio_hint`.

### Known Risks / Gotchas

- **SuperTonic needs `SUPERTONIC_MODEL_PATH` + an `inference_fn`** wired at the
  deployment level (`supertonic_backend.py:122,262`). Without them SuperTonic
  raises at first synthesis — the fallback path MUST be exercised in tests
  (`test_build_synth_falls_back_to_google`).
- **MIME format mismatch** — SuperTonic returns `audio/wav`, the FEAT-224
  default config used `audio/ogg`. Switch `AudioSessionConfig.tts_mime_format`
  default to `audio/wav` and ensure the `question` message reports the actual
  format so the client `<audio>` element plays it.
- **`MAX_QUESTIONS = 10` truncation** (`audio_ws.py:53`) now interacts with
  fallback fields: truncation must not silently drop a required field. Prefer
  surfacing an error/warning over truncating away required questions (revisit
  the cap — see Open Questions).
- **Low-confidence gate ordering** — store the pending transcript on the session
  while awaiting `confirm_answer`; do not advance `current_index` until
  confirmed. A `confirm_answer{confirmed:false}` must re-send the *same*
  question, not skip it.
- **Cross-package optional dep** — `parrot-formdesigner` depends on
  `ai-parrot-integrations` (`parrot.voice.*`) only as an optional extra; forms
  without audio must import/run without the voice stack installed (keep the
  `TYPE_CHECKING` import guards already in `audio_ws.py:41-48`).
- **Sensitive read-back** — never synthesize or echo a `password` value; only
  narrate the prompt label.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `ai-parrot-integrations[voice-supertonic]` | current | SuperTonic ONNX backend (`onnxruntime` + weights). Optional extra. |
| `faster-whisper` | `>=1.0` | STT transcription (already a voice dep). |
| `google-cloud-texttospeech` | `>=2.0` | Google TTS fallback backend. |
| `aiohttp` | `>=3.9` | WebSocket server (already a dependency). |
| `PyJWT` | `>=2.0` | JWT validation in `TokenValidator` (already a voice dep). |

---

## 8. Open Questions

> Questions resolved with the user during spec authoring are marked `[x]`.

- [x] Default TTS backend for audio forms? — *Resolved with user*: **SuperTonic-first,
      Google fallback** (then text-only if neither is usable).
- [x] How to handle non-voice-answerable fields (selection) and complex fields
      (REST/file/location)? — *Resolved with user*: **Hybrid in-session** — narrate
      and collect a UI `answer_selection` for selection fields; render a
      single-field visual fallback (`fallback_html` / `answer_payload`) for
      complex fields. No field is dropped.
- [x] Confirm transcribed answers before storing? — *Resolved with user*:
      **Confirm only low-confidence** — auto-advance when STT confidence ≥
      `stt_confirm_threshold` (default 0.6), otherwise emit `confirm_request`.
- [x] Should the `MAX_QUESTIONS = 10` cap be raised or made
      per-session-configurable now that fallback fields keep more questions in
      the flow, and what is the exact behavior when a required field would be
      truncated? — *Owner: Jesus*: per-form be configurable, by default 10
- [x] For `PROMPT_SELECT`, should the server also attempt best-effort voice→
      option fuzzy matching as a convenience (selection still canonical), and if
      so what confidence gate applies? — *Owner: Jesus* (deferrable — Non-Goal
      for this iteration).: best-effort, in low confidence we can also uses an LLM to review and refine the text
- [x] Should `VISUAL_FALLBACK` answers reuse the existing REST resolver /
      `blob_storage` pipeline for file/REST payloads, or collect a reference
      only and resolve at final submission? — *Owner: Jesus*: yes, re-use

---

## Worktree Strategy

- **Isolation unit**: `per-spec` — all tasks run sequentially in one worktree.
- **Rationale**: The five modules form a strict dependency chain
  (models → renderer/classification → WS dispatch → routes → tests); they all
  touch the same four FEAT-224 files, so parallel worktrees would only create
  merge conflicts.
- **Cross-feature dependencies**: Depends on FEAT-224 (audio renderer modules,
  merged) and FEAT-231 (SuperTonic backend, merged) already being present on
  `dev`. No other spec must merge first.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-06-12 | Jesus Lara | Initial draft — SuperTonic adoption, VoiceMode taxonomy, hybrid in-session fallbacks, low-confidence STT confirmation. |
