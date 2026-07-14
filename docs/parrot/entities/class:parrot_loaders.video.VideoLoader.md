---
type: Wiki Entity
title: VideoLoader
id: class:parrot_loaders.video.VideoLoader
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Generating Video transcripts from URL Videos.
relates_to:
- concept: class:parrot_loaders.basevideo.BaseVideoLoader
  rel: extends
---

# VideoLoader

Defined in [`parrot_loaders.video`](../summaries/mod:parrot_loaders.video.md).

```python
class VideoLoader(BaseVideoLoader)
```

Generating Video transcripts from URL Videos.

## Methods

- `def download_video(self, url: str, path: str) -> Path` — Downloads a video from a URL using yt-dlp.
- `async def load_video(self, url: str, video_title: str, transcript: str) -> list`
- `def parse(self, source)`
