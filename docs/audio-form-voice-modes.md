# Audio Form Voice Modes — Developer Guide

**Feature**: FEAT-236 (extends FEAT-224)
**Package**: `parrot-formdesigner`
**Min version**: 1.x

> **Prerequisites**: read [`formdesigner-audio-renderer.md`](formdesigner-audio-renderer.md)
> for the baseline FEAT-224 architecture. This guide documents the FEAT-236
> extensions: SuperTonic TTS, the VoiceMode taxonomy, hybrid answer flows, and the
> low-confidence STT confirmation gate.

---

## Table of Contents

1. [What Changed in FEAT-236](#1-what-changed-in-feat-236)
2. [Architecture — Hybrid Voice Flow](#2-architecture--hybrid-voice-flow)
3. [Server Setup](#3-server-setup)
   - 3.1 [Basic setup (SuperTonic-first, auto-fallback)](#31-basic-setup-supertonic-first-auto-fallback)
   - 3.2 [Full setup with explicit synthesizer override](#32-full-setup-with-explicit-synthesizer-override)
   - 3.3 [Environment variables for SuperTonic](#33-environment-variables-for-supertonic)
4. [REST Endpoint — Audio Manifest](#4-rest-endpoint--audio-manifest)
   - 4.1 [Request](#41-request)
   - 4.2 [Response — full payload with VoiceMode](#42-response--full-payload-with-voicemode)
5. [VoiceMode Taxonomy](#5-voicemode-taxonomy)
   - 5.1 [Classification table](#51-classification-table)
   - 5.2 [Per-field override via meta](#52-per-field-override-via-meta)
6. [start_session — Extended Payload](#6-start_session--extended-payload)
7. [WebSocket Protocol — Complete Message Reference](#7-websocket-protocol--complete-message-reference)
   - 7.1 [Client → Server messages](#71-client--server-messages)
   - 7.2 [Server → Client messages](#72-server--client-messages)
8. [Flow Diagrams by VoiceMode](#8-flow-diagrams-by-voicemode)
   - 8.1 [VOICE — spoken or typed answer](#81-voice--spoken-or-typed-answer)
   - 8.2 [PROMPT\_SELECT — narrated + UI selection](#82-prompt_select--narrated--ui-selection)
   - 8.3 [VISUAL\_FALLBACK — inline visual render](#83-visual_fallback--inline-visual-render)
   - 8.4 [STT confidence gate](#84-stt-confidence-gate)
9. [Frontend Integration Guide](#9-frontend-integration-guide)
   - 9.1 [Connecting and authenticating](#91-connecting-and-authenticating)
   - 9.2 [Starting a session with TTS config](#92-starting-a-session-with-tts-config)
   - 9.3 [Rendering a question by VoiceMode](#93-rendering-a-question-by-voicemode)
   - 9.4 [VOICE questions — text and speech answers](#94-voice-questions--text-and-speech-answers)
   - 9.5 [PROMPT\_SELECT questions — UI selection](#95-prompt_select-questions--ui-selection)
   - 9.6 [VISUAL\_FALLBACK questions — inline render + payload](#96-visual_fallback-questions--inline-render--payload)
   - 9.7 [STT confirm flow](#97-stt-confirm-flow)
   - 9.8 [Navigation helpers](#98-navigation-helpers)
   - 9.9 [Playing TTS audio (WAV)](#99-playing-tts-audio-wav)
   - 9.10 [Full vanilla JS reference client](#910-full-vanilla-js-reference-client)
   - 9.11 [React / TypeScript component](#911-react--typescript-component)
10. [Error Codes](#10-error-codes)
11. [Security Considerations](#11-security-considerations)
12. [FAQ](#12-faq)

---

## 1. What Changed in FEAT-236

| Area | FEAT-224 (baseline) | FEAT-236 (this guide) |
|------|--------------------|-----------------------|
| **TTS backend** | Google only | SuperTonic (sub-second ONNX) → Google fallback → text-only |
| **TTS audio format** | `audio/ogg` | `audio/wav` (SuperTonic native) |
| **Field handling** | REST, ARRAY, HIDDEN silently dropped | Only HIDDEN dropped; REST/ARRAY get `VISUAL_FALLBACK`; no required field is lost |
| **Question metadata** | `index, field_id, label, required, field_type, audio, options` | + `voice_mode`, `render_mode`, `sensitive`, `fallback_html` |
| **Answer sources** | `text`, `speech` | + `selection` (PROMPT\_SELECT), `text` reused for visual payload |
| **Client message types** | `start_session`, `answer_text`, `answer_audio` (binary), `skip_question`, `go_back`, `repeat_question`, `end_session`, `ping` | + `answer_selection`, `answer_payload`, `confirm_answer` |
| **Server message types** | `session_started`, `question`, `transcription`, `answer_accepted`, `answer_rejected`, `form_complete`, `session_ended`, `error`, `pong` | + `confirm_request` |
| **STT confidence** | Auto-advance always | Below threshold → `confirm_request` → `confirm_answer` gate |
| **Session config** | `form_id`, `locale` only | + `tts_backend`, `tts_voice`, `tts_mime_format`, `auto_advance`, `enumerate_options`, `stt_confirm_threshold` |
| **Sensitive fields** | Not addressed | Password fields delivered without TTS audio; transcript masked as `[hidden]` |

---

## 2. Architecture — Hybrid Voice Flow

```
Frontend                              Backend (parrot-formdesigner)
   │                                             │
   │  GET /api/v1/forms/{id}/render/audio        │
   ├────────────────────────────────────────────►│  AudioFormRenderer
   │◄── AudioFormManifest (voice_mode per Q) ────┤  classify_voice_mode()
   │                                             │
   │  WS wss://…/forms/{id}/audio/ws             │
   ├────────────────────────────────────────────►│  AudioFormWSHandler
   │  Sec-WebSocket-Protocol: <JWT>              │  ↳ JWT auth
   │                                             │
   │  → start_session { tts_backend: "supertonic", … }
   │◄── session_started                          │  build AudioFormManifest
   │◄── question [0] { voice_mode: "voice", … }  │  SuperTonic TTS (lazy)
   │                                             │
   │  ── VOICE question ─────────────────────────│
   │  (play WAV audio)                           │
   │  [binary frame: recorded speech]            │
   ├────────────────────────────────────────────►│  FasterWhisper STT
   │◄── transcription { text, confidence: 0.95 } │
   │◄── answer_accepted { source: "speech" }     │
   │◄── question [1] { voice_mode: "prompt_select", options: […] }
   │                                             │
   │  ── PROMPT_SELECT question ─────────────────│
   │  (display radio buttons / select list)      │
   │  → answer_selection { field_id, value }     │
   ├────────────────────────────────────────────►│
   │◄── answer_accepted { source: "selection" }  │
   │◄── question [2] { voice_mode: "visual_fallback", fallback_html }
   │                                             │
   │  ── VISUAL_FALLBACK question ───────────────│
   │  (inject fallback_html into DOM)            │
   │  → answer_payload { field_id, value }       │
   ├────────────────────────────────────────────►│
   │◄── answer_accepted                          │
   │◄── form_complete { submission_id, answers } │
   │                                             │
   │  ── Low-confidence STT gate (any VOICE Q) ──│
   │  [binary: low-confidence speech]            │
   ├────────────────────────────────────────────►│
   │◄── transcription { confidence: 0.35 }       │
   │◄── confirm_request { transcript }           │
   │  → confirm_answer { confirmed: true/false } │
   ├────────────────────────────────────────────►│
   │◄── answer_accepted  OR  re-sent question    │
   │                                             │
   └─ WS close ─────────────────────────────────►│
```

### Components involved

| Component | Location | Role |
|-----------|----------|------|
| `AudioFormRenderer` | `renderers/audio.py` | Classifies fields into VoiceMode; builds manifest |
| `classify_voice_mode()` | `renderers/audio.py` | FieldType → VoiceMode lookup (with meta override) |
| `build_audio_synthesizer()` | `renderers/audio.py` | Constructs VoiceSynthesizer (SuperTonic → Google → None) |
| `synthesize_with_fallback()` | `renderers/audio.py` | Per-utterance fallback chain (never raises) |
| `AudioFormWSHandler` | `api/audio_ws.py` | WebSocket session state machine |
| `AudioSessionConfig` | `audio/models.py` | Per-session TTS/STT config |
| `VoiceMode` | `audio/models.py` | `VOICE`, `PROMPT_SELECT`, `VISUAL_FALLBACK` enum |
| `setup_form_api()` | `api/routes.py` | Mounts WS + REST routes on aiohttp app |

---

## 3. Server Setup

### 3.1 Basic setup (SuperTonic-first, auto-fallback)

The simplest production setup: provide `transcriber` and `token_validator`;
let the handler pick the TTS backend lazily.

```python
from aiohttp import web
from parrot_formdesigner.api.routes import setup_form_api
from parrot_formdesigner.services.registry import FormRegistry
from parrot.voice.transcriber.faster_whisper_backend import FasterWhisperBackend
from parrot.voice.handler import TokenValidator
import os

app = web.Application()
registry = FormRegistry(require_tenant=False)

setup_form_api(
    app,
    registry,
    # No synthesizer= here → auto_synthesize=True is set internally.
    # The handler will try SuperTonic first, then Google, then text-only.
    # SUPERTONIC_MODEL_PATH env var controls the ONNX weights path.
    transcriber=FasterWhisperBackend(model_size="base"),
    token_validator=TokenValidator(secret_key=os.environ["JWT_SECRET"]),
)

# Routes now available:
# GET  /api/v1/forms/{form_id}/render/audio
# GET  /api/v1/forms/{form_id}/audio/ws     (WebSocket)
```

### 3.2 Full setup with explicit synthesizer override

Use this when you want to pin a specific backend or inject a test synthesizer.

```python
from parrot.voice.tts.synthesizer import VoiceSynthesizer
from parrot.voice.tts.models import TTSConfig

# Pin SuperTonic explicitly (no auto-detect)
synthesizer = VoiceSynthesizer(
    TTSConfig(
        backend="supertonic",
        mime_format="audio/wav",   # SuperTonic native output
    )
)

setup_form_api(
    app,
    registry,
    synthesizer=synthesizer,     # explicit → auto_synthesize is False
    transcriber=FasterWhisperBackend(model_size="base"),
    token_validator=TokenValidator(secret_key=os.environ["JWT_SECRET"]),
    submission_storage=my_submission_storage,
)
```

### 3.3 Environment variables for SuperTonic

SuperTonic uses an ONNX graph pipeline. No ONNX model is loaded at
route-setup time — everything is lazy on the first `synthesize()` call.

| Variable | Required | Description |
|----------|----------|-------------|
| `SUPERTONIC_MODEL_PATH` | Yes (SuperTonic) | Absolute path to the ONNX weights directory |
| `JWT_SECRET` | Yes (production) | HMAC secret for `TokenValidator` |

If `SUPERTONIC_MODEL_PATH` is unset or the ONNX graph fails to load,
the handler automatically falls back to Google TTS (no exception, only a
`WARNING` log). If Google is also unavailable, questions are delivered
text-only (no `audio` field).

---

## 4. REST Endpoint — Audio Manifest

### 4.1 Request

```
GET /api/v1/forms/{form_id}/render/audio
Authorization: Bearer <jwt>
Accept-Language: es          (optional — determines question locale)
```

Query parameters:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `locale` | `"en"` | BCP 47 locale for label resolution |

### 4.2 Response — full payload with VoiceMode

`200 OK`, `Content-Type: application/json`

```json
{
  "form_id": "customer-intake",
  "title": "Customer Intake Form",
  "total_questions": 5,
  "locale": "en",
  "ws_endpoint": "/api/v1/forms/customer-intake/audio/ws",
  "questions": [
    {
      "index": 0,
      "field_id": "full_name",
      "field_type": "text",
      "label": "What is your full name?",
      "description": "Please include first and last name.",
      "required": true,
      "constraints": { "max_length": 100 },
      "options": null,
      "voice_mode": "voice",
      "render_mode": "voice",
      "sensitive": false,
      "fallback_html": null
    },
    {
      "index": 1,
      "field_id": "department",
      "field_type": "select",
      "label": "Which department do you work in?",
      "description": null,
      "required": true,
      "constraints": null,
      "options": [
        { "value": "eng",  "label": "Engineering" },
        { "value": "mkt",  "label": "Marketing" },
        { "value": "ops",  "label": "Operations" },
        { "value": "hr",   "label": "Human Resources" }
      ],
      "voice_mode": "prompt_select",
      "render_mode": "select",
      "sensitive": false,
      "fallback_html": null
    },
    {
      "index": 2,
      "field_id": "satisfaction",
      "field_type": "nps",
      "label": "How likely are you to recommend us? (0–10)",
      "description": null,
      "required": true,
      "constraints": null,
      "options": null,
      "voice_mode": "prompt_select",
      "render_mode": "select",
      "sensitive": false,
      "fallback_html": null
    },
    {
      "index": 3,
      "field_id": "contract",
      "field_type": "file",
      "label": "Please upload your signed contract.",
      "description": "PDF or image format accepted.",
      "required": false,
      "constraints": null,
      "options": null,
      "voice_mode": "visual_fallback",
      "render_mode": "visual",
      "sensitive": false,
      "fallback_html": "<input type=\"file\" name=\"contract\" accept=\".pdf,.jpg,.png\" />"
    },
    {
      "index": 4,
      "field_id": "password",
      "field_type": "password",
      "label": "Create a PIN",
      "description": null,
      "required": true,
      "constraints": null,
      "options": null,
      "voice_mode": "voice",
      "render_mode": "voice",
      "sensitive": true,
      "fallback_html": null
    }
  ]
}
```

> **Note**: `audio_prompt` (TTS bytes) is **never** serialized to JSON.
> TTS audio is delivered in real-time through the WebSocket as base64
> within each `question` message.

---

## 5. VoiceMode Taxonomy

### 5.1 Classification table

Every field in the form is assigned a `VoiceMode`. The renderer classifies
fields by `FieldType`; a per-field `meta` override wins.

| VoiceMode | `render_mode` | FieldTypes | Session behaviour |
|-----------|---------------|------------|-------------------|
| `VOICE` | `"voice"` | `text`, `email`, `phone`, `number`, `date`, `time`, `textarea`, `url`, `audio`, `password`, `integer`, `float`, `currency`, `zipcode`, `rating`, `duration`, `radio`, `checkbox` | Narrate question → accept `answer_text` (keyboard) or binary frame (speech) |
| `PROMPT_SELECT` | `"select"` | `select`, `multi_select`, `dynamic_select`, `boolean`, `ranking`, `likert`, `nps`, `color` | Narrate question + options → accept `answer_selection` only |
| `VISUAL_FALLBACK` | `"visual"` | `rest`, `remote_response`, `file`, `image`, `location`, `signature`, `transfer_list`, `availability`, `array` | Narrate a bridge prompt → send `fallback_html` inline → accept `answer_payload` |
| *(skipped)* | — | `hidden` | Field is omitted from the question list entirely |

### 5.2 Per-field override via meta

Any field can override its VoiceMode by setting `meta.voice_mode` in the
`FormField` definition. This is useful for custom field types or exceptional
cases (e.g. force a `boolean` to become `VOICE` for natural language parsing).

```python
from parrot_formdesigner.core.schema import FormField
from parrot_formdesigner.core.types import FieldType

# Force a boolean to VOICE mode (non-default)
agree_field = FormField(
    field_id="agree",
    field_type=FieldType.BOOLEAN,
    label="Do you agree to the terms?",
    required=True,
    meta={"voice_mode": "voice"},   # override: will accept text answer
)

# Force a text field to visual (e.g. rich text editor)
rich_field = FormField(
    field_id="bio",
    field_type=FieldType.TEXTAREA,
    label="Tell us about yourself",
    meta={"voice_mode": "visual_fallback"},
)
```

Invalid override values are logged as warnings and fall back to the default
FieldType classification.

---

## 6. start_session — Extended Payload

FEAT-236 adds optional TTS/STT configuration keys to `start_session`.
All keys are optional; omitted keys use the model defaults.

```json
{
  "type": "start_session",
  "form_id": "customer-intake",
  "locale": "es",

  "tts_backend": "supertonic",
  "tts_voice": null,
  "tts_mime_format": "audio/wav",
  "auto_advance": true,
  "enumerate_options": true,
  "stt_confirm_threshold": 0.6
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `form_id` | string | (from URL) | Form to load. If omitted uses the `{form_id}` URL param. |
| `locale` | string | `"en"` | BCP 47 locale for label resolution and TTS language. |
| `tts_backend` | `"supertonic"` \| `"google"` | `"supertonic"` | Preferred TTS backend. The handler falls back automatically when the preferred backend is unavailable. |
| `tts_voice` | string \| null | `null` | Optional voice name forwarded to the TTS backend. |
| `tts_mime_format` | string | `"audio/wav"` | MIME type of the TTS output. `audio/wav` is the SuperTonic native format. Change to `"audio/ogg"` for the Google backend. |
| `auto_advance` | boolean | `true` | When `true`, advance to the next question immediately after a valid answer. |
| `enumerate_options` | boolean | `true` | When `true`, read option labels aloud for `PROMPT_SELECT` questions: *"Choose one: Engineering, Marketing, Operations."* |
| `stt_confirm_threshold` | float 0–1 | `0.6` | STT confidence below this value triggers a `confirm_request` instead of auto-advancing. |

---

## 7. WebSocket Protocol — Complete Message Reference

### 7.1 Client → Server messages

All text frames are JSON with a `"type"` field. Binary frames are raw audio.

---

#### `start_session`

Opens the audio form session. Must be the first message after authenticating.
See §6 for the full payload.

```json
{
  "type": "start_session",
  "form_id": "customer-intake",
  "locale": "en",
  "tts_backend": "supertonic",
  "enumerate_options": true,
  "stt_confirm_threshold": 0.6
}
```

---

#### `answer_text`

Submits a typed (keyboard) answer to the current `VOICE` question.

```json
{
  "type": "answer_text",
  "field_id": "full_name",
  "value": "Jane Smith"
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `field_id` | Yes | Must match the `field_id` of the current question |
| `value` | Yes | Answer string |

---

#### Binary frame — speech answer (`answer_audio`)

For `VOICE` questions, send a raw binary WebSocket frame containing the
recorded audio. No JSON wrapper — just the bytes directly.

```javascript
ws.send(audioBlob);          // Blob from MediaRecorder
// or
ws.send(audioArrayBuffer);   // ArrayBuffer
```

Supported formats: `audio/webm`, `audio/mp4`, `audio/ogg`.

---

#### `answer_selection`

Submits a UI selection for a `PROMPT_SELECT` question. Supports both
single-select (`value`) and multi-select (`values`).

**Single select:**
```json
{
  "type": "answer_selection",
  "field_id": "department",
  "value": "eng"
}
```

**Multi-select:**
```json
{
  "type": "answer_selection",
  "field_id": "tags",
  "values": ["backend", "python", "async"]
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `field_id` | Yes | Must match current question's `field_id` |
| `value` | One of | Single option value (must be in the question's `options` list) |
| `values` | One of | Array of option values (for `multi_select` fields) |

Multi-select values are stored as a comma-joined string: `"backend,python,async"`.

---

#### `answer_payload`

Submits the value collected from an inline `VISUAL_FALLBACK` field.

```json
{
  "type": "answer_payload",
  "field_id": "contract",
  "value": "https://storage.example.com/uploads/contract-12345.pdf"
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `field_id` | Yes | Must match current question's `field_id` |
| `value` | Yes | Value collected by the inline visual field (URL, blob reference, etc.) |

---

#### `confirm_answer`

Confirms or rejects a low-confidence STT transcript after a `confirm_request`.

```json
{
  "type": "confirm_answer",
  "field_id": "full_name",
  "confirmed": true
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `field_id` | No | Field ID being confirmed (validated against pending answer) |
| `confirmed` | Yes | `true` → store and advance; `false` → discard and re-send question |

---

#### `skip_question`

Skips the current optional question. Returns `answer_rejected` for required fields.

```json
{ "type": "skip_question" }
```

---

#### `go_back`

Navigates to a previous question to re-answer it.

```json
{ "type": "go_back" }
```
```json
{ "type": "go_back", "to_index": 0 }
```

| Field | Required | Description |
|-------|----------|-------------|
| `to_index` | No | Zero-based question index to return to. Omit to go back one question. |

---

#### `repeat_question`

Requests the server to re-send the current question (replay TTS audio).

```json
{ "type": "repeat_question" }
```

---

#### `end_session`

Aborts the session without submitting.

```json
{ "type": "end_session" }
```

---

#### `ping`

Keep-alive heartbeat. The server heartbeats every 30 s; send `ping` every 20 s.

```json
{ "type": "ping" }
```

---

### 7.2 Server → Client messages

---

#### `session_started`

Confirms the session was created. The first `question` follows immediately.

```json
{
  "type": "session_started",
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "total_questions": 5,
  "title": "Customer Intake Form"
}
```

---

#### `question`

Delivers the next question to render. Always includes `voice_mode` and
`render_mode` (FEAT-236). Fields present depend on the question type.

```json
{
  "type": "question",
  "index": 1,
  "field_id": "department",
  "label": "Which department do you work in?",
  "required": true,
  "field_type": "select",
  "description": null,

  "voice_mode": "prompt_select",
  "render_mode": "select",
  "sensitive": false,

  "audio": "UklGRiQAAABXQVZFZm10IBAAAA…",
  "options": [
    { "value": "eng", "label": "Engineering" },
    { "value": "mkt", "label": "Marketing" },
    { "value": "ops", "label": "Operations" }
  ],
  "fallback_html": null
}
```

| Field | Always present | Description |
|-------|---------------|-------------|
| `type` | Yes | `"question"` |
| `index` | Yes | Zero-based question position |
| `field_id` | Yes | ID to use in answer messages |
| `label` | Yes | Question text (resolved to session locale) |
| `required` | Yes | `true` if mandatory |
| `field_type` | Yes | Raw `FieldType` value (`"text"`, `"select"`, `"file"`, …) |
| `voice_mode` | Yes | `"voice"`, `"prompt_select"`, or `"visual_fallback"` |
| `render_mode` | Yes | `"voice"`, `"select"`, or `"visual"` |
| `sensitive` | Yes | `true` for password fields — mute TTS read-back, mask transcript |
| `description` | Only if set | Help text |
| `audio` | Only if TTS succeeded | Base64-encoded WAV bytes |
| `options` | PROMPT\_SELECT only | `[{"value": "...", "label": "..."}]` |
| `fallback_html` | VISUAL\_FALLBACK only | Pre-rendered single-field HTML to inject |

**Audio format note**: SuperTonic outputs `audio/wav` (44.1 kHz, 16-bit PCM).
When Google TTS is active the format is `audio/ogg`. Always decode generically:

```javascript
const mimeType = question.field_type === "audio/wav" ? "audio/wav" : "audio/ogg";
// or just use a generic Blob and let the browser detect
const blob = new Blob([bytes]);
```

---

#### `transcription`

Sent before `answer_accepted` when the answer came from a binary audio frame.
Allows the UI to display the transcript as it was captured.

```json
{
  "type": "transcription",
  "field_id": "full_name",
  "text": "Jane Smith",
  "confidence": 0.97
}
```

> For `sensitive` fields the `text` is `"[hidden]"` regardless of the actual
> transcript. The real value is stored server-side.

---

#### `confirm_request`

Sent instead of `answer_accepted` when the STT `confidence` is below the
`stt_confirm_threshold`. The client must ask the user to confirm or repeat.

```json
{
  "type": "confirm_request",
  "field_id": "full_name",
  "transcript": "Jane Smith",
  "confidence": 0.35
}
```

The session is paused. No other answer is accepted until `confirm_answer` is sent.

> For `sensitive` fields `transcript` is `"[hidden]"`.

---

#### `answer_accepted`

Confirms a valid answer was stored. `source` indicates how it was received.

```json
{
  "type": "answer_accepted",
  "field_id": "full_name",
  "value": "Jane Smith",
  "source": "speech"
}
```

`source` values: `"text"` (keyboard), `"speech"` (STT), `"selection"` (UI).

> For `sensitive` fields the `value` field is **omitted** from the response.

---

#### `answer_rejected`

The answer failed validation (required field empty, invalid option, etc.).
The session does not advance — the same question is still active.

```json
{
  "type": "answer_rejected",
  "field_id": "department",
  "reason": "'invalid_dept' is not a valid option"
}
```

---

#### `form_complete`

All questions answered. The form has been submitted to storage (when configured).

```json
{
  "type": "form_complete",
  "submission_id": "sub_a1b2c3d4",
  "answers": {
    "full_name":    { "value": "Jane Smith",     "source": "speech" },
    "department":   { "value": "eng",            "source": "selection" },
    "satisfaction": { "value": "9",              "source": "selection" },
    "contract":     { "value": "https://…/doc",  "source": "text" }
  }
}
```

`submission_id` is `null` if no `submission_storage` was configured or if the
store write failed (a `WARNING` is logged; the session still completes normally).

---

#### `session_ended`

Confirmation of `end_session` (client abort).

```json
{ "type": "session_ended", "session_id": "550e8400-…" }
```

---

#### `error`

Protocol or internal error. Connection stays open unless `code` is
`AUTH_REQUIRED` (auto-close).

```json
{ "type": "error", "code": "FORM_NOT_FOUND", "message": "Form 'x' not found" }
```

---

#### `pong`

Response to `ping`.

```json
{ "type": "pong" }
```

---

## 8. Flow Diagrams by VoiceMode

### 8.1 VOICE — spoken or typed answer

```
Server                          Client
  │                               │
  │◄── question { voice_mode:"voice", audio }
  │    (play WAV audio)           │
  │                               │
  │    Option A — Type            │
  │◄── answer_text { field_id, value }
  │── answer_accepted ───────────►│
  │── question [next] ───────────►│
  │                               │
  │    Option B — Speak           │
  │◄── [binary audio frame]       │
  │                               │
  │  (confidence ≥ threshold)     │
  │── transcription ─────────────►│
  │── answer_accepted ───────────►│
  │── question [next] ───────────►│
  │                               │
  │  (confidence < threshold)     │
  │── transcription ─────────────►│
  │── confirm_request ───────────►│  ← see §8.4
```

### 8.2 PROMPT\_SELECT — narrated + UI selection

```
Server                          Client
  │                               │
  │── question {                  │
  │     voice_mode: "prompt_select",
  │     render_mode: "select",    │
  │     options: [...],           │
  │     audio: "..." }───────────►│
  │    (play WAV: "Which dept?    │
  │     Options: Eng, Mkt, Ops.") │
  │    (render radio buttons /    │
  │     select dropdown)          │
  │                               │
  │◄── answer_selection {         │
  │     field_id: "department",   │
  │     value: "eng" }            │
  │── answer_accepted ───────────►│
  │── question [next] ───────────►│
```

### 8.3 VISUAL\_FALLBACK — inline visual render

```
Server                          Client
  │                               │
  │── question {                  │
  │     voice_mode: "visual_fallback",
  │     render_mode: "visual",    │
  │     fallback_html: "<input type='file'…>",
  │     audio: "…" }─────────────►│
  │    (play WAV: "Please upload  │
  │     your signed contract.")   │
  │    (inject fallback_html in   │
  │     DOM; user interacts)      │
  │    (collect value from field) │
  │                               │
  │◄── answer_payload {           │
  │     field_id: "contract",     │
  │     value: "https://…/doc" }  │
  │── answer_accepted ───────────►│
  │── question [next] ───────────►│
```

### 8.4 STT confidence gate

```
Server                          Client
  │                               │
  │◄── [binary audio frame]       │
  │  (transcribe with Whisper)    │
  │  (confidence = 0.35 < 0.6)   │
  │                               │
  │── transcription {             │
  │     text: "Jane Smith",       │
  │     confidence: 0.35 } ──────►│
  │── confirm_request {           │
  │     transcript: "Jane Smith", │
  │     confidence: 0.35 } ──────►│
  │    (UI: "Did you say          │
  │     'Jane Smith'?")           │
  │                               │
  │  User confirms:               │
  │◄── confirm_answer { confirmed: true }
  │── answer_accepted ───────────►│
  │── question [next] ───────────►│
  │                               │
  │  User rejects:                │
  │◄── confirm_answer { confirmed: false }
  │── question [same] ───────────►│  (re-sent, nothing stored)
```

---

## 9. Frontend Integration Guide

### 9.1 Connecting and authenticating

```javascript
const token = await getAuthToken(); // your JWT refresh logic

const ws = new WebSocket(
  `wss://api.example.com/api/v1/forms/${formId}/audio/ws`,
  [token]  // pass JWT as WebSocket subprotocol (recommended)
);

ws.binaryType = "arraybuffer"; // needed to receive binary frames

ws.addEventListener("open", () => {
  console.log("WS connected");
});

ws.addEventListener("close", (event) => {
  console.log("WS closed", event.code, event.reason);
});

ws.addEventListener("error", () => {
  console.error("WS error — check network and JWT validity");
});
```

If the `Sec-WebSocket-Protocol` mechanism is blocked by a proxy, fall back
to the `auth` message:

```javascript
ws.addEventListener("open", () => {
  // Send auth as FIRST message
  ws.send(JSON.stringify({ type: "auth", token }));
  // Then start_session normally
});
```

---

### 9.2 Starting a session with TTS config

```javascript
ws.addEventListener("open", () => {
  ws.send(JSON.stringify({
    type: "start_session",
    form_id: formId,
    locale: "en",
    tts_backend: "supertonic",     // prefer sub-second ONNX TTS
    enumerate_options: true,        // read option labels for PROMPT_SELECT
    stt_confirm_threshold: 0.65,    // confirm if confidence < 65%
  }));
});
```

---

### 9.3 Rendering a question by VoiceMode

The central dispatch — branch on `render_mode` (or `voice_mode`) to show
the right input control:

```javascript
function handleQuestion(msg) {
  currentFieldId = msg.field_id;
  currentVoiceMode = msg.voice_mode;

  // Play TTS audio if present
  if (msg.audio) playWavAudio(msg.audio);

  // Show question text
  document.getElementById("question-label").textContent = msg.label;
  document.getElementById("question-label").dataset.required = msg.required;

  // Update progress
  updateProgress(msg.index + 1, totalQuestions);

  // Render the appropriate input control
  switch (msg.render_mode) {
    case "voice":
      renderVoiceInput(msg);
      break;
    case "select":
      renderSelectInput(msg);
      break;
    case "visual":
      renderVisualFallback(msg);
      break;
  }
}
```

---

### 9.4 VOICE questions — text and speech answers

```javascript
function renderVoiceInput(msg) {
  const container = document.getElementById("input-area");
  container.innerHTML = `
    <div class="voice-input ${msg.sensitive ? "sensitive" : ""}">
      <input
        id="text-answer"
        type="${msg.sensitive ? "password" : "text"}"
        placeholder="Type your answer or press the mic button"
        autocomplete="off"
      />
      <button id="mic-btn" class="mic-button" aria-label="Record answer">
        🎤
      </button>
    </div>
  `;

  // Text answer
  document.getElementById("text-answer").addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      sendTextAnswer(currentFieldId, e.target.value.trim());
      e.target.value = "";
    }
  });

  // Speech answer
  document.getElementById("mic-btn").addEventListener("mousedown", startRecording);
  document.getElementById("mic-btn").addEventListener("mouseup", stopRecording);
  document.getElementById("mic-btn").addEventListener("touchstart", startRecording);
  document.getElementById("mic-btn").addEventListener("touchend", stopRecording);
}

function sendTextAnswer(fieldId, value) {
  ws.send(JSON.stringify({ type: "answer_text", field_id: fieldId, value }));
}
```

---

### 9.5 PROMPT\_SELECT questions — UI selection

```javascript
function renderSelectInput(msg) {
  const container = document.getElementById("input-area");
  const isMulti = msg.field_type === "multi_select";

  if (msg.options && msg.options.length > 0) {
    // Render radio or checkbox buttons
    const controls = msg.options.map(opt => `
      <label class="option-label">
        <input
          type="${isMulti ? "checkbox" : "radio"}"
          name="voice-option"
          value="${escapeHtml(opt.value)}"
        />
        <span>${escapeHtml(opt.label)}</span>
      </label>
    `).join("");

    container.innerHTML = `
      <div class="select-options" role="group" aria-label="${msg.label}">
        ${controls}
      </div>
      <button id="confirm-selection" class="btn-primary">Confirm</button>
    `;
  } else {
    // NPS / rating — numeric input
    container.innerHTML = `
      <input id="nps-input" type="number"
             min="0" max="10" placeholder="0–10" />
      <button id="confirm-selection" class="btn-primary">Confirm</button>
    `;
  }

  document.getElementById("confirm-selection").addEventListener("click", () => {
    if (isMulti) {
      const selected = [...document.querySelectorAll('[name="voice-option"]:checked')]
        .map(el => el.value);
      sendSelection(msg.field_id, null, selected);
    } else {
      const radio = document.querySelector('[name="voice-option"]:checked');
      const nps = document.getElementById("nps-input");
      const value = radio ? radio.value : (nps ? nps.value : "");
      sendSelection(msg.field_id, value, null);
    }
  });
}

function sendSelection(fieldId, value, values) {
  const msg = { type: "answer_selection", field_id: fieldId };
  if (values !== null) msg.values = values;
  else msg.value = value;
  ws.send(JSON.stringify(msg));
}
```

---

### 9.6 VISUAL\_FALLBACK questions — inline render + payload

The server sends a pre-rendered `fallback_html` fragment for complex
field types (`file`, `image`, `location`, `signature`, etc.). The client
injects it into the DOM, lets the user interact, then collects and sends
the resulting value via `answer_payload`.

```javascript
function renderVisualFallback(msg) {
  const container = document.getElementById("input-area");

  // Inject the server-rendered HTML fragment
  container.innerHTML = `
    <div class="visual-fallback-container">
      <p class="fallback-hint">
        This question requires a visual response.
        Complete the field below then press Continue.
      </p>
      <div id="fallback-field">
        ${msg.fallback_html}
      </div>
      <button id="fallback-submit" class="btn-primary">Continue</button>
    </div>
  `;

  // For file inputs: listen for change and collect a URL/blob ref
  const fileInput = container.querySelector("input[type='file']");
  if (fileInput) {
    fileInput.addEventListener("change", (e) => {
      const file = e.target.files[0];
      if (file) {
        // Option 1: upload to your storage, then answer_payload with URL
        uploadFile(file).then((url) => {
          document.getElementById("fallback-submit").dataset.value = url;
        });
      }
    });
  }

  document.getElementById("fallback-submit").addEventListener("click", () => {
    const value = collectFallbackValue(msg.field_id, container);
    if (value !== null) {
      ws.send(JSON.stringify({
        type: "answer_payload",
        field_id: msg.field_id,
        value: value,
      }));
    }
  });
}

function collectFallbackValue(fieldId, container) {
  // Try named input/select first
  const namedInput = container.querySelector(`[name="${fieldId}"]`);
  if (namedInput) return namedInput.value || null;

  // Fall back to any input
  const anyInput = container.querySelector("input, select, textarea");
  return anyInput ? anyInput.value || null : null;
}
```

---

### 9.7 STT confirm flow

When the server is uncertain about a transcription, it pauses the session
and sends `confirm_request`. Show the transcript to the user and ask them
to confirm or repeat.

```javascript
function handleConfirmRequest(msg) {
  const container = document.getElementById("input-area");
  container.innerHTML = `
    <div class="confirm-transcript">
      <p class="confirm-label">I heard:</p>
      <blockquote class="transcript-text">
        "${escapeHtml(msg.transcript)}"
        <small>(confidence: ${Math.round(msg.confidence * 100)}%)</small>
      </blockquote>
      <div class="confirm-buttons">
        <button id="confirm-yes" class="btn-primary">Yes, that's correct</button>
        <button id="confirm-no" class="btn-secondary">No, let me try again</button>
      </div>
    </div>
  `;

  document.getElementById("confirm-yes").addEventListener("click", () => {
    ws.send(JSON.stringify({
      type: "confirm_answer",
      field_id: msg.field_id,
      confirmed: true,
    }));
  });

  document.getElementById("confirm-no").addEventListener("click", () => {
    ws.send(JSON.stringify({
      type: "confirm_answer",
      field_id: msg.field_id,
      confirmed: false,
    }));
    // Server will re-send the same question — no need to do anything else
  });
}
```

---

### 9.8 Navigation helpers

```javascript
// Skip current optional question
function skipQuestion() {
  ws.send(JSON.stringify({ type: "skip_question" }));
}

// Go back to previous question
function goBack() {
  ws.send(JSON.stringify({ type: "go_back" }));
}

// Jump to specific question by index
function goToQuestion(index) {
  ws.send(JSON.stringify({ type: "go_back", to_index: index }));
}

// Repeat current question's TTS audio
function repeatQuestion() {
  ws.send(JSON.stringify({ type: "repeat_question" }));
}

// Keep-alive (server heartbeat is 30 s; send ping every 20 s)
const pingInterval = setInterval(() => {
  if (ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: "ping" }));
  }
}, 20_000);
```

---

### 9.9 Playing TTS audio (WAV)

SuperTonic outputs `audio/wav`. Decode the base64 payload and play it:

```javascript
function playWavAudio(base64Audio, mimeType = "audio/wav") {
  // Decode base64 → ArrayBuffer
  const binaryStr = atob(base64Audio);
  const bytes = new Uint8Array(binaryStr.length);
  for (let i = 0; i < binaryStr.length; i++) {
    bytes[i] = binaryStr.charCodeAt(i);
  }

  const blob = new Blob([bytes], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const audio = new Audio(url);

  audio.onended = () => URL.revokeObjectURL(url);
  audio.onerror = () => {
    URL.revokeObjectURL(url);
    console.warn("Audio playback failed — continuing in text-only mode");
  };

  // Return the promise so callers can await playback completion if needed
  return audio.play().catch((err) => {
    // Autoplay blocked: show a "Tap to hear question" button
    console.warn("Autoplay blocked:", err);
    showPlayButton(url);
  });
}
```

---

### 9.10 Full vanilla JS reference client

A complete, framework-agnostic reference implementation that handles all
VoiceModes, the confirm flow, and graceful TTS degradation.

```javascript
/**
 * AudioFormClientV2 — FEAT-236 reference implementation.
 *
 * Supports VOICE, PROMPT_SELECT, and VISUAL_FALLBACK questions;
 * STT confirm flow; SuperTonic WAV audio; and session navigation.
 *
 * Usage:
 *   const client = new AudioFormClientV2("my-form", jwtToken, {
 *     container: document.getElementById("form-area"),
 *     onComplete: (submissionId, answers) => { ... },
 *     onError: (code, message) => { ... },
 *   });
 *   client.connect("en");
 */
class AudioFormClientV2 {
  constructor(formId, token, options = {}) {
    this.formId = formId;
    this.token = token;
    this.container = options.container || document.body;
    this.onComplete = options.onComplete || (() => {});
    this.onError = options.onError || ((code, msg) => console.error(code, msg));
    this.locale = "en";

    this._ws = null;
    this._sessionId = null;
    this._totalQuestions = 0;
    this._currentIndex = 0;
    this._currentFieldId = null;
    this._currentVoiceMode = null;
    this._pingTimer = null;
    this._mediaRecorder = null;
    this._audioChunks = [];
    this._isRecording = false;
  }

  // ── Public API ─────────────────────────────────────────────────────────────

  connect(locale = "en") {
    this.locale = locale;
    const url = `/api/v1/forms/${this.formId}/audio/ws`;
    this._ws = new WebSocket(url, [this.token]);
    this._ws.binaryType = "arraybuffer";

    this._ws.onopen = () => {
      this._send({
        type: "start_session",
        form_id: this.formId,
        locale: this.locale,
        tts_backend: "supertonic",
        enumerate_options: true,
        stt_confirm_threshold: 0.65,
      });
      this._pingTimer = setInterval(() => this._send({ type: "ping" }), 20_000);
    };

    this._ws.onmessage = (ev) => {
      if (typeof ev.data === "string") this._dispatch(JSON.parse(ev.data));
      // binary frames from server are not expected; ignore
    };

    this._ws.onclose = () => {
      clearInterval(this._pingTimer);
      this._render("closed", {});
    };

    this._ws.onerror = () => {
      this.onError("WS_ERROR", "WebSocket connection failed");
    };
  }

  disconnect() {
    this._ws?.close(1000, "Client disconnect");
  }

  // ── Message dispatcher ─────────────────────────────────────────────────────

  _dispatch(msg) {
    switch (msg.type) {
      case "session_started":
        this._sessionId = msg.session_id;
        this._totalQuestions = msg.total_questions;
        this._renderHeader(msg.title);
        break;

      case "question":
        this._currentFieldId = msg.field_id;
        this._currentVoiceMode = msg.voice_mode;
        this._currentIndex = msg.index;
        this._renderProgress(msg.index + 1);
        this._renderQuestion(msg);
        if (msg.audio) playWavAudio(msg.audio);
        break;

      case "transcription":
        this._showTranscription(msg.text, msg.confidence);
        break;

      case "confirm_request":
        this._renderConfirm(msg);
        break;

      case "answer_accepted":
        this._markAccepted(msg.field_id, msg.value, msg.source);
        break;

      case "answer_rejected":
        this._showError(msg.reason);
        break;

      case "form_complete":
        clearInterval(this._pingTimer);
        this.onComplete(msg.submission_id, msg.answers);
        this._render("complete", msg);
        break;

      case "error":
        this.onError(msg.code, msg.message);
        break;

      case "pong":
        break; // heartbeat — ignore
    }
  }

  // ── Question rendering ─────────────────────────────────────────────────────

  _renderQuestion(msg) {
    this._renderLabel(msg.label, msg.required, msg.description);

    switch (msg.render_mode) {
      case "voice":
        this._renderVoiceInput(msg);
        break;
      case "select":
        this._renderSelectInput(msg);
        break;
      case "visual":
        this._renderVisualFallback(msg);
        break;
    }
  }

  _renderVoiceInput(msg) {
    const inputType = msg.sensitive ? "password" : "text";
    const inputArea = this._el("input-area");
    inputArea.innerHTML = `
      <div class="voice-input-row">
        <input id="voice-text-input" type="${inputType}"
               class="voice-text-input"
               placeholder="Type your answer or tap the mic"
               autocomplete="off" />
        <button id="voice-mic-btn" class="mic-btn" aria-label="Record">🎤</button>
      </div>
      <button id="voice-submit-btn" class="btn-primary">Submit</button>
      <button id="voice-skip-btn" class="btn-secondary"
              ${msg.required ? "disabled" : ""}>Skip</button>
    `;

    this._el("voice-submit-btn").onclick = () => {
      const val = this._el("voice-text-input").value.trim();
      if (val) this._send({ type: "answer_text", field_id: msg.field_id, value: val });
    };

    this._el("voice-text-input").onkeydown = (e) => {
      if (e.key === "Enter") this._el("voice-submit-btn").click();
    };

    this._el("voice-skip-btn").onclick = () => this._send({ type: "skip_question" });

    // Mic recording
    const micBtn = this._el("voice-mic-btn");
    micBtn.onmousedown = micBtn.ontouchstart = (e) => {
      e.preventDefault();
      this._startRecording();
    };
    micBtn.onmouseup = micBtn.ontouchend = (e) => {
      e.preventDefault();
      this._stopRecording();
    };
  }

  _renderSelectInput(msg) {
    const isMulti = msg.field_type === "multi_select";
    const inputArea = this._el("input-area");

    let controls = "";
    if (msg.options?.length) {
      controls = msg.options.map(opt => `
        <label class="option-label">
          <input type="${isMulti ? "checkbox" : "radio"}"
                 name="audio-option" value="${_esc(opt.value)}" />
          <span>${_esc(opt.label)}</span>
        </label>
      `).join("");
    } else {
      controls = `<input id="nps-value" type="number" min="0" max="10"
                         class="nps-input" placeholder="Enter value" />`;
    }

    inputArea.innerHTML = `
      <div class="option-group" role="group">${controls}</div>
      <button id="select-confirm-btn" class="btn-primary">Confirm Selection</button>
    `;

    this._el("select-confirm-btn").onclick = () => {
      if (isMulti) {
        const vals = [...inputArea.querySelectorAll('[name="audio-option"]:checked')]
          .map(el => el.value);
        this._send({ type: "answer_selection", field_id: msg.field_id, values: vals });
      } else if (msg.options?.length) {
        const radio = inputArea.querySelector('[name="audio-option"]:checked');
        if (radio) this._send({ type: "answer_selection", field_id: msg.field_id, value: radio.value });
      } else {
        const val = this._el("nps-value")?.value;
        if (val !== undefined) this._send({ type: "answer_selection", field_id: msg.field_id, value: val });
      }
    };
  }

  _renderVisualFallback(msg) {
    const inputArea = this._el("input-area");
    inputArea.innerHTML = `
      <p class="fallback-hint">Complete the field below, then press Continue.</p>
      <div id="fallback-slot">${msg.fallback_html || ""}</div>
      <button id="fallback-continue-btn" class="btn-primary">Continue</button>
    `;

    this._el("fallback-continue-btn").onclick = () => {
      const slot = this._el("fallback-slot");
      const named = slot.querySelector(`[name="${msg.field_id}"]`);
      const any = slot.querySelector("input, select, textarea");
      const value = (named || any)?.value ?? "";
      this._send({ type: "answer_payload", field_id: msg.field_id, value });
    };
  }

  _renderConfirm(msg) {
    const inputArea = this._el("input-area");
    inputArea.innerHTML = `
      <div class="confirm-box">
        <p>I heard: <strong>"${_esc(msg.transcript)}"</strong>
           <small>(${Math.round(msg.confidence * 100)}% confidence)</small></p>
        <button id="confirm-yes-btn" class="btn-primary">Yes, correct</button>
        <button id="confirm-no-btn"  class="btn-secondary">No, try again</button>
      </div>
    `;
    this._el("confirm-yes-btn").onclick = () =>
      this._send({ type: "confirm_answer", field_id: msg.field_id, confirmed: true });
    this._el("confirm-no-btn").onclick = () =>
      this._send({ type: "confirm_answer", field_id: msg.field_id, confirmed: false });
  }

  // ── Recording ─────────────────────────────────────────────────────────────

  async _startRecording() {
    if (this._isRecording) return;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mimeType = MediaRecorder.isTypeSupported("audio/webm")
        ? "audio/webm"
        : MediaRecorder.isTypeSupported("audio/mp4") ? "audio/mp4" : "";
      this._mediaRecorder = new MediaRecorder(stream, mimeType ? { mimeType } : {});
      this._audioChunks = [];
      this._isRecording = true;

      this._mediaRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) this._audioChunks.push(e.data);
      };
      this._mediaRecorder.onstop = () => {
        const blob = new Blob(this._audioChunks, mimeType ? { type: mimeType } : {});
        this._ws.send(blob);
        stream.getTracks().forEach(t => t.stop());
        this._isRecording = false;
        this._el("voice-mic-btn")?.classList.remove("recording");
      };

      this._mediaRecorder.start();
      this._el("voice-mic-btn")?.classList.add("recording");
    } catch (err) {
      console.warn("Microphone access denied:", err);
    }
  }

  _stopRecording() {
    if (this._mediaRecorder?.state !== "inactive") this._mediaRecorder?.stop();
  }

  // ── UI helpers ────────────────────────────────────────────────────────────

  _renderHeader(title) {
    let h = this.container.querySelector(".audio-form-header");
    if (!h) {
      h = Object.assign(document.createElement("div"), { className: "audio-form-header" });
      this.container.prepend(h);
    }
    h.textContent = title;
  }

  _renderProgress(current) {
    let p = this.container.querySelector(".audio-form-progress");
    if (!p) {
      p = Object.assign(document.createElement("div"), { className: "audio-form-progress" });
      this.container.querySelector(".audio-form-header")?.after(p);
    }
    p.textContent = `Question ${current} of ${this._totalQuestions}`;
  }

  _renderLabel(label, required, description) {
    let q = this._el("question-display");
    if (!q) {
      q = Object.assign(document.createElement("div"), { id: "question-display" });
      this.container.querySelector(".audio-form-progress")?.after(q);
    }
    q.innerHTML = `
      <p class="question-label ${required ? "required" : ""}">
        ${_esc(label)}${required ? " <span aria-hidden='true'>*</span>" : ""}
      </p>
      ${description ? `<p class="question-description">${_esc(description)}</p>` : ""}
    `;
  }

  _showTranscription(text, confidence) {
    let div = this._el("transcription-preview");
    if (!div) {
      div = Object.assign(document.createElement("div"), { id: "transcription-preview" });
      this._el("input-area")?.before(div);
    }
    div.innerHTML = `
      <span class="transcription-text">Heard: "${_esc(text)}"</span>
      <span class="transcription-confidence">${Math.round(confidence * 100)}%</span>
    `;
  }

  _markAccepted(fieldId, value, source) {
    const prev = this._el("transcription-preview");
    if (prev) prev.remove();
    // Optional: add checkmark or "answered" indicator
  }

  _showError(reason) {
    let div = this._el("answer-error");
    if (!div) {
      div = Object.assign(document.createElement("div"), {
        id: "answer-error", className: "answer-error"
      });
      this._el("input-area")?.after(div);
    }
    div.textContent = reason;
  }

  _render(state, data) {
    if (state === "complete") {
      this.container.innerHTML = `
        <div class="form-complete">
          <h2>Form Complete!</h2>
          <p>Submission ID: ${_esc(data.submission_id ?? "N/A")}</p>
        </div>
      `;
    } else if (state === "closed") {
      this.container.querySelector(".audio-form-footer")?.remove();
    }
  }

  _el(id) { return this.container.querySelector(`#${id}`) || document.getElementById(id); }
  _send(msg) { if (this._ws?.readyState === WebSocket.OPEN) this._ws.send(JSON.stringify(msg)); }
}

// ── Utilities ────────────────────────────────────────────────────────────────

function _esc(str) {
  return String(str ?? "")
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#039;");
}

function playWavAudio(base64, mimeType = "audio/wav") {
  const bytes = Uint8Array.from(atob(base64), c => c.charCodeAt(0));
  const blob = new Blob([bytes], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const audio = new Audio(url);
  audio.onended = () => URL.revokeObjectURL(url);
  return audio.play().catch(() => URL.revokeObjectURL(url));
}

// ── Bootstrap ────────────────────────────────────────────────────────────────

const client = new AudioFormClientV2("customer-intake", localStorage.getItem("jwt"), {
  container: document.getElementById("audio-form-root"),
  onComplete: (submissionId, answers) => {
    console.log("Submitted:", submissionId, answers);
    showThankYouPage();
  },
  onError: (code, message) => {
    if (code === "AUTH_REQUIRED") window.location.href = "/login";
    else showToast(`Error: ${message}`);
  },
});

client.connect("en");
```

---

### 9.11 React / TypeScript component

A production-ready React hook + component that wraps the WebSocket protocol.

```typescript
// hooks/useAudioForm.ts

import { useCallback, useEffect, useRef, useState } from "react";

export type VoiceMode = "voice" | "prompt_select" | "visual_fallback";
export type RenderMode = "voice" | "select" | "visual";
export type AnswerSource = "text" | "speech" | "selection";

export interface QuestionMessage {
  type: "question";
  index: number;
  field_id: string;
  label: string;
  required: boolean;
  field_type: string;
  voice_mode: VoiceMode;
  render_mode: RenderMode;
  sensitive: boolean;
  description?: string;
  audio?: string;           // base64 WAV
  options?: Array<{ value: string; label: string }>;
  fallback_html?: string;
}

export interface ConfirmRequest {
  type: "confirm_request";
  field_id: string;
  transcript: string;
  confidence: number;
}

export interface FormComplete {
  type: "form_complete";
  submission_id: string | null;
  answers: Record<string, { value: string; source: AnswerSource }>;
}

export type SessionState =
  | "idle"
  | "connecting"
  | "started"
  | "question"
  | "confirming"
  | "complete"
  | "error";

export interface UseAudioFormOptions {
  formId: string;
  token: string;
  locale?: string;
  ttsBackend?: "supertonic" | "google";
  sttConfirmThreshold?: number;
  enumerateOptions?: boolean;
  onComplete?: (submissionId: string | null, answers: FormComplete["answers"]) => void;
}

export function useAudioForm({
  formId,
  token,
  locale = "en",
  ttsBackend = "supertonic",
  sttConfirmThreshold = 0.65,
  enumerateOptions = true,
  onComplete,
}: UseAudioFormOptions) {
  const ws = useRef<WebSocket | null>(null);
  const mediaRecorder = useRef<MediaRecorder | null>(null);
  const audioChunks = useRef<Blob[]>([]);

  const [sessionState, setSessionState] = useState<SessionState>("idle");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [totalQuestions, setTotalQuestions] = useState(0);
  const [currentQuestion, setCurrentQuestion] = useState<QuestionMessage | null>(null);
  const [confirmRequest, setConfirmRequest] = useState<ConfirmRequest | null>(null);
  const [transcription, setTranscription] = useState<{ text: string; confidence: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isRecording, setIsRecording] = useState(false);

  const send = useCallback((msg: object) => {
    if (ws.current?.readyState === WebSocket.OPEN) {
      ws.current.send(JSON.stringify(msg));
    }
  }, []);

  useEffect(() => {
    setSessionState("connecting");
    const socket = new WebSocket(
      `/api/v1/forms/${formId}/audio/ws`,
      [token]
    );
    socket.binaryType = "arraybuffer";
    ws.current = socket;

    socket.onopen = () => {
      setSessionState("started");
      send({
        type: "start_session",
        form_id: formId,
        locale,
        tts_backend: ttsBackend,
        enumerate_options: enumerateOptions,
        stt_confirm_threshold: sttConfirmThreshold,
      });
    };

    socket.onmessage = (ev) => {
      if (typeof ev.data !== "string") return;
      const msg = JSON.parse(ev.data) as { type: string } & Record<string, unknown>;

      switch (msg.type) {
        case "session_started":
          setSessionId(msg.session_id as string);
          setTotalQuestions(msg.total_questions as number);
          break;

        case "question":
          setCurrentQuestion(msg as unknown as QuestionMessage);
          setConfirmRequest(null);
          setTranscription(null);
          setError(null);
          setSessionState("question");
          if ((msg as QuestionMessage).audio) {
            playWavAudio((msg as QuestionMessage).audio!);
          }
          break;

        case "transcription":
          setTranscription({ text: msg.text as string, confidence: msg.confidence as number });
          break;

        case "confirm_request":
          setConfirmRequest(msg as unknown as ConfirmRequest);
          setSessionState("confirming");
          break;

        case "answer_accepted":
          setTranscription(null);
          break;

        case "answer_rejected":
          setError(msg.reason as string);
          break;

        case "form_complete": {
          const complete = msg as unknown as FormComplete;
          setSessionState("complete");
          onComplete?.(complete.submission_id, complete.answers);
          break;
        }

        case "error":
          setError(msg.message as string);
          if (msg.code === "AUTH_REQUIRED") setSessionState("error");
          break;
      }
    };

    socket.onclose = () => setSessionState("idle");
    socket.onerror = () => setSessionState("error");

    const pingTimer = setInterval(() => send({ type: "ping" }), 20_000);
    return () => {
      clearInterval(pingTimer);
      socket.close(1000, "Component unmounted");
    };
  }, [formId, token]); // eslint-disable-line react-hooks/exhaustive-deps

  // Answer methods
  const answerText = useCallback((fieldId: string, value: string) => {
    send({ type: "answer_text", field_id: fieldId, value });
  }, [send]);

  const answerSelection = useCallback((fieldId: string, value: string | null, values?: string[]) => {
    const msg: Record<string, unknown> = { type: "answer_selection", field_id: fieldId };
    if (values !== undefined) msg.values = values;
    else msg.value = value;
    send(msg);
  }, [send]);

  const answerPayload = useCallback((fieldId: string, value: string) => {
    send({ type: "answer_payload", field_id: fieldId, value });
  }, [send]);

  const confirmAnswer = useCallback((fieldId: string, confirmed: boolean) => {
    send({ type: "confirm_answer", field_id: fieldId, confirmed });
    setSessionState("question");
  }, [send]);

  const skipQuestion = useCallback(() => send({ type: "skip_question" }), [send]);
  const goBack = useCallback((toIndex?: number) => {
    const msg: Record<string, unknown> = { type: "go_back" };
    if (toIndex !== undefined) msg.to_index = toIndex;
    send(msg);
  }, [send]);
  const repeatQuestion = useCallback(() => send({ type: "repeat_question" }), [send]);

  const startRecording = useCallback(async () => {
    if (isRecording) return;
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const mimeType = MediaRecorder.isTypeSupported("audio/webm") ? "audio/webm"
      : MediaRecorder.isTypeSupported("audio/mp4") ? "audio/mp4" : "";
    const rec = new MediaRecorder(stream, mimeType ? { mimeType } : {});
    audioChunks.current = [];
    setIsRecording(true);
    rec.ondataavailable = (e) => { if (e.data.size > 0) audioChunks.current.push(e.data); };
    rec.onstop = () => {
      const blob = new Blob(audioChunks.current, mimeType ? { type: mimeType } : {});
      ws.current?.send(blob);
      stream.getTracks().forEach(t => t.stop());
      setIsRecording(false);
    };
    rec.start();
    mediaRecorder.current = rec;
  }, [isRecording]);

  const stopRecording = useCallback(() => {
    if (mediaRecorder.current?.state !== "inactive") mediaRecorder.current?.stop();
  }, []);

  return {
    sessionState, sessionId, totalQuestions, currentQuestion,
    confirmRequest, transcription, error, isRecording,
    answerText, answerSelection, answerPayload, confirmAnswer,
    skipQuestion, goBack, repeatQuestion, startRecording, stopRecording,
  };
}

function playWavAudio(base64: string, mimeType = "audio/wav"): void {
  const bytes = Uint8Array.from(atob(base64), c => c.charCodeAt(0));
  const blob = new Blob([bytes], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const audio = new Audio(url);
  audio.onended = () => URL.revokeObjectURL(url);
  audio.play().catch(() => URL.revokeObjectURL(url));
}
```

```tsx
// components/AudioFormPlayer.tsx

import React from "react";
import { useAudioForm, QuestionMessage, ConfirmRequest } from "../hooks/useAudioForm";

interface Props {
  formId: string;
  token: string;
  onComplete: (submissionId: string | null) => void;
}

export function AudioFormPlayer({ formId, token, onComplete }: Props) {
  const {
    sessionState, totalQuestions, currentQuestion,
    confirmRequest, transcription, error, isRecording,
    answerText, answerSelection, answerPayload, confirmAnswer,
    skipQuestion, goBack, repeatQuestion, startRecording, stopRecording,
  } = useAudioForm({
    formId, token,
    onComplete: (id) => onComplete(id),
  });

  if (sessionState === "idle" || sessionState === "connecting") {
    return <div className="audio-form-loading">Connecting…</div>;
  }

  if (sessionState === "complete") {
    return <div className="audio-form-complete">Form submitted successfully!</div>;
  }

  if (sessionState === "error") {
    return <div className="audio-form-error">Connection error. Please log in again.</div>;
  }

  return (
    <div className="audio-form-container">
      {currentQuestion && (
        <>
          <div className="audio-form-progress">
            Question {currentQuestion.index + 1} of {totalQuestions}
          </div>

          <QuestionLabel question={currentQuestion} />

          {transcription && (
            <div className="transcription-preview">
              Heard: "{transcription.text}" ({Math.round(transcription.confidence * 100)}%)
            </div>
          )}

          {error && <div className="answer-error">{error}</div>}

          {sessionState === "confirming" && confirmRequest ? (
            <ConfirmPanel
              confirmRequest={confirmRequest}
              onConfirm={(confirmed) => confirmAnswer(confirmRequest.field_id, confirmed)}
            />
          ) : (
            <QuestionInput
              question={currentQuestion}
              isRecording={isRecording}
              onTextAnswer={answerText}
              onSelection={answerSelection}
              onPayload={answerPayload}
              onStartRecording={startRecording}
              onStopRecording={stopRecording}
              onSkip={skipQuestion}
            />
          )}

          <div className="audio-form-nav">
            <button onClick={() => goBack()} className="btn-nav">← Back</button>
            <button onClick={repeatQuestion} className="btn-nav">↺ Repeat</button>
          </div>
        </>
      )}
    </div>
  );
}

function QuestionLabel({ question }: { question: QuestionMessage }) {
  return (
    <div className="question-display">
      <p className={`question-label ${question.required ? "required" : ""}`}>
        {question.label}
        {question.required && <span aria-hidden="true"> *</span>}
      </p>
      {question.description && (
        <p className="question-description">{question.description}</p>
      )}
    </div>
  );
}

function ConfirmPanel({
  confirmRequest,
  onConfirm,
}: {
  confirmRequest: ConfirmRequest;
  onConfirm: (confirmed: boolean) => void;
}) {
  return (
    <div className="confirm-box">
      <p>
        I heard: <strong>"{confirmRequest.transcript}"</strong>{" "}
        <small>({Math.round(confirmRequest.confidence * 100)}% confidence)</small>
      </p>
      <button onClick={() => onConfirm(true)} className="btn-primary">Yes, correct</button>
      <button onClick={() => onConfirm(false)} className="btn-secondary">No, try again</button>
    </div>
  );
}

function QuestionInput({
  question,
  isRecording,
  onTextAnswer,
  onSelection,
  onPayload,
  onStartRecording,
  onStopRecording,
  onSkip,
}: {
  question: QuestionMessage;
  isRecording: boolean;
  onTextAnswer: (fieldId: string, value: string) => void;
  onSelection: (fieldId: string, value: string | null, values?: string[]) => void;
  onPayload: (fieldId: string, value: string) => void;
  onStartRecording: () => void;
  onStopRecording: () => void;
  onSkip: () => void;
}) {
  const [textValue, setTextValue] = React.useState("");
  const [selectedValue, setSelectedValue] = React.useState<string>("");
  const [selectedValues, setSelectedValues] = React.useState<string[]>([]);
  const [payloadValue, setPayloadValue] = React.useState("");

  if (question.render_mode === "select") {
    const isMulti = question.field_type === "multi_select";
    return (
      <div className="select-input">
        {question.options?.map(opt => (
          <label key={opt.value} className="option-label">
            <input
              type={isMulti ? "checkbox" : "radio"}
              name="audio-option"
              value={opt.value}
              checked={isMulti ? selectedValues.includes(opt.value) : selectedValue === opt.value}
              onChange={() => {
                if (isMulti) {
                  setSelectedValues(prev =>
                    prev.includes(opt.value)
                      ? prev.filter(v => v !== opt.value)
                      : [...prev, opt.value]
                  );
                } else {
                  setSelectedValue(opt.value);
                }
              }}
            />
            {opt.label}
          </label>
        ))}
        <button
          className="btn-primary"
          onClick={() => {
            if (isMulti) onSelection(question.field_id, null, selectedValues);
            else onSelection(question.field_id, selectedValue);
          }}
        >
          Confirm
        </button>
      </div>
    );
  }

  if (question.render_mode === "visual") {
    return (
      <div className="visual-fallback-input">
        {question.fallback_html && (
          <div
            className="fallback-html-slot"
            dangerouslySetInnerHTML={{ __html: question.fallback_html }}
          />
        )}
        <input
          type="text"
          value={payloadValue}
          onChange={(e) => setPayloadValue(e.target.value)}
          placeholder="Value from the field above…"
        />
        <button
          className="btn-primary"
          onClick={() => onPayload(question.field_id, payloadValue)}
        >
          Continue
        </button>
      </div>
    );
  }

  // Default: VOICE
  return (
    <div className="voice-input">
      <input
        type={question.sensitive ? "password" : "text"}
        value={textValue}
        onChange={(e) => setTextValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && textValue.trim()) {
            onTextAnswer(question.field_id, textValue.trim());
            setTextValue("");
          }
        }}
        placeholder="Type your answer or use the mic"
        autoComplete="off"
      />
      <button
        className={`mic-btn ${isRecording ? "recording" : ""}`}
        onMouseDown={onStartRecording}
        onMouseUp={onStopRecording}
        onTouchStart={onStartRecording}
        onTouchEnd={onStopRecording}
        aria-label={isRecording ? "Stop recording" : "Start recording"}
      >
        {isRecording ? "⏹" : "🎤"}
      </button>
      <button
        className="btn-primary"
        onClick={() => { onTextAnswer(question.field_id, textValue.trim()); setTextValue(""); }}
      >
        Submit
      </button>
      {!question.required && (
        <button className="btn-secondary" onClick={onSkip}>Skip</button>
      )}
    </div>
  );
}
```

---

## 10. Error Codes

| Code | Cause | Closes WS? | Recovery |
|------|-------|-----------|----------|
| `AUTH_REQUIRED` | JWT absent, expired, or invalid | **Yes** | Redirect to login, refresh token |
| `FORM_NOT_FOUND` | `form_id` not in the registry | No | Check form ID |
| `SESSION_NOT_STARTED` | Message sent before `start_session` | No | Send `start_session` first |
| `SESSION_COMPLETE` | Answer sent after `form_complete` | No | Close connection |
| `TRANSCRIBER_UNAVAILABLE` | Binary frame received, but no STT configured | No | Switch to `answer_text` |
| `TRANSCRIPTION_ERROR` | Internal STT error | No | Retry with binary frame or `answer_text` |
| `INVALID_JSON` | Text frame is not valid JSON | No | Fix message serialization |
| `UNKNOWN_MESSAGE_TYPE` | Unknown `type` field | No | Check message type spelling |
| `INVALID_INDEX` | `to_index` out of range in `go_back` | No | Use a valid index (0–total-1) |
| `NO_PENDING_ANSWER` | `confirm_answer` sent without prior `confirm_request` | No | Don't send `confirm_answer` unless `confirm_request` was received |
| `FIELD_MISMATCH` | `confirm_answer.field_id` ≠ pending field | No | Use the `field_id` from `confirm_request` |
| `WRONG_FIELD` | Answer `field_id` ≠ current question | No | Always use `field_id` from the last `question` message |
| `INTERNAL_ERROR` | Unhandled server exception | No | Log and retry if transient |

---

## 11. Security Considerations

### Authentication

- **Always** configure `token_validator` in production. Without it, all
  connections are accepted as `anonymous` and a `WARNING` is emitted.
- Pass the JWT as a `Sec-WebSocket-Protocol` subprotocol — never in the URL
  (it would appear in server logs and browser history).
- Rotate the JWT signing key periodically and ensure it differs from other
  services.

### Sensitive fields (passwords)

- Password fields (`FieldType.PASSWORD`) have `sensitive: true` in the
  `question` message. The server never sends TTS audio for them.
- Transcriptions of sensitive fields return `"[hidden]"` to the client;
  the real transcript is stored server-side only.
- The `answer_accepted` response for sensitive fields omits the `value` field.

### Frame size

- Default max binary frame: **10 MB** (configurable via `max_msg_size` in
  `AudioFormWSHandler.__init__`).
- Validate on the client side that audio blobs stay under the limit before
  sending.

### Temporary files

- Audio frames are written to a temp file (`/tmp/audio_form_*.ogg`) during
  STT transcription.
- The file is unconditionally deleted in a `finally` block, even if
  transcription fails.
- Ensure the temp directory (`TMPDIR`) has adequate space and is not
  world-readable.

### CORS / Origin

- The WebSocket endpoint does not perform `Origin` validation itself.
  Configure the `aiohttp` CORS middleware to allow only trusted origins.

### Graceful TTS degradation

- If SuperTonic weights are missing or the ONNX runtime fails to load, the
  session falls back to Google TTS with no interruption.
- If both backends are unavailable, questions are delivered text-only (no
  `audio` field). The client must handle absent `audio` gracefully — never
  assume it is present.

---

## 12. FAQ

**What happens if I send `answer_text` for a `PROMPT_SELECT` question?**

It is accepted as-is (`source: "text"`). The validator does not enforce
`answer_selection` for `PROMPT_SELECT` questions at the protocol level;
only `answer_selection` validates the value against the options list. Using
`answer_text` bypasses options validation — useful for accessibility tools
that paste option values programmatically.

**Can I use `enumerate_options: false` to suppress reading option labels?**

Yes. Set `enumerate_options: false` in `start_session`. The TTS will only
narrate the question label, not the option list. The options are still
delivered in the `question` message for the UI to render.

**What is the TTS audio format and sample rate?**

SuperTonic emits **WAV** (`audio/wav`, 44.1 kHz, 16-bit PCM). Google TTS
emits **OGG Vorbis** (`audio/ogg`, 24 kHz). The `tts_mime_format` field in
`AudioSessionConfig` (default `"audio/wav"`) indicates which format the
client should use when creating the `Blob`. Both are natively decoded by
all modern browsers.

**How do I handle a `VISUAL_FALLBACK` field for `location` or `signature`?**

The server renders a generic `<input type="text" name="{field_id}" />` as
the fallback HTML when no specific HTML5 renderer is registered for that
field type. Override it by registering a custom `FieldRenderer` with the
`HTML5Renderer` registry for those `FieldType` values.

**Does the session survive a page reload?**

No. Session state is in-memory on the server. Closing the WebSocket loses
the session. To build resumable sessions, implement a Redis-backed
`SessionStore` keyed by `session_id` (returned in `session_started`) and
pass `session_id` back in `start_session` to restore state.

**How can I test without real TTS/STT hardware?**

Inject mock dependencies in `setup_form_api`:

```python
from unittest.mock import AsyncMock, MagicMock

synth = AsyncMock()
synth.synthesize.return_value = MagicMock(audio=b"fake-audio", mime_format="audio/wav")

transcriber = AsyncMock()
transcriber.transcribe.return_value = MagicMock(
    text="test answer", confidence=0.95, language="en"
)

setup_form_api(app, registry, synthesizer=synth, transcriber=transcriber)
```

**Can I use `answer_payload` for a REST field that uploads a file?**

Yes. The typical flow is:
1. Client receives `VISUAL_FALLBACK` question with a `<input type="file">` in `fallback_html`.
2. User selects a file.
3. Client uploads the file to its own storage (S3, GCS, etc.).
4. Client sends `answer_payload` with the resulting URL or object key.
5. Server stores the URL as the field's answer.

---

*Documentation for parrot-formdesigner — FEAT-236 Audio Renderer Form (Voice Modes).*
*See also: [`formdesigner-audio-renderer.md`](formdesigner-audio-renderer.md) (FEAT-224 baseline).*
