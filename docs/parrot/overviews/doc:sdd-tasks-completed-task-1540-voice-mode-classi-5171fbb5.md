---
type: Wiki Overview
title: 'TASK-1540: Voice-Mode Classification + SuperTonic-first Synthesizer'
id: doc:sdd-tasks-completed-task-1540-voice-mode-classification-and-synthesizer-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Spec §2 (pillars 1 & 2) + §3 Module 2. Evolve `AudioFormRenderer` to (a)
  classify
relates_to:
- concept: mod:parrot.voice
  rel: mentions
- concept: mod:parrot.voice.tts.models
  rel: mentions
- concept: mod:parrot.voice.tts.synthesizer
  rel: mentions
---

# TASK-1540: Voice-Mode Classification + SuperTonic-first Synthesizer

**Feature**: FEAT-236 — Audio Renderer Form
**Spec**: `sdd/specs/audio-renderer-form.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1539
**Assigned-to**: unassigned

---

## Context

Spec §2 (pillars 1 & 2) + §3 Module 2. Evolve `AudioFormRenderer` to (a) classify
every field into a `VoiceMode` instead of silently dropping REST/ARRAY/select
fields, and (b) build a SuperTonic-first `VoiceSynthesizer` that gracefully falls
back to Google, then to text-only.

---

## Scope

- Add `classify_voice_mode(field: FormField) -> VoiceMode` to `renderers/audio.py`
  implementing the default `FieldType → VoiceMode` table (spec §2 pillar 2), with
  a per-field override read from `FormField.meta["voice_mode"]` (case-insensitive
  match against `VoiceMode` values; invalid override → log warning, use default).
- Replace the `_SKIP_FIELD_TYPES` drop behavior: only `FieldType.HIDDEN` is
  excluded from questions; `GROUP` still flattens to children. All other fields
  become questions tagged with `voice_mode`, derived `render_mode`
  (`VOICE→"voice"`, `PROMPT_SELECT→"select"`, `VISUAL_FALLBACK→"visual"`), and
  `sensitive=True` for `FieldType.PASSWORD`.
- Carry `voice_mode`/`render_mode`/`sensitive` through `_field_to_questions()` and
  `split_into_questions()` onto each `AudioQuestion`.
- Add module-level `build_audio_synthesizer(config: AudioSessionConfig | None =
  None) -> "VoiceSynthesizer | None"`: construct `VoiceSynthesizer(TTSConfig(
  backend="supertonic", voice=config.tts_voice, mime_format=config.tts_mime_format))`;
  return it. The actual SuperTonic→Google→None fallback happens at synthesis time
  (a backend only raises on first `synthesize()`), so `build_audio_synthesizer`
  must expose a small async helper or the renderer must catch synthesis failures
  and rebuild with `backend="google"`, and on a second failure deliver text-only.
  Keep the fallback logic in ONE place reusable by the WS handler (TASK-1541).
- Update unit tests in `test_audio_form_renderer.py` (+ a focused test module if
  cleaner) for classification and the fallback helper.

**NOT in scope**: WS message handlers / dispatch (TASK-1541), routes (TASK-1542),
cross-cutting WS integration tests (TASK-1543).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/audio.py` | MODIFY | Add `classify_voice_mode`, `build_audio_synthesizer`; replace skip logic; tag questions. |
| `packages/parrot-formdesigner/tests/formdesigner/test_audio_form_renderer.py` | MODIFY | Classification + fallback tests. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.core.types import FieldType, LocalizedString  # core/types.py:13,16
from parrot_formdesigner.core.schema import FormField, FormSchema, RenderedForm  # renderers/audio.py:18
from parrot_formdesigner.audio.models import (
    AudioFormManifest, AudioQuestion, AudioSessionConfig, VoiceMode,  # VoiceMode added by TASK-1539
)
# Voice TTS — ai-parrot-integrations (optional dep; guard with TYPE_CHECKING / lazy import)
from parrot.voice.tts.synthesizer import VoiceSynthesizer  # voice/tts/synthesizer.py:21
from parrot.voice.tts.models import TTSConfig             # voice/tts/models.py:16
```

### Existing Signatures to Use
```python
# renderers/audio.py
class AudioFormRenderer(AbstractFormRenderer):  # line 65
    def __init__(self, synthesizer: Optional["VoiceSynthesizer"] = None) -> None: ...  # line 87
    def split_into_questions(self, form, *, locale="en") -> list[AudioQuestion]: ...   # line 100
    def _field_to_questions(self, field, *, locale="en") -> list[AudioQuestion]: ...   # line 141
