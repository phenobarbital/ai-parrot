---
type: Wiki Entity
title: ClassificationPlugin
id: class:parrot.interfaces.images.plugins.classify.ClassificationPlugin
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: ClassificationPlugin is a plugin for performing image classification.
relates_to:
- concept: class:parrot.interfaces.images.plugins.abstract.ImagePlugin
  rel: extends
---

# ClassificationPlugin

Defined in [`parrot.interfaces.images.plugins.classify`](../summaries/mod:parrot.interfaces.images.plugins.classify.md).

```python
class ClassificationPlugin(ImagePlugin)
```

ClassificationPlugin is a plugin for performing image classification.
Uses Gemini 2.5 multimodal model for image classification tasks.

## Methods

- `async def analyze(self, image: Union[Path, Image.Image], **kwargs) -> dict` — Analyze the image and classify it into a retail category.
