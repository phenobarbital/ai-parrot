# TASK-016: Voice Transcription Data Models

**Feature**: MS Teams Voice Note Support
**Spec**: `sdd/specs/msteams-voice-support.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: claude-session

---

## Context

This task implements the foundational Pydantic data models for the voice transcription feature. These models define configuration, results, and attachment parsing — used by all other modules in FEAT-008.

Reference: Spec Section 2 "Data Models"

---

## Scope

- Implement `TranscriberBackend` enum (FASTER_WHISPER, OPENAI_WHISPER)
- Implement `VoiceTranscriberConfig` model with all fields from spec
- Implement `TranscriptionResult` model
- Implement `AudioAttachment` model for parsing MS Teams attachments
- Write unit tests for model validation

**NOT in scope**:
- Backend implementations (TASK-017, TASK-018, TASK-019)
- Integration with MSTeamsAgentWrapper (TASK-021)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/integrations/msteams/voice/__init__.py` | CREATE | Package init, exports models |
| `parrot/integrations/msteams/voice/models.py` | CREATE | All Pydantic models |
| `tests/integrations/msteams/test_voice_models.py` | CREATE | Unit tests for models |

---

## Implementation Notes

### Pattern to Follow
```python
# Reference: parrot/tools/ibkr/models.py
from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum

class TranscriberBackend(str, Enum):
    """Available transcription backends."""
    FASTER_WHISPER = "faster_whisper"
    OPENAI_WHISPER = "openai_whisper"

class VoiceTranscriberConfig(BaseModel):
    """Configuration for voice transcription."""
    enabled: bool = Field(True, description="Enable voice note processing")
    backend: TranscriberBackend = Field(
        TranscriberBackend.FASTER_WHISPER,
        description="Transcription backend to use"
    )
    # ... rest of fields from spec
```

### Key Constraints
- Use `str, Enum` pattern for JSON serialization compatibility
- All fields must have descriptions for documentation
- Default values must be sensible (enabled=True, backend=FASTER_WHISPER)
- `max_audio_duration_seconds` default is 60 (per spec open questions)

### References in Codebase
- `parrot/tools/ibkr/models.py` — Pydantic model patterns
- `parrot/integrations/msteams/models.py` — existing MS Teams models

---

## Acceptance Criteria

- [ ] `TranscriberBackend` enum with two values
- [ ] `VoiceTranscriberConfig` validates all fields correctly
- [ ] `TranscriptionResult` serializes/deserializes properly
- [ ] `AudioAttachment` parses MS Teams attachment format
- [ ] All tests pass: `pytest tests/integrations/msteams/test_voice_models.py -v`
- [ ] No linting errors: `ruff check parrot/integrations/msteams/voice/`
- [ ] Import works: `from parrot.integrations.msteams.voice import VoiceTranscriberConfig`

---

## Test Specification

```python
# tests/integrations/msteams/test_voice_models.py
import pytest
from parrot.integrations.msteams.voice.models import (
    TranscriberBackend,
    VoiceTranscriberConfig,
    TranscriptionResult,
    AudioAttachment,
)


class TestVoiceTranscriberConfig:
    def test_default_values(self):
        """Config has sensible defaults."""
        config = VoiceTranscriberConfig()
        assert config.enabled is True
        assert config.backend == TranscriberBackend.FASTER_WHISPER
        assert config.model_size == "small"
        assert config.max_audio_duration_seconds == 60

    def test_openai_backend_requires_key(self):
        """OpenAI backend should accept api_key."""
        config = VoiceTranscriberConfig(
            backend=TranscriberBackend.OPENAI_WHISPER,
            openai_api_key="sk-test123"
        )
        assert config.openai_api_key == "sk-test123"


class TestTranscriptionResult:
    def test_required_fields(self):
        """Result requires text, language, duration, processing_time."""
        result = TranscriptionResult(
            text="Hello world",
            language="en",
            duration_seconds=5.2,
            processing_time_ms=1200
        )
        assert result.text == "Hello world"
        assert result.confidence is None  # optional


class TestAudioAttachment:
    def test_parse_teams_attachment(self):
        """Parses MS Teams audio attachment format."""
        attachment = AudioAttachment(
            content_url="https://teams.microsoft.com/files/audio.ogg",
            content_type="audio/ogg",
            name="voice_note.ogg"
        )
        assert attachment.content_type == "audio/ogg"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/msteams-voice-support.spec.md` for full context
2. **Check dependencies** — this task has no dependencies
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** the models following the scope above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-016-voice-transcription-models.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-24
**Notes**: Implemented all four Pydantic models:
- `TranscriberBackend` enum with FASTER_WHISPER and OPENAI_WHISPER values
- `VoiceTranscriberConfig` with all configuration fields and validation
- `TranscriptionResult` with required and optional fields
- `AudioAttachment` with helper properties (`is_voice_note`, `file_extension`)

Created package at `parrot/integrations/msteams/voice/` with proper exports.
All 30 unit tests pass.

**Deviations from spec**: none
