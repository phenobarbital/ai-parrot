# FormDesigner — Audio Renderer

**Feature**: FEAT-224  
**Paquete**: `parrot-formdesigner`  
**Versión mínima requerida**: 1.x  

---

## Índice

1. [¿Qué es el Audio Renderer?](#1-qué-es-el-audio-renderer)
2. [Arquitectura general](#2-arquitectura-general)
3. [Componentes del backend](#3-componentes-del-backend)
   - 3.1 [AudioFormRenderer](#31-audioformrenderer)
   - 3.2 [AudioFormWSHandler](#32-audioformwshandler)
   - 3.3 [AudioFieldRenderer (HTML5)](#33-audiofield-renderer-html5)
   - 3.4 [Modelos de datos](#34-modelos-de-datos)
4. [Configuración del servidor](#4-configuración-del-servidor)
5. [REST endpoint — obtener el manifiesto](#5-rest-endpoint--obtener-el-manifiesto)
6. [Protocolo WebSocket](#6-protocolo-websocket)
   - 6.1 [Autenticación](#61-autenticación)
   - 6.2 [Mensajes cliente → servidor](#62-mensajes-cliente--servidor)
   - 6.3 [Mensajes servidor → cliente](#63-mensajes-servidor--cliente)
   - 6.4 [Flujo completo de una sesión](#64-flujo-completo-de-una-sesión)
7. [Guía de integración para el frontend](#7-guía-de-integración-para-el-frontend)
   - 7.1 [Conectarse y autenticarse](#71-conectarse-y-autenticarse)
   - 7.2 [Iniciar sesión](#72-iniciar-sesión)
   - 7.3 [Responder con texto](#73-responder-con-texto)
   - 7.4 [Responder con audio](#74-responder-con-audio)
   - 7.5 [Navegación: saltar, volver, repetir](#75-navegación-saltar-volver-repetir)
   - 7.6 [Completar el formulario](#76-completar-el-formulario)
   - 7.7 [Cliente completo de referencia](#77-cliente-completo-de-referencia)
8. [CSS y accesibilidad del campo AUDIO en HTML5](#8-css-y-accesibilidad-del-campo-audio-en-html5)
9. [Errores y códigos de error](#9-errores-y-códigos-de-error)
10. [Consideraciones de seguridad](#10-consideraciones-de-seguridad)
11. [Preguntas frecuentes](#11-preguntas-frecuentes)

---

## 1. ¿Qué es el Audio Renderer?

El **Audio Renderer** convierte cualquier `FormSchema` de FormDesigner en una
experiencia de llenado de formulario **por voz**: cada campo se lee en voz alta
mediante TTS (Text-to-Speech), el usuario responde hablando o escribiendo, y
las respuestas se recopilan y envían como datos estándar del formulario.

La comunicación entre el frontend y el servidor se realiza a través de un
**WebSocket** dedicado que gestiona el estado completo de la sesión, la
transcripción de audio (STT con Faster Whisper) y la síntesis de voz (TTS).

### Casos de uso

- **Accesibilidad**: usuarios que no pueden leer/escribir cómodamente.
- **Trabajo de campo**: operadores con las manos ocupadas que necesitan
  dictar respuestas.
- **Interacciones telefónicas**: bots de voz que dirigen al usuario a través
  de un formulario estructurado.
- **Formularios HTML5 mixtos**: campos de tipo `AUDIO` integrados en formularios
  visuales normales.

---

## 2. Arquitectura general

```
Frontend                         Backend (parrot-formdesigner)
   │                                       │
   │  GET /api/v1/forms/{id}/render/audio  │
   ├──────────────────────────────────────►│  AudioFormRenderer
   │◄── AudioFormManifest (JSON) ──────────┤  (manifest + ws_endpoint)
   │                                       │
   │  WS wss://…/forms/{id}/audio/ws       │
   ├──────────────────────────────────────►│  AudioFormWSHandler
   │  Sec-WebSocket-Protocol: <JWT>        │  ↳ autenticación JWT
   │                                       │
   │  → start_session                      │
   │◄── session_started                    │  carga FormSchema
   │◄── question {label, audio_b64}        │  TTS pre-sintetizado
   │                                       │
   │  → answer_text / binary blob          │  STT si es audio
   │◄── [transcription]                    │  transcribe con Whisper
   │◄── answer_accepted                    │  valida y almacena
   │◄── question (siguiente)               │
   │  ...                                  │
   │◄── form_complete {answers, sub_id}    │  envía al storage
   │                                       │
   └─ WS close ───────────────────────────►│
```

### Tecnologías involucradas

| Capa | Tecnología |
|------|-----------|
| TTS (voz del servidor) | `VoiceSynthesizer` (`parrot.voice.tts`) |
| STT (transcripción) | `FasterWhisperBackend` (`parrot.voice.transcriber`) |
| Autenticación WS | `TokenValidator` (`parrot.voice.handler`) |
| HTTP / WS server | `aiohttp` |
| Modelos de datos | `pydantic` v2 |
| Grabación en el browser | `MediaRecorder API` |

---

## 3. Componentes del backend

### 3.1 AudioFormRenderer

**Ruta**: `parrot_formdesigner/renderers/audio.py`

Hereda de `AbstractFormRenderer` y está registrado bajo la clave `"audio"`.
Su responsabilidad es convertir un `FormSchema` en un **`AudioFormManifest`**:
una lista secuencial de preguntas listas para ser leídas o reproducidas.

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

**Comportamiento clave:**

- Los campos de tipo `HIDDEN`, `ARRAY` y `REST` se omiten automáticamente.
- Los campos de tipo `GROUP` se expanden: sus hijos se añaden como preguntas
  independientes.
- Los campos `SELECT`, `MULTI_SELECT` y `DYNAMIC_SELECT` incluyen la lista
  de opciones en la pregunta.
- Si se inyecta un `VoiceSynthesizer`, cada pregunta se pre-sintetiza durante
  `render()` y el audio se almacena en `AudioQuestion.audio_prompt` (bytes).
  Al serializar el manifiesto a JSON, `audio_prompt` se excluye (los bytes se
  entregan por WebSocket en base64).
- El número máximo de preguntas por sesión es **10** (excedentes se truncan
  con un log de advertencia).

### 3.2 AudioFormWSHandler

**Ruta**: `parrot_formdesigner/api/audio_ws.py`

Handler aiohttp para el endpoint WebSocket. Gestiona una **sesión de estado**
completa por cada conexión: autenticación, carga del formulario, entrega de
preguntas, recepción de respuestas (texto o audio), transcripción y envío final.

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

**Flujo interno por conexión:**

1. Se prepara el `WebSocketResponse` con `heartbeat=30 s`.
2. Se autentica la conexión (ver §6.1).
3. Se crea un `AudioSessionState` vacío con un `session_id` único (UUID4).
4. Bucle de mensajes:
   - Frames de texto → dispatch por `type` a los handlers internos.
   - Frames binarios → `_handle_answer_audio` → STT → validación.
5. Al responder la última pregunta → `_finish_session` → `FormSubmission` → storage.

### 3.3 AudioFieldRenderer (HTML5)

**Ruta**: `parrot_formdesigner/renderers/fields/audio.py`

Implementa el protocolo `FieldRenderer` para `FieldType.AUDIO` dentro del
`HTML5Renderer`. Genera un snippet HTML autónomo con:

- Botón de grabación con toggle start/stop.
- Indicador visual de onda de audio (animable por CSS).
- `<input type="hidden">` que almacena la transcripción (o el texto tecleado).
- JavaScript inline con `MediaRecorder API` (detección de MIME type para
  compatibilidad Safari: `audio/webm` o `audio/mp4`).
- Evento `audio-recorded` (CustomEvent con `{ fieldId, blob }`) para que el
  framework del frontend capture el blob y lo envíe al WebSocket.

### 3.4 Modelos de datos

Definidos en `parrot_formdesigner/audio/models.py`:

```python
class AudioSessionConfig(BaseModel):
    form_id: str
    locale: str = "en"
    tts_voice: str | None = None
    tts_mime_format: str = "audio/ogg"
    auto_advance: bool = True

class AudioQuestion(BaseModel):
    index: int               # posición 0-based en la lista
    field_id: str            # ID del campo en el FormSchema
    field_type: str          # valor del FieldType enum ("text", "select", …)
    label: str               # texto resuelto de la pregunta
    description: str | None  # texto de ayuda (opcional)
    required: bool
    audio_prompt: bytes | None  # TTS pre-sintetizado (no se serializa a JSON)
    constraints: dict | None
    options: list[dict] | None  # [{value, label}] para campos SELECT

class AudioFormManifest(BaseModel):
    form_id: str
    title: str
    total_questions: int
    questions: list[AudioQuestion]
    ws_endpoint: str         # ruta WS, ej. "/api/v1/forms/{id}/audio/ws"
    locale: str

class AudioAnswer(BaseModel):
    field_id: str
    value: str
    source: Literal["text", "speech"]
    confidence: float | None   # 0.0–1.0, solo para source="speech"
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

---

## 4. Configuración del servidor

El endpoint WebSocket se monta automáticamente cuando se llama a
`setup_form_api()` con al menos uno de `synthesizer`, `transcriber` o
`token_validator`:

```python
from parrot_formdesigner.api.routes import setup_form_api
from parrot.voice.tts.synthesizer import VoiceSynthesizer
from parrot.voice.transcriber.faster_whisper_backend import FasterWhisperBackend
from parrot.voice.handler import TokenValidator

setup_form_api(
    app,
    registry,
    # Síntesis de voz (TTS). Opcional: sin él no se entrega audio al cliente.
    synthesizer=VoiceSynthesizer(backend="google"),
    # Transcripción de voz (STT). Opcional: sin él no se aceptan frames binarios.
    transcriber=FasterWhisperBackend(model_size="base"),
    # Validación JWT. Requerido en producción.
    token_validator=TokenValidator(secret_key=os.environ["JWT_SECRET"]),
    # Storage de envíos (opcional).
    submission_storage=my_submission_storage,
)
```

Esto registra la ruta:

```
GET  /api/v1/forms/{form_id}/audio/ws   →  AudioFormWSHandler.handle_websocket
GET  /api/v1/forms/{form_id}/render/audio  →  AudioFormRenderer (vía render dispatcher)
```

> **Nota de producción**: El endpoint WS **no usa** los decoradores
> `navigator-auth` (`is_authenticated` / `user_session`) porque devuelven
> HTTP 401, lo que es incompatible con el handshake de WebSocket. La
> autenticación se realiza **dentro** del handler mediante JWT.

---

## 5. REST endpoint — obtener el manifiesto

Antes de abrir la conexión WebSocket, el frontend puede (opcionalmente) obtener
el manifiesto del formulario en modo audio para pre-renderizar la UI:

```
GET /api/v1/forms/{form_id}/render/audio
Authorization: Bearer <jwt>
Accept-Language: es   (opcional, determina el locale de las preguntas)
```

**Respuesta** `200 OK`:

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

> **Nota**: el campo `audio_prompt` (bytes TTS) está **excluido** del JSON.
> El audio llega por WebSocket en base64 dentro del mensaje `question`.

---

## 6. Protocolo WebSocket

### 6.1 Autenticación

El handler soporta **dos mecanismos** de autenticación, en orden de preferencia:

#### Mecanismo 1 — Subprotocol header (recomendado)

El token JWT se pasa como un subprotocolo personalizado en el header
`Sec-WebSocket-Protocol` durante el upgrade:

```
GET /api/v1/forms/onboarding-form/audio/ws HTTP/1.1
Upgrade: websocket
Connection: Upgrade
Sec-WebSocket-Protocol: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9…
```

En el browser con la API nativa de WebSocket:

```javascript
const token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9…";
const ws = new WebSocket(
  "wss://api.example.com/api/v1/forms/onboarding-form/audio/ws",
  [token]   // segundo argumento = subprotocols
);
```

#### Mecanismo 2 — Mensaje `auth` (fallback)

Si no se detecta un token válido en el header, el servidor espera **10 segundos**
por un mensaje JSON de tipo `auth` como primer mensaje de la conexión:

```json
{ "type": "auth", "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9…" }
```

Si ninguno de los dos mecanismos funciona, el servidor envía:

```json
{ "type": "error", "code": "AUTH_REQUIRED", "message": "Authentication required" }
```

…y cierra la conexión.

---

### 6.2 Mensajes cliente → servidor

Todos los mensajes de texto son JSON con un campo `"type"`.

#### `start_session`

Inicia la sesión de audio para un formulario. **Debe ser el primer mensaje**
después de autenticarse.

```json
{
  "type": "start_session",
  "form_id": "onboarding-form",
  "locale": "es"
}
```

| Campo | Tipo | Requerido | Descripción |
|-------|------|-----------|-------------|
| `form_id` | string | Sí* | ID del formulario. Si se omite, usa el de la URL. |
| `locale` | string | No | BCP 47 (ej. `"es"`, `"en-US"`). Default: `"en"`. |

---

#### `answer_text`

Envía una respuesta de texto para la pregunta actual.

```json
{
  "type": "answer_text",
  "field_id": "name",
  "value": "Juan García López"
}
```

| Campo | Tipo | Requerido | Descripción |
|-------|------|-----------|-------------|
| `field_id` | string | Sí | Debe coincidir con el `field_id` de la pregunta activa. |
| `value` | string | Sí | Valor de la respuesta. |

---

#### `answer_audio` — frame binario

Para enviar una respuesta de voz, se envía un **frame binario WebSocket**
(no un mensaje JSON) con los bytes del audio grabado.

```javascript
ws.send(audioBlob);        // Blob de MediaRecorder
// o
ws.send(audioArrayBuffer); // ArrayBuffer
```

El servidor:
1. Escribe los bytes en un archivo temporal.
2. Transcribe con Faster Whisper.
3. Devuelve un mensaje `transcription` con el texto y la confianza.
4. Valida y almacena la respuesta.
5. Avanza a la siguiente pregunta.

Formatos soportados: `audio/webm`, `audio/mp4`, `audio/ogg`.

---

#### `skip_question`

Salta la pregunta actual si es **opcional**. Si es obligatoria, el servidor
responde con `answer_rejected`.

```json
{ "type": "skip_question" }
```

---

#### `go_back`

Navega a una pregunta anterior para corregir una respuesta.

```json
{
  "type": "go_back",
  "to_index": 0
}
```

| Campo | Tipo | Requerido | Descripción |
|-------|------|-----------|-------------|
| `to_index` | integer | No | Índice 0-based al que volver. Si se omite, retrocede una posición. |

---

#### `repeat_question`

Solicita que se reenvíe la pregunta actual (útil para repetir el audio TTS).

```json
{ "type": "repeat_question" }
```

---

#### `end_session`

Aborta la sesión sin enviar el formulario.

```json
{ "type": "end_session" }
```

---

#### `ping`

Keep-alive para mantener la conexión activa.

```json
{ "type": "ping" }
```

---

### 6.3 Mensajes servidor → cliente

#### `session_started`

Confirma que la sesión fue iniciada correctamente.

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

Entrega la siguiente pregunta. Incluye el audio TTS en base64 si hay
sintetizador disponible.

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

| Campo | Siempre presente | Descripción |
|-------|-----------------|-------------|
| `index` | Sí | Posición 0-based en la lista total. |
| `field_id` | Sí | ID del campo. Usarlo en `answer_text`. |
| `label` | Sí | Texto de la pregunta (ya resuelto al locale). |
| `required` | Sí | `true` si la pregunta es obligatoria. |
| `field_type` | Sí | Tipo de campo (`"text"`, `"select"`, `"audio"`, …). |
| `description` | Solo si existe | Texto de ayuda adicional. |
| `audio` | Solo si hay TTS | Base64 del audio WAV/OGG para reproducir. |
| `options` | Solo para SELECT | `[{"value": "…", "label": "…"}]`. |

**Reproducir el audio TTS** (ejemplo):

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

Enviado **antes** de `answer_accepted` cuando la respuesta fue por audio.
Permite al frontend mostrar la transcripción al usuario para que la confirme
o corrija antes de que se procese.

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

Confirma que la respuesta fue validada y almacenada.

```json
{
  "type": "answer_accepted",
  "field_id": "name",
  "value": "Juan García López",
  "source": "speech"
}
```

`source` es `"text"` o `"speech"`.

---

#### `answer_rejected`

La respuesta no pasó la validación.

```json
{
  "type": "answer_rejected",
  "field_id": "name",
  "reason": "This field is required"
}
```

---

#### `form_complete`

Enviado cuando todas las preguntas han sido respondidas y el formulario fue
enviado al storage.

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

`submission_id` es `null` si no hay storage configurado o si el envío falló
(se registra un warning en el servidor pero la sesión se completa igualmente).

---

#### `session_ended`

Confirmación de `end_session`.

```json
{
  "type": "session_ended",
  "session_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

---

#### `error`

Error de protocolo o del servidor. La conexión puede seguir abierta a menos
que el código sea `AUTH_REQUIRED` (en cuyo caso se cierra inmediatamente).

```json
{
  "type": "error",
  "code": "FORM_NOT_FOUND",
  "message": "Form 'onboarding-form' not found"
}
```

---

#### `pong`

Respuesta al `ping`.

```json
{ "type": "pong" }
```

---

### 6.4 Flujo completo de una sesión

```
Cliente                                    Servidor
   │                                          │
   │  WS connect + JWT subprotocol            │
   ├─────────────────────────────────────────►│
   │◄──────── (conexión establecida) ─────────┤
   │                                          │
   │  → start_session { form_id, locale }     │
   ├─────────────────────────────────────────►│
   │◄──── session_started { id, total, title} ┤
   │◄──── question [0] { label, audio_b64 }   ┤
   │                                          │
   │  (reproducir audio TTS)                  │
   │  (usuario habla)                         │
   │                                          │
   │  → [binary frame: grabación .webm]       │
   ├─────────────────────────────────────────►│  → STT
   │◄──── transcription { text, confidence }  ┤
   │◄──── answer_accepted { source: "speech" }┤
   │◄──── question [1] { label, audio_b64 }   ┤
   │                                          │
   │  (usuario escribe)                       │
   │                                          │
   │  → answer_text { field_id, value }       │
   ├─────────────────────────────────────────►│
   │◄──── answer_accepted                     ┤
   │◄──── question [2] ...                    ┤
   │  ...                                     │
   │  (última pregunta respondida)            │
   │◄──── answer_accepted                     ┤
   │◄──── form_complete { submission_id, …}   ┤
   │                                          │
   └─ WS close ──────────────────────────────►│
```

---

## 7. Guía de integración para el frontend

### 7.1 Conectarse y autenticarse

```javascript
// Obtener JWT previamente (login o refresh token)
const token = await getAuthToken();

const wsUrl = `wss://api.example.com/api/v1/forms/${formId}/audio/ws`;

// Pasar el JWT como subprotocolo (mecanismo recomendado)
const ws = new WebSocket(wsUrl, [token]);

ws.addEventListener("open", () => {
  console.log("Conexión establecida");
});

ws.addEventListener("error", (event) => {
  console.error("Error WS:", event);
});
```

---

### 7.2 Iniciar sesión

```javascript
ws.addEventListener("open", () => {
  ws.send(JSON.stringify({
    type: "start_session",
    form_id: "onboarding-form",
    locale: "es"
  }));
});
```

Al recibir `session_started`, el servidor enviará inmediatamente el primer
`question`. Guarda el `session_id` si necesitas identificar la sesión:

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

### 7.3 Responder con texto

```javascript
function sendTextAnswer(fieldId, value) {
  ws.send(JSON.stringify({
    type: "answer_text",
    field_id: fieldId,
    value: value
  }));
}

// Ejemplo: desde un <input>
document.getElementById("answer-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    sendTextAnswer(state.currentFieldId, e.target.value.trim());
    e.target.value = "";
  }
});
```

---

### 7.4 Responder con audio

La grabación se realiza con `MediaRecorder`. El blob resultante se envía
directamente como frame binario WebSocket.

```javascript
let mediaRecorder = null;
let audioChunks = [];

async function startRecording() {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });

  // Detectar MIME type compatible (Chrome: webm, Safari: mp4)
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
    // Enviar como frame binario WebSocket
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

Gestionar la transcripción recibida del servidor:

```javascript
if (msg.type === "transcription") {
  // Mostrar la transcripción al usuario mientras se valida
  showTranscriptionPreview(msg.field_id, msg.text, msg.confidence);
}

if (msg.type === "answer_accepted" && msg.source === "speech") {
  confirmTranscription(msg.field_id, msg.value);
}
```

---

### 7.5 Navegación: saltar, volver, repetir

```javascript
// Saltar pregunta opcional
function skipQuestion() {
  ws.send(JSON.stringify({ type: "skip_question" }));
}

// Volver a la pregunta anterior
function goBack() {
  ws.send(JSON.stringify({ type: "go_back" }));
  // o a una pregunta específica:
  // ws.send(JSON.stringify({ type: "go_back", to_index: 2 }));
}

// Repetir el audio TTS de la pregunta actual
function repeatQuestion() {
  ws.send(JSON.stringify({ type: "repeat_question" }));
}

// Keep-alive cada 20 segundos (el servidor ya hace heartbeat en 30 s)
setInterval(() => {
  if (ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: "ping" }));
  }
}, 20_000);
```

---

### 7.6 Completar el formulario

```javascript
if (msg.type === "form_complete") {
  console.log("Formulario completado:", msg.submission_id);
  console.log("Respuestas:", msg.answers);

  // Cerrar la conexión limpiamente
  ws.close(1000, "Form completed");

  // Redirigir o mostrar pantalla de confirmación
  showSuccessScreen(msg.submission_id);
}
```

---

### 7.7 Cliente completo de referencia

A continuación se muestra un cliente minimal en JavaScript vanilla que
implementa el flujo completo. Se puede usar como base para una implementación
en React, Vue, Svelte u otro framework.

```javascript
/**
 * AudioFormClient — cliente de referencia para el audio renderer.
 * Uso: const client = new AudioFormClient(formId, token, callbacks);
 *      client.connect();
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

  // ── Conexión ──────────────────────────────────────────────────────────────

  connect(locale = "es") {
    const url = `/api/v1/forms/${this.formId}/audio/ws`;
    this.ws = new WebSocket(url, [this.token]);
    this.ws.binaryType = "arraybuffer";

    this.ws.onopen = () => {
      this._send({ type: "start_session", form_id: this.formId, locale });
      this._pingInterval = setInterval(() => this._send({ type: "ping" }), 20_000);
    };

    this.ws.onmessage = (event) => {
      if (event.data instanceof ArrayBuffer) return; // no esperamos binario del servidor
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

  // ── Dispatch de mensajes entrantes ─────────────────────────────────────────

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
        break; // ignorar
    }
  }

  // ── Envío de respuestas ───────────────────────────────────────────────────

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

  // ── Grabación de audio ────────────────────────────────────────────────────

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

// ── Uso ──────────────────────────────────────────────────────────────────────

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

// Botón de grabar
document.getElementById("record-btn").addEventListener("mousedown", () => client.startRecording());
document.getElementById("record-btn").addEventListener("mouseup", () => client.stopRecording());

// Input de texto
document.getElementById("text-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    client.answerText(currentFieldId, e.target.value.trim());
    e.target.value = "";
  }
});
```

---

## 8. CSS y accesibilidad del campo AUDIO en HTML5

Cuando se usa el `HTML5Renderer` con campos de tipo `AUDIO` (formularios
visuales mixtos), el renderer genera este markup:

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

El botón emite un `CustomEvent` llamado `audio-recorded` con
`{ detail: { fieldId, blob } }` que burbujea hasta el documento. El framework
debe escuchar este evento para enviar el blob al WebSocket:

```javascript
document.addEventListener("audio-recorded", async (e) => {
  const { fieldId, blob } = e.detail;
  // enviar blob por WebSocket y esperar la transcripción del servidor
  ws.send(blob);
  // cuando llegue "transcription", rellenar el input hidden:
  // document.querySelector(`[data-audio-field="${fieldId}"]`).value = transcript;
});
```

### CSS mínimo recomendado

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

/* Animación de onda cuando está grabando */
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

## 9. Errores y códigos de error

| Código | Causa | ¿Cierra la conexión? |
|--------|-------|---------------------|
| `AUTH_REQUIRED` | JWT ausente, inválido o expirado | Sí |
| `FORM_NOT_FOUND` | El `form_id` no existe en el registry | No |
| `SESSION_NOT_STARTED` | Se envió un mensaje antes de `start_session` | No |
| `SESSION_COMPLETE` | Se envió respuesta después de `form_complete` | No |
| `TRANSCRIBER_UNAVAILABLE` | Frame binario sin transcriber configurado | No |
| `TRANSCRIPTION_ERROR` | Error interno al transcribir el audio | No |
| `INVALID_JSON` | Frame de texto no es JSON válido | No |
| `UNKNOWN_MESSAGE_TYPE` | Campo `type` desconocido | No |
| `INVALID_INDEX` | `to_index` fuera de rango en `go_back` | No |
| `INTERNAL_ERROR` | Excepción no capturada en el servidor | No |

---

## 10. Consideraciones de seguridad

### JWT y producción

- **Siempre** configura `token_validator` en producción. Sin él, todas las
  conexiones se aceptan como `anonymous` y se emite un warning en los logs.
- El token JWT **no debe incluirse** en la URL (aparecería en logs de servidor).
  Usar el mecanismo de subprotocolo header o el mensaje `auth`.
- Asegurar que el `secret_key` de `TokenValidator` sea diferente al de otros
  servicios y rotarlo periódicamente.

### Tamaño de frames

- Por defecto, el servidor acepta frames de hasta **10 MB**. Ajustarlo con el
  parámetro `max_msg_size` de `AudioFormWSHandler` si los audios son más
  cortos para reducir la superficie de ataque.
- Validar en el frontend que el audio grabado no exceda el límite antes de
  enviarlo.

### Archivos temporales

- El servidor escribe el audio en un archivo temporal en el sistema de archivos
  durante la transcripción. El archivo se borra en el bloque `finally` aunque
  la transcripción falle. Los archivos usan el prefijo `audio_form_` y el
  sufijo `.ogg`.

### CORS y origen

- El endpoint WebSocket **no tiene verificación de `Origin`** propia;
  confía en la configuración CORS del servidor aiohttp. Configura el
  middleware CORS del servidor para permitir solo los orígenes conocidos.

---

## 11. Preguntas frecuentes

**¿Qué pasa si el usuario recarga la página a mitad del formulario?**

El estado de la sesión es **en memoria**; se pierde al cerrar la conexión WS.
Si necesitas sesiones recuperables, implementa un `RedisSessionStore` y persiste
`AudioSessionState` por `session_id`.

**¿Puedo usar el audio renderer sin TTS?**

Sí. Si no proporcionas `synthesizer`, los mensajes `question` no incluirán el
campo `audio`. El frontend simplemente muestra el texto de `label`.

**¿Puedo usar el audio renderer sin STT?**

Sí. Si no proporcionas `transcriber`, los frames binarios serán rechazados con
`TRANSCRIBER_UNAVAILABLE`. El usuario puede responder solo mediante `answer_text`.

**¿Cuántas preguntas puede tener un formulario en modo audio?**

El límite actual es **10 preguntas** por sesión. Formularios más largos se
truncan y se emite un warning. Este límite puede cambiarse modificando la
constante `MAX_QUESTIONS` en `api/audio_ws.py`.

**¿Cómo sé en qué idioma sintetiza el TTS?**

El parámetro `locale` de `start_session` (o el parámetro de la solicitud
`render/audio`) se pasa al sintetizador. Los valores válidos dependen del
backend TTS configurado (ej. Google TTS soporta tags BCP-47 como `es-MX`,
`en-US`, `fr-FR`).

**¿El campo `AUDIO` en HTML5 envía el audio al WebSocket automáticamente?**

No. El snippet HTML5 emite el evento `audio-recorded` con el blob, pero el
frontend es responsable de capturarlo y enviarlo al WebSocket. Esto es
intencional para dar control total al framework sobre el flujo de la sesión.

**¿Se puede integrar con React / Vue / Svelte?**

Sí. La clase `AudioFormClient` del §7.7 es framework-agnóstica. Úsala como
capa de servicio y conecta sus callbacks al estado del componente.

---

*Documento generado para parrot-formdesigner — FEAT-224 Audio Renderer.*
