# Feature Specification: REST API — Generate Video Reel

**Feature ID**: FEAT-008
**Date**: 2026-02-19
**Author**: Jesus Lara
**Status**: approved
**Target version**: next

---

## 1. Motivation & Business Requirements

> Expose the existing `generate_video_reel` pipeline through HTTP so external clients (frontend, mobile, third-party integrators) can trigger reel generation and discover the required payload shape without reading source code.

### Problem Statement
`GoogleGenAIClient.generate_video_reel` is only accessible programmatically. There is no REST surface for it; other generation actions (video, image, music, speech) already have HTTP endpoints in `GoogleGeneration` but video reels do not. Additionally, clients need a machine-readable way to discover the `VideoReelRequest` schema (and its nested types) to build dynamic forms.

### Goals
- **POST** endpoint that accepts a `VideoReelRequest` JSON body, invokes `generate_video_reel`, and returns the result (file paths / streaming).
- **GET** endpoint that returns the full JSON Schema for `VideoReelRequest` (including `VideoReelScene`, `AspectRatio`, `MusicGenre`, `MusicMood`).
- Handler inherits from `BaseHandler` (from `navigator.views`).

### Non-Goals (explicitly out of scope)
- Modifying the `generate_video_reel` pipeline itself.
- Authentication/authorization changes (relies on existing middleware).
- WebSocket or SSE streaming of generation progress.
- Frontend integration.

---

## 2. Architectural Design

### Overview
Add a new handler class `VideoReelHandler(BaseHandler)` in `parrot/handlers/video_reel.py` that:
1. On **POST** `/api/v1/generation/video_reel` — validates the body against `VideoReelRequest`, instantiates `GoogleGenAIClient`, calls `generate_video_reel`, and returns the `AIMessage` result as JSON (or streams the final file).
2. On **GET** `/api/v1/generation/video_reel/schema` — returns the JSON Schema for `VideoReelRequest` (via `model_json_schema()`), enriched with the schemas for nested types.

### Component Diagram
```
Client
  │
  ├── POST /api/v1/generation/video_reel
  │        │
  │        ▼
  │   VideoReelHandler.post()
  │        │
  │        ▼
  │   GoogleGenAIClient.generate_video_reel(request)
  │        │
  │        ▼
  │   AIMessage (files, usage)
  │
  └── GET  /api/v1/generation/video_reel/schema
           │
           ▼
      VideoReelHandler.get()
           │
           ▼
      VideoReelRequest.model_json_schema()
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `navigator.views.BaseHandler` | extends | Handler base class |
| `GoogleGenAIClient` | uses | Instantiated per-request, closed in `finally` |
| `VideoReelRequest` | uses | Pydantic model for payload validation |
| `GoogleGenerationHelper` | extends | Add `video_reel_request` to `list_schemas()` |
| `AIMessageFactory` | uses (indirectly) | Called inside `generate_video_reel` |

### Data Models
No new models needed. Existing models consumed:
```python
# parrot/models/google.py
class VideoReelRequest(BaseModel): ...   # line 406
class VideoReelScene(BaseModel): ...     # line 381
class AspectRatio(str, Enum): ...        # line 203
class MusicGenre(str, Enum): ...         # line 88
class MusicMood(str, Enum): ...          # line 159
```

### New Public Interfaces
```python
# parrot/handlers/video_reel.py
class VideoReelHandler(BaseHandler):
    """REST handler for video reel generation."""

    async def post(self) -> web.Response:
        """Generate a video reel from a VideoReelRequest payload."""
        ...

    async def get(self) -> web.Response:
        """Return JSON Schema for VideoReelRequest and nested types."""
        ...
