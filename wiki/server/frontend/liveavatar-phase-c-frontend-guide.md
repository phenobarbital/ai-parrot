---
title: "DEPRECATED: Native Voice Avatar (LiveAvatar Phase C) Technical Guide for Frontend"
---

# DEPRECATED: Native Voice Avatar (LiveAvatar Phase C) Technical Guide for Frontend

> **DEPRECATED (FEAT-249, 2026-06-19)**
> Phase C (LiveKit Agents worker stack) was removed from the codebase.
> All voice modes are now documented under the **Mode A / B / C / D taxonomy**.
> See [`liveavatar-frontend-guide.md`](liveavatar-frontend-guide.md) for the
> current LITE (Mode A) guide, and
> [`liveavatar-fullmode-sveltekit-guide.md`](liveavatar-fullmode-sveltekit-guide.md)
> for FULL (Mode B).  This document is preserved for historical reference only —
> do **not** use the APIs described here; they no longer exist.

**Audience**: the Frontend team (AgentChat, Svelte 5) that needs a
**fluid voice conversation with a talking avatar** — the user speaks into the
microphone, the agent answers with voice and face (lip-sync), and the
**structured artifacts** (charts, data, canvas) keep being rendered in the UI.

**Scope**: FEAT-243 — *LiveAvatar — Phase C (voice-native hybrid, ai-parrot
as the brain)*. Unlike Phase A, here the browser **publishes its
microphone** to the room and the conversation is **voice-native**: the *turn-taking*
(STT + VAD + turn detection + barge-in) is handled by a **LiveKit
Agents worker**, not by your chat logic. The "brain" is still ai-parrot: the worker
overrides `llm_node` to call `ask_stream()`. Speakable text → TTS →
avatar; structured outputs → AgentChat WS channel (same `session_id`).

---

