---
type: Wiki Entity
title: AvatarVoiceProvider
id: class:parrot.integrations.liveavatar.voice_provider.AvatarVoiceProvider
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Lazily-built, shared Supertonic→PCM provider for avatar speech.
---

# AvatarVoiceProvider

Defined in [`parrot.integrations.liveavatar.voice_provider`](../summaries/mod:parrot.integrations.liveavatar.voice_provider.md).

```python
class AvatarVoiceProvider
```

Lazily-built, shared Supertonic→PCM provider for avatar speech.

Construct once (cheap) and store on the aiohttp ``app``.  The first call to
:meth:`synthesize_pcm` builds the ONNX pipeline; subsequent calls reuse it.

Args:
    model_dir: Supertonic model directory.  When ``None`` the standard
        resolution order is used: ``SUPERTONIC_MODEL_PATH`` env var, then
        ``<BASE_DIR>/models/supertonic-3``.
    voice: Default Supertonic voice id (``M1``..``F5``).
    language: Default BCP-47 language tag.
    target_sample_rate: Output PCM sample rate handed to the avatar.
        Defaults to :data:`AVATAR_PCM_SAMPLE_RATE` (24 kHz).

## Methods

- `async def synthesize_pcm(self, text: str) -> bytes` — Synthesize ``text`` to avatar-ready PCM (24 kHz mono 16-bit LE).
