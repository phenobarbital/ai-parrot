---
type: Wiki Overview
title: FormDesigner — Audio Renderer
id: doc:docs-formdesigner-audio-renderer-md
tags:
- overview
timestamp: '2026-07-14T22:20:21+00:00'
summary: 1. [¿Qué es el Audio Renderer?](#1-qué-es-el-audio-renderer)
relates_to:
- concept: mod:parrot.voice.handler
  rel: mentions
- concept: mod:parrot.voice.transcriber
  rel: mentions
- concept: mod:parrot.voice.transcriber.faster_whisper_backend
  rel: mentions
- concept: mod:parrot.voice.tts
  rel: mentions
- concept: mod:parrot.voice.tts.synthesizer
  rel: mentions
---

# FormDesigner — Audio Renderer

**Feature**: FEAT-224  
**Paquete**: `parrot-formdesigner`  
**Versión mínima requerida**: 1.x  

---

> **🆕 FEAT-236 — Audio Renderer Form (Voice Modes)**
>
> Esta guía cubre la implementación original del Audio Renderer (FEAT-224):
> backend Google TTS, protocolo WebSocket básico, y campos de respuesta
> `text`/`speech`.
>
> FEAT-236 amplió esta base con:
> - **SuperTonic TTS** como backend preferido (sub-segundo, ONNX) con
>   fallback automático a Google.
> - **Taxonomía `VoiceMode`** — cada pregunta se clasifica como `VOICE`,
>   `PROMPT_SELECT`, o `VISUAL_FALLBACK`: ya no se descarta ningún campo
>   requerido.
> - **Nuevos mensajes WebSocket**: `answer_selection`, `answer_payload`,
>   `confirm_answer` (cliente) y `confirm_request` (servidor).
> - **Campos nuevos en `question`**: `voice_mode`, `render_mode`,
>   `sensitive`, `fallback_html`.
> - **Compuerta de confianza STT**: respuestas con baja confianza activan
>   un turno de confirmación antes de almacenarse.
>
> **→ Guía completa de FEAT-236:**
> [`audio-form-voice-modes.md`](audio-form-voice-modes.md)

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
  > **⚠️ Actualizado en FEAT-236**: solo `HIDDEN` se omite. Los campos
  > `REST`, `ARRAY`, `FILE`, `IMAGE`, `LOCATION`, etc. ya no se descartan;
  > en su lugar se clasifican como `VoiceMode.VISUAL_FALLBACK` y se
  > entregan con un `fallback_html` inline para que el usuario los complete
  > visualmente dentro de la sesión. Ningún campo requerido se pierde.
  > Ver [§5 de la guía FEAT-236](audio-form-voice-modes.md#5-voicemode-taxonomy).
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

> **🆕 Modelos extendidos en FEAT-236** — los modelos anteriores son la
> definición baseline. FEAT-236 añadió:
>
> - **`VoiceMode`** — enum `VOICE | PROMPT_SELECT | VISUAL_FALLBACK`.
> - **`AudioQuestion`** — campos nuevos: `voice_mode`, `render_mode`,
>   `sensitive`, `fallback_html`.
> - **`AudioSessionConfig`** — campos nuevos: `tts_backend`,
>   `enumerate_options`, `stt_confirm_threshold`.
> - **`AudioAnswer.source`** — nuevo valor `"selection"` además de
>   `"text"` y `"speech"`.
> - **`AudioSessionState`** — campo nuevo `pending` (respuesta de STT
>   con baja confianza en espera de confirmación).
>
> Definiciones completas:
> [`audio-form-voice-modes.md §4`](audio-form-voice-modes.md#4-rest-endpoint--audio-manifest)

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

# ── FEAT-236: configuración SuperTonic-first (recomendada) ───────────────────
# Omite el parámetro synthesizer= para activar el modo auto_synthesize.
# El handler intentará SuperTonic → Google → texto solo, en ese orden.
# Requiere la variable de entorno SUPERTONIC_MODEL_PATH apuntando al
# directorio con los pesos ONNX.
#
# setup_form_api(
#     app, registry,
#     transcriber=FasterWhisperBackend(model_size="base"),
#     token_validator=TokenValidator(secret_key=os.environ["JWT_SECRET"]),
#     # sin synthesizer= → auto_synthesize=True internamente
# )
#
# Ver guía completa: audio-form-voice-modes.md §3
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

> **🆕 FEAT-236** — el manifiesto incluye campos adicionales por pregunta:
> `voice_mode` (`"voice"` | `"prompt_select"` | `"visual_fallback"`),
> `render_mode` (`"voice"` | `"select"` | `"visual"`), `sensitive`
> (boolean), y `fallback_html` (HTML inline para campos complejos).
> Ver payload completo:
> [`audio-form-voice-modes.md §4`](audio-form-voice-modes.md#42-response--full-payload-with-voicemode)

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

> **🆕 FEAT-236** añade tres nuevos tipos de mensaje:
> - **`answer_selection`** — respuesta de selección UI para preguntas
>   `PROMPT_SELECT` (radio/checkbox/dropdown).
> - **`answer_payload`** — valor recogido de un campo `VISUAL_FALLBACK`
>   renderizado inline.
> - **`confirm_answer`** — confirma o rechaza una transcripción STT con
>   baja confianza después de recibir `confirm_request`.
>
> Ver referencia completa:
> [`audio-form-voice-modes.md §7.1`](audio-form-voice-modes.md#71-client--server-messages)

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

> **🆕 FEAT-236** — `start_session` acepta seis campos adicionales
> opcionales: `tts_backend`, `tts_voice`, `tts_mime_format`,
> `auto_advance`, `enumerate_options`, `stt_confirm_threshold`.
> Ver [`audio-form-voice-modes.md §6`](audio-form-voice-modes.md#6-start_session--extended-payload).

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

> **🆕 FEAT-236** — el mensaje `question` incluye cuatro campos nuevos
> siempre presentes: `voice_mode`, `render_mode`, `sensitive`, y
> `fallback_html` (solo para `VISUAL_FALLBACK`). El frontend debe ramificar
> su lógica de renderizado según `render_mode`: `"voice"` → input de
> texto/micrófono; `"select"` → radio/checkbox; `"visual"` → inyectar
> `fallback_html`.
> Ver [`audio-form-voice-modes.md §7.2`](audio-form-voice-modes.md#72-server--client-messages).

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

> **🆕 FEAT-236** — `source` puede ser también `"selection"` cuando la
> respuesta provino de un `answer_selection` (pregunta `PROMPT_SELECT`).
> Para campos sensibles (`sensitive: true`), el campo `value` se omite
> de la respuesta.

---

#### `confirm_request` *(nuevo en FEAT-236)*

Enviado cuando la confianza STT está por debajo del umbral configurado
(`stt_confirm_threshold`). La sesión se pausa hasta recibir `confirm_answer`.

```json
{
  "type": "confirm_request",
  "field_id": "nombre",
  "transcript": "Juan García López",
  "confidence": 0.38
}
```

El cliente debe mostrar el transcript al usuario y pedir confirmación.
Responder con `confirm_answer { confirmed: true }` para aceptar, o
`{ confirmed: false }` para descartar y re-enviar la misma pregunta.

Ver flujo completo:
[`audio-form-voice-modes.md §8.4`](audio-form-voice-modes.md#84-stt-confidence-gate)

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

…(truncated)…
