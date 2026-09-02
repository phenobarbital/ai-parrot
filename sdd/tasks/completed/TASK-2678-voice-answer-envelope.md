# TASK-2678: VoiceAnswerEnvelope Model

**Feature**: FEAT-488 — FormField Content-Type
**Spec**: `sdd/specs/formfield-content-type.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2677
**Assigned-to**: unassigned

---

## Context

Introduces the `VoiceAnswerEnvelope` Pydantic model — the canonical JSON
shape for fields answered with a voice note (transcription + optional audio
blob reference). This model is the concrete payload submitted when a
`TEXT_AREA` field with `accept_content_types=["text/plain", "application/json"]`
receives a voice answer. Follows the `FileEnvelope` pattern (FEAT-460).

Implements spec §3 Module 2.

---

## Scope

- Create `packages/parrot-formdesigner/src/parrot_formdesigner/core/voice_answer.py` (new file).
- Define `VoiceAnswerEnvelope(BaseModel)` with `model_config = ConfigDict(extra="forbid")`,
  fields: `answer: str`, `blob_ref: str | None = None`, `data_url: str | None = None`.
- Export `VoiceAnswerEnvelope` from `parrot_formdesigner.core` by adding it to `core/__init__.py`.

**NOT in scope**: validator changes, renderer changes, or tests (covered by TASK-2684).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/voice_answer.py` | CREATE | `VoiceAnswerEnvelope` Pydantic model |
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/__init__.py` | MODIFY | Export `VoiceAnswerEnvelope` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# For core/voice_answer.py (new file)
from pydantic import BaseModel, ConfigDict, Field

# For core/__init__.py (existing file — add one import line)
from .voice_answer import VoiceAnswerEnvelope
```

### Existing Signatures to Use

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/core/file_envelope.py
# — blueprint; mirror this structure exactly

class FileEnvelope(BaseModel):                   # line 16
    model_config = ConfigDict(extra="forbid")    # line 33
    filename: str = Field(..., description="Original filename with extension")  # line 35
    content_type: str = Field(..., description="MIME type of the file")         # line 36
    size: int = Field(..., ge=0, description="File size in bytes")              # line 37
    blob_ref: str | None = Field(default=None, description="Server storage reference")    # line 38
    data_url: str | None = Field(default=None, description="Inline base64 data URL")      # line 39
    thumbnail_url: str | None = Field(default=None, description="Thumbnail URL (images)") # line 40
    checksum: str | None = Field(default=None, description="SHA-256 hash")               # line 41

