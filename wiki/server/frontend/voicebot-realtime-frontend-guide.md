---
title: "VoiceBot · VoiceChatHandler · FEAT 245 — Frontend Guide for Realtime Conversation with Agents"
---

# VoiceBot · VoiceChatHandler · FEAT 245 — Frontend Guide for Realtime Conversation with Agents

> **Purpose of this document**: give a frontend team everything needed to
> build a **fully interactive, realtime, WebSocket-based** UI that talks to an
> AI-Parrot agent by voice — including the **avatar with lip-sync** mode (FEAT-245).
>
> It covers three layers:
> 1. **`VoiceBot`** — the voice brain (Gemini Live, native bidirectional audio).
> 2. **`VoiceChatHandler`** — the aiohttp handler that exposes `/ws/voice` to the browser.
> 3. **FEAT-245** — the audio "tee" that moves the mouth of a LiveAvatar/LiveKit avatar.
>
> Everything described here was verified against the code in `packages/ai-parrot` and
> `packages/ai-parrot-integrations` (state: `dev`, June 2026; avatar section
> updated for FEAT-536, September 2026).
>
> **Working reference**: `examples/clients/voice/` serves EVERYTHING described in this guide
> as a real, runnable page — Gemini/Nova provider toggle, capabilities panel,
> `tool_call`/`display_data`, the **Avatar** control (off by default, with tenant/agent ID),
> the avatar video/audio with the single-source policy, the **Enable avatar
> audio** button for blocked autoplay, and the **Interrupt / speak-again** control. Read it alongside this
> guide — `examples/clients/voice/README.md` documents the full acceptance runbook
> (startup, prerequisites, scenario matrix).

---

## 0. Mental map in 30 seconds

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
                          │  VoiceBot → GeminiLiveClient | NovaClient        │
                          │   · Gemini 2.5 native-audio / Nova 2 Sonic      │
                          │   · VAD · STT in/out · tools · interrupción     │
                          └───────────────────────────────────────────────┘
                                              │  (FEAT-245: tee del MISMO audio 24k)
                                              ▼
                          VoiceAvatarSession.speak(pcm) → AvatarWebSocket → LiveAvatar → LiveKit room
```

**The three golden rules of the frontend:**

1. **Input**: microphone → **PCM 16-bit, 16 kHz, mono** → send as **binary** (preferred) or base64.
2. **Output**: the server sends **PCM 16-bit, 24 kHz, mono** inside `response_chunk.audio_base64`.
3. **Avatar (FEAT-245, single-source policy refined in FEAT-536)**: if you request
   `avatar:true`, the browser may receive the audio **twice** (over `/ws/voice` and over the
   LiveKit room) — at most **one** should play at a time. But **do not mute it
   unconditionally on connect**: keep playing `/ws/voice` while the avatar track
   is not yet playable (connecting, autoplay blocked, or muted), and only
   then switch — muting the `/ws/voice` source and letting the avatar track play (the
   one with lip-sync). See §4.3/§4.4 for the exact sequence.

---

## 1. `VoiceBot` — the voice brain

**File**: `packages/ai-parrot/src/parrot/bots/voice.py`

```python
class VoiceBot(A2AEnabledMixin, BaseBot):
```

`VoiceBot` is an AI-Parrot bot specialized in voice. It is **multi-provider**: internally
it uses `GeminiLiveClient` (Gemini 2.5 with native audio) or `NovaClient` (Amazon Nova 2 Sonic),
depending on `voice_config.provider` — `"google_live"` (default) or `"nova"` (FEAT-315/FEAT-418).
The voice provider selection is **independent** of the text `llm` you pass; both
clients implement the same `VoiceCapable` protocol (`stream_voice()` →
`AsyncIterator[LiveVoiceResponse]`), so everything described in the rest of this guide —
WS frame format, `tool_call`/`display_data`, avatar — applies equally to both.

### 1.1 Construction

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
        enable_vad=True,                      # automatic turn detection
        enable_input_transcription=True,      # user STT
        enable_output_transcription=True,     # assistant STT
    ),
)
await bot.configure()   # async initialization (Redis memory by default)
```

`VoiceConfig` (`packages/ai-parrot/src/parrot/models/voice.py`):

