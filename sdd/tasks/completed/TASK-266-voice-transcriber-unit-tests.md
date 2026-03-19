# TASK-266: Voice Transcriber Unit Tests

**Feature**: Telegram Voice Note Support (FEAT-039)
**Spec**: `sdd/specs/telegram-voice-notes.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-262, TASK-263
**Assigned-to**: claude-session

---

## Context

> Unit tests for the shared voice transcription module and MS Teams backward compatibility.
> Implements spec Section 4 — Unit Tests (shared transcriber + backward compat).

---

## Scope

### Test Files

**`tests/voice/transcriber/test_shared_transcriber.py`** (CREATE):
- `test_transcriber_imports_from_shared_location` — verify public imports from `parrot.voice.transcriber`
- `test_config_model_unchanged` — `VoiceTranscriberConfig` fields match original
- `test_transcription_result_model` — `TranscriptionResult` fields (text, language, duration)
- `test_transcriber_backend_enum` — `TranscriberBackend` has expected values
- `test_abstract_backend_interface` — `AbstractTranscriberBackend` defines required methods

**`tests/integrations/msteams/test_msteams_voice_backward_compat.py`** (CREATE):
- `test_msteams_imports_still_work` — existing import paths still resolve
- `test_audio_attachment_stays_in_msteams` — `AudioAttachment` importable from `parrot.integrations.msteams.voice`
- `test_voice_transcriber_importable_from_msteams` — `VoiceTranscriber` importable from old path
- `test_config_importable_from_msteams` — `VoiceTranscriberConfig` importable from old path

### Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/voice/__init__.py` | CREATE | Test package init |
| `tests/voice/transcriber/__init__.py` | CREATE | Test package init |
| `tests/voice/transcriber/test_shared_transcriber.py` | CREATE | Shared module tests |
| `tests/integrations/msteams/test_msteams_voice_backward_compat.py` | CREATE | Backward compat tests |

---

## Implementation Notes

- Tests should verify imports and model shapes, NOT actual transcription (no GPU/API needed)
- Use `isinstance` checks and attribute inspection for model tests
- For backward compat tests, just verify that `import` statements resolve without errors
- No network calls or file system operations needed

---

## Acceptance Criteria

- [ ] All shared transcriber import tests pass
- [ ] All model field tests pass
- [ ] All MS Teams backward compatibility import tests pass
- [ ] No network calls in tests
- [ ] Tests run without GPU or API keys

---

## Agent Instructions

When you pick up this task:

1. **Verify** TASK-262 and TASK-263 are complete
2. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
3. **Create** test directory structure
4. **Implement** all test files
5. **Run** `pytest tests/voice/ tests/integrations/msteams/test_msteams_voice_backward_compat.py -v`
6. **Move this file** to `sdd/tasks/completed/`
7. **Update index** → `"done"`
