---
type: Wiki Summary
title: parrot.integrations.liveavatar.voice_provider
id: mod:parrot.integrations.liveavatar.voice_provider
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Shared avatar voice provider (FEAT-242 Phase A — chat→avatar wiring).
relates_to:
- concept: class:parrot.integrations.liveavatar.voice_provider.AvatarVoiceProvider
  rel: defines
- concept: mod:parrot.voice.tts.supertonic_inference
  rel: references
---

# `parrot.integrations.liveavatar.voice_provider`

Shared avatar voice provider (FEAT-242 Phase A — chat→avatar wiring).

Bridges the agent's text replies to the LiveAvatar "mouth" by synthesizing
speakable sentences to **raw PCM at the rate the avatar expects** (24 kHz mono
16-bit, see :mod:`parrot.integrations.liveavatar.avatar_ws`).

Two concerns are solved here so the request handlers stay thin:

1. **Lazy, shared Supertonic pipeline.** Building a :class:`SupertonicPipeline`
   loads four ONNX graphs and costs seconds, so the pipeline is created ONCE on
   first use (under an async lock) and reused across every avatar turn.  The
   provider object itself is cheap to construct, so it can be stored on the
   aiohttp ``app`` at startup without paying the model-load cost up front.

2. **Sample-rate reconciliation.** Supertonic-3 emits PCM at its *native* rate
   (``pipeline.sample_rate`` — 44.1 kHz for the shipped weights), but the
   LiveAvatar LITE media server assumes 24 kHz mono 16-bit (the chunk sizing in
   ``avatar_ws.py`` is built around that).  Feeding 44.1 kHz PCM unchanged makes
   the avatar play audio at the wrong pitch/speed, so the provider resamples to
   :data:`AVATAR_PCM_SAMPLE_RATE` before returning.

The public surface is a single async callable :meth:`synthesize_pcm` with the
shape ``(text: str) -> bytes`` — exactly what :class:`AvatarTurnSpeaker`
consumes.  Synthesis runs in a worker thread so the event loop is never blocked.

## Classes

- **`AvatarVoiceProvider`** — Lazily-built, shared Supertonic→PCM provider for avatar speech.