| Field | Default | Note |
|---|---|---|
| `provider` | `"google_live"` | `"google_live"` (Gemini Live) or `"nova"` (Amazon Nova 2 Sonic) |
| `voice_name` | `"Puck"` | prebuilt voice of the active provider — `"Puck"`/`"Charon"`/... for Gemini, `"matthew"`/... for Nova |
| `language` | `"en-US"` | BCP-47 |
| `input_format` | `PCM_16K` | what the browser **must** send |
| `output_format` | `PCM_24K` | what the server returns |
| `temperature` | `0.7` | |
| `max_tokens` | `4096` | |
| `enable_vad` | `True` | automatic turn-taking |
| `enable_input_transcription` | `True` | enables the `transcription` event (user) |
| `enable_output_transcription` | `True` | assistant transcription |

### 1.2 Key methods (what the handler consumes)

| Method | Signature (abridged) | Use |
|---|---|---|
| `ask_stream(audio_input, session_id, user_id)` | `AsyncIterator[LiveVoiceResponse]` | **bidirectional streaming** — the heart of realtime mode |
| `ask_voice(audio_input, ...)` | `-> LiveVoiceResponse` | one-shot: full buffer → full response (buffered mode) |
| `ask(question: str, ...)` | `AsyncIterator[LiveVoiceResponse]` | text → voice (TTS / testing) |
| `configure(app=None)` | `-> None` | async initialization; Redis memory by default |

`ask_stream` accepts as `audio_input` **either a complete `bytes` or an `AsyncIterator[bytes]`** of
PCM16/16k chunks. The handler passes it a generator that reads from an `asyncio.Queue` fed
by the frames arriving from the WebSocket.

### 1.3 `LiveVoiceResponse` — the object that flows in every chunk

**File**: `packages/ai-parrot/src/parrot/models/voice.py` — the same dataclass is produced
by both `GeminiLiveClient` (`packages/ai-parrot-client-google/src/parrot/clients/google/live.py`)
and `NovaClient` (`packages/ai-parrot-client-amazon/src/parrot/clients/amazon/nova/audio.py`),
so the handler never needs to branch per provider.

```python
@dataclass
class LiveVoiceResponse:
    text: str = ""
    audio_data: Optional[bytes] = None
    audio_format: str = "audio/pcm;rate=24000"
    is_complete: bool = False        # end of turn
    is_interrupted: bool = False     # barge-in (user cut in)
    tool_calls: List[LiveToolCall] = []
    usage: Optional[LiveCompletionUsage] = None
    turn_metadata: Optional[VoiceTurnMetadata] = None
    session_id / turn_id / user_id
    role: Optional[str] = None       # "user" | "assistant" — canonical envelope (FEAT-418)
    metadata: Dict[str, Any] = {}    # display_data, go_away, reconnect_required...
```

> **Canonical envelope (FEAT-418)**: `role` is the attribute that determines whether a chunk is
> a **user** transcription (`role="user"`) or **assistant** text/audio
> (`role="assistant"`) — lowercase, the same for both providers (Gemini Live and Nova 2
> Sonic). The handler translates `role` into `transcription {is_user: true|false}` in the WS frame (see
> §3.2, "Server → Client" table) — the wire protocol (`transcription.is_user`) **did not
> change**, only the internal source of the data in Python. The `metadata["user_transcription"]` key (and its counterpart
> `metadata["assistant_transcription"]`) no longer exist — do not read them if you consume
> `LiveVoiceResponse` directly (e.g. if you write your own handler).

The handler translates each `LiveVoiceResponse` into one or more WebSocket messages
(`response_chunk`, `transcription`, `tool_call`, `display_data`, `response_complete`).

### 1.4 VAD, turn-taking and interruption (what matters for UX)

`GeminiLiveClient` configures **automatic voice activity detection (VAD)**:

```python
realtime_input_config=types.RealtimeInputConfig(
    automatic_activity_detection=types.AutomaticActivityDetection(
        disabled=False,
        start_of_speech_sensitivity=START_SENSITIVITY_HIGH,
        end_of_speech_sensitivity=END_SENSITIVITY_HIGH,
        prefix_padding_ms=100,
        silence_duration_ms=500,   # 500 ms of silence closes the turn
    )
)
```

