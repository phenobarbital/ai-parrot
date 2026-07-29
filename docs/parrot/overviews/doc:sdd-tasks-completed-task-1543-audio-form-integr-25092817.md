---
type: Wiki Overview
title: 'TASK-1543: Audio Form Integration Tests (Hybrid Voice Flows)'
id: doc:sdd-tasks-completed-task-1543-audio-form-integration-tests-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Spec §3 Module 5 + §4 (Integration Tests). End-to-end coverage of the evolved
relates_to:
- concept: mod:parrot.voice.transcriber.models
  rel: mentions
---

# TASK-1543: Audio Form Integration Tests (Hybrid Voice Flows)

**Feature**: FEAT-236 — Audio Renderer Form
**Spec**: `sdd/specs/audio-renderer-form.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1539, TASK-1540, TASK-1541, TASK-1542
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5 + §4 (Integration Tests). End-to-end coverage of the evolved
audio form: a mixed-mode form exercising all three `VoiceMode`s, the
low-confidence STT confirmation turn, the visual fallback completing a required
REST field, and the SuperTonic→Google→text-only degradation path.

---

## Scope

- Add a `mixed_mode_form` fixture (a TEXT → `VOICE`, a SELECT → `PROMPT_SELECT`,
  a required REST → `VISUAL_FALLBACK`) to the formdesigner test fixtures
  (`conftest.py` or the integration module).
- Add/extend `mock_synthesizer` (returns WAV bytes; parametrizable to raise on
  first synthesize to exercise SuperTonic→Google fallback) and `mock_transcriber`
  (returns a `TranscriptionResult` with a parametrizable `.confidence`).
- Implement the integration tests in `test_audio_integration.py`:
  - `test_ws_prompt_select_flow`, `test_ws_multi_select_values`
  - `test_ws_visual_fallback_flow` (required REST completes the form)
  - `test_ws_low_confidence_confirm`, `test_ws_low_confidence_reject_reprompts`,
    `test_ws_high_confidence_auto_advance`
  - `test_ws_sensitive_no_audio`
  - `test_ws_supertonic_to_google_degradation`

**NOT in scope**: production implementation (TASK-1539..1542). This task only adds
tests and fixtures; if a test reveals a bug, fix it in the owning module's task
scope and note it.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/tests/formdesigner/test_audio_integration.py` | MODIFY | New integration tests for hybrid flows. |
| `packages/parrot-formdesigner/tests/formdesigner/conftest.py` | MODIFY | `mixed_mode_form`, `mock_synthesizer`, `mock_transcriber` fixtures. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.audio.models import (
    VoiceMode, AudioSessionConfig, AudioAnswer, AudioQuestion,
)
from parrot_formdesigner.api.audio_ws import AudioFormWSHandler
from parrot_formdesigner.renderers.audio import AudioFormRenderer
```

### Existing Signatures to Use
```python
# Existing test scaffolding already present in the package:
#   tests/formdesigner/conftest.py                 — shared fixtures
#   tests/formdesigner/test_audio_integration.py   — FEAT-224 WS session lifecycle tests
#   tests/formdesigner/test_audio_ws_handler.py    — fake-WebSocket harness pattern to reuse
# AudioFormWSHandler.__init__(registry, synthesizer, transcriber, validator, *,
#   token_validator=None, submission_storage=None, max_msg_size=...)  # api/audio_ws.py:90
# AudioFormWSHandler.handle_websocket(request) -> web.WebSocketResponse  # line 115

