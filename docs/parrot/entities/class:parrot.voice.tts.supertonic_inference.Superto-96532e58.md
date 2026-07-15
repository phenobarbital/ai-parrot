---
type: Wiki Entity
title: SupertonicPipeline
id: class:parrot.voice.tts.supertonic_inference.SupertonicPipeline
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Runs the Supertonic-3 four-graph pipeline and returns raw PCM.
---

# SupertonicPipeline

Defined in [`parrot.voice.tts.supertonic_inference`](../summaries/mod:parrot.voice.tts.supertonic_inference.md).

```python
class SupertonicPipeline
```

Runs the Supertonic-3 four-graph pipeline and returns raw PCM.

The instance is **callable** with the signature
``SupertonicTTSBackend`` expects for ``inference_fn``::

    pipeline(session, text, *, voice, language, sample_rate) -> bytes

The ``session`` and ``sample_rate`` arguments are ignored (the pipeline
owns its own four ONNX sessions and reports its native sample rate via
:attr:`sample_rate`); they exist only to satisfy the seam contract.

Loading is eager — the constructor opens all four ONNX sessions, the
config and the tokeniser table — so build it lazily (e.g. from the
backend's ``_ensure_session``) to keep object construction cheap.

Args:
    model_dir: Directory containing ``onnx/`` and ``voice_styles/`` (or the
        ``onnx`` directory itself).
    onnx_subdir: Name of the ONNX subdirectory under ``model_dir``.
    voice_styles_subdir: Name of the voice-styles subdirectory.
    default_voice: Voice id used when the caller passes ``None``.
    total_step: Number of flow-matching denoising steps (higher = smoother,
        slower). Upstream default is 8.
    speed: Speech-rate multiplier (>1 = faster). Upstream default is 1.05.
    use_gpu: Reserved; CPU execution only for now.

## Methods

- `def synthesize_pcm(self, text: str, *, voice: Optional[str]=None, language: Optional[str]=None, silence_duration: float=0.3) -> bytes` — Synthesize ``text`` to raw PCM (16-bit LE mono at :attr:`sample_rate`).