Implications for the frontend:

- **You do not need a push-to-talk button** in streaming mode: just send audio continuously;
  Gemini detects turn start/end. (Push-to-talk remains valid and useful in `buffered` mode.)
- **Barge-in**: if the user speaks while the assistant is responding, Gemini emits
  `is_interrupted=True`. The UI must **immediately flush its audio playback queue**
  on receiving `response_chunk.is_interrupted == true` or `response_complete.is_interrupted == true`.
- **End of turn**: `response_complete` + `ready_to_speak` signal that the assistant has finished.

---

## 2. `VoiceChatHandler` — the WebSocket endpoint

**File**: `packages/ai-parrot-integrations/src/parrot/voice/handler.py`

This is the aiohttp handler the browser consumes. (There is also `voice/server.py`, an alternative
standalone server; **to integrate into an aiohttp app use `VoiceChatHandler`**.)

### 2.1 Mounting on the server

```python
from aiohttp import web
from parrot.voice.handler import VoiceChatHandler

handler = VoiceChatHandler(
    bot_factory=lambda: create_voice_bot(name="Sales", voice_name="Puck", tools=[...]),
    require_auth=True,
    secret_key=os.environ["JWT_SECRET"],   # or a custom TokenValidator
    auth_timeout=30.0,
    ws_route="/ws/voice",
)

app = web.Application()
handler.setup_routes(app, prefix="/api/v1")   # → /api/v1/ws/voice (+ /health, /static)
web.run_app(app, host="0.0.0.0", port=8765)
```

Routes registered by `setup_routes(app, prefix, include_health=True, include_static=True)`:

| Route | Method | Purpose |
|---|---|---|
| `{prefix}/ws/voice` | GET (upgrade) | Voice WebSocket (main) |
| `{prefix}/health` | GET | health check |
| `{prefix}/static/*` | GET | serve assets (optional) |

### 2.2 Authentication (3 methods)

The handler validates a **JWT**. There are three ways to pass it; pick one:

| Method | How | When |
|---|---|---|
| **`Sec-WebSocket-Protocol`** (recommended) | `new WebSocket(url, ["jwt", token])` | most secure: validated **before** the upgrade |
| **Query param** | `new WebSocket(url + "?token=" + token)` | simple, but the token ends up in logs |
| **Post-connection message** | `ws.send({type:"auth", token})` | when the token is not available at connect time |

`TokenValidator` (`packages/ai-parrot/src/parrot/core/ws_auth.py`) resolves in order:
custom `validator_func` → `navigator_auth.SECRET_KEY` → `secret_key` fallback → fallback mode
(accepts any token; **testing only**). It returns an `AuthenticatedUser`
(`user_id`, `username`, `email`, `roles`, `permissions`).

> If `require_auth=False`, you can skip all the auth steps and start the session directly.

### 2.3 Session lifecycle

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

### 2.4 Modes: `streaming` vs `buffered`

Chosen in `start_session` with `streaming_mode` (default `"streaming"`).

| Aspect | `streaming` (recommended, fully interactive) | `buffered` (push-to-talk) |
|---|---|---|
| Audio input | frames sent continuously → queue → Gemini immediately | accumulated and sent all at once |
| Processing trigger | continuous (VAD detects turns) | `stop_recording` or `voice_complete` |
| Response | chunked (`response_chunk`) in realtime | complete (`voice_response`) |
| Latency | low | higher |
| Use case | natural conversation, barge-in | mobile, offline recording |

---

## 3. Complete WebSocket protocol

> Verified against `_handle_message` and the handlers in `handler.py`.

### 3.1 Client → Server

