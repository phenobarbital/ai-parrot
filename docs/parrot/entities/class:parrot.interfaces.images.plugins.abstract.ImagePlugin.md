---
type: Wiki Entity
title: ImagePlugin
id: class:parrot.interfaces.images.plugins.abstract.ImagePlugin
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: ImagePlugin is a base class for image processing plugins.
---

# ImagePlugin

Defined in [`parrot.interfaces.images.plugins.abstract`](../summaries/mod:parrot.interfaces.images.plugins.abstract.md).

```python
class ImagePlugin(ABC)
```

ImagePlugin is a base class for image processing plugins.
It provides a common interface for image processing tasks.
Subclasses should implement the `analyze` method to define
the specific image processing logic.

## Methods

- `async def analyze(self, image: Image.Image, **kwargs) -> Any` — Analyze the image and perform the desired processing.
- `async def start(self)` — Start the plugin. This method can be overridden by subclasses
- `async def dispose(self)` — Dispose of the plugin resources.