# core/__init__.py (existing) — current tail of imports (append after the last .schema import)
# from .schema import (
#     FormField, FormSection, FormSubsection, ... (verify actual content)
# )
# from .file_envelope import FileEnvelope, UPLOAD_FIELD_TYPES, is_single_cardinality
# ← add: from .voice_answer import VoiceAnswerEnvelope
```

### Does NOT Exist

- ~~`parrot_formdesigner.core.voice_answer`~~ — does not exist yet; this task creates it.
- ~~`VoiceAnswerEnvelope`~~ — does not exist anywhere in the codebase yet.
- ~~`VoiceAnswerEnvelope.content_type`~~ — the envelope does NOT have a `content_type` field; `FileEnvelope` does, but `VoiceAnswerEnvelope` does not (it is implicit: always `"application/json"`).
- ~~`AudioQuestion.accept_content_types`~~ — do NOT add any field to `AudioQuestion` in this task.

---

## Implementation Notes

### Pattern to Follow

```python
# core/voice_answer.py — mirror file_envelope.py exactly:
"""Canonical value shape for voice-note answers (FEAT-488).

A TEXT_AREA field with accept_content_types containing "application/json"
may receive a VoiceAnswerEnvelope dict as its submission value. The validator
passes it through unchanged; the consumer is responsible for parsing.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class VoiceAnswerEnvelope(BaseModel):
    """Dual payload for a voice-note answer on a text field.

    Attributes:
        answer: Transcription / text answer (required).
        blob_ref: Server-side voice note storage reference.
            Pre-populated by the audio renderer before submission.
            None when no blob has been stored (text-only fallback).
        data_url: Inline base64 audio data URL for small notes.
            None when the audio is stored server-side via blob_ref.
    """

    model_config = ConfigDict(extra="forbid")

    answer: str = Field(..., description="Transcribed text answer")
    blob_ref: str | None = Field(default=None, description="Server-side audio reference")
    data_url: str | None = Field(default=None, description="Inline base64 audio data URL")
```

### Key Constraints

- `model_config = ConfigDict(extra="forbid")` is mandatory (mirrors `FileEnvelope`).
- `answer` is the only required field; both `blob_ref` and `data_url` are optional.
- Do NOT add a `content_type` field — the MIME type of this envelope is always
  `"application/json"` by convention, not stored as a field.
- The `__init__.py` addition must be a single `from .voice_answer import VoiceAnswerEnvelope`
  line; do not reorganize existing imports.

### References in Codebase

- `packages/parrot-formdesigner/src/parrot_formdesigner/core/file_envelope.py` — blueprint
- `packages/parrot-formdesigner/src/parrot_formdesigner/core/__init__.py` — export target

---

## Acceptance Criteria

- [ ] `core/voice_answer.py` exists with `VoiceAnswerEnvelope` class.
- [ ] `VoiceAnswerEnvelope` has `model_config = ConfigDict(extra="forbid")`.
- [ ] `VoiceAnswerEnvelope.answer` is a required `str` field.
- [ ] `VoiceAnswerEnvelope.blob_ref` and `.data_url` are `str | None` with `default=None`.
- [ ] `from parrot_formdesigner.core import VoiceAnswerEnvelope` resolves without error.
- [ ] `from parrot_formdesigner.core.voice_answer import VoiceAnswerEnvelope` resolves without error.
- [ ] `VoiceAnswerEnvelope(answer="hello")` creates a valid instance.
- [ ] `VoiceAnswerEnvelope(answer="hi", extra="boom")` raises a Pydantic validation error.
- [ ] No linting errors: `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/core/voice_answer.py`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/test_core_models.py (or new file)

from parrot_formdesigner.core.voice_answer import VoiceAnswerEnvelope
import pytest


class TestVoiceAnswerEnvelope:
    def test_minimal_creation(self):
        env = VoiceAnswerEnvelope(answer="Hello world")
        assert env.answer == "Hello world"
        assert env.blob_ref is None
        assert env.data_url is None

    def test_full_creation(self):
        env = VoiceAnswerEnvelope(
            answer="Hello",
            blob_ref="s3://bucket/voice-123.ogg",
            data_url="data:audio/ogg;base64,abc123",
        )
        assert env.blob_ref == "s3://bucket/voice-123.ogg"

    def test_extra_field_forbidden(self):
        with pytest.raises(Exception):
            VoiceAnswerEnvelope(answer="hi", nonexistent="boom")

    def test_roundtrip(self):
        env = VoiceAnswerEnvelope(answer="Hi", blob_ref="s3://x/y")
        dumped = env.model_dump()
        restored = VoiceAnswerEnvelope(**dumped)
        assert restored == env

    def test_import_from_core(self):
        from parrot_formdesigner.core import VoiceAnswerEnvelope as VE
        assert VE is VoiceAnswerEnvelope
```

---

## Agent Instructions

1. **Read the spec** at `sdd/specs/formfield-content-type.spec.md`.
2. **Check dependencies** — verify TASK-2677 is in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — read `core/file_envelope.py` and `core/__init__.py` before writing.
4. **Update status** in `sdd/tasks/index/formfield-content-type.json` → `"in_progress"`.
5. **Implement** the new file and the `__init__.py` addition.
6. **Verify** all acceptance criteria.
7. **Move** to `sdd/tasks/completed/TASK-2678-voice-answer-envelope.md`.
8. **Update index** → `"completed"`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: —
**Date**: —
**Notes**: —
**Deviations from spec**: none


---

## Completion Note

**Completed**: 2026-09-01
**Status**: done

### Summary
Successfully implemented the VoiceAnswerEnvelope Pydantic model for FEAT-488.

### Files Created/Modified
- `packages/parrot-formdesigner/src/parrot_formdesigner/core/voice_answer.py` (NEW)
  - Created VoiceAnswerEnvelope class with model_config = ConfigDict(extra="forbid")
  - Defined fields: answer (required str), blob_ref (str|None), data_url (str|None)
  - Added module docstring explaining the purpose and usage
  
- `packages/parrot-formdesigner/src/parrot_formdesigner/core/__init__.py` (MODIFIED)
  - Added import: `from .voice_answer import VoiceAnswerEnvelope`
  - Added VoiceAnswerEnvelope to __all__ exports

### Verification
All acceptance criteria verified:
- ✅ core/voice_answer.py exists with VoiceAnswerEnvelope class
- ✅ VoiceAnswerEnvelope has model_config = ConfigDict(extra="forbid")
- ✅ VoiceAnswerEnvelope.answer is a required str field
- ✅ VoiceAnswerEnvelope.blob_ref and .data_url are str | None with default=None
- ✅ from parrot_formdesigner.core import VoiceAnswerEnvelope resolves without error
- ✅ from parrot_formdesigner.core.voice_answer import VoiceAnswerEnvelope resolves without error
- ✅ VoiceAnswerEnvelope(answer="hello") creates a valid instance
- ✅ VoiceAnswerEnvelope(answer="hi", extra="boom") raises Pydantic validation error
- ✅ No linting errors from ruff check

### Implementation Notes
- Followed the FileEnvelope pattern from FEAT-460 exactly
- No content_type field added (implicitly "application/json")
- All imports verified against existing codebase
