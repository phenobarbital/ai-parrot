# TASK-2681: Audio Renderer — Read accept_content_types for Submission Shape

**Feature**: FEAT-488 — FormField Content-Type
**Spec**: `sdd/specs/formfield-content-type.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2677, TASK-2678
**Assigned-to**: unassigned

---

## Context

The `AudioFormRenderer` converts a `FormSchema` into an `AudioFormManifest`
(a sequential list of `AudioQuestion` objects for voice-driven Q&A). This
task extends the renderer to surface `accept_content_types` from `FormField`
so the audio session knows that a given field may receive a `VoiceAnswerEnvelope`
dict instead of a plain string.

Implements spec §3 Module 5.

---

## Scope

- Read `AudioQuestion` definition from `audio/models.py` (not `renderers/audio.py`).
- If `AudioQuestion` does not already have an `accept_content_types` field,
  add `accept_content_types: list[str] | None = None` to it.
- In `AudioFormRenderer`, when building an `AudioQuestion` for a field,
  copy `field.accept_content_types` into `AudioQuestion.accept_content_types`.
- Import `VoiceAnswerEnvelope` from `parrot_formdesigner.core.voice_answer`
  in `renderers/audio.py` for documentation / type annotation purposes if
  needed (do NOT eagerly deserialize).

**NOT in scope**: changes to `AudioFormManifest`, `AudioSessionConfig`,
`VoiceMode`, or any voice recording pipeline.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/audio/models.py` | MODIFY | Add `accept_content_types: list[str] \| None = None` to `AudioQuestion` (only if absent) |
| `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/audio.py` | MODIFY | Copy `field.accept_content_types` → `AudioQuestion.accept_content_types` when building questions |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# renderers/audio.py — existing imports (verified at file head)
from ..audio.models import (
    AudioFormManifest,
    AudioQuestion,
    AudioSessionConfig,
    VoiceMode,
)
from ..core.schema import FormField, FormSchema, RenderedForm
from ..core.style import StyleSchema
from ..core.types import FieldType, LocalizedString
from .base import AbstractFormRenderer

# Add if needed for type annotations:
from ..core.voice_answer import VoiceAnswerEnvelope
```

### Existing Signatures to Use

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/renderers/audio.py
# (read the actual file to find the AudioQuestion construction site)

_SKIP_FIELD_TYPES: frozenset[FieldType] = frozenset({FieldType.HIDDEN})  # verified
_SELECT_TYPES: frozenset[FieldType] = frozenset({...})                    # verified
_PROMPT_SELECT_TYPES: frozenset[FieldType] = frozenset({...})             # verified

class AudioFormRenderer(AbstractFormRenderer):
    # find the method that builds AudioQuestion objects and read its body
    # before making any changes
    ...
```

**CRITICAL**: Read `audio/models.py` before making any change to `AudioQuestion`.
The class definition, its fields, and `model_config` must be verified first.
Do NOT assume `AudioQuestion` has or lacks `accept_content_types` — check the file.

### Does NOT Exist

- ~~`AudioQuestion.accept_content_types`~~ — may not exist yet; verify before adding.
- ~~`AudioFormRenderer._voice_answer_envelope`~~ — no such method; this task only propagates the list.
- ~~`renderers/audio.py` imports `VoiceAnswerEnvelope` today~~ — it does not; this task may add it.

---

## Implementation Notes

### Key Constraints

1. **Read `audio/models.py` first** — find `AudioQuestion` definition, check
   whether it already has `accept_content_types`. Only add the field if absent.
2. If `AudioQuestion` has `model_config = ConfigDict(extra="forbid")`, the
   new field must be an explicit Pydantic field declaration.
3. Do NOT raise an error or warning when `field.accept_content_types` is `None`
   — just do not set the field (leave it as `None`/default).
4. Do NOT deserialize submitted values into `VoiceAnswerEnvelope` in this
   task — the renderer only builds the manifest, not processes submissions.

### Pattern to Follow

Find where `AudioQuestion(...)` is constructed in `renderers/audio.py` and
add `accept_content_types=field.accept_content_types` to the constructor call.

### References in Codebase

- `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/audio.py` — target
- `packages/parrot-formdesigner/src/parrot_formdesigner/audio/models.py` — `AudioQuestion` definition (READ FIRST)

---

## Acceptance Criteria

- [ ] `AudioQuestion` has an `accept_content_types: list[str] | None = None` field (added if absent).
- [ ] `AudioFormRenderer` copies `field.accept_content_types` into `AudioQuestion` when building questions.
- [ ] Fields with `accept_content_types=None` produce `AudioQuestion` with `accept_content_types=None` (no error).
- [ ] Fields with `accept_content_types=["text/plain","application/json"]` produce `AudioQuestion` with the same list.
- [ ] All existing audio renderer tests pass: `pytest packages/parrot-formdesigner/tests/unit/ -k audio -v`
- [ ] No linting errors on modified files.

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/ (add to appropriate test file)

from parrot_formdesigner.core.schema import FormField, FormSchema
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.renderers.audio import AudioFormRenderer


def test_audio_renderer_propagates_accept_content_types():
    """AudioQuestion receives accept_content_types from FormField."""
    field = FormField(
        field_id="answer",
        field_type=FieldType.TEXT_AREA,
        label="Answer",
        accept_content_types=["text/plain", "application/json"],
    )
    # Wrap in a minimal FormSchema and render
    # (Check existing audio renderer tests for the exact schema construction pattern)
    ...
    # Assert the corresponding AudioQuestion has the list
    question = manifest.questions[0]
    assert question.accept_content_types == ["text/plain", "application/json"]


def test_audio_renderer_accept_content_types_none_by_default():
    """Fields without accept_content_types produce AudioQuestion.accept_content_types=None."""
    field = FormField(
        field_id="notes", field_type=FieldType.TEXT_AREA, label="Notes"
    )
    ...
    question = manifest.questions[0]
    assert question.accept_content_types is None
```

---

## Agent Instructions

1. **Read the spec** at `sdd/specs/formfield-content-type.spec.md`.
2. **Check dependencies** — verify TASK-2677 and TASK-2678 are in `sdd/tasks/completed/`.
3. **Read `audio/models.py` FIRST** — find `AudioQuestion` and verify its current fields before writing any code.
4. **Read `renderers/audio.py`** — find the `AudioQuestion(...)` constructor call site.
5. **Update status** → `"in_progress"`.
6. **Implement** the field addition (if needed) and the propagation.
7. **Verify** all acceptance criteria.
8. **Move** to `sdd/tasks/completed/TASK-2681-audio-renderer-accept-content-types.md`.
9. **Update index** → `"completed"`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: —
**Date**: —
**Notes**: —
**Deviations from spec**: none
