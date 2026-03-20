# TASK-103: Add Lyria Batch Data Models

**Feature**: google-lyria-music-generation
**Spec**: `sdd/specs/google-lyria-music-generation.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: claude-session

---

## Context

This task implements Module 1 from the spec. It adds the Pydantic data models needed for the Vertex AI Lyria batch API integration.

These models will be used by the `generate_music_batch()` method (TASK-104) to validate requests and parse responses.

---

## Scope

- Add `LyriaModel` enum to `parrot/models/google.py`
- Add `MusicBatchRequest` Pydantic model for request validation
- Add `MusicBatchResponse` Pydantic model for response parsing

**NOT in scope**:
- Implementation of the batch generation method (TASK-104)
- Modifying existing `MusicGenerationRequest` model

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/models/google.py` | MODIFY | Add LyriaModel enum, MusicBatchRequest, MusicBatchResponse |

---

## Implementation Notes

### Pattern to Follow

Follow the existing `MusicGenerationRequest` model pattern in the same file:

```python
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field

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
        description="Deterministic seed for reproducible output."
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

### Key Constraints

- Add models after existing `MusicGenerationRequest` class
- Include Field descriptions (used for documentation)
- Validate seed/sample_count exclusivity in `generate_music_batch()`, not in model

### References in Codebase

- `parrot/models/google.py:194` — existing `MusicGenerationRequest` pattern
- `parrot/models/google.py:88` — existing `MusicGenre` enum pattern

---

## Acceptance Criteria

- [ ] `LyriaModel` enum with `LYRIA_002` and `LYRIA_REALTIME` values
- [ ] `MusicBatchRequest` model with prompt, negative_prompt, seed, sample_count
- [ ] `MusicBatchResponse` model with audio_content, mime_type
- [ ] All models importable: `from parrot.models.google import LyriaModel, MusicBatchRequest, MusicBatchResponse`
- [ ] No linting errors: `ruff check parrot/models/google.py`

---

## Test Specification

```python
# tests/test_lyria_models.py
import pytest
from parrot.models.google import LyriaModel, MusicBatchRequest, MusicBatchResponse


class TestLyriaModel:
    def test_lyria_002_value(self):
        """LyriaModel.LYRIA_002 has correct value."""
        assert LyriaModel.LYRIA_002.value == "lyria-002"

    def test_lyria_realtime_value(self):
        """LyriaModel.LYRIA_REALTIME has correct value."""
        assert LyriaModel.LYRIA_REALTIME.value == "lyria-realtime-exp"


class TestMusicBatchRequest:
    def test_valid_request(self):
        """MusicBatchRequest validates with required fields."""
        req = MusicBatchRequest(prompt="Calm acoustic guitar")
        assert req.prompt == "Calm acoustic guitar"
        assert req.sample_count == 1
        assert req.seed is None

    def test_request_with_all_fields(self):
        """MusicBatchRequest accepts all optional fields."""
        req = MusicBatchRequest(
            prompt="Upbeat electronic",
            negative_prompt="drums",
            seed=42,
            sample_count=1
        )
        assert req.negative_prompt == "drums"
        assert req.seed == 42

    def test_sample_count_range(self):
        """sample_count must be 1-4."""
        with pytest.raises(ValueError):
            MusicBatchRequest(prompt="test", sample_count=5)

    def test_empty_prompt_raises(self):
        """Empty prompt raises validation error."""
        with pytest.raises(ValueError):
            MusicBatchRequest(prompt="")


class TestMusicBatchResponse:
    def test_valid_response(self):
        """MusicBatchResponse parses correctly."""
        resp = MusicBatchResponse(
            audio_content="SGVsbG8=",
            mime_type="audio/wav"
        )
        assert resp.audio_content == "SGVsbG8="
        assert resp.mime_type == "audio/wav"

    def test_default_mime_type(self):
        """mime_type defaults to audio/wav."""
        resp = MusicBatchResponse(audio_content="SGVsbG8=")
        assert resp.mime_type == "audio/wav"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/google-lyria-music-generation.spec.md` for full context
2. **Check dependencies** — this task has none
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** the models in `parrot/models/google.py`
5. **Run tests**: `pytest tests/test_lyria_models.py -v`
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-103-lyria-batch-models.md`
8. **Update index** → `"done"`

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-03-02
**Notes**: Added LyriaModel enum, MusicBatchRequest, and MusicBatchResponse models to parrot/models/google.py. Created comprehensive test suite with 16 tests in tests/test_lyria_models.py. All tests pass, linting clean.

**Deviations from spec**: Added `min_length=1` validation to MusicBatchRequest.prompt field to enforce non-empty prompts at the model level (spec suggested validating in generate_music_batch method, but Pydantic validation is more idiomatic).
