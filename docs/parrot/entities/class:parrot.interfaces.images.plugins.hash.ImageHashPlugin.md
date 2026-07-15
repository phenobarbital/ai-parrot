---
type: Wiki Entity
title: ImageHashPlugin
id: class:parrot.interfaces.images.plugins.hash.ImageHashPlugin
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: ImageHashPlugin is a plugin for generating perceptual hashes of images.
relates_to:
- concept: class:parrot.interfaces.images.plugins.abstract.ImagePlugin
  rel: extends
---

# ImageHashPlugin

Defined in [`parrot.interfaces.images.plugins.hash`](../summaries/mod:parrot.interfaces.images.plugins.hash.md).

```python
class ImageHashPlugin(ImagePlugin)
```

ImageHashPlugin is a plugin for generating perceptual hashes of images.
It extends the ImagePlugin class and implements the analyze method to generate hashes.

## Methods

- `async def analyze(self, image: Image.Image, **kwargs) -> str` — Generate a perceptual hash of the given image.
