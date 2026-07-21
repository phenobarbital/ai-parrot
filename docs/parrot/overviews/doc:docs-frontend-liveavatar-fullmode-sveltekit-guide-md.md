---
type: Wiki Overview
title: Guía Frontend (SvelteKit) — LiveAvatar FULL Mode + VoiceBot (FEAT-248)
id: doc:docs-frontend-liveavatar-fullmode-sveltekit-guide-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: para conversar **por voz con un agente de ai-parrot mostrando un avatar
---

# Guía Frontend (SvelteKit) — LiveAvatar FULL Mode + VoiceBot (FEAT-248)

**Audiencia**: equipo de Frontend que va a construir un **módulo SvelteKit**
para conversar **por voz con un agente de ai-parrot mostrando un avatar
parlante** (lip-sync) en tiempo real.

**Ámbito**: FEAT-248 — *LiveAvatar FULL Mode — `speak_text` Integration*. Aquí
el navegador **no** publica micrófono crudo a tu backend ni corre TTS: la sala
de LiveKit la gestiona **LiveAvatar** (STT + TTS + vídeo con lip-sync). El
backend de ai-parrot solo **acuña la sesión** y devuelve credenciales de
LiveKit. **El bucle de conversación lo conduce el frontend**:

```
usuario habla → user.transcription (STT de LiveAvatar)
             → tú llamas al agente ai-parrot (texto)
             → avatar.speak_text {text}  (el avatar lo habla, SIN su LLM)
```

> ✅ **Estado del backend (2026-06-19).** FEAT-248 está **implementado y
> fusionado en `dev`** (rama `feat-248-liveavatar-fullmode-speaktext`). Código
> real y verificado:
> - `packages/ai-parrot-server/src/parrot/handlers/avatar_fullmode.py` —
>   endpoints REST `start`/`stop`/`avatars`/`voices`/`transcript`.
> - `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/client.py` —
>   `create_full_session_token()`, `start_session()`, `list_avatars()`,
>   `list_voices()`, `get_session_transcript()`.
> - `…/liveavatar/models.py` — `FullModeConfig`, `FullModeSessionHandle`,
>   `TenantAvatarConfig`.
> - `…/liveavatar/optin.py` — `is_fullmode_enabled()` (gate por tenant).
> - `…/liveavatar/fullmode_observer.py` — observador pasivo de la sala
>   (logging/transcripción server-side, **opcional**).
> - `sdd/specs/liveavatar-fullmode-speaktext.spec.md` — especificación.
>
> Lo que ya está **confirmado por spike** (`spike_q1_speaktext.py`, Q1 resuelto):
> `avatar.speak_text` habla **texto arbitrario** en modo restringido (sin
> `context_id` ni `llm_configuration_id`), es decir, el avatar **nunca**
> responde solo con su LLM interno. Tú controlas qué dice.

---

## 0. Índice

