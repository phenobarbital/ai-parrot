# Feature Specification: Google Lyria Music Generation Enhancement

**Feature ID**: FEAT-020
**Date**: 2026-03-02
**Author**: Jesus Lara
**Status**: approved
**Target version**: 1.x.x
**Brainstorm**: `sdd/proposals/google-lyria-music-generation.brainstorm.md`

---

## 1. Motivation & Business Requirements

### Problem Statement

The `GoogleGenAIClient` already has a `generate_music` method using **Lyria RealTime** (streaming WebSocket API). However, this implementation:

1. **Streams raw PCM bytes** — requires external handling to create usable audio files
2. **Only supports Lyria RealTime** — the Vertex AI batch endpoint (`lyria-002`) offers simpler, non-streaming generation
3. **Lacks clear naming** — current method name doesn't indicate it's streaming
4. **No reproducibility** — RealTime API doesn't support deterministic seeds

**Users affected**: Developers building AI music applications, video reel generation (already uses music), batch audio processing pipelines.

### Goals

- Add `generate_music_batch()` method using Vertex AI Lyria batch API (`lyria-002`)
- Return complete WAV files instead of raw PCM streams
- Support reproducible generation via `seed` parameter
- Support `negative_prompt` for excluding unwanted musical elements
- Rename existing `generate_music` to `generate_music_stream` for API clarity

### Non-Goals (explicitly out of scope)

- Lyria 3 integration (AI vocals, multimodal input) — deferred until public API availability
- SynthID watermark detection utilities
- Real-time steering/interactive music sessions
- MP3/OGG format conversion (WAV output only)

---

## 2. Architectural Design

### Overview

Add a new `generate_music_batch()` method to the `GoogleGeneration` mixin that calls the Vertex AI Lyria REST API. This complements the existing streaming approach with a simpler batch alternative.

**Key difference from existing `generate_music`:**
- Single HTTP POST vs. WebSocket connection
- Returns complete files vs. yielding byte chunks
- Supports `seed` for deterministic output
- Requires Vertex AI (not available via Gemini API key)

### Component Diagram

```
User Code
    │
    ▼
GoogleGenAIClient (client.py)
    │  inherits from
    ▼
GoogleGeneration (generation.py)
    │
    ├─► generate_music_stream()  ──► Lyria RealTime (WebSocket)
    │   (renamed from generate_music)
    │
    └─► generate_music_batch()   ──► Vertex AI REST API
            │                         POST lyria-002:predict
            ▼
        MusicBatchRequest         ──► MusicBatchResponse
        (Pydantic model)              (base64 WAV)
            │
            ▼
        _save_audio_file()        ──► Output: List[Path]
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `GoogleGeneration` mixin | extends | Add new method alongside existing |
| `GoogleGenAIClient.get_client()` | uses | Vertex AI credentials |
| `_save_audio_file()` | uses | WAV file encoding (already exists) |
| `MusicGenre`, `MusicMood` enums | uses | Existing prompt building |
| `MusicGenerationRequest` | reference | Pattern for new request model |

### Data Models

```python
from typing import Optional, List
from pathlib import Path
from pydantic import BaseModel, Field
from enum import Enum

class LyriaModel(str, Enum):
    """Available Lyria models."""
    LYRIA_002 = "lyria-002"
    LYRIA_REALTIME = "lyria-realtime-exp"

class MusicBatchRequest(BaseModel):
    """Request payload for Lyria batch music generation."""
    prompt: str = Field(
        ...,
        description="Text description of the desired music in US English."
    )
    negative_prompt: Optional[str] = Field(
        None,
        description="Elements to exclude from generation (e.g., 'drums, vocals')."
    )
    seed: Optional[int] = Field(
        None,
        description="Deterministic seed for reproducible output. Cannot combine with sample_count > 1."
    )
    sample_count: int = Field(
        1,
        ge=1,
        le=4,
        description="Number of audio samples to generate (1-4)."
    )

class MusicBatchResponse(BaseModel):
    """Response from Lyria batch API."""
    audio_content: str = Field(..., description="Base64-encoded WAV audio")
    mime_type: str = Field(default="audio/wav")
```

### New Public Interfaces

```python
class GoogleGeneration:
    """Mixin for Google Generative AI generation capabilities."""

    async def generate_music_batch(
        self,
        prompt: str,
        negative_prompt: Optional[str] = None,
        seed: Optional[int] = None,
        sample_count: int = 1,
        output_directory: Optional[Path] = None,
        genre: Optional[Union[str, MusicGenre]] = None,
        mood: Optional[Union[str, MusicMood]] = None,
    ) -> List[Path]:
        """
        Generate music using Vertex AI Lyria batch API.

        Returns complete 30-second WAV files (48kHz stereo).

        Args:
            prompt: Text description of desired music.
            negative_prompt: Elements to exclude from generation.
            seed: Deterministic seed (cannot combine with sample_count > 1).
            sample_count: Number of variations to generate (1-4).
            output_directory: Where to save files (default: temp dir).
            genre: Music genre hint (appended to prompt).
            mood: Music mood hint (appended to prompt).

        Returns:
            List of Paths to generated WAV files.

        Raises:
            ValueError: If prompt is empty or seed used with sample_count > 1.
            AuthenticationError: If Vertex AI credentials invalid.
        """
        ...

    # Renamed from generate_music for clarity
    async def generate_music_stream(
        self,
        prompt: str,
        genre: Optional[Union[str, MusicGenre]] = None,
        mood: Optional[Union[str, MusicMood]] = None,
        bpm: int = 90,
        temperature: float = 1.0,
        density: float = 0.5,
        brightness: float = 0.5,
        timeout: int = 300
    ) -> AsyncIterator[bytes]:
        """
        Stream music using Lyria RealTime API.

        Yields raw 48kHz stereo PCM audio chunks.

        Note: Renamed from generate_music() for API clarity.
        """
        ...

    # Deprecation alias
    @deprecated("Use generate_music_stream() instead")
    async def generate_music(self, *args, **kwargs) -> AsyncIterator[bytes]:
        """Deprecated: Use generate_music_stream() instead."""
        return self.generate_music_stream(*args, **kwargs)
