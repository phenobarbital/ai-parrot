---
type: Wiki Entity
title: VideoLocalLoader
id: class:parrot_loaders.videolocal.VideoLocalLoader
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Generating Video transcripts from local Videos.
relates_to:
- concept: class:parrot_loaders.basevideo.BaseVideoLoader
  rel: extends
---

# VideoLocalLoader

Defined in [`parrot_loaders.videolocal`](../summaries/mod:parrot_loaders.videolocal.md).

```python
class VideoLocalLoader(BaseVideoLoader)
```

Generating Video transcripts from local Videos.

## Methods

- `async def load_video(self, url: str, video_title: str, transcript: str) -> list`
