---
type: Wiki Entity
title: SupertonicONNXBackend
id: class:parrot.voice.tts.supertonic_inference.SupertonicONNXBackend
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: :class:`SupertonicTTSBackend` wired for the real Supertonic-3 weights.
relates_to:
- concept: class:parrot.voice.tts.supertonic_backend.SupertonicTTSBackend
  rel: extends
---

# SupertonicONNXBackend

Defined in [`parrot.voice.tts.supertonic_inference`](../summaries/mod:parrot.voice.tts.supertonic_inference.md).

```python
class SupertonicONNXBackend(SupertonicTTSBackend)
```

:class:`SupertonicTTSBackend` wired for the real Supertonic-3 weights.

Overrides session creation to load the four-graph
:class:`SupertonicPipeline` and bind it as the backend's ``inference_fn``.
Everything else (async offload, WAV wrapping, empty-text guard, truthful
``mime_format``) is inherited unchanged.

Construction stays cheap — the heavy ONNX load happens lazily on the first
``synthesize`` call, via :meth:`_ensure_session`.

Args:
    model_dir: Directory with ``onnx/`` and ``voice_styles/``. Defaults to
        ``SUPERTONIC_MODEL_PATH``.
    voice: Default voice id (``M1``..``F5``). ``None`` → ``default_voice``.
    onnx_subdir: ONNX subdirectory name.
    voice_styles_subdir: Voice-styles subdirectory name.
    default_voice: Voice used when neither ``voice`` nor the call supplies one.
    total_step: Flow-matching denoising steps.
    speed: Speech-rate multiplier.
    use_gpu: Reserved (CPU only).
    **kwargs: Forwarded to :class:`SupertonicTTSBackend`.
