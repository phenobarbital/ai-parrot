---
type: Wiki Overview
title: 'TASK-1462: AudioFormRenderer — Standalone Audio Renderer'
id: doc:sdd-tasks-completed-task-1462-audio-form-renderer-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The core renderer that converts any `FormSchema` into an `AudioFormManifest`
  —
relates_to:
- concept: mod:parrot.voice.tts.models
  rel: mentions
- concept: mod:parrot.voice.tts.synthesizer
  rel: mentions
---

# TASK-1462: AudioFormRenderer — Standalone Audio Renderer

**Feature**: FEAT-224 — FormDesigner Audio Renderer
**Spec**: `sdd/specs/formdesigner-audio-renderer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1459, TASK-1460
**Assigned-to**: unassigned

---

## Context

The core renderer that converts any `FormSchema` into an `AudioFormManifest` —
a sequential list of questions ready for the audio Q&A session. This renderer
is registered under `"audio"` format key and is discoverable at
`GET /api/v1/forms/{form_id}/render/audio`. Implements Spec §3 Module 4.

---

## Scope

- Create `AudioFormRenderer` class extending `AbstractFormRenderer`.
- Implement `render()` → returns `RenderedForm` with `AudioFormManifest` as content.
- Implement `split_into_questions()` — flattens `FormSchema` sections/subsections
  into a sequential list of `AudioQuestion` objects:
  - Iterate sections → subsections → fields via `iter_all_fields()`.
  - Skip `FieldType.HIDDEN` fields (not audible).
  - Expand `FieldType.GROUP` children into individual questions.
  - Resolve `LocalizedString` labels to the requested locale.
  - Include `options` for `SELECT`/`MULTI_SELECT` fields.
- Optionally pre-synthesize TTS audio for each question if a `VoiceSynthesizer`
  is provided (constructor parameter).
- Register `"audio"` in the renderer registry via `register_renderer()`.
- Write unit tests.

**NOT in scope**: WebSocket handler, route registration, field-level AUDIO rendering.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/audio.py` | CREATE | AudioFormRenderer class |
| `tests/formdesigner/test_audio_form_renderer.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.renderers.base import AbstractFormRenderer  # verified: renderers/base.py:57
from parrot_formdesigner.core.schema import (
    FormSchema,      # verified: core/schema.py:242
    FormField,       # verified: core/schema.py:24
    FormSection,     # verified: core/schema.py:102
    RenderedForm,    # verified: core/schema.py:357
)
from parrot_formdesigner.core.types import FieldType, LocalizedString  # verified: core/types.py:16, 13
from parrot_formdesigner.core.style import StyleSchema  # verified: renderers/base.py:11
from parrot_formdesigner.audio.models import (  # created by TASK-1460
    AudioFormManifest,
    AudioQuestion,
)
# Optional TTS dependency:
from parrot.voice.tts.synthesizer import VoiceSynthesizer  # verified: voice/tts/synthesizer.py:21
from parrot.voice.tts.models import SynthesisResult  # verified: voice/tts/synthesizer.py:18
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/renderers/base.py:57
class AbstractFormRenderer(ABC):
    @abstractmethod
    async def render(
        self, form: FormSchema, style: StyleSchema | None = None, *,
        locale: str = "en", prefilled: dict[str, Any] | None = None,
        errors: dict[str, str] | None = None,
    ) -> RenderedForm: ...  # line 68

# packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py:288
class FormSchema(BaseModel):
    def iter_all_fields(self) -> Iterator[FormField]: ...  # line 288

# packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py:128
class FormSection(BaseModel):
    def iter_fields(self) -> Iterator[FormField]: ...  # line 128

# parrot.voice.tts.synthesizer:21
class VoiceSynthesizer:
    async def synthesize(self, text: str, *, language: Optional[str] = None) -> SynthesisResult: ...
    # SynthesisResult has .audio (bytes) and .mime_format (str)
```

### Does NOT Exist
- ~~`parrot_formdesigner.renderers.audio`~~ — does not exist yet, this task creates it
- ~~`AudioFormRenderer`~~ — does not exist anywhere
- ~~`AbstractFormRenderer.split_into_questions()`~~ — not part of the base class; this is a new method specific to AudioFormRenderer
- ~~`VoiceSynthesizer.synthesize_to_base64()`~~ — no such method; must manually base64-encode `.audio` bytes
- ~~`FormField.get_label(locale)`~~ — no such method; must implement locale resolution manually (str passthrough or dict[locale] lookup)

---

## Implementation Notes

