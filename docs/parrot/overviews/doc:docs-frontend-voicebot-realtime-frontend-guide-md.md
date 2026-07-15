---
type: Wiki Overview
title: VoiceBot · VoiceChatHandler · FEAT-245 — Guía de Frontend para Conversación
  Realtime con Agentes
id: doc:docs-frontend-voicebot-realtime-frontend-guide-md
tags:
- overview
timestamp: '2026-07-14T22:20:21+00:00'
summary: ┌──────────────────────────── Browser (tu UI) ───────────────────────────┐
relates_to:
- concept: mod:parrot.bots.voice
  rel: mentions
- concept: mod:parrot.models.voice
  rel: mentions
- concept: mod:parrot.voice.handler
  rel: mentions
---

# VoiceBot · VoiceChatHandler · FEAT-245 — Guía de Frontend para Conversación Realtime con Agentes

> **Objetivo de este documento**: dar a un equipo de frontend todo lo necesario para
> construir una UI **full-interactive, realtime, basada en WebSocket** que hable con un
> agente de AI-Parrot por voz — incluyendo el modo con **avatar con lip-sync** (FEAT-245).
>
> Cubre tres capas:
> 1. **`VoiceBot`** — el cerebro de voz (Gemini Live, audio nativo bidireccional).
> 2. **`VoiceChatHandler`** — el handler aiohttp que expone `/ws/voice` al navegador.
> 3. **FEAT-245** — el "tee" de audio que mueve la boca de un avatar LiveAvatar/LiveKit.
>
> Todo lo descrito aquí está verificado contra el código en `packages/ai-parrot` y
> `packages/ai-parrot-integrations` (estado: `dev`, junio 2026).

---

## 0. Mapa mental en 30 segundos

```
                          ┌──────────────────────────── Browser (tu UI) ───────────────────────────┐
   Micrófono (16 kHz PCM) │  getUserMedia → AudioWorklet → PCM16 16k                                 │
        ──────────────────┼──▶ WebSocket /ws/voice (binario o base64)                               │
                          │                                                                          │
   Altavoz (24 kHz PCM)   │  ◀── response_chunk {audio_base64} ── Web Audio API (cola de reproducción)│
        ◀─────────────────┤                                                                          │
   Avatar vídeo+audio     │  ◀── LiveKit room (subscribe-only token)  ←─ SOLO si avatar:true         │
        ◀─────────────────┘                                                                          │
                          └──────────────────────────────────────────────────────────────────────────┘
                                              │  ▲
                                  /ws/voice   │  │  response_chunk / transcription / tool_call ...
                                              ▼  │
                          ┌───────────────────────────────────────────────┐
                          │  VoiceChatHandler (aiohttp)                     │
                          │   · auth JWT · sesión · cola de audio           │
                          │   · streaming | buffered                        │
                          └───────────────────────────────────────────────┘
                                              │  ▲
                              VoiceBot.ask_stream(audio_iter)  │
                                              ▼  │  LiveVoiceResponse(audio 24k, text, tool_calls)
                          ┌───────────────────────────────────────────────┐
                          │  VoiceBot → GeminiLiveClient                    │
                          │   · Gemini 2.5 native-audio                     │
                          │   · VAD · STT in/out · tools · interrupción     │
                          └───────────────────────────────────────────────┘
                                              │  (FEAT-245: tee del MISMO audio 24k)
                                              ▼
                          VoiceAvatarSession.speak(pcm) → AvatarWebSocket → LiveAvatar → LiveKit room
```

**Las tres reglas de oro del frontend:**

1. **Entrada**: micrófono → **PCM 16-bit, 16 kHz, mono** → enviar como **binario** (preferido) o base64.
2. **Salida**: el servidor manda **PCM 16-bit, 24 kHz, mono** dentro de `response_chunk.audio_base64`.
3. **Avatar (FEAT-245)**: si pides `avatar:true`, el navegador recibe el audio **dos veces**
   (por `/ws/voice` y por la sala LiveKit). **Debes silenciar una fuente** para evitar eco —
   recomendado: silenciar el audio de `/ws/voice` y escuchar la pista del avatar (la que tiene lip-sync).

---

## 1. `VoiceBot` — el cerebro de voz

**Archivo**: `packages/ai-parrot/src/parrot/bots/voice.py`

```python
class VoiceBot(A2AEnabledMixin, BaseBot):
```

`VoiceBot` es un bot de AI-Parrot especializado en voz. Internamente **siempre** usa
`GeminiLiveClient` (Gemini 2.5 con audio nativo), independientemente del `llm` que pases.

