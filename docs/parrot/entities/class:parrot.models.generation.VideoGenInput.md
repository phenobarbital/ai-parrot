---
type: Wiki Entity
title: VideoGenInput
id: class:parrot.models.generation.VideoGenInput
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Structured input for VEO video generation with all supported parameters.
---

# VideoGenInput

Defined in [`parrot.models.generation`](../summaries/mod:parrot.models.generation.md).

```python
class VideoGenInput(BaseModel)
```

Structured input for VEO video generation with all supported parameters.

Accepted by ``video_generation`` as an alternative to a plain ``str`` prompt.
When individual kwargs are also passed to ``video_generation``, they override
the values from this model.

See: https://ai.google.dev/gemini-api/docs/video
