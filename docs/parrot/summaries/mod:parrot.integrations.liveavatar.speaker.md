---
type: Wiki Summary
title: parrot.integrations.liveavatar.speaker
id: mod:parrot.integrations.liveavatar.speaker
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Per-turn avatar speaker (FEAT-242 Phase A — chat→avatar wiring).
relates_to:
- concept: class:parrot.integrations.liveavatar.speaker.AvatarTurnSpeaker
  rel: defines
- concept: mod:parrot.integrations.liveavatar.avatar_ws
  rel: references
- concept: mod:parrot.integrations.liveavatar.models
  rel: references
- concept: mod:parrot.integrations.liveavatar.room_audio_publisher
  rel: references
- concept: mod:parrot.integrations.liveavatar.speakable
  rel: references
---

# `parrot.integrations.liveavatar.speaker`

Per-turn avatar speaker (FEAT-242 Phase A — chat→avatar wiring).

The missing bridge between the chat handler and the avatar's "mouth".

Unlike :class:`AvatarSessionOrchestrator` — which owns the whole session
lifecycle (create → start → speak → stop) for a single one-shot turn — this
class **reuses an already-started session** (the one created by
``POST /api/v1/agents/avatar/{agent}/start`` and stored in
``app['avatar_sessions']``).  That matches the real lifecycle:

    /start  → session created once, persists
    /chat   → AvatarTurnSpeaker opens a WS, speaks this turn, closes the WS
    /chat   → …another turn, same session…
    /stop   → session torn down

Design goals:

- **Never block the text stream.**  Synthesis is CPU-heavy ONNX work.  If the
  chat handler awaited synthesis inside its per-chunk loop, the browser's text
  stream would stall.  So sentences are pushed onto an :class:`asyncio.Queue`
  (a cheap, non-blocking op) and a background consumer task synthesizes + sends
  the PCM concurrently.  The avatar audio lags the text slightly — which is the
  desired behaviour.
- **Graceful degradation.**  Any TTS or WS error is logged and skipped; the
  chat turn continues in text-only mode (spec §7).
- **Mode-aware sink (FEAT-256).**  When a :class:`~room_audio_publisher.RoomAudioPublisher`
  is injected (avatar-OFF path), the speaker routes PCM to the room audio source
  instead of the LiveAvatar WebSocket.  Exactly one sink is active per session
  (avatar-ON XOR avatar-OFF) — no double audio.

Usage (avatar-ON)::

    async with AvatarTurnSpeaker(handle, synth_pcm_fn) as speaker:
        async for chunk in bot.ask_stream(...):
            if isinstance(chunk, str):
                speaker.feed(chunk)        # cheap, non-blocking
        await speaker.finish()             # flush + flush WS buffer

Usage (avatar-OFF / FEAT-256)::

    async with AvatarTurnSpeaker(
        handle, synth_pcm_fn, room_publisher=publisher
    ) as speaker:
        ...

## Classes

- **`AvatarTurnSpeaker`** — Speak one chat turn through an already-started LiveAvatar session.
