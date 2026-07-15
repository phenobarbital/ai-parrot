---
type: Wiki Entity
title: AudioLoader
id: class:parrot_loaders.audio.AudioLoader
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Generating transcripts from local Audio.
relates_to:
- concept: class:parrot_loaders.basevideo.BaseVideoLoader
  rel: extends
---

# AudioLoader

Defined in [`parrot_loaders.audio`](../summaries/mod:parrot_loaders.audio.md).

```python
class AudioLoader(BaseVideoLoader)
```

Generating transcripts from local Audio.

## Methods

- `def load_video(self, path)`
- `async def load_audio(self, path: PurePath) -> list`
- `async def extract_audio(self, path: PurePath) -> list` — Extract audio transcript and summary from a local audio file.
