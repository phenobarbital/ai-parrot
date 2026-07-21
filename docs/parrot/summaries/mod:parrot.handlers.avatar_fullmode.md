---
type: Wiki Summary
title: parrot.handlers.avatar_fullmode
id: mod:parrot.handlers.avatar_fullmode
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: FULL Mode avatar endpoint — start/stop sessions and list avatars/voices (FEAT-248).
relates_to:
- concept: class:parrot.handlers.avatar_fullmode.FullmodeAvatarsView
  rel: defines
- concept: class:parrot.handlers.avatar_fullmode.FullmodeStartView
  rel: defines
- concept: class:parrot.handlers.avatar_fullmode.FullmodeStopView
  rel: defines
- concept: class:parrot.handlers.avatar_fullmode.FullmodeTranscriptView
  rel: defines
- concept: class:parrot.handlers.avatar_fullmode.FullmodeVoicesView
  rel: defines
- concept: func:parrot.handlers.avatar_fullmode.close_all_fullmode_sessions
  rel: defines
- concept: func:parrot.handlers.avatar_fullmode.register_fullmode_routes
  rel: defines
- concept: mod:parrot.handlers.avatar
  rel: references
- concept: mod:parrot.integrations.liveavatar
  rel: references
- concept: mod:parrot.integrations.liveavatar.client
  rel: references
- concept: mod:parrot.integrations.liveavatar.optin
  rel: references
- concept: mod:parrot.integrations.liveavatar.tenant_config
  rel: references
---

# `parrot.handlers.avatar_fullmode`

FULL Mode avatar endpoint — start/stop sessions and list avatars/voices (FEAT-248).

Provides REST endpoints for the LiveAvatar FULL mode avatar session:

    POST /api/v1/avatar/fullmode/{agent_id}/start
        Start a FULL mode avatar session.  Returns viewer credentials ONLY
        (``session_id``, ``livekit_url``, ``livekit_client_token``).  The
        ``session_token`` and any server-side secrets are NEVER returned.
        The live :class:`LiveAvatarClient` (with its keep-alive loop) is
        kept alive and stored in ``app[FULLMODE_SESSIONS_KEY]`` so the
        matching ``/stop`` can tear it down.

    POST /api/v1/avatar/fullmode/{agent_id}/stop
        Stop an active FULL mode session by ``session_id``: stops the
        LiveAvatar session, cancels the keep-alive loop, and closes the
        HTTP client.  Idempotent — unknown/expired sessions return 204.

    GET /api/v1/avatar/avatars
        List available avatars (stock + user-uploaded) from the LiveAvatar API.

    GET /api/v1/avatar/voices
        List available voices from the LiveAvatar API.

    GET /api/v1/avatar/session/{session_id}/transcript
        Retrieve the server-side transcript for a completed FULL mode session.

All FULL mode session management is separate from the LITE phase (``avatar.py``)
and uses a dedicated session store key ``FULLMODE_SESSIONS_KEY``.  The opt-in
gate uses ``is_fullmode_enabled()`` (a superset of ``is_avatar_enabled()``).

Lazy imports of the liveavatar stack happen inside the handlers so server
boot never hard-requires the optional ``ai-parrot-integrations[liveavatar]``
extra.

## Classes

- **`FullmodeStartView(BaseView)`** — Authenticated entrypoint for POST .../fullmode/{agent_id}/start.
- **`FullmodeStopView(BaseView)`** — Authenticated entrypoint for POST .../fullmode/{agent_id}/stop.
- **`FullmodeAvatarsView(BaseView)`** — Authenticated entrypoint for GET /api/v1/avatar/avatars.
- **`FullmodeVoicesView(BaseView)`** — Authenticated entrypoint for GET /api/v1/avatar/voices.
- **`FullmodeTranscriptView(BaseView)`** — Authenticated entrypoint for GET /api/v1/avatar/session/{session_id}/transcript.

## Functions

- `def register_fullmode_routes(router: Any) -> bool` — Register FULL mode avatar endpoints on the provided aiohttp router.
- `async def close_all_fullmode_sessions(app: web.Application) -> None` — Best-effort teardown of any lingering FULL mode sessions on shutdown.
