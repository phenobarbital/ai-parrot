# Avatar Technical Guide (LiveAvatar Phase A) for Frontend

**Audience**: the Frontend team (AgentChat, Svelte 5) that needs to display a
**talking avatar with lip-sync** that speaks the agent's response, receiving
the **video + audio** in the browser.

**Scope**: FEAT-242 — *LiveAvatar — Phase A (avatar as the "mouth" of AgentChat)*.
The avatar is a **voice/video presentation layer, NOT a second brain**:
ai-parrot still resolves the whole turn (text, browser STT or `AgentVoiceTalk`
STT); the backend synthesizes the response to PCM and pushes it to the avatar.
The browser is **only a viewer** of a LiveKit Cloud room.

> This document is grounded in the real code merged into `dev`
> (branch `feat-242-liveavatar-phase-a-mouth`). The file paths are
> **verification anchors** (anti-hallucination); the semantic contract is
> what matters.
>
> Verified source files (2026-06-18):
> - `packages/ai-parrot-server/src/parrot/handlers/avatar.py` — `start`/`stop` endpoints
> - `packages/ai-parrot-server/src/parrot/handlers/agent_voice.py` — `AgentVoiceTalk` (`avatar` flag)
> - `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/room_manager.py` — LiveKit tokens
> - `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/orchestrator.py` — orchestrator (PCM push)
> - `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/models.py` — Pydantic models
> - `sdd/specs/liveavatar-phase-a-mouth.spec.md` — specification (FEAT-242)
> - `sdd/tasks/completed/TASK-009-frontend-livekit-viewer.md` — viewer contract

---

## 0. Index

