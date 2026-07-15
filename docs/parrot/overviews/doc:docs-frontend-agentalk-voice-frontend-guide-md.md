---
type: Wiki Overview
title: Guía Técnica de Voz (AgentTalk Voice) para Frontend
id: doc:docs-frontend-agentalk-voice-frontend-guide-md
tags:
- overview
timestamp: '2026-07-14T22:20:21+00:00'
summary: (grabar y enviar nota de voz + reproducir la contestación hablada del agente)
---

# Guía Técnica de Voz (AgentTalk Voice) para Frontend

**Audiencia**: equipo de Frontend que construye la UI de conversación por voz
(grabar y enviar nota de voz + reproducir la contestación hablada del agente)
sobre AI-Parrot.

**Ámbito**: FEAT-231 — *AgentTalk Voice Support* (round-trip REST:
`audio → STT → agente de texto → TTS → audio + contenido`).

**Endpoint**: `POST /api/v1/agents/voice/{agent_id}`
(handler `AgentVoiceTalk`, subclase de `AgentTalk`).

> Este documento está fundamentado en el código real de la rama
> `feat-231-agentalk-voice-support`. Las rutas de archivo y números de línea
> son **anclas de verificación** (anti-alucinación) y pueden moverse; el
> contrato semántico es el que importa.
>
> Archivos fuente verificados:
> - `packages/ai-parrot-server/src/parrot/handlers/agent_voice.py` — handler de voz
> - `packages/ai-parrot-server/src/parrot/handlers/agent.py` — `AgentTalk` (texto, heredado)
> - `packages/ai-parrot-server/src/parrot/manager/manager.py:1453-1480` — registro de ruta
> - `sdd/specs/agentalk-voice-support.spec.md` — especificación (FEAT-231)

---

## 0. Índice