| `type` | Payload | Effect |
|---|---|---|
| `auth` | `{token}` **or** `{authorization:"Bearer <jwt>"}` | post-connection authentication |
| `ping` | `{timestamp?}` | keepalive (replies `pong`) |
| `start_session` | `{config:{...}, streaming_mode?, avatar?, avatar_id?, tenant_id?}` | starts a voice session |
| `end_session` | `{}` | ends the session |
| `reset_session` | `{}` | end + restart |
| `start_recording` | `{}` | marks recording start (buffered); **also** the message to use for an explicit "Interrupt / speak-again" button (FEAT-536) — resending it while a response is in progress interrupts the active avatar (if any) and replaces the current turn; **do not** invent a new message for this |
| `stop_recording` | `{}` | end of recording → processes the buffer |
| `audio_data` / `audio_chunk` | `{data:"<base64 PCM16 16k>"}` | audio chunk via JSON |
| `send_text` / `text_message` | `{text:"...", streaming?}` | text input → spoken response |
| `voice_complete` / `voice_buffer` | `{audio_base64:"..."}` | complete buffer (non-streaming) |
| **(binary)** | raw PCM16 16k bytes | **most efficient way** to send audio |

**`config` of `start_session`:**

```jsonc
{
  "voice_name": "Puck",        // optional
  "language": "en-US",         // optional
  "system_prompt": "...",      // optional, prompt override
  "model": "gemini-3.8-live",   // optional
  "send_welcome": false         // optional, initial greeting
}
```

**Avatar fields (FEAT-245, additive):** `avatar: true`, `avatar_id?`, `tenant_id?`
(see §4).

### 3.2 Server → Client

| `type` | Payload | When |
|---|---|---|
| `connected` | `{session_id, authenticated, require_auth}` | on connect |
| `auth_success` | `{user:{user_id, username}}` | auth OK |
| `auth_error` | `{message}` | auth failed |
| `auth_required` | `{message}` | the server requires auth and none arrived |
| `session_started` | `{session_id, user_id, streaming_mode, config:{...}, avatar?}` | session ready |
| `ready_to_speak` | `{message}` | ready for new input (after `session_started` and after each turn) |
| `recording_started` | `{}` | recording started (buffered) |
| `recording_stopped` | `{message, duration_ms?}` | recording finished |
| `processing` | `{message, audio_size?}` | processing audio (buffered) |
| **`response_chunk`** | `{text, audio_base64, audio_format, is_interrupted}` | **response chunk (streaming)** |
| `voice_response` | `{text, audio_base64, audio_format, is_complete, usage?}` | complete response (buffered) |
| `response_complete` | `{text, is_interrupted}` | end of turn (streaming) |
| `transcription` | `{text, is_user}` | user (and/or assistant) STT |
| `tool_call` | `{name, arguments, result, execution_time_ms}` | tool executed |
| `display_data` | `{data}` | visual metadata from a tool (charts, tables...) |
| `pong` | `{timestamp, ping_count, session_id, session_active, ...}` | reply to `ping` |
| `session_ended` | `{session_id}` | session ended |
| `session_warning` | `{message, time_left?}` | Gemini is about to reconnect (GoAway) |
| `error` | `{message, code?, is_retryable?}` | error |

**Audio formats (in `session_started.config`):**

```
input_format:  "audio/pcm;rate=16000"   // lo que el navegador envía
output_format: "audio/pcm;rate=24000"   // lo que el servidor devuelve
```

> ⚠️ **`response_chunk` vs `voice_response`**: in **streaming** the audio arrives chunked in
> `response_chunk` and the turn closes with `response_complete`. In **buffered** a single
> `voice_response` arrives with `is_complete:true`. Your UI must handle both depending on the chosen mode.

> 🧠 The handler **filters out the model's "thoughts"** (text like `**Clarifying...**` or
> `**Show Product...**`) and **does not forward the assistant's transcription** to avoid duplicating
> the `response_chunk` text. That is, you get the assistant's text from the `text` of the
> chunks, not from a `transcription is_user:false` event.

---

## 4. FEAT-245 — Avatar with lip-sync (LiveAvatar + LiveKit)

**Spec**: `sdd/specs/voicechat-liveavatar-gemini.spec.md` (Gemini, TASK-1588/1589/1590 ✅) +
`sdd/specs/voicebot-liveavatar-implementation.spec.md` (Nova parity and viewer in the demo
UI, FEAT-536). **Status: complete and merged for both providers.**

### 4.1 What it does

