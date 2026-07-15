---
type: Wiki Entity
title: DetectionPlugin
id: class:parrot.interfaces.images.plugins.detect.DetectionPlugin
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: DetectionPlugin is a plugin for performing image detection.
relates_to:
- concept: class:parrot.interfaces.images.plugins.classifybase.ClassifyBase
  rel: extends
---

# DetectionPlugin

Defined in [`parrot.interfaces.images.plugins.detect`](../summaries/mod:parrot.interfaces.images.plugins.detect.md).

```python
class DetectionPlugin(ClassifyBase)
```

DetectionPlugin is a plugin for performing image detection.
Uses Gemini 2.5 multimodal model for image detection tasks.

## Methods

- `async def analyze(self, image: Union[Path, Image.Image], **kwargs) -> dict` — Analyze the image and classify it into a retail category.
