---
type: Wiki Overview
title: 'Feature Specification: Audio Renderer Form — Turn-by-Turn Voice with SuperTonic
  & Narration Fallbacks'
id: doc:sdd-specs-audio-renderer-form-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: FEAT-224 shipped the **FormDesigner Audio Renderer** — an `AudioFormRenderer`
relates_to:
- concept: mod:parrot.voice
  rel: mentions
- concept: mod:parrot.voice.handler
  rel: mentions
- concept: mod:parrot.voice.transcriber.faster_whisper_backend
  rel: mentions
- concept: mod:parrot.voice.transcriber.models
  rel: mentions
- concept: mod:parrot.voice.tts
  rel: mentions
- concept: mod:parrot.voice.tts.models
  rel: mentions
- concept: mod:parrot.voice.tts.supertonic_backend
  rel: mentions
- concept: mod:parrot.voice.tts.synthesizer
  rel: mentions
---

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

…(truncated)…