```

---

## 3. Module Breakdown

### Module 1: Data Models

- **Path**: `parrot/models/google.py`
- **Responsibility**: Add `LyriaModel` enum and `MusicBatchRequest`/`MusicBatchResponse` models
- **Depends on**: Existing Pydantic imports

### Module 2: Batch Generation Method

- **Path**: `parrot/clients/google/generation.py`
- **Responsibility**: Implement `generate_music_batch()` method in `GoogleGeneration` mixin
- **Depends on**: Module 1 (models), existing `_save_audio_file()`, `get_client()`

### Module 3: Method Rename + Deprecation

- **Path**: `parrot/clients/google/generation.py`
- **Responsibility**: Rename `generate_music` → `generate_music_stream`, add deprecation alias
- **Depends on**: None (refactor only)

### Module 4: Update Internal Callers

- **Path**: `parrot/clients/google/generation.py`
- **Responsibility**: Update `_generate_reel_music()` to use new method name
- **Depends on**: Module 3

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_music_batch_request_validation` | Module 1 | MusicBatchRequest validates prompt, seed/sample_count exclusivity |
| `test_generate_music_batch_builds_payload` | Module 2 | Correct JSON payload construction |
| `test_generate_music_batch_with_seed` | Module 2 | Seed parameter passed correctly |
| `test_generate_music_batch_with_negative_prompt` | Module 2 | Negative prompt included |
| `test_generate_music_batch_saves_files` | Module 2 | WAV files saved to output directory |
| `test_generate_music_batch_empty_prompt_raises` | Module 2 | ValueError on empty prompt |
| `test_generate_music_batch_seed_with_samples_raises` | Module 2 | ValueError on seed + sample_count > 1 |
| `test_generate_music_stream_alias` | Module 3 | Deprecated `generate_music` calls `generate_music_stream` |

### Integration Tests

| Test | Description |
|---|---|
| `test_lyria_batch_end_to_end` | Generate music via Vertex AI, verify WAV output |
| `test_lyria_batch_reproducibility` | Same seed produces same output hash |
| `test_reel_generation_uses_stream` | Video reel generation still works after rename |

### Test Data / Fixtures

```python
import pytest
from pathlib import Path

@pytest.fixture
def music_batch_request():
    return {
        "prompt": "Calm acoustic guitar melody",
        "negative_prompt": "drums, electric guitar",
        "seed": 42
    }

@pytest.fixture
def mock_lyria_response():
    # Minimal valid WAV header + silence
    return {
        "predictions": [{
            "audioContent": "UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQAAAAA=",
            "mimeType": "audio/wav"
        }]
    }

@pytest.fixture
def output_dir(tmp_path):
    return tmp_path / "music_output"
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `generate_music_batch()` generates valid 30-second WAV files
- [ ] `seed` parameter produces reproducible output (same seed = same audio)
- [ ] `negative_prompt` successfully excludes specified elements
- [ ] `sample_count` generates correct number of variations
- [ ] Existing `generate_music` renamed to `generate_music_stream`
- [ ] Deprecation warning emitted when calling old `generate_music` name
- [ ] `_generate_reel_music` updated to use new method name
- [ ] All unit tests pass (`pytest tests/test_lyria*.py -v`)
- [ ] Integration test passes with real Vertex AI credentials
- [ ] No breaking changes to existing video reel generation
- [ ] Example code added to `examples/clients/`

---

## 6. Implementation Notes & Constraints

### Patterns to Follow

- Use `aiohttp` for HTTP POST (consistent with existing code)
- Use `google.oauth2.service_account` for Vertex AI auth (existing pattern)
- Follow `generate_images` method as reference for batch API patterns
- Use `self.logger` for all logging
- Create output directory if it doesn't exist (like `generate_images`)

### Known Risks / Gotchas

| Risk | Mitigation |
|---|---|
| Vertex AI quotas/rate limits | Implement retry with exponential backoff |
| Large base64 response (30s WAV ~2.8MB) | Stream response body, don't load entirely in memory |
| Content safety rejection | Return empty list, log warning (don't raise) |
| API endpoint changes | Use constants for URL construction |

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `aiohttp` | `>=3.8` | Async HTTP client (already in deps) |
| `google-auth` | `>=2.0` | Service account auth (already in deps) |
| `pydantic` | `>=2.0` | Request/response models (already in deps) |

### API Reference

**Endpoint:**
```
POST https://{LOCATION}-aiplatform.googleapis.com/v1/projects/{PROJECT_ID}/locations/{LOCATION}/publishers/google/models/lyria-002:predict
```

**Request:**
```json
{
  "instances": [{
    "prompt": "Calm acoustic folk song with gentle guitar",
    "negative_prompt": "drums, electric guitar",
    "seed": 42
  }],
  "parameters": {
    "sample_count": 1
  }
}
```

**Response:**
```json
{
  "predictions": [{
    "audioContent": "<base64-encoded-wav>",
    "mimeType": "audio/wav"
  }]
}
```

---

## 7. Open Questions

All open questions from brainstorm have been resolved:

- [x] Add to `GoogleGeneration` mixin (not directly to client) — **Resolved: Yes**
- [x] Deprecate `generate_music` → `generate_music_stream` — **Resolved: Yes**
- [x] Include SynthID metadata utilities — **Resolved: No**

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-03-02 | Claude | Initial draft from brainstorm |
