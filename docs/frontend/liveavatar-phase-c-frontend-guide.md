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

> ✅ **Estado de esta guía (2026-06-18, rev 1.1).** El backend de Phase C
> (FEAT-243) está **implementado y fusionado en `dev`** (rama
> `feat-243-liveavatar-phase-c-voice-native`, 104 tests en verde). Lo que ya es
> **código real y verificado**: el worker de LiveKit Agents, el `llm_node` que
> llama a ai-parrot, el `OutputBridge` y su **contrato de salida estructurada**,
> y el transporte cross-process por Redis hacia la WS de AgentChat.
>
> **El endpoint de arranque del navegador YA EXISTE** (resuelto post-rev 1.1):
> `POST /api/v1/agents/avatar/{agent_id}/voice-native/start` acuña un **token con
> publicación de audio** (`can_publish` micrófono + subscribe) y hace **explicit
> dispatch del worker** a la sala con la `AvatarJobMetadata`. Contrato real en
> [§4](#4-paso-1--arrancar-la-sesión-voz-nativa) y estado en
> [§11](#11-estado-del-arranque-token-de-publicación--dispatch). El modelo mental,
> el flujo LiveKit y el consumo de salidas estructuradas por la WS **también**
> están anclados en código real.
>
> Archivos fuente verificados (2026-06-18, post-merge):
> - `…/liveavatar/livekit_agent/models.py` — `AvatarJobMetadata`, `StructuredOutputMessage`
> - `…/liveavatar/livekit_agent/agent.py` — `LiveAvatarAgent.llm_node` + `_classify` / `_structured_payload`
> - `…/liveavatar/livekit_agent/worker.py` — `entrypoint`, `parse_job_metadata`, `open_avatar_session`
> - `…/liveavatar/livekit_agent/pipeline.py` — `build_session` (STT/VAD/turn/TTS)
> - `…/liveavatar/output_bridge.py` + `output_transport.py` — bridge + Redis pub/sub
> - `…/liveavatar/room_manager.py` — `mint_room_tokens` (`client_token` subscribe-only, Phase A) + `mint_browser_token` (publish-audio, Phase C) + `dispatch_worker`
> - `packages/ai-parrot-server/src/parrot/handlers/avatar.py` — `VoiceNativeAvatarView` / `_start_voice_native_session` (endpoint `/voice-native/start`)
> - `packages/ai-parrot-server/src/parrot/handlers/liveavatar_output.py` — subscriber server-side
> - `packages/ai-parrot-server/src/parrot/handlers/user.py:357` — `broadcast_to_channel`
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
11. [Estado del arranque (token de publicación + dispatch)](#11-estado-del-arranque-token-de-publicación--dispatch)
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
| STT | STT del navegador o de `AgentVoiceTalk` | **STT del pipeline LiveKit** (Deepgram `nova-3`) |
| Barge-in | No nativo | **Nativo** (Silero VAD + MultilingualModel turn-detection) |
| Salidas estructuradas | En el **envelope REST** de `/voice` | Por la **WS de AgentChat** (`broadcast_to_channel`) |
| Audio del agente | PCM empujado por backend (Supertonic) | **TTS (Cartesia)** del pipeline → avatar, por la sala |

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

**✅ Implementado.** El endpoint de arranque voz-nativo **ya existe** y hace las
dos cosas que el navegador necesita: (a) acuña un **token con publicación de
audio** y (b) hace **explicit dispatch del worker** a la sala con la
`AvatarJobMetadata`. El worker de LiveKit Agents corre como proceso de larga vida
(`WorkerOptions(agent_name=…)`) y recibe su contexto por esa job-metadata:

```python
# …/liveavatar/livekit_agent/models.py  (verificado)
class AvatarJobMetadata(BaseModel):
    ws_url: str          # URL ws de la sala (informativo / diagnóstico)
    session_id: str      # conversación de AgentChat — sala + canal WS
    agent_name: str      # agente ai-parrot que actúa de cerebro
    tenant_id: str | None = None
```

> **Nota backend (informativa).** El `agent_name` que se despacha en LiveKit es el
> del **worker** (`WorkerOptions.agent_name`, env `LIVEAVATAR_WORKER_AGENT_NAME`,
> por defecto `liveavatar-voice`) — **distinto** del `agent_name` ai-parrot que
> viaja dentro de `AvatarJobMetadata` (el del path `{agent_id}`). El dispatch se
> hace con `LiveKitAPI().agent_dispatch.create_dispatch(...)` desde
> `LiveKitRoomManager.dispatch_worker`.

El contrato del endpoint:

| | |
|---|---|
| **Método** | `POST` |
| **Ruta** | `/api/v1/agents/avatar/{agent_id}/voice-native/start` |
| **Auth** | Requerida (cookie de sesión / `Authorization`, igual que el chat) |
| **Content-Type** | `application/json` |

**Request body:**

```jsonc
{
  "session_id": "abc-123",   // OBLIGATORIO. Clave compartida: sala LiveKit + canal WS.
  "tenant_id": "acme"        // Opcional. Opt-in por tenant (va a la job-metadata).
}
```

**Response 200 esperada:**

```jsonc
{
  "livekit_url": "wss://<project>.livekit.cloud",
  "token": "<JWT publish(audio)+subscribe>",   // ⚠️ debe permitir publicar audio
  "session_id": "abc-123"
}
```

> ✅ **Token de publicación (resuelto).** El endpoint usa
> `LiveKitRoomManager.mint_browser_token`, que acuña un JWT con `can_publish=True`
> **restringido a la fuente `microphone`** (audio) + `can_subscribe=True`. Es el
> token que devuelve `/voice-native/start` en el campo **`token`** (no confundir
> con el `client_token` subscribe-only de Phase A). Con él,
> `setMicrophoneEnabled(true)` funciona; el navegador **no** puede publicar vídeo.

**Errores esperados:**

| Código | Significado | Acción de UI |
|--------|-------------|--------------|
| `200` | Token emitido + worker despachado | Conéctate a la sala y publica mic |
| `400` | Falta `session_id` | Bug del cliente: corrige el payload |
| `403` | Tenant sin opt-in de avatar | Oculta el avatar; degrada a chat de texto/voz |
| `503` | Stack/env no disponible (`ai-parrot-integrations[liveavatar-voice]` / `livekit-agents` / env) | Fallback "avatar no disponible" |

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
`broadcast_to_channel(session_id, StructuredOutputMessage.model_dump())`.

> **Detalle de backend (informativo).** El worker corre en **otro proceso** que
> el servidor de AgentChat, así que el `OutputBridge` publica primero a un canal
> **Redis pub/sub** (`liveavatar:structured-outputs`) y un subscriber del servidor
> (`configure_liveavatar_output_subscriber`) lo **re-emite** por
> `broadcast_to_channel`. Para el frontend esto es transparente: tú solo te
> suscribes al canal `session_id` en `/ws/user`.

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

**Schema de la salida estructurada** — `StructuredOutputMessage` (P4 **resuelto**,
verificado en `models.py` + `agent.py`). El mensaje que recibes por la WS es
exactamente el `model_dump()`:

```jsonc
{
  "type": "tool_call" | "canvas" | "data" | "<output_mode>",  // discriminador (ver abajo)
  "session_id": "abc-123",
  "payload": {                 // forma FIJA, la produce _structured_payload()
    "response":    "texto de la respuesta (puede ser null)",
    "data":        { /* el dato estructurado, ya JSON-safe (frames→records) */ },
    "code":        "código generado o null",
    "artifact_id": "id del artefacto o null",
    "output_mode": "chart | map | table | … o null",
    "tool_calls":  ["nombre_de_la_tool", "…"]   // solo nombres
  },
  "turn_id": "<artifact_id o null>"   // ⚠️ hoy turn_id == artifact_id
}
```

**Cómo se decide `type`** (`_classify`, en orden):

| Condición en el `AIMessage` | `type` resultante |
|---|---|
| Tiene `tool_calls` | `"tool_call"` |
| `output_mode` ≠ `default`/`null` | el valor de `output_mode` (p.ej. `"chart"`, `"map"`, `"table"`) |
| Tiene `artifact_id` | `"canvas"` |
| En otro caso (lleva `data`) | `"data"` |

> **Importante — qué NO llega por la WS.** Solo se publican los turnos con salida
> **estructurada** (`tool_calls`, `data`, `artifact_id`, u `output_mode` no
> default). Un turno de **solo voz** (respuesta hablada sin estructura) **no
> genera ningún mensaje** en el canal: el usuario lo **oye** por el avatar y no
> hay nada que pintar. No esperes un "transcript" del texto hablado por esta vía.

Recomendación de integración: **reaprovecha tu render actual de artefactos**.
El `payload` reusa los mismos campos del envelope de `AgentTalk`
(`response`/`data`/`code`/`artifact_id`/`output_mode`), así que mapea
`StructuredOutputMessage.payload` a tu render existente
(ver `docs/frontend/structured-artifacts-frontend-guide.md`). Usa `type` (o
`payload.output_mode`) como discriminador del componente a montar.

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
- **Estado "pensando" durante `tool_calls` largos (Q-filler — resuelto):** la
  solución implementada es una **frase hablada por el avatar**. Si un turno se
  resuelve en `tool_calls` sin producir voz, `LiveAvatarAgent` emite un filler
  (`DEFAULT_FILLER_TEXT = "Let me look into that for you."`) por TTS para que el
  avatar **no se quede mudo**. **No** necesitas pintar nada para esto: el usuario
  lo oye.
  - De forma **complementaria**, ese mismo turno **sí** publica un
    `StructuredOutputMessage` con `type: "tool_call"` (con `payload.tool_calls`
    = nombres de las herramientas). Si quieres, úsalo para un indicador opcional
    en la UI ("Consultando datos: `revenue_query`…"). Es opcional; el filler
    hablado ya cubre el "no dead air".
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
  type: string; // "tool_call" | "canvas" | "data" | <output_mode> (chart/map/table/…)
  session_id: string;
  payload: {
    response: string | null;
    data: unknown;            // ya JSON-safe (frames→records)
    code: string | null;
    artifact_id: string | null;
    output_mode: string | null;
    tool_calls: string[];     // nombres de las tools
  };
  turn_id: string | null;     // hoy == artifact_id
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
    const res = await fetch(`/api/v1/agents/avatar/${this.agentId}/voice-native/start`, {
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

## 11. Estado del arranque (token de publicación + dispatch)

Todas las Open Questions del spec y el **entrypoint del navegador** (token de
sala + dispatch del worker) están **resueltos e implementados**. Ya no hay
bloqueantes para el frontend.

| Item | Estado | Impacto en frontend |
|---|---|---|
| **Endpoint de arranque + dispatch** (§4) | ✅ **Implementado**: `POST /api/v1/agents/avatar/{agent_id}/voice-native/start` (mint token + `dispatch_worker` con `AvatarJobMetadata`) | Llama a ese endpoint; recibe `{livekit_url, token, session_id}`. |
| **Token publish para el navegador** (§4) | ✅ **Implementado**: `mint_browser_token` (`can_publish` micrófono + subscribe) | El campo `token` ya permite `setMicrophoneEnabled(true)`. |
| **P4 — `StructuredOutputMessage`** | ✅ **Resuelto** (implementado, ver §6) | Contrato fijo: `type` + `payload {response,data,code,artifact_id,output_mode,tool_calls}` + `turn_id`. |
| **Q-filler** (§7) | ✅ **Resuelto**: filler hablado por el avatar | Nada que pintar (opcional: usar el msg `tool_call`). |
| **P5 — pin de `livekit-agents`** | ✅ **Resuelto**: `~=1.5`, validado en **1.6.1** | Server-side; condiciona barge-in/turn (ya validado). |
| **Q-plugins** | ✅ **Resuelto**: Deepgram `nova-3` · Cartesia · Silero · MultilingualModel | Determina STT/TTS/VAD (server-side). |
| **Q-deploy** | ✅ **Resuelto**: modelo `PROCESS` + warm pool (`num_idle_processes`) | Puede afectar el TTFB del primer turno (latencia percibida). |

**Recomendación.** El frontend puede integrarse **directamente** contra esta
guía: el flujo completo (arranque → publish mic + subscribe avatar → salidas
estructuradas por la WS) está anclado en código real y con tests. Ya no hace
falta mockear `/start`.

> **Requisitos de despliegue** (para que el endpoint funcione end-to-end): env
> `LIVEKIT_URL` / `LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET` (mint + dispatch),
> `LIVEAVATAR_WORKER_AGENT_NAME` (opcional, default `liveavatar-voice`); el
> **worker** corriendo (`worker.configure(bot_resolver=…)` + `worker.run()`, ver
> `examples/liveavatar_voice_worker.py`) y registrado con ese mismo `agent_name`;
> y el subscriber de salida activo en el server
> (`configure_liveavatar_output_subscriber(app)`, opt-in `ENABLE_LIVEAVATAR_VOICE`).
> El opt-in por tenant (`is_avatar_enabled`) sigue gobernando el `403`.

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

    const res = await fetch(`/api/v1/agents/avatar/${agentId}/voice-native/start`, {
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
- [ ] `POST .../voice-native/start` para arrancar (endpoint **ya implementado**; ver [§11](#11-estado-del-arranque-token-de-publicación--dispatch)). Sin bloqueantes pendientes.

---

## Apéndice — Resumen de contratos

```jsonc
// 1) POST /api/v1/agents/avatar/{agent_id}/voice-native/start   (auth requerida) [IMPLEMENTADO]
//    Acuña token publish(audio) + DESPACHA el worker con AvatarJobMetadata.
//    body:
{ "session_id": "abc-123", "tenant_id": "acme" }
//    200:
{ "livekit_url": "wss://<project>.livekit.cloud",
  "token": "<JWT publish(microphone)+subscribe>",   // NO el client_token subscribe-only de Phase A
  "session_id": "abc-123" }
//    400 falta session_id · 403 tenant sin opt-in · 503 stack/env/dispatch no disponible

// 2) LiveKit room (livekit-client)
//    room.connect(livekit_url, token)
//    room.localParticipant.setMicrophoneEnabled(true)   // publica mic (nuevo)
//    avatar remoto = identidad "avatar-agent" (suscribe su vídeo+audio)

// 3) WS /ws/user (UserSocketManager) — salidas estructuradas [P4 RESUELTO]
//    → { "type": "auth",      "content": { "token": "<bearer>" } }
//    → { "type": "subscribe", "content": { "channel": "abc-123" } }   // == session_id
//    ← { "type": "subscribed", "channel": "abc-123" }
//    ← StructuredOutputMessage (model_dump):
{ "type": "tool_call" | "canvas" | "data" | "<output_mode>",
  "session_id": "abc-123",
  "payload": { "response": null, "data": {}, "code": null,
               "artifact_id": null, "output_mode": null, "tool_calls": [] },
  "turn_id": null }   // turn_id == artifact_id
//    (los turnos de SOLO voz no emiten mensaje)

// 4) POST .../stop    (auth requerida) — homólogo a Phase A, idempotente (204)
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
| 1.1 | 2026-06-18 | Claude (FEAT-243) | Revisada contra el merge en `dev`: contrato `StructuredOutputMessage` real (P4 resuelto), filler hablado (Q-filler), pipeline Deepgram/Cartesia/Silero, `livekit-agents ~=1.5` (P5), transporte Redis. Único bloqueante restante: endpoint de arranque del navegador + token publish |
| 1.2 | 2026-06-18 | Claude (FEAT-243) | **Bloqueante resuelto**: implementado `POST /api/v1/agents/avatar/{agent_id}/voice-native/start` (`VoiceNativeAvatarView`) que acuña token publish-audio (`mint_browser_token`) y despacha el worker (`dispatch_worker` → `create_dispatch` con `AvatarJobMetadata`). Ejemplos §10/§12 y contratos actualizados a la ruta real. Sin bloqueantes pendientes |
