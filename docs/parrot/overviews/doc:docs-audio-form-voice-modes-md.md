---
type: Wiki Overview
title: Audio Form Voice Modes — Developer Guide
id: doc:docs-audio-form-voice-modes-md
tags:
- overview
timestamp: '2026-07-14T22:20:21+00:00'
summary: 1. [What Changed in FEAT-236](#1-what-changed-in-feat-236)
relates_to:
- concept: mod:parrot.voice.handler
  rel: mentions
- concept: mod:parrot.voice.transcriber.faster_whisper_backend
  rel: mentions
- concept: mod:parrot.voice.tts.models
  rel: mentions
- concept: mod:parrot.voice.tts.synthesizer
  rel: mentions
---

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

…(truncated)…
