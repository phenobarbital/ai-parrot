---
type: Wiki Summary
title: parrot.voice.tts.supertonic_backend
id: mod:parrot.voice.tts.supertonic_backend
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Supertonic TTS Backend.
relates_to:
- concept: class:parrot.voice.tts.supertonic_backend.SupertonicTTSBackend
  rel: defines
- concept: mod:parrot.voice.tts.backend
  rel: references
- concept: mod:parrot.voice.tts.models
  rel: references
---

# `parrot.voice.tts.supertonic_backend`

Supertonic TTS Backend.

Implements :class:`AbstractTTSBackend` against the Supertonic sub-second
text-to-speech model (ONNX runtime + weights). Mirrors the structure of
:class:`GoogleTTSBackend`: the heavy ONNX session is created lazily on first
synthesis, and inference runs off the event loop via ``asyncio.to_thread``.

Unlike the Google backend (which returns raw PCM and leaves container
conversion to the caller), this backend returns a **browser-playable WAV
container** by default and labels ``SynthesisResult.mime_format`` truthfully —
``mime_format`` is a label, not a converter, so the bytes always match the
label.

Extras-gated: the ONNX runtime and the Supertonic weights ship behind the
``ai-parrot-integrations[voice-supertonic]`` extra. When those dependencies
(or the model weights) are missing, ``synthesize`` raises ``ImportError`` /
``ValueError`` — it never silently degrades. Graceful degradation to
text-only is the *handler's* responsibility (FEAT-231, AgentVoiceTalk).

Added by FEAT-231 (AgentTalk Voice Support).

## Classes

- **`SupertonicTTSBackend(AbstractTTSBackend)`** — TTS backend that wraps the Supertonic ONNX speech model.