### Pattern to Follow
```python
# Follow the renderer registration pattern from api/render.py:37
# _seed_default_renderers() imports and registers:
from ..renderers.html5 import HTML5Renderer
_RENDERERS.setdefault("html", HTML5Renderer())
# Similarly for audio:
from ..renderers.audio import AudioFormRenderer
_RENDERERS.setdefault("audio", AudioFormRenderer())
```

### Key Constraints
- `render()` must return `RenderedForm(content=manifest, content_type="application/json")`.
- `LocalizedString` resolution: if `str`, use as-is. If `dict`, look up `locale` key, fallback to `"en"`, fallback to first value.
- `VoiceSynthesizer` is optional in the constructor — when `None`, `AudioQuestion.audio_prompt` stays `None` (client-side TTS or lazy server synthesis).
- Skip `FieldType.HIDDEN` fields entirely.
- For `FieldType.GROUP`, flatten children into individual questions.
- For `FieldType.ARRAY`, skip (cannot be meaningfully voiced as a single question).
- The `ws_endpoint` in the manifest should be a relative path template: `/api/v1/forms/{form_id}/audio/ws`.
- Async throughout — TTS synthesis uses `await`.

### References in Codebase
- `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/html5.py` — existing renderer implementation
- `packages/parrot-formdesigner/src/parrot_formdesigner/api/render.py:37` — renderer registration

---

## Acceptance Criteria

- [ ] `AudioFormRenderer` extends `AbstractFormRenderer`
- [ ] `render()` returns `RenderedForm` with `AudioFormManifest` as content
- [ ] `split_into_questions()` correctly flattens a multi-section form
- [ ] Hidden fields are excluded from the questions list
- [ ] GROUP children are expanded into individual questions
- [ ] LocalizedString labels resolve correctly for the given locale
- [ ] SELECT/MULTI_SELECT fields include their options in the question
- [ ] When VoiceSynthesizer is provided, audio_prompt is populated per question
- [ ] Tests pass: `pytest tests/formdesigner/test_audio_form_renderer.py -v`
- [ ] No linting errors

---

## Test Specification

```python
# tests/formdesigner/test_audio_form_renderer.py
import pytest
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.renderers.audio import AudioFormRenderer


@pytest.fixture
def simple_form():
    return FormSchema(
        form_id="test-001",
        title="Test Form",
        sections=[FormSection(
            section_id="s1",
            title="Section 1",
            fields=[
                FormField(field_id="name", field_type=FieldType.TEXT,
                          label="What is your name?", required=True),
                FormField(field_id="age", field_type=FieldType.NUMBER,
                          label="How old are you?"),
                FormField(field_id="secret", field_type=FieldType.HIDDEN,
                          label="hidden", default="x"),
            ],
        )],
    )


@pytest.fixture
def renderer():
    return AudioFormRenderer()


class TestSplitIntoQuestions:
    def test_flat_form(self, renderer, simple_form):
        questions = renderer.split_into_questions(simple_form)
        assert len(questions) == 2  # hidden excluded
        assert questions[0].field_id == "name"
        assert questions[1].field_id == "age"

    def test_questions_are_indexed(self, renderer, simple_form):
        questions = renderer.split_into_questions(simple_form)
        assert questions[0].index == 0
        assert questions[1].index == 1

    def test_required_flag(self, renderer, simple_form):
        questions = renderer.split_into_questions(simple_form)
        assert questions[0].required is True
        assert questions[1].required is False


class TestRender:
    @pytest.mark.asyncio
    async def test_returns_rendered_form(self, renderer, simple_form):
        result = await renderer.render(simple_form)
        assert result.content_type == "application/json"
        assert result.content["form_id"] == "test-001"
        assert result.content["total_questions"] == 2

    @pytest.mark.asyncio
    async def test_manifest_has_ws_endpoint(self, renderer, simple_form):
        result = await renderer.render(simple_form)
        assert "/audio/ws" in result.content["ws_endpoint"]
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/formdesigner-audio-renderer.spec.md` §2 Overview and §3 Module 4
2. **Check dependencies** — TASK-1459 (FieldType.AUDIO) and TASK-1460 (models) must be complete
3. **Verify the Codebase Contract** — confirm AbstractFormRenderer, FormSchema.iter_all_fields()
4. **Update status** in `sdd/tasks/index/formdesigner-audio-renderer.json` → `"in-progress"`
5. **Implement** the renderer
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1462-audio-form-renderer.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-06-04
**Notes**: Created `renderers/audio.py` with `AudioFormRenderer` extending `AbstractFormRenderer`. Implemented `split_into_questions()` (skips HIDDEN/ARRAY, expands GROUP children, includes SELECT options) and `render()` returning `RenderedForm(content=manifest_dict, content_type="application/json")`. Optional `VoiceSynthesizer` pre-synthesizes questions at render time. 13 unit tests pass.

**Deviations from spec**: none
