---
type: Wiki Overview
title: 'TASK-1541: Per-VoiceMode WebSocket Dispatch + Fallback Handlers'
id: doc:sdd-tasks-completed-task-1541-ws-handler-voice-mode-dispatch-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Spec §2 (pillar 3 + WebSocket Protocol) + §3 Module 3. The core behavioral
  task:'
relates_to:
- concept: mod:parrot.voice.handler
  rel: mentions
- concept: mod:parrot.voice.transcriber.faster_whisper_backend
  rel: mentions
- concept: mod:parrot.voice.transcriber.models
  rel: mentions
- concept: mod:parrot.voice.tts.synthesizer
  rel: mentions
---

# TASK-1541: Per-VoiceMode WebSocket Dispatch + Fallback Handlers

**Feature**: FEAT-236 — Audio Renderer Form
**Spec**: `sdd/specs/audio-renderer-form.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1539, TASK-1540
**Assigned-to**: unassigned

---

## Context

Spec §2 (pillar 3 + WebSocket Protocol) + §3 Module 3. The core behavioral task:
drive each question by its `VoiceMode`, add the hybrid-fallback answer paths
(`answer_selection`, `answer_payload`), the low-confidence STT read-back gate
(`confirm_request`/`confirm_answer`), the visual-fallback single-field render,
and sensitive-field muting. Build the synthesizer via the SuperTonic-first helper
from TASK-1540.

---

## Scope

- Carry an `AudioSessionConfig` on the session (default `tts_backend="supertonic"`,
  `stt_confirm_threshold=0.6`, `enumerate_options=True`), populated from
  `start_session` payload (`locale`, `tts_voice`, `tts_backend`, thresholds).
- Build the session synthesizer via the TASK-1540 helper
  (`build_audio_synthesizer` / `_synthesize_with_fallback`) — SuperTonic → Google
  → text-only — instead of using `self.synthesizer.synthesize` directly. The
  injected `self.synthesizer` remains supported for tests/overrides.
- Extend `_send_question` to include `voice_mode`, `render_mode`, `sensitive`,
  and (for `VISUAL_FALLBACK`) `fallback_html`. For `PROMPT_SELECT`, narrate the
  label and, when `enumerate_options`, append the option labels to the TTS text.
  For `sensitive` questions, do NOT synthesize/echo the value (narrate the label
  only).
- Render `fallback_html` for `VISUAL_FALLBACK` questions using a single
  `HTML5Renderer` field renderer:
  `await HTML5Renderer()._registry[field_type].render(field, locale=...)`. If the
  field type has no HTML5 renderer, fall back to a minimal `<input>` and log.
- Add handlers and register them in the `_dispatch_text` handlers dict:
  - `_handle_answer_selection` — accept `{field_id, value}` or `{field_id,
    values:[...]}`; validate against the question's `options`; store
    `AudioAnswer(source="selection")`; advance.
  - `_handle_answer_payload` — accept `{field_id, value}` for `VISUAL_FALLBACK`;
    validate; store (`source="text"`); advance.
  - `_handle_confirm_answer` — `{field_id, confirmed: bool}`; on `true` store the
    pending transcript and advance; on `false` re-send the SAME question (do not
    advance), discard the pending transcript.
- Add the low-confidence gate in `_handle_answer_audio`: when
  `result.confidence is not None and result.confidence < config.stt_confirm_threshold`,
  store the transcript as PENDING on the session and emit `confirm_request`
  `{field_id, transcript, confidence}` instead of accepting+advancing. At/above
  the threshold (or confidence `None`), keep current auto-advance behavior.

**NOT in scope**: model field definitions (TASK-1539), classification/synthesizer
helper internals (TASK-1540), route wiring defaults (TASK-1542), cross-cutting
integration tests (TASK-1543) — though handler-level unit tests belong here.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/audio_ws.py` | MODIFY | VoiceMode dispatch, selection/payload/confirm handlers, low-confidence gate, fallback render, sensitive muting. |
| `packages/parrot-formdesigner/tests/formdesigner/test_audio_ws_handler.py` | MODIFY | Handler-level tests for the new flows. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from aiohttp import WSMsgType, web  # api/audio_ws.py:31
from parrot_formdesigner.audio.models import (
    AudioAnswer, AudioFormManifest, AudioQuestion, AudioSessionState,
    AudioSessionConfig, VoiceMode,   # AudioSessionConfig+VoiceMode via TASK-1539
)
from parrot_formdesigner.renderers.audio import (
    AudioFormRenderer, build_audio_synthesizer,  # build_audio_synthesizer via TASK-1540
)
from parrot_formdesigner.renderers.html5 import HTML5Renderer  # for VISUAL_FALLBACK field render
# TYPE_CHECKING-guarded (api/audio_ws.py:41-48):
#   parrot.voice.handler.{AuthenticatedUser, TokenValidator}
#   parrot.voice.tts.synthesizer.VoiceSynthesizer
#   parrot.voice.transcriber.faster_whisper_backend.FasterWhisperBackend
```

### Existing Signatures to Use
```python
# api/audio_ws.py
class AudioFormWSHandler:  # line 56
    def __init__(self, registry, synthesizer, transcriber, validator, *,
                 token_validator=None, submission_storage=None,
                 max_msg_size=10*1024*1024) -> None: ...  # line 90
    async def handle_websocket(self, request) -> web.WebSocketResponse: ...  # line 115
    async def _dispatch_text(self, ws, msg_type, data, session, request, audio_cache): ...  # line 258
    #   handlers dict at line 277 — ADD: "answer_selection", "answer_payload", "confirm_answer"
    async def _handle_start_session(self, *, ws, data, session, request, audio_cache): ...  # line 306
    async def _handle_answer_text(self, *, ws, data, session, request, audio_cache): ...  # line 375
    async def _handle_answer_audio(self, ws, audio_bytes, session, audio_cache): ...  # line 394
    #   transcription at line 428-442: result.text, result.confidence
    async def _accept_answer(self, ws, session, field_id, value, *, source="text",
                             confidence=None, raw_transcript=None) -> bool: ...  # line 573
    async def _advance_session(self, ws, session, request, audio_cache): ...  # line 636
    async def _advance_session_no_request(self, ws, session, audio_cache): ...  # line 656
    async def _send_question(self, ws, question, audio_cache): ...  # line 718 — msg dict at line 744
    async def _send_error(self, ws, code, message): ...  # line 799