Both Gemini Live and Nova 2 Sonic emit audio at **24 kHz mono 16-bit** — exactly
what the avatar's "mouth" expects (`AVATAR_PCM_SAMPLE_RATE = 24_000`), so the same tee
works unchanged for the active provider. FEAT-245/FEAT-536 **tee** (duplicate) that
same audio:
one copy goes to the browser (existing behavior) and another goes to the avatar, **without resampling**.

```
Gemini Live | Nova 2 Sonic (24k) ──▶ VoiceChatHandler._send_voice_response
                          ├──▶ response_chunk (browser, audio b64)         [existente]
                          └──▶ VoiceAvatarSession.speak(pcm_24k)            [FEAT-245]
                                 └──▶ AvatarWebSocket.send_audio_frame → LiveAvatar
                                        └──▶ LiveKit room ──▶ Browser (vídeo+audio avatar)
```

**New components** (`packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/`):

- `VoiceAvatarSession` (`voice_session.py`) — lifecycle wrapper: starts the LiveAvatar session,
  mints LiveKit tokens, exposes `viewer_credentials`, `speak()`, `finish_turn()`,
  `interrupt()`, `aclose()`.
- `AvatarWebSocket` (`avatar_ws.py`) — WS transport to the media server (LITE protocol):
  chunks the PCM (first chunk ~400 ms, the rest ~1 s, 1 MB cap) and emits frames
  `{"type":"agent.speak","audio":"<b64>"}`, `agent.speak_end`, `agent.interrupt`.
- `LiveKitRoomManager` (`room_manager.py`) — mints `client_token` (subscribe-only, for the
  browser) and `agent_token` (publish, **server only**).
- `is_avatar_enabled` (`optin.py`) — per-tenant/agent opt-in gate (default-deny).

### 4.2 How the frontend enables it

In `start_session`, add the avatar fields:

```jsonc
{
  "type": "start_session",
  "streaming_mode": "streaming",
  "config": { "voice_name": "Puck", "language": "en-US" },
  "avatar": true,
  "avatar_id": "5761a14c",      // optional: avatar override
  "tenant_id": "acme"            // required for the opt-in gate
}
```

The `session_started` response includes an `avatar` block:

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

### 4.3 Critical avatar rules for the frontend

1. **Graceful degradation**: if `avatar.active == false`, voice works just the same; show only
   the voice-without-face mode. **Never** block the conversation because the avatar fails.
2. **Dual audio / echo — single-source policy (FEAT-536)**: when `avatar.active ==
   true` and `avatar.audio == "dual"`, the audio may arrive over `/ws/voice` **and** over the LiveKit
   room — at most **one** source should play at any instant. **Do not mute it
   immediately upon subscribing to the track**: the avatar track may not be playable yet
   (connecting, blocked by autoplay, or muted). Follow the sequence: (a) while the avatar
   track is not playable, let `/ws/voice` play normally; (b) when the
   browser confirms it IS playable (`RoomEvent.AudioPlaybackStatusChanged` /
   `room.canPlaybackAudio`, and optionally after a user gesture via `Room.startAudio()`
   if autoplay blocked it) and the user chooses/defaults to avatar audio, mute the remote
   element, stop/clear the pending local PCM, stop playing new local chunks and only then unmute the avatar; (c) if the avatar fails/disconnects,
   go back to `/ws/voice` but **only for future chunks** — do not play a backlog that
   would duplicate what was already said. An explicit user mute is sticky: no automatic
   transition should undo it. Full implementation reference (injectable controller
   with a fake SDK for tests):
   `examples/clients/voice/static/avatar-viewer.js`'s `AvatarViewerController`.
3. **Subscribe only**: the `client_token` is **subscribe-only**. The browser joins the LiveKit room
   as a spectator (avatar video+audio). The user's microphone is **NOT** published
   to LiveKit; it keeps going over `/ws/voice`.
4. **Barge-in**: when `response_*.is_interrupted == true` arrives, the server already calls
   `avatar.interrupt()`; your UI only needs to flush its local audio queue.
5. **Structured data (charts/tables/tool_call)** does **not** travel over LiveKit: it arrives over `/ws/voice`
   (`tool_call`, `display_data`). Render it in your chat panel as usual.

### 4.4 Joining the LiveKit room (client)