### 1.1 Construcción

```python
from parrot.bots.voice import VoiceBot
from parrot.models.voice import VoiceConfig

bot = VoiceBot(
    name="Sales Assistant",
    system_prompt="Eres un asistente de ventas conciso...",
    tools=[SearchTool(), RecommendTool()],
    voice_config=VoiceConfig(
        voice_name="Puck",        # Puck, Charon, Kore, Aoede, Fenrir...
        language="en-US",
        temperature=0.7,
        max_tokens=4096,
        enable_vad=True,                      # detección de turno automática
        enable_input_transcription=True,      # STT del usuario
        enable_output_transcription=True,     # STT del asistente
    ),
)
await bot.configure()   # inicialización async (memoria Redis por defecto)
```

`VoiceConfig` (`packages/ai-parrot/src/parrot/models/voice.py`):

| Campo | Default | Nota |
|---|---|---|
| `voice_name` | `"Puck"` | voz prebuilt de Gemini |
| `language` | `"en-US"` | BCP-47 |
| `input_format` | `PCM_16K` | lo que el navegador **debe** enviar |
| `output_format` | `PCM_24K` | lo que el servidor devuelve |
| `temperature` | `0.7` | |
| `max_tokens` | `4096` | |
| `enable_vad` | `True` | turn-taking automático |
| `enable_input_transcription` | `True` | habilita evento `transcription` (usuario) |
| `enable_output_transcription` | `True` | transcripción del asistente |

### 1.2 Métodos clave (lo que consume el handler)

| Método | Firma (resumida) | Uso |
|---|---|---|
| `ask_stream(audio_input, session_id, user_id)` | `AsyncIterator[LiveVoiceResponse]` | **streaming bidireccional** — el corazón del modo realtime |
| `ask_voice(audio_input, ...)` | `-> LiveVoiceResponse` | one-shot: buffer completo → respuesta completa (modo buffered) |
| `ask(question: str, ...)` | `AsyncIterator[LiveVoiceResponse]` | texto → voz (TTS / pruebas) |
| `configure(app=None)` | `-> None` | inicialización async; memoria Redis por defecto |

`ask_stream` acepta como `audio_input` **un `bytes` completo o un `AsyncIterator[bytes]`** de
chunks PCM16/16k. El handler le pasa un generador que lee de una `asyncio.Queue` alimentada
por los frames que llegan del WebSocket.

### 1.3 `LiveVoiceResponse` — el objeto que fluye en cada chunk

**Archivo**: `packages/ai-parrot/src/parrot/clients/live.py`

```python
@dataclass
class LiveVoiceResponse:
    text: str = ""
    audio_data: Optional[bytes] = None
    audio_format: str = "audio/pcm;rate=24000"
    is_complete: bool = False        # fin de turno
    is_interrupted: bool = False     # barge-in (el usuario cortó)
    tool_calls: List[LiveToolCall] = []
    usage: Optional[LiveCompletionUsage] = None
    turn_metadata: Optional[VoiceTurnMetadata] = None
    session_id / turn_id / user_id
    metadata: Dict[str, Any] = {}    # user_transcription, display_data, go_away...
```

El handler traduce cada `LiveVoiceResponse` a uno o varios mensajes WebSocket
(`response_chunk`, `transcription`, `tool_call`, `display_data`, `response_complete`).

### 1.4 VAD, turn-taking e interrupción (lo importante para la UX)

`GeminiLiveClient` configura **detección automática de actividad de voz (VAD)**:

```python
realtime_input_config=types.RealtimeInputConfig(
    automatic_activity_detection=types.AutomaticActivityDetection(
        disabled=False,
        start_of_speech_sensitivity=START_SENSITIVITY_HIGH,
        end_of_speech_sensitivity=END_SENSITIVITY_HIGH,
        prefix_padding_ms=100,
        silence_duration_ms=500,   # 500 ms de silencio cierra el turno
    )
)
```

Implicaciones para el frontend:

- **No necesitas botón push-to-talk** en modo streaming: basta con enviar audio continuamente;
  Gemini detecta inicio/fin de turno. (El push-to-talk sigue siendo válido y útil en modo `buffered`.)
- **Barge-in**: si el usuario habla mientras el asistente responde, Gemini emite
  `is_interrupted=True`. La UI debe **vaciar inmediatamente su cola de reproducción de audio**
  al recibir `response_chunk.is_interrupted == true` o `response_complete.is_interrupted == true`.
