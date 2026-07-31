---
type: Wiki Overview
title: 'TASK-1539: VoiceMode Enum + Audio Model Extensions'
id: doc:sdd-tasks-completed-task-1539-voicemode-model-extensions-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Spec §2 (Data Models) + §3 Module 1. This is the foundation task: it introduces'
---

# TASK-1539: VoiceMode Enum + Audio Model Extensions

**Feature**: FEAT-236 — Audio Renderer Form
**Spec**: `sdd/specs/audio-renderer-form.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §2 (Data Models) + §3 Module 1. This is the foundation task: it introduces
the `VoiceMode` taxonomy enum and the additive fields on the existing FEAT-224
audio models that every later task (renderer classification, WS dispatch,
routes) builds on. All changes are additive and backward-compatible.

---

## Scope

- Add a `VoiceMode(str, Enum)` to `audio/models.py` with members `VOICE`,
  `PROMPT_SELECT`, `VISUAL_FALLBACK`.
- Extend `AudioQuestion` with: `voice_mode: VoiceMode = VoiceMode.VOICE`,
  `render_mode: Literal["voice","select","visual"] = "voice"`,
  `sensitive: bool = False`, `fallback_html: Optional[str] = None`.
- Extend `AudioSessionConfig` with: `tts_backend: Literal["supertonic","google"]
  = "supertonic"`, `enumerate_options: bool = True`,
  `stt_confirm_threshold: float = Field(default=0.6, ge=0.0, le=1.0)`, and change
  the default of `tts_mime_format` from `"audio/ogg"` to `"audio/wav"` (SuperTonic
  emits WAV).
- Extend `AudioAnswer.source` Literal to include `"selection"` →
  `Literal["text","speech","selection"]`.
- Write/extend unit tests in `test_audio_models.py`.

**NOT in scope**: classification logic (`classify_voice_mode` — TASK-1540),
synthesizer construction, WS handler changes, routes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/audio/models.py` | MODIFY | Add `VoiceMode`; extend `AudioQuestion`, `AudioSessionConfig`, `AudioAnswer`. |
| `packages/parrot-formdesigner/tests/formdesigner/test_audio_models.py` | MODIFY | Add tests for the new enum + fields. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from enum import Enum                                  # stdlib
from typing import Literal, Optional                   # already imported (audio/models.py:11)
from pydantic import BaseModel, ConfigDict, Field      # already imported (audio/models.py:13)
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/audio/models.py
class AudioQuestion(BaseModel):       # line 37  — model_config = ConfigDict(extra="forbid") (line 54)
    index: int; field_id: str; field_type: str; label: str
    description: Optional[str] = None; required: bool = False
    audio_prompt: Optional[bytes] = None
    constraints: Optional[dict] = None; options: Optional[list[dict]] = None

class AudioSessionConfig(BaseModel):  # line 16  — extra="forbid" (line 28)
    form_id: str; locale: str = "en"
    tts_voice: Optional[str] = None
    tts_mime_format: str = "audio/ogg"            # line 33 — CHANGE default to "audio/wav"
    auto_advance: bool = True

class AudioAnswer(BaseModel):         # line 92  — extra="forbid" (line 104)
    field_id: str; value: str
    source: Literal["text", "speech"] = "text"    # line 108 — EXTEND with "selection"
    confidence: Optional[float] = None
    raw_transcript: Optional[str] = None
