---
type: Wiki Overview
title: 'TASK-1460: Audio Data Models'
id: doc:sdd-tasks-completed-task-1460-audio-data-models-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Defines the Pydantic data models shared by the audio renderer and the
---

# TASK-1460: Audio Data Models

**Feature**: FEAT-224 — FormDesigner Audio Renderer
**Spec**: `sdd/specs/formdesigner-audio-renderer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Defines the Pydantic data models shared by the audio renderer and the
WebSocket handler. These models are the data contract for the entire audio
form session. Implements Spec §3 Module 3.

---

## Scope

- Create the `parrot_formdesigner/audio/` subpackage with `__init__.py` and `models.py`.
- Implement the following Pydantic models:
  - `AudioSessionConfig` — session configuration (form_id, locale, tts settings).
  - `AudioQuestion` — a single question in the session (index, field_id, label, etc.).
  - `AudioFormManifest` — session manifest (list of questions, ws_endpoint, metadata).
  - `AudioAnswer` — an answer to a question (value, source text/speech, confidence).
  - `AudioSessionState` — server-side session state (current index, answers dict).
- Write comprehensive unit tests for serialization, validation, and edge cases.

**NOT in scope**: Renderer logic, WebSocket handler, TTS/STT integration.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/audio/__init__.py` | CREATE | Subpackage init with public exports |
| `packages/parrot-formdesigner/src/parrot_formdesigner/audio/models.py` | CREATE | All audio data models |
| `tests/formdesigner/test_audio_models.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pydantic import BaseModel, Field  # standard pydantic
```

### Existing Signatures to Use
```python
# No existing classes to extend — these are new models.
# Follow the Pydantic pattern used throughout the codebase:
# packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py:24
class FormField(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field_id: str
    field_type: FieldType
    label: LocalizedString
    # ... (reference for Pydantic style)
```

### Does NOT Exist
- ~~`parrot_formdesigner.audio`~~ — subpackage does not exist yet, this task creates it
- ~~`parrot_formdesigner.audio.models`~~ — does not exist yet
- ~~`parrot_formdesigner.models.AudioQuestion`~~ — no audio models anywhere in the package

---

## Implementation Notes

### Pattern to Follow
```python
# Follow existing Pydantic model patterns from core/schema.py
from pydantic import BaseModel, Field
from typing import Optional


class AudioSessionConfig(BaseModel):
    """Configuration for an audio form session."""
    form_id: str
    locale: str = "en"
    tts_voice: Optional[str] = None
    tts_mime_format: str = "audio/ogg"
    auto_advance: bool = True
```

### Key Constraints
- Use `model_config = ConfigDict(extra="forbid")` for strict validation.
- `AudioQuestion.audio_prompt` stores raw bytes (TTS output) — use `Optional[bytes]`.
- `AudioAnswer.source` should be a `Literal["text", "speech"]`.
- `AudioSessionState.answers` is `dict[str, AudioAnswer]` keyed by `field_id`.
- All models must be JSON-serializable (except `audio_prompt` bytes — exclude from JSON manifest or base64-encode).

### References in Codebase
- `packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py` — Pydantic model style
- Spec §2 Data Models — complete field definitions

---

## Acceptance Criteria

- [ ] `AudioSessionConfig` validates with required `form_id` and defaults
- [ ] `AudioQuestion` serializes to JSON (audio_prompt excluded or base64)
- [ ] `AudioFormManifest` holds a list of `AudioQuestion` and metadata
- [ ] `AudioAnswer` enforces `source` is `"text"` or `"speech"`
- [ ] `AudioSessionState` tracks current question index and answers
- [ ] All models reject extra fields (`extra="forbid"`)
- [ ] Tests pass: `pytest tests/formdesigner/test_audio_models.py -v`
- [ ] No linting errors: `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/audio/`

---

## Test Specification

```python
# tests/formdesigner/test_audio_models.py
import pytest
from pydantic import ValidationError
from parrot_formdesigner.audio.models import (
    AudioAnswer,
    AudioFormManifest,
    AudioQuestion,
    AudioSessionConfig,
    AudioSessionState,
)


class TestAudioSessionConfig:
    def test_defaults(self):
        cfg = AudioSessionConfig(form_id="f1")
        assert cfg.locale == "en"
        assert cfg.tts_mime_format == "audio/ogg"
        assert cfg.auto_advance is True

    def test_requires_form_id(self):
        with pytest.raises(ValidationError):
            AudioSessionConfig()


class TestAudioQuestion:
    def test_minimal(self):
        q = AudioQuestion(index=0, field_id="name", field_type="text", label="Name?")
        assert q.required is False

    def test_with_options(self):
        q = AudioQuestion(
            index=1, field_id="color", field_type="select",
            label="Favorite color?",
            options=[{"value": "red", "label": "Red"}],
        )
        assert len(q.options) == 1


class TestAudioAnswer:
    def test_text_source(self):
        a = AudioAnswer(field_id="name", value="Alice", source="text")
        assert a.confidence is None

    def test_speech_source(self):
        a = AudioAnswer(field_id="name", value="Alice", source="speech", confidence=0.95)
        assert a.confidence == 0.95


class TestAudioSessionState:
    def test_initial_state(self):
        state = AudioSessionState(session_id="s1", form_id="f1", user_id="u1")
        assert state.current_index == 0
        assert state.answers == {}
        assert state.completed is False

    def test_add_answer(self):
        state = AudioSessionState(session_id="s1", form_id="f1", user_id="u1")
        state.answers["name"] = AudioAnswer(field_id="name", value="Alice", source="text")
        assert "name" in state.answers
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/formdesigner-audio-renderer.spec.md` §2 Data Models
2. **Check dependencies** — this task has none (models are standalone)
3. **Verify the Codebase Contract** — confirm `parrot_formdesigner/audio/` does not exist yet
4. **Update status** in `sdd/tasks/index/formdesigner-audio-renderer.json` → `"in-progress"`
5. **Implement** the models package
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1460-audio-data-models.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-06-04
**Notes**: Created `parrot_formdesigner/audio/__init__.py` and `audio/models.py` with all 5 Pydantic models (AudioSessionConfig, AudioQuestion, AudioFormManifest, AudioAnswer, AudioSessionState). All models use ConfigDict(extra="forbid"). AudioAnswer.source uses Literal["text","speech"]. 18 unit tests pass.

**Deviations from spec**: none
