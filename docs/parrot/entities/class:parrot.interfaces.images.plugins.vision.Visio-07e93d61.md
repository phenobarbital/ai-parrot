---
type: Wiki Entity
title: VisionTransformerPlugin
id: class:parrot.interfaces.images.plugins.vision.VisionTransformerPlugin
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: VisionTransformerPlugin is a plugin for generating vector representations
  of images.
relates_to:
- concept: class:parrot.interfaces.images.plugins.abstract.ImagePlugin
  rel: extends
---

# VisionTransformerPlugin

Defined in [`parrot.interfaces.images.plugins.vision`](../summaries/mod:parrot.interfaces.images.plugins.vision.md).

```python
class VisionTransformerPlugin(ImagePlugin)
```

VisionTransformerPlugin is a plugin for generating vector representations of images.
It extends the ImagePlugin class and implements the analyze method to generate vectors.

## Methods

- `async def start(self)`
- `async def dispose(self)` — Close the model and processor.
- `async def analyze(self, image: Image.Image, **kwargs) -> np.ndarray` — Generate a vector representation of the given image.
