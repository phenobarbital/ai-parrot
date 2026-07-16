---
type: Wiki Summary
title: parrot.voice.tts.supertonic_inference
id: mod:parrot.voice.tts.supertonic_inference
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Supertonic ONNX inference wiring (4-graph flow-matching TTS).
relates_to:
- concept: class:parrot.voice.tts.supertonic_inference.Style
  rel: defines
- concept: class:parrot.voice.tts.supertonic_inference.SupertonicONNXBackend
  rel: defines
- concept: class:parrot.voice.tts.supertonic_inference.SupertonicPipeline
  rel: defines
- concept: class:parrot.voice.tts.supertonic_inference.UnicodeProcessor
  rel: defines
- concept: func:parrot.voice.tts.supertonic_inference.chunk_text
  rel: defines
- concept: func:parrot.voice.tts.supertonic_inference.get_latent_mask
  rel: defines
- concept: func:parrot.voice.tts.supertonic_inference.length_to_mask
  rel: defines
- concept: func:parrot.voice.tts.supertonic_inference.load_voice_style
  rel: defines
- concept: mod:parrot.voice.tts.supertonic_backend
  rel: references
---

# `parrot.voice.tts.supertonic_inference`

Supertonic ONNX inference wiring (4-graph flow-matching TTS).

The :class:`SupertonicTTSBackend` in ``supertonic_backend.py`` is intentionally
agnostic about the concrete Supertonic ONNX graph I/O — it exposes an
``inference_fn`` seam (FEAT-231 §8 R-deps). This module fills that seam for the
public **Supertonic-3** weights (``Supertone/supertonic-3`` on Hugging Face),
which ship the model split across four ONNX graphs run in sequence:

    text  --tokenise-->  text_ids ----------------------------------+
                                                                     |
    duration_predictor(text_ids, style_dp, text_mask)  -->  duration |
    text_encoder(text_ids, style_ttl, text_mask)        -->  text_emb |
    vector_estimator(noisy_latent, text_emb, ..., step) -->  latent   |  x total_step
    vocoder(latent)                                     -->  waveform <+

The math mirrors the upstream reference (``py/helper.py`` in
``supertone-inc/supertonic``); it is reimplemented here against
``numpy``/``onnxruntime`` only — no upstream package dependency.

Expected on-disk layout (as produced by ``make install-supertonic``)::

    <model_dir>/
    ├── onnx/
    │   ├── duration_predictor.onnx
    │   ├── text_encoder.onnx
    │   ├── vector_estimator.onnx
    │   ├── vocoder.onnx
    │   ├── tts.json              # config (sample_rate, chunk sizes, latent_dim)
    │   └── unicode_indexer.json  # codepoint -> token id table
    └── voice_styles/
        ├── M1.json … M5.json     # speaker style vectors (style_ttl + style_dp)
        └── F1.json … F5.json

``SUPERTONIC_MODEL_PATH`` (or ``model_dir=``) should point at ``<model_dir>``
(the directory that *contains* ``onnx/`` and ``voice_styles/``). Pointing it
directly at the ``onnx/`` directory is also tolerated. When neither is given,
the backend falls back to ``<BASE_DIR>/models/supertonic-3`` — exactly where
``make install-supertonic`` puts the weights — so a standard checkout works
with no configuration at all.

Added by FEAT-231 follow-up (Supertonic 4-graph inference wiring).

## Classes

- **`UnicodeProcessor`** — Codepoint-based text tokeniser for Supertonic.
- **`Style`** — A speaker style: the two conditioning tensors Supertonic consumes.
- **`SupertonicPipeline`** — Runs the Supertonic-3 four-graph pipeline and returns raw PCM.
- **`SupertonicONNXBackend(SupertonicTTSBackend)`** — :class:`SupertonicTTSBackend` wired for the real Supertonic-3 weights.

## Functions

- `def length_to_mask(lengths: np.ndarray, max_len: Optional[int]=None) -> np.ndarray` — Build a binary length mask of shape ``(B, 1, max_len)``.
- `def get_latent_mask(wav_lengths: np.ndarray, base_chunk_size: int, chunk_compress_factor: int) -> np.ndarray` — Mask the latent sequence to the per-item audio length.
- `def chunk_text(text: str, max_len: int=300) -> list[str]` — Split text into synthesis-sized chunks by paragraph then sentence.
- `def load_voice_style(path: str) -> Style` — Load a single voice-style JSON into a batch-of-one :class:`Style`.
