# TASK-466: Understanding Handler Implementation

**Feature**: image-video-understanding-handler
**Spec**: `sdd/specs/image-video-understanding-handler.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-465
**Assigned-to**: unassigned

---

## Context

This is the core task — implements the aiohttp handler that receives image or video
uploads via POST, dispatches to the correct `GoogleGenAIClient` method, and returns
the analysis result. Implements **Module 2** from the spec.

---

## Scope

- Implement `UnderstandingHandler(BaseView)` in `parrot/handlers/understanding.py`.
- **POST handler** (`async def post`):
  1. Parse request body — support both `multipart/form-data` (file upload) and `application/json` (with `media_url`).
  2. For multipart: read the `file` field, save to a temp file, detect media type from filename/content-type.
  3. For JSON: parse body into `UnderstandingRequest`, use `media_url` and `media_type`.
  4. Determine media type: explicit `media_type` field → content-type header → file extension.
  5. **Image path**: call `client.image_understanding(prompt=prompt, images=[path], detect_objects=True)`.
  6. **Video path**: call `client.video_understanding(prompt=prompt, video=path, as_image=True, stateless=True)`.
  7. Serialise `AIMessage` → `UnderstandingResponse` → JSON.
  8. Clean up temp files in a `finally` block.
- **GET handler** (`async def get`): return JSON schema catalog (request schema + supported media types + defaults).
- **`setup()` classmethod**: register routes at `/api/v1/google/understanding`.
- Use `self.logger` throughout for request lifecycle logging.

**NOT in scope**: route registration in `__init__.py` (TASK-467), integration tests with real API (TASK-468).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/handlers/understanding.py` | CREATE | Main handler with POST and GET |
| `tests/handlers/test_understanding_handler.py` | CREATE | Unit tests with mocked client |

---

## Implementation Notes

### Pattern to Follow
```python
# Follow LyriaMusicHandler / VideoReelHandler patterns
import logging
import tempfile
from pathlib import Path
from aiohttp import web
from navigator.views import BaseView
from parrot.clients.google.client import GoogleGenAIClient
from parrot.handlers.models.understanding import (
    UnderstandingRequest,
    UnderstandingResponse,
    media_type_from_filename,
)

class UnderstandingHandler(BaseView):
    _logger_name = "Parrot.UnderstandingHandler"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.logger = logging.getLogger(self._logger_name)

    @classmethod
    def setup(cls, app, route="/api/v1/google/understanding"):
        _app = app.get_app() if hasattr(app, 'get_app') else app
        _app.router.add_view(route, cls)

    async def post(self) -> web.Response:
        # 1. Detect content type (multipart vs JSON)
        # 2. Extract prompt + media file/URL
        # 3. Determine image vs video
        # 4. Call appropriate client method
        # 5. Return serialised response
        ...

    async def get(self) -> web.Response:
        # Return parameter catalog / JSON schema
        ...
```

### Multipart Handling
```python
async def _handle_multipart(self):
    """Parse multipart/form-data, return (prompt, file_path, media_type)."""
    reader = await self.request.multipart()
    prompt = None
    file_path = None
    media_type = None
    temp_dir = tempfile.mkdtemp()

    async for part in reader:
        if part.name == "prompt":
            prompt = (await part.read()).decode("utf-8")
        elif part.name == "file":
            filename = part.filename or "upload"
            file_path = Path(temp_dir) / filename
            with open(file_path, "wb") as f:
                while chunk := await part.read_chunk():
                    f.write(chunk)
            # Detect from content-type header or filename
            content_type = part.headers.get("Content-Type", "")
            if content_type.startswith("video/"):
                media_type = "video"
            elif content_type.startswith("image/"):
                media_type = "image"
            else:
                media_type = media_type_from_filename(filename)
        elif part.name == "media_type":
            media_type = (await part.read()).decode("utf-8")

    return prompt, file_path, media_type, temp_dir
```

### Key Constraints
- Always clean up temp files in a `finally` block using `shutil.rmtree(temp_dir)`.
- Instantiate `GoogleGenAIClient` per-request, use `async with client:`.
- Forward `model`, `temperature`, `timeout` from request to client when provided.
- Return 400 for missing prompt, missing media, or unsupported media type.
- Return 500 with logged traceback for client errors.

### References in Codebase
- `parrot/handlers/lyria_music.py` — handler pattern with BaseView
- `parrot/handlers/video_reel.py` — multipart file handling pattern
- `parrot/clients/google/analysis.py` — `image_understanding`, `video_understanding` signatures

---

## Acceptance Criteria

- [ ] POST with multipart image file → calls `image_understanding` → returns 200
- [ ] POST with multipart video file → calls `video_understanding` → returns 200
- [ ] POST with JSON body + `media_url` → dispatches correctly
- [ ] Missing prompt → 400
- [ ] Missing media (no file + no URL) → 400
- [ ] GET → returns JSON schema catalog
- [ ] Temp files cleaned up after every request
- [ ] All tests pass: `pytest tests/handlers/test_understanding_handler.py -v`

---

## Test Specification

```python
# tests/handlers/test_understanding_handler.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from parrot.handlers.understanding import UnderstandingHandler


@pytest.fixture
def mock_ai_message():
    msg = MagicMock()
    msg.content = "A red square on white background"
    msg.structured_output = {"detections": []}
    msg.model = "gemini-2.5-flash"
    msg.provider = "google_genai"
    msg.usage = None
    return msg


class TestUnderstandingHandler:
    @pytest.mark.asyncio
    async def test_image_dispatches_to_image_understanding(self, mock_ai_message):
        """Verify image uploads call image_understanding with detect_objects=True."""
        ...

    @pytest.mark.asyncio
    async def test_video_dispatches_to_video_understanding(self, mock_ai_message):
        """Verify video uploads call video_understanding with as_image=True, stateless=True."""
        ...

    @pytest.mark.asyncio
    async def test_missing_prompt_returns_400(self):
        """POST without prompt returns 400."""
        ...

    @pytest.mark.asyncio
    async def test_missing_media_returns_400(self):
        """POST without file or URL returns 400."""
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/image-video-understanding-handler.spec.md`
2. **Check dependencies** — verify TASK-465 is in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-466-understanding-handler.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-03-27
**Notes**: All 19 unit tests pass. Handler supports multipart file upload and JSON+URL modes. Media type detection from Content-Type header and file extension. Temp file cleanup in finally block. GET endpoint returns parameter catalog/schema.

**Deviations from spec**: none
