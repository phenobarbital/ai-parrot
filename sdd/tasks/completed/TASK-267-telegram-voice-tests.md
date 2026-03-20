# TASK-267: Telegram Voice Handler Tests

**Feature**: Telegram Voice Note Support (FEAT-039)
**Spec**: `sdd/specs/telegram-voice-notes.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-264, TASK-265
**Assigned-to**: claude-session

---

## Context

> Unit and integration tests for the Telegram voice handler functionality.
> Implements spec Section 4 — Telegram voice tests.

---

## Scope

### Test Files

**`tests/integrations/telegram/test_telegram_voice.py`** (CREATE):
- `test_handle_voice_downloads_and_transcribes` — mock bot.get_file, transcriber
- `test_handle_voice_sends_transcription_reply` — show_transcription=True
- `test_handle_voice_skips_transcription_reply` — show_transcription=False
- `test_handle_voice_disabled_ignores_message` — voice_config=None
- `test_handle_voice_empty_transcription` — empty result sends error message
- `test_handle_voice_duration_exceeded` — over max duration sends error
- `test_handle_voice_audio_file` — ContentType.AUDIO (not just VOICE)
- `test_handle_voice_cleanup_on_error` — temp file deleted even on failure

**`tests/integrations/telegram/test_telegram_voice_integration.py`** (CREATE):
- `test_voice_message_full_flow` — voice note → transcription → agent response
- `test_audio_message_full_flow` — audio file → transcription → agent response
- `test_voice_with_no_config_ignored` — no voice_config, voice message silently ignored

### Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/integrations/telegram/test_telegram_voice.py` | CREATE | Unit tests for handle_voice |
| `tests/integrations/telegram/test_telegram_voice_integration.py` | CREATE | Integration tests |

---

## Implementation Notes

- Mock `bot.get_file()`, `bot.download_file()`, and `VoiceTranscriber.transcribe_file()`
- Mock `message.voice` and `message.audio` objects with `file_id`, `duration` attributes
- For integration tests, mock the full flow from message to agent response
- Use `AsyncMock` for all async methods
- Verify temp file cleanup by mocking `os.unlink` or `tempfile` and asserting calls
- No actual audio files or transcription needed (all mocked)

---

## Acceptance Criteria

- [x] All 8 unit tests implemented and passing
- [x] All 3 integration tests implemented and passing
- [x] Tests cover both VOICE and AUDIO content types
- [x] Temp file cleanup verified (even on errors)
- [x] show_transcription behavior verified for both True and False
- [x] Duration limit enforcement tested
- [x] No network calls in tests

---

## Agent Instructions

When you pick up this task:

1. **Verify** TASK-264 and TASK-265 are complete
2. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
3. **Read** `parrot/integrations/telegram/wrapper.py` for handle_voice implementation
4. **Implement** all test files
5. **Run** `pytest tests/integrations/telegram/test_telegram_voice.py tests/integrations/telegram/test_telegram_voice_integration.py -v`
6. **Move this file** to `sdd/tasks/completed/`
7. **Update index** → `"done"`