- **Fin de turno**: `response_complete` + `ready_to_speak` señalan que el asistente terminó.

---

## 2. `VoiceChatHandler` — el endpoint WebSocket

**Archivo**: `packages/ai-parrot-integrations/src/parrot/voice/handler.py`

Es el handler aiohttp que el navegador consume. (Existe también `voice/server.py`, un servidor
standalone alternativo; **para integrar en una app aiohttp usa `VoiceChatHandler`**.)

### 2.1 Montaje en el servidor

```python
from aiohttp import web
from parrot.voice.handler import VoiceChatHandler

handler = VoiceChatHandler(
    bot_factory=lambda: create_voice_bot(name="Sales", voice_name="Puck", tools=[...]),
    require_auth=True,
    secret_key=os.environ["JWT_SECRET"],   # o un TokenValidator custom
    auth_timeout=30.0,
    ws_route="/ws/voice",
)

app = web.Application()
handler.setup_routes(app, prefix="/api/v1")   # → /api/v1/ws/voice (+ /health, /static)
web.run_app(app, host="0.0.0.0", port=8765)
```

Rutas registradas por `setup_routes(app, prefix, include_health=True, include_static=True)`:

| Ruta | Método | Propósito |
|---|---|---|
| `{prefix}/ws/voice` | GET (upgrade) | WebSocket de voz (principal) |
| `{prefix}/health` | GET | health check |
| `{prefix}/static/*` | GET | servir assets (opcional) |

### 2.2 Autenticación (3 métodos)

El handler valida un **JWT**. Hay tres formas de pasarlo; elige una:

| Método | Cómo | Cuándo |
|---|---|---|
| **`Sec-WebSocket-Protocol`** (recomendado) | `new WebSocket(url, ["jwt", token])` | más seguro: se valida **antes** del upgrade |
| **Query param** | `new WebSocket(url + "?token=" + token)` | simple, pero el token queda en logs |
| **Mensaje post-conexión** | `ws.send({type:"auth", token})` | cuando el token no está disponible al conectar |

`TokenValidator` (`packages/ai-parrot/src/parrot/core/ws_auth.py`) resuelve en orden:
`validator_func` custom → `navigator_auth.SECRET_KEY` → `secret_key` fallback → modo fallback
(acepta cualquier token; **solo testing**). Devuelve un `AuthenticatedUser`
(`user_id`, `username`, `email`, `roles`, `permissions`).

> Si `require_auth=False`, puedes omitir todo lo de auth y empezar la sesión directamente.

### 2.3 Ciclo de vida de la sesión

```
connect ──▶ {connected}
   │  (auth si aplica) ──▶ {auth_success | auth_error | auth_required}
   ▼
start_session ──▶ {session_started} ──▶ {ready_to_speak}
   │
   ├─ (streaming) enviar audio binario/base64 en continuo
   │     ◀── response_chunk* ◀── transcription ◀── tool_call ◀── response_complete ◀── ready_to_speak
   │
   └─ (buffered) start_recording → audio... → stop_recording (o voice_complete)
         ◀── processing ◀── voice_response ◀── ready_to_speak
   ▼
end_session ──▶ {session_ended}   (o reset_session para reiniciar)
disconnect
```

### 2.4 Modos: `streaming` vs `buffered`

Se elige en `start_session` con `streaming_mode` (default `"streaming"`).

| Aspecto | `streaming` (recomendado, full-interactive) | `buffered` (push-to-talk) |
|---|---|---|
| Entrada de audio | frames enviados en continuo → cola → Gemini al instante | se acumulan y se mandan de golpe |
| Disparo de proceso | continuo (VAD detecta turnos) | `stop_recording` o `voice_complete` |
| Respuesta | troceada (`response_chunk`) en tiempo real | completa (`voice_response`) |
| Latencia | baja | mayor |
| Caso de uso | conversación natural, barge-in | móvil, grabación offline |

---

## 3. Protocolo WebSocket completo

> Verificado contra `_handle_message` y los handlers en `handler.py`.

### 3.1 Cliente → Servidor

