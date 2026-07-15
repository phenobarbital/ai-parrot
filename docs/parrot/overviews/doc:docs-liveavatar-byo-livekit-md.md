---
type: Wiki Overview
title: LiveAvatar over your own LiveKit (Cloud or self-hosted)
id: doc:docs-liveavatar-byo-livekit-md
tags:
- overview
timestamp: '2026-07-14T22:20:21+00:00'
summary: This runbook wires the **kept "LITE over LiveKit" transport** (FEAT-242 /
---

# LiveAvatar over your own LiveKit (Cloud or self-hosted)

This runbook wires the **kept "LITE over LiveKit" transport** (FEAT-242 /
FEAT-249 Mode A + Mode C) so a LiveAvatar avatar publishes into a LiveKit room
**you own** — either a LiveKit Cloud project or a self-hosted LiveKit server.

> Scope: you own the **transport** (the LiveKit room) and the **brain**
> (ai-parrot text + TTS "mouth"). The avatar *rendering* is still the external
> **LiveAvatar managed service**, which joins your room as a publisher. This is
> NOT the deleted "Phase C" LiveKit Agents worker.

---

## 1. Architecture

```
ai-parrot backend                         LiveAvatar SaaS              YOUR LiveKit (Cloud or self-hosted)
─────────────────                         ──────────────              ───────────────────────────────────
POST /api/v1/agents/avatar/{id}/start
  ├─ LiveKitRoomManager.mint_room_tokens(session_id, agent_id)
  │     client_token  (can_publish=False, subscribe-only)  ──────────────────────────────────────────────┐
  │     agent_token   (can_publish=True)                                                                  │
  ├─ LiveAvatarClient.create_session_token(livekit_config={url, room, agent_token}) ──► avatar joins room │
  └─ returns {livekit_url, client_token, session_id} ──► browser ─────────────────► subscribes to room ◄──┘
                                                                                        "avatar-agent" publishes video+audio
```

Key files:
- `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/room_manager.py`
  — `LiveKitRoomManager`, `mint_room_tokens()`, `LiveKitRoomTokens`.
- `packages/ai-parrot-server/src/parrot/handlers/avatar.py`
  — `/start`, `/stop`, `/viewers` handlers + `register_avatar_routes()`.

---

## 2. Configuration (the only thing that selects Cloud vs self-hosted)

`LiveKitRoomManager.__init__` reads these from the environment (constructor args
override them) — `room_manager.py:73-75`:

| Env var | Purpose |
|---|---|
| `LIVEKIT_URL` | LiveKit WebSocket URL. **This is what makes it BYO.** |
| `LIVEKIT_API_KEY` | API key used to mint room JWTs. |
| `LIVEKIT_API_SECRET` | API secret used to mint room JWTs. |

Plus the LiveAvatar service credentials (so the SaaS avatar can be created):
the same env the existing LITE start path already uses
(`LIVEAVATAR_*`, incl. `LIVEAVATAR_SANDBOX=false` for a production avatar — see
the avatar `client.py`).

### LiveKit Cloud
```bash
export LIVEKIT_URL="wss://my-project.livekit.cloud"
export LIVEKIT_API_KEY="<cloud api key>"
export LIVEKIT_API_SECRET="<cloud api secret>"
```

### Self-hosted LiveKit
```bash
export LIVEKIT_URL="wss://livekit.internal.company.com:7881"   # ws:// if no TLS
export LIVEKIT_API_KEY="<key from your livekit.yaml>"
export LIVEKIT_API_SECRET="<secret from your livekit.yaml>"
```
The token minting uses the stock `livekit-api` library and is instance-agnostic —
nothing pins it to Cloud. Make sure the LiveAvatar SaaS can reach your
`LIVEKIT_URL` over the network (a self-hosted server must be publicly reachable
or peered, since the avatar connects *to* it).

---

## 3. Enable the routes

`register_avatar_routes(router)` (`avatar.py:442`) mounts the endpoints, but it
**defensively no-ops** unless the integration extra is installed:

```bash
pip install "ai-parrot-integrations[liveavatar]"
```
If the import fails you'll see: *"Avatar endpoints disabled … install
'ai-parrot-integrations[liveavatar]'"* and the routes won't exist.

Registered routes:
- `POST /api/v1/agents/avatar/{agent_id}/start`
- `POST /api/v1/agents/avatar/{agent_id}/stop`
- `POST /api/v1/avatar/{agent_id}/viewers`  (Mode C — multi-viewer)

All are served through the authenticated `AvatarSessionView` / `AvatarViewersView`.

---

## 4. Start a session

```bash
curl -X POST https://your-host/api/v1/agents/avatar/<agent_id>/start \
  -H "Authorization: Bearer <token>" -H "Content-Type: application/json" -d '{}'
```
Response (viewer credentials ONLY — `agent_token`/session secrets stay
server-side, `avatar.py:248-252`):
```json
{
  "livekit_url": "wss://my-project.livekit.cloud",
  "client_token": "<subscribe-only JWT>",
  "session_id": "<room name>"
}
```

The browser uses `livekit_url` + `client_token` with the standard
[`livekit-client`](https://docs.livekit.io/client-sdk-js/) SDK to join the room
and subscribe to the `avatar-agent` participant's video/audio. **No in-repo
frontend ships** — you build the viewer with the LiveKit JS/React SDK.

---

## 5. Multi-viewer (Mode C)

Mint extra subscribe-only tokens for the same room (`avatar.py:346-426`):
```bash
curl -X POST https://your-host/api/v1/avatar/<agent_id>/viewers \
  -H "Authorization: Bearer <token>" -H "Content-Type: application/json" \
  -d '{"session_id": "<room name>", "count": 5}'
```
```json
{ "viewers": [ { "identity": "viewer-0-…", "livekit_url": "wss://…", "client_token": "<JWT>" }, … ] }
```

---

## 6. Stop

```bash
curl -X POST https://your-host/api/v1/agents/avatar/<agent_id>/stop \
  -H "Authorization: Bearer <token>" -d '{"session_id": "<room name>"}'
```
Identified by `session_id` only; the server-side session token is never accepted
from the client.

---

## 7. Making the avatar speak

The LiveKit room is only the transport. The avatar "mouth" (chat turn → TTS PCM
pushed to the avatar over `AvatarWebSocket`) is the LITE path wired in FEAT-242
(`AvatarTurnSpeaker` / `AvatarVoiceProvider`). Drive it through the agent's
normal chat/voice turn — the synthesized audio (Supertonic, resampled
44100→24000) is what animates the avatar inside your room. See
`audio-form-voice-modes.md` for the full set of voice modes.

---

## 8. Caveats

- **Avatar rendering is not self-hostable here** — the LiveKit room is yours, but
  the avatar is the external LiveAvatar service joining via `agent_token`.
- **No live-LiveKit e2e in-repo** — coverage is contract/token level
  (`test_room_manager.py`, fakes). Validate against a real self-hosted server
  before production.
- **Self-hosted reachability** — the LiveAvatar SaaS must be able to dial your
  `LIVEKIT_URL`. A purely internal/non-routable LiveKit server won't work unless
  the avatar service can reach it.
- **Production avatar** — set `LIVEAVATAR_SANDBOX=false` (a sandbox/production
  mismatch makes `/start` return 400).
