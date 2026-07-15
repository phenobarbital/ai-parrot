---
type: Wiki Entity
title: LyriaMusicHandler
id: class:parrot.handlers.lyria_music.LyriaMusicHandler
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: REST handler for Lyria music generation.
---

# LyriaMusicHandler

Defined in [`parrot.handlers.lyria_music`](../summaries/mod:parrot.handlers.lyria_music.md).

```python
class LyriaMusicHandler(BaseView)
```

REST handler for Lyria music generation.

Endpoints:
    POST /api/v1/google/generation/music — Generate music via Lyria.
    GET  /api/v1/google/generation/music — Catalog of genres, moods, and schema.

## Methods

- `async def post(self) -> web.StreamResponse` — Generate music from a MusicGenerationRequest payload.
- `async def get(self) -> web.Response` — Return catalog of genres, moods, parameter ranges, and JSON schema.