# FormSchema construction (FEAT-224 fixture pattern, spec §4):
#   FormSchema(form_id=..., title=..., sections=[FormSection(section_id=..., fields=[FormField(...)])])
# parrot.voice.transcriber.models.TranscriptionResult — .text, .confidence: Optional[float]
```

### Does NOT Exist
- ~~A live SuperTonic ONNX model in CI~~ — never load real weights; mock the
  synthesizer. Degradation test asserts text-only/Google path, not real audio.
- ~~`FasterWhisperBackend.transcribe_bytes()`~~ — mock `transcribe()` returning a
  `TranscriptionResult`-like object with `.text` and `.confidence`.
- ~~A real WebSocket server~~ — reuse the existing fake-WS harness in
  `test_audio_ws_handler.py` (capture `send_json` calls), do not open sockets.

---

## Implementation Notes

### Pattern to Follow
- Reuse the existing fake-WebSocket test harness already used by
  `test_audio_ws_handler.py` (a stub exposing `send_json`, `receive`, `prepare`,
  async-iteration over queued messages). Mirror the FEAT-224 integration tests in
  `test_audio_integration.py`.
- Drive each flow by feeding messages and asserting the captured server replies
  (`question` carries `voice_mode`/`render_mode`; `confirm_request` on low
  confidence; `form_complete` after the REST fallback answer).

### Key Constraints
- Tests must run without the `voice-supertonic` extra and without
  `SUPERTONIC_MODEL_PATH` set (mock everything).
- Deterministic: parametrize confidence and synth-failure rather than relying on
  timing.

---

## Acceptance Criteria

- [ ] `mixed_mode_form` fixture covers `VOICE`, `PROMPT_SELECT`, and a required
      `VISUAL_FALLBACK` REST field.
- [ ] `PROMPT_SELECT` single + multi selection flows pass.
- [ ] `VISUAL_FALLBACK` flow completes a required REST field → `form_complete`.
- [ ] Low-confidence confirm/reject and high-confidence auto-advance flows pass.
- [ ] `sensitive` (password) question is delivered without audio.
- [ ] SuperTonic→Google→text-only degradation test passes with everything mocked.
- [ ] Full suite green: `pytest packages/parrot-formdesigner/tests/formdesigner/ -v`
- [ ] No lint errors: `ruff check packages/parrot-formdesigner/tests/formdesigner/`

---

## Test Specification

```python
# test_audio_integration.py (sketch — reuse fake-WS harness)
async def test_ws_visual_fallback_flow(handler, mixed_mode_form, fake_ws):
    # start_session -> answer VOICE -> answer_selection for SELECT ->
    # answer_payload for required REST -> expect form_complete
    ...

async def test_ws_low_confidence_confirm(handler, mock_transcriber, fake_ws):
    mock_transcriber.confidence = 0.2   # < default 0.6 threshold
    # answer_audio -> expect "confirm_request"; confirm_answer{confirmed:true} -> stored
    ...
```

---

## Agent Instructions

1. **Read** spec §4; confirm TASK-1539..1542 are in `sdd/tasks/completed/`.
2. **Verify** the Codebase Contract; locate the existing fake-WS harness.
3. **Update index** → `in-progress`.
4. **Implement** fixtures + integration tests.
5. **Verify** the full formdesigner suite is green.
6. **Move** to `sdd/tasks/completed/`; **update index** → `done`; fill Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Opus 4.8)
**Date**: 2026-06-12
**Notes**: Added the `mixed_mode_form` fixture (TEXT/VOICE + SELECT/
PROMPT_SELECT + required REST/VISUAL_FALLBACK) to `conftest.py`, and documented
the existing `mock_synthesizer` (now WAV bytes; set `.side_effect` to simulate a
failing backend) and `mock_transcriber` (set `.return_value` for a specific
`.confidence`). Implemented 8 integration tests in `test_audio_integration.py`
under `TestHybridVoiceFlows`: `test_ws_prompt_select_flow`,
`test_ws_multi_select_values`, `test_ws_visual_fallback_flow` (required REST →
`form_complete`), `test_ws_low_confidence_confirm`,
`test_ws_low_confidence_reject_reprompts`, `test_ws_high_confidence_auto_advance`,
`test_ws_sensitive_no_audio`, `test_ws_supertonic_to_google_degradation`. Full
formdesigner suite: 165 passed; all FEAT-236-touched files ruff-clean.
**Deviations from spec**: (1) Tests use the package's established integration
pattern — a real in-process aiohttp test client (`aiohttp_client` + `ws_connect`,
loopback only, all TTS/STT mocked) — rather than the "fake-WS harness" the task
text references; `test_audio_ws_handler.py` actually uses direct method calls
with an `AsyncMock` ws (not a queue-based harness), and `test_audio_integration.py`
already uses `ws_connect`, so this is the consistent, proven approach (no
external network). (2) The degradation test injects a synthesizer that raises and
asserts text-only delivery (per the task note "asserts text-only/Google path,
not real audio"); the SuperTonic→Google backend chain itself is unit-tested in
TASK-1540. (3) `ruff --fix` removed several pre-existing unused imports (`json`,
`AudioFormManifest`, `_RENDERERS`×4) from `test_audio_integration.py` (a file in
scope) to satisfy the no-lint AC. Two pre-existing unused `import pytest`
warnings remain in `test_audio_control_metadata.py` and `test_audio_fieldtype.py`
— these files are unrelated to FEAT-236 and were left untouched per file-fidelity
discipline; all FEAT-236-touched files are lint-clean.
