---
type: Wiki Overview
title: Guía Técnica del Avatar (LiveAvatar Phase A) para Frontend
id: doc:docs-frontend-liveavatar-frontend-guide-md
tags:
- overview
timestamp: '2026-07-14T22:20:21+00:00'
summary: el **vídeo + audio** en el navegador.
---

# Guía Técnica del Avatar (LiveAvatar Phase A) para Frontend

**Audiencia**: equipo de Frontend (AgentChat, Svelte 5) que necesita mostrar un
**avatar parlante con lip-sync** que verbaliza la respuesta del agente, recibiendo
el **vídeo + audio** en el navegador.

**Ámbito**: FEAT-242 — *LiveAvatar — Phase A (avatar as the "mouth" of AgentChat)*.
El avatar es una **capa de presentación de voz/vídeo, NO un segundo cerebro**:
ai-parrot sigue resolviendo el turno completo (texto, STT del navegador o STT de
`AgentVoiceTalk`); el backend sintetiza la respuesta a PCM y la empuja al avatar.
El navegador es **únicamente espectador** (viewer) de una sala de LiveKit Cloud.

> Este documento está fundamentado en el código real fusionado en `dev`
> (rama `feat-242-liveavatar-phase-a-mouth`). Las rutas de archivo son
> **anclas de verificación** (anti-alucinación); el contrato semántico es lo
> que importa.
>
> Archivos fuente verificados (2026-06-18):
> - `packages/ai-parrot-server/src/parrot/handlers/avatar.py` — endpoints `start`/`stop`
> - `packages/ai-parrot-server/src/parrot/handlers/agent_voice.py` — `AgentVoiceTalk` (flag `avatar`)
> - `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/room_manager.py` — tokens LiveKit
> - `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/orchestrator.py` — orquestador (PCM push)
> - `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/models.py` — modelos Pydantic
> - `sdd/specs/liveavatar-phase-a-mouth.spec.md` — especificación (FEAT-242)
> - `sdd/tasks/completed/TASK-009-frontend-livekit-viewer.md` — contrato del viewer

---

## 0. Índice

