---
type: Concept
title: get_latent_mask()
id: func:parrot.voice.tts.supertonic_inference.get_latent_mask
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Mask the latent sequence to the per-item audio length.
---

# get_latent_mask

```python
def get_latent_mask(wav_lengths: np.ndarray, base_chunk_size: int, chunk_compress_factor: int) -> np.ndarray
```

Mask the latent sequence to the per-item audio length.

Args:
    wav_lengths: Per-item waveform sample counts, shape ``(B,)``.
    base_chunk_size: Vocoder base chunk size (samples per latent frame).
    chunk_compress_factor: Latent compression factor from the config.

Returns:
    Latent mask of shape ``(B, 1, latent_len)``.