| `type` | Payload | Efecto |
|---|---|---|
| `auth` | `{token}` **o** `{authorization:"Bearer <jwt>"}` | autenticación post-conexión |
| `ping` | `{timestamp?}` | keepalive (responde `pong`) |
| `start_session` | `{config:{...}, streaming_mode?, avatar?, avatar_id?, tenant_id?}` | inicia sesión de voz |
| `end_session` | `{}` | termina sesión |
| `reset_session` | `{}` | end + restart |
| `start_recording` | `{}` | marca inicio de grabación (buffered) |
| `stop_recording` | `{}` | fin de grabación → procesa buffer |
| `audio_data` / `audio_chunk` | `{data:"<base64 PCM16 16k>"}` | chunk de audio vía JSON |
| `send_text` / `text_message` | `{text:"...", streaming?}` | entrada de texto → respuesta hablada |
| `voice_complete` / `voice_buffer` | `{audio_base64:"..."}` | buffer completo (no streaming) |
| **(binario)** | bytes crudos PCM16 16k | **forma más eficiente** de mandar audio |

**`config` de `start_session`:**

```jsonc
{
  "voice_name": "Puck",        // opcional
  "language": "en-US",         // opcional
  "system_prompt": "...",      // opcional, override del prompt
  "model": "gemini-2.5-...",   // opcional
  "send_welcome": false         // opcional, saludo inicial
}
```

**Campos de avatar (FEAT-245, aditivos):** `avatar: true`, `avatar_id?`, `tenant_id?`
(ver §4).

### 3.2 Servidor → Cliente

| `type` | Payload | Cuándo |
|---|---|---|
| `connected` | `{session_id, authenticated, require_auth}` | al conectar |
| `auth_success` | `{user:{user_id, username}}` | auth OK |
| `auth_error` | `{message}` | auth falló |
| `auth_required` | `{message}` | el server exige auth y no llegó |
| `session_started` | `{session_id, user_id, streaming_mode, config:{...}, avatar?}` | sesión lista |
| `ready_to_speak` | `{message}` | listo para nueva entrada (tras `session_started` y tras cada turno) |
| `recording_started` | `{}` | grabación iniciada (buffered) |
| `recording_stopped` | `{message, duration_ms?}` | grabación terminada |
| `processing` | `{message, audio_size?}` | procesando audio (buffered) |
| **`response_chunk`** | `{text, audio_base64, audio_format, is_interrupted}` | **chunk de respuesta (streaming)** |
| `voice_response` | `{text, audio_base64, audio_format, is_complete, usage?}` | respuesta completa (buffered) |
| `response_complete` | `{text, is_interrupted}` | fin de turno (streaming) |
| `transcription` | `{text, is_user}` | STT de usuario (y/o asistente) |
| `tool_call` | `{name, arguments, result, execution_time_ms}` | herramienta ejecutada |
| `display_data` | `{data}` | metadata visual de una tool (gráficos, tablas...) |
| `pong` | `{timestamp, ping_count, session_id, session_active, ...}` | respuesta a `ping` |
| `session_ended` | `{session_id}` | sesión terminada |
| `session_warning` | `{message, time_left?}` | Gemini va a reconectar (GoAway) |
| `error` | `{message, code?, is_retryable?}` | error |

**Formatos de audio (en `session_started.config`):**

```
input_format:  "audio/pcm;rate=16000"   // lo que el navegador envía
output_format: "audio/pcm;rate=24000"   // lo que el servidor devuelve
```

> ⚠️ **`response_chunk` vs `voice_response`**: en **streaming** el audio llega troceado en
> `response_chunk` y el turno cierra con `response_complete`. En **buffered** llega una sola
> `voice_response` con `is_complete:true`. Tu UI debe manejar ambos según el modo elegido.

> 🧠 El handler **filtra "pensamientos"** del modelo (texto tipo `**Clarifying...**` o
> `**Show Product...**`) y **no reenvía la transcripción del asistente** para evitar duplicar
> el texto de `response_chunk`. Es decir: el texto del asistente lo obtienes del `text` de los
> chunks, no de un evento `transcription is_user:false`.

---

## 4. FEAT-245 — Avatar con lip-sync (LiveAvatar + LiveKit)

**Spec**: `sdd/specs/voicechat-liveavatar-gemini.spec.md` · **Estado: completo y mergeado**
(TASK-1588/1589/1590 ✅).

### 4.1 Qué hace

Gemini Live emite audio a **24 kHz mono 16-bit** — exactamente lo que espera la "boca" del
avatar (`AVATAR_PCM_SAMPLE_RATE = 24_000`). FEAT-245 **tee-a** (duplica) ese mismo audio:
una copia va al navegador (comportamiento existente) y otra va al avatar, **sin resampling**.

