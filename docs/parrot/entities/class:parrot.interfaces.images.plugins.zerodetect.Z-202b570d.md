---
type: Wiki Entity
title: ZeroShotDetectionPlugin
id: class:parrot.interfaces.images.plugins.zerodetect.ZeroShotDetectionPlugin
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: ZeroShotDetectionPlugin is a plugin for performing zero-shot object detection
  using the Grounding DINO model.
relates_to:
- concept: class:parrot.interfaces.images.plugins.abstract.ImagePlugin
  rel: extends
---

# ZeroShotDetectionPlugin

Defined in [`parrot.interfaces.images.plugins.zerodetect`](../summaries/mod:parrot.interfaces.images.plugins.zerodetect.md).

```python
class ZeroShotDetectionPlugin(ImagePlugin)
```

ZeroShotDetectionPlugin is a plugin for performing zero-shot object detection using the Grounding DINO model.

## Methods

- `async def start(self)` — Initialize the model and processor.
- `async def dispose(self)` — Close the model and processor.
- `async def analyze(self, image: Image.Image, **kwargs) -> dict` — Generate a vector representation of the given image.
