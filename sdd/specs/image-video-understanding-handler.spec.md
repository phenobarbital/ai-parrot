# Feature Specification: Image & Video Understanding REST API Handler

**Feature ID**: FEAT-066
**Date**: 2026-03-27
**Author**: AI-Parrot Team
**Status**: approved
**Target version**: 0.next

---

## 1. Motivation & Business Requirements

### Problem Statement

AI-Parrot already exposes `GoogleGenAIClient.image_understanding()` and
`GoogleGenAIClient.video_understanding()` as library methods, but there is no
HTTP endpoint that lets external services or front-end apps call them via REST.
Operators need a single POST endpoint that automatically dispatches to the
correct analysis method based on the uploaded media type (image vs video).

### Goals
- Provide a **single REST handler** (`POST /api/v1/google/understanding`) that
  accepts an image or video and returns AI-powered analysis.
- For **images**: call `image_understanding(detect_objects=True)` and return
  structured detection results.
- For **videos**: call `video_understanding(as_image=True, stateless=True)` and
  return the analysis.
- Support multipart file upload and JSON-with-URL modes.
- Return responses as serialised `AIMessage` (content + structured_output + usage).

### Non-Goals (explicitly out of scope)
- Streaming / SSE responses (future enhancement).
- Authentication / authorisation (handled by middleware already in place).
- Support for providers other than Google GenAI (may be added later).
- Background job / polling pattern (analysis is synchronous per request).

---

## 2. Architectural Design

### Overview

A new `UnderstandingHandler(BaseView)` handler receives a POST request,
inspects the content type of the uploaded file (or the explicit `media_type`
field), dispatches to either `image_understanding` or `video_understanding` on
`GoogleGenAIClient`, and returns the `AIMessage` as JSON.

### Component Diagram
```
Client (POST multipart/json)
       │
       ▼
 UnderstandingHandler (BaseView)
       │
       ├─ image? ──→ GoogleGenAIClient.image_understanding(detect_objects=True)
       │                       │
       │                       ▼
       │                  AIMessage (content + structured_output)
       │
       └─ video? ──→ GoogleGenAIClient.video_understanding(as_image=True, stateless=True)
                               │
                               ▼
                          AIMessage (content)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `GoogleGenAIClient` | uses | Instantiated per-request with optional model override |
| `GoogleAnalysis` mixin | uses (via client) | `image_understanding`, `video_understanding` |
| `navigator.views.BaseView` | extends | Handler base class (aiohttp) |
| `AIMessage` | returns | Serialised response model |
| `GoogleModel` | config | Enum for model selection |
| `DetectionBox`, `Detection` | data | Returned inside `structured_output` for images |

### Data Models

```python
from pydantic import BaseModel, Field
from typing import Optional

class UnderstandingRequest(BaseModel):
    """Request body for JSON mode (non-multipart)."""
    prompt: str = Field(..., description="Analysis prompt / question")
    media_url: Optional[str] = Field(None, description="URL to image or video")
    media_type: Optional[str] = Field(
        None,
        description="Explicit media type hint: 'image' or 'video'. "
                    "Auto-detected from extension/content-type when omitted."
    )
    model: Optional[str] = Field(None, description="GoogleModel override")
    detect_objects: bool = Field(True, description="Enable object detection for images")
    as_image: bool = Field(True, description="Extract frames for video analysis")
    temperature: Optional[float] = Field(None, description="Sampling temperature")
    timeout: Optional[int] = Field(600, description="Request timeout in seconds")

class UnderstandingResponse(BaseModel):
    """Serialised AIMessage subset returned to the caller."""
    content: str
    structured_output: Optional[dict] = None
    model: Optional[str] = None
    provider: str = "google_genai"
    usage: Optional[dict] = None
```

### New Public Interfaces

```python
class UnderstandingHandler(BaseView):
    """REST handler for image and video understanding.

    Endpoints:
        POST /api/v1/google/understanding — Analyse image or video
        GET  /api/v1/google/understanding — Return parameter catalog/schema
    """

    @classmethod
    def setup(cls, app, route="/api/v1/google/understanding"): ...

    async def post(self) -> web.Response: ...
    async def get(self) -> web.Response: ...