_SKIP_FIELD_TYPES = frozenset({FieldType.HIDDEN, FieldType.ARRAY, FieldType.REST})  # line 31 — REPLACE (HIDDEN only)
_SELECT_TYPES = frozenset({FieldType.SELECT, FieldType.MULTI_SELECT, FieldType.DYNAMIC_SELECT})  # line 36
def _resolve(value, locale="en") -> str: ...  # line 41 — reuse for labels/options

# core/types.py — FieldType members available for the mapping table
#   text, text_area, number, integer, boolean, date, datetime, time, select,
#   multi_select, file, image, color, url, email, phone, password, hidden, group,
#   array, signature, dynamic_select, transfer_list, remote_response, availability,
#   location, tags, nps, likert, ranking, rest, audio   (lines 19-53)

# core/schema.py
class FormField(BaseModel):           # line 24
    field_type: FieldType             # line 56
    required: bool = False            # line 60
    options: list[FieldOption] | None # line 64
    children: list[FormField] | None  # line 68
    meta: dict[str, Any] | None = None  # line 70  ← override source

# parrot.voice.tts.models
class TTSConfig(BaseModel):  # voice/tts/models.py:16
    backend: Literal["google","elevenlabs","openai","supertonic"] = "google"  # line 41
    voice: Optional[str] = None; language: Optional[str] = None; mime_format: str = "audio/ogg"

# parrot.voice.tts.synthesizer
class VoiceSynthesizer:  # voice/tts/synthesizer.py:21
    def __init__(self, config: Optional[TTSConfig] = None) -> None: ...  # line 46
    async def synthesize(self, text, *, language=None) -> SynthesisResult: ...  # line 102 (.audio bytes)
    async def close(self) -> None: ...  # line 147
```

### Does NOT Exist
- ~~`classify_voice_mode` / `build_audio_synthesizer`~~ — add them in this task.
- ~~`VoiceSynthesizer.synthesize_to_base64()`~~ — use `synthesize()` → `result.audio`.
- ~~A `backend` kwarg on `VoiceSynthesizer.__init__`~~ — backend is set via `TTSConfig(backend=...)`.
- ~~`SupertonicTTSBackend` returning OGG~~ — it always returns `audio/wav`.

---

## Implementation Notes

### Pattern to Follow
- Keep the lazy/`TYPE_CHECKING` import guards for `parrot.voice.*` already used in
  `renderers/audio.py:23-24` so forms without the voice extra still import.
- Fallback shape (the one reusable place):
```python
async def _synthesize_with_fallback(text, *, language=None) -> bytes | None:
    for backend in ("supertonic", "google"):
        synth = VoiceSynthesizer(TTSConfig(backend=backend, ...))
        try:
            return (await synth.synthesize(text, language=language)).audio
        except (ImportError, ValueError, RuntimeError) as exc:
            logger.warning("TTS backend %s unavailable: %s", backend, exc)
        finally:
            await synth.close()
    return None  # text-only
