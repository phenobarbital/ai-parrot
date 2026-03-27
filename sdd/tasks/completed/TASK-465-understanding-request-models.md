# TASK-465: Understanding Request & Response Models

**Feature**: image-video-understanding-handler
**Spec**: `sdd/specs/image-video-understanding-handler.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This task creates the Pydantic data models used by the Understanding REST handler.
These models validate incoming requests and serialise outgoing responses.
Implements **Module 1** from the spec.

---

## Scope

- Implement `UnderstandingRequest` Pydantic model with fields: `prompt`, `media_url`, `media_type`, `model`, `detect_objects`, `as_image`, `temperature`, `timeout`.
- Implement `UnderstandingResponse` Pydantic model with fields: `content`, `structured_output`, `model`, `provider`, `usage`.
- Add a helper function `media_type_from_filename(filename: str) -> str` that returns `"image"` or `"video"` based on file extension, or raises `ValueError` for unknown extensions.
- Write unit tests for model validation and the media-type detection helper.

**NOT in scope**: handler implementation, route registration, integration tests.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/handlers/models/understanding.py` | CREATE | Pydantic request/response models + media_type helper |
| `tests/handlers/test_understanding_models.py` | CREATE | Unit tests for models and helper |
| `parrot/handlers/models/__init__.py` | MODIFY | Export new models (create if missing) |

---

## Implementation Notes

### Pattern to Follow
```python
# Follow the pattern from existing handler models
from pydantic import BaseModel, Field
from typing import Optional

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".webm", ".mkv", ".flv", ".wmv"}

def media_type_from_filename(filename: str) -> str:
    """Return 'image' or 'video' based on file extension."""
    ext = Path(filename).suffix.lower()
    if ext in IMAGE_EXTENSIONS:
        return "image"
    if ext in VIDEO_EXTENSIONS:
        return "video"
    raise ValueError(f"Unsupported media extension: {ext}")

class UnderstandingRequest(BaseModel):
    prompt: str = Field(..., description="Analysis prompt / question")
    media_url: Optional[str] = Field(None, description="URL to image or video")
    media_type: Optional[str] = Field(None, description="'image' or 'video'")
    model: Optional[str] = Field(None, description="GoogleModel override")
    detect_objects: bool = Field(True, description="Enable object detection for images")
    as_image: bool = Field(True, description="Extract frames for video analysis")
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0)
    timeout: Optional[int] = Field(600, ge=1, le=3600)
```

### Key Constraints
- All fields must have clear `description` for JSON schema generation.
- `media_type` must validate against `("image", "video")` when provided.
- `UnderstandingResponse` should have a `@classmethod from_ai_message(cls, msg: AIMessage)` factory.

### References in Codebase
- `parrot/models/responses.py` — `AIMessage` model
- `parrot/handlers/models/` — existing handler model patterns (if any)

---

## Acceptance Criteria

- [ ] `UnderstandingRequest` validates correct input and rejects bad input
- [ ] `UnderstandingResponse.from_ai_message()` correctly serialises an `AIMessage`
- [ ] `media_type_from_filename()` correctly classifies image and video extensions
- [ ] `media_type_from_filename()` raises `ValueError` for unknown extensions
- [ ] All tests pass: `pytest tests/handlers/test_understanding_models.py -v`
- [ ] Import works: `from parrot.handlers.models.understanding import UnderstandingRequest, UnderstandingResponse`

---

## Test Specification

```python
# tests/handlers/test_understanding_models.py
import pytest
from parrot.handlers.models.understanding import (
    UnderstandingRequest,
    UnderstandingResponse,
    media_type_from_filename,
)


class TestMediaTypeDetection:
    @pytest.mark.parametrize("ext", [".png", ".jpg", ".jpeg", ".gif", ".webp"])
    def test_image_extensions(self, ext):
        assert media_type_from_filename(f"file{ext}") == "image"

    @pytest.mark.parametrize("ext", [".mp4", ".mov", ".avi", ".webm", ".mkv"])
    def test_video_extensions(self, ext):
        assert media_type_from_filename(f"file{ext}") == "video"

    def test_unknown_extension_raises(self):
        with pytest.raises(ValueError, match="Unsupported"):
            media_type_from_filename("file.xyz")


class TestUnderstandingRequest:
    def test_valid_request(self):
        req = UnderstandingRequest(prompt="Describe this image")
        assert req.prompt == "Describe this image"
        assert req.detect_objects is True

    def test_missing_prompt_raises(self):
        with pytest.raises(Exception):
            UnderstandingRequest()

    def test_invalid_media_type_rejected(self):
        with pytest.raises(Exception):
            UnderstandingRequest(prompt="x", media_type="audio")
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/image-video-understanding-handler.spec.md`
2. **Check dependencies** — none for this task
3. **Update status** in `tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-465-understanding-request-models.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-03-27
**Notes**: All 32 unit tests pass. Models include UnderstandingRequest, UnderstandingResponse with from_ai_message() factory, and media_type_from_filename() helper. Note: implementation was pre-committed as "video understanding api" on the feature branch.

**Deviations from spec**: none
