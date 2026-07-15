---
type: Wiki Entity
title: VideoUnderstandingLoader
id: class:parrot_loaders.videounderstanding.VideoUnderstandingLoader
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Video analysis loader using Google GenAI for understanding video content.
relates_to:
- concept: class:parrot_loaders.basevideo.BaseVideoLoader
  rel: extends
---

# VideoUnderstandingLoader

Defined in [`parrot_loaders.videounderstanding`](../summaries/mod:parrot_loaders.videounderstanding.md).

```python
class VideoUnderstandingLoader(BaseVideoLoader)
```

Video analysis loader using Google GenAI for understanding video content.
Extracts step-by-step instructions and spoken text from training videos.

## Methods

- `async def load_video(self, url: str, video_title: str, transcript: str) -> list` — Required abstract method implementation.
- `async def close(self)` — Clean up resources.