1. [Modelo mental: el navegador es un viewer de LiveKit](#1-modelo-mental)
2. [Las piezas: 3 llamadas HTTP + 1 sala de LiveKit](#2-las-piezas)
3. [Aclaración importante sobre "WebSockets"](#3-aclaración-importante-sobre-websockets)
4. [Paso 1 — Arrancar la sesión de avatar (`/start`)](#4-paso-1--arrancar-la-sesión-de-avatar-start)
5. [Paso 2 — Unirse a la sala y pintar el vídeo (LiveKit)](#5-paso-2--unirse-a-la-sala-y-pintar-el-vídeo-livekit)
6. [Paso 3 — Conversar con el agente (`avatar: true`)](#6-paso-3--conversar-con-el-agente-avatar-true)
7. [Paso 4 — Cerrar la sesión (`/stop`)](#7-paso-4--cerrar-la-sesión-stop)
8. [Opt-in por tenant y manejo de errores](#8-opt-in-por-tenant-y-manejo-de-errores)
9. [Salidas estructuradas: siguen por el canal de siempre](#9-salidas-estructuradas)
10. [Ejemplo completo (TS, vanilla)](#10-ejemplo-completo-ts-vanilla)
11. [Componente Svelte 5 (referencia)](#11-componente-svelte-5-referencia)
12. [Checklist de integración Frontend](#12-checklist-de-integración-frontend)

---

## 1. Modelo mental

El avatar **NO** publica vídeo desde el navegador, ni el navegador empuja audio.
Todo lo contrario: el **backend** abre la sesión del avatar, lo hace unirse a
*nuestra* sala de LiveKit Cloud, y empuja el PCM de voz al media-server de
LiveAvatar. El avatar publica sus pistas de **vídeo + audio** en la sala. El
navegador simplemente **se suscribe** (subscribe-only) y las pinta.

```
                         ┌──────────────────────── BACKEND (ai-parrot) ───────────────────────┐
 [Browser]               │                                                                     │
   │  1) POST /avatar/{id}/start ─────────────────▶  AvatarSessionOrchestrator                 │
   │     { session_id, tenant_id }                     │  ├─ LiveAvatarClient  (crea/arranca)   │
   │  ◀── { livekit_url, client_token, session_id }    │  ├─ LiveKitRoomManager (mint tokens)   │
   │                                                   │  └─ AvatarWebSocket   (PCM push)       │
   │                                                   ▼                                        │
   │  2) join(livekit_url, client_token)  ───▶  Sala de LiveKit Cloud  ◀── avatar publica       │
   │     (suscribe vídeo + audio)                (room = session_id)      vídeo/audio lip-sync   │
   │  ◀═══════════════ pistas <video>/<audio> ═══════════════                                   │
   │                                                                                            │
   │  3) POST /voice/{id}  { avatar:true, query, tenant_id }  ─▶ ask_stream → Supertonic PCM ───┘
   │  ◀── { response, output, data, media, ... }   (texto/estructurado para la UI)
   │                                                  el avatar HABLA por la sala
   │  4) POST /avatar/{id}/stop  { session_id }  ─▶ stop_session + cierre
   └──
```

**Consecuencias prácticas:**

- El navegador usa la librería **`livekit-client`** (JS) como espectador. No
  necesitas saber nada de WebRTC a bajo nivel; el SDK lo gestiona.
- El navegador **solo recibe `client_token`** (subscribe-only). El `agent_token`
  y la WS del media-server del avatar **nunca** salen del backend.
- La **sala** se identifica con el **`session_id`** de AgentChat (lo compartes
  entre el chat y el avatar).
- El avatar entra a la sala como un participante remoto con identidad
  **`avatar-agent`**. Tú te suscribes a sus pistas remotas.
- Las **salidas estructuradas** (charts, data, canvas) **no** viajan por LiveKit;
  siguen llegando por el envelope de `/voice` (o por la WS de AgentChat de
  siempre). LiveKit es **solo cara y voz**.

---

## 2. Las piezas

Para mostrar un avatar parlante necesitas orquestar **3 llamadas HTTP** y **1
conexión de sala** de LiveKit:

| # | Acción | Método / Ruta | Quién |
|---|--------|---------------|-------|
| 1 | Arrancar sesión de avatar | `POST /api/v1/agents/avatar/{agent_id}/start` | Frontend |
| 2 | Unirse a la sala y pintar vídeo | `livekit-client` → `room.connect(url, token)` | Frontend |
| 3 | Conversar (el agente responde y el avatar habla) | `POST /api/v1/agents/voice/{agent_id}` con `avatar: true` | Frontend |
| 4 | Cerrar sesión | `POST /api/v1/agents/avatar/{agent_id}/stop` | Frontend |

Las rutas `start`/`stop` las sirve `AvatarSessionView`, una vista **autenticada**
(`@is_authenticated()` + `@user_session()`), igual que `AgentTalk`/`AgentVoiceTalk`.
Envía las **mismas credenciales** (cookie de sesión / `Authorization`) que ya usas
para el chat.

---

## 3. Aclaración importante sobre "WebSockets"

En Phase A **no** hay un WebSocket propio de ai-parrot para recibir el vídeo del
avatar. El vídeo/audio llega **por la sala de LiveKit** (que internamente usa
WebRTC con señalización por WebSocket, pero eso lo abstrae `livekit-client`).

Hay tres "canales" que conviene no confundir:

| Canal | Para qué | ¿Lo tocas en Phase A? |
|-------|----------|------------------------|
| **Sala de LiveKit** (`livekit-client`) | Recibir **vídeo + audio** del avatar | **Sí** — es el corazón del viewer |
| **REST `/voice`** (`AgentVoiceTalk`) | Enviar el turno y recibir el envelope (texto + estructurado) | **Sí** |
| **WS de streaming de AgentChat** (`StreamHandler`, `/bots/{bot_id}/stream/ws`) | Streaming de tokens de texto del chat | **Opcional** — si ya lo usas para el chat, sigue igual |

> El media-server WebSocket de LiveAvatar (`ws_url`) por el que se empuja el PCM
> es **estrictamente server-side**. El frontend **no** se conecta a él jamás.

---

## 4. Paso 1 — Arrancar la sesión de avatar (`/start`)

| | |
|---|---|
| **Método** | `POST` |
| **Ruta** | `/api/v1/agents/avatar/{agent_id}/start` |
| **Auth** | Requerida (igual que el chat) |
| **Content-Type** | `application/json` |

**Request body:**

```jsonc
{
  "session_id": "abc-123",   // OBLIGATORIO. El mismo session_id de AgentChat.
  "tenant_id": "acme"        // Opcional. Para el opt-in por tenant.
}
```

**Response 200 (solo credenciales de viewer):**

```jsonc
{
  "livekit_url": "wss://<project>.livekit.cloud",
  "client_token": "<JWT subscribe-only>",
  "session_id": "abc-123"
}
```

> **NO esperes** `agent_token` ni `ws_url` ni `session_token` en la respuesta:
> son secretos de servidor y **nunca** se serializan al cliente. Si tu código
> los busca, está mal.

**Errores típicos:**

- `400` — falta `session_id`.
- `403` — el tenant no tiene el avatar habilitado (opt-in apagado). Cae a
  chat/voz normal sin avatar.
- `503` — falta el stack (`ai-parrot-integrations[liveavatar]`) o faltan las
  variables de entorno `LIVEAVATAR_*` / `LIVEKIT_*` en el servidor.

---

## 5. Paso 2 — Unirse a la sala y pintar el vídeo (LiveKit)

Instala el SDK del navegador:

```bash
npm install livekit-client
```

Con `{ livekit_url, client_token }` del paso 1, te conectas a la sala y te
suscribes a las pistas del avatar (participante remoto `avatar-agent`):

```ts
import {
  Room,
  RoomEvent,
  RemoteTrack,
  RemoteTrackPublication,
  RemoteParticipant,
  Track,
} from "livekit-client";

async function joinAvatarRoom(
  livekitUrl: string,
  clientToken: string,
  videoEl: HTMLVideoElement,
  audioEl: HTMLAudioElement,
): Promise<Room> {
  const room = new Room({ adaptiveStream: true, dynacast: true });

  // Suscripción a pistas remotas (vídeo y audio del avatar).
  room.on(
    RoomEvent.TrackSubscribed,
    (
      track: RemoteTrack,
      _pub: RemoteTrackPublication,
      _participant: RemoteParticipant,
    ) => {
      if (track.kind === Track.Kind.Video) {
        track.attach(videoEl);   // pinta el vídeo del avatar
      } else if (track.kind === Track.Kind.Audio) {
        track.attach(audioEl);   // reproduce la voz del avatar
      }
    },
  );

  room.on(RoomEvent.TrackUnsubscribed, (track) => track.detach());

  room.on(RoomEvent.Disconnected, () => {
    console.info("[avatar] desconectado de la sala");
  });

  await room.connect(livekitUrl, clientToken);
  return room;
}
```

Notas:

- El token es **subscribe-only**: el navegador **no puede** publicar, solo
  recibir. Es seguro exponerlo al cliente.
- El elemento `<audio>` puede requerir interacción del usuario (autoplay): pinta
  el avatar tras un click/tap, o muestra un botón "Activar sonido".
- La pista de audio que LiveKit reproduce es **la voz del avatar** (lip-sync). No
  uses además el `audio_base64` del envelope de `/voice` para reproducir: causaría
  doble audio. (Ver §6.)

---

## 6. Paso 3 — Conversar con el agente (`avatar: true`)

El turno de conversación se hace contra el endpoint de voz **de siempre**
(`AgentVoiceTalk`), añadiendo el flag `avatar: true`. El backend resuelve el turno
y, en paralelo, hace que **el avatar lo diga en voz alta por la sala**.

| | |
|---|---|
| **Método** | `POST` |
| **Ruta** | `/api/v1/agents/voice/{agent_id}` |
| **Body** | multipart (nota de voz) **o** JSON/form con `query` de texto |

Campos relevantes para el avatar (se leen en `_read_voice_options`):

| Campo | Tipo | Efecto |
|-------|------|--------|
| `avatar` | `true` \| `"true"` | Activa el modo avatar para ese turno |
| `tenant_id` | `string` | Opt-in por tenant (debe coincidir con el del `/start`) |
| `query` | `string` | El texto del turno (si no envías nota de voz) |

**Importante — comportamiento en Phase A:**

- El flag `avatar:true` pasa por la **compuerta de opt-in** del tenant. Si está
  apagado, el backend cae silenciosamente a la ruta de texto/voz normal.
- El **PCM lo empuja el backend** al avatar (vía la sesión arrancada en el `/start`).
  El navegador **no** recibe el audio del agente por este endpoint para reproducirlo;
  lo **oye por la sala de LiveKit**.
- El envelope de respuesta es el **mismo de `AgentTalk`/`AgentVoiceTalk`**:
  `response`, `output`, `data`, `media`, etc. Úsalo para pintar texto y
  artefactos estructurados, **no** para reproducir audio del avatar.

```ts
async function sendAvatarTurn(
  agentId: string,
  sessionId: string,
  query: string,
  tenantId?: string,
): Promise<any> {
  const form = new FormData();
  form.append("query", query);
  form.append("avatar", "true");
  form.append("session_id", sessionId);
  if (tenantId) form.append("tenant_id", tenantId);

  const res = await fetch(`/api/v1/agents/voice/${agentId}`, {
    method: "POST",
    body: form,
    credentials: "include", // misma auth que el chat
  });
  if (!res.ok) throw new Error(`voice turn failed: ${res.status}`);
  return res.json(); // envelope de AgentTalk (texto + estructurado)
}
```

> Si el endpoint te devuelve `audio_base64` (puede ocurrir cuando enviaste una
> nota de voz), **ignóralo en modo avatar** para no duplicar la voz: el avatar
> ya está hablando por la sala.

---

## 7. Paso 4 — Cerrar la sesión (`/stop`)

Cierra **siempre** la sesión al terminar (cerrar el chat, navegar fuera,
`beforeunload`). El backend para la sesión de LiveAvatar, cancela el keep-alive y
libera el cliente HTTP.

| | |
|---|---|
| **Método** | `POST` |
| **Ruta** | `/api/v1/agents/avatar/{agent_id}/stop` |
| **Body** | `{ "session_id": "abc-123" }` |
| **Response** | `204 No Content` (idempotente: sesión desconocida → también `204`) |

> El `/stop` se identifica **solo por `session_id`**. El `session_token` es un
> secreto de servidor y **no** se acepta desde el cliente.

```ts
async function stopAvatar(agentId: string, sessionId: string): Promise<void> {
  await fetch(`/api/v1/agents/avatar/${agentId}/stop`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId }),
    credentials: "include",
  });
}
```

Y en el navegador, desconéctate también de la sala:

```ts
await room.disconnect();
```

Como red de seguridad, el backend tiene un `max_session_duration`
(`LIVEAVATAR_MAX_SESSION_DURATION`) que autotermina sesiones abandonadas, pero
**no dependas de él**: llama a `/stop` explícitamente.

---

## 8. Opt-in por tenant y manejo de errores

El avatar es **opt-in por programa/tenant**. Diseña la UI para que sea
**avatar-aware**:

- Antes de mostrar el botón "Hablar con avatar", o al recibir `403` del `/start`,
  **oculta** el viewer y comporta el chat como texto/voz normal.
- `session_id` **debe ser el mismo** en `/start`, en el turno `/voice` y en `/stop`.
- Maneja `503` (stack no instalado / env faltante) mostrando un fallback elegante
  ("avatar no disponible ahora mismo"), nunca un error rojo.

| Código | Significado | Acción de UI sugerida |
|--------|-------------|------------------------|
| `200` | Sesión creada | Conéctate a la sala |
| `400` | Falta `session_id` | Bug del cliente: corrige el payload |
| `403` | Tenant sin opt-in | Oculta el avatar; usa chat/voz normal |
| `503` | Stack/env no disponible | Fallback "avatar no disponible" |

---

## 9. Salidas estructuradas

**No** enrutes charts/data/canvas por LiveKit. Las salidas estructuradas siguen
llegando exactamente como hoy:

- En el **envelope** de la respuesta de `/voice` (`output`, `data`, `media`,
  `artifact_id`, …), o
- Por la **WS de streaming de AgentChat** (`StreamHandler`) si ya la usas.

LiveKit transporta **solo** la cara y la voz del avatar. La regla de oro:
**el usuario *oye* el `response` (texto hablable) por el avatar y *ve* las
tablas/gráficos/datos en la UI** (como siempre).

---

## 10. Ejemplo completo (TS, vanilla)

```ts
import { Room, RoomEvent, Track } from "livekit-client";

interface StartResponse {
  livekit_url: string;
  client_token: string;
  session_id: string;
}

export class AvatarSession {
  private room: Room | null = null;

  constructor(
    private agentId: string,
    private sessionId: string,
    private videoEl: HTMLVideoElement,
    private audioEl: HTMLAudioElement,
    private tenantId?: string,
  ) {}

  /** Paso 1 + 2: arranca la sesión y se une a la sala. */
  async start(): Promise<void> {
    const res = await fetch(`/api/v1/agents/avatar/${this.agentId}/start`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: this.sessionId,
        tenant_id: this.tenantId,
      }),
      credentials: "include",
    });

    if (res.status === 403) {
      throw new AvatarDisabledError("avatar no habilitado para este tenant");
    }
    if (!res.ok) {
      throw new Error(`avatar start failed: ${res.status}`);
    }

    const { livekit_url, client_token }: StartResponse = await res.json();

    this.room = new Room({ adaptiveStream: true, dynacast: true });
    this.room.on(RoomEvent.TrackSubscribed, (track) => {
      if (track.kind === Track.Kind.Video) track.attach(this.videoEl);
      else if (track.kind === Track.Kind.Audio) track.attach(this.audioEl);
    });
    this.room.on(RoomEvent.TrackUnsubscribed, (track) => track.detach());

    await this.room.connect(livekit_url, client_token);
  }

  /** Paso 3: envía un turno; el avatar lo dice por la sala. */
  async ask(query: string): Promise<any> {
    const form = new FormData();
    form.append("query", query);
    form.append("avatar", "true");
    form.append("session_id", this.sessionId);
    if (this.tenantId) form.append("tenant_id", this.tenantId);

    const res = await fetch(`/api/v1/agents/voice/${this.agentId}`, {
      method: "POST",
      body: form,
      credentials: "include",
    });
    if (!res.ok) throw new Error(`voice turn failed: ${res.status}`);
    const envelope = await res.json();
    // Pinta envelope.response / envelope.output / envelope.data en la UI.
    // NO reproduzcas envelope.audio_base64 en modo avatar (doble audio).
    return envelope;
  }

  /** Paso 4: cierra todo. */
  async stop(): Promise<void> {
    try {
      await this.room?.disconnect();
    } finally {
      this.room = null;
      await fetch(`/api/v1/agents/avatar/${this.agentId}/stop`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: this.sessionId }),
        credentials: "include",
      });
    }
  }
}

class AvatarDisabledError extends Error {}
```

Uso:

```ts
const session = new AvatarSession(
  "concierge",
  crypto.randomUUID(),            // o el session_id de AgentChat
  document.querySelector("#avatar-video")!,
  document.querySelector("#avatar-audio")!,
  "acme",
);

try {
  await session.start();
  const reply = await session.ask("¿Cuál fue el revenue del Q1?");
  renderEnvelope(reply); // tu render de texto/estructurado de siempre
} catch (e) {
  if (e instanceof AvatarDisabledError) showTextOnlyChat();
  else showAvatarUnavailable();
}

window.addEventListener("beforeunload", () => { session.stop(); });
```

---

## 11. Componente Svelte 5 (referencia)

> Este es el componente que TASK-009 espera en el repo de AgentChat (Svelte 5),
> usando *runes*. Es una referencia — adáptalo a tus stores/estilos.

```svelte
<script lang="ts">
  import { Room, RoomEvent, Track } from "livekit-client";
  import { onDestroy } from "svelte";

  // Props (Svelte 5 runes)
  let {
    agentId,
    sessionId,
    tenantId = undefined,
    enabled = true, // opt-in aware: false → no inicializa el viewer
  }: {
    agentId: string;
    sessionId: string;
    tenantId?: string;
    enabled?: boolean;
  } = $props();

  let videoEl = $state<HTMLVideoElement | null>(null);
  let audioEl = $state<HTMLAudioElement | null>(null);
  let status = $state<"idle" | "connecting" | "live" | "disabled" | "error">("idle");
  let room: Room | null = null;

  async function start() {
    if (!enabled) { status = "disabled"; return; }
    status = "connecting";

    const res = await fetch(`/api/v1/agents/avatar/${agentId}/start`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, tenant_id: tenantId }),
      credentials: "include",
    });

    if (res.status === 403) { status = "disabled"; return; } // tenant sin opt-in
    if (!res.ok) { status = "error"; return; }

    const { livekit_url, client_token } = await res.json();

    room = new Room({ adaptiveStream: true, dynacast: true });
    room.on(RoomEvent.TrackSubscribed, (track) => {
      if (track.kind === Track.Kind.Video && videoEl) track.attach(videoEl);
      else if (track.kind === Track.Kind.Audio && audioEl) track.attach(audioEl);
    });
    room.on(RoomEvent.TrackUnsubscribed, (track) => track.detach());

    await room.connect(livekit_url, client_token);
    status = "live";
  }

  async function stop() {
    try { await room?.disconnect(); }
    finally {
      room = null;
      await fetch(`/api/v1/agents/avatar/${agentId}/stop`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId }),
        credentials: "include",
      });
    }
  }

  // Arranca cuando el viewer se monta y está habilitado
  $effect(() => {
    if (enabled && status === "idle") start();
  });

  onDestroy(() => { stop(); });
</script>

{#if status !== "disabled"}
  <div class="avatar-viewer" data-status={status}>
    <!-- svelte-ignore a11y_media_has_caption -->
    <video bind:this={videoEl} autoplay playsinline muted></video>
    <audio bind:this={audioEl} autoplay></audio>
    {#if status === "connecting"}<span class="hint">Conectando avatar…</span>{/if}
    {#if status === "error"}<span class="hint">Avatar no disponible</span>{/if}
  </div>
{/if}
```

> El envío del turno (`avatar:true` contra `/voice`) lo hace tu lógica de chat
> existente; este componente es **solo el viewer**. Comparte el `sessionId` entre
> ambos.

---

## 12. Checklist de integración Frontend

- [ ] Instalar `livekit-client` y fijar la versión.
- [ ] Generar/compartir un único `session_id` entre chat, `/start`, `/voice` y `/stop`.
- [ ] `POST /avatar/{id}/start` → guardar `livekit_url` + `client_token`.
- [ ] **No** buscar `agent_token` / `ws_url` / `session_token` en la respuesta.
- [ ] `room.connect(url, token)` y `attach()` de las pistas **vídeo** y **audio**.
- [ ] Gestionar autoplay del `<audio>` (gesto del usuario si hace falta).
- [ ] Enviar el turno a `/voice/{id}` con `avatar:true` + `session_id` (+ `tenant_id`).
- [ ] **No** reproducir `audio_base64` del envelope en modo avatar (doble audio).
- [ ] Pintar `response`/`output`/`data`/`media` como en el chat normal.
- [ ] Ser **opt-in aware**: ocultar el viewer ante `403`; degradar a chat/voz.
- [ ] `POST /avatar/{id}/stop` + `room.disconnect()` al cerrar / `beforeunload`.
- [ ] Fallback elegante ante `503` (stack/env no disponible).
- [ ] Enviar las mismas credenciales de auth que el resto de AgentChat (`credentials: "include"`).

---

## Apéndice — Resumen de contratos

```jsonc
// POST /api/v1/agents/avatar/{agent_id}/start   (auth requerida)
// body:
{ "session_id": "abc-123", "tenant_id": "acme" }
// 200:
{ "livekit_url": "wss://<project>.livekit.cloud",
  "client_token": "<JWT subscribe-only>",
  "session_id": "abc-123" }
// 400 falta session_id · 403 tenant sin opt-in · 503 stack/env no disponible

// POST /api/v1/agents/voice/{agent_id}          (auth requerida)
// form/multipart: query=<texto> | <nota de voz>, avatar=true, session_id=abc-123, tenant_id=acme
// 200: envelope de AgentTalk { response, output, data, media, ... }

// POST /api/v1/agents/avatar/{agent_id}/stop    (auth requerida)
// body:
{ "session_id": "abc-123" }
// 204 (idempotente)
```

**Identidades de LiveKit** (informativo):
- Sala (`room`) = `session_id`.
- Avatar (participante remoto que publica vídeo/audio) = identidad `avatar-agent`.
- Viewer (tu navegador) = identidad `agent_id`, grants **subscribe-only**.

---

## Historial de revisión

| Versión | Fecha | Autor | Cambio |
|---------|-------|-------|--------|
| 1.0 | 2026-06-18 | Claude (FEAT-242) | Guía inicial de integración frontend del avatar (Phase A) |