1. [Modelo mental: un adaptador de voz sobre el chat de texto](#1-modelo-mental)
2. [El endpoint de voz](#2-el-endpoint-de-voz)
3. [Enviar la nota de voz (request)](#3-enviar-la-nota-de-voz-request)
4. [La respuesta (envelope + audio)](#4-la-respuesta-envelope--audio)
5. [Reproducir la contestación por voz](#5-reproducir-la-contestación-por-voz)
6. [Selectores opcionales por petición (backends STT/TTS, formato)](#6-selectores-opcionales-por-petición)
7. [Degradación y manejo de errores](#7-degradación-y-manejo-de-errores)
8. [Ejemplos completos (JS/TS)](#8-ejemplos-completos-jsts)
9. [Checklist de integración Frontend](#9-checklist-de-integración-frontend)

---

## 1. Modelo mental

El endpoint de voz **no es un endpoint nuevo de conversación**. Es un
**adaptador de I/O de voz alrededor del flujo de texto existente** de
`AgentTalk`. Hereda *exactamente* la misma resolución de agente, PBAC, HITL,
autenticación, sesiones y negociación de salida que el chat normal. Solo añade
dos costuras:

```
 POST multipart (nota de voz)
         │
         ▼
  ┌──────────────────────────────────────────────┐
  │ 1. ENTRADA (STT)                               │
  │    audio adjunto ──transcribe──▶ query: str    │
  └──────────────────────────────────────────────┘
         │
         ▼
   bot.ask(question=query, …) ──▶ AIMessage   (idéntico al chat de texto)
         │
         ▼
  ┌──────────────────────────────────────────────┐
  │ 2. SALIDA (TTS)                                │
  │    AIMessage.response (str) ──synthesize──▶    │
  │    audio_base64 + audio_format                 │
  └──────────────────────────────────────────────┘
         │
         ▼
 HTTP 200  { …envelope de AgentTalk…, audio_base64, audio_format }
```

**Consecuencias prácticas para el Frontend:**

- El **envelope de respuesta es idéntico** al de `AgentTalk` (`/chat/...`) más
  **dos campos** (`audio_base64`, `audio_format`). Si ya consumes el chat de
  texto, reutilizas todo el parsing.
- **Solo se sintetiza `response.response`** (el texto hablable de la respuesta).
  Lo no-hablable (`output`, `data`, `media`, artefactos estructurados) sigue
  viajando como `content` y **nunca** pasa por el sintetizador. Es decir:
  el usuario *oye* el texto de la respuesta y *ve* las tablas/gráficos/datos.
- Si envías texto (no audio) a este endpoint, se comporta como el chat normal:
  **sin** `audio_base64` en la respuesta.

---

## 2. El endpoint de voz

| | |
|---|---|
| **Método** | `POST` |
| **Ruta** | `/api/v1/agents/voice/{agent_id}` |
| **`{agent_id}`** | nombre/slug del agente (igual que en `/chat/{agent_id}`) |
| **Auth** | `@is_authenticated()` + `@user_session()` (idéntico a `AgentTalk`) |
| **Content-Type entrada** | `multipart/form-data` (para enviar el audio) |
| **Content-Type salida** | `application/json` |

> **Disponibilidad de la ruta** (`manager.py:1453-1480`): la ruta se registra
> bajo un *guard* de integración opcional. Si el servidor no tiene instalado
> el stack de voz (`ai-parrot-integrations[voice]`), la ruta **no se registra**
> y el servidor arranca igual. En ese caso el endpoint devolverá `404`. Trátalo
> como *feature detection*: si recibes `404` en `/voice/...`, oculta la UI de voz.

---

## 3. Enviar la nota de voz (request)

Para enviar audio **debes** usar `multipart/form-data` (es lo que activa
`handle_upload()` en el servidor). El audio va como un *file part*; el resto de
parámetros del chat van como *form fields* (los mismos que aceptaría
`/chat/{agent_id}`).

### 3.1 El file part de audio

El handler detecta el adjunto de audio de dos maneras
(`agent_voice.py::_is_audio`):

1. Por **MIME type**: cualquiera que empiece por `audio/`, o exactamente
   `video/webm` (porque `MediaRecorder` en navegador suele producir
   `audio/webm` o `video/webm`).
2. Por **extensión del nombre de archivo**, si el MIME no es concluyente.
   Contenedores soportados (`_AUDIO_EXTS`, espejo de
   `VoiceTranscriber.SUPPORTED_FORMATS`):

   ```
   .ogg  .mp3  .wav  .m4a  .webm  .mp4  .flac
   ```

> **Recomendación**: graba con `MediaRecorder` y sube `audio/webm` (Opus) o
> `audio/ogg`. Asegúrate de que el `filename` del part tenga una extensión
> válida de la lista (p. ej. `nota.webm`) como respaldo a la detección por MIME.

El **nombre del campo del file part es libre** — el handler busca *cualquier*
adjunto de audio en *cualquier* campo (`_find_audio_attachment` recorre todos
los campos). Usa un nombre claro como `audio` o `file`.

### 3.2 Form fields (todos opcionales salvo lo indicado)

Como el flujo de texto es heredado de `AgentTalk`, estos campos se comportan
igual que en `/chat/{agent_id}`:

| Campo | Tipo | Notas |
|---|---|---|
| `query` | string | **Normalmente NO se envía.** Si lo envías, **gana el texto** y el audio se descarta (ver abajo). |
| `session_id` | string | ID de conversación para mantener contexto. Recomendado. |
| `user_id` | string | Opcional; normalmente resuelto por la sesión autenticada. |
| `output_mode` | string | `json \| html \| markdown \| terminal \| default`. Para voz interesa que el envelope sea JSON (default ya devuelve JSON estructurado en `_format_response`). |
| `message_id` | string | ID de mensaje generado por el cliente (se usa como `turn_id` para dedup en el historial). |
| `use_conversation_history` | bool | default `true`. |
| `use_vector_context` | bool | default `true`. |
| `format_kwargs` | objeto JSON | p. ej. `{"include_sources": true}`. En multipart, envíalo como string JSON. |
| **`stt_backend`** | string | **Nuevo (voz).** Selector de motor STT. Ver §6. |
| **`tts_backend`** | string | **Nuevo (voz).** Selector de motor TTS. Ver §6. |
| **`audio_format`** | string | **Nuevo (voz).** Contenedor de audio de salida deseado. Ver §6. |

### 3.3 Regla de precedencia: audio vs. `query`

`agent_voice.py::handle_upload`:

- **Hay audio y NO hay `query`** → se transcribe el audio y el transcript se
  inyecta como `query`. (`_did_transcribe = True` → la respuesta llevará audio.)
- **Hay audio Y hay `query`** (texto explícito no vacío) → **gana el texto**:
  el audio se descarta, su tempfile se borra, y el flujo es de texto puro
  (la respuesta **no** llevará `audio_base64`).
- **No hay audio** → se comporta exactamente como `AgentTalk` de texto.

> Implicación de UI: para una nota de voz, **no** rellenes `query`. Si tu UI
> permite escribir Y grabar a la vez, decide cuál mandas: si mandas ambos, oirás
> silencio (respuesta solo texto) porque el texto tiene prioridad.

---

## 4. La respuesta (envelope + audio)

`HTTP 200`, `application/json`. Es el **envelope estándar de `AgentTalk`**
(construido en `agent.py::_format_response`, rama `output_format == 'json'`) más
los dos campos de audio que añade `AgentVoiceTalk::_augment_with_audio`.

```jsonc
{
  // ── Envelope heredado de AgentTalk ──────────────────────────
  "input":  "Hola, ¿qué tiempo hace en Madrid?",   // el transcript (query usado)
  "output": "...",            // salida estructurada (DataFrame→records, modelos, etc.) o texto
  "data":   null,             // filas/datos crudos cuando aplica (p. ej. DatabaseAgent)
  "response": "En Madrid hace sol, 25°C.",  // ← TEXTO HABLABLE (lo que se sintetiza)
  "output_mode": "json",
  "code": null,
  "metadata": {
    "model": "gemini-2.0-...",
    "provider": "google",
    "session_id": "abc-123",
    "turn_id": "…",
    "user_id": "…",
    "response_time": 842,      // ms
    "usage": { /* tokens */ },
    "finish_reason": "stop",
    "stop_reason": null,
    "created_at": "2026-06-09T..."
  },
  "sources": [ /* documentos RAG si los hay */ ],
  "tool_calls": [ /* herramientas invocadas si las hay */ ],

  // ── Añadido por AgentVoiceTalk (solo si hubo voz de entrada y TTS tuvo éxito) ──
  "audio_base64": "<base64 de los bytes de audio>",
  "audio_format": "audio/wav"   // mime_format REAL del audio devuelto
}
```

### Campos clave para voz

| Campo | Significado |
|---|---|
| `response` | El **texto** de la contestación del agente. Es exactamente lo que se sintetizó a voz. Muéstralo como subtítulo/transcript junto al reproductor. |
| `audio_base64` | Bytes del audio de la contestación, codificados en **base64** (ASCII). **Presente solo** cuando: (a) la entrada fue una nota de voz, y (b) el TTS tuvo éxito. |
| `audio_format` | El **MIME real** del audio (`SynthesisResult.mime_format`), p. ej. `audio/wav`. Es *veraz* — úsalo tal cual para construir el `Blob`/`data:` URI. No lo asumas. |
| `output` / `data` / artefactos | Contenido **no hablable**: tablas, gráficos, mapas, ficheros. Renderízalo visualmente como en el chat normal (ver la guía de artefactos estructurados). **Nunca** se mete en el audio. |

> **`audio_base64` ausente ≠ error.** Si la petición fue texto, o el TTS no
> estaba disponible/falló, el envelope llega **sin** `audio_base64` pero con
> `response` (texto). Es la degradación esperada (§7).

---

## 5. Reproducir la contestación por voz

`audio_base64` + `audio_format` → reproducible directamente. Dos vías:

**Vía A — `data:` URI (simple):**

```ts
function playFromEnvelope(envelope: any) {
  if (!envelope.audio_base64) return;            // degradado a solo-texto
  const src = `data:${envelope.audio_format};base64,${envelope.audio_base64}`;
  const audio = new Audio(src);
  audio.play();
}
```

**Vía B — `Blob` + object URL (mejor para clips largos / control de memoria):**

```ts
function blobFromEnvelope(envelope: any): Blob | null {
  if (!envelope.audio_base64) return null;
  const bytes = Uint8Array.from(atob(envelope.audio_base64), c => c.charCodeAt(0));
  return new Blob([bytes], { type: envelope.audio_format });  // ← usa el mime REAL
}

const blob = blobFromEnvelope(envelope);
if (blob) {
  const url = URL.createObjectURL(blob);
  const audio = new Audio(url);
  audio.onended = () => URL.revokeObjectURL(url);   // libera memoria
  audio.play();
}
```

> El formato por defecto del servidor es **`audio/wav`** (decisión U5 del spec:
> contenedor amigable para el reproductor web). Todos los navegadores modernos
> reproducen WAV. Si pides otro formato vía `audio_format` (§6), respeta el
> `audio_format` *devuelto*, no el que pediste — el servidor etiqueta de forma
> veraz lo que realmente sintetizó.

---

## 6. Selectores opcionales por petición

`agent_voice.py::_read_voice_options` lee tres form fields opcionales. **No son
necesarios para el caso normal** (hay defaults sensatos); úsalos solo si el
backend tiene esos motores instalados.

| Field | Default | Valores | Efecto |
|---|---|---|---|
| `stt_backend` | `faster_whisper` (default de `VoiceTranscriberConfig`) | `faster_whisper`, `openai_whisper`, `moonshine` | Motor de transcripción (audio→texto). Si el valor es desconocido, se ignora y usa el default. |
| `tts_backend` | `google` | `google`, `elevenlabs`, `openai`, `supertonic` | Motor de síntesis (texto→audio). |
| `audio_format` | `audio/wav` | p. ej. `audio/wav`, `audio/ogg` | Contenedor de salida deseado. El servidor devuelve el `audio_format` real en el envelope. |

> **Estos backends son opt-in y dependen de extras instalados en el servidor**
> (`voice-supertonic`, `voice-moonshine`, etc.). Si pides un backend cuyo extra
> no está instalado, el handler degrada: STT no disponible → `503`; TTS no
> disponible → respuesta **solo-texto** (ver §7). Para el caso común, **omite
> estos campos** y deja que el servidor use FasterWhisper (STT) + Google (TTS).

---

## 7. Degradación y manejo de errores

El diseño prioriza **no romper la conversación**. Resumen de comportamientos:

| Situación | Código | Cuerpo | Qué hace el Frontend |
|---|---|---|---|
| Voz OK, TTS OK | `200` | envelope + `audio_base64` + `audio_format` | Reproduce audio + muestra `response`. |
| Voz OK, **TTS falla / no disponible** | `200` | envelope **sin** `audio_base64` | Muestra `response` como texto; sin reproductor. *(`_augment_with_audio` captura `ValueError/RuntimeError/ImportError` y devuelve la respuesta de texto intacta.)* |
| Texto (sin audio) a `/voice/...` | `200` | envelope **sin** `audio_base64` | Igual que el chat normal. |
| **STT no disponible** (stack/extra no instalado) | `503` | `{"error": "Voice transcription is unavailable; install ai-parrot-integrations[voice]."}` | Muestra error; sugiere reintentar como texto. |
| **Audio no transcribible** (formato inválido, supera duración máx., corrupto) | `400` | `{"error": "Could not transcribe audio: <detalle>"}` | Muestra error de grabación; permite regrabar. |
| Auth requerida por una tool (OAuth) | `200` | `AuthRequiredEnvelope` (heredado) | Render "Connect pill" (igual que en chat). |
| HITL suspend (pausa por interacción humana) | `200` | `PausedEnvelope` (heredado) | Render UI de HITL (igual que en chat). |
| Agente no encontrado | `404` | `{"error": "Agent '…' not found."}` | Error de configuración. |
| Ruta de voz no registrada (sin stack de voz) | `404` | — | Oculta la UI de voz (feature detection). |

**Límite de duración del audio**: el transcriber aplica
`max_audio_duration_seconds` (default **60s**, `VoiceTranscriberConfig`). Notas
de voz más largas devuelven `400`. Considera limitar la grabación en el cliente.

**Regla mental**: trata `audio_base64` como *opcional siempre*. Tu UI debe
funcionar perfectamente solo con `response` (texto). El audio es un *enhancement*.

---

## 8. Ejemplos completos (JS/TS)

### 8.1 Grabar y enviar una nota de voz

```ts
// 1. Grabar con MediaRecorder
async function recordVoiceNote(): Promise<Blob> {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  const recorder = new MediaRecorder(stream, { mimeType: "audio/webm" });
  const chunks: BlobPart[] = [];
  recorder.ondataavailable = (e) => chunks.push(e.data);
  recorder.start();
  // … parar tras la interacción del usuario …
  await new Promise<void>((res) => (recorder.onstop = () => res()));
  stream.getTracks().forEach((t) => t.stop());
  return new Blob(chunks, { type: "audio/webm" });
}

// 2. Enviar al endpoint de voz
async function sendVoiceNote(agentId: string, audio: Blob, sessionId?: string) {
  const form = new FormData();
  // nombre de archivo CON extensión válida como respaldo a la detección MIME
  form.append("audio", audio, "nota.webm");
  if (sessionId) form.append("session_id", sessionId);
  // NO envíes 'query' — gana el texto y descarta el audio
  // selectores opcionales:
  // form.append("tts_backend", "supertonic");
  // form.append("audio_format", "audio/wav");

  const res = await fetch(`/api/v1/agents/voice/${agentId}`, {
    method: "POST",
    body: form,                 // el navegador pone el boundary de multipart
    credentials: "include",     // cookies de sesión / auth
  });

  if (res.status === 404) throw new Error("Voz no disponible en este servidor");
  const envelope = await res.json();
  if (!res.ok) throw new Error(envelope.error ?? `HTTP ${res.status}`);
  return envelope;
}
```

### 8.2 Consumir la respuesta (audio + texto + artefactos)

```ts
const envelope = await sendVoiceNote("weather-bot", audioBlob, sessionId);

// (a) Subtítulo / transcript de la contestación
renderAssistantText(envelope.response);

// (b) Reproducir la voz si vino
if (envelope.audio_base64) {
  const bytes = Uint8Array.from(atob(envelope.audio_base64), c => c.charCodeAt(0));
  const url = URL.createObjectURL(new Blob([bytes], { type: envelope.audio_format }));
  const player = new Audio(url);
  player.onended = () => URL.revokeObjectURL(url);
  await player.play();
} else {
  // degradación a solo-texto — perfectamente válido
}

// (c) Render de artefactos NO hablables (tablas/gráficos/mapas/datos)
//     igual que en el chat normal — ver structured-artifacts-frontend-guide.md
if (envelope.output_mode?.startsWith("structured_")) {
  renderStructuredArtifact(envelope);   // usa envelope.response.artifacts + envelope.data
}
```

---

## 9. Checklist de integración Frontend

- [ ] Grabar con `MediaRecorder` (`audio/webm` u `audio/ogg`) y subir como
      `multipart/form-data`, con `filename` que tenga extensión válida
      (`.webm`, `.ogg`, `.wav`, …).
- [ ] **No** enviar `query` en una nota de voz (el texto tiene prioridad sobre el audio).
- [ ] Enviar `session_id` para mantener el hilo de conversación.
- [ ] Reproducir `audio_base64` usando **el `audio_format` devuelto** (no asumir WAV).
- [ ] Mostrar siempre `response` (texto) como transcript/subtítulo de la voz.
- [ ] Tratar `audio_base64` como **opcional**: la UI debe funcionar en solo-texto.
- [ ] Render de `output`/`data`/artefactos como en el chat normal (no entran en el audio).
- [ ] Manejar `503` (STT no disponible) y `400` (audio no transcribible) con mensajes claros.
- [ ] Feature detection: `404` en `/voice/...` → ocultar la UI de voz.
- [ ] (Opcional) Limitar la duración de grabación en cliente (servidor: 60s por defecto).
- [ ] (Opcional) Exponer selectores `stt_backend` / `tts_backend` / `audio_format`
      solo si el servidor tiene esos motores instalados.

---

## Apéndice — Anclas de verificación (código real)

| Concepto | Archivo:línea |
|---|---|
| Handler de voz | `packages/ai-parrot-server/src/parrot/handlers/agent_voice.py` |
| Detección de audio (MIME/extensión) | `agent_voice.py::_is_audio`, `_AUDIO_EXTS` |
| Inyección de transcript / precedencia audio vs query | `agent_voice.py::handle_upload` |
| Selectores STT/TTS/formato | `agent_voice.py::_read_voice_options` |
| Adjunta `audio_base64` + `audio_format` | `agent_voice.py::_augment_with_audio`, `_synthesize` |
| Degradación TTS (try/except) | `agent_voice.py::_augment_with_audio` |
| Default `audio/wav` | `agent_voice.py::_DEFAULT_AUDIO_FORMAT` |
| Envelope JSON heredado | `agent.py::_format_response` (rama `output_format == 'json'`) |
| Campo `response` (texto hablable) | `agent.py::_format_response` → `obj_response["response"]` |
| Registro de ruta bajo guard opcional | `manager/manager.py:1453-1480` |
| Especificación completa | `sdd/specs/agentalk-voice-support.spec.md` (FEAT-231) |

> Estado FEAT-231: implementado y verificado en la rama
> `feat-231-agentalk-voice-support` (4 tareas: Supertonic TTS, Moonshine STT,
> handler `AgentVoiceTalk`, registro de ruta). Pendiente de merge a `dev` en el
> momento de redactar esta guía.
