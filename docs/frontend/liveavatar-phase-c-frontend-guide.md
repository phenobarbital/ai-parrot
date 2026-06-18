# Guía Técnica del Avatar Voz-Nativo (LiveAvatar Phase C) para Frontend

**Audiencia**: equipo de Frontend (AgentChat, Svelte 5) que necesita una
**conversación de voz fluida con avatar parlante** — el usuario habla por el
micrófono, el agente responde con voz y cara (lip-sync), y los **artefactos
estructurados** (charts, data, canvas) siguen pintándose en la UI.

**Ámbito**: FEAT-243 — *LiveAvatar — Phase C (voice-native hybrid, ai-parrot
as the brain)*. A diferencia de Phase A, aquí el navegador **publica su
micrófono** en la sala y la conversación es **voz-nativa**: el *turn-taking*
(STT + VAD + detección de turno + barge-in) lo gestiona un **worker de LiveKit
Agents**, no tu lógica de chat. El "cerebro" sigue siendo ai-parrot: el worker
sobrescribe `llm_node` para llamar a `ask_stream()`. El texto hablable → TTS →
avatar; las salidas estructuradas → canal WS de AgentChat (mismo `session_id`).

---

> ⚠️ **Estado de esta guía (2026-06-18).** El backend de Phase C (FEAT-243) está
> **en implementación** (tareas `pending`). Esta guía está fundamentada en:
> - El spec aprobado `sdd/specs/liveavatar-phase-c-voice-native.spec.md` (FEAT-243).
> - El código **ya fusionado** de Phase A (FEAT-242) que Phase C **reutiliza**:
>   `room_manager.py`, `client.py`, `speakable.py`, `handlers/user.py`.
>
> Las partes marcadas **`[PROPUESTA — confirmar con backend]`** describen el
> contrato HTTP/dispatch que FEAT-243 todavía debe materializar (ver
> [§11 Contratos abiertos](#11-contratos-abiertos-p4--p5--dispatch)). El modelo
> mental, el flujo de LiveKit (publicar mic + suscribir avatar) y el consumo de
> salidas estructuradas por la WS **sí** están anclados en código real y son
> estables.
>
> Archivos fuente verificados (2026-06-18):
> - `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/room_manager.py` — `mint_room_tokens` (grants)
> - `packages/ai-parrot-server/src/parrot/handlers/avatar.py` — `/start` `/stop` (Phase A)
> - `packages/ai-parrot-server/src/parrot/handlers/user.py:357` — `UserSocketManager.broadcast_to_channel`
> - `packages/ai-parrot/src/parrot/human/channels/web.py` — patrón canal = `session_id`
> - `sdd/specs/liveavatar-phase-c-voice-native.spec.md` — especificación (FEAT-243)

---

## 0. Índice

1. [Modelo mental: voz-nativo, el navegador publica micrófono](#1-modelo-mental)
2. [Phase C vs Phase A — qué cambia en el frontend](#2-phase-c-vs-phase-a)
3. [Las piezas: 1 arranque de sesión + 1 sala LiveKit + 1 canal WS](#3-las-piezas)
4. [Paso 1 — Arrancar la sesión voz-nativa](#4-paso-1--arrancar-la-sesión-voz-nativa)
5. [Paso 2 — Unirse a la sala, publicar mic y pintar el avatar](#5-paso-2--unirse-a-la-sala-publicar-mic-y-pintar-el-avatar)
6. [Paso 3 — Recibir salidas estructuradas por la WS de AgentChat](#6-paso-3--salidas-estructuradas-por-la-ws)
7. [Estados de turno, barge-in y "pensando"](#7-estados-de-turno-barge-in-y-pensando)
8. [Paso 4 — Cerrar la sesión](#8-paso-4--cerrar-la-sesión)
9. [Opt-in por tenant y manejo de errores](#9-opt-in-por-tenant-y-errores)
10. [Ejemplo completo (TS, vanilla)](#10-ejemplo-completo-ts-vanilla)
11. [Contratos abiertos (P4 / P5 / dispatch)](#11-contratos-abiertos-p4--p5--dispatch)
12. [Componente Svelte 5 (referencia)](#12-componente-svelte-5-referencia)
13. [Checklist de integración Frontend](#13-checklist-de-integración-frontend)
14. [Apéndice — Resumen de contratos](#apéndice--resumen-de-contratos)

---

## 1. Modelo mental

En Phase C la conversación es **voz-nativa y continua**. No hay un POST por turno:
el usuario simplemente **habla**, y un **worker de LiveKit Agents** (server-side)
escucha el audio del navegador, detecta inicio/fin de turno, interrupciones
(barge-in) y dispara la respuesta. Ese worker **no usa el LLM de LiveKit**:
sobrescribe `llm_node` para llamar a **ai-parrot** (`ask_stream`). La respuesta se
**bifurca**:

- **texto hablable** → `SpeakableFlattener` → TTS de LiveKit → el **avatar lo dice**;
- **salidas estructuradas** (charts / data / canvas / `tool_calls`) → un
  **OutputBridge** las publica en el **canal WS de AgentChat** con clave
  `session_id` (la misma conversación que el avatar está hablando).

```
                          ┌──────────────── BACKEND (ai-parrot) ─────────────────┐
 [Browser]                │                                                       │
   │ 1) POST .../start  ──┼─▶ mint token (PUBLISH+SUBSCRIBE) · dispatch worker    │
   │    {session_id,      │      con job metadata {session_id, agent_name,        │
   │     tenant_id}       │      tenant_id, ws_url}                               │
   │ ◀── {livekit_url, token, session_id}                                         │
   │                      │                                                       │
   │ 2) join(url, token)  │   LiveKit Cloud room (room = session_id)              │
   │  ── publica MIC ────▶│──▶ AgentSession (STT · VAD · turn-detect · barge-in)  │
   │  ◀═ vídeo+audio ═════│◀── avatar publica cara/voz   │                        │
   │     del avatar       │                       llm_node override (LiveAvatarAgent)
   │                      │                              │                        │
   │                      │            ai-parrot ask_stream(agent, q, session_id, tenant)
   │                      │             │                         │               │
   │                      │     texto hablable              salidas estructuradas │
   │                      │     →TTS→ avatar HABLA           → OutputBridge        │
   │                      │                                       │               │
   │ 3) WS /ws/user  ◀════╪═══ broadcast_to_channel(session_id) ◀─┘               │
   │    (subscribe        │                                                       │
   │     al canal         │                                                       │
   │     session_id)      │                                                       │
   │ 4) POST .../stop  ───┼─▶ teardown worker + sesión                            │
   └──                    └───────────────────────────────────────────────────────┘
```

**Consecuencias prácticas:**

- El navegador usa **`livekit-client`** como **participante con publicación de
  audio** (mic), y a la vez **suscriptor** del vídeo/audio del avatar. Es
  publish **de audio** + subscribe; **no** publica vídeo.
- **No envías el turno por REST.** No hay `POST /voice` por cada frase. El
  usuario habla y el worker se encarga del turno. Tu UI **escucha** resultados,
  no los pide.
- Las **salidas estructuradas llegan por la WS de AgentChat** (`/ws/user`),
  suscribiéndote al **canal = `session_id`**. **No** llegan en un envelope de
  respuesta REST (en Phase C no hay tal respuesta por turno).
- El **`session_id` es el pegamento**: nombra la sala de LiveKit *y* el canal WS
  de salidas estructuradas. Compártelo entre las tres patas (start, sala, WS).
- **Barge-in es nativo**: si el usuario habla mientras el avatar habla, LiveKit
  interrumpe al avatar automáticamente. No tienes que implementar el corte.

---

## 2. Phase C vs Phase A

Si ya integraste Phase A (FEAT-242, ver `liveavatar-frontend-guide.md`), estos
son los cambios. **No reutilices el flujo de turno de Phase A en Phase C.**

| Aspecto | Phase A (FEAT-242) | Phase C (FEAT-243) |
|---|---|---|
| Rol del navegador | **Solo viewer** (subscribe-only) | **Publica mic** + suscribe avatar |
| Token de sala | `client_token` **subscribe-only** | token **publish(audio)+subscribe** ⚠️ |
| Turn-taking | Manual: tu lógica de chat dispara cada turno | **Nativo**: worker LiveKit (STT/VAD/turn/barge-in) |
| Envío del turno | `POST /voice` con `avatar:true` por turno | **Ninguno** — el usuario habla; el worker escucha |
| STT | STT del navegador o de `AgentVoiceTalk` | **STT del pipeline LiveKit** (Deepgram) |
| Barge-in | No nativo | **Nativo** (VAD + turn-detection) |
| Salidas estructuradas | En el **envelope REST** de `/voice` | Por la **WS de AgentChat** (`broadcast_to_channel`) |
| Audio del agente | PCM empujado por backend (Supertonic) | **TTS de LiveKit** por la sala |

> **Regla de oro (igual que Phase A)**: el usuario **oye** el texto hablable por
> el avatar y **ve** las tablas/gráficos/datos en la UI. LiveKit transporta solo
> cara y voz; lo estructurado va por la WS.

---

## 3. Las piezas

Para una conversación voz-nativa con avatar necesitas orquestar **3 canales**:

| # | Acción | Cómo | Quién |
|---|--------|------|-------|
| 1 | Arrancar la sesión voz-nativa | `POST .../start` → token + dispatch del worker | Frontend |
| 2 | Unirse a la sala, **publicar mic**, pintar avatar | `livekit-client` → `room.connect` + `setMicrophoneEnabled(true)` | Frontend |
| 3 | Recibir salidas estructuradas | WS `/ws/user` → `subscribe` al canal `session_id` | Frontend |
| 4 | Cerrar la sesión | `POST .../stop` + `room.disconnect()` + cerrar WS | Frontend |

La diferencia estructural con Phase A: **desaparece el POST de turno** y
**aparece la suscripción WS** como vía de salidas estructuradas.

---

## 4. Paso 1 — Arrancar la sesión voz-nativa

**`[PROPUESTA — confirmar con backend]`** El spec FEAT-243 define la inyección de
contexto al worker vía **LiveKit job metadata** (`AvatarJobMetadata`:
`ws_url`, `session_id`, `agent_name`, `tenant_id`), pero **no fija aún el
endpoint HTTP** que el frontend llama para (a) acuñar el token de sala y (b)
**despachar el worker** a la sala con esa metadata. El contrato natural —
homólogo al `/start` de Phase A — es:

| | |
|---|---|
| **Método** | `POST` |
| **Ruta** | `/api/v1/agents/avatar/{agent_id}/start` *(o un `.../voice-native/start` dedicado — a confirmar)* |
| **Auth** | Requerida (cookie de sesión / `Authorization`, igual que el chat) |
| **Content-Type** | `application/json` |

**Request body:**

```jsonc
{
  "session_id": "abc-123",   // OBLIGATORIO. Clave compartida: sala LiveKit + canal WS.
  "tenant_id": "acme"        // Opcional. Opt-in por tenant.
}
```

**Response 200 (propuesta):**

```jsonc
{
  "livekit_url": "wss://<project>.livekit.cloud",
  "token": "<JWT publish(audio)+subscribe>",   // ⚠️ debe permitir publicar audio
  "session_id": "abc-123"
}
```

> ⚠️ **Gap de token (crítico para backend).** El `LiveKitRoomManager.mint_room_tokens`
> de Phase A acuña el `client_token` con **`can_publish=False`** (subscribe-only,
> pensado para un viewer). En Phase C el navegador **debe publicar su micrófono**,
> así que necesita un token con `can_publish=True` (al menos para audio).
> **FEAT-243 debe acuñar un token publish-capaz para el navegador** (o añadir una
> variante a `mint_room_tokens`). Como frontend, **asume que recibirás un token
> que te permite publicar audio**; si al hacer `setMicrophoneEnabled(true)`
> LiveKit lanza un error de permisos, es este gap del backend, no tu bug.

Además del token, el `/start` debe **despachar el worker de LiveKit Agents** a la
sala con la job metadata (`session_id`, `agent_name`, `tenant_id`, `ws_url`).
Eso es responsabilidad del backend; el frontend **no** ve ni toca esa metadata.

**Errores esperados** (homólogos a Phase A):

| Código | Significado | Acción de UI |
|--------|-------------|--------------|
| `200` | Sesión + worker arrancados | Conéctate a la sala y publica mic |
| `400` | Falta `session_id` | Bug del cliente: corrige el payload |
| `403` | Tenant sin opt-in de avatar | Oculta el avatar; degrada a chat de texto/voz |
| `503` | Stack/env no disponible (`ai-parrot-integrations[liveavatar]` / `livekit-agents` / env) | Fallback "avatar no disponible" |

---

## 5. Paso 2 — Unirse a la sala, publicar mic y pintar el avatar

Instala el SDK:

```bash
npm install livekit-client
```

Con `{ livekit_url, token }` del paso 1, te conectas, **habilitas el micrófono**
(publicación de audio) y te suscribes a las pistas del avatar (participante
remoto `avatar-agent`):

```ts
import {
  Room,
  RoomEvent,
  RemoteTrack,
  RemoteTrackPublication,
  RemoteParticipant,
  Track,
} from "livekit-client";

async function joinVoiceNativeRoom(
  livekitUrl: string,
  token: string,
  videoEl: HTMLVideoElement,
  audioEl: HTMLAudioElement,
): Promise<Room> {
  const room = new Room({ adaptiveStream: true, dynacast: true });

  // Suscripción a las pistas REMOTAS del avatar (vídeo + voz TTS).
  room.on(
    RoomEvent.TrackSubscribed,
    (
      track: RemoteTrack,
      _pub: RemoteTrackPublication,
      participant: RemoteParticipant,
    ) => {
      // El avatar entra como participante remoto "avatar-agent".
      if (track.kind === Track.Kind.Video) {
        track.attach(videoEl); // pinta la cara del avatar
      } else if (track.kind === Track.Kind.Audio) {
        track.attach(audioEl); // reproduce la voz (TTS) del avatar
      }
    },
  );
  room.on(RoomEvent.TrackUnsubscribed, (track) => track.detach());

  await room.connect(livekitUrl, token);

  // ▶ PUBLICA EL MICRÓFONO. Esto es lo nuevo de Phase C: el worker server-side
  //   escucha este audio para STT/VAD/turn-detection. Requiere un token con
  //   can_publish=true (ver el gap en §4).
  await room.localParticipant.setMicrophoneEnabled(true);

  return room;
}
```

Notas clave:

- `setMicrophoneEnabled(true)` dispara el permiso de micrófono del navegador.
  Hazlo **tras un gesto del usuario** (click en "Empezar a hablar") para no chocar
  con las políticas de autoplay/permisos.
- **No publiques vídeo** (`setCameraEnabled` no se usa): el avatar es la cara, no
  tú. Solo audio sube; vídeo+audio del avatar baja.
- El `<audio>` del avatar también puede requerir gesto del usuario para sonar.
  Cubre ambas cosas con el mismo botón de inicio.
- El **mute** del usuario = `room.localParticipant.setMicrophoneEnabled(false)`.
  Útil para un botón "silenciar micro".

---

## 6. Paso 3 — Salidas estructuradas por la WS

En Phase C **no hay envelope REST por turno**. Las salidas estructuradas
(charts, data, canvas, `tool_calls`) llegan por la **WebSocket de AgentChat**
(`UserSocketManager`, ruta por defecto **`/ws/user`**), cuando el backend hace
`broadcast_to_channel(session_id, StructuredOutputMessage)`.

El `UserSocketManager` **solo entrega a suscriptores del canal** (si no hay
nadie suscrito, el mensaje se descarta — **no hay buffer**). Por eso debes
**suscribirte al canal `session_id` ANTES de empezar a hablar**.

**Protocolo de la WS** (verificado en `handlers/user.py`):

```ts
// 1) Conecta
const ws = new WebSocket(`${wsBase}/ws/user`);

// 2) Autentícate (el server responde {type:"auth_required"} al abrir)
ws.send(JSON.stringify({ type: "auth", content: { token: bearerToken } }));

// 3) Suscríbete al canal == session_id (el server responde {type:"subscribed"})
ws.send(JSON.stringify({ type: "subscribe", content: { channel: sessionId } }));

// 4) Recibe las salidas estructuradas
ws.onmessage = (ev) => {
  const msg = JSON.parse(ev.data);
  // mensajes de control de la propia WS:
  if (msg.type === "auth_required" || msg.type === "subscribed") return;
  // salida estructurada de la conversación (ver schema abajo):
  renderStructuredOutput(msg);
};
```

**Schema de la salida estructurada** — `StructuredOutputMessage` (spec FEAT-243,
sección "Data Models"). **`[PROPUESTA — P4, confirmar con backend]`** el contrato
exacto (nombres de `type`, forma de `payload`) es la **Open Question P4** del
spec y debe cerrarse antes de implementar el render:

```jsonc
{
  "type": "chart" | "data" | "canvas" | "tool_call",  // discriminador
  "session_id": "abc-123",
  "payload": { /* depende del type — el artefacto a pintar */ },
  "turn_id": "t-789"        // opcional: agrupa salidas de un mismo turno
}
```

Recomendación de integración: **reaprovecha tu render actual de artefactos**
estructurados. Si AgentChat ya pinta `output`/`data`/`media`/charts/canvas desde
el envelope REST de `AgentTalk`, mapea `StructuredOutputMessage.payload` a ese
mismo render. Lo ideal es que el contrato P4 reutilice las **mismas formas** que
ya consume tu UI (ver `docs/frontend/structured-artifacts-frontend-guide.md`) —
plantéalo así al backend para no duplicar renderers.

> **Si ya usas la WS `/ws/user` para el chat**, no abras una segunda conexión:
> reutiliza la misma y solo añade `subscribe` al canal `session_id`. El canal de
> Phase C es el **mismo mecanismo** que usa Web-HITL (`channel = session_id`,
> ver `human/channels/web.py`).

---

## 7. Estados de turno, barge-in y "pensando"

Phase C es conversacional en tiempo real; la UI debería reflejar el estado del
turno para que se sienta viva.

- **Barge-in (nativo):** si el usuario habla mientras el avatar habla, el
  pipeline LiveKit **interrumpe** la voz del avatar. No tienes que cortar nada;
  como mucho, refleja "escuchando…" en la UI cuando el VAD detecte voz del
  usuario.
- **Estado "pensando" durante `tool_calls` largos:** mientras ai-parrot ejecuta
  herramientas, el avatar puede quedarse en silencio (riesgo de "dead air"). El
  spec contempla un **filler/"thinking"** (Open Question **Q-filler**). Cómo se
  señala al frontend está **por definir**; previsiones razonables a confirmar con
  backend:
  - un `StructuredOutputMessage` con `type: "tool_call"` (o un `type` de estado)
    que tu UI traduzca a un indicador "El asistente está consultando datos…", **o**
  - una utterance hablada por el avatar ("déjame revisar eso…"), que no requiere
    nada en el frontend.
- **Estados de UI sugeridos:** `idle` → `connecting` → `listening` (VAD del
  usuario) → `speaking` (avatar habla) → `thinking` (tool_calls). Deriva
  `speaking`/`listening` de eventos de `livekit-client` (`RoomEvent`,
  `isSpeaking` de participantes) y `thinking` del canal WS si el backend lo
  emite.

> Para detectar quién habla puedes usar `RoomEvent.ActiveSpeakersChanged` o el
> flag `participant.isSpeaking` de `livekit-client`. El participante remoto
> `avatar-agent` hablando = pinta "speaking"; el local hablando = "listening".

---

## 8. Paso 4 — Cerrar la sesión

Cierra **siempre** al terminar (cerrar chat, navegar fuera, `beforeunload`):
desconéctate de la sala, cierra la WS y avisa al backend para que pare el worker.

| | |
|---|---|
| **Método** | `POST` |
| **Ruta** | `/api/v1/agents/avatar/{agent_id}/stop` *(a confirmar, homólogo a Phase A)* |
| **Body** | `{ "session_id": "abc-123" }` |
| **Response** | `204 No Content` (idempotente) |

```ts
async function stopVoiceNative(
  agentId: string,
  sessionId: string,
  room: Room,
  ws: WebSocket | null,
): Promise<void> {
  try {
    await room.localParticipant.setMicrophoneEnabled(false);
    await room.disconnect();
  } finally {
    ws?.close();
    await fetch(`/api/v1/agents/avatar/${agentId}/stop`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId }),
      credentials: "include",
    });
  }
}
```

> El backend registra `stop_session` como **shutdown callback** del worker, pero
> **no dependas de él**: llama a `/stop` explícitamente para liberar el worker y
> la sesión cuanto antes (es un recurso *stateful* de larga vida).

---

## 9. Opt-in por tenant y errores

El avatar es **opt-in por programa/tenant** (inyectado al worker vía job
metadata). Diseña la UI **avatar-aware**, igual que en Phase A:

- Ante `403` en `/start`, **oculta** el avatar y degrada a chat de texto/voz
  normal — sin error rojo.
- `session_id` **debe ser el mismo** en `/start`, en la sala LiveKit, en el
  `subscribe` de la WS y en `/stop`.
- Ante `503` (stack/env no disponible), muestra un fallback elegante.
- Si el micrófono es denegado por el navegador, informa con claridad ("necesito
  acceso al micrófono para conversar") — sin mic no hay turno en Phase C.

---

## 10. Ejemplo completo (TS, vanilla)

```ts
import { Room, RoomEvent, Track } from "livekit-client";

interface StartResponse {
  livekit_url: string;
  token: string;          // publish(audio)+subscribe — ver §4
  session_id: string;
}

interface StructuredOutputMessage {
  type: "chart" | "data" | "canvas" | "tool_call";
  session_id: string;
  payload: Record<string, unknown>;
  turn_id?: string;
}

export class VoiceNativeAvatarSession {
  private room: Room | null = null;
  private ws: WebSocket | null = null;

  constructor(
    private agentId: string,
    private sessionId: string,
    private bearerToken: string,
    private wsBase: string, // p.ej. wss://host (sin /ws/user)
    private videoEl: HTMLVideoElement,
    private audioEl: HTMLAudioElement,
    private onStructured: (m: StructuredOutputMessage) => void,
    private tenantId?: string,
  ) {}

  /** Paso 1 + 2 + 3: arranca sesión, entra a la sala, publica mic, abre la WS. */
  async start(): Promise<void> {
    // 1) Arranca la sesión voz-nativa (mint token + dispatch worker).
    const res = await fetch(`/api/v1/agents/avatar/${this.agentId}/start`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: this.sessionId, tenant_id: this.tenantId }),
      credentials: "include",
    });
    if (res.status === 403) throw new AvatarDisabledError("avatar no habilitado");
    if (!res.ok) throw new Error(`start failed: ${res.status}`);
    const { livekit_url, token }: StartResponse = await res.json();

    // 3) Suscríbete al canal de salidas estructuradas ANTES de hablar.
    await this.openStructuredChannel();

    // 2) Únete a la sala, suscribe avatar y PUBLICA el micrófono.
    this.room = new Room({ adaptiveStream: true, dynacast: true });
    this.room.on(RoomEvent.TrackSubscribed, (track) => {
      if (track.kind === Track.Kind.Video) track.attach(this.videoEl);
      else if (track.kind === Track.Kind.Audio) track.attach(this.audioEl);
    });
    this.room.on(RoomEvent.TrackUnsubscribed, (track) => track.detach());

    await this.room.connect(livekit_url, token);
    await this.room.localParticipant.setMicrophoneEnabled(true); // ← mic ON
  }

  /** Abre la WS de AgentChat y se suscribe al canal == session_id. */
  private openStructuredChannel(): Promise<void> {
    return new Promise((resolve, reject) => {
      this.ws = new WebSocket(`${this.wsBase}/ws/user`);
      this.ws.onopen = () => {
        this.ws!.send(JSON.stringify({ type: "auth", content: { token: this.bearerToken } }));
        this.ws!.send(JSON.stringify({ type: "subscribe", content: { channel: this.sessionId } }));
      };
      this.ws.onmessage = (ev) => {
        const msg = JSON.parse(ev.data);
        if (msg.type === "subscribed") return resolve();
        if (msg.type === "auth_required" || msg.type === "error") return;
        this.onStructured(msg as StructuredOutputMessage); // chart/data/canvas/tool_call
      };
      this.ws.onerror = (e) => reject(e);
    });
  }

  /** Silenciar / reactivar el micrófono del usuario. */
  async setMuted(muted: boolean): Promise<void> {
    await this.room?.localParticipant.setMicrophoneEnabled(!muted);
  }

  /** Paso 4: cierra todo. */
  async stop(): Promise<void> {
    try {
      await this.room?.localParticipant.setMicrophoneEnabled(false);
      await this.room?.disconnect();
    } finally {
      this.room = null;
      this.ws?.close();
      this.ws = null;
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
const session = new VoiceNativeAvatarSession(
  "concierge",
  crypto.randomUUID(),               // o el session_id de AgentChat
  myBearerToken,
  "wss://miservidor",
  document.querySelector("#avatar-video")!,
  document.querySelector("#avatar-audio")!,
  (m) => renderStructuredArtifact(m), // tu render de charts/data/canvas
  "acme",
);

// Arranca tras un gesto del usuario (permiso de micrófono).
document.querySelector("#start-talking")!.addEventListener("click", async () => {
  try {
    await session.start();
  } catch (e) {
    if (e instanceof AvatarDisabledError) showTextOnlyChat();
    else showAvatarUnavailable();
  }
});

window.addEventListener("beforeunload", () => { session.stop(); });
```

---

## 11. Contratos abiertos (P4 / P5 / dispatch)

Para que el frontend pueda terminarse sin sobresaltos, **alinea estos puntos con
backend** (son las Open Questions del spec FEAT-243):

| Item | Qué falta | Impacto en frontend |
|---|---|---|
| **Token publish** (§4) | `mint_room_tokens` hoy da el token de viewer **subscribe-only**; Phase C necesita **publish(audio)+subscribe** para el navegador | Sin esto, `setMicrophoneEnabled(true)` falla. **Bloqueante.** |
| **Endpoint `/start` + dispatch** | El spec define la job metadata pero **no el endpoint** que la frontend invoca ni cómo se despacha el worker | Define ruta, body y forma de respuesta (`livekit_url`, `token`, `session_id`). **Bloqueante.** |
| **P4 — `StructuredOutputMessage`** | Valores de `type` y forma de `payload` por cada tipo (chart/data/canvas/tool_call) | Define el render. Idealmente reusa las formas del envelope actual. **Bloqueante para render.** |
| **Q-filler** (§7) | Cómo se señala "pensando" durante `tool_calls` largos (mensaje WS vs utterance) | Determina si pintas un indicador o no haces nada. **No bloqueante.** |
| **P5 — pin de `livekit-agents`** | Versión fijada del worker | Sin impacto directo en frontend (es server-side), pero condiciona el comportamiento de barge-in/turn. |
| **Q-deploy** | spawn-per-session vs warm pool | Puede afectar el TTFB del primer turno (latencia percibida). |

**Recomendación:** que backend confirme **token publish** + **endpoint `/start`**
+ **schema P4** antes de cablear el render. Mientras tanto, el frontend puede
construirse contra los stubs de esta guía (modelo, LiveKit publish/subscribe,
suscripción WS) ya que esa parte está anclada en código real.

---

## 12. Componente Svelte 5 (referencia)

> Referencia con *runes*. Es el viewer voz-nativo: publica mic, pinta el avatar y
> escucha el canal WS de salidas estructuradas. Adáptalo a tus stores/estilos.

```svelte
<script lang="ts">
  import { Room, RoomEvent, Track } from "livekit-client";
  import { onDestroy } from "svelte";

  let {
    agentId,
    sessionId,
    bearerToken,
    wsBase,                       // p.ej. wss://host
    tenantId = undefined,
    enabled = true,               // opt-in aware: false → no inicializa
    onStructured = (_m: any) => {},
  }: {
    agentId: string;
    sessionId: string;
    bearerToken: string;
    wsBase: string;
    tenantId?: string;
    enabled?: boolean;
    onStructured?: (m: any) => void;
  } = $props();

  let videoEl = $state<HTMLVideoElement | null>(null);
  let audioEl = $state<HTMLAudioElement | null>(null);
  let status = $state<"idle" | "connecting" | "live" | "disabled" | "error">("idle");
  let muted = $state(false);
  let room: Room | null = null;
  let ws: WebSocket | null = null;

  async function start() {
    if (!enabled) { status = "disabled"; return; }
    status = "connecting";

    const res = await fetch(`/api/v1/agents/avatar/${agentId}/start`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, tenant_id: tenantId }),
      credentials: "include",
    });
    if (res.status === 403) { status = "disabled"; return; }
    if (!res.ok) { status = "error"; return; }
    const { livekit_url, token } = await res.json();

    // Canal WS de salidas estructuradas (antes de hablar).
    ws = new WebSocket(`${wsBase}/ws/user`);
    ws.onopen = () => {
      ws!.send(JSON.stringify({ type: "auth", content: { token: bearerToken } }));
      ws!.send(JSON.stringify({ type: "subscribe", content: { channel: sessionId } }));
    };
    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);
      if (["auth_required", "subscribed", "error"].includes(msg.type)) return;
      onStructured(msg);
    };

    // Sala LiveKit: suscribe avatar + publica mic.
    room = new Room({ adaptiveStream: true, dynacast: true });
    room.on(RoomEvent.TrackSubscribed, (track) => {
      if (track.kind === Track.Kind.Video && videoEl) track.attach(videoEl);
      else if (track.kind === Track.Kind.Audio && audioEl) track.attach(audioEl);
    });
    room.on(RoomEvent.TrackUnsubscribed, (track) => track.detach());

    await room.connect(livekit_url, token);
    await room.localParticipant.setMicrophoneEnabled(true);
    status = "live";
  }

  async function toggleMute() {
    muted = !muted;
    await room?.localParticipant.setMicrophoneEnabled(!muted);
  }

  async function stop() {
    try {
      await room?.localParticipant.setMicrophoneEnabled(false);
      await room?.disconnect();
    } finally {
      room = null;
      ws?.close(); ws = null;
      await fetch(`/api/v1/agents/avatar/${agentId}/stop`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId }),
        credentials: "include",
      });
    }
  }

  // Arranca tras gesto del usuario (botón); evita autoplay/permiso de micro.
  onDestroy(() => { stop(); });
</script>

{#if status !== "disabled"}
  <div class="avatar-viewer" data-status={status}>
    <!-- svelte-ignore a11y_media_has_caption -->
    <video bind:this={videoEl} autoplay playsinline muted></video>
    <audio bind:this={audioEl} autoplay></audio>

    {#if status === "idle"}
      <button onclick={start}>Empezar a hablar</button>
    {/if}
    {#if status === "connecting"}<span class="hint">Conectando…</span>{/if}
    {#if status === "live"}
      <button onclick={toggleMute}>{muted ? "Activar micro" : "Silenciar"}</button>
    {/if}
    {#if status === "error"}<span class="hint">Avatar no disponible</span>{/if}
  </div>
{/if}
```

---

## 13. Checklist de integración Frontend

- [ ] Instalar `livekit-client` y fijar la versión.
- [ ] Generar/compartir un único `session_id` entre `/start`, la **sala LiveKit**, el **`subscribe` de la WS** y `/stop`.
- [ ] `POST .../start` → guardar `livekit_url` + `token` (token **publish-capaz**).
- [ ] Arrancar **tras un gesto del usuario** (permiso de micrófono + autoplay).
- [ ] `room.connect(url, token)` y **`setMicrophoneEnabled(true)`** (publicar mic).
- [ ] `attach()` de las pistas **vídeo** y **audio** del avatar (`avatar-agent`).
- [ ] **No** publicar vídeo; **no** enviar POST de turno por cada frase.
- [ ] Abrir la WS `/ws/user`, `auth`, y **`subscribe` al canal `session_id`** **antes** de hablar.
- [ ] Render de `StructuredOutputMessage` (chart/data/canvas/tool_call) reusando tu render de artefactos actual.
- [ ] Reflejar estados de turno (`listening`/`speaking`/`thinking`) y barge-in nativo.
- [ ] Botón de **mute** (`setMicrophoneEnabled(false/true)`).
- [ ] Ser **opt-in aware**: ocultar avatar ante `403`; degradar a chat de texto/voz.
- [ ] Fallback elegante ante `503` (stack/env no disponible) y micrófono denegado.
- [ ] `POST .../stop` + `room.disconnect()` + `ws.close()` al cerrar / `beforeunload`.
- [ ] Mismas credenciales de auth que el resto de AgentChat (`credentials: "include"`).
- [ ] **Alinear con backend** los [contratos abiertos](#11-contratos-abiertos-p4--p5--dispatch) (token publish, endpoint `/start`, schema P4).

---

## Apéndice — Resumen de contratos

```jsonc
// 1) POST /api/v1/agents/avatar/{agent_id}/start   (auth requerida) [PROPUESTA]
//    body:
{ "session_id": "abc-123", "tenant_id": "acme" }
//    200:
{ "livekit_url": "wss://<project>.livekit.cloud",
  "token": "<JWT publish(audio)+subscribe>",   // ⚠️ debe permitir publicar audio
  "session_id": "abc-123" }
//    400 falta session_id · 403 tenant sin opt-in · 503 stack/env no disponible

// 2) LiveKit room (livekit-client)
//    room.connect(livekit_url, token)
//    room.localParticipant.setMicrophoneEnabled(true)   // publica mic (nuevo)
//    avatar remoto = identidad "avatar-agent" (suscribe su vídeo+audio)

// 3) WS /ws/user (UserSocketManager) — salidas estructuradas
//    → { "type": "auth",      "content": { "token": "<bearer>" } }
//    → { "type": "subscribe", "content": { "channel": "abc-123" } }   // == session_id
//    ← { "type": "subscribed", "channel": "abc-123" }
//    ← StructuredOutputMessage:  [PROPUESTA — P4]
{ "type": "chart" | "data" | "canvas" | "tool_call",
  "session_id": "abc-123", "payload": { /* artefacto */ }, "turn_id": "t-789" }

// 4) POST /api/v1/agents/avatar/{agent_id}/stop    (auth requerida) [PROPUESTA]
//    body:
{ "session_id": "abc-123" }
//    204 (idempotente)
```

**Identidades de LiveKit** (informativo):
- Sala (`room`) = `session_id`.
- Avatar (participante remoto que publica vídeo/audio) = identidad `avatar-agent`.
- Navegador (tú) = **publica audio (mic)** + suscribe avatar.

---

## Historial de revisión

| Versión | Fecha | Autor | Cambio |
|---------|-------|-------|--------|
| 1.0 | 2026-06-18 | Claude (FEAT-243) | Guía inicial de integración frontend del avatar voz-nativo (Phase C) |
