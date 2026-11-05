---
title: "Frontend Guide for SvelteKit: LiveAvatar FULL Mode and VoiceBot (FEAT 248)"
---

# Frontend Guide for SvelteKit: LiveAvatar FULL Mode and VoiceBot (FEAT 248)

**Audience**: the Frontend team that will build a **SvelteKit module** for
**talking by voice with an ai-parrot agent while showing a talking avatar**
(lip-sync) in real time.

**Scope**: FEAT-248 — *LiveAvatar FULL Mode — `speak_text` Integration*. Here
the browser does **not** publish raw microphone audio to your backend or run
TTS: the LiveKit room is managed by **LiveAvatar** (STT + TTS + video with
lip-sync). The ai-parrot backend only **mints the session** and returns
LiveKit credentials. **The conversation loop is driven by the frontend**:

```
user speaks → user.transcription (LiveAvatar STT)
            → you call the ai-parrot agent (text)
            → avatar.speak_text {text}  (the avatar speaks it, WITHOUT its LLM)
```

> ✅ **Backend status (2026-06-19).** FEAT-248 is **implemented and merged
> into `dev`** (branch `feat-248-liveavatar-fullmode-speaktext`). Real,
> verified code:
> - `packages/ai-parrot-server/src/parrot/handlers/avatar_fullmode.py` —
>   REST endpoints `start`/`stop`/`avatars`/`voices`/`transcript`.
> - `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/client.py` —
>   `create_full_session_token()`, `start_session()`, `list_avatars()`,
>   `list_voices()`, `get_session_transcript()`.
> - `…/liveavatar/models.py` — `FullModeConfig`, `FullModeSessionHandle`,
>   `TenantAvatarConfig`.
> - `…/liveavatar/optin.py` — `is_fullmode_enabled()` (per-tenant gate).
> - `…/liveavatar/fullmode_observer.py` — passive room observer
>   (server-side logging/transcription, **optional**).
> - `sdd/specs/liveavatar-fullmode-speaktext.spec.md` — specification.
>
> What is already **confirmed by spike** (`spike_q1_speaktext.py`, Q1 resolved):
> `avatar.speak_text` speaks **arbitrary text** in restricted mode (without
> `context_id` or `llm_configuration_id`), meaning the avatar **never**
> answers on its own with its internal LLM. You control what it says.

---

## 0. Index

