# TASK-265: Telegram Voice Handler

**Feature**: Telegram Voice Note Support (FEAT-039)
**Spec**: `sdd/specs/telegram-voice-notes.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-6h)
**Depends-on**: TASK-262, TASK-264
**Assigned-to**: claude-session

---

## Context

> Add voice message handling to `TelegramAgentWrapper` — register handlers for `ContentType.VOICE` and `ContentType.AUDIO`, download audio from Telegram CDN, transcribe via `VoiceTranscriber`, and process the transcribed text through the existing agent flow.
> Implements spec Section 3 — Module 4.

---

## Scope

### Files to Modify

**`parrot/integrations/telegram/wrapper.py`** (MODIFY):
- Import `VoiceTranscriber`, `VoiceTranscriberConfig` from `parrot.voice.transcriber`
- Register handlers for `ContentType.VOICE` and `ContentType.AUDIO` in private chats
- Implement `handle_voice(message: Message)`:
  1. Extract `voice` or `audio` object from message
  2. Check `voice_config` is enabled, else ignore
  3. Send `ChatAction.TYPING` indicator
  4. Download file via `bot.get_file(file_id)` → `bot.download_file(file_path, dest)`
  5. Transcribe via `VoiceTranscriber.transcribe_file()`
  6. Validate result (non-empty text, duration check)
  7. Optionally reply with transcription text (italic)
  8. Process through existing message flow
  9. Clean up temp file in `finally` block
- Initialize `VoiceTranscriber` in wrapper `__init__` (lazy — only if `voice_config` is set)
- Add cleanup in wrapper shutdown

### Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/integrations/telegram/wrapper.py` | MODIFY | Add handle_voice handler, transcriber init/cleanup |

---

## Implementation Notes

- Use `tempfile.NamedTemporaryFile` for downloaded audio (auto-cleanup on close)
- Telegram voice notes are `.ogg` (Opus) — Whisper supports this natively, no conversion needed
- Audio files (`ContentType.AUDIO`) can be `.mp3`, `.m4a`, etc. — all supported by Whisper
- Both `message.voice` and `message.audio` provide `file_id` and `duration`
- Authorization check: use same `_is_authorized()` pattern as text messages
- Duration limit: check `message.voice.duration` against `voice_config.max_audio_duration_seconds` BEFORE downloading
- Show transcription: if `show_transcription=True`, reply with `_"transcribed text"_` (italic) before processing
- The transcribed text should be processed through the exact same flow as `handle_message()` text input

### Data Flow
```
Voice message → handle_voice()
  → auth check
  → duration check
  → download to temp file
  → VoiceTranscriber.transcribe_file(temp_path)
  → (optional) reply with transcription
  → process as text through agent flow
  → cleanup temp file
```

---

## Acceptance Criteria

- [ ] `handle_voice()` processes `ContentType.VOICE` messages in private chats
- [ ] `handle_voice()` processes `ContentType.AUDIO` messages in private chats
- [ ] Audio is downloaded via aiogram `bot.get_file()` API
- [ ] Transcription uses `VoiceTranscriber` (FasterWhisper or OpenAI backend)
- [ ] Transcription text shown to user when `show_transcription=True`
- [ ] Transcribed text is processed through existing agent message flow
- [ ] Duration limit enforced (`max_audio_duration_seconds`)
- [ ] Temp files always cleaned up (even on errors)
- [ ] Voice disabled by default (handler skips if `voice_config=None`)
- [ ] VoiceTranscriber initialized lazily (only if voice_config set)

---

## Agent Instructions

When you pick up this task:

1. **Verify** TASK-262 and TASK-264 are complete
2. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
3. **Read** `parrot/integrations/telegram/wrapper.py` for existing handler patterns
4. **Read** `parrot/integrations/msteams/wrapper.py` for voice handling reference
5. **Implement** the `handle_voice()` method and handler registration
6. **Run** `ruff check parrot/integrations/telegram/wrapper.py`
7. **Run** `pytest tests/integrations/telegram/ -v`
8. **Move this file** to `sdd/tasks/completed/`
9. **Update index** → `"done"`
