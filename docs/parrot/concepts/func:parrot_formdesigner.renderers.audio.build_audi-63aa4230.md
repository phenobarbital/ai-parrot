---
type: Concept
title: build_audio_synthesizer()
id: func:parrot_formdesigner.renderers.audio.build_audio_synthesizer
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Build a VoiceSynthesizer preferring SuperTonic, else None (FEAT-236).
---

# build_audio_synthesizer

```python
def build_audio_synthesizer(config: AudioSessionConfig | None=None) -> 'VoiceSynthesizer | None'
```

Build a VoiceSynthesizer preferring SuperTonic, else None (FEAT-236).

Constructs a ``VoiceSynthesizer`` configured with the preferred TTS backend
(``config.tts_backend``, default ``"supertonic"``). The backend itself is
created lazily on first ``synthesize()`` — no model is loaded here. Returns
``None`` when the ``parrot.voice`` TTS stack is not importable at all
(text-only session). The SuperTonic→Google→text-only fallback at synthesis
time lives in :func:`synthesize_with_fallback`.

Args:
    config: Optional session config carrying ``tts_backend``,
        ``tts_voice`` and ``tts_mime_format``.

Returns:
    A configured ``VoiceSynthesizer``, or ``None`` if voice TTS is
    unavailable.
