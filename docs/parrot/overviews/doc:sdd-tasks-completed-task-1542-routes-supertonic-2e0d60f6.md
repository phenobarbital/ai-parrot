---
type: Wiki Overview
title: 'TASK-1542: Routes / SuperTonic-first Wiring Defaults'
id: doc:sdd-tasks-completed-task-1542-routes-supertonic-wiring-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Spec §3 Module 4. `setup_form_api()` already accepts `synthesizer`,
relates_to:
- concept: mod:parrot.voice.handler
  rel: mentions
- concept: mod:parrot.voice.transcriber.faster_whisper_backend
  rel: mentions
- concept: mod:parrot.voice.tts.synthesizer
  rel: mentions
---

# TASK-1542: Routes / SuperTonic-first Wiring Defaults

**Feature**: FEAT-236 — Audio Renderer Form
**Spec**: `sdd/specs/audio-renderer-form.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1540, TASK-1541
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4. `setup_form_api()` already accepts `synthesizer`,
`transcriber`, and `token_validator` and mounts the audio WS endpoint when any is
provided. This task lets audio work out-of-the-box where SuperTonic weights are
configured (no explicit synthesizer passed) and documents the SuperTonic env
requirement — without changing the public signature.

---

## Scope

- In `setup_form_api()`, when `synthesizer is None` but a `transcriber` or
  `token_validator` is provided (i.e. audio is intended), allow the
  `AudioFormWSHandler` to build its synthesizer lazily via the TASK-1540
  SuperTonic-first helper. Keep accepting an explicitly-injected `synthesizer`
  (overrides the lazy build). Do NOT add new required parameters.
- Update the `setup_form_api()` docstring to note the SuperTonic env contract
  (`SUPERTONIC_MODEL_PATH` weights + `voice-supertonic` extra) and the graceful
  Google/text-only fallback.
- Update `test_audio_routes.py` to cover the lazy-synthesizer wiring path.

**NOT in scope**: the handler's internal fallback logic (TASK-1541), the helper
itself (TASK-1540), model fields (TASK-1539).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py` | MODIFY | Lazy SuperTonic-first synthesizer when none injected; docstring note. |
| `packages/parrot-formdesigner/tests/formdesigner/test_audio_routes.py` | MODIFY | Wiring tests. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# routes.py TYPE_CHECKING block (lines 46-48):
from parrot.voice.handler import TokenValidator
from parrot.voice.tts.synthesizer import VoiceSynthesizer
from parrot.voice.transcriber.faster_whisper_backend import FasterWhisperBackend
# In-function lazy imports (existing pattern, lines 248-249):
from .audio_ws import AudioFormWSHandler
from ..services.validators import FormValidator
```

### Existing Signatures to Use
```python
# api/routes.py — setup_form_api signature (lines 95-102), additive only:
def setup_form_api(
    app, registry, *, client=None, submission_storage=None, forwarder=None,
    base_path="/api/v1", blob_storage=None, resolver=None, partial_store=None,
    synthesizer: "VoiceSynthesizer | None" = None,        # line 99
    transcriber: "FasterWhisperBackend | None" = None,    # line 100
    token_validator: "TokenValidator | None" = None,      # line 101
) -> None: ...

# Existing audio mount block (lines 244-263):
if synthesizer is not None or transcriber is not None or token_validator is not None:
    from .audio_ws import AudioFormWSHandler
    from ..services.validators import FormValidator
    audio_handler = AudioFormWSHandler(
        registry=registry, synthesizer=synthesizer, transcriber=transcriber,
        validator=FormValidator(), token_validator=token_validator,
        submission_storage=submission_storage,
    )
    app.router.add_get(f"{bp}/forms/{{form_id}}/audio/ws", audio_handler.handle_websocket)

# Helper to reuse (TASK-1540):
from parrot_formdesigner.renderers.audio import build_audio_synthesizer  # renderers/audio.py
```

### Does NOT Exist
- ~~New required params on `setup_form_api`~~ — keep the signature backward-compatible.
- ~~A separate audio-only setup function~~ — reuse the existing mount block.
- ~~`AudioFormWSHandler` requiring a non-None synthesizer~~ — it accepts `None` (api/audio_ws.py:90).

---

## Implementation Notes

### Pattern to Follow
- Minimal change: either pass a lazily-built synthesizer into the existing
  `AudioFormWSHandler(...)` construction, or let the handler build it on
  `start_session` (TASK-1541 already wires `build_audio_synthesizer`). Choose the
  path that keeps construction cheap (no model load at route-setup time —
  `VoiceSynthesizer` is lazy; the ONNX session loads on first synthesize).
- Keep the `if synthesizer is not None or transcriber is not None or
  token_validator is not None:` gate so non-audio apps are unaffected.

### Key Constraints
- No model load at import/route-setup time.
- Backward-compatible: existing callers passing an explicit `synthesizer` keep
  their behavior.

---

## Acceptance Criteria

- [ ] `setup_form_api()` signature unchanged (no new required args).
- [ ] When audio is intended but no `synthesizer` is injected, the audio handler
      uses the SuperTonic-first helper (verified via test, no ONNX load required).
- [ ] An explicitly-injected `synthesizer` still takes precedence.
- [ ] Docstring documents `SUPERTONIC_MODEL_PATH` + graceful fallback.
- [ ] Tests pass: `pytest packages/parrot-formdesigner/tests/formdesigner/test_audio_routes.py -v`
- [ ] No lint errors: `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py`

---

## Test Specification

```python
# - test_setup_mounts_audio_ws_when_transcriber_only
# - test_explicit_synthesizer_takes_precedence
# - test_route_setup_does_not_load_onnx_model   (no SUPERTONIC_MODEL_PATH needed)
```

---

## Agent Instructions

1. **Read** spec §3 Module 4; confirm TASK-1540 and TASK-1541 are in
   `sdd/tasks/completed/`.
2. **Verify** the Codebase Contract against `api/routes.py`.
3. **Update index** → `in-progress`.
4. **Implement** the minimal lazy-wiring change + docstring.
5. **Verify** acceptance criteria.
6. **Move** to `sdd/tasks/completed/`; **update index** → `done`; fill Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Opus 4.8)
**Date**: 2026-06-12
**Notes**: In `setup_form_api`'s existing audio mount block, the
`AudioFormWSHandler` is now constructed with `auto_synthesize=(synthesizer is
None)`. So when audio is intended (transcriber/token_validator provided) but no
explicit synthesizer is injected, the handler lazily synthesizes via the
SuperTonic-first `synthesize_with_fallback` (TASK-1540/1541) — and an injected
synthesizer still takes precedence (auto stays off). No new params; the mount
gate is unchanged. No ONNX model is loaded at setup time (no synthesizer object
is constructed there; `VoiceSynthesizer`/SuperTonic load lazily on first
`synthesize()`). Updated the docstring to document `synthesizer`/`transcriber`/
`token_validator` and the `SUPERTONIC_MODEL_PATH` + `voice-supertonic` extra
contract with graceful Google/text-only fallback. Added 3 wiring tests
(transcriber-only → auto on + no synth; explicit synth precedence; setup loads
no ONNX). 11 route tests pass; ruff clean.
**Deviations from spec**: Removed a pre-existing unused `import pytest` from
`test_audio_routes.py` (file already in scope) to satisfy the "no lint errors"
acceptance criterion.
