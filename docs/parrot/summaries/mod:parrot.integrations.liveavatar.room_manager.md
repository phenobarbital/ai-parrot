---
type: Wiki Summary
title: parrot.integrations.liveavatar.room_manager
id: mod:parrot.integrations.liveavatar.room_manager
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: LiveKit room manager — BYO Cloud tokens (FEAT-242 Phase A — Module 3).
relates_to:
- concept: class:parrot.integrations.liveavatar.room_manager.LiveKitRoomManager
  rel: defines
- concept: mod:parrot.integrations.liveavatar.models
  rel: references
---

# `parrot.integrations.liveavatar.room_manager`

LiveKit room manager — BYO Cloud tokens (FEAT-242 Phase A — Module 3).

Mints a LiveKit Cloud room plus client/agent JWT tokens using the
``livekit-api`` library.

Env vars required:
    LIVEKIT_URL        wss://<project>.livekit.cloud
    LIVEKIT_API_KEY    LiveKit Cloud API key
    LIVEKIT_API_SECRET LiveKit Cloud API secret

Tokens:
    client_token  — subscribe-only grants (browser viewer; safe to expose).
    agent_token   — publish + subscribe grants (avatar participant; server-side only).

``livekit-api`` is an optional dependency; a clear error is raised on import
if the package is not installed (install with the ``liveavatar`` extra).

## Classes

- **`LiveKitRoomManager`** — Mint LiveKit Cloud room tokens for the BYO transport.