```

---

## 3. Module Breakdown

### Module 1: Request Models
- **Path**: `parrot/handlers/models/understanding.py`
- **Responsibility**: Pydantic request/response models (`UnderstandingRequest`, `UnderstandingResponse`)
- **Depends on**: `parrot.models` (AIMessage, GoogleModel)

### Module 2: Understanding Handler
- **Path**: `parrot/handlers/understanding.py`
- **Responsibility**: aiohttp handler with POST (analyse) and GET (catalog) endpoints.
  Media-type detection logic, multipart file handling, client dispatch.
- **Depends on**: Module 1, `GoogleGenAIClient`, `BaseView`

### Module 3: Route Registration
- **Path**: `parrot/handlers/__init__.py` (update)
- **Responsibility**: Import `UnderstandingHandler` and wire `setup()` into the app router.
- **Depends on**: Module 2

### Module 4: Unit & Integration Tests
- **Path**: `tests/handlers/test_understanding.py`
- **Responsibility**: Test handler routing, media-type detection, request validation,
  mocked client calls, and end-to-end integration with real images.
- **Depends on**: Modules 1-3

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_image_detected_by_extension` | Module 2 | `.png`, `.jpg`, `.webp` → image path |
| `test_video_detected_by_extension` | Module 2 | `.mp4`, `.mov`, `.webm` → video path |
| `test_explicit_media_type_overrides` | Module 2 | `media_type=video` forces video path |
| `test_missing_prompt_returns_400` | Module 2 | No prompt → 400 error |
| `test_missing_media_returns_400` | Module 2 | No file and no URL → 400 error |
| `test_request_model_validation` | Module 1 | Pydantic rejects bad input |
| `test_response_serialisation` | Module 1 | AIMessage → UnderstandingResponse |

### Integration Tests
| Test | Description |
|---|---|
| `test_post_image_returns_detections` | Upload a test PNG, verify structured_output has detections |
| `test_post_video_returns_analysis` | Upload a short video, verify content text |
| `test_get_returns_catalog` | GET endpoint returns JSON schema |

### Test Data / Fixtures
```python
@pytest.fixture
def sample_image(tmp_path):
    """Create a simple test image with a red rectangle."""
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (500, 500), "white")
    ImageDraw.Draw(img).rectangle([100, 100, 300, 300], fill="red")
    path = tmp_path / "test.png"
    img.save(path)
    return path

@pytest.fixture
def mock_google_client(mocker):
    """Mock GoogleGenAIClient for unit tests."""
    ...
```

---

## 5. Acceptance Criteria

- [ ] `POST /api/v1/google/understanding` with an image file calls `image_understanding(detect_objects=True)` and returns 200 with `structured_output`
- [ ] `POST /api/v1/google/understanding` with a video file calls `video_understanding(as_image=True, stateless=True)` and returns 200
- [ ] Multipart file upload works (field name: `file`)
- [ ] JSON body with `media_url` works for remote images/videos
- [ ] Media type auto-detected from file extension / content-type header
- [ ] Explicit `media_type` field overrides auto-detection
- [ ] Missing prompt or media returns 400 with clear error message
- [ ] `GET /api/v1/google/understanding` returns parameter catalog / JSON schema
- [ ] All unit tests pass
- [ ] No breaking changes to existing handlers or client API

---

## 6. Implementation Notes & Constraints

### Patterns to Follow
- Inherit from `navigator.views.BaseView` (same as `LyriaMusicHandler`, `VideoReelHandler`)
- Instantiate `GoogleGenAIClient` per-request, use `async with client:` context manager
- Use `self.logger` for all logging
- Pydantic validation for request body
- Return `self.json_response()` / `self.error()` from BaseView

### Media-Type Detection Heuristic
```
1. If `media_type` field is set → use it
2. Else if multipart → inspect Content-Type header of the part
3. Else if URL → inspect file extension
4. image extensions: .png, .jpg, .jpeg, .gif, .webp, .bmp, .tiff
5. video extensions: .mp4, .mov, .avi, .webm, .mkv, .flv, .wmv
```

### Known Risks / Gotchas
- Large video uploads may hit aiohttp's default body size limit — configure `client_max_size` on the route.
- `video_understanding` can take up to 10 minutes for long videos — the `timeout` parameter should be forwarded.
- Multipart temp files must be cleaned up after processing.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `google-genai` | `>=1.0` | Already in project — Google GenAI SDK |
| `Pillow` | `>=10.0` | Already in project — image handling |
| `aiohttp` | `>=3.9` | Already in project — HTTP framework |

---

## 7. Open Questions

- [ ] Should the endpoint split into two routes (`/understanding/image` and `/understanding/video`) instead of a single auto-detecting route? — *Owner: team*: No.
- [ ] Should we support batch analysis (multiple images in one request)? — *Owner: team*: No.

---

## Worktree Strategy

- **Isolation unit**: per-spec (sequential tasks)
- All 4 modules are tightly coupled and should be implemented in order within a single worktree.
- **Cross-feature dependencies**: None — `GoogleAnalysis` methods already exist.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-03-27 | AI-Parrot Team | Initial draft |
