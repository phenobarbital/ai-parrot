---
type: Concept
title: load_voice_style()
id: func:parrot.voice.tts.supertonic_inference.load_voice_style
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Load a single voice-style JSON into a batch-of-one :class:`Style`.
---

# load_voice_style

```python
def load_voice_style(path: str) -> Style
```

Load a single voice-style JSON into a batch-of-one :class:`Style`.

The JSON carries ``style_ttl``/``style_dp`` as ``{"dims": [...],
"data": [...]}`` blocks; ``data`` is reshaped to ``dims[1:]`` and given a
leading batch axis.

Args:
    path: Path to a ``voice_styles/<name>.json`` file.

Returns:
    A :class:`Style` with batch size 1.