```

### Does NOT Exist
- ~~`VoiceMode`~~ — enum not present yet; add it.
- ~~`AudioQuestion.voice_mode` / `.render_mode` / `.sensitive` / `.fallback_html`~~ — add.
- ~~`AudioSessionConfig.tts_backend` / `.enumerate_options` / `.stt_confirm_threshold`~~ — add.
- ~~`AudioAnswer.source == "selection"`~~ — only `"text"`/`"speech"` today.

---

## Implementation Notes

### Pattern to Follow
- Mirror the existing Pydantic style in `audio/models.py`: `model_config =
  ConfigDict(extra="forbid")`, Google-style docstrings, typed fields with
  `Field(...)` where bounds apply.
- Place `VoiceMode` near the top of the module (after imports) so both
  `AudioQuestion` and downstream modules can import it.

### Key Constraints
- All additions must be backward-compatible (defaulted) — existing FEAT-224
  serialization of `AudioQuestion`/`AudioSessionConfig`/`AudioAnswer` must still
  validate unchanged.
- `extra="forbid"` is intentional — keep it; new fields are server-side defaults.

---

## Acceptance Criteria

- [ ] `VoiceMode` enum exists with `VOICE`, `PROMPT_SELECT`, `VISUAL_FALLBACK`.
- [ ] `AudioQuestion` has `voice_mode` (default `VOICE`), `render_mode` (default
      `"voice"`), `sensitive` (default `False`), `fallback_html` (default `None`).
- [ ] `AudioSessionConfig.tts_backend` defaults `"supertonic"`,
      `stt_confirm_threshold` defaults `0.6` (bounded 0–1), `enumerate_options`
      defaults `True`, `tts_mime_format` defaults `"audio/wav"`.
- [ ] `AudioAnswer(source="selection")` validates.
- [ ] Tests pass: `pytest packages/parrot-formdesigner/tests/formdesigner/test_audio_models.py -v`
- [ ] No lint errors: `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/audio/models.py`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/formdesigner/test_audio_models.py
from parrot_formdesigner.audio.models import (
    VoiceMode, AudioQuestion, AudioSessionConfig, AudioAnswer,
)


def test_voice_mode_enum_values():
    assert {m.value for m in VoiceMode} >= {"voice", "prompt_select", "visual_fallback"}


def test_audio_question_voice_fields_default():
    q = AudioQuestion(index=0, field_id="f", field_type="text", label="L")
    assert q.voice_mode == VoiceMode.VOICE
    assert q.render_mode == "voice"
    assert q.sensitive is False and q.fallback_html is None


def test_session_config_supertonic_default():
    cfg = AudioSessionConfig(form_id="x")
    assert cfg.tts_backend == "supertonic"
    assert cfg.stt_confirm_threshold == 0.6
    assert cfg.enumerate_options is True
    assert cfg.tts_mime_format == "audio/wav"


def test_audio_answer_source_selection():
    a = AudioAnswer(field_id="f", value="v", source="selection")
    assert a.source == "selection"
```

---

## Agent Instructions

When you pick up this task:
1. **Read the spec** §2 (Data Models) and §3 Module 1.
2. **Verify the Codebase Contract** against `audio/models.py` before editing.
3. **Update index** → `in-progress`.
4. **Implement** the additive model changes.
5. **Verify** acceptance criteria.
6. **Move** this file to `sdd/tasks/completed/`.
7. **Update index** → `done`. Fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Opus 4.8)
**Date**: 2026-06-12
**Notes**: Added `VoiceMode(str, Enum)` with `VOICE`/`PROMPT_SELECT`/
`VISUAL_FALLBACK` near the top of `audio/models.py`. Extended `AudioQuestion`
with `voice_mode` (default `VOICE`), `render_mode` (`Literal["voice","select",
"visual"]`, default `"voice"`), `sensitive` (default `False`), `fallback_html`
(default `None`). Extended `AudioSessionConfig` with `tts_backend`
(`Literal["supertonic","google"]`, default `"supertonic"`), `enumerate_options`
(default `True`), `stt_confirm_threshold` (`Field(default=0.6, ge=0.0, le=1.0)`),
and changed `tts_mime_format` default `"audio/ogg"` → `"audio/wav"`. Extended
`AudioAnswer.source` to `Literal["text","speech","selection"]`. All additive /
backward-compatible; `extra="forbid"` preserved. Updated the pre-existing
FEAT-224 `test_defaults` assertion (mime now `audio/wav`) since the default
change is in-scope for this task. 27 tests pass; ruff clean.
**Deviations from spec**: none
