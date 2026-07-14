---
type: Wiki Summary
title: parrot.integrations.liveavatar.client
id: mod:parrot.integrations.liveavatar.client
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: LiveAvatar HTTP client and session lifecycle (FEAT-242 Phase A — Module 1).
relates_to:
- concept: class:parrot.integrations.liveavatar.client.LiveAvatarClient
  rel: defines
- concept: mod:parrot.integrations.liveavatar.models
  rel: references
---

# `parrot.integrations.liveavatar.client`

LiveAvatar HTTP client and session lifecycle (FEAT-242 Phase A — Module 1).

Ports the LiveAvatar starter ``liveavatar_client.py`` (httpx/websockets) to
``aiohttp`` per project standards.

Responsibilities:
- ``create_session_token``: create a LITE session (optionally with
  ``livekit_config`` so the avatar joins our LiveKit Cloud room).
- ``create_full_session_token``: create a FULL mode session (FEAT-248).
- ``start_session``: start the created session (Bearer auth).
- ``stop_session``: stop/close the session (idempotent).
- ``keep_alive``: periodic HTTP keep-alive (< 5 min interval).
- ``list_avatars``: list available avatars (FEAT-248).
- ``list_voices``: list available voices (FEAT-248).
- ``get_session_transcript``: retrieve session transcript (FEAT-248).

Auth headers:
- ``X-API-KEY: cfg.api_key`` on create / stop / keep-alive.
- ``Authorization: Bearer <handle.session_token>`` on start_session.

Keep-alive strategy: HTTP ``/v1/sessions/{id}/keep-alive`` is used here
(not the WS variant).  # TODO P7 — if WS keep_alive is chosen in the
future, move this call to AvatarWebSocket (TASK-003).

## Classes

- **`LiveAvatarClient`** — Async HTTP client for the LiveAvatar LITE API.
