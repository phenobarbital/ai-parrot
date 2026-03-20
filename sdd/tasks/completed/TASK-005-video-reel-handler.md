# TASK-005: Implement VideoReelHandler

**Feature**: REST API — Generate Video Reel
**Spec**: `docs/sdd/specs/rest-api-generate-video-reel.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: 6dbd6c81-1df6-47ce-8a07-afe0cf2c4e7f

---

## Context

> Core handler for FEAT-008. Implements Section 3 — Module 1 of the spec.
> Provides POST (invoke `generate_video_reel` pipeline) and GET (JSON Schema) endpoints.

---

## Scope

- Create `parrot/handlers/video_reel.py` with `VideoReelHandler(BaseHandler)`.
- Implement `post()`: parse JSON → `VideoReelRequest(**data)` → instantiate `GoogleGenAIClient` → call `generate_video_reel(request, output_directory, ...)` → serialize `AIMessage` result as JSON → return response. Close client in `finally`. Return 400 on validation error, 500 on pipeline failure.
- Implement `get()`: return JSON containing `VideoReelRequest.model_json_schema()`, `VideoReelScene.model_json_schema()`, and enum values for `AspectRatio`, `MusicGenre`, `MusicMood`.
- Add `configure_routes()` method to register POST and GET routes.

**NOT in scope**: Handler registration in `__init__.py` (TASK-007), tests (TASK-008), schema helper update (TASK-006).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/handlers/video_reel.py` | CREATE | VideoReelHandler implementation |

---

## Implementation Notes

### Pattern to Follow
```python
# Mirror parrot/handlers/lyria_music.py structure:
from navigator.views import BaseHandler
from parrot.clients.google import GoogleGenAIClient
from parrot.models.google import VideoReelRequest, VideoReelScene, AspectRatio, MusicGenre, MusicMood

class VideoReelHandler(BaseHandler):
    async def post(self) -> web.Response:
        data = await self.request.json()
        req = VideoReelRequest(**data)
        client = GoogleGenAIClient(model=model)
        try:
            result = await client.generate_video_reel(request=req, output_directory=output_dir)
            # Serialize AIMessage to JSON
            return self.json_response(result_dict)
        finally:
            await client.close()

    async def get(self) -> web.Response:
        schema = VideoReelRequest.model_json_schema()
        ...
```

### Key Constraints
- Use `datamodel.parsers.json.json_encoder` for serializing `AIMessage` if needed.
- `generate_video_reel` is long-running (minutes) — do not add timeouts at handler level.
- Extract optional `output_directory`, `user_id`, `session_id` from data before Pydantic validation.
- Use `self.logger` for error logging.

### References in Codebase
- `parrot/handlers/lyria_music.py` — same pattern (BaseHandler, post/get, GoogleGenAIClient)
- `parrot/clients/google/generation.py:GoogleGeneration.generate_video_reel` — the pipeline method
- `parrot/models/google.py:VideoReelRequest` — Pydantic model (line 452)

---

## Acceptance Criteria

- [ ] `VideoReelHandler` inherits from `BaseHandler`
- [ ] `post()` validates JSON body against `VideoReelRequest`
- [ ] `post()` returns 400 on invalid payload with descriptive error
- [ ] `post()` invokes `GoogleGenAIClient.generate_video_reel` and returns serialized result
- [ ] `post()` closes client in `finally` block
- [ ] `get()` returns JSON Schema for `VideoReelRequest` with nested type schemas
- [ ] No linting errors: `ruff check parrot/handlers/video_reel.py`
- [ ] Import works: `from parrot.handlers.video_reel import VideoReelHandler`

---

## Test Specification

| Test | Description |
|---|---|
| `test_post_valid_payload` | POST with valid `VideoReelRequest` body returns 200 |
| `test_post_invalid_payload` | POST without `prompt` returns 400 |
| `test_get_schema` | GET returns JSON Schema with all required fields |

*(Full test implementation is in TASK-008)*

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none for this task
3. **Update status** in `tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-005-video-reel-handler.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: 6dbd6c81-1df6-47ce-8a07-afe0cf2c4e7f
**Date**: 2026-02-19
**Notes**: Created `parrot/handlers/video_reel.py` with `VideoReelHandler(BaseHandler)`. Implements `post()` (validate VideoReelRequest, invoke generate_video_reel, serialize AIMessage via json_encoder), `get()` (schema catalog with nested types and enum values), and `configure_routes()`. Ruff clean, import verified.

**Deviations from spec**: Route is `/api/v1/google/generation/video_reel` (matching the Lyria handler prefix pattern), GET schema endpoint at `/api/v1/google/generation/video_reel/schema`.