1. [Modelo mental: ¿quién hace qué?](#1-modelo-mental-quién-hace-qué)
2. [FULL Mode vs LITE (Phase A) vs voz-nativo (Phase C)](#2-full-mode-vs-lite-vs-voz-nativo)
3. [Dependencias del frontend](#3-dependencias-del-frontend)
4. [Paso 1 — Arrancar la sesión (`/fullmode/start`)](#4-paso-1--arrancar-la-sesión-fullmodestart)
5. [Paso 2 — Conectar a la sala LiveKit y pintar el vídeo](#5-paso-2--conectar-a-la-sala-livekit-y-pintar-el-vídeo)
6. [Paso 3 — Protocolo de eventos (data channels)](#6-paso-3--protocolo-de-eventos-data-channels)
7. [Paso 4 — El bucle de conversación](#7-paso-4--el-bucle-de-conversación)
8. [Paso 5 — Llamar al agente ai-parrot (texto)](#8-paso-5--llamar-al-agente-ai-parrot-texto)
9. [Paso 6 — Parar la sesión (`/fullmode/stop`)](#9-paso-6--parar-la-sesión-fullmodestop)
10. [Endpoints de descubrimiento (avatars / voices / transcript)](#10-endpoints-de-descubrimiento)
11. [Arquitectura del módulo SvelteKit](#11-arquitectura-del-módulo-sveltekit)
12. [Seguridad, gating y manejo de errores](#12-seguridad-gating-y-manejo-de-errores)
13. [Checklist de implementación](#13-checklist-de-implementación)
14. [Referencia rápida de la API](#14-referencia-rápida-de-la-api)

---

## 1. Modelo mental: ¿quién hace qué?

Tres actores. **Memorízalos**, porque el reparto de responsabilidades es lo que
distingue FULL Mode de los otros modos.

| Actor | Responsabilidad |
|---|---|
| **LiveAvatar** (managed room) | STT (transcribe al usuario), TTS (sintetiza la voz del avatar) y **vídeo con lip-sync**. Es dueño de la sala LiveKit. |
| **Backend ai-parrot** (este repo) | Acuña la sesión FULL, devuelve `livekit_url` + `livekit_client_token`, mantiene keep-alive, y (opcional) observa la sala para logging/transcripción. **NO corre TTS/STT.** |
| **Frontend (tú)** | Conecta a la sala, pinta el vídeo, **conduce el bucle**: recibe `user.transcription`, llama al agente ai-parrot por texto, y envía `avatar.speak_text` con la respuesta. |

```
┌──────────────┐  POST /fullmode/start   ┌───────────────┐  POST /v1/sessions/* ┌────────────┐
│  Frontend    │ ───────────────────────>│  Backend       │ ───────────────────> │ LiveAvatar │
│  (SvelteKit) │ <─────────────────────── │  ai-parrot     │ <─────────────────── │   API      │
│              │  {livekit_url,           │ (avatar_       │  {livekit_url,       │            │
│              │   livekit_client_token,  │  fullmode.py)  │   livekit_client_    │            │
│              │   session_id}            │                │   token}             │            │
└──────┬───────┘                          └───────────────┘                      └─────┬──────┘
       │                                                                                │
       │  ① join room (livekit-client) ──────────────────────────────────────────────> │
       │  ② <video> ← track de vídeo del avatar (lip-sync) <──────────────────────────  │
       │  ③ recibe `user.transcription` (agent-response) <──────────────────────────── │
       │                                                                                │
       │  ④ POST /bots/{agent}/stream/...  → texto del agente (ai-parrot)               │
       │                                                                                │
       │  ⑤ envía `avatar.speak_text {text}` (agent-control) ─────────────────────────>│
       │  ⑥ el avatar habla + emite `avatar.transcription.chunk` <───────────────────── │
```

**Punto clave**: el "cerebro" es ai-parrot, pero el avatar es solo una **boca
tonta**. Le mandas texto por `avatar.speak_text` y lo dice. Nunca decide qué
hablar por su cuenta (modo restringido).

---

## 2. FULL Mode vs LITE vs voz-nativo

| | **FULL Mode (FEAT-248)** | **LITE / Phase A (FEAT-242)** | **Voz-nativo / Phase C (FEAT-243)** |
|---|---|---|---|
| Quién hace TTS | LiveAvatar | ai-parrot (Supertonic ONNX, push PCM por WS) | LiveKit Agents (plugin Cartesia) |
| Quién hace STT | LiveAvatar | — (no hay voz de entrada) | LiveKit Agents (plugin Deepgram) |
| ¿Navegador publica micrófono? | **No al backend** — LiveAvatar lo capta en la sala | No | Sí (a la sala) |
| Bucle de conversación | **lo conduce el frontend** | el frontend | un worker de LiveKit Agents |
| Infra de ai-parrot | mínima (solo gateway) | runtime Supertonic | worker LiveKit largo |
| Transporte vídeo | LiveKit room (`livekit_url`) | WS (`ws_url`) | LiveKit room |
| Credencial al navegador | `livekit_client_token` | `ws_url` + token | token con publish de audio |

> ⚠️ En FULL Mode, el handle de sesión hereda `ws_url` de la clase base
> (`AvatarSessionHandle`) pero **está vacío y no se usa** — solo aplica a LITE.
> Usa siempre `livekit_url` + `livekit_client_token`.

Esta guía cubre **solo FULL Mode**. Phase C (LiveKit Agents worker) fue eliminado
en FEAT-249; consulta el [Mode A / B / C / D taxonomy](./liveavatar-frontend-guide.md)
para el mapa actualizado de modos de voz.

---

## 3. Dependencias del frontend

```bash
npm i livekit-client
# Opcional, si LiveAvatar publica el SDK web (preferido si está disponible):
# npm i @heygen/liveavatar-web-sdk
```

- **`livekit-client`** — es el camino garantizado: conectas a la sala,
  suscribes el track de vídeo del avatar y usas los **data channels** para
  enviar/recibir eventos (`agent-control` / `agent-response`).
- **`@heygen/liveavatar-web-sdk`** — si está disponible, envuelve lo anterior y
  puede exponer helpers de envío/suscripción de eventos. Verifica que exponga
  `agent-control`/`agent-response`; si no, cae a `livekit-client` directo
  (esta guía usa `livekit-client`, que siempre funciona).

---

## 4. Paso 1 — Arrancar la sesión (`/fullmode/start`)

**Endpoint** (autenticado: `@is_authenticated()` + `@user_session()`):

```
POST /api/v1/avatar/fullmode/{agent_id}/start
```

`{agent_id}` es el nombre lógico del agente de ai-parrot que va a "pensar".

**Request body** (JSON):

```jsonc
{
  "session_id": "abc-123",      // REQUERIDO. ID de sesión de AgentChat, compartido con el navegador
  "tenant_id": "acme",          // opcional, para el gate de opt-in por tenant
  "agent_name": "support-bot"   // opcional; por defecto = {agent_id} de la ruta
}
```

**Response** (200, **solo credenciales de visor**):

```jsonc
{
  "session_id": "abc-123",
  "livekit_url": "wss://<project>.livekit.cloud",
  "livekit_client_token": "eyJhbGciOi..."   // JWT subscribe-only para el navegador
}
```

> 🔒 **Nunca** se devuelven `session_token`, `api_key` ni ningún secreto
> server-side. El `livekit_client_token` es de **solo suscripción** (el
> navegador no publica tracks; LiveAvatar lo hace).

**Códigos de error que debes manejar**:

| Código | Significado | Acción frontend |
|---|---|---|
| `400` | falta `session_id` | bug del cliente; revisa el body |
| `403` | el tenant no tiene FULL mode habilitado (`is_fullmode_enabled`) | muestra "avatar no disponible para tu cuenta" |
| `409` | ya hay una sesión activa para ese `session_id` | reutiliza la sesión existente o genera un `session_id` nuevo |
| `503` | el stack de LiveAvatar no está instalado o falta config `LIVEAVATAR_*` | error de infraestructura; reintenta/avisa |

**Ejemplo (SvelteKit, fetch con credenciales de cookie de sesión)**:

```ts
// src/lib/api/avatarFullmode.ts
export interface FullModeSession {
  session_id: string;
  livekit_url: string;
  livekit_client_token: string;
}

export async function startFullModeSession(
  agentId: string,
  sessionId: string,
  opts: { tenantId?: string; agentName?: string } = {}
): Promise<FullModeSession> {
  const res = await fetch(`/api/v1/avatar/fullmode/${agentId}/start`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include', // cookie de navigator_auth
    body: JSON.stringify({
      session_id: sessionId,
      tenant_id: opts.tenantId,
      agent_name: opts.agentName
    })
  });
  if (!res.ok) {
    throw new Error(`fullmode/start falló: ${res.status} ${res.statusText}`);
  }
  return res.json();
}
```

> ⏱️ El backend arranca un **keep-alive** automático (ping < 5 min) mientras la
> sesión vive, y aplica `max_session_duration` como red de seguridad para
> sesiones abandonadas. En **sandbox** la duración se topa a ~60s sin importar
> lo que pidas. Una sesión FULL consume créditos STT+TTS+vídeo por minuto:
> **siempre llama a `/stop`** al terminar (ver §9).

---

## 5. Paso 2 — Conectar a la sala LiveKit y pintar el vídeo

Con `livekit_url` + `livekit_client_token`, conecta con `livekit-client` y
suscribe el track de vídeo del avatar:

```ts
import { Room, RoomEvent, Track, type RemoteTrack } from 'livekit-client';

export async function connectAvatarRoom(
  session: FullModeSession,
  videoEl: HTMLVideoElement
): Promise<Room> {
  const room = new Room({ adaptiveStream: true, dynacast: true });

  room.on(RoomEvent.TrackSubscribed, (track: RemoteTrack) => {
    if (track.kind === Track.Kind.Video) {
      track.attach(videoEl);          // <video> ← lip-sync del avatar
    } else if (track.kind === Track.Kind.Audio) {
      track.attach();                 // audio del avatar (voz TTS)
    }
  });

  await room.connect(session.livekit_url, session.livekit_client_token);
  return room;
}
```

```svelte
<!-- AvatarStage.svelte -->
<video bind:this={videoEl} autoplay playsinline class="avatar-video"></video>
```

> El navegador es **solo suscriptor**: no publica cámara ni micrófono propios.
> LiveAvatar captura el micrófono del usuario dentro de su propia sala gestionada
> y emite el vídeo del avatar como track remoto.

---

## 6. Paso 3 — Protocolo de eventos (data channels)

Toda la conversación viaja como **mensajes JSON por data channels de LiveKit**,
en dos topics:

- **`agent-control`** → **tú envías** (comandos al avatar).
- **`agent-response`** → **tú recibes** (transcripciones y estado del avatar).

**Envelope confirmado por spike (plano, sin anidar)**:

```jsonc
{
  "event_id": "<uuid>",          // genera uno por mensaje que envíes
  "event_type": "avatar.speak_text",
  "session_id": "<liveavatar-session-id>",
  "source_event_id": null,        // en eventos de respuesta, correla con el comando
  "text": "<texto>"               // payload opcional según el evento
}
```

### 6.1 Envías en `agent-control`

| `event_type` | Payload | Uso |
|---|---|---|
| `avatar.speak_text` | `{text}` | **Hablar el texto del agente (sin LLM)** — salida principal. ✅ verificado. |
| `avatar.interrupt` | — | Barge-in: corta y limpia la cola de habla |
| `avatar.start_listening` / `avatar.stop_listening` | — | Pista de UX de "escuchando" |
| `user.start_push_to_talk` / `user.stop_push_to_talk` | — | Solo en `interactivity_type = PUSH_TO_TALK` |

### 6.2 Recibes en `agent-response`

| `event_type` | Payload | Uso |
|---|---|---|
| `user.transcription` | `{text}` | **Salida de STT** — lo que dijo el usuario (dispara el bucle) |
| `user.speak_started` / `user.speak_ended` | — | Fronteras de turno / disparar barge-in |
| `avatar.speak_started` / `avatar.speak_ended` | `{source_event_id}` | Estado de habla del avatar (correlado al comando que lo originó) |
| `avatar.transcription.chunk` | `{text}` | ✅ (verificado, no documentado) texto hablado **palabra por palabra** mientras el avatar habla |
| `avatar.transcription` | `{text}` | Texto hablado completo, una sola vez |
| `session.stopped` | `{end_reason}` | Teardown: `IDLE_TIMEOUT`, `MAX_DURATION_REACHED`, `NO_CREDITS`, … |

### 6.3 Enviar y recibir con `livekit-client`

```ts
const encoder = new TextEncoder();
const decoder = new TextDecoder();

// ENVIAR un comando en agent-control
async function sendControl(room: Room, eventType: string, text?: string) {
  const envelope = {
    event_id: crypto.randomUUID(),
    event_type: eventType,
    session_id: liveavatarSessionId, // ver nota abajo
    source_event_id: null,
    ...(text !== undefined ? { text } : {})
  };
  await room.localParticipant.publishData(
    encoder.encode(JSON.stringify(envelope)),
    { reliable: true, topic: 'agent-control' }
  );
}

// RECIBIR eventos en agent-response
room.on(RoomEvent.DataReceived, (payload, _participant, _kind, topic) => {
  if (topic !== 'agent-response') return;
  const evt = JSON.parse(decoder.decode(payload));
  handleAgentResponse(evt); // ver §7
});
```

> ℹ️ **`session_id` en el envelope** es el **id de sesión de LiveAvatar**, no el
> `session_id` de AgentChat. Lo verás en los propios eventos de `agent-response`
> que llegan; cachéalo del primer evento recibido. El backend lo conoce como
> `liveavatar_session_id` pero **no lo expone** en la respuesta de `/start`
> (solo se necesita para el endpoint de transcript, §10).

---

## 7. Paso 4 — El bucle de conversación

El frontend orquesta todo. Bucle mínimo:

```ts
async function handleAgentResponse(evt: any) {
  switch (evt.event_type) {
    case 'user.transcription': {
      const userText = evt.text?.trim();
      if (!userText) return;
      // 1) pinta el turno del usuario en el chat
      appendMessage({ role: 'user', text: userText });

      // 2) interrumpe si el avatar estaba hablando (barge-in)
      if (avatarIsSpeaking) await sendControl(room, 'avatar.interrupt');

      // 3) pregunta al agente ai-parrot (§8) y haz que el avatar lo hable
      await askAgentAndSpeak(userText);
      break;
    }
    case 'avatar.speak_started':
      avatarIsSpeaking = true;
      break;
    case 'avatar.speak_ended':
      avatarIsSpeaking = false;
      break;
    case 'avatar.transcription.chunk':
      // sincroniza subtítulos palabra-a-palabra con el habla del avatar
      appendAvatarChunk(evt.text);
      break;
    case 'session.stopped':
      onSessionStopped(evt.end_reason);
      break;
  }
}
```

### 7.1 Streaming end-to-end (recomendado)

Para latencia baja, **no esperes la respuesta completa** del agente. Empareja
el `ask_stream` por-frase de ai-parrot (§8) con un `avatar.speak_text` por cada
frase, y deja que `avatar.transcription.chunk` sincronice la UI:

```ts
async function askAgentAndSpeak(userText: string) {
  for await (const sentence of streamAgentSentences(agentId, sessionId, userText)) {
    await sendControl(room, 'avatar.speak_text', sentence); // habla frase a frase
  }
}
```

> El avatar encola los `speak_text` y los habla en orden. Si el usuario
> interrumpe, manda `avatar.interrupt` para limpiar la cola antes del siguiente
> turno.

---

## 8. Paso 5 — Llamar al agente ai-parrot (texto)

El avatar es la boca; **el texto viene del agente de ai-parrot**. Usa los
endpoints de streaming existentes del servidor (`handlers/stream.py`):

```
POST /bots/{bot_id}/stream/sse      # Server-Sent Events
POST /bots/{bot_id}/stream/ndjson   # NDJSON
POST /bots/{bot_id}/stream/chunked  # chunked transfer
GET  /bots/{bot_id}/stream/ws       # WebSocket
```

Body mínimo: `{ "prompt": "<texto del usuario>", ... }` (el resto de claves se
pasan como kwargs a `ask_stream`).

Estrategia recomendada para FULL Mode: **agrupa los chunks del stream en frases
completas** (el avatar habla mejor frases que palabras sueltas) y emite un
`avatar.speak_text` por frase. Puedes reutilizar el flattener de frases del
backend conceptualmente — en el frontend basta con dividir por `.?!` cuando el
buffer crece:

```ts
async function* streamAgentSentences(botId: string, sessionId: string, prompt: string) {
  const res = await fetch(`/bots/${botId}/stream/ndjson`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ prompt, session_id: sessionId })
  });
  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    // separa por líneas NDJSON, extrae el texto, acumula hasta cerrar frase
    // ...emite cada frase completa con `yield sentence;`
  }
  if (buffer.trim()) yield buffer.trim();
}
```

> El `session_id` que pasas al agente **debe ser el mismo** que usaste en
> `/fullmode/start`, para que las salidas estructuradas (charts, data, canvas)
> que el agente emita lleguen al mismo canal de AgentChat que tu UI ya escucha.

---

## 9. Paso 6 — Parar la sesión (`/fullmode/stop`)

**Endpoint** (autenticado):

```
POST /api/v1/avatar/fullmode/{agent_id}/stop
```

Body: `{ "session_id": "abc-123" }`. **Respuesta: `204 No Content`**
(idempotente — un `session_id` desconocido/expirado también devuelve 204).

El backend hace `stop_session` + cancela el keep-alive + cierra el cliente HTTP.

```ts
export async function stopFullModeSession(agentId: string, sessionId: string): Promise<void> {
  await fetch(`/api/v1/avatar/fullmode/${agentId}/stop`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ session_id: sessionId })
  });
  // y desconecta la sala localmente
}
```

> 🧹 **Imprescindible** en el `onDestroy` del componente y en
> `beforeunload`/`pagehide`: una sesión sin `/stop` sigue quemando créditos
> hasta `max_session_duration`. Llama a `room.disconnect()` y a `/stop`.

```svelte
<script lang="ts">
  import { onDestroy } from 'svelte';
  onDestroy(async () => {
    room?.disconnect();
    await stopFullModeSession(agentId, sessionId);
  });
</script>
```

---

## 10. Endpoints de descubrimiento

Todos autenticados, todos read-only (proxy a la API de LiveAvatar con
`X-API-KEY` server-side). **No** requieren opt-in de avatar.

| Endpoint | Respuesta | Uso |
|---|---|---|
| `GET /api/v1/avatar/avatars?tenant_id=` | `{ "avatars": [...] }` | Poblar un selector de avatar |
| `GET /api/v1/avatar/voices?tenant_id=` | `{ "voices": [...] }` | Poblar un selector de voz |
| `GET /api/v1/avatar/session/{session_id}/transcript` | dict de transcript | Recuperar transcript de una sesión finalizada (`{session_id}` = id de LiveAvatar) |

```ts
export async function listAvatars(tenantId?: string) {
  const q = tenantId ? `?tenant_id=${encodeURIComponent(tenantId)}` : '';
  const res = await fetch(`/api/v1/avatar/avatars${q}`, { credentials: 'include' });
  const { avatars } = await res.json();
  return avatars;
}
```

> ⚠️ La **selección** de `avatar_id`/`voice_id`/`language`/`interactivity_type`
> que se usa al crear la sesión la resuelve el **backend** por tenant (env +
> override de BD vía `resolve_fullmode_config`). Hoy el `/start` **no acepta**
> avatar/voz en el body — usa la config del tenant. Estos listados sirven para
> UI de administración o para una futura ampliación del contrato de `/start`.

---

## 11. Arquitectura del módulo SvelteKit

Estructura sugerida (Svelte 5 + runas):

```
src/lib/avatar-fullmode/
├── api/
│   ├── avatarFullmode.ts     // start/stop + listados (§4, §9, §10)
│   └── agentStream.ts        // streamAgentSentences (§8)
├── livekit/
│   ├── room.ts               // connectAvatarRoom (§5)
│   └── dataChannel.ts        // sendControl + parser de agent-response (§6)
├── state/
│   └── conversation.svelte.ts // estado del bucle: turnos, avatarIsSpeaking, subtítulos
└── components/
    ├── AvatarStage.svelte    // <video> + overlay de estado
    ├── ConversationLog.svelte// historial de turnos + subtítulos
    └── AvatarSession.svelte   // orquesta: start → connect → loop → stop
```

**Máquina de estados de la sesión** (útil para la UI):

```
idle → starting (POST /start) → connecting (room.connect)
     → live (escuchando / hablando) → stopping (POST /stop) → idle
                                     ↘ error (403/409/503 o session.stopped)
```

`AvatarSession.svelte` (esqueleto):

```svelte
<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { startFullModeSession, stopFullModeSession } from '$lib/avatar-fullmode/api/avatarFullmode';
  import { connectAvatarRoom } from '$lib/avatar-fullmode/livekit/room';

  let { agentId, sessionId } = $props();
  let videoEl: HTMLVideoElement;
  let room: import('livekit-client').Room | undefined;
  let status = $state<'idle'|'starting'|'live'|'error'>('idle');

  onMount(async () => {
    try {
      status = 'starting';
      const session = await startFullModeSession(agentId, sessionId);
      room = await connectAvatarRoom(session, videoEl);
      wireDataChannel(room);   // §6 + §7
      status = 'live';
    } catch (e) {
      status = 'error';
    }
  });

  onDestroy(async () => {
    room?.disconnect();
    await stopFullModeSession(agentId, sessionId);
  });
</script>

<video bind:this={videoEl} autoplay playsinline></video>
{#if status === 'error'}<p>No se pudo iniciar el avatar.</p>{/if}
```

---

## 12. Seguridad, gating y manejo de errores

- **Autenticación**: todos los endpoints van detrás de `@is_authenticated()` +
  `@user_session()` (navigator_auth). Envía siempre `credentials: 'include'`.
- **Secretos**: el `/start` devuelve **solo** `livekit_url` +
  `livekit_client_token` (subscribe-only). Nunca recibirás `api_key` ni
  `session_token`. No intentes acuñar tokens de LiveKit en el cliente.
- **Opt-in por tenant** (`403`): FULL Mode es *default-deny*. El backend mira
  `LIVEAVATAR_FULLMODE_ENABLED_TENANTS` (lista separada por comas; `*` = todos).
  Si recibes 403, el tenant no está habilitado.
- **Una sesión por `session_id`** (`409`): el backend rechaza un segundo
  `/start` con el mismo `session_id` activo. Maneja el 409 reutilizando o
  regenerando el id.
- **`session.stopped`**: trátalo como teardown remoto. Según `end_reason`
  (`NO_CREDITS`, `MAX_DURATION_REACHED`, `IDLE_TIMEOUT`), muestra el mensaje
  adecuado y vuelve a `idle`. No asumas que `/stop` ya corrió: llámalo igual
  (es idempotente).
- **Créditos**: cada minuto de sesión consume STT+TTS+vídeo. Cierra siempre.

---

## 13. Checklist de implementación

- [ ] `POST /fullmode/start` con `session_id` (+ `tenant_id` si aplica), manejar 403/409/503.
- [ ] Conectar `livekit-client` con `livekit_url` + `livekit_client_token`, attach del `<video>`.

…(truncated)…
