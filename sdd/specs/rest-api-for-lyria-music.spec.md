# Feature Specification: REST API — Lyria Music Generation

**Feature ID**: FEAT-009
**Date**: 2026-02-19
**Author**: Jesus Lara
**Status**: approved
**Target version**: next

---

## 1. Motivation & Business Requirements

> Expose Lyria music generation through a dedicated, standalone HTTP handler so external clients can trigger music creation and discover available genres/moods without sharing the monolithic `GoogleGeneration` view.

### Problem Statement
`GoogleGenAIClient.generate_music` is currently accessible via the multiplexed `GoogleGeneration(BaseView)` POST endpoint (action = `"music"`), but there is no dedicated handler that:
- Follows the `BaseHandler` pattern (consistent with `StreamHandler` and the user's request).
- Provides a clean REST surface specifically for music (independent of video/image/speech actions).
- Exposes a schema/catalog GET endpoint so clients can discover `MusicGenre`, `MusicMood` enums and valid parameter ranges (BPM, temperature, density, brightness).

### Goals
- **POST** endpoint that accepts a JSON body with music parameters, invokes `GoogleGenAIClient.generate_music`, and streams the resulting WAV audio back via chunked transfer.
- **GET** endpoint that returns the catalog of available genres, moods, and parameter ranges as JSON.
- Handler inherits from `navigator.views.BaseHandler`.
- A Pydantic model (`MusicGenerationRequest`) to validate and document the POST payload.

### Non-Goals (explicitly out of scope)
- Modifying the existing `GoogleGeneration` view or its `_generate_music` method.
- Modifying `GoogleGenAIClient.generate_music` logic.
- Authentication/authorization changes (relies on existing middleware).
- WebSocket-based music streaming.
- Frontend integration.

---

## 2. Architectural Design

### Overview
Add a new handler class `LyriaMusicHandler(BaseHandler)` in `parrot/handlers/lyria_music.py` that:
1. On **POST** `/api/v1/generation/music` — validates the body against `MusicGenerationRequest`, instantiates `GoogleGenAIClient`, calls `generate_music`, and streams WAV audio chunks back via `StreamResponse`.
2. On **GET** `/api/v1/generation/music` — returns a JSON catalog with available genres, moods, and parameter ranges.

### Component Diagram
```
Client
  │
  ├── POST /api/v1/generation/music
  │        │
  │        ▼
  │   LyriaMusicHandler.post()
  │        │  validate → MusicGenerationRequest
  │        ▼
  │   GoogleGenAIClient.generate_music(prompt, genre, mood, bpm, ...)
  │        │  yields bytes
  │        ▼
  │   StreamResponse (audio/wav, chunked)
  │
  └── GET  /api/v1/generation/music
           │
           ▼
      LyriaMusicHandler.get()
           │
           ▼
      { genres: [...], moods: [...], parameters: {...} }
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `navigator.views.BaseHandler` | extends | Handler base class |
| `GoogleGenAIClient` | uses | Instantiated per-request, closed in `finally` |
| `MusicGenre` | uses | Enum for genre catalog |
| `MusicMood` | uses | Enum for mood catalog |
| `GoogleModel` | uses | Default model selection |

### Data Models

New model in `parrot/models/google.py`:
```python
class MusicGenerationRequest(BaseModel):
    """Request payload for Lyria music generation."""
    prompt: str = Field(..., description="Text description of the desired music.")
    genre: Optional[MusicGenre] = Field(None, description="Music genre.")
    mood: Optional[MusicMood] = Field(None, description="Music mood.")
    bpm: int = Field(90, ge=60, le=200, description="Beats per minute (60-200).")
    temperature: float = Field(1.0, ge=0.0, le=3.0, description="Creativity (0.0-3.0).")
    density: float = Field(0.5, ge=0.0, le=1.0, description="Note density (0.0-1.0).")
    brightness: float = Field(0.5, ge=0.0, le=1.0, description="Tonal brightness (0.0-1.0).")
    timeout: int = Field(300, ge=10, le=600, description="Max generation duration in seconds.")
```

### New Public Interfaces
```python
# parrot/handlers/lyria_music.py
class LyriaMusicHandler(BaseHandler):
    """REST handler for Lyria music generation."""

    async def post(self) -> web.StreamResponse:
        """Stream WAV audio from a MusicGenerationRequest payload."""
        ...

    async def get(self) -> web.Response:
        """Return available genres, moods, and parameter metadata."""
        ...
```

---

## 3. Module Breakdown

### Module 1: MusicGenerationRequest model
- **Path**: `parrot/models/google.py`
- **Responsibility**: Pydantic model with validated fields for the POST payload.
- **Depends on**: `MusicGenre`, `MusicMood` (same file)

### Module 2: LyriaMusicHandler
- **Path**: `parrot/handlers/lyria_music.py`
- **Responsibility**: HTTP handler with `post()` (streaming WAV) and `get()` (catalog JSON).
- **Depends on**: `BaseHandler`, `GoogleGenAIClient`, `MusicGenerationRequest`, `MusicGenre`, `MusicMood`, `GoogleModel`
- **Details**:
  - `post()`: Parse JSON → `MusicGenerationRequest(**data)` → create `GoogleGenAIClient` → iterate `generate_music()` → write chunks to `StreamResponse` → close client in `finally`.
  - `get()`: Return JSON with lists of `MusicGenre` values, `MusicMood` values, parameter ranges, and `MusicGenerationRequest.model_json_schema()`.

### Module 3: Update GoogleGenerationHelper
- **Path**: `parrot/handlers/google_generation.py`
- **Responsibility**: Add `music_generation_request` entry to `list_schemas()`.
- **Depends on**: Module 1

### Module 4: Tests
- **Path**: `tests/test_lyria_music_handler.py`
- **Responsibility**: Unit tests for the handler endpoints.
- **Depends on**: Module 1, Module 2

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_post_valid_payload` | Module 2 | POST with valid `MusicGenerationRequest` body returns 200 with audio/wav content-type |
| `test_post_missing_prompt` | Module 2 | POST without `prompt` field returns 400 |
| `test_post_invalid_bpm` | Module 2 | POST with `bpm` outside 60-200 returns 400 (Pydantic validation) |
| `test_get_catalog` | Module 2 | GET returns JSON with `genres`, `moods`, and `parameters` keys |
| `test_get_catalog_genres_complete` | Module 2 | GET `genres` list matches all `MusicGenre` enum values |
| `test_model_json_schema` | Module 1 | `MusicGenerationRequest.model_json_schema()` includes all fields with constraints |

### Integration Tests
| Test | Description |
|---|---|
| `test_end_to_end_music_stream` | Full request → mock `generate_music` yielding bytes → validate streamed WAV response |

### Test Data / Fixtures
```python
@pytest.fixture
def music_payload():
    return {
        "prompt": "Relaxing lo-fi beats for a rainy afternoon",
        "genre": "Lo-Fi Hip Hop",
        "mood": "Chill",
        "bpm": 85,
        "temperature": 1.0,
        "density": 0.4,
        "brightness": 0.3,
        "timeout": 60,
    }
```

### How to Run
```bash
source .venv/bin/activate
pytest tests/test_lyria_music_handler.py -v
```

---

## 5. Acceptance Criteria

- [ ] `POST /api/v1/generation/music` accepts a valid `MusicGenerationRequest` JSON body, streams WAV audio back.
- [ ] `POST` returns 400 on invalid payload with a descriptive error message.
- [ ] `GET /api/v1/generation/music` returns genres, moods, parameter ranges, and the full JSON schema.
- [ ] `LyriaMusicHandler` inherits from `BaseHandler`.
- [ ] `MusicGenerationRequest` model is defined with proper Pydantic constraints.
- [ ] `GoogleGenerationHelper.list_schemas()` includes `music_generation_request`.
- [ ] All unit tests pass: `pytest tests/test_lyria_music_handler.py -v`
- [ ] No breaking changes to existing endpoints.

---

## 6. Implementation Notes & Constraints

### Patterns to Follow
- Mirror `GoogleGeneration._generate_music()` streaming pattern: `StreamResponse` with `audio/wav` + chunked transfer.
- Use `StreamHandler` as the reference for `BaseHandler` inheritance.
- Instantiate `GoogleGenAIClient` per-request, close in `finally`.
- Pydantic model for payload validation (with `ge`/`le` field constraints).

### Known Risks / Gotchas
- `generate_music` is long-running (real-time streaming, up to 5 min timeout). HTTP proxies may need increased timeouts.
- `BaseHandler` vs `BaseView`: existing `GoogleGeneration` uses `BaseView`. This spec explicitly uses `BaseHandler` as requested. Both come from `navigator.views`.
- The Lyria model (`models/lyria-realtime-exp`) is experimental — API may change.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `navigator-api` | existing | Provides `BaseHandler` |
| `google-genai` | existing | Google GenAI client (Lyria) |

---

## 7. Open Questions

- [ ] **Route prefix**: Is `/api/v1/generation/music` the desired path, or should it be under a different prefix? — *Owner: Jesus*: /api/v1/google/generation/music
- [ ] **Coexistence**: Should the existing `action: "music"` in `GoogleGeneration` be deprecated in favor of this handler, or kept as-is? — *Owner: Jesus*: No
- [ ] **Download mode**: Should the endpoint also support a non-streaming mode that buffers the full audio and returns it with `Content-Length`? — *Owner: Jesus*: Yes

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-02-19 | Agent | Initial draft |