```
Gemini Live (24k) ──▶ VoiceChatHandler._send_voice_response
                          ├──▶ response_chunk (browser, audio b64)         [existente]
                          └──▶ VoiceAvatarSession.speak(pcm_24k)            [FEAT-245]
                                 └──▶ AvatarWebSocket.send_audio_frame → LiveAvatar
                                        └──▶ LiveKit room ──▶ Browser (vídeo+audio avatar)
```

**Componentes nuevos** (`packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/`):

- `VoiceAvatarSession` (`voice_session.py`) — wrapper de ciclo de vida: arranca la sesión
  LiveAvatar, mintea tokens LiveKit, expone `viewer_credentials`, `speak()`, `finish_turn()`,
  `interrupt()`, `aclose()`.
- `AvatarWebSocket` (`avatar_ws.py`) — transporte WS al media server (protocolo LITE):
  trocea el PCM (primer chunk ~400 ms, resto ~1 s, tope 1 MB) y emite frames
  `{"type":"agent.speak","audio":"<b64>"}`, `agent.speak_end`, `agent.interrupt`.
- `LiveKitRoomManager` (`room_manager.py`) — mintea `client_token` (subscribe-only, para el
  navegador) y `agent_token` (publish, **solo servidor**).
- `is_avatar_enabled` (`optin.py`) — gate de opt-in por tenant/agente (default-deny).

### 4.2 Cómo lo activa el frontend

En `start_session`, añade los campos de avatar:

```jsonc
{
  "type": "start_session",
  "streaming_mode": "streaming",
  "config": { "voice_name": "Puck", "language": "en-US" },
  "avatar": true,
  "avatar_id": "5761a14c",      // opcional: override del avatar
  "tenant_id": "acme"            // requerido para el gate de opt-in
}
```

La respuesta `session_started` incluye un bloque `avatar`:

```jsonc
// Caso OK (tenant habilitado, sesión arrancó):
{
  "type": "session_started",
  "session_id": "sess-abc",
  "config": { "voice_name": "Puck", "input_format": "audio/pcm;rate=16000",
              "output_format": "audio/pcm;rate=24000" },
  "avatar": {
    "active": true,
    "livekit_url": "wss://<project>.livekit.cloud",
    "client_token": "<JWT subscribe-only>",   // ← úsalo para unirte a la sala
    "room": "sess-abc",                        // = session_id
    "audio": "dual"                            // ← señal: silencia una fuente de audio
  }
}

// Caso degradado (no habilitado, error, o extra no instalado):
{ "type": "session_started", ...,
  "avatar": { "active": false, "reason": "avatar mode is not enabled for this tenant" } }
```

### 4.3 Reglas críticas del avatar para el frontend

1. **Degradación elegante**: si `avatar.active == false`, la voz funciona igual; muestra solo
   el modo voz-sin-cara. **Nunca** bloquees la conversación porque el avatar falle.
2. **Audio dual / eco**: cuando `avatar.active == true` y `avatar.audio == "dual"`, el audio
   llega por `/ws/voice` **y** por la sala LiveKit. **Silencia el audio de `/ws/voice`** y deja
   sonar solo la pista del avatar (lleva el lip-sync sincronizado). Si no, habrá eco/doble voz.
3. **Solo subscribe**: el `client_token` es **subscribe-only**. El navegador se une a la sala
   LiveKit como espectador (vídeo+audio del avatar). El micrófono del usuario **NO** se publica
   a LiveKit; sigue yendo por `/ws/voice`.
4. **Barge-in**: cuando llega `response_*.is_interrupted == true`, el servidor ya llama a
   `avatar.interrupt()`; tu UI solo debe vaciar su cola de audio local.
5. **Estructurados (charts/tablas/tool_call)** **no** viajan por LiveKit: llegan por `/ws/voice`
   (`tool_call`, `display_data`). Renderízalos en tu panel de chat como siempre.

### 4.4 Unirse a la sala LiveKit (cliente)

```js
import { Room, RoomEvent } from 'livekit-client';

async function joinAvatarRoom(avatar) {
  if (!avatar?.active) return null;
  const room = new Room({ adaptiveStream: true });
  await room.connect(avatar.livekit_url, avatar.client_token);

  room.on(RoomEvent.TrackSubscribed, (track, pub, participant) => {
    if (track.kind === 'video') {
      track.attach(document.getElementById('avatarVideo'));
    } else if (track.kind === 'audio') {
      track.attach();                  // reproduce la voz del avatar (con lip-sync)
      muteVoiceWsPlayback(true);       // ← silencia la fuente /ws/voice (evita eco)
    }
  });
  return room;
}
```

---

## 5. Implementación del frontend — receta completa

