---
type: Wiki Summary
title: parrot.handlers.avatar
id: mod:parrot.handlers.avatar
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Avatar session endpoint — start/stop/viewers for an avatar session (FEAT-242,
  FEAT-249).
relates_to:
- concept: class:parrot.handlers.avatar.AvatarSessionView
  rel: defines
- concept: class:parrot.handlers.avatar.AvatarViewersView
  rel: defines
- concept: func:parrot.handlers.avatar.avatar_upstream_error_response
  rel: defines
- concept: func:parrot.handlers.avatar.close_all_avatar_sessions
  rel: defines
- concept: func:parrot.handlers.avatar.register_avatar_routes
  rel: defines
- concept: mod:parrot.integrations.liveavatar
  rel: references
- concept: mod:parrot.integrations.liveavatar.optin
  rel: references
- concept: mod:parrot.integrations.liveavatar.room_audio_publisher
  rel: references
---

# `parrot.handlers.avatar`

Avatar session endpoint — start/stop/viewers for an avatar session (FEAT-242, FEAT-249).

Additional endpoint for Mode C (multi-viewer LITE):

    POST /api/v1/avatar/{agent_id}/viewers
        For an active LITE session, mint up to ``count`` additional subscribe-only
        viewer tokens and return them as a list. No secrets are ever returned.


Provides authenticated REST endpoints for the LiveAvatar LITE avatar session:

    POST /api/v1/agents/avatar/{agent_id}/start
        Start an avatar session for the named agent.  Returns viewer credentials
        ONLY (``livekit_url``, ``client_token``, ``session_id``).  The
        ``agent_token``, ``ws_url`` and ``session_token`` are NEVER returned to
        the client.  The live :class:`LiveAvatarClient` (with its keep-alive
        loop) is kept alive and stored in ``app['avatar_sessions']`` so the
        matching ``/stop`` can tear it down.

    POST /api/v1/agents/avatar/{agent_id}/stop
        Stop an active avatar session by ``session_id``: stops the LiveAvatar
        session, cancels the keep-alive loop, and closes the HTTP client.

Both endpoints are served through :class:`AvatarSessionView`, a
``navigator.views.BaseView`` decorated with ``@is_authenticated()`` and
``@user_session()`` (mirrors :class:`AgentTalk`) — so an unauthenticated caller
can neither start nor stop a session.

Integration with ``AgentVoiceTalk``:
The avatar mode is exposed as a request flag (``avatar=true``) on the voice
endpoint.  A separate POST to ``/api/v1/agents/avatar/{agent_id}/start``
pre-starts the avatar session and returns viewer credentials that the browser
uses to join the LiveKit room; the browser still calls the voice endpoint as
normal for the actual dialogue.

## Classes

- **`AvatarSessionView(BaseView)`** — Authenticated entrypoint for the avatar start/stop actions.
- **`AvatarViewersView(BaseView)`** — Authenticated endpoint to mint extra subscribe-only viewer tokens (Mode C).

## Functions

- `def avatar_upstream_error_response(exc: ClientResponseError) -> web.Response` — Translate a LiveAvatar upstream error into a clean JSON response.
- `async def close_all_avatar_sessions(app: web.Application) -> None` — Best-effort teardown of any lingering avatar sessions on shutdown.
- `def register_avatar_routes(router: Any) -> bool` — Register avatar session endpoints on the provided aiohttp router.
