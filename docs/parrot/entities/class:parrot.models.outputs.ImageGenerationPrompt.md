---
type: Wiki Entity
title: ImageGenerationPrompt
id: class:parrot.models.outputs.ImageGenerationPrompt
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Input schema for generating an image.
---

# ImageGenerationPrompt

Defined in [`parrot.models.outputs`](../summaries/mod:parrot.models.outputs.md).

```python
class ImageGenerationPrompt(BaseModel)
```

Input schema for generating an image.

Carries the full homologated attribute surface shared by both the Gemini
(``generate_image``) and Imagen (``generate_images``) backends. Individual
method kwargs always take precedence over the fields set here.