MAX_QUESTIONS = 10  # line 53

# AudioSessionState (mutate to hold config + pending transcript)
class AudioSessionState(BaseModel):  # audio/models.py:113
    session_id, form_id, user_id, current_index=0, answers: dict, manifest, completed=False

# HTML5Renderer single-field render
class HTML5Renderer(AbstractFormRenderer):  # renderers/html5.py:78
    self._registry: dict[FieldType, FieldRenderer]  # line 118 (built by _build_registry, line 121)
# FieldRenderer protocol (renderers/base.py:15):
#   async def render(self, field: FormField, *, locale="en", prefilled=None, error=None) -> Any

# parrot.voice.transcriber.models.TranscriptionResult — .text, .confidence: Optional[float]
```

### Does NOT Exist
- ~~`_handle_answer_selection` / `_handle_answer_payload` / `_handle_confirm_answer`~~ — add.
- ~~`AudioSessionState.config` / `.pending_transcript`~~ — not present; either extend the
  model (additive, defaulted) or track on the handler keyed by session_id. Prefer
  extending `AudioSessionState` with `config: AudioSessionConfig | None = None` and
  a `pending: AudioAnswer | None = None` (additive).
- ~~`FasterWhisperBackend.transcribe_bytes()`~~ — use temp-file `transcribe(Path)` (existing pattern, line 419-461).
- ~~`HTML5Renderer.render_field(...)`~~ — no such method; use `_registry[ft].render(field, ...)`.

---

## Implementation Notes

### Pattern to Follow
- Follow the existing dispatcher style (`_dispatch_text`, line 258) — all
  text handlers take `*, ws, data, session, request, audio_cache`.
- Reuse `_accept_answer` (line 573) for storing answers; pass `source="selection"`.
- For `confirm_answer{confirmed:false}`, re-send via `_send_question` with the
  current question (mirror `_handle_repeat_question`, line 523).
- Keep the SuperTonic→Google→text-only fallback in the TASK-1540 helper; the
  handler just calls it.

### Key Constraints
- Async throughout. Never advance `current_index` while a transcript is pending
  confirmation.
- Multi-select: store the joined/serialized values consistently with how
  `FormValidator` expects them (check `services/validators.py`).
- Sensitive: never put a `password` value into TTS text or `transcription`/
  read-back messages.

---

## Acceptance Criteria

- [ ] `question` messages carry `voice_mode`, `render_mode`, `sensitive`, and
      `fallback_html` (for `VISUAL_FALLBACK`).
- [ ] `answer_selection` (single + `values[]`) validates against options and
      stores `AudioAnswer(source="selection")`, then advances.
- [ ] `answer_payload` completes a `VISUAL_FALLBACK` question; a required REST
      field can be answered this way and the form reaches `form_complete`.
- [ ] Speech answer with confidence `< stt_confirm_threshold` emits
      `confirm_request` and does NOT advance; `confirm_answer{confirmed:true}`
      stores + advances; `confirm_answer{confirmed:false}` re-sends the same
      question and stores nothing.
- [ ] Speech answer with confidence ≥ threshold (or `None`) auto-advances.
- [ ] `sensitive` questions carry no TTS audio / no value read-back.
- [ ] Synthesizer construction uses the SuperTonic-first helper with graceful
      fallback (no crash when SuperTonic weights/extra are missing).
- [ ] Existing FEAT-224 message flows still pass unchanged.
- [ ] Tests pass: `pytest packages/parrot-formdesigner/tests/formdesigner/test_audio_ws_handler.py -v`
- [ ] No lint errors: `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/api/audio_ws.py`

---

## Test Specification

```python
# Handler-level tests with a fake WebSocket capturing send_json calls.
# - test_question_message_includes_voice_mode
# - test_answer_selection_single_and_multi
# - test_visual_fallback_question_has_fallback_html
# - test_low_confidence_emits_confirm_request_no_advance
# - test_confirm_true_stores_and_advances
# - test_confirm_false_resends_same_question
# - test_high_confidence_auto_advances
# - test_sensitive_password_no_audio
```

---

## Agent Instructions

1. **Read** spec §2 pillar 3 + WebSocket Protocol and §3 Module 3; confirm
   TASK-1539 and TASK-1540 are in `sdd/tasks/completed/`.
2. **Verify** the Codebase Contract (especially the HTML5 `_registry` render path
   and the TASK-1540 helper name).
3. **Update index** → `in-progress`.
4. **Implement** the dispatch + fallback + confirmation logic.
5. **Verify** acceptance criteria.
6. **Move** to `sdd/tasks/completed/`; **update index** → `done`; fill Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Opus 4.8)
**Date**: 2026-06-12
**Notes**: Added `answer_selection`/`answer_payload`/`confirm_answer` to the
`_dispatch_text` handlers dict and implemented `_handle_answer_selection`
(single `value` + multi `values[]`, validates against `options`, stores
`source="selection"`, multi joined as comma string), `_handle_answer_payload`
(VISUAL_FALLBACK → `source="text"`), and `_handle_confirm_answer`
(`confirmed:true` stores the pending transcript + advances; `false` discards +
re-sends the same question). `_handle_answer_audio` now gates on
`session.config.stt_confirm_threshold`: below threshold it stores a PENDING
`AudioAnswer` and emits `confirm_request` without advancing; at/above (or
`confidence None`) it keeps auto-advance. `_send_question` carries
`voice_mode`/`render_mode`/`sensitive` always, `fallback_html` for
VISUAL_FALLBACK (via `HTML5Renderer._registry[ft].render`, minimal `<input>`
fallback when no renderer — REST has none), enumerates PROMPT_SELECT option
labels into the narration when `enumerate_options`, and mutes audio for
`sensitive` questions. Synthesis routed through a new `_synthesize` helper:
injected `self.synthesizer` wins (tests/overrides); otherwise the SuperTonic-
first `synthesize_with_fallback` is used only when the new
`auto_synthesize=True` flag is set (default False → no network for callers that
pass no synthesizer). Config parsed from `start_session` via
`_build_session_config`. 15 new handler tests; full formdesigner suite 154
passed; ruff clean.
**Deviations from spec**: (1) Two files were modified beyond the task's
"Files to Create/Modify" table, both sanctioned/required: `audio/models.py`
(added `AudioSessionState.config` + `.pending`) is explicitly directed by this
task's Codebase Contract ("Prefer extending AudioSessionState with config:...
pending:..."); `renderers/audio.py` had `synthesize_with_fallback`'s `except`
broadened from `(ImportError, ValueError, RuntimeError)` to `Exception` because
the live Google backend (creds present in this env) raises a domain-specific
`SpeechGenerationError` — the narrow catch would have let it propagate and
break the "never raises" contract the helper documents. (2) Sensitive questions
carry NO TTS audio at all (not "narrate the label only"): the task AC and test
name (`no_audio`) require it, and it is the safer posture for passwords. (3)
Added an `auto_synthesize` opt-in constructor flag so the no-injected-
synthesizer fallback does not fire (and hit a real backend) until TASK-1542
wires it on — keeps existing FEAT-224 tests network-free.