> **Complete, tested reference**: `examples/clients/voice/static/avatar-viewer.js`
> (`AvatarViewerController`, FEAT-536) implements exactly this single-source
> policy — it registers listeners before connecting, never publishes microphone/camera, keeps
> a generation token to invalidate stale connections/events, and only switches to avatar
> audio when `room.canPlaybackAudio` confirms it is playable. The snippet below
> is a simplified version for illustration — use the real file as the implementation
> basis, do not rewrite this policy from scratch.

```js
import { Room, RoomEvent, Track } from 'livekit-client';

async function joinAvatarRoom(avatar, { onAvatarPlayable, onStopLocalPlayback } = {}) {
  if (!avatar?.active) return null;
  const room = new Room({ adaptiveStream: true });

  // Listeners BEFORE connect() — don't miss tracks already present when joining.
  room.on(RoomEvent.TrackSubscribed, (track) => {
    if (track.kind === Track.Kind.Video) {
      track.attach(document.getElementById('avatarVideo'));
      return;
    }
    if (track.kind === Track.Kind.Audio) {
      const audioEl = document.getElementById('avatarAudio');
      track.attach(audioEl);
      audioEl.muted = true; // starts muted — /ws/voice keeps playing
    }
  });
  room.on(RoomEvent.AudioPlaybackStatusChanged, () => {
    if (room.canPlaybackAudio) {
      // ONLY now is it safe to switch source: (1) mute the remote
      // element during the transition, (2) stop/clear the pending local
      // PCM, (3) stop playing new local chunks, (4)
      // unmute the avatar. See avatar-viewer.js for the full sequence
      // with generation guards and sticky explicit mute.
      onStopLocalPlayback?.();
      onAvatarPlayable?.();
    }
  });

  await room.connect(avatar.livekit_url, avatar.client_token);
  return room;
}
```

---

## 5. Frontend implementation — complete recipe

### 5.1 Microphone capture → PCM16 16 kHz

The browser gives float32 audio at the `AudioContext`'s `sampleRate`. You must **downsample
to 16 kHz** and convert to **PCM 16-bit little-endian**. Use an `AudioWorklet` (not
`ScriptProcessorNode`, which is deprecated).

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
// main.js — capture + resample to 16k + PCM16
async function startMic(ws) {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true }
  });
  const ctx = new AudioContext();                 // e.g. 48000 Hz
  await ctx.audioWorklet.addModule('pcm-worklet.js');
  const src = ctx.createMediaStreamSource(stream);
  const node = new AudioWorkletNode(ctx, 'pcm-worklet');

  node.port.onmessage = (e) => {
    const pcm16 = floatTo16kPCM(e.data, ctx.sampleRate);  // ↓ see helper
    if (ws.readyState === WebSocket.OPEN) ws.send(pcm16); // ← BINARY, the most efficient
  };
  src.connect(node);
  return { ctx, stream };
}

// linear downsample to 16 kHz + Int16
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

### 5.2 Playing the server's 24 kHz audio

`response_chunk.audio_base64` is **PCM16 24k mono**. Decode it and queue it in an
`AudioContext` at 24 kHz for continuous, gapless playback.

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
  flush() {                       // barge-in: cut playback immediately
    this.sources.forEach(s => { try { s.stop(); } catch {} });
    this.sources = [];
    this.nextTime = 0;
  }
}
```

### 5.3 Reference WebSocket client

The repo already includes an example JS client and two complete HTML pages:

- `packages/ai-parrot-integrations/src/parrot/voice/ui/basic.js` — `VoiceChatClient` class.
- `packages/ai-parrot-integrations/src/parrot/voice/ui/voice_chat.html` — complete voice UI.
- `packages/ai-parrot-integrations/src/parrot/voice/ui/chat.html` — chat UI.

Minimal fully interactive skeleton (streaming + optional avatar):

```js
const player = new PCMPlayer(24000);
let avatarRoom = null;

const ws = new WebSocket('wss://api.example.com/api/v1/ws/voice', ['jwt', JWT]);
ws.binaryType = 'arraybuffer';