```
  (FEAT-231: graceful degradation is the handler's responsibility — never raise.)

### Key Constraints
- Async throughout; never block the loop.
- `FormField.meta` may be `None` — guard before `meta.get(...)`.
- Do not drop required fields. A REST/select field MUST appear as a question.

---

## Acceptance Criteria

- [ ] `classify_voice_mode` maps text/number/email/date/phone/url/tags → `VOICE`;
      select/multi_select/dynamic_select/boolean/ranking/likert/nps/color →
      `PROMPT_SELECT`; rest/remote_response/file/image/location/signature/
      transfer_list/availability/array → `VISUAL_FALLBACK`.
- [ ] `FormField.meta["voice_mode"]` overrides the default; invalid value logs a
      warning and falls back to the default.
- [ ] Only `HIDDEN` is excluded from `split_into_questions()`; a required REST
      field appears as a `VISUAL_FALLBACK` question.
- [ ] `password` questions are tagged `sensitive=True`.
- [ ] `build_audio_synthesizer` / fallback helper prefers SuperTonic, falls back
      to Google, then returns `None`/text-only without raising.
- [ ] Tests pass: `pytest packages/parrot-formdesigner/tests/formdesigner/test_audio_form_renderer.py -v`
- [ ] No lint errors: `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/renderers/audio.py`

---

## Test Specification

```python
import pytest
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.core.schema import FormField
from parrot_formdesigner.audio.models import VoiceMode
from parrot_formdesigner.renderers.audio import classify_voice_mode


@pytest.mark.parametrize("ft,mode", [
    (FieldType.TEXT, VoiceMode.VOICE),
    (FieldType.SELECT, VoiceMode.PROMPT_SELECT),
    (FieldType.REST, VoiceMode.VISUAL_FALLBACK),
])
def test_classify_default(ft, mode):
    assert classify_voice_mode(FormField(field_id="f", field_type=ft, label="L")) == mode


def test_classify_meta_override():
    f = FormField(field_id="f", field_type=FieldType.TEXT, label="L",
                  meta={"voice_mode": "visual_fallback"})
    assert classify_voice_mode(f) == VoiceMode.VISUAL_FALLBACK
```

---

## Agent Instructions

1. **Read** spec §2 pillars 1–2 and §3 Module 2; confirm TASK-1539 is in
   `sdd/tasks/completed/`.
2. **Verify** the Codebase Contract.
3. **Update index** → `in-progress`.
4. **Implement**; keep the fallback in one reusable place.
5. **Verify** acceptance criteria.
6. **Move** to `sdd/tasks/completed/`; **update index** → `done`; fill Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Opus 4.8)
**Date**: 2026-06-12
**Notes**: Added `classify_voice_mode(field)` with `_PROMPT_SELECT_TYPES` /
`_VISUAL_FALLBACK_TYPES` frozensets and a VOICE default for everything else
(incl. AUDIO), plus a case-insensitive `meta["voice_mode"]` override that warns
and falls back on an invalid value. Replaced `_SKIP_FIELD_TYPES` with
`{HIDDEN}` only — REST/ARRAY/select fields are now kept as questions.
`_field_to_questions` tags each question with `voice_mode`, derived
`render_mode` (via `_RENDER_MODE_BY_VOICE`), and `sensitive=True` for PASSWORD;
`split_into_questions` and `_synthesize_questions` now use `model_copy` so the
new voice fields are preserved through re-indexing/synthesis. Added the single
reusable `synthesize_with_fallback(text, *, config, language)` implementing
SuperTonic→Google→None at synthesis time (catches ImportError/ValueError/
RuntimeError, never raises) and `build_audio_synthesizer(config)` returning a
SuperTonic-configured `VoiceSynthesizer` (or None if the voice stack is
unimportable). Both use lazy in-function imports so forms without the voice
extra still import. 54 renderer tests pass; full formdesigner suite 139 passed;
ruff clean.
**Deviations from spec**: Minor, in-scope: (1) options are now populated for
ANY field that defines `field.options` (previously only SELECT/MULTI/DYNAMIC)
so PROMPT_SELECT types like ranking/likert/nps can enumerate options downstream
— strictly additive. (2) `FieldType.AUDIO`, not listed in the spec §2 table,
defaults to VOICE (the documented catch-all). Two reusable helpers were
provided (`build_audio_synthesizer` + `synthesize_with_fallback`) as the task
explicitly allowed ("expose a small async helper ... keep the fallback logic in
ONE place").
