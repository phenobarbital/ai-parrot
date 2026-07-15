---
type: Wiki Summary
title: parrot.integrations.liveavatar.room_audio_publisher
id: mod:parrot.integrations.liveavatar.room_audio_publisher
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Headless LiveKit room audio publisher (FEAT-256 Module 1).
relates_to:
- concept: class:parrot.integrations.liveavatar.room_audio_publisher.RoomAudioPublisher
  rel: defines
- concept: mod:parrot.integrations.liveavatar.models
  rel: references
---

# `parrot.integrations.liveavatar.room_audio_publisher`

Headless LiveKit room audio publisher (FEAT-256 Module 1).

Joins the ai-parrot-owned LiveKit room as a headless participant (using the
publish-capable ``agent_token`` from :func:`~room_manager.LiveKitRoomManager.mint_room_tokens`)
and publishes a direct audio track fed with Supertonic PCM frames.

This is the core of the avatar-OFF path: when the avatar is disabled (or
LiveAvatar has no credits), ai-parrot itself pushes audio directly into the
room so the browser still hears the bot.

Audio format: 24 kHz mono 16-bit PCM (matches Supertonic output — no
resampling).

Design constraints:
- Keep-alive: the publisher is long-lived; do NOT use it as a one-shot
  context manager per turn (mirrors the keep-alive caveat in
  ``handlers/avatar.py``).
- Idempotent ``aclose``: teardown never raises; safe to call multiple times.
- No double audio: only ONE sink (publisher OR LiveAvatar WS) is ever active
  per session.

Usage::

    publisher = await RoomAudioPublisher.start(tokens)
    # ... per turn ...
    await publisher.capture_pcm(pcm_bytes)
    # ... on interrupt ...
    await publisher.flush()
    # ... on session end ...
    await publisher.aclose()

## Classes

- **`RoomAudioPublisher`** — Headless LiveKit participant that publishes a Supertonic audio track.
