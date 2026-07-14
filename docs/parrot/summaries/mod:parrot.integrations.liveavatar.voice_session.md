---
type: Wiki Summary
title: parrot.integrations.liveavatar.voice_session
id: mod:parrot.integrations.liveavatar.voice_session
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: VoiceAvatarSession — drive a LiveAvatar mouth from a realtime PCM stream
  (FEAT-245).
relates_to:
- concept: class:parrot.integrations.liveavatar.voice_session.VoiceAvatarSession
  rel: defines
- concept: mod:parrot.integrations.liveavatar.avatar_ws
  rel: references
- concept: mod:parrot.integrations.liveavatar.client
  rel: references
- concept: mod:parrot.integrations.liveavatar.models
  rel: references
- concept: mod:parrot.integrations.liveavatar.room_manager
  rel: references
---

# `parrot.integrations.liveavatar.voice_session`

VoiceAvatarSession — drive a LiveAvatar mouth from a realtime PCM stream (FEAT-245).

Thin session-lifecycle wrapper that connects a realtime PCM source (e.g. Gemini
Live's 24 kHz output) to the LiveAvatar LITE "mouth" (``AvatarWebSocket``).
No TTS, no resampling — the caller supplies ready-to-send 24 kHz mono 16-bit PCM.

Lifecycle::

    session = await VoiceAvatarSession.start(
        agent_id="my-agent",
        session_id="sess-abc",
        tenant_id="acme",          # optional
        avatar_id="custom-avatar", # optional; falls back to LIVEAVATAR_AVATAR_ID
    )
    # session_started reply → include session.viewer_credentials
    async for chunk in gemini_stream:
        if chunk.audio_data:
            await session.speak(chunk.audio_data)
        if chunk.is_complete:
            await session.finish_turn()
        if chunk.is_interrupted:
            await session.interrupt()
    await session.aclose()

Design notes
------------
- The opt-in gate (``is_avatar_enabled``) is NOT called here — that check is the
  caller's responsibility (TASK-1589).  This keeps the helper transport-only and
  independently unit-testable.
- ``aclose`` is idempotent and never raises; it is safe to call from cleanup code.
- ``mint_room_tokens`` is sync CPU work (JWT signing); it is offloaded via
  ``asyncio.to_thread``.
- The ``AvatarWebSocket`` is opened in ``start`` and held open for the session
  lifetime (NOT used as a short-lived ``async with`` block, per the FEAT-242
  keep-alive caveat at avatar.py:157-176).

## Classes

- **`VoiceAvatarSession`** — Drives a LiveAvatar mouth from a realtime PCM (24 kHz mono 16-bit) stream.