```

---

## 3. Module Breakdown

### Module 1: VideoReelHandler
- **Path**: `parrot/handlers/video_reel.py`
- **Responsibility**: HTTP handler with `post()` and `get()` methods.
- **Depends on**: `navigator.views.BaseHandler`, `GoogleGenAIClient`, `VideoReelRequest`
- **Details**:
  - `post()`: Parse JSON body → `VideoReelRequest(**data)` → extract optional `output_directory`, `user_id`, `session_id` → call `client.generate_video_reel(request, ...)` → serialize `AIMessage` to JSON → return response. On error return 400/500.
  - `get()`: Build schema dict via `VideoReelRequest.model_json_schema()` → return JSON. Also include `VideoReelScene.model_json_schema()` and enum values for `AspectRatio`, `MusicGenre`, `MusicMood`.

### Module 2: Update GoogleGenerationHelper
- **Path**: `parrot/handlers/google_generation.py`
- **Responsibility**: Add `video_reel_request` entry to `list_schemas()`.
- **Depends on**: Module 1 (conceptually, same models)

### Module 3: Handler registration
- **Path**: `parrot/handlers/__init__.py` (and/or route configuration)
- **Responsibility**: Import `VideoReelHandler` and register routes.
- **Depends on**: Module 1

### Module 4: Tests
- **Path**: `tests/test_video_reel_handler.py`
- **Responsibility**: Unit tests for the handler endpoints.
- **Depends on**: Module 1

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_post_valid_payload` | Module 1 | POST with valid `VideoReelRequest` body returns 200 with file paths |
| `test_post_invalid_payload` | Module 1 | POST with missing `prompt` field returns 400 |
| `test_get_schema` | Module 1 | GET returns JSON Schema with all required fields/definitions |
| `test_schema_includes_enums` | Module 1 | GET schema includes `AspectRatio`, `MusicGenre`, `MusicMood` enum values |

### Integration Tests
| Test | Description |
|---|---|
| `test_end_to_end_reel` | Full request → mock pipeline → response (mocked `GoogleGenAIClient`) |

### Test Data / Fixtures
```python
@pytest.fixture
def video_reel_payload():
    return {
        "prompt": "A cinematic reel about ocean conservation",
        "music_genre": "Chillout",
        "aspect_ratio": "9:16",
    }
```

### Existing Tests
- `tests/test_google_reel.py` — covers `generate_video_reel` at the client level (mock-based). Handler-level tests are new.

### How to Run
```bash
source .venv/bin/activate
pytest tests/test_video_reel_handler.py -v
pytest tests/test_google_reel.py -v   # existing, sanity check
```

---

## 5. Acceptance Criteria

- [ ] `POST /api/v1/generation/video_reel` accepts a valid `VideoReelRequest` JSON body, invokes the pipeline, and returns the serialized `AIMessage`.
- [ ] `POST` returns 400 on invalid payload with a descriptive error message.
- [ ] `GET /api/v1/generation/video_reel/schema` returns the full JSON Schema for `VideoReelRequest` (plus nested type definitions).
- [ ] `VideoReelHandler` inherits from `BaseHandler`.
- [ ] `GoogleGenerationHelper.list_schemas()` includes `video_reel_request`.
- [ ] All unit tests pass: `pytest tests/test_video_reel_handler.py -v`
- [ ] No breaking changes to existing endpoints.

---

## 6. Implementation Notes & Constraints

### Patterns to Follow
- Mirror `GoogleGeneration._generate_video()` pattern: instantiate client, call method, close in `finally`.
- Use `datamodel.parsers.json.json_encoder` for serializing `AIMessage`.
- Follow `StreamHandler` pattern for `BaseHandler` inheritance.
- Use `self._stream_file()` helper for optional binary streaming of the final reel file.

### Known Risks / Gotchas
- `generate_video_reel` is long-running (minutes). The HTTP request may time out. A future enhancement could add a job-queue / polling pattern, but that is out of scope for this spec.
- `BaseHandler` vs `BaseView` choice: existing `GoogleGeneration` uses `BaseView`. The user explicitly requested `BaseHandler`; confirm this is intentional (both come from `navigator.views`).

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `navigator-api` | existing | Provides `BaseHandler` |
| `google-genai` | existing | Google GenAI client |
| `moviepy` | existing | Used by `generate_video_reel` assembly (already a dependency) |

---

## 7. Open Questions

- [ ] **Route prefix**: Is `/api/v1/generation/video_reel` the desired path, or should it nest under `/api/v1/google/` or another prefix? — *Owner: Jesus*
- [ ] **BaseHandler vs BaseView**: The existing `GoogleGeneration` uses `BaseView`. The user asked for `BaseHandler`. Confirm which is preferred. — *Owner: Jesus*
- [ ] **Long-running timeout**: Should the endpoint return immediately with a job ID (async pattern) or block until completion? — *Owner: Jesus*

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-02-19 | Agent | Initial draft |
