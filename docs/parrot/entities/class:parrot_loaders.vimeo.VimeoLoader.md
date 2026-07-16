---
type: Wiki Entity
title: VimeoLoader
id: class:parrot_loaders.vimeo.VimeoLoader
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Loader for Vimeo videos.
relates_to:
- concept: class:parrot_loaders.youtube.YoutubeLoader
  rel: extends
---

# VimeoLoader

Defined in [`parrot_loaders.vimeo`](../summaries/mod:parrot_loaders.vimeo.md).

```python
class VimeoLoader(YoutubeLoader)
```

Loader for Vimeo videos.

## Methods

- `async def load_video(self, url: str, video_title: str, transcript: Optional[Union[str, None]]=None) -> list`
- `def extract_video(self, url: str) -> list`
- `def extract(self) -> list`