> ✅ **Status of this guide (2026-06-18, rev 1.1).** The Phase C backend
> (FEAT-243) is **implemented and merged into `dev`** (branch
> `feat-243-liveavatar-phase-c-voice-native`, 104 tests green). What is already
> **real, verified code**: the LiveKit Agents worker, the `llm_node` that
> calls ai-parrot, the `OutputBridge` and its **structured output contract**,
> and the cross-process transport over Redis to the AgentChat WS.
>
> **The browser start endpoint ALREADY EXISTS** (resolved post-rev 1.1):
> `POST /api/v1/agents/avatar/{agent_id}/voice-native/start` mints a **token with
> audio publishing** (microphone `can_publish` + subscribe) and performs an **explicit dispatch
> of the worker** to the room with the `AvatarJobMetadata`. Real contract in
> [§4](#4-step-1--start-the-native-voice-session) and status in
> [§11](#11-startup-status-publish-token--dispatch). The mental model, the LiveKit
> flow and the consumption of structured outputs over the WS are **also**
> anchored in real code.
>
> Verified source files (2026-06-18, post-merge):
> - `…/liveavatar/livekit_agent/models.py` — `AvatarJobMetadata`, `StructuredOutputMessage`
> - `…/liveavatar/livekit_agent/agent.py` — `LiveAvatarAgent.llm_node` + `_classify` / `_structured_payload`
> - `…/liveavatar/livekit_agent/worker.py` — `entrypoint`, `parse_job_metadata`, `open_avatar_session`
> - `…/liveavatar/livekit_agent/pipeline.py` — `build_session` (STT/VAD/turn/TTS)
> - `…/liveavatar/output_bridge.py` + `output_transport.py` — bridge + Redis pub/sub
> - `…/liveavatar/room_manager.py` — `mint_room_tokens` (`client_token` subscribe-only, Phase A) + `mint_browser_token` (publish-audio, Phase C) + `dispatch_worker`
> - `packages/ai-parrot-server/src/parrot/handlers/avatar.py` — `VoiceNativeAvatarView` / `_start_voice_native_session` (endpoint `/voice-native/start`)
> - `packages/ai-parrot-server/src/parrot/handlers/liveavatar_output.py` — server-side subscriber
> - `packages/ai-parrot-server/src/parrot/handlers/user.py:357` — `broadcast_to_channel`
> - `sdd/specs/liveavatar-phase-c-voice-native.spec.md` — specification (FEAT-243)

---

## 0. Index

1. [Mental model: voice-native, the browser publishes the microphone](#1-mental-model)
2. [Phase C vs Phase A — what changes in the frontend](#2-phase-c-vs-phase-a)
3. [The pieces: 1 session start + 1 LiveKit room + 1 WS channel](#3-the-pieces)
4. [Step 1 — Start the native voice session](#4-step-1--start-the-native-voice-session)
5. [Step 2 — Join the room, publish the mic and render the avatar](#5-step-2--join-the-room-publish-the-mic-and-render-the-avatar)
6. [Step 3 — Receive structured outputs over the AgentChat WS](#6-step-3--structured-outputs-over-the-ws)
7. [Turn states, barge-in and "thinking"](#7-turn-states-barge-in-and-thinking)
8. [Step 4 — Close the session](#8-step-4--close-the-session)
9. [Per-tenant opt-in and error handling](#9-per-tenant-opt-in-and-errors)
10. [Full example (TS, vanilla)](#10-full-example-ts-vanilla)
11. [Startup status (publish token + dispatch)](#11-startup-status-publish-token--dispatch)
12. [Svelte 5 component (reference)](#12-svelte-5-component-reference)
13. [Frontend integration checklist](#13-frontend-integration-checklist)
14. [Appendix — Contract summary](#appendix--contract-summary)

---

## 1. Mental model

In Phase C the conversation is **voice-native and continuous**. There is no POST per turn:
the user simply **speaks**, and a **LiveKit Agents worker** (server-side)
listens to the browser's audio, detects start/end of turn, interruptions
(barge-in) and triggers the response. That worker **does not use LiveKit's LLM**:
it overrides `llm_node` to call **ai-parrot** (`ask_stream`). The response is
**forked**:

- **speakable text** → `SpeakableFlattener` → LiveKit TTS → the **avatar says it**;
- **structured outputs** (charts / data / canvas / `tool_calls`) → an
  **OutputBridge** publishes them to the **AgentChat WS channel** keyed by
  `session_id` (the same conversation the avatar is speaking).

```
                          ┌──────────────── BACKEND (ai-parrot) ─────────────────┐
 [Browser]                │                                                       │
   │ 1) POST .../start  ──┼─▶ mint token (PUBLISH+SUBSCRIBE) · dispatch worker    │
   │    {session_id,      │      with job metadata {session_id, agent_name,       │
   │     tenant_id}       │      tenant_id, ws_url}                               │
   │ ◀── {livekit_url, token, session_id}                                         │
   │                      │                                                       │
   │ 2) join(url, token)  │   LiveKit Cloud room (room = session_id)              │
   │  ── publishes MIC ──▶│──▶ AgentSession (STT · VAD · turn-detect · barge-in)  │
   │  ◀═ video+audio ═════│◀── avatar publishes face/voice │                      │
   │     of the avatar    │                       llm_node override (LiveAvatarAgent)
   │                      │                              │                        │
   │                      │            ai-parrot ask_stream(agent, q, session_id, tenant)
   │                      │             │                         │               │
   │                      │     speakable text             structured outputs     │
   │                      │     →TTS→ avatar SPEAKS          → OutputBridge        │
   │                      │                                       │               │
   │ 3) WS /ws/user  ◀════╪═══ broadcast_to_channel(session_id) ◀─┘               │
   │    (subscribe        │                                                       │
   │     to the           │                                                       │
   │     session_id       │                                                       │
   │     channel)         │                                                       │
   │ 4) POST .../stop  ───┼─▶ teardown worker + session                           │
   └──                    └───────────────────────────────────────────────────────┘
```

**Practical consequences:**

- The browser uses **`livekit-client`** as a **participant with audio
  publishing** (mic), and at the same time as a **subscriber** of the avatar's video/audio. It is
  publish **of audio** + subscribe; it does **not** publish video.
- **You do not send the turn over REST.** There is no `POST /voice` for each sentence. The
  user speaks and the worker handles the turn. Your UI **listens** for results,
  it does not request them.
- **Structured outputs arrive over the AgentChat WS** (`/ws/user`),
  by subscribing to the **channel = `session_id`**. They do **not** arrive in a REST
  response envelope (in Phase C there is no such per-turn response).
- The **`session_id` is the glue**: it names the LiveKit room *and* the WS channel
  for structured outputs. Share it across the three legs (start, room, WS).
- **Barge-in is native**: if the user speaks while the avatar is speaking, LiveKit
  interrupts the avatar automatically. You do not have to implement the cut.

---

## 2. Phase C vs Phase A

If you already integrated Phase A (FEAT-242, see `liveavatar-frontend-guide.md`), these
are the changes. **Do not reuse Phase A's turn flow in Phase C.**

| Aspect | Phase A (FEAT-242) | Phase C (FEAT-243) |
|---|---|---|
| Browser role | **Viewer only** (subscribe-only) | **Publishes mic** + subscribes to avatar |
| Room token | `client_token` **subscribe-only** | **publish(audio)+subscribe** token ⚠️ |
| Turn-taking | Manual: your chat logic triggers each turn | **Native**: LiveKit worker (STT/VAD/turn/barge-in) |
| Turn submission | `POST /voice` with `avatar:true` per turn | **None** — the user speaks; the worker listens |
| STT | Browser STT or `AgentVoiceTalk` STT | **LiveKit pipeline STT** (Deepgram `nova-3`) |
| Barge-in | Not native | **Native** (Silero VAD + MultilingualModel turn-detection) |
| Structured outputs | In the `/voice` **REST envelope** | Over the **AgentChat WS** (`broadcast_to_channel`) |
| Agent audio | PCM pushed by backend (Supertonic) | Pipeline **TTS (Cartesia)** → avatar, through the room |

> **Golden rule (same as Phase A)**: the user **hears** the speakable text from
> the avatar and **sees** the tables/charts/data in the UI. LiveKit carries only
> face and voice; structured content goes over the WS.

---

## 3. The pieces

For a voice-native conversation with an avatar you need to orchestrate **3 channels**:

| # | Action | How | Who |
|---|--------|------|-------|
| 1 | Start the voice-native session | `POST .../start` → token + worker dispatch | Frontend |
| 2 | Join the room, **publish mic**, render avatar | `livekit-client` → `room.connect` + `setMicrophoneEnabled(true)` | Frontend |
| 3 | Receive structured outputs | WS `/ws/user` → `subscribe` to the `session_id` channel | Frontend |
| 4 | Close the session | `POST .../stop` + `room.disconnect()` + close WS | Frontend |

The structural difference from Phase A: the **turn POST disappears** and the
**WS subscription appears** as the path for structured outputs.

---

## 4. Step 1 — Start the native voice session

**✅ Implemented.** The voice-native start endpoint **already exists** and does the
two things the browser needs: (a) it mints a **token with audio
publishing** and (b) it performs an **explicit dispatch of the worker** to the room with the
`AvatarJobMetadata`. The LiveKit Agents worker runs as a long-lived process
(`WorkerOptions(agent_name=…)`) and receives its context through that job metadata:

```python
# …/liveavatar/livekit_agent/models.py  (verified)
class AvatarJobMetadata(BaseModel):
    ws_url: str          # room ws URL (informational / diagnostics)
    session_id: str      # AgentChat conversation — room + WS channel
    agent_name: str      # ai-parrot agent acting as the brain
    tenant_id: str | None = None
```

> **Backend note (informational).** The `agent_name` dispatched in LiveKit is that
> of the **worker** (`WorkerOptions.agent_name`, env `LIVEAVATAR_WORKER_AGENT_NAME`,
> default `liveavatar-voice`) — **different** from the ai-parrot `agent_name` that
> travels inside `AvatarJobMetadata` (the one from the `{agent_id}` path). The dispatch is
> done with `LiveKitAPI().agent_dispatch.create_dispatch(...)` from
> `LiveKitRoomManager.dispatch_worker`.

The endpoint contract:

| | |
|---|---|
| **Method** | `POST` |
| **Route** | `/api/v1/agents/avatar/{agent_id}/voice-native/start` |
| **Auth** | Required (session cookie / `Authorization`, same as chat) |
| **Content-Type** | `application/json` |

**Request body:**

```jsonc
{
  "session_id": "abc-123",   // REQUIRED. Shared key: LiveKit room + WS channel.
  "tenant_id": "acme"        // Optional. Per-tenant opt-in (goes into the job metadata).
}
```

**Expected 200 response:**

```jsonc
{
  "livekit_url": "wss://<project>.livekit.cloud",
  "token": "<JWT publish(audio)+subscribe>",   // ⚠️ must allow publishing audio
  "session_id": "abc-123"
}
```

> ✅ **Publish token (resolved).** The endpoint uses
> `LiveKitRoomManager.mint_browser_token`, which mints a JWT with `can_publish=True`
> **restricted to the `microphone` source** (audio) + `can_subscribe=True`. It is the
> token that `/voice-native/start` returns in the **`token`** field (do not confuse it
> with Phase A's subscribe-only `client_token`). With it,
> `setMicrophoneEnabled(true)` works; the browser **cannot** publish video.

**Expected errors:**

| Code | Meaning | UI action |
|--------|-------------|--------------|
| `200` | Token issued + worker dispatched | Connect to the room and publish mic |
| `400` | Missing `session_id` | Client bug: fix the payload |
| `403` | Tenant without avatar opt-in | Hide the avatar; degrade to text/voice chat |
| `503` | Stack/env unavailable (`ai-parrot-integrations[liveavatar-voice]` / `livekit-agents` / env) | "Avatar unavailable" fallback |

---

## 5. Step 2 — Join the room, publish the mic and render the avatar

Install the SDK:

```bash
npm install livekit-client
```

With `{ livekit_url, token }` from step 1, you connect, **enable the microphone**
(audio publishing) and subscribe to the avatar's tracks (remote
participant `avatar-agent`):

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

  // Subscribe to the avatar's REMOTE tracks (video + TTS voice).
  room.on(
    RoomEvent.TrackSubscribed,
    (
      track: RemoteTrack,
      _pub: RemoteTrackPublication,
      participant: RemoteParticipant,
    ) => {
      // The avatar joins as the remote participant "avatar-agent".
      if (track.kind === Track.Kind.Video) {
        track.attach(videoEl); // renders the avatar's face
      } else if (track.kind === Track.Kind.Audio) {
        track.attach(audioEl); // plays the avatar's voice (TTS)
      }
    },
  );
  room.on(RoomEvent.TrackUnsubscribed, (track) => track.detach());

  await room.connect(livekitUrl, token);

  // ▶ PUBLISH THE MICROPHONE. This is the new part of Phase C: the server-side worker
  //   listens to this audio for STT/VAD/turn-detection. Requires a token with
  //   can_publish=true (see the gap in §4).
  await room.localParticipant.setMicrophoneEnabled(true);

  return room;
}
```

Key notes:

- `setMicrophoneEnabled(true)` triggers the browser's microphone permission prompt.
  Do it **after a user gesture** (click on "Start talking") so it does not clash
  with autoplay/permission policies.
- **Do not publish video** (`setCameraEnabled` is not used): the avatar is the face, not
  you. Only audio goes up; the avatar's video+audio comes down.
- The avatar's `<audio>` may also require a user gesture to play. Cover both
  with the same start button.
- The user's **mute** = `room.localParticipant.setMicrophoneEnabled(false)`.
  Useful for a "mute mic" button.

---

## 6. Step 3 — Structured outputs over the WS

In Phase C there is **no per-turn REST envelope**. Structured outputs
(charts, data, canvas, `tool_calls`) arrive over the **AgentChat WebSocket**
(`UserSocketManager`, default route **`/ws/user`**), when the backend calls
`broadcast_to_channel(session_id, StructuredOutputMessage.model_dump())`.

> **Backend detail (informational).** The worker runs in a **different process** from
> the AgentChat server, so the `OutputBridge` first publishes to a **Redis pub/sub**
> channel (`liveavatar:structured-outputs`) and a server subscriber
> (`configure_liveavatar_output_subscriber`) **re-emits** it through
> `broadcast_to_channel`. For the frontend this is transparent: you just
> subscribe to the `session_id` channel on `/ws/user`.

The `UserSocketManager` **only delivers to channel subscribers** (if nobody is
subscribed, the message is dropped — **there is no buffer**). That is why you must
**subscribe to the `session_id` channel BEFORE you start speaking**.

**WS protocol** (verified in `handlers/user.py`):

```ts
// 1) Connect
const ws = new WebSocket(`${wsBase}/ws/user`);

// 2) Authenticate (the server replies {type:"auth_required"} on open)
ws.send(JSON.stringify({ type: "auth", content: { token: bearerToken } }));

// 3) Subscribe to the channel == session_id (the server replies {type:"subscribed"})
ws.send(JSON.stringify({ type: "subscribe", content: { channel: sessionId } }));

// 4) Receive the structured outputs
ws.onmessage = (ev) => {
  const msg = JSON.parse(ev.data);
  // control messages from the WS itself:
  if (msg.type === "auth_required" || msg.type === "subscribed") return;
  // structured output of the conversation (see schema below):
  renderStructuredOutput(msg);
};
```

**Structured output schema** — `StructuredOutputMessage` (P4 **resolved**,
verified in `models.py` + `agent.py`). The message you receive over the WS is
exactly the `model_dump()`:

```jsonc
{
  "type": "tool_call" | "canvas" | "data" | "<output_mode>",  // discriminator (see below)
  "session_id": "abc-123",
  "payload": {                 // FIXED shape, produced by _structured_payload()
    "response":    "response text (may be null)",
    "data":        { /* the structured data, already JSON-safe (frames→records) */ },
    "code":        "generated code or null",
    "artifact_id": "artifact id or null",
    "output_mode": "chart | map | table | … or null",
    "tool_calls":  ["tool_name", "…"]   // names only
  },
  "turn_id": "<artifact_id or null>"   // ⚠️ today turn_id == artifact_id
}
```

**How `type` is decided** (`_classify`, in order):

| Condition on the `AIMessage` | Resulting `type` |
|---|---|
| Has `tool_calls` | `"tool_call"` |
| `output_mode` ≠ `default`/`null` | the value of `output_mode` (e.g. `"chart"`, `"map"`, `"table"`) |
| Has `artifact_id` | `"canvas"` |
| Otherwise (carries `data`) | `"data"` |

> **Important — what does NOT arrive over the WS.** Only turns with **structured**
> output (`tool_calls`, `data`, `artifact_id`, or a non-default `output_mode`) are
> published. A **voice-only** turn (spoken response without structure) **generates
> no message** on the channel: the user **hears** it from the avatar and
> there is nothing to render. Do not expect a "transcript" of the spoken text through this path.

Integration recommendation: **reuse your current artifact rendering**.
The `payload` reuses the same fields as the `AgentTalk` envelope
(`response`/`data`/`code`/`artifact_id`/`output_mode`), so map
`StructuredOutputMessage.payload` to your existing rendering
(see `wiki/server/frontend/structured-artifacts-frontend-guide.md`). Use `type` (or
`payload.output_mode`) as the discriminator for the component to mount.

> **If you already use the `/ws/user` WS for chat**, do not open a second connection:
> reuse the same one and just add `subscribe` to the `session_id` channel. The Phase C
> channel is the **same mechanism** used by Web-HITL (`channel = session_id`,
> see `human/channels/web.py`).

---

## 7. Turn states, barge-in and "thinking"

Phase C is real-time conversational; the UI should reflect the turn state
so that it feels alive.

- **Barge-in (native):** if the user speaks while the avatar is speaking, the
  LiveKit pipeline **interrupts** the avatar's voice. You do not have to cut anything;
  at most, reflect "listening…" in the UI when the VAD detects the user's voice.
- **"Thinking" state during long `tool_calls` (Q-filler — resolved):** the
  implemented solution is a **phrase spoken by the avatar**. If a turn
  resolves into `tool_calls` without producing voice, `LiveAvatarAgent` emits a filler
  (`DEFAULT_FILLER_TEXT = "Let me look into that for you."`) through TTS so the
  avatar **does not go mute**. You do **not** need to render anything for this: the user
  hears it.
  - **Complementarily**, that same turn **does** publish a
    `StructuredOutputMessage` with `type: "tool_call"` (with `payload.tool_calls`
    = the tool names). If you want, use it for an optional indicator
    in the UI ("Querying data: `revenue_query`…"). It is optional; the spoken
    filler already covers the "no dead air" requirement.
- **Suggested UI states:** `idle` → `connecting` → `listening` (user
  VAD) → `speaking` (avatar speaks) → `thinking` (tool_calls). Derive
  `speaking`/`listening` from `livekit-client` events (`RoomEvent`,
  participants' `isSpeaking`) and `thinking` from the WS channel if the backend
  emits it.

> To detect who is speaking you can use `RoomEvent.ActiveSpeakersChanged` or the
> `participant.isSpeaking` flag from `livekit-client`. The remote participant
> `avatar-agent` speaking = render "speaking"; the local one speaking = "listening".

---

## 8. Step 4 — Close the session

**Always** close when finished (closing the chat, navigating away, `beforeunload`):
disconnect from the room, close the WS and notify the backend so it stops the worker.

| | |
|---|---|
| **Method** | `POST` |
| **Route** | `/api/v1/agents/avatar/{agent_id}/stop` *(to be confirmed, counterpart of Phase A)* |
| **Body** | `{ "session_id": "abc-123" }` |
| **Response** | `204 No Content` (idempotent) |

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

> ✅ **`/stop` now releases the worker explicitly.** The backend tracks the
> dispatch created in `/voice-native/start` (by `session_id`) and, on receiving
> `/stop`, **deletes the dispatch** (`delete_dispatch` → `LiveKitAPI.agent_dispatch`)
> in addition to the Phase A cleanup. It is **idempotent** (a `/stop` for an unknown
> or already closed session also responds `204`) and the same `session_id` works
> for both phases. Even so, call `/stop` as soon as possible: the worker is a
> long-lived *stateful* resource and you should not wait for the room's *empty-timeout*.

---

## 9. Per-tenant opt-in and errors

The avatar is **opt-in per program/tenant** (injected into the worker via job
metadata). Design the UI to be **avatar-aware**, as in Phase A:

- On `403` at `/start`, **hide** the avatar and degrade to normal text/voice chat
  — no red error.
- `session_id` **must be the same** in `/start`, in the LiveKit room, in the
  WS `subscribe` and in `/stop`.
- On `503` (stack/env unavailable), show an elegant fallback.
- If the microphone is denied by the browser, inform clearly ("I need
  microphone access to converse") — without a mic there is no turn in Phase C.

---

## 10. Full example (TS, vanilla)

```ts
import { Room, RoomEvent, Track } from "livekit-client";

interface StartResponse {
  livekit_url: string;
  token: string;          // publish(audio)+subscribe — see §4
  session_id: string;
}

interface StructuredOutputMessage {
  type: string; // "tool_call" | "canvas" | "data" | <output_mode> (chart/map/table/…)
  session_id: string;
  payload: {
    response: string | null;
    data: unknown;            // already JSON-safe (frames→records)
    code: string | null;
    artifact_id: string | null;
    output_mode: string | null;
    tool_calls: string[];     // tool names
  };
  turn_id: string | null;     // today == artifact_id
}

export class VoiceNativeAvatarSession {
  private room: Room | null = null;
  private ws: WebSocket | null = null;

  constructor(
    private agentId: string,
    private sessionId: string,
    private bearerToken: string,
    private wsBase: string, // e.g. wss://host (without /ws/user)
    private videoEl: HTMLVideoElement,
    private audioEl: HTMLAudioElement,
    private onStructured: (m: StructuredOutputMessage) => void,
    private tenantId?: string,
  ) {}

  /** Step 1 + 2 + 3: start the session, join the room, publish mic, open the WS. */
  async start(): Promise<void> {
    // 1) Start the voice-native session (mint token + dispatch worker).
    const res = await fetch(`/api/v1/agents/avatar/${this.agentId}/voice-native/start`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: this.sessionId, tenant_id: this.tenantId }),
      credentials: "include",
    });
    if (res.status === 403) throw new AvatarDisabledError("avatar no habilitado");
    if (!res.ok) throw new Error(`start failed: ${res.status}`);
    const { livekit_url, token }: StartResponse = await res.json();

    // 3) Subscribe to the structured outputs channel BEFORE speaking.
    await this.openStructuredChannel();

    // 2) Join the room, subscribe to the avatar and PUBLISH the microphone.
    this.room = new Room({ adaptiveStream: true, dynacast: true });
    this.room.on(RoomEvent.TrackSubscribed, (track) => {
      if (track.kind === Track.Kind.Video) track.attach(this.videoEl);
      else if (track.kind === Track.Kind.Audio) track.attach(this.audioEl);
    });
    this.room.on(RoomEvent.TrackUnsubscribed, (track) => track.detach());

    await this.room.connect(livekit_url, token);
    await this.room.localParticipant.setMicrophoneEnabled(true); // ← mic ON
  }

  /** Opens the AgentChat WS and subscribes to the channel == session_id. */
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

  /** Mute / unmute the user's microphone. */
  async setMuted(muted: boolean): Promise<void> {
    await this.room?.localParticipant.setMicrophoneEnabled(!muted);
  }

  /** Step 4: close everything. */
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

Usage:

```ts
const session = new VoiceNativeAvatarSession(
  "concierge",
  crypto.randomUUID(),               // or the AgentChat session_id
  myBearerToken,
  "wss://miservidor",
  document.querySelector("#avatar-video")!,
  document.querySelector("#avatar-audio")!,
  (m) => renderStructuredArtifact(m), // your chart/data/canvas rendering
  "acme",
);

// Start after a user gesture (microphone permission).
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

## 11. Startup status (publish token + dispatch)

All of the spec's Open Questions and the **browser entrypoint** (room token
+ worker dispatch) are **resolved and implemented**. There are no blockers left
for the frontend.

| Item | Status | Frontend impact |
|---|---|---|
| **Start endpoint + dispatch** (§4) | ✅ **Implemented**: `POST /api/v1/agents/avatar/{agent_id}/voice-native/start` (mint token + `dispatch_worker` with `AvatarJobMetadata`) | Call that endpoint; it returns `{livekit_url, token, session_id}`. |
| **Publish token for the browser** (§4) | ✅ **Implemented**: `mint_browser_token` (microphone `can_publish` + subscribe) | The `token` field now allows `setMicrophoneEnabled(true)`. |
| **P4 — `StructuredOutputMessage`** | ✅ **Resolved** (implemented, see §6) | Fixed contract: `type` + `payload {response,data,code,artifact_id,output_mode,tool_calls}` + `turn_id`. |
| **Q-filler** (§7) | ✅ **Resolved**: filler spoken by the avatar | Nothing to render (optional: use the `tool_call` msg). |
| **P5 — `livekit-agents` pin** | ✅ **Resolved**: `~=1.5`, validated on **1.6.1** | Server-side; conditions barge-in/turn (already validated). |
| **Q-plugins** | ✅ **Resolved**: Deepgram `nova-3` · Cartesia · Silero · MultilingualModel | Determines STT/TTS/VAD (server-side). |
| **Q-deploy** | ✅ **Resolved**: `PROCESS` model + warm pool (`num_idle_processes`) | May affect the first turn's TTFB (perceived latency). |

**Recommendation.** The frontend can integrate **directly** against this
guide: the complete flow (start → publish mic + subscribe avatar → structured
outputs over the WS) is anchored in real code and covered by tests. There is no longer any need
to mock `/start`.

> **Deployment requirements** (for the endpoint to work end-to-end): env
> `LIVEKIT_URL` / `LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET` (mint + dispatch),
> `LIVEAVATAR_WORKER_AGENT_NAME` (optional, default `liveavatar-voice`); the
> **worker** running (`worker.configure(bot_resolver=…)` + `worker.run()`, see
> `examples/liveavatar_voice_worker.py`) and registered with that same `agent_name`;
> and the output subscriber active on the server
> (`configure_liveavatar_output_subscriber(app)`, opt-in `ENABLE_STRUCTURED_OUTPUT_TRANSPORT`
— previously `ENABLE_LIVEAVATAR_VOICE`, renamed in FEAT-249).
> The per-tenant opt-in (`is_avatar_enabled`) still governs the `403`.

---

## 12. Svelte 5 component (reference)

> Reference using *runes*. It is the voice-native viewer: it publishes the mic, renders the avatar and
> listens to the structured outputs WS channel. Adapt it to your stores/styles.

```svelte
<script lang="ts">
  import { Room, RoomEvent, Track } from "livekit-client";
  import { onDestroy } from "svelte";

  let {
    agentId,
    sessionId,
    bearerToken,
    wsBase,                       // e.g. wss://host
    tenantId = undefined,
    enabled = true,               // opt-in aware: false → does not initialize
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

    // Structured outputs WS channel (before speaking).
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

    // LiveKit room: subscribe to avatar + publish mic.
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

  // Start after a user gesture (button); avoids autoplay/mic permission issues.
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

## 13. Frontend integration checklist

- [ ] Install `livekit-client` and pin the version.
- [ ] Generate/share a single `session_id` across `/start`, the **LiveKit room**, the **WS `subscribe`** and `/stop`.
- [ ] `POST .../start` → store `livekit_url` + `token` (**publish-capable** token).
- [ ] Start **after a user gesture** (microphone permission + autoplay).
- [ ] `room.connect(url, token)` and **`setMicrophoneEnabled(true)`** (publish mic).
- [ ] `attach()` the avatar's **video** and **audio** tracks (`avatar-agent`).
- [ ] **Do not** publish video; **do not** send a turn POST for each sentence.
- [ ] Open the `/ws/user` WS, `auth`, and **`subscribe` to the `session_id` channel** **before** speaking.
- [ ] Render `StructuredOutputMessage` (chart/data/canvas/tool_call) reusing your current artifact rendering.
- [ ] Reflect turn states (`listening`/`speaking`/`thinking`) and native barge-in.
- [ ] **Mute** button (`setMicrophoneEnabled(false/true)`).
- [ ] Be **opt-in aware**: hide the avatar on `403`; degrade to text/voice chat.
- [ ] Graceful fallback on `503` (stack/env unavailable) and denied microphone.
- [ ] `POST .../stop` + `room.disconnect()` + `ws.close()` on close / `beforeunload`.
- [ ] Same auth credentials as the rest of AgentChat (`credentials: "include"`).
- [ ] `POST .../voice-native/start` to start (endpoint **already implemented**; see [§11](#11-startup-status-publish-token--dispatch)). No pending blockers.

---

## Appendix — Contract summary

```jsonc
// 1) POST /api/v1/agents/avatar/{agent_id}/voice-native/start   (auth required) [IMPLEMENTED]
//    Mints publish(audio) token + DISPATCHES the worker with AvatarJobMetadata.
//    body:
{ "session_id": "abc-123", "tenant_id": "acme" }
//    200:
{ "livekit_url": "wss://<project>.livekit.cloud",
  "token": "<JWT publish(microphone)+subscribe>",   // NOT Phase A's subscribe-only client_token
  "session_id": "abc-123" }
//    400 missing session_id · 403 tenant without opt-in · 503 stack/env/dispatch unavailable

// 2) LiveKit room (livekit-client)
//    room.connect(livekit_url, token)
//    room.localParticipant.setMicrophoneEnabled(true)   // publishes mic (new)
//    remote avatar = identity "avatar-agent" (subscribe to its video+audio)

// 3) WS /ws/user (UserSocketManager) — structured outputs [P4 RESOLVED]
//    → { "type": "auth",      "content": { "token": "<bearer>" } }
//    → { "type": "subscribe", "content": { "channel": "abc-123" } }   // == session_id
//    ← { "type": "subscribed", "channel": "abc-123" }
//    ← StructuredOutputMessage (model_dump):
{ "type": "tool_call" | "canvas" | "data" | "<output_mode>",
  "session_id": "abc-123",
  "payload": { "response": null, "data": {}, "code": null,
               "artifact_id": null, "output_mode": null, "tool_calls": [] },
  "turn_id": null }   // turn_id == artifact_id
//    (VOICE-ONLY turns emit no message)

// 4) POST .../stop    (auth required) — deletes the worker dispatch; idempotent (204)
//    body:
{ "session_id": "abc-123" }
//    204 (idempotent)
```

**LiveKit identities** (informational):
- Room (`room`) = `session_id`.
- Avatar (remote participant that publishes video/audio) = identity `avatar-agent`.
- Browser (you) = **publishes audio (mic)** + subscribes to avatar.

---

## Revision history

| Version | Date | Author | Change |
|---------|-------|-------|--------|
| 1.0 | 2026-06-18 | Claude (FEAT-243) | Initial frontend integration guide for the voice-native avatar (Phase C) |
| 1.1 | 2026-06-18 | Claude (FEAT-243) | Revised against the merge into `dev`: real `StructuredOutputMessage` contract (P4 resolved), spoken filler (Q-filler), Deepgram/Cartesia/Silero pipeline, `livekit-agents ~=1.5` (P5), Redis transport. Only remaining blocker: browser start endpoint + publish token |
| 1.2 | 2026-06-18 | Claude (FEAT-243) | **Blocker resolved**: implemented `POST /api/v1/agents/avatar/{agent_id}/voice-native/start` (`VoiceNativeAvatarView`) which mints the publish-audio token (`mint_browser_token`) and dispatches the worker (`dispatch_worker` → `create_dispatch` with `AvatarJobMetadata`). Examples §10/§12 and contracts updated to the real route. No pending blockers |