ws.onmessage = async (ev) => {
  if (ev.data instanceof ArrayBuffer) return;          // (this server sends audio as b64 JSON)
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
        avatarRoom = await joinAvatarRoom(m.avatar);   // mutes /ws/voice inside
      }
      break;

    case 'ready_to_speak':
      await startMic(ws);                              // starts sending binary PCM16 16k
      break;

    case 'response_chunk':
      if (m.is_interrupted) player.flush();            // barge-in
      else if (m.audio_base64 && !avatarRoom) player.enqueueBase64Pcm16(m.audio_base64);
      if (m.text) appendAssistantText(m.text);
      break;

    case 'response_complete':
      if (m.is_interrupted) player.flush();
      finalizeAssistantTurn(m.text);
      break;

    case 'transcription':
      if (m.is_user) showUserBubble(m.text);
      break;

    case 'tool_call':    renderToolCall(m); break;     // name, args, result
    case 'display_data': renderArtifact(m.data); break;// charts/tables
    case 'session_warning': /* Gemini will reconnect */ break;
    case 'error':        showError(m.message); break;
  }
};

// keepalive
setInterval(() => ws.send(JSON.stringify({ type: 'ping' })), 30000);
```

### 5.4 UI state checklist

| UI state | Triggered by | Visual action |
|---|---|---|
| Connecting | `new WebSocket` | spinner |
| Connected / authenticated | `connected` / `auth_success` | enable "Start" |
| Session ready | `session_started` + `ready_to_speak` | enable microphone |
| Avatar active | `session_started.avatar.active` | show `<video>`, mute `/ws/voice` audio |
| User speaking | (VAD; optional `transcription is_user`) | "listening" waveform/indicator |
| Assistant speaking | `response_chunk` with audio | "speaking" waveform + play/lip-sync |
| Interrupted | `*.is_interrupted` | `player.flush()`, cut waveform |
| Turn complete | `response_complete` + `ready_to_speak` | back to "ready" |
| Tool | `tool_call` / `display_data` | tool card / artifact |
| Reconnection | `session_warning` | discreet notice, do not cut |
| Error | `error` | toast; retry if `is_retryable` |

---

## 6. Environment variables (server)

```bash
# Auth
JWT_SECRET=<secret>                       # o navigator_auth.SECRET_KEY

# Gemini Live (VoiceBot)
GOOGLE_API_KEY=<key>                      # o VertexAI (project/location/credentials)

# FEAT-245 — LiveAvatar
LIVEAVATAR_API_KEY=<secret>
LIVEAVATAR_AVATAR_ID=<avatar_id>
LIVEAVATAR_BASE_URL=https://api.liveavatar.com
LIVEAVATAR_SANDBOX=false                  # ⚠️ production avatar requires false (otherwise /start 400)
LIVEAVATAR_WS_CONNECT_TIMEOUT=5.0

# FEAT-245 — LiveKit Cloud
LIVEKIT_URL=wss://<project>.livekit.cloud
LIVEKIT_API_KEY=<key>
LIVEKIT_API_SECRET=<secret>

