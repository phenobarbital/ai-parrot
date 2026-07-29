---
type: Wiki Overview
title: 'TASK-1461: AudioFieldRenderer — Per-Field Audio Input for HTML5'
id: doc:sdd-tasks-completed-task-1461-audio-field-renderer-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Adds audio input capability to the HTML5 renderer so any form can include
  an
---

# TASK-1461: AudioFieldRenderer — Per-Field Audio Input for HTML5

**Feature**: FEAT-224 — FormDesigner Audio Renderer
**Spec**: `sdd/specs/formdesigner-audio-renderer.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1459
**Assigned-to**: unassigned

---

## Context

Adds audio input capability to the HTML5 renderer so any form can include an
`AUDIO` field type. This renders as a record button + hidden input that stores
the transcribed text. Implements Spec §3 Module 2.

---

## Scope

- Create `AudioFieldRenderer` class implementing the `FieldRenderer` protocol.
- The HTML5 output: a `<button>` to start/stop recording, a visual waveform
  indicator, a hidden `<input>` for the transcribed text, and inline JavaScript
  using the MediaRecorder API.
- Register `AudioFieldRenderer` for `FieldType.AUDIO` in the `HTML5Renderer._build_registry()` method.
- Write unit tests for the rendered HTML output.

**NOT in scope**: Adaptive Card rendering, WebSocket handler, server-side TTS/STT.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/fields/audio.py` | CREATE | AudioFieldRenderer class |
| `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/html5.py` | MODIFY | Register AUDIO in `_build_registry()` |
| `tests/formdesigner/test_audio_field_renderer.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.core.types import FieldType  # verified: core/types.py:16
from parrot_formdesigner.core.schema import FormField  # verified: core/schema.py:24
from parrot_formdesigner.renderers.base import FieldRenderer  # verified: renderers/base.py:15 (Protocol)
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/renderers/base.py:15
@runtime_checkable
class FieldRenderer(Protocol):
    async def render(
        self, field: FormField, *, locale: str = "en",
        prefilled: Any = None, error: str | None = None,
    ) -> Any: ...

# packages/parrot-formdesigner/src/parrot_formdesigner/renderers/html5.py:77
class HTML5Renderer(AbstractFormRenderer):
    def __init__(self) -> None:
        # ...
        self._registry: dict[FieldType, FieldRenderer] = {}  # line 117
        self._build_registry()  # line 118

    def _build_registry(self) -> None:  # line 120
        # ... defines inner renderer classes
        # Registry ends at line 285 with FieldType.RANKING
        # FieldType.REST is NOT in _registry (no handler yet)
```

### Does NOT Exist
- ~~`parrot_formdesigner.renderers.fields`~~ — subpackage does not exist; must create `__init__.py`
- ~~`parrot_formdesigner.renderers.fields.audio`~~ — does not exist yet
- ~~`HTML5Renderer.register_field_renderer()`~~ — no public registration method; must modify `_build_registry()` directly
- ~~`HTML5Renderer._render_audio()`~~ — no such private method exists

---

## Implementation Notes

### Pattern to Follow
```python
# Follow the inner-class pattern from html5.py:_build_registry()
# Example from _SignatureRenderer (line 198):
class _AudioRenderer:
    def __init__(self_, renderer: "HTML5Renderer") -> None:
        self_._r = renderer

    async def render(
        self_, field: FormField, *, locale: str = "en",
        prefilled: Any = None, error: str | None = None,
    ) -> Any:
        return self_._r._render_audio(field, prefilled)
```

Alternatively, create the `AudioFieldRenderer` as a standalone class in
`renderers/fields/audio.py` and import it in `_build_registry()`. Either
approach is acceptable — the standalone file is cleaner for a larger renderer.

### Key Constraints
- The rendered HTML MUST work as a standalone snippet (no external JS dependency).
- Use the MediaRecorder API with `audio/webm` or `audio/ogg` MIME type.
- The hidden `<input>` stores the transcribed text (client-side or via WS).
- Include a `data-field-type="audio"` attribute for frontend JavaScript hooks.
- Follow the same HTML structure as other field renderers (wrapper div, label, input, error).

### References in Codebase
- `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/html5.py:198` — `_SignatureRenderer` pattern (most similar field type)
- `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/html5.py:253` — `_registry` dict

---

## Acceptance Criteria

- [ ] `AudioFieldRenderer` implements the `FieldRenderer` protocol
- [ ] `isinstance(AudioFieldRenderer(...), FieldRenderer)` is `True`
- [ ] HTML5 renderer produces `<button>` and `<input type="hidden">` for AUDIO fields
- [ ] Rendered HTML includes inline JavaScript for MediaRecorder API
- [ ] `FieldType.AUDIO` is registered in `HTML5Renderer._registry`
- [ ] Tests pass: `pytest tests/formdesigner/test_audio_field_renderer.py -v`
- [ ] No linting errors

---

## Test Specification

```python
# tests/formdesigner/test_audio_field_renderer.py
import pytest
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.core.schema import FormField
from parrot_formdesigner.renderers.base import FieldRenderer
from parrot_formdesigner.renderers.html5 import HTML5Renderer


@pytest.fixture
def audio_field():
    return FormField(
        field_id="voice_note",
        field_type=FieldType.AUDIO,
        label="Leave a voice note",
    )


@pytest.fixture
def renderer():
    return HTML5Renderer()


class TestAudioFieldInRegistry:
    def test_audio_in_registry(self, renderer):
        assert FieldType.AUDIO in renderer._registry

    def test_audio_renderer_is_field_renderer(self, renderer):
        assert isinstance(renderer._registry[FieldType.AUDIO], FieldRenderer)


class TestAudioFieldRendering:
    @pytest.mark.asyncio
    async def test_render_produces_html(self, renderer, audio_field):
        html = await renderer._registry[FieldType.AUDIO].render(audio_field)
        assert isinstance(html, str)
        assert "<button" in html
        assert 'type="hidden"' in html

    @pytest.mark.asyncio
    async def test_render_includes_field_id(self, renderer, audio_field):
        html = await renderer._registry[FieldType.AUDIO].render(audio_field)
        assert "voice_note" in html

    @pytest.mark.asyncio
    async def test_render_includes_mediarecorder(self, renderer, audio_field):
        html = await renderer._registry[FieldType.AUDIO].render(audio_field)
        assert "MediaRecorder" in html or "mediarecorder" in html.lower()
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/formdesigner-audio-renderer.spec.md` §3 Module 2
2. **Check dependencies** — TASK-1459 (FieldType.AUDIO) must be complete
3. **Verify the Codebase Contract** — confirm `_build_registry()` and `_registry` dict
4. **Update status** in `sdd/tasks/index/formdesigner-audio-renderer.json` → `"in-progress"`
5. **Implement** the field renderer and register it
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1461-audio-field-renderer.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-06-04
**Notes**: Created `renderers/fields/__init__.py` and `renderers/fields/audio.py` with `AudioFieldRenderer` class. Modified `renderers/html5.py` to import and register `AudioFieldRenderer` for `FieldType.AUDIO` in `_build_registry()`. 12 unit tests pass.

**Deviations from spec**: none
