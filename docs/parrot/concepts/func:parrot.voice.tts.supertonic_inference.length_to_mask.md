---
type: Concept
title: length_to_mask()
id: func:parrot.voice.tts.supertonic_inference.length_to_mask
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Build a binary length mask of shape ``(B, 1, max_len)``.
---

# length_to_mask

```python
def length_to_mask(lengths: np.ndarray, max_len: Optional[int]=None) -> np.ndarray
```

Build a binary length mask of shape ``(B, 1, max_len)``.

Args:
    lengths: Per-item valid lengths, shape ``(B,)``.
    max_len: Mask width; defaults to ``lengths.max()``.

Returns:
    Float32 mask, ``1.0`` for valid positions and ``0.0`` for padding.
