---
type: Wiki Entity
title: Style
id: class:parrot.voice.tts.supertonic_inference.Style
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'A speaker style: the two conditioning tensors Supertonic consumes.'
---

# Style

Defined in [`parrot.voice.tts.supertonic_inference`](../summaries/mod:parrot.voice.tts.supertonic_inference.md).

```python
class Style
```

A speaker style: the two conditioning tensors Supertonic consumes.

Attributes:
    ttl: ``style_ttl`` tensor (text-encoder / vector-estimator conditioning).
    dp: ``style_dp`` tensor (duration-predictor conditioning).
