# FormDesigner Audio Renderer

**Feature**: FEAT-224  
**Package**: `parrot-formdesigner`  
**Minimum required version**: 1.x  

---

> **🆕 FEAT-236 — Audio Renderer Form (Voice Modes)**
>
> This guide covers the original Audio Renderer implementation (FEAT-224):
> Google TTS backend, the basic WebSocket protocol, and the `text`/`speech`
> answer fields.
>
> FEAT-236 extended this foundation with:
> - **SuperTonic TTS** as the preferred backend (sub-second, ONNX) with
>   automatic fallback to Google.
> - **`VoiceMode` taxonomy** — every question is classified as `VOICE`,
>   `PROMPT_SELECT`, or `VISUAL_FALLBACK`: no required field is dropped
>   any more.
> - **New WebSocket messages**: `answer_selection`, `answer_payload`,
>   `confirm_answer` (client) and `confirm_request` (server).
> - **New fields in `question`**: `voice_mode`, `render_mode`,
>   `sensitive`, `fallback_html`.
> - **STT confidence gate**: low-confidence answers trigger a confirmation
>   turn before being stored.
>
> **→ Full FEAT-236 guide:**
> [`audio-form-voice-modes.md`](../integrations/audio-form-voice-modes.md)

---

## Table of contents

1. [What is the Audio Renderer?](#1-what-is-the-audio-renderer)
2. [General architecture](#2-general-architecture)
3. [Backend components](#3-backend-components)
   - 3.1 [AudioFormRenderer](#31-audioformrenderer)
   - 3.2 [AudioFormWSHandler](#32-audioformwshandler)
   - 3.3 [AudioFieldRenderer (HTML5)](#33-audiofieldrenderer-html5)
   - 3.4 [Data models](#34-data-models)
4. [Server configuration](#4-server-configuration)
5. [REST endpoint — getting the manifest](#5-rest-endpoint--getting-the-manifest)
6. [WebSocket protocol](#6-websocket-protocol)
   - 6.1 [Authentication](#61-authentication)
   - 6.2 [Client → server messages](#62-client--server-messages)
   - 6.3 [Server → client messages](#63-server--client-messages)
   - 6.4 [Full session flow](#64-full-session-flow)
7. [Frontend integration guide](#7-frontend-integration-guide)
   - 7.1 [Connecting and authenticating](#71-connecting-and-authenticating)
   - 7.2 [Starting the session](#72-starting-the-session)
   - 7.3 [Answering with text](#73-answering-with-text)
   - 7.4 [Answering with audio](#74-answering-with-audio)
   - 7.5 [Navigation: skip, go back, repeat](#75-navigation-skip-go-back-repeat)
   - 7.6 [Completing the form](#76-completing-the-form)
   - 7.7 [Full reference client](#77-full-reference-client)
8. [CSS and accessibility of the AUDIO field in HTML5](#8-css-and-accessibility-of-the-audio-field-in-html5)
9. [Errors and error codes](#9-errors-and-error-codes)
10. [Security considerations](#10-security-considerations)
11. [Frequently asked questions](#11-frequently-asked-questions)

---

## 1. What is the Audio Renderer?

The **Audio Renderer** turns any FormDesigner `FormSchema` into a **voice-driven**
form-filling experience: each field is read aloud using TTS (Text-to-Speech),
the user answers by speaking or typing, and the answers are collected and
submitted as standard form data.

Communication between the frontend and the server goes through a dedicated
**WebSocket** that manages the full session state, audio transcription
(STT with Faster Whisper) and speech synthesis (TTS).

### Use cases

- **Accessibility**: users who cannot comfortably read or write.
- **Field work**: operators with their hands full who need to dictate
  answers.
- **Phone interactions**: voice bots that guide the user through a
  structured form.
- **Mixed HTML5 forms**: `AUDIO` fields embedded in regular visual
  forms.

---

## 2. General architecture

```
Frontend                         Backend (parrot-formdesigner)
   │                                       │
   │  GET /api/v1/forms/{id}/render/audio  │
   ├──────────────────────────────────────►│  AudioFormRenderer
   │◄── AudioFormManifest (JSON) ──────────┤  (manifest + ws_endpoint)
   │                                       │
   │  WS wss://…/forms/{id}/audio/ws       │
   ├──────────────────────────────────────►│  AudioFormWSHandler
   │  Sec-WebSocket-Protocol: <JWT>        │  ↳ JWT authentication
   │                                       │
   │  → start_session                      │
   │◄── session_started                    │  loads FormSchema
   │◄── question {label, audio_b64}        │  pre-synthesized TTS
   │                                       │
   │  → answer_text / binary blob          │  STT if audio
   │◄── [transcription]                    │  transcribes with Whisper
   │◄── answer_accepted                    │  validates and stores
   │◄── question (next)                    │
   │  ...                                  │
   │◄── form_complete {answers, sub_id}    │  submits to storage
   │                                       │
   └─ WS close ───────────────────────────►│
```

### Technologies involved

| Layer | Technology |
|------|-----------|
| TTS (server voice) | `VoiceSynthesizer` (`parrot.voice.tts`) |
| STT (transcription) | `FasterWhisperBackend` (`parrot.voice.transcriber`) |
| WS authentication | `TokenValidator` (`parrot.voice.handler`) |
| HTTP / WS server | `aiohttp` |
| Data models | `pydantic` v2 |
| Browser recording | `MediaRecorder API` |

---

## 3. Backend components

### 3.1 AudioFormRenderer

**Path**: `parrot_formdesigner/renderers/audio.py`

Inherits from `AbstractFormRenderer` and is registered under the key `"audio"`.
Its responsibility is to convert a `FormSchema` into an **`AudioFormManifest`**:
a sequential list of questions ready to be read aloud or played back.

```python
class AudioFormRenderer(AbstractFormRenderer):
    def __init__(self, synthesizer: VoiceSynthesizer | None = None): ...

    def split_into_questions(
        self, form: FormSchema, *, locale: str = "en"
    ) -> list[AudioQuestion]: ...

    async def render(
        self, form: FormSchema, ..., locale: str = "en"
    ) -> RenderedForm: ...
```

**Key behavior:**

- Fields of type `HIDDEN`, `ARRAY` and `REST` are skipped automatically.
  > **⚠️ Updated in FEAT-236**: only `HIDDEN` is skipped. `REST`, `ARRAY`,
  > `FILE`, `IMAGE`, `LOCATION` fields, etc. are no longer dropped;
  > instead they are classified as `VoiceMode.VISUAL_FALLBACK` and
  > delivered with an inline `fallback_html` so the user can complete them
  > visually within the session. No required field is lost.
  > See [§5 of the FEAT-236 guide](../integrations/audio-form-voice-modes.md#5-voicemode-taxonomy).
- `GROUP` fields are expanded: their children are added as independent
  questions.
- `SELECT`, `MULTI_SELECT` and `DYNAMIC_SELECT` fields include the list
  of options in the question.
- If a `VoiceSynthesizer` is injected, each question is pre-synthesized during
  `render()` and the audio is stored in `AudioQuestion.audio_prompt` (bytes).
  When the manifest is serialized to JSON, `audio_prompt` is excluded (the bytes
  are delivered over WebSocket as base64).
- The maximum number of questions per session is **10** (extra questions are
  truncated with a warning log).

### 3.2 AudioFormWSHandler

**Path**: `parrot_formdesigner/api/audio_ws.py`

aiohttp handler for the WebSocket endpoint. It manages a complete **stateful
session** for each connection: authentication, form loading, question delivery,
receiving answers (text or audio), transcription and final submission.

```python
class AudioFormWSHandler:
    def __init__(
        self,
        registry: FormRegistry,
        synthesizer: VoiceSynthesizer | None,
        transcriber: FasterWhisperBackend | None,
        validator: FormValidator,
        *,
        token_validator: TokenValidator | None = None,
        submission_storage: FormSubmissionStorage | None = None,
        max_msg_size: int = 10 * 1024 * 1024,  # 10 MB
    ): ...

    async def handle_websocket(self, request: web.Request) -> web.WebSocketResponse: ...
```

**Internal flow per connection:**

1. The `WebSocketResponse` is prepared with `heartbeat=30 s`.
2. The connection is authenticated (see §6.1).
3. An empty `AudioSessionState` is created with a unique `session_id` (UUID4).
4. Message loop:
   - Text frames → dispatch by `type` to the internal handlers.
   - Binary frames → `_handle_answer_audio` → STT → validation.
5. When the last question is answered → `_finish_session` → `FormSubmission` → storage.

### 3.3 AudioFieldRenderer (HTML5)

**Path**: `parrot_formdesigner/renderers/fields/audio.py`

Implements the `FieldRenderer` protocol for `FieldType.AUDIO` inside the
`HTML5Renderer`. It generates a self-contained HTML snippet with:

- A recording button with a start/stop toggle.
- A visual audio waveform indicator (animatable via CSS).
- An `<input type="hidden">` that stores the transcript (or the typed text).
- Inline JavaScript using the `MediaRecorder API` (MIME type detection for
  Safari compatibility: `audio/webm` or `audio/mp4`).
- An `audio-recorded` event (CustomEvent with `{ fieldId, blob }`) so the
  frontend framework can capture the blob and send it to the WebSocket.

### 3.4 Data models

Defined in `parrot_formdesigner/audio/models.py`:

```python
class AudioSessionConfig(BaseModel):
    form_id: str
    locale: str = "en"
    tts_voice: str | None = None
    tts_mime_format: str = "audio/ogg"
    auto_advance: bool = True

class AudioQuestion(BaseModel):
    index: int               # 0-based position in the list
    field_id: str            # field ID in the FormSchema
    field_type: str          # FieldType enum value ("text", "select", …)
    label: str               # resolved question text
    description: str | None  # help text (optional)
    required: bool
    audio_prompt: bytes | None  # pre-synthesized TTS (not serialized to JSON)
    constraints: dict | None
    options: list[dict] | None  # [{value, label}] for SELECT fields

class AudioFormManifest(BaseModel):
    form_id: str
    title: str
    total_questions: int
    questions: list[AudioQuestion]
    ws_endpoint: str         # WS route, e.g. "/api/v1/forms/{id}/audio/ws"
    locale: str

class AudioAnswer(BaseModel):
    field_id: str
    value: str
    source: Literal["text", "speech"]
    confidence: float | None   # 0.0–1.0, only for source="speech"
    raw_transcript: str | None

class AudioSessionState(BaseModel):
    session_id: str
    form_id: str
    user_id: str
    current_index: int = 0
    answers: dict[str, AudioAnswer]
    manifest: AudioFormManifest | None
    completed: bool = False
```

> **🆕 Models extended in FEAT-236** — the models above are the baseline
> definition. FEAT-236 added:
>
> - **`VoiceMode`** — enum `VOICE | PROMPT_SELECT | VISUAL_FALLBACK`.
> - **`AudioQuestion`** — new fields: `voice_mode`, `render_mode`,
>   `sensitive`, `fallback_html`.
> - **`AudioSessionConfig`** — new fields: `tts_backend`,
>   `enumerate_options`, `stt_confirm_threshold`.
> - **`AudioAnswer.source`** — new value `"selection"` in addition to
>   `"text"` and `"speech"`.
> - **`AudioSessionState`** — new field `pending` (low-confidence STT
>   answer awaiting confirmation).
>
> Full definitions:
> [`audio-form-voice-modes.md §4`](../integrations/audio-form-voice-modes.md#4-rest-endpoint-audio-manifest)

---

## 4. Server configuration

The WebSocket endpoint is mounted automatically when `setup_form_api()` is
called with at least one of `synthesizer`, `transcriber` or
`token_validator`:

```python
from parrot_formdesigner.api.routes import setup_form_api
from parrot.voice.tts.synthesizer import VoiceSynthesizer
from parrot.voice.transcriber.faster_whisper_backend import FasterWhisperBackend
from parrot.voice.handler import TokenValidator

setup_form_api(
    app,
    registry,
    # Speech synthesis (TTS). Optional: without it no audio is delivered to the client.
    synthesizer=VoiceSynthesizer(backend="google"),
    # Speech transcription (STT). Optional: without it binary frames are not accepted.
    transcriber=FasterWhisperBackend(model_size="base"),
    # JWT validation. Required in production.
    token_validator=TokenValidator(secret_key=os.environ["JWT_SECRET"]),
    # Submission storage (optional).
    submission_storage=my_submission_storage,
)

# ── FEAT-236: SuperTonic-first configuration (recommended) ───────────────────
# Omit the synthesizer= parameter to enable auto_synthesize mode.
# The handler will try SuperTonic → Google → text only, in that order.
# Requires the SUPERTONIC_MODEL_PATH environment variable pointing to the
# directory with the ONNX weights.
#
# setup_form_api(
#     app, registry,
#     transcriber=FasterWhisperBackend(model_size="base"),
#     token_validator=TokenValidator(secret_key=os.environ["JWT_SECRET"]),
#     # no synthesizer= → auto_synthesize=True internally
# )
#
# See the full guide: audio-form-voice-modes.md §3
```

This registers the route:

```
GET  /api/v1/forms/{form_id}/audio/ws   →  AudioFormWSHandler.handle_websocket
GET  /api/v1/forms/{form_id}/render/audio  →  AudioFormRenderer (via the render dispatcher)
```

> **Production note**: The WS endpoint **does not use** the `navigator-auth`
> decorators (`is_authenticated` / `user_session`) because they return
> HTTP 401, which is incompatible with the WebSocket handshake.
> Authentication is performed **inside** the handler using JWT.

---

## 5. REST endpoint — getting the manifest

Before opening the WebSocket connection, the frontend can (optionally) fetch
the form manifest in audio mode to pre-render the UI:

```
GET /api/v1/forms/{form_id}/render/audio
Authorization: Bearer <jwt>
Accept-Language: es   (optional, determines the locale of the questions)
```

**Response** `200 OK`:

```json
{
  "form_id": "onboarding-form",
  "title": "Formulario de incorporación",
  "total_questions": 5,
  "locale": "es",
  "ws_endpoint": "/api/v1/forms/onboarding-form/audio/ws",
  "questions": [
    {
      "index": 0,
      "field_id": "name",
      "field_type": "text",
      "label": "¿Cuál es tu nombre completo?",
      "description": null,
      "required": true,
      "constraints": { "max_length": 100 },
      "options": null
    },
    {
      "index": 1,
      "field_id": "department",
      "field_type": "select",
      "label": "¿A qué departamento perteneces?",
      "required": true,
      "constraints": null,
      "options": [
        { "value": "eng", "label": "Ingeniería" },
        { "value": "mkt", "label": "Marketing" },
        { "value": "ops", "label": "Operaciones" }
      ]
    }
  ]
}
```

> **Note**: the `audio_prompt` field (TTS bytes) is **excluded** from the JSON.
> The audio arrives over WebSocket as base64 inside the `question` message.

> **🆕 FEAT-236** — the manifest includes additional per-question fields:
> `voice_mode` (`"voice"` | `"prompt_select"` | `"visual_fallback"`),
> `render_mode` (`"voice"` | `"select"` | `"visual"`), `sensitive`
> (boolean), and `fallback_html` (inline HTML for complex fields).
> See the full payload:
> [`audio-form-voice-modes.md §4`](../integrations/audio-form-voice-modes.md#42-response-full-payload-with-voicemode)

---

## 6. WebSocket protocol

### 6.1 Authentication

The handler supports **two authentication mechanisms**, in order of preference:

#### Mechanism 1 — Subprotocol header (recommended)

The JWT token is passed as a custom subprotocol in the
`Sec-WebSocket-Protocol` header during the upgrade:

```
GET /api/v1/forms/onboarding-form/audio/ws HTTP/1.1
Upgrade: websocket
Connection: Upgrade
Sec-WebSocket-Protocol: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9…
```

In the browser with the native WebSocket API:

```javascript
const token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9…";
const ws = new WebSocket(
  "wss://api.example.com/api/v1/forms/onboarding-form/audio/ws",
  [token]   // second argument = subprotocols
);
```

#### Mechanism 2 — `auth` message (fallback)

If no valid token is detected in the header, the server waits **10 seconds**
for a JSON message of type `auth` as the first message on the connection:

```json
{ "type": "auth", "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9…" }
```

If neither mechanism works, the server sends:

```json
{ "type": "error", "code": "AUTH_REQUIRED", "message": "Authentication required" }
```

…and closes the connection.

---

### 6.2 Client → server messages

All text messages are JSON with a `"type"` field.

> **🆕 FEAT-236** adds three new message types:
> - **`answer_selection`** — UI selection answer for `PROMPT_SELECT`
>   questions (radio/checkbox/dropdown).
> - **`answer_payload`** — value collected from an inline-rendered
>   `VISUAL_FALLBACK` field.
> - **`confirm_answer`** — confirms or rejects a low-confidence STT
>   transcript after receiving `confirm_request`.
>
> See the full reference:
> [`audio-form-voice-modes.md §7.1`](../integrations/audio-form-voice-modes.md#71-client-server-messages)

#### `start_session`

Starts the audio session for a form. It **must be the first message**
after authenticating.

```json
{
  "type": "start_session",
  "form_id": "onboarding-form",
  "locale": "es"
}
```

| Field | Type | Required | Description |
|-------|------|-----------|-------------|
| `form_id` | string | Yes* | Form ID. If omitted, the one from the URL is used. |
| `locale` | string | No | BCP 47 (e.g. `"es"`, `"en-US"`). Default: `"en"`. |

> **🆕 FEAT-236** — `start_session` accepts six additional optional
> fields: `tts_backend`, `tts_voice`, `tts_mime_format`,
> `auto_advance`, `enumerate_options`, `stt_confirm_threshold`.
> See [`audio-form-voice-modes.md §6`](../integrations/audio-form-voice-modes.md#6-start_session-extended-payload).

---

#### `answer_text`

Sends a text answer for the current question.

```json
{
  "type": "answer_text",
  "field_id": "name",
  "value": "Juan García López"
}
```

| Field | Type | Required | Description |
|-------|------|-----------|-------------|
| `field_id` | string | Yes | Must match the `field_id` of the active question. |
| `value` | string | Yes | Answer value. |

---

#### `answer_audio` — binary frame

To send a voice answer, send a **binary WebSocket frame**
(not a JSON message) with the bytes of the recorded audio.

```javascript
ws.send(audioBlob);        // MediaRecorder Blob
// or
ws.send(audioArrayBuffer); // ArrayBuffer
```

The server:
1. Writes the bytes to a temporary file.
2. Transcribes with Faster Whisper.
3. Returns a `transcription` message with the text and the confidence.
4. Validates and stores the answer.
5. Advances to the next question.

Supported formats: `audio/webm`, `audio/mp4`, `audio/ogg`.

---

#### `skip_question`

Skips the current question if it is **optional**. If it is required, the server
responds with `answer_rejected`.

```json
{ "type": "skip_question" }
```

---

#### `go_back`

Navigates to a previous question to correct an answer.

```json
{
  "type": "go_back",
  "to_index": 0
}
```

| Field | Type | Required | Description |
|-------|------|-----------|-------------|
| `to_index` | integer | No | 0-based index to go back to. If omitted, goes back one position. |

---

#### `repeat_question`

Requests that the current question be resent (useful for replaying the TTS audio).

```json
{ "type": "repeat_question" }
```

---

#### `end_session`

Aborts the session without submitting the form.

```json
{ "type": "end_session" }
```

---

#### `ping`

Keep-alive to hold the connection open.

```json
{ "type": "ping" }
```

---

### 6.3 Server → client messages

#### `session_started`

Confirms that the session was started successfully.

```json
{
  "type": "session_started",
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "total_questions": 5,
  "title": "Formulario de incorporación"
}
```

---

#### `question`

Delivers the next question. Includes the TTS audio as base64 if a
synthesizer is available.

```json
{
  "type": "question",
  "index": 0,
  "field_id": "name",
  "label": "¿Cuál es tu nombre completo?",
  "required": true,
  "field_type": "text",
  "description": "Ingresa tu nombre y apellidos completos.",
  "audio": "SUQzBAAAAAAAI1RTU0UAAAAPAAADTGF2ZjU4Ljc2LjEwMAAA…",
  "options": null
}
```

| Field | Always present | Description |
|-------|-----------------|-------------|
| `index` | Yes | 0-based position in the full list. |
| `field_id` | Yes | Field ID. Use it in `answer_text`. |
| `label` | Yes | Question text (already resolved to the locale). |
| `required` | Yes | `true` if the question is required. |
| `field_type` | Yes | Field type (`"text"`, `"select"`, `"audio"`, …). |
| `description` | Only if present | Additional help text. |
| `audio` | Only if TTS is available | Base64 of the WAV/OGG audio to play. |
| `options` | Only for SELECT | `[{"value": "…", "label": "…"}]`. |

> **🆕 FEAT-236** — the `question` message includes four new fields that are
> always present: `voice_mode`, `render_mode`, `sensitive`, and
> `fallback_html` (only for `VISUAL_FALLBACK`). The frontend must branch its
> rendering logic on `render_mode`: `"voice"` → text/microphone input;
> `"select"` → radio/checkbox; `"visual"` → inject
> `fallback_html`.
> See [`audio-form-voice-modes.md §7.2`](../integrations/audio-form-voice-modes.md#72-server-client-messages).

**Playing the TTS audio** (example):

```javascript
function playQuestionAudio(base64Audio) {
  const binary = atob(base64Audio);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  const blob = new Blob([bytes], { type: "audio/ogg" });
  const url = URL.createObjectURL(blob);
  const audio = new Audio(url);
  audio.onended = () => URL.revokeObjectURL(url);
  audio.play();
}
```

---

#### `transcription`

Sent **before** `answer_accepted` when the answer was given by audio.
It lets the frontend show the transcript to the user so they can confirm
or correct it before it is processed.

```json
{
  "type": "transcription",
  "field_id": "name",
  "text": "Juan García López",
  "confidence": 0.97
}
```

---

#### `answer_accepted`

Confirms that the answer was validated and stored.

```json
{
  "type": "answer_accepted",
  "field_id": "name",
  "value": "Juan García López",
  "source": "speech"
}
```

`source` is `"text"` or `"speech"`.

> **🆕 FEAT-236** — `source` can also be `"selection"` when the
> answer came from an `answer_selection` (`PROMPT_SELECT` question).
> For sensitive fields (`sensitive: true`), the `value` field is omitted
> from the response.

---

#### `confirm_request` *(new in FEAT-236)*

Sent when the STT confidence is below the configured threshold
(`stt_confirm_threshold`). The session is paused until `confirm_answer` is received.

```json
{
  "type": "confirm_request",
  "field_id": "nombre",
  "transcript": "Juan García López",
  "confidence": 0.38
}
```

The client must show the transcript to the user and ask for confirmation.
Reply with `confirm_answer { confirmed: true }` to accept, or
`{ confirmed: false }` to discard and resend the same question.

See the full flow:
[`audio-form-voice-modes.md §8.4`](../integrations/audio-form-voice-modes.md#84-stt-confidence-gate)

---

#### `answer_rejected`

The answer did not pass validation.

```json
{
  "type": "answer_rejected",
  "field_id": "name",
  "reason": "This field is required"
}
```

---

#### `form_complete`

Sent when all questions have been answered and the form was submitted
to storage.

```json
{
  "type": "form_complete",
  "submission_id": "sub_9f3a1b2c",
  "answers": {
    "name": { "value": "Juan García López", "source": "speech" },
    "department": { "value": "eng", "source": "text" }
  }
}
```

`submission_id` is `null` if no storage is configured or if the submission failed
(a warning is logged on the server but the session still completes).

---

#### `session_ended`

Confirmation of `end_session`.

```json
{
  "type": "session_ended",
  "session_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

---

#### `error`

Protocol or server error. The connection may stay open unless
the code is `AUTH_REQUIRED` (in which case it is closed immediately).

```json
{
  "type": "error",
  "code": "FORM_NOT_FOUND",
  "message": "Form 'onboarding-form' not found"
}
```

---

#### `pong`

Reply to `ping`.

```json
{ "type": "pong" }
```

---

### 6.4 Full session flow

```
Client                                     Server
   │                                          │
   │  WS connect + JWT subprotocol            │
   ├─────────────────────────────────────────►│
   │◄──────── (connection established) ───────┤
   │                                          │
   │  → start_session { form_id, locale }     │
   ├─────────────────────────────────────────►│
   │◄──── session_started { id, total, title} ┤
   │◄──── question [0] { label, audio_b64 }   ┤
   │                                          │
   │  (play TTS audio)                        │
   │  (user speaks)                           │
   │                                          │
   │  → [binary frame: .webm recording]       │
   ├─────────────────────────────────────────►│  → STT
   │◄──── transcription { text, confidence }  ┤
   │◄──── answer_accepted { source: "speech" }┤
   │◄──── question [1] { label, audio_b64 }   ┤
   │                                          │
   │  (user types)                            │
   │                                          │
   │  → answer_text { field_id, value }       │
   ├─────────────────────────────────────────►│
   │◄──── answer_accepted                     ┤
   │◄──── question [2] ...                    ┤
   │  ...                                     │
   │  (last question answered)                │
   │◄──── answer_accepted                     ┤
   │◄──── form_complete { submission_id, …}   ┤
   │                                          │
   └─ WS close ──────────────────────────────►│
```

---

## 7. Frontend integration guide

### 7.1 Connecting and authenticating

```javascript
// Obtain the JWT beforehand (login or refresh token)
const token = await getAuthToken();

const wsUrl = `wss://api.example.com/api/v1/forms/${formId}/audio/ws`;

// Pass the JWT as a subprotocol (recommended mechanism)
const ws = new WebSocket(wsUrl, [token]);

ws.addEventListener("open", () => {
  console.log("Conexión establecida");
});

ws.addEventListener("error", (event) => {
  console.error("Error WS:", event);
});
```

---

### 7.2 Starting the session

```javascript
ws.addEventListener("open", () => {
  ws.send(JSON.stringify({
    type: "start_session",
    form_id: "onboarding-form",
    locale: "es"
  }));
});
```

Upon receiving `session_started`, the server will immediately send the first
`question`. Save the `session_id` if you need to identify the session:

```javascript
ws.addEventListener("message", (event) => {
  const msg = JSON.parse(event.data);

  if (msg.type === "session_started") {
    state.sessionId = msg.session_id;
    state.totalQuestions = msg.total_questions;
    updateTitle(msg.title);
  }

  if (msg.type === "question") {
    showQuestion(msg);
    if (msg.audio) playQuestionAudio(msg.audio);
  }
});
```

---

### 7.3 Answering with text

```javascript
function sendTextAnswer(fieldId, value) {
  ws.send(JSON.stringify({
    type: "answer_text",
    field_id: fieldId,
    value: value
  }));
}

// Example: from an <input>
document.getElementById("answer-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    sendTextAnswer(state.currentFieldId, e.target.value.trim());
    e.target.value = "";
  }
});
```

---

### 7.4 Answering with audio

Recording is done with `MediaRecorder`. The resulting blob is sent
directly as a binary WebSocket frame.

```javascript
let mediaRecorder = null;
let audioChunks = [];

async function startRecording() {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });

  // Detect a compatible MIME type (Chrome: webm, Safari: mp4)
  const mimeType = MediaRecorder.isTypeSupported("audio/webm")
    ? "audio/webm"
    : MediaRecorder.isTypeSupported("audio/mp4")
    ? "audio/mp4"
    : "";

  const options = mimeType ? { mimeType } : {};
  mediaRecorder = new MediaRecorder(stream, options);
  audioChunks = [];

  mediaRecorder.addEventListener("dataavailable", (e) => {
    if (e.data.size > 0) audioChunks.push(e.data);
  });

  mediaRecorder.addEventListener("stop", () => {
    const blob = new Blob(audioChunks, mimeType ? { type: mimeType } : {});
    // Send as a binary WebSocket frame
    ws.send(blob);
    stream.getTracks().forEach((t) => t.stop());
  });

  mediaRecorder.start();
}

function stopRecording() {
  if (mediaRecorder && mediaRecorder.state !== "inactive") {
    mediaRecorder.stop();
  }
}
```

Handling the transcript received from the server:

```javascript
if (msg.type === "transcription") {
  // Show the transcript to the user while it is being validated
  showTranscriptionPreview(msg.field_id, msg.text, msg.confidence);
}

if (msg.type === "answer_accepted" && msg.source === "speech") {
  confirmTranscription(msg.field_id, msg.value);
}
```

---

### 7.5 Navigation: skip, go back, repeat

```javascript
// Skip an optional question
function skipQuestion() {
  ws.send(JSON.stringify({ type: "skip_question" }));
}

// Go back to the previous question
function goBack() {
  ws.send(JSON.stringify({ type: "go_back" }));
  // or to a specific question:
  // ws.send(JSON.stringify({ type: "go_back", to_index: 2 }));
}

// Repeat the TTS audio of the current question
function repeatQuestion() {
  ws.send(JSON.stringify({ type: "repeat_question" }));
}

// Keep-alive every 20 seconds (the server already sends a heartbeat every 30 s)
setInterval(() => {
  if (ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: "ping" }));
  }
}, 20_000);
```

---

### 7.6 Completing the form

```javascript
if (msg.type === "form_complete") {
  console.log("Formulario completado:", msg.submission_id);
  console.log("Respuestas:", msg.answers);

  // Close the connection cleanly
  ws.close(1000, "Form completed");

  // Redirect or show a confirmation screen
  showSuccessScreen(msg.submission_id);
}
```

---

### 7.7 Full reference client

Below is a minimal vanilla JavaScript client that
implements the full flow. It can be used as the basis for an implementation
in React, Vue, Svelte or another framework.

```javascript
/**
 * AudioFormClient — reference client for the audio renderer.
 * Usage: const client = new AudioFormClient(formId, token, callbacks);
 *        client.connect();
 */
class AudioFormClient {
  constructor(formId, token, callbacks = {}) {
    this.formId = formId;
    this.token = token;
    this.cb = callbacks;  // { onQuestion, onTranscription, onAccepted, onRejected, onComplete, onError }
    this.ws = null;
    this.mediaRecorder = null;
    this.audioChunks = [];
    this.isRecording = false;
    this._pingInterval = null;
  }

  // ── Connection ────────────────────────────────────────────────────────────

  connect(locale = "es") {
    const url = `/api/v1/forms/${this.formId}/audio/ws`;
    this.ws = new WebSocket(url, [this.token]);
    this.ws.binaryType = "arraybuffer";

    this.ws.onopen = () => {
      this._send({ type: "start_session", form_id: this.formId, locale });
      this._pingInterval = setInterval(() => this._send({ type: "ping" }), 20_000);
    };

    this.ws.onmessage = (event) => {
      if (event.data instanceof ArrayBuffer) return; // we do not expect binary from the server
      this._handleMessage(JSON.parse(event.data));
    };

    this.ws.onclose = () => {
      clearInterval(this._pingInterval);
      this.cb.onClose?.();
    };

    this.ws.onerror = (err) => this.cb.onError?.({ code: "WS_ERROR", message: err });
  }

  disconnect() {
    this.ws?.close(1000, "Client disconnect");
  }

  // ── Dispatch of incoming messages ──────────────────────────────────────────

  _handleMessage(msg) {
    switch (msg.type) {
      case "session_started":
        this.cb.onSessionStarted?.(msg);
        break;
      case "question":
        this.cb.onQuestion?.(msg);
        if (msg.audio) this._playAudio(msg.audio);
        break;
      case "transcription":
        this.cb.onTranscription?.(msg);
        break;
      case "answer_accepted":
        this.cb.onAccepted?.(msg);
        break;
      case "answer_rejected":
        this.cb.onRejected?.(msg);
        break;
      case "form_complete":
        this.cb.onComplete?.(msg);
        break;
      case "error":
        this.cb.onError?.(msg);
        break;
      case "pong":
        break; // ignore
    }
  }

  // ── Sending answers ───────────────────────────────────────────────────────

  answerText(fieldId, value) {
    this._send({ type: "answer_text", field_id: fieldId, value });
  }

  skipQuestion() {
    this._send({ type: "skip_question" });
  }

  goBack(toIndex) {
    const msg = { type: "go_back" };
    if (toIndex !== undefined) msg.to_index = toIndex;
    this._send(msg);
  }

  repeatQuestion() {
    this._send({ type: "repeat_question" });
  }

  end() {
    this._send({ type: "end_session" });
  }

  // ── Audio recording ───────────────────────────────────────────────────────

  async startRecording() {
    if (this.isRecording) return;
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const mimeType = MediaRecorder.isTypeSupported("audio/webm")
      ? "audio/webm"
      : MediaRecorder.isTypeSupported("audio/mp4") ? "audio/mp4" : "";

    this.mediaRecorder = new MediaRecorder(stream, mimeType ? { mimeType } : {});
    this.audioChunks = [];
    this.isRecording = true;

    this.mediaRecorder.ondataavailable = (e) => {
      if (e.data.size > 0) this.audioChunks.push(e.data);
    };

    this.mediaRecorder.onstop = () => {
      const blob = new Blob(this.audioChunks, mimeType ? { type: mimeType } : {});
      this.ws.send(blob);
      stream.getTracks().forEach((t) => t.stop());
      this.isRecording = false;
    };

    this.mediaRecorder.start();
  }

  stopRecording() {
    if (this.mediaRecorder?.state !== "inactive") this.mediaRecorder.stop();
  }

  // ── Helpers ───────────────────────────────────────────────────────────────

  _send(msg) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(msg));
    }
  }

  _playAudio(base64) {
    const binary = atob(base64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    const blob = new Blob([bytes], { type: "audio/ogg" });
    const url = URL.createObjectURL(blob);
    const audio = new Audio(url);
    audio.onended = () => URL.revokeObjectURL(url);
    audio.play().catch(console.warn);
  }
}

// ── Usage ────────────────────────────────────────────────────────────────────

const client = new AudioFormClient("onboarding-form", jwtToken, {
  onSessionStarted: ({ total_questions, title }) => {
    document.title = title;
    updateProgress(0, total_questions);
  },
  onQuestion: ({ index, label, required, options, field_type }) => {
    renderQuestion({ index, label, required, options, field_type });
  },
  onTranscription: ({ text, confidence }) => {
    showTranscriptionPreview(text, confidence);
  },
  onAccepted: ({ field_id, value }) => {
    markAnswered(field_id, value);
  },
  onRejected: ({ field_id, reason }) => {
    showValidationError(field_id, reason);
  },
  onComplete: ({ submission_id, answers }) => {
    showSuccessScreen(submission_id);
    client.disconnect();
  },
  onError: ({ code, message }) => {
    console.error(`[${code}] ${message}`);
  },
});

client.connect("es");

// Record button
document.getElementById("record-btn").addEventListener("mousedown", () => client.startRecording());
document.getElementById("record-btn").addEventListener("mouseup", () => client.stopRecording());

// Text input
document.getElementById("text-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    client.answerText(currentFieldId, e.target.value.trim());
    e.target.value = "";
  }
});
```

---

## 8. CSS and accessibility of the AUDIO field in HTML5

When the `HTML5Renderer` is used with `AUDIO` fields (mixed visual
forms), the renderer generates this markup:

```html
<div class="form-field form-field--audio" data-field-type="audio" data-field-id="name">
  <label class="field-label" for="name-transcript">¿Cuál es tu nombre?</label>
  <div class="audio-recorder" id="name-recorder">
    <button type="button" class="audio-record-btn" id="name-btn"
            aria-label="Start recording" data-recording="false">
      <span class="audio-record-icon">●</span>
      <span class="audio-record-label">Record</span>
    </button>
    <div class="audio-waveform" id="name-waveform" aria-hidden="true">
      <span></span><span></span><span></span><span></span><span></span>
    </div>
  </div>
  <input type="hidden" id="name-transcript" name="name"
         value="" data-audio-field="name" />
</div>
```

The button emits a `CustomEvent` called `audio-recorded` with
`{ detail: { fieldId, blob } }` that bubbles up to the document. The framework
must listen for this event to send the blob to the WebSocket:

```javascript
document.addEventListener("audio-recorded", async (e) => {
  const { fieldId, blob } = e.detail;
  // send the blob over WebSocket and wait for the server transcript
  ws.send(blob);
  // when "transcription" arrives, fill in the hidden input:
  // document.querySelector(`[data-audio-field="${fieldId}"]`).value = transcript;
});
```

### Recommended minimal CSS

```css
.audio-record-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.4em;
  padding: 0.5em 1em;
  border: 2px solid currentColor;
  border-radius: 2em;
  cursor: pointer;
  transition: background-color 0.2s;
}
.audio-record-btn[data-recording="true"] {
  background-color: #ef4444;
  color: #fff;
  border-color: #ef4444;
}
.audio-record-icon {
  font-size: 1.2em;
  line-height: 1;
}

/* Waveform animation while recording */
.audio-waveform {
  display: flex;
  gap: 3px;
  align-items: flex-end;
  height: 24px;
  visibility: hidden;
}
.audio-waveform--active {
  visibility: visible;
}
.audio-waveform span {
  width: 4px;
  background: #3b82f6;
  border-radius: 2px;
  animation: wave 1.2s ease-in-out infinite;
}
.audio-waveform span:nth-child(2) { animation-delay: 0.1s; }
.audio-waveform span:nth-child(3) { animation-delay: 0.2s; }
.audio-waveform span:nth-child(4) { animation-delay: 0.3s; }
.audio-waveform span:nth-child(5) { animation-delay: 0.4s; }

@keyframes wave {
  0%, 100% { height: 4px; }
  50% { height: 20px; }
}
```

---

## 9. Errors and error codes

| Code | Cause | Closes the connection? |
|--------|-------|---------------------|
| `AUTH_REQUIRED` | JWT missing, invalid or expired | Yes |
| `FORM_NOT_FOUND` | The `form_id` does not exist in the registry | No |
| `SESSION_NOT_STARTED` | A message was sent before `start_session` | No |
| `SESSION_COMPLETE` | An answer was sent after `form_complete` | No |
| `TRANSCRIBER_UNAVAILABLE` | Binary frame with no transcriber configured | No |
| `TRANSCRIPTION_ERROR` | Internal error while transcribing the audio | No |
| `INVALID_JSON` | Text frame is not valid JSON | No |
| `UNKNOWN_MESSAGE_TYPE` | Unknown `type` field | No |
| `INVALID_INDEX` | `to_index` out of range in `go_back` | No |
| `INTERNAL_ERROR` | Uncaught exception on the server | No |

> **🆕 FEAT-236** adds three new error codes:
> `NO_PENDING_ANSWER` (`confirm_answer` was sent without a prior
> `confirm_request`), `FIELD_MISMATCH` (`confirm_answer.field_id` does not match
> the pending answer), and `WRONG_FIELD` (an answer was sent for a field
> other than the active question's). See the full table in
> [`audio-form-voice-modes.md §10`](../integrations/audio-form-voice-modes.md#10-error-codes).

---

## 10. Security considerations

### JWT and production

- **Always** configure `token_validator` in production. Without it, all
  connections are accepted as `anonymous` and a warning is emitted in the logs.
- The JWT token **must not be included** in the URL (it would appear in server logs).
  Use the subprotocol header mechanism or the `auth` message.
- Make sure the `secret_key` of `TokenValidator` is different from that of other
  services and rotate it periodically.

### Frame size

- By default, the server accepts frames of up to **10 MB**. Adjust it with the
  `max_msg_size` parameter of `AudioFormWSHandler` if the audio clips are
  shorter, to reduce the attack surface.
- Validate in the frontend that the recorded audio does not exceed the limit before
  sending it.

### Temporary files

- The server writes the audio to a temporary file on the file system
  during transcription. The file is deleted in the `finally` block even if
  the transcription fails. The files use the `audio_form_` prefix and the
  `.ogg` suffix.

### CORS and origin

- The WebSocket endpoint **has no `Origin` check** of its own;
  it relies on the aiohttp server's CORS configuration. Configure the
  server's CORS middleware to allow only known origins.

---

## 11. Frequently asked questions

**What happens if the user reloads the page halfway through the form?**

The session state is **in memory**; it is lost when the WS connection closes.
If you need recoverable sessions, implement a `RedisSessionStore` and persist
`AudioSessionState` by `session_id`.

**Can I use the audio renderer without TTS?**

Yes. If you do not provide `synthesizer`, `question` messages will not include the
`audio` field. The frontend simply shows the `label` text.

**Can I use the audio renderer without STT?**

Yes. If you do not provide `transcriber`, binary frames will be rejected with
`TRANSCRIBER_UNAVAILABLE`. The user can answer only through `answer_text`.

**How many questions can a form have in audio mode?**

The current limit is **10 questions** per session. Longer forms are
truncated and a warning is emitted. This limit can be changed by modifying the
`MAX_QUESTIONS` constant in `api/audio_ws.py`.

**How do I know which language the TTS synthesizes in?**

The `locale` parameter of `start_session` (or the request parameter of
`render/audio`) is passed to the synthesizer. Valid values depend on the
configured TTS backend (e.g. Google TTS supports BCP-47 tags such as `es-MX`,
`en-US`, `fr-FR`).

**Does the `AUDIO` field in HTML5 send the audio to the WebSocket automatically?**

No. The HTML5 snippet emits the `audio-recorded` event with the blob, but the
frontend is responsible for capturing it and sending it to the WebSocket. This is
intentional, to give the framework full control over the session flow.

**Can it be integrated with React / Vue / Svelte?**

Yes. The `AudioFormClient` class from §7.7 is framework-agnostic. Use it as a
service layer and connect its callbacks to the component state.

---

---

## See also

| Document | Description |
|-----------|-------------|
| [`audio-form-voice-modes.md`](../integrations/audio-form-voice-modes.md) | **Full FEAT-236 guide** — SuperTonic TTS, VoiceMode taxonomy, hybrid flows, extended WebSocket protocol, JS reference client and React/TypeScript component |
| [`voice_chat.md`](../integrations/voice_chat.md) | Conversational voice integration (FEAT-231 AgentTalk) — different from form mode |
| [`whisperx.md`](../integrations/whisperx.md) | STT backend configuration (WhisperX / FasterWhisper) |

---

*Document generated for parrot-formdesigner — FEAT-224 Audio Renderer.*  
*See [`audio-form-voice-modes.md`](../integrations/audio-form-voice-modes.md) for the FEAT-236 extensions.*