1. [Mental model: who does what?](#1-mental-model-who-does-what)
2. [FULL Mode vs LITE (Phase A) vs native voice (Phase C)](#2-full-mode-vs-lite-vs-native-voice)
3. [Frontend dependencies](#3-frontend-dependencies)
4. [Step 1 — Start the session (`/fullmode/start`)](#4-step-1--start-the-session-fullmodestart)
5. [Step 2 — Connect to the LiveKit room and render the video](#5-step-2--connect-to-the-livekit-room-and-render-the-video)
6. [Step 3 — Event protocol (data channels)](#6-step-3--event-protocol-data-channels)
7. [Step 4 — The conversation loop](#7-step-4--the-conversation-loop)
8. [Step 5 — Call the ai-parrot agent (text)](#8-step-5--call-the-ai-parrot-agent-text)
9. [Step 6 — Stop the session (`/fullmode/stop`)](#9-step-6--stop-the-session-fullmodestop)
10. [Discovery endpoints (avatars / voices / transcript)](#10-discovery-endpoints)
11. [SvelteKit module architecture](#11-sveltekit-module-architecture)
12. [Security, gating, and error handling](#12-security-gating-and-error-handling)
13. [Implementation checklist](#13-implementation-checklist)
14. [Quick API reference](#14-quick-api-reference)

---

## 1. Mental model: who does what?

Three actors. **Memorize them**, because the split of responsibilities is what
distinguishes FULL Mode from the other modes.

| Actor | Responsibility |
|---|---|
| **LiveAvatar** (managed room) | STT (transcribes the user), TTS (synthesizes the avatar's voice) and **video with lip-sync**. It owns the LiveKit room. |
| **ai-parrot backend** (this repo) | Mints the FULL session, returns `livekit_url` + `livekit_client_token`, maintains keep-alive, and (optionally) observes the room for logging/transcription. **It does NOT run TTS/STT.** |
| **Frontend (you)** | Connects to the room, renders the video, **drives the loop**: receives `user.transcription`, calls the ai-parrot agent with text, and sends `avatar.speak_text` with the response. |

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
       │  ② <video> ← avatar video track (lip-sync) <──────────────────────────────────  │
       │  ③ receives `user.transcription` (agent-response) <──────────────────────────── │
       │                                                                                │
       │  ④ POST /bots/{agent}/stream/...  → agent text (ai-parrot)                     │
       │                                                                                │
       │  ⑤ sends `avatar.speak_text {text}` (agent-control) ─────────────────────────>│
       │  ⑥ the avatar speaks + emits `avatar.transcription.chunk` <──────────────────── │
```

**Key point**: the "brain" is ai-parrot, but the avatar is just a **dumb
mouth**. You send it text via `avatar.speak_text` and it says it. It never
decides what to say on its own (restricted mode).

---

## 2. FULL Mode vs LITE vs native voice

| | **FULL Mode (FEAT-248)** | **LITE / Phase A (FEAT-242)** | **Native voice / Phase C (FEAT-243)** |
|---|---|---|---|
| Who does TTS | LiveAvatar | ai-parrot (Supertonic ONNX, PCM pushed over WS) | LiveKit Agents (Cartesia plugin) |
| Who does STT | LiveAvatar | — (no voice input) | LiveKit Agents (Deepgram plugin) |
| Does the browser publish the microphone? | **Not to the backend** — LiveAvatar captures it in the room | No | Yes (to the room) |
| Conversation loop | **driven by the frontend** | the frontend | a LiveKit Agents worker |
| ai-parrot infra | minimal (gateway only) | Supertonic runtime | long-running LiveKit worker |
| Video transport | LiveKit room (`livekit_url`) | WS (`ws_url`) | LiveKit room |
| Credential for the browser | `livekit_client_token` | `ws_url` + token | token with audio publish |

> ⚠️ In FULL Mode, the session handle inherits `ws_url` from the base class
> (`AvatarSessionHandle`) but it is **empty and unused** — it only applies to
> LITE. Always use `livekit_url` + `livekit_client_token`.

This guide covers **FULL Mode only**. Phase C (LiveKit Agents worker) was removed
in FEAT-249; see the [Mode A / B / C / D taxonomy](liveavatar-frontend-guide.md)
for the updated map of voice modes.

---

## 3. Frontend dependencies

```bash
npm i livekit-client
# Optional, if LiveAvatar publishes the web SDK (preferred if available):
# npm i @heygen/liveavatar-web-sdk
```

- **`livekit-client`** — this is the guaranteed path: you connect to the room,
  subscribe to the avatar's video track, and use the **data channels** to
  send/receive events (`agent-control` / `agent-response`).
- **`@heygen/liveavatar-web-sdk`** — if available, it wraps the above and may
  expose helpers for sending/subscribing to events. Verify that it exposes
  `agent-control`/`agent-response`; if not, fall back to `livekit-client`
  directly (this guide uses `livekit-client`, which always works).

---

## 4. Step 1 — Start the session (`/fullmode/start`)

**Endpoint** (authenticated: `@is_authenticated()` + `@user_session()`):

```
POST /api/v1/avatar/fullmode/{agent_id}/start
```

`{agent_id}` is the logical name of the ai-parrot agent that will do the "thinking".

**Request body** (JSON):

```jsonc
{
  "session_id": "abc-123",      // REQUIRED. AgentChat session ID, shared with the browser
  "tenant_id": "acme",          // optional, for the per-tenant opt-in gate
  "agent_name": "support-bot"   // optional; defaults to the route's {agent_id}
}
```

**Response** (200, **viewer credentials only**):

```jsonc
{
  "session_id": "abc-123",
  "livekit_url": "wss://<project>.livekit.cloud",
  "livekit_client_token": "eyJhbGciOi..."   // subscribe-only JWT for the browser
}
```

> 🔒 `session_token`, `api_key`, or any server-side secret are **never**
> returned. The `livekit_client_token` is **subscribe-only** (the browser does
> not publish tracks; LiveAvatar does).

**Error codes you must handle**:

| Code | Meaning | Frontend action |
|---|---|---|
| `400` | missing `session_id` | client bug; check the body |
| `403` | the tenant does not have FULL mode enabled (`is_fullmode_enabled`) | show "avatar not available for your account" |
| `409` | there is already an active session for that `session_id` | reuse the existing session or generate a new `session_id` |
| `503` | the LiveAvatar stack is not installed or `LIVEAVATAR_*` config is missing | infrastructure error; retry/notify |

**Example (SvelteKit, fetch with session cookie credentials)**:

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
    credentials: 'include', // navigator_auth cookie
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

> ⏱️ The backend automatically starts a **keep-alive** (ping < 5 min) while the
> session is alive, and applies `max_session_duration` as a safety net for
> abandoned sessions. In **sandbox** the duration is capped at ~60s regardless
> of what you request. A FULL session consumes STT+TTS+video credits per minute:
> **always call `/stop`** when finished (see §9).

---

## 5. Step 2 — Connect to the LiveKit room and render the video

With `livekit_url` + `livekit_client_token`, connect with `livekit-client` and
subscribe to the avatar's video track:

```ts
import { Room, RoomEvent, Track, type RemoteTrack } from 'livekit-client';

export async function connectAvatarRoom(
  session: FullModeSession,
  videoEl: HTMLVideoElement
): Promise<Room> {
  const room = new Room({ adaptiveStream: true, dynacast: true });

  room.on(RoomEvent.TrackSubscribed, (track: RemoteTrack) => {
    if (track.kind === Track.Kind.Video) {
      track.attach(videoEl);          // <video> ← avatar lip-sync
    } else if (track.kind === Track.Kind.Audio) {
      track.attach();                 // avatar audio (TTS voice)
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

> The browser is **subscriber-only**: it does not publish its own camera or
> microphone. LiveAvatar captures the user's microphone inside its own managed
> room and emits the avatar's video as a remote track.

---

## 6. Step 3 — Event protocol (data channels)

The entire conversation travels as **JSON messages over LiveKit data channels**,
on two topics:

- **`agent-control`** → **you send** (commands to the avatar).
- **`agent-response`** → **you receive** (transcriptions and avatar state).

**Envelope confirmed by spike (flat, not nested)**:

```jsonc
{
  "event_id": "<uuid>",          // generate one per message you send
  "event_type": "avatar.speak_text",
  "session_id": "<liveavatar-session-id>",
  "source_event_id": null,        // in response events, correlates with the command
  "text": "<text>"                // optional payload depending on the event
}
```

### 6.1 What you send on `agent-control`

| `event_type` | Payload | Use |
|---|---|---|
| `avatar.speak_text` | `{text}` | **Speak the agent's text (no LLM)** — primary output. ✅ verified. |
| `avatar.interrupt` | — | Barge-in: cuts off and clears the speech queue |
| `avatar.start_listening` / `avatar.stop_listening` | — | "Listening" UX hint |
| `user.start_push_to_talk` / `user.stop_push_to_talk` | — | Only with `interactivity_type = PUSH_TO_TALK` |

### 6.2 What you receive on `agent-response`

| `event_type` | Payload | Use |
|---|---|---|
| `user.transcription` | `{text}` | **STT output** — what the user said (triggers the loop) |
| `user.speak_started` / `user.speak_ended` | — | Turn boundaries / trigger barge-in |
| `avatar.speak_started` / `avatar.speak_ended` | `{source_event_id}` | Avatar speech state (correlated with the command that originated it) |
| `avatar.transcription.chunk` | `{text}` | ✅ (verified, undocumented) spoken text **word by word** while the avatar speaks |
| `avatar.transcription` | `{text}` | Full spoken text, delivered once |
| `session.stopped` | `{end_reason}` | Teardown: `IDLE_TIMEOUT`, `MAX_DURATION_REACHED`, `NO_CREDITS`, … |

### 6.3 Send and receive with `livekit-client`

```ts
const encoder = new TextEncoder();
const decoder = new TextDecoder();

// SEND a command on agent-control
async function sendControl(room: Room, eventType: string, text?: string) {
  const envelope = {
    event_id: crypto.randomUUID(),
    event_type: eventType,
    session_id: liveavatarSessionId, // see note below
    source_event_id: null,
    ...(text !== undefined ? { text } : {})
  };
  await room.localParticipant.publishData(
    encoder.encode(JSON.stringify(envelope)),
    { reliable: true, topic: 'agent-control' }
  );
}

// RECEIVE events on agent-response
room.on(RoomEvent.DataReceived, (payload, _participant, _kind, topic) => {
  if (topic !== 'agent-response') return;
  const evt = JSON.parse(decoder.decode(payload));
  handleAgentResponse(evt); // see §7
});
```

> ℹ️ **`session_id` in the envelope** is the **LiveAvatar session id**, not the
> AgentChat `session_id`. You will see it in the incoming `agent-response`
> events themselves; cache it from the first event received. The backend knows
> it as `liveavatar_session_id` but **does not expose it** in the `/start`
> response (it is only needed for the transcript endpoint, §10).

---

## 7. Step 4 — The conversation loop

The frontend orchestrates everything. Minimal loop:

```ts
async function handleAgentResponse(evt: any) {
  switch (evt.event_type) {
    case 'user.transcription': {
      const userText = evt.text?.trim();
      if (!userText) return;
      // 1) render the user's turn in the chat
      appendMessage({ role: 'user', text: userText });

      // 2) interrupt if the avatar was speaking (barge-in)
      if (avatarIsSpeaking) await sendControl(room, 'avatar.interrupt');

      // 3) ask the ai-parrot agent (§8) and have the avatar speak it
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
      // sync word-by-word subtitles with the avatar's speech
      appendAvatarChunk(evt.text);
      break;
    case 'session.stopped':
      onSessionStopped(evt.end_reason);
      break;
  }
}
```

### 7.1 End-to-end streaming (recommended)

For low latency, **do not wait for the agent's complete response**. Pair
ai-parrot's per-sentence `ask_stream` (§8) with one `avatar.speak_text` per
sentence, and let `avatar.transcription.chunk` sync the UI:

```ts
async function askAgentAndSpeak(userText: string) {
  for await (const sentence of streamAgentSentences(agentId, sessionId, userText)) {
    await sendControl(room, 'avatar.speak_text', sentence); // speak sentence by sentence
  }
}
```

> The avatar queues the `speak_text` commands and speaks them in order. If the
> user interrupts, send `avatar.interrupt` to clear the queue before the next
> turn.

---

## 8. Step 5 — Call the ai-parrot agent (text)

The avatar is the mouth; **the text comes from the ai-parrot agent**. Use the
server's existing streaming endpoints (`handlers/stream.py`):

```
POST /bots/{bot_id}/stream/sse      # Server-Sent Events
POST /bots/{bot_id}/stream/ndjson   # NDJSON
POST /bots/{bot_id}/stream/chunked  # chunked transfer
GET  /bots/{bot_id}/stream/ws       # WebSocket
```

Minimal body: `{ "prompt": "<user text>", ... }` (the remaining keys are
passed as kwargs to `ask_stream`).

Recommended strategy for FULL Mode: **group the stream chunks into complete
sentences** (the avatar speaks sentences better than isolated words) and emit
one `avatar.speak_text` per sentence. You can conceptually reuse the backend's
sentence flattener — in the frontend it is enough to split on `.?!` when the
buffer grows:

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
    // split by NDJSON lines, extract the text, accumulate until a sentence closes
    // ...emit each complete sentence with `yield sentence;`
  }
  if (buffer.trim()) yield buffer.trim();
}
```

> The `session_id` you pass to the agent **must be the same** one you used in
> `/fullmode/start`, so that the structured outputs (charts, data, canvas) the
> agent emits reach the same AgentChat channel your UI is already listening on.

---

## 9. Step 6 — Stop the session (`/fullmode/stop`)

**Endpoint** (authenticated):

```
POST /api/v1/avatar/fullmode/{agent_id}/stop
```

Body: `{ "session_id": "abc-123" }`. **Response: `204 No Content`**
(idempotent — an unknown/expired `session_id` also returns 204).

The backend performs `stop_session` + cancels the keep-alive + closes the HTTP client.

```ts
export async function stopFullModeSession(agentId: string, sessionId: string): Promise<void> {
  await fetch(`/api/v1/avatar/fullmode/${agentId}/stop`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ session_id: sessionId })
  });
  // and disconnect from the room locally
}
```

> 🧹 **Essential** in the component's `onDestroy` and in
> `beforeunload`/`pagehide`: a session without `/stop` keeps burning credits
> until `max_session_duration`. Call `room.disconnect()` and `/stop`.

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

## 10. Discovery endpoints

All authenticated, all read-only (proxy to the LiveAvatar API with a
server-side `X-API-KEY`). They do **not** require avatar opt-in.

| Endpoint | Response | Use |
|---|---|---|
| `GET /api/v1/avatar/avatars?tenant_id=` | `{ "avatars": [...] }` | Populate an avatar selector |
| `GET /api/v1/avatar/voices?tenant_id=` | `{ "voices": [...] }` | Populate a voice selector |
| `GET /api/v1/avatar/session/{session_id}/transcript` | transcript dict | Retrieve the transcript of a finished session (`{session_id}` = LiveAvatar id) |

```ts
export async function listAvatars(tenantId?: string) {
  const q = tenantId ? `?tenant_id=${encodeURIComponent(tenantId)}` : '';
  const res = await fetch(`/api/v1/avatar/avatars${q}`, { credentials: 'include' });
  const { avatars } = await res.json();
  return avatars;
}
```

> ⚠️ The **selection** of `avatar_id`/`voice_id`/`language`/`interactivity_type`
> used when creating the session is resolved by the **backend** per tenant (env +
> DB override via `resolve_fullmode_config`). Today `/start` **does not accept**
> avatar/voice in the body — it uses the tenant config. These listings serve
> admin UIs or a future extension of the `/start` contract.

---

## 11. SvelteKit module architecture

Suggested structure (Svelte 5 + runes):

```
src/lib/avatar-fullmode/
├── api/
│   ├── avatarFullmode.ts     // start/stop + listings (§4, §9, §10)
│   └── agentStream.ts        // streamAgentSentences (§8)
├── livekit/
│   ├── room.ts               // connectAvatarRoom (§5)
│   └── dataChannel.ts        // sendControl + agent-response parser (§6)
├── state/
│   └── conversation.svelte.ts // loop state: turns, avatarIsSpeaking, subtitles
└── components/
    ├── AvatarStage.svelte    // <video> + status overlay
    ├── ConversationLog.svelte// turn history + subtitles
    └── AvatarSession.svelte   // orchestrates: start → connect → loop → stop
```

**Session state machine** (useful for the UI):

```
idle → starting (POST /start) → connecting (room.connect)
     → live (listening / speaking) → stopping (POST /stop) → idle
                                     ↘ error (403/409/503 or session.stopped)
```

`AvatarSession.svelte` (skeleton):

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

## 12. Security, gating, and error handling

- **Authentication**: all endpoints sit behind `@is_authenticated()` +
  `@user_session()` (navigator_auth). Always send `credentials: 'include'`.
- **Secrets**: `/start` returns **only** `livekit_url` +
  `livekit_client_token` (subscribe-only). You will never receive `api_key` or
  `session_token`. Do not try to mint LiveKit tokens on the client.
- **Per-tenant opt-in** (`403`): FULL Mode is *default-deny*. The backend checks
  `LIVEAVATAR_FULLMODE_ENABLED_TENANTS` (comma-separated list; `*` = all).
  If you get a 403, the tenant is not enabled.
- **One session per `session_id`** (`409`): the backend rejects a second
  `/start` with the same active `session_id`. Handle the 409 by reusing or
  regenerating the id.
- **`session.stopped`**: treat it as a remote teardown. Depending on `end_reason`
  (`NO_CREDITS`, `MAX_DURATION_REACHED`, `IDLE_TIMEOUT`), show the appropriate
  message and return to `idle`. Do not assume `/stop` has already run: call it
  anyway (it is idempotent).
- **Credits**: every minute of session consumes STT+TTS+video. Always close.

---

## 13. Implementation checklist

- [ ] `POST /fullmode/start` with `session_id` (+ `tenant_id` if applicable), handle 403/409/503.
- [ ] Connect `livekit-client` with `livekit_url` + `livekit_client_token`, attach the `<video>`.
- [ ] Subscribe to `RoomEvent.DataReceived` filtering on `topic === 'agent-response'`.
- [ ] Parse the flat envelope (`event_type`, `text`, `source_event_id`).
- [ ] Loop: `user.transcription` → ai-parrot `ask_stream` → `avatar.speak_text` per sentence.
- [ ] Barge-in: `avatar.interrupt` when the user talks over the avatar.
- [ ] Subtitles: render `avatar.transcription.chunk` word by word.
- [ ] Same `session_id` in `/start` and in the agent calls (for structured artifacts).
- [ ] `onDestroy` + `pagehide`: `room.disconnect()` + `POST /fullmode/stop`.
- [ ] Handle `session.stopped` with `end_reason`.
- [ ] (Admin) `GET /avatars` and `/voices` for selectors.

---

## 14. Quick API reference

### REST (ai-parrot backend)

| Method | Route | Body / Query | Response |
|---|---|---|---|
| POST | `/api/v1/avatar/fullmode/{agent_id}/start` | `{session_id, tenant_id?, agent_name?}` | `{session_id, livekit_url, livekit_client_token}` |
| POST | `/api/v1/avatar/fullmode/{agent_id}/stop` | `{session_id}` | `204` |
| GET | `/api/v1/avatar/avatars` | `?tenant_id=` | `{avatars: [...]}` |
| GET | `/api/v1/avatar/voices` | `?tenant_id=` | `{voices: [...]}` |
| GET | `/api/v1/avatar/session/{session_id}/transcript` | — | transcript dict |
| POST | `/bots/{bot_id}/stream/{sse\|ndjson\|chunked}` | `{prompt, session_id, ...}` | agent text stream |

### Data channels (LiveKit)

| Topic | Direction | Key events |
|---|---|---|
| `agent-control` | frontend → avatar | `avatar.speak_text {text}`, `avatar.interrupt`, `avatar.start/stop_listening`, `user.start/stop_push_to_talk` |
| `agent-response` | avatar → frontend | `user.transcription {text}`, `user.speak_started/ended`, `avatar.speak_started/ended {source_event_id}`, `avatar.transcription.chunk {text}`, `avatar.transcription {text}`, `session.stopped {end_reason}` |

### Event envelope

```jsonc
{ "event_id": "<uuid>", "event_type": "<...>", "session_id": "<liveavatar-id>",
  "source_event_id": "<uuid|null>", "text": "<optional>" }
```

---

### Structured outputs channel — `/ws/userinfo` (FEAT-249 Mode B)

The `/ws/userinfo` channel is the delivery surface for **structured payloads**
generated by the agent (charts, data, tool calls). It is independent of
LiveKit — it is ai-parrot's own WebSocket.

#### Subscription protocol

1. **Connect** to the WebSocket `wss://<host>/ws/userinfo` (requires session authentication).
2. **Subscribe** to the agent's channel by sending:

```jsonc
{ "type": "subscribe", "content": { "channel": "<session_id>" } }
```

The backend confirms with:

```jsonc
{ "type": "subscribed", "channel": "<session_id>" }
```

3. **Receive** `StructuredOutputMessage` envelopes when the agent produces structured output:

```jsonc
{
  "type": "<chart|data|canvas|tool_call>",
  "session_id": "<session_id>",
  "payload": { /* type-dependent content */ },
  "turn_id": "<turn-id | null>"
}
```

#### `type` values

| Value | Meaning |
|---|---|
| `chart` | Visual artifact (chart, infographic) |
| `data` | Tabular data or structured JSON |
| `canvas` | Canvas content |
| `tool_call` | Tool call result |

#### Full Mode B flow

```
Frontend                      ai-parrot
   │                              │
   │── POST /api/v1/agents/chat ──▶│  (avatar_bifurcate=true in body)
   │                              │── agent generates response + structured output
   │◀── text (stream) ────────────│
   │◀── StructuredOutputMessage ──│  (published via Redis → /ws/userinfo → browser)
   │    on channel <session_id>   │
```

> **Multi-worker architecture note**: `broadcast_to_channel` in
> `UserSocketManager` is in-process. For the payload to reach the worker that
> serves the browser's WebSocket connection, the agent first publishes to the
> Redis transport (`RedisBroadcastForwarder`) and the Redis subscriber
> (`run_output_subscriber`) forwards it locally with `broadcast_to_channel`.

---

**Related documents**:
- Backend specification: `sdd/specs/liveavatar-fullmode-speaktext.spec.md` (FEAT-248)
- Native voice (Phase C): ~~[`liveavatar-phase-c-frontend-guide.md`](liveavatar-phase-c-frontend-guide.md)~~ *(removed in FEAT-249)*
- LITE (Phase A): [`liveavatar-frontend-guide.md`](liveavatar-frontend-guide.md)