1. [Mental model: the browser is a LiveKit viewer](#1-mental-model)
2. [The pieces: 3 HTTP calls + 1 LiveKit room](#2-the-pieces)
3. [Important clarification about "WebSockets"](#3-important-clarification-about-websockets)
4. [Step 1 — Start the avatar session (`/start`)](#4-step-1--start-the-avatar-session-start)
5. [Step 2 — Join the room and render the video (LiveKit)](#5-step-2--join-the-room-and-render-the-video-livekit)
6. [Step 3 — Talk to the agent (`avatar: true`)](#6-step-3--talk-to-the-agent-avatar-true)
7. [Step 4 — Close the session (`/stop`)](#7-step-4--close-the-session-stop)
8. [Per-tenant opt-in and error handling](#8-per-tenant-opt-in-and-error-handling)
9. [Structured outputs: they keep using the usual channel](#9-structured-outputs)
10. [Full example (TS, vanilla)](#10-full-example-ts-vanilla)
11. [Svelte 5 component (reference)](#11-svelte-5-component-reference)
12. [Frontend integration checklist](#12-frontend-integration-checklist)

---

## 1. Mental model

The avatar does **NOT** publish video from the browser, nor does the browser push audio.
Quite the opposite: the **backend** opens the avatar session, makes it join
*our* LiveKit Cloud room, and pushes the voice PCM to the LiveAvatar
media-server. The avatar publishes its **video + audio** tracks in the room. The
browser simply **subscribes** (subscribe-only) and renders them.

```
                         ┌──────────────────────── BACKEND (ai-parrot) ───────────────────────┐
 [Browser]               │                                                                     │
   │  1) POST /avatar/{id}/start ─────────────────▶  AvatarSessionOrchestrator                 │
   │     { session_id, tenant_id }                     │  ├─ LiveAvatarClient  (create/start)   │
   │  ◀── { livekit_url, client_token, session_id }    │  ├─ LiveKitRoomManager (mint tokens)   │
   │                                                   │  └─ AvatarWebSocket   (PCM push)       │
   │                                                   ▼                                        │
   │  2) join(livekit_url, client_token)  ───▶  LiveKit Cloud room  ◀── avatar publishes        │
   │     (subscribe video + audio)               (room = session_id)      lip-sync video/audio   │
   │  ◀═══════════════ <video>/<audio> tracks ═══════════════                                   │
   │                                                                                            │
   │  3) POST /voice/{id}  { avatar:true, query, tenant_id }  ─▶ ask_stream → Supertonic PCM ───┘
   │  ◀── { response, output, data, media, ... }   (text/structured for the UI)
   │                                                  the avatar SPEAKS through the room
   │  4) POST /avatar/{id}/stop  { session_id }  ─▶ stop_session + shutdown
   └──
```

**Practical consequences:**

- The browser uses the **`livekit-client`** (JS) library as a viewer. You
  don't need to know anything about low-level WebRTC; the SDK handles it.
- The browser **only receives `client_token`** (subscribe-only). The `agent_token`
  and the avatar media-server WS **never** leave the backend.
- The **room** is identified by the AgentChat **`session_id`** (you share it
  between the chat and the avatar).
- The avatar joins the room as a remote participant with identity
  **`avatar-agent`**. You subscribe to its remote tracks.
- **Structured outputs** (charts, data, canvas) **do not** travel over LiveKit;
  they keep arriving through the `/voice` envelope (or through the usual AgentChat WS).
  LiveKit is **face and voice only**.

---

## 2. The pieces

To display a talking avatar you need to orchestrate **3 HTTP calls** and **1
LiveKit room connection**:

| # | Action | Method / Route | Who |
|---|--------|----------------|-----|
| 1 | Start avatar session | `POST /api/v1/agents/avatar/{agent_id}/start` | Frontend |
| 2 | Join the room and render video | `livekit-client` → `room.connect(url, token)` | Frontend |
| 3 | Converse (the agent responds and the avatar speaks) | `POST /api/v1/agents/voice/{agent_id}` with `avatar: true` | Frontend |
| 4 | Close session | `POST /api/v1/agents/avatar/{agent_id}/stop` | Frontend |

The `start`/`stop` routes are served by `AvatarSessionView`, an **authenticated** view
(`@is_authenticated()` + `@user_session()`), just like `AgentTalk`/`AgentVoiceTalk`.
Send the **same credentials** (session cookie / `Authorization`) that you already use
for the chat.

---

## 3. Important clarification about "WebSockets"

In Phase A there is **no** ai-parrot WebSocket of its own to receive the avatar
video. The video/audio arrives **through the LiveKit room** (which internally uses
WebRTC with WebSocket signaling, but `livekit-client` abstracts that away).

There are three "channels" that should not be confused:

| Channel | Purpose | Do you touch it in Phase A? |
|---------|---------|-----------------------------|
| **LiveKit room** (`livekit-client`) | Receive the avatar's **video + audio** | **Yes** — it is the heart of the viewer |
| **REST `/voice`** (`AgentVoiceTalk`) | Send the turn and receive the envelope (text + structured) | **Yes** |
| **AgentChat streaming WS** (`StreamHandler`, `/bots/{bot_id}/stream/ws`) | Chat text token streaming | **Optional** — if you already use it for the chat, it stays the same |

> The LiveAvatar media-server WebSocket (`ws_url`) through which the PCM is pushed
> is **strictly server-side**. The frontend **never** connects to it.

---

## 4. Step 1 — Start the avatar session (`/start`)

| | |
|---|---|
| **Method** | `POST` |
| **Route** | `/api/v1/agents/avatar/{agent_id}/start` |
| **Auth** | Required (same as the chat) |
| **Content-Type** | `application/json` |

**Request body:**

```jsonc
{
  "session_id": "abc-123",   // REQUIRED. The same session_id as AgentChat.
  "tenant_id": "acme"        // Optional. For the per-tenant opt-in.
}
```

**Response 200 (viewer credentials only):**

```jsonc
{
  "livekit_url": "wss://<project>.livekit.cloud",
  "client_token": "<JWT subscribe-only>",
  "session_id": "abc-123"
}
```

> **DO NOT expect** `agent_token`, `ws_url` or `session_token` in the response:
> they are server secrets and are **never** serialized to the client. If your code
> looks for them, it is wrong.

**Typical errors:**

- `400` — `session_id` is missing.
- `403` — the tenant does not have the avatar enabled (opt-in off). Fall back to
  normal chat/voice without an avatar.
- `503` — the stack (`ai-parrot-integrations[liveavatar]`) is missing or the
  `LIVEAVATAR_*` / `LIVEKIT_*` environment variables are missing on the server.

---

## 5. Step 2 — Join the room and render the video (LiveKit)

Install the browser SDK:

```bash
npm install livekit-client
```

With `{ livekit_url, client_token }` from step 1, you connect to the room and
subscribe to the avatar's tracks (remote participant `avatar-agent`):

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

  // Subscribe to remote tracks (the avatar's video and audio).
  room.on(
    RoomEvent.TrackSubscribed,
    (
      track: RemoteTrack,
      _pub: RemoteTrackPublication,
      _participant: RemoteParticipant,
    ) => {
      if (track.kind === Track.Kind.Video) {
        track.attach(videoEl);   // render the avatar's video
      } else if (track.kind === Track.Kind.Audio) {
        track.attach(audioEl);   // play the avatar's voice
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

Notes:

- The token is **subscribe-only**: the browser **cannot** publish, only
  receive. It is safe to expose it to the client.
- The `<audio>` element may require user interaction (autoplay): render the
  avatar after a click/tap, or show an "Enable sound" button.
- The audio track that LiveKit plays is **the avatar's voice** (lip-sync). Do not
  additionally use the `audio_base64` from the `/voice` envelope for playback: it would cause
  double audio. (See §6.)

---

## 6. Step 3 — Talk to the agent (`avatar: true`)

The conversation turn is made against the **usual** voice endpoint
(`AgentVoiceTalk`), adding the `avatar: true` flag. The backend resolves the turn
and, in parallel, makes **the avatar say it out loud through the room**.

| | |
|---|---|
| **Method** | `POST` |
| **Route** | `/api/v1/agents/voice/{agent_id}` |
| **Body** | multipart (voice note) **or** JSON/form with a text `query` |

Fields relevant to the avatar (read in `_read_voice_options`):

| Field | Type | Effect |
|-------|------|--------|
| `avatar` | `true` \| `"true"` | Enables avatar mode for that turn |
| `tenant_id` | `string` | Per-tenant opt-in (must match the one from `/start`) |
| `query` | `string` | The turn text (if you don't send a voice note) |

**Important — behavior in Phase A:**

- The `avatar:true` flag goes through the tenant's **opt-in gate**. If it is
  off, the backend silently falls back to the normal text/voice path.
- The **PCM is pushed by the backend** to the avatar (via the session started in `/start`).
  The browser does **not** receive the agent's audio from this endpoint to play it;
  it **hears it through the LiveKit room**.
- The response envelope is the **same as `AgentTalk`/`AgentVoiceTalk`**:
  `response`, `output`, `data`, `media`, etc. Use it to render text and
  structured artifacts, **not** to play avatar audio.

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
    credentials: "include", // same auth as the chat
  });
  if (!res.ok) throw new Error(`voice turn failed: ${res.status}`);
  return res.json(); // AgentTalk envelope (text + structured)
}
```

> If the endpoint returns `audio_base64` (it can happen when you sent a voice
> note), **ignore it in avatar mode** so the voice is not duplicated: the avatar
> is already speaking through the room.

---

## 7. Step 4 — Close the session (`/stop`)

**Always** close the session when finished (closing the chat, navigating away,
`beforeunload`). The backend stops the LiveAvatar session, cancels the keep-alive and
releases the HTTP client.

| | |
|---|---|
| **Method** | `POST` |
| **Route** | `/api/v1/agents/avatar/{agent_id}/stop` |
| **Body** | `{ "session_id": "abc-123" }` |
| **Response** | `204 No Content` (idempotent: unknown session → also `204`) |

> `/stop` is identified **only by `session_id`**. The `session_token` is a
> server secret and is **not** accepted from the client.

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

And in the browser, disconnect from the room as well:

```ts
await room.disconnect();
```

As a safety net, the backend has a `max_session_duration`
(`LIVEAVATAR_MAX_SESSION_DURATION`) that auto-terminates abandoned sessions, but
**do not rely on it**: call `/stop` explicitly.

---

## 8. Per-tenant opt-in and error handling

The avatar is **opt-in per program/tenant**. Design the UI to be
**avatar-aware**:

- Before showing the "Talk to avatar" button, or upon receiving `403` from `/start`,
  **hide** the viewer and make the chat behave as normal text/voice.
- `session_id` **must be the same** in `/start`, in the `/voice` turn and in `/stop`.
- Handle `503` (stack not installed / missing env) by showing a graceful fallback
  ("avatar not available right now"), never a red error.

| Code | Meaning | Suggested UI action |
|------|---------|---------------------|
| `200` | Session created | Connect to the room |
| `400` | Missing `session_id` | Client bug: fix the payload |
| `403` | Tenant without opt-in | Hide the avatar; use normal chat/voice |
| `503` | Stack/env unavailable | "Avatar not available" fallback |

---

## 9. Structured outputs

**Do not** route charts/data/canvas through LiveKit. Structured outputs keep
arriving exactly as they do today:

- In the **envelope** of the `/voice` response (`output`, `data`, `media`,
  `artifact_id`, …), or
- Through the **AgentChat streaming WS** (`StreamHandler`) if you already use it.

LiveKit carries **only** the avatar's face and voice. The golden rule:
**the user *hears* the `response` (speakable text) through the avatar and *sees* the
tables/charts/data in the UI** (as always).

---

## 10. Full example (TS, vanilla)

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

  /** Step 1 + 2: start the session and join the room. */
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

  /** Step 3: send a turn; the avatar says it through the room. */
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
    // Render envelope.response / envelope.output / envelope.data in the UI.
    // DO NOT play envelope.audio_base64 in avatar mode (double audio).
    return envelope;
  }

  /** Step 4: close everything. */
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

Usage:

```ts
const session = new AvatarSession(
  "concierge",
  crypto.randomUUID(),            // or the AgentChat session_id
  document.querySelector("#avatar-video")!,
  document.querySelector("#avatar-audio")!,
  "acme",
);

try {
  await session.start();
  const reply = await session.ask("¿Cuál fue el revenue del Q1?");
  renderEnvelope(reply); // your usual text/structured rendering
} catch (e) {
  if (e instanceof AvatarDisabledError) showTextOnlyChat();
  else showAvatarUnavailable();
}

window.addEventListener("beforeunload", () => { session.stop(); });
```

---

## 11. Svelte 5 component (reference)

> This is the component that TASK-009 expects in the AgentChat repo (Svelte 5),
> using *runes*. It is a reference — adapt it to your stores/styles.

```svelte
<script lang="ts">
  import { Room, RoomEvent, Track } from "livekit-client";
  import { onDestroy } from "svelte";

  // Props (Svelte 5 runes)
  let {
    agentId,
    sessionId,
    tenantId = undefined,
    enabled = true, // opt-in aware: false → does not initialize the viewer
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

    if (res.status === 403) { status = "disabled"; return; } // tenant without opt-in
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

  // Starts when the viewer is mounted and enabled
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

> Sending the turn (`avatar:true` against `/voice`) is done by your existing
> chat logic; this component is **only the viewer**. Share the `sessionId` between
> both.

---

## 12. Frontend integration checklist

- [ ] Install `livekit-client` and pin the version.
- [ ] Generate/share a single `session_id` across chat, `/start`, `/voice` and `/stop`.
- [ ] `POST /avatar/{id}/start` → store `livekit_url` + `client_token`.
- [ ] **Do not** look for `agent_token` / `ws_url` / `session_token` in the response.
- [ ] `room.connect(url, token)` and `attach()` the **video** and **audio** tracks.
- [ ] Handle `<audio>` autoplay (user gesture if needed).
- [ ] Send the turn to `/voice/{id}` with `avatar:true` + `session_id` (+ `tenant_id`).
- [ ] **Do not** play the envelope's `audio_base64` in avatar mode (double audio).
- [ ] Render `response`/`output`/`data`/`media` as in the normal chat.
- [ ] Be **opt-in aware**: hide the viewer on `403`; degrade to chat/voice.
- [ ] `POST /avatar/{id}/stop` + `room.disconnect()` on close / `beforeunload`.
- [ ] Graceful fallback on `503` (stack/env unavailable).
- [ ] Send the same auth credentials as the rest of AgentChat (`credentials: "include"`).

---

## Appendix — Contract summary

```jsonc
// POST /api/v1/agents/avatar/{agent_id}/start   (auth required)
// body:
{ "session_id": "abc-123", "tenant_id": "acme" }
// 200:
{ "livekit_url": "wss://<project>.livekit.cloud",
  "client_token": "<JWT subscribe-only>",
  "session_id": "abc-123" }
// 400 missing session_id · 403 tenant without opt-in · 503 stack/env unavailable

// POST /api/v1/agents/voice/{agent_id}          (auth required)
// form/multipart: query=<text> | <voice note>, avatar=true, session_id=abc-123, tenant_id=acme
// 200: AgentTalk envelope { response, output, data, media, ... }

// POST /api/v1/agents/avatar/{agent_id}/stop    (auth required)
// body:
{ "session_id": "abc-123" }
// 204 (idempotent)
```

**LiveKit identities** (informational):
- Room (`room`) = `session_id`.
- Avatar (remote participant that publishes video/audio) = identity `avatar-agent`.
- Viewer (your browser) = identity `agent_id`, **subscribe-only** grants.

---

## Revision history

| Version | Date | Author | Change |
|---------|------|--------|--------|
| 1.0 | 2026-06-18 | Claude (FEAT-242) | Initial frontend integration guide for the avatar (Phase A) |