# FEAT-245 — opt-in gate (default-deny)
LIVEAVATAR_ENABLED_TENANTS=acme,demo      # or "*" for all
LIVEAVATAR_ENABLED_AGENTS=agent1,agent2   # optional, filters by agent
```

> The avatar extra is optional: `pip install ai-parrot-integrations[liveavatar]`. If it is not
> installed and you request `avatar:true`, the handler returns `avatar.active=false` (lazy import,
> graceful degradation) and `/ws/voice` works just the same.

---

## 7. Common errors and how to avoid them

| Symptom | Cause | Solution |
|---|---|---|
| Choppy audio / "chipmunk" | sending at the `AudioContext` sample rate (48k) instead of 16k | downsample to **16 kHz** before sending |
| The assistant does not respond | sending non-mono, non-PCM format, or never reaching `ready_to_speak` | mono, PCM16 16k, wait for `ready_to_speak` |
| **Echo / doubled voice** with avatar | you play audio from `/ws/voice` **and** from LiveKit at the same time | apply the single-source policy (§4.3/§4.4): mute `/ws/voice` only once `room.canPlaybackAudio` confirms the avatar track is playable, not on subscribe |
| **No audio** after enabling avatar | you muted `/ws/voice` unconditionally before the avatar track was playable (autoplay blocked) | let `/ws/voice` play until `room.canPlaybackAudio` is confirmed; offer an "Enable avatar audio" button that calls `Room.startAudio()` |
| The assistant does not stop when interrupted | you ignore `is_interrupted` | `player.flush()` on receiving it |
| Avatar does not appear | `avatar.active=false` | check `tenant_id` in opt-in + `LIVEAVATAR_SANDBOX` + extra installed |
| `/start` returns 400 | production avatar with `SANDBOX=true` | `LIVEAVATAR_SANDBOX=false` |
| Duplicated assistant text | you expected `transcription is_user:false` | the text comes in `response_chunk.text`; the server suppresses that transcription |
| Connection drops after a few minutes | no keepalive | send `ping` every ~30 s |

---

## 8. Code references (absolute paths)

**VoiceBot / Gemini Live and Nova 2 Sonic clients**
- `packages/ai-parrot/src/parrot/bots/voice.py` — `VoiceBot`
- `packages/ai-parrot/src/parrot/models/voice.py` — `VoiceConfig`, `LiveVoiceResponse`, `LiveToolCall`
- `packages/ai-parrot-client-google/src/parrot/clients/google/live.py` — `GeminiLiveClient`
- `packages/ai-parrot-client-amazon/src/parrot/clients/amazon/nova/audio.py` — `NovaClient` (Amazon Nova 2 Sonic, FEAT-315/FEAT-536)
- `packages/ai-parrot/src/parrot/core/ws_auth.py` — `TokenValidator`, `AuthenticatedUser`

**WebSocket handler**
- `packages/ai-parrot-integrations/src/parrot/voice/handler.py` — `VoiceChatHandler`, `WebSocketConnection`
- `packages/ai-parrot-integrations/src/parrot/voice/ui/basic.js` — reference JS client
- `packages/ai-parrot-integrations/src/parrot/voice/ui/voice_chat.html` — complete voice UI

**Working demo, both providers + avatar (FEAT-536)**
- `examples/clients/voice/server.py` — two `VoiceChatHandler`s (`/ws/gemini`, `/ws/nova`), the
  dual-output demo tool, and the `/voice-assets/livekit-client.umd.js` route
- `examples/clients/voice/static/dual_provider.html` — the complete page: provider
  toggle, capabilities panel, avatar, tool/data events panel, Interrupt
- `examples/clients/voice/static/avatar-viewer.js` — `AvatarViewerController`, the
  single-source policy implemented and tested (injectable SDK)
- `examples/clients/voice/README.md` — prerequisites (including the blocked LiveKit SDK) and
  the real-live acceptance runbook (§4/AC13)

**FEAT-245 — Avatar**
- `sdd/specs/voicechat-liveavatar-gemini.spec.md` — spec
- `sdd/tasks/index/voicechat-liveavatar-gemini.json` — tasks (all done)
- `.../integrations/liveavatar/voice_session.py` — `VoiceAvatarSession`
- `.../integrations/liveavatar/avatar_ws.py` — `AvatarWebSocket` (LITE protocol)
- `.../integrations/liveavatar/room_manager.py` — `LiveKitRoomManager` (tokens)
- `.../integrations/liveavatar/optin.py` — `is_avatar_enabled`
- `.../integrations/liveavatar/models.py` — Pydantic models
- `packages/ai-parrot-integrations/tests/voice/test_voicechat_avatar_integration.py` — e2e tests

**Related frontend guides**
- `wiki/server/frontend/liveavatar-frontend-guide.md` — Phase A (FEAT-242)
- ~~`wiki/server/frontend/liveavatar-phase-c-frontend-guide.md`~~ — Phase C (FEAT-243, removed in FEAT-249)
- `wiki/bots/frontend/agentalk-voice-frontend-guide.md` — AgentTalk voice
- `wiki/server/frontend/structured-artifacts-frontend-guide.md` — structured artifacts

**Related proposal (uncommitted)**
- `sdd/proposals/spec-liveavatar-fullmode-speaktext.md` — FULL Mode (`avatar.speak_text`),
  an alternative to FEAT-245 where the avatar speaks from text instead of raw PCM.
