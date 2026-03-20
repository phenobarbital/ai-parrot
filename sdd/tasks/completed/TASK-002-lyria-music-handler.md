# TASK-002: Implement LyriaMusicHandler

**Feature**: REST API — Lyria Music Generation
**Spec**: `docs/sdd/specs/rest-api-for-lyria-music.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-001
**Assigned-to**: unassigned

---

## Context

> Core handler task for FEAT-009. Creates the dedicated REST endpoint for Lyria music generation.
> Implements spec Section 3 — Module 2.
> User confirmed route: `/api/v1/google/generation/music`.
> User confirmed: also support non-streaming (download) mode.

---

## Scope

- Create `parrot/handlers/lyria_music.py` with `LyriaMusicHandler(BaseHandler)`.
- **`post()`**: Parse JSON body → validate via `MusicGenerationRequest` → instantiate `GoogleGenAIClient` → call `generate_music()` → stream WAV audio chunks via `StreamResponse`. On validation error return 400.
  - If request body includes `"stream": false`, buffer the entire audio and return with `Content-Type: audio/wav` and `Content-Length`.
- **`get()`**: Return JSON catalog: `{ genres: [...], moods: [...], parameters: { bpm: { min, max, default }, ... }, schema: MusicGenerationRequest.model_json_schema() }`.
- Register the handler's routes via a `configure_routes` method (pattern from `StreamHandler`).

**NOT in scope**: `GoogleGenerationHelper` update (TASK-003), tests (TASK-004).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/handlers/lyria_music.py` | CREATE | Handler with `post()` and `get()` |
| `parrot/handlers/__init__.py` | MODIFY | Add import (lazy or direct) |

---

## Implementation Notes

### Pattern to Follow
```python
# Follow StreamHandler (parrot/handlers/stream.py) for BaseHandler inheritance
# Follow GoogleGeneration._generate_music (parrot/handlers/google_generation.py:125)
# for the streaming pattern

from navigator.views import BaseHandler
from parrot.clients.google import GoogleGenAIClient
from parrot.models.google import (
    MusicGenerationRequest, MusicGenre, MusicMood, GoogleModel
)

class LyriaMusicHandler(BaseHandler):
    """REST handler for Lyria music generation."""

    async def post(self) -> web.StreamResponse:
        data = await self.request.json()
        try:
            req = MusicGenerationRequest(**data)
        except ValidationError as e:
            return self.error(str(e), status=400)

        client = GoogleGenAIClient(model=GoogleModel.GEMINI_2_5_FLASH.value)
        try:
            if data.get("stream", True):
                # Streaming mode
                stream = web.StreamResponse(
                    status=200,
                    headers={"Content-Type": "audio/wav", "Transfer-Encoding": "chunked"},
                )
                await stream.prepare(self.request)
                async for chunk in client.generate_music(
                    prompt=req.prompt, genre=req.genre, mood=req.mood,
                    bpm=req.bpm, temperature=req.temperature,
                    density=req.density, brightness=req.brightness,
                    timeout=req.timeout,
                ):
                    await stream.write(chunk)
                await stream.write_eof()
                return stream
            else:
                # Download mode — buffer full audio
                audio_bytes = b""
                async for chunk in client.generate_music(...):
                    audio_bytes += chunk
                return web.Response(
                    body=audio_bytes,
                    content_type="audio/wav",
                    headers={"Content-Length": str(len(audio_bytes))},
                )
        finally:
            await client.close()
```

### Key Constraints
- Client must be closed in `finally`.
- Use `self.request` (BaseHandler provides it).
- Route: `/api/v1/google/generation/music` (confirmed by user).
- Default to streaming mode (`stream: true`).

### References in Codebase
- `parrot/handlers/stream.py` — `BaseHandler` inheritance pattern
- `parrot/handlers/google_generation.py:125-148` — `_generate_music` streaming
- `parrot/clients/google/generation.py:897-986` — `generate_music` signature

---

## Acceptance Criteria

- [x] `LyriaMusicHandler` class exists and inherits from `BaseHandler`
- [x] `post()` validates body via `MusicGenerationRequest`, returns 400 on invalid input
- [x] `post()` streams WAV audio in chunked mode by default
- [x] `post()` buffers and returns full audio when `stream: false`
- [x] `get()` returns genres, moods, parameter ranges, and schema JSON
- [x] `configure_routes()` registers GET and POST on `/api/v1/google/generation/music`
- [x] Client is always closed in `finally`
- [x] No linting errors: `ruff check parrot/handlers/lyria_music.py`

---

## Test Specification

> See TASK-004 for full test suite. Smoke test:

```python
from parrot.handlers.lyria_music import LyriaMusicHandler
assert issubclass(LyriaMusicHandler, BaseHandler)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-001 must be in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-002-lyria-music-handler.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: Antigravity
**Date**: 2026-02-19
**Notes**: Handler was already implemented. Added lazy import to `parrot/handlers/__init__.py`. All smoke tests and ruff checks pass.

**Deviations from spec**: none
