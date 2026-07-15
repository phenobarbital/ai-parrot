---
type: Wiki Entity
title: VideoResolution
id: class:parrot.models.generation.VideoResolution
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Supported video resolutions for VEO models.
---

# VideoResolution

Defined in [`parrot.models.generation`](../summaries/mod:parrot.models.generation.md).

```python
class VideoResolution(str, Enum)
```

Supported video resolutions for VEO models.

Notes:
    - ``1080p`` and ``4k`` require ``duration=8`` and are unsupported by VEO 2.0.
    - Video extension only supports ``720p``.