### 5.1 Captura de micrófono → PCM16 16 kHz

El navegador da audio float32 a la `sampleRate` del `AudioContext`. Hay que **downsamplear
a 16 kHz** y convertir a **PCM 16-bit little-endian**. Usa un `AudioWorklet` (no
`ScriptProcessorNode`, deprecado).

```js
// pcm-worklet.js  (AudioWorkletProcessor)
class PCMWorklet extends AudioWorkletProcessor {
  constructor() { super(); this._buf = []; }
  process(inputs) {
    const ch = inputs[0][0];
    if (ch) this.port.postMessage(ch.slice(0));   // float32 @ contextRate
    return true;
  }
}
registerProcessor('pcm-worklet', PCMWorklet);
```

```js
// main.js — captura + resample a 16k + PCM16
async function startMic(ws) {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true }
  });
  const ctx = new AudioContext();                 // p.ej. 48000 Hz
  await ctx.audioWorklet.addModule('pcm-worklet.js');
  const src = ctx.createMediaStreamSource(stream);
  const node = new AudioWorkletNode(ctx, 'pcm-worklet');

  node.port.onmessage = (e) => {
    const pcm16 = floatTo16kPCM(e.data, ctx.sampleRate);  // ↓ ver helper
    if (ws.readyState === WebSocket.OPEN) ws.send(pcm16); // ← BINARIO, lo más eficiente
  };
  src.connect(node);
  return { ctx, stream };
}

// downsample lineal a 16 kHz + Int16
function floatTo16kPCM(float32, inRate) {
  const ratio = inRate / 16000;
  const outLen = Math.floor(float32.length / ratio);
  const out = new Int16Array(outLen);
  for (let i = 0; i < outLen; i++) {
    const s = Math.max(-1, Math.min(1, float32[Math.floor(i * ratio)]));
    out[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
  }
  return out.buffer;  // ArrayBuffer PCM16 16k mono LE
}
```

### 5.2 Reproducción del audio 24 kHz del servidor

`response_chunk.audio_base64` es **PCM16 24k mono**. Decodifícalo y encólalo en un
`AudioContext` a 24 kHz para reproducción continua sin cortes.

```js
class PCMPlayer {
  constructor(sampleRate = 24000) {
    this.ctx = new AudioContext({ sampleRate });
    this.nextTime = 0;
    this.sources = [];
  }
  enqueueBase64Pcm16(b64) {
    const bytes = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
    const i16 = new Int16Array(bytes.buffer);
    const f32 = Float32Array.from(i16, v => v / 0x8000);
    const buf = this.ctx.createBuffer(1, f32.length, this.ctx.sampleRate);
    buf.copyToChannel(f32, 0);
    const node = this.ctx.createBufferSource();
    node.buffer = buf; node.connect(this.ctx.destination);
    const t = Math.max(this.ctx.currentTime, this.nextTime);
    node.start(t);
    this.nextTime = t + buf.duration;
    this.sources.push(node);
  }
  flush() {                       // barge-in: cortar reproducción inmediatamente
    this.sources.forEach(s => { try { s.stop(); } catch {} });
    this.sources = [];
    this.nextTime = 0;
  }
}
```

### 5.3 Cliente WebSocket de referencia

El repo ya incluye un cliente JS de ejemplo y dos páginas HTML completas:

- `packages/ai-parrot-integrations/src/parrot/voice/ui/basic.js` — clase `VoiceChatClient`.
- `packages/ai-parrot-integrations/src/parrot/voice/ui/voice_chat.html` — UI de voz completa.
- `packages/ai-parrot-integrations/src/parrot/voice/ui/chat.html` — UI de chat.

Esqueleto mínimo full-interactive (streaming + avatar opcional):

```js
const player = new PCMPlayer(24000);
let avatarRoom = null;

const ws = new WebSocket('wss://api.example.com/api/v1/ws/voice', ['jwt', JWT]);
ws.binaryType = 'arraybuffer';

ws.onmessage = async (ev) => {
  if (ev.data instanceof ArrayBuffer) return;          // (este server manda audio en JSON b64)
  const m = JSON.parse(ev.data);
  switch (m.type) {
    case 'connected':
      ws.send(JSON.stringify({
        type: 'start_session',
        streaming_mode: 'streaming',
        config: { voice_name: 'Puck', language: 'en-US' },
        avatar: USE_AVATAR, tenant_id: TENANT,
      }));
      break;

    case 'session_started':
      if (m.avatar?.active) {

…(truncated)…
