# Feature Specification: Telegram Voice Note Support

**Feature ID**: FEAT-039
**Date**: 2026-03-09
**Author**: AI-Parrot Team
**Status**: approved
**Target version**: 1.6.0

---

## 1. Motivation & Business Requirements

> Enable Telegram bots to process voice messages and audio files by transcribing them to text and passing the transcribed text to the agent as input.

### Problem Statement

The `TelegramAgentWrapper` currently handles text, photos, and documents — but ignores voice messages and audio files entirely. When a Telegram user sends a voice note (the microphone button) or forwards an audio file, the bot does not respond.

This is a significant UX gap:
- Voice notes are the most common message type on Telegram mobile (especially in non-English markets)
- Users expect AI assistants to understand voice input
- The MS Teams integration already supports voice notes via `VoiceTranscriber` (FEAT-008), but the transcription infrastructure lives inside `parrot/integrations/msteams/voice/` — tightly coupled to MS Teams

### Goals

1. Register handlers for `ContentType.VOICE` (voice notes) and `ContentType.AUDIO` (audio files) in `TelegramAgentWrapper`
2. Download audio from Telegram CDN via `bot.get_file()` + `bot.download_file()`
3. Transcribe using the existing `VoiceTranscriber` (FasterWhisper or OpenAI Whisper backends)
4. Optionally show the transcription text to the user before processing
5. Feed the transcribed text through the existing agent message flow
6. **Refactor** the voice transcription system to a shared location (`parrot/voice/transcriber/`) so both MS Teams and Telegram (and future integrations) can reuse it without cross-importing
7. Add `voice_config` to `TelegramAgentConfig` for per-bot transcription settings

### Non-Goals (explicitly out of scope)

- Real-time streaming transcription (voice notes are complete files)
- Text-to-speech responses (bot responds with text)
- Video message audio extraction
- Voice authentication / speaker identification
- Adding new transcription backends (only reuse existing FasterWhisper and OpenAI Whisper)
- Group voice message support (private chats first; group support is a follow-up)

---

## 2. Architectural Design

### Overview

Refactor the voice transcription system from `parrot/integrations/msteams/voice/` to `parrot/voice/transcriber/` as a shared service. Then add a `handle_voice()` handler to `TelegramAgentWrapper` that downloads, transcribes, and processes voice input.

### Component Diagram

```
Telegram User (voice note)
      │
      ▼
TelegramAgentWrapper.handle_voice(message)
      │
      ├─ 1. Send typing indicator
      ├─ 2. Download via bot.get_file() → bot.download_file()
      ├─ 3. Save to temp file (.ogg)
      │
      ▼
VoiceTranscriber.transcribe_file(temp_path)     ← shared service
      │
      ├─ FasterWhisperBackend (local GPU)
      └─ OpenAIWhisperBackend (cloud API)
      │
      ▼
TranscriptionResult { text, language, duration }
      │
      ├─ 4. (Optional) Reply with transcription text
      ├─ 5. Process text through existing agent flow
      └─ 6. Clean up temp file
```

### Shared Voice Module Structure

```
parrot/voice/transcriber/          ← NEW shared location
├── __init__.py                     # Public exports
├── models.py                       # VoiceTranscriberConfig, TranscriptionResult, TranscriberBackend
├── backend.py                      # AbstractTranscriberBackend
├── transcriber.py                  # VoiceTranscriber orchestrator
├── faster_whisper_backend.py       # FasterWhisper backend
└── openai_backend.py               # OpenAI Whisper backend

parrot/integrations/msteams/voice/  ← MODIFY to re-export from shared
├── __init__.py                     # Re-export from parrot.voice.transcriber + MS Teams-specific AudioAttachment
└── models.py                       # Keep only AudioAttachment (MS Teams-specific)
```

### Integration Points

| Component | Change | Description |
|-----------|--------|-------------|
| `parrot/voice/transcriber/` | CREATE | Move voice transcription system to shared location |
| `parrot/integrations/msteams/voice/` | MODIFY | Re-export from shared module, keep only MS Teams-specific `AudioAttachment` |
| `parrot/integrations/telegram/models.py` | MODIFY | Add `voice_config: Optional[VoiceTranscriberConfig]` field |
| `parrot/integrations/telegram/wrapper.py` | MODIFY | Add `handle_voice()` handler, register for VOICE + AUDIO content types |

### Data Flow

1. **Voice message arrives** → aiogram dispatches to `handle_voice(message: Message)`
2. **Authorization check** — same `_is_authorized()` pattern as text messages
3. **Download audio** — `file = await bot.get_file(message.voice.file_id)` → `await bot.download_file(file.file_path, destination)`
4. **Transcribe** — `result = await self._transcriber.transcribe_file(temp_path, language=config.language)`
5. **Validate** — check result is non-empty, duration within limits
6. **Show transcription** (if `show_transcription=True`) — reply with italic transcription text
7. **Process as text** — call the same agent flow as `handle_message()` with `result.text` as input
8. **Cleanup** — delete temp file

### Telegram Audio Types

| Content Type | aiogram attribute | Default format | Use case |
|-------------|-------------------|---------------|----------|
| `ContentType.VOICE` | `message.voice` | `.ogg` (Opus) | Microphone recordings |
| `ContentType.AUDIO` | `message.audio` | Varies (.mp3, .m4a) | Forwarded audio files |

Both provide `file_id` for download via `bot.get_file()`.

---

## 3. Module Breakdown

### Module 1: Shared Voice Transcription Module

**Action**: CREATE `parrot/voice/transcriber/`

Move the following files from `parrot/integrations/msteams/voice/` to `parrot/voice/transcriber/`:
- `models.py` → `VoiceTranscriberConfig`, `TranscriptionResult`, `TranscriberBackend` (remove `AudioAttachment` — that stays in msteams)
- `backend.py` → `AbstractTranscriberBackend`
- `transcriber.py` → `VoiceTranscriber`
- `faster_whisper_backend.py` → `FasterWhisperBackend`
- `openai_backend.py` → `OpenAIWhisperBackend`

Update all internal imports within the moved files.

### Module 2: MS Teams Backward Compatibility

**Action**: MODIFY `parrot/integrations/msteams/voice/`

- Update `__init__.py` to re-export everything from `parrot.voice.transcriber`
- Keep `AudioAttachment` model in `parrot/integrations/msteams/voice/models.py` (MS Teams-specific)
- Update `parrot/integrations/msteams/wrapper.py` imports to use new paths (or rely on re-exports)

### Module 3: Telegram Config Updates

**Action**: MODIFY `parrot/integrations/telegram/models.py`

- Add `voice_config: Optional[VoiceTranscriberConfig] = None` to `TelegramAgentConfig`
- Update `from_dict()` to parse `voice_config` from YAML (same pattern as MS Teams)
- Add `voice_enabled` property: `return self.voice_config is not None and self.voice_config.enabled`

### Module 4: Telegram Voice Handler

**Action**: MODIFY `parrot/integrations/telegram/wrapper.py`

- Register handlers for `ContentType.VOICE` and `ContentType.AUDIO` in private chats
- Implement `handle_voice(message: Message)`:
  1. Extract `voice` or `audio` object from message
  2. Check `voice_config` is enabled, else ignore
  3. Send `ChatAction.TYPING` indicator
  4. Download file via `bot.get_file(file_id)` → `bot.download_file(file_path, dest)`
  5. Transcribe via `VoiceTranscriber.transcribe_file()`
  6. Validate result (non-empty text, duration check)
  7. Optionally reply with transcription
  8. Process through existing message flow
  9. Clean up temp file in `finally` block
- Initialize `VoiceTranscriber` in wrapper `__init__` (lazy — only if `voice_config` is set)
- Add cleanup in wrapper shutdown

---

## 4. Testing Strategy

### Unit Tests

**`tests/voice/transcriber/test_shared_transcriber.py`** (CREATE):
- `test_transcriber_imports_from_shared_location` — verify public imports
- `test_config_model_unchanged` — VoiceTranscriberConfig fields match original
- `test_transcription_result_model` — TranscriptionResult fields

**`tests/integrations/telegram/test_telegram_voice.py`** (CREATE):
- `test_handle_voice_downloads_and_transcribes` — mock bot.get_file, transcriber
- `test_handle_voice_sends_transcription_reply` — show_transcription=True
- `test_handle_voice_skips_transcription_reply` — show_transcription=False
- `test_handle_voice_disabled_ignores_message` — voice_config=None
- `test_handle_voice_empty_transcription` — empty result sends error message
- `test_handle_voice_duration_exceeded` — over max duration sends error
- `test_handle_voice_audio_file` — ContentType.AUDIO (not just VOICE)
- `test_handle_voice_cleanup_on_error` — temp file deleted even on failure

**`tests/integrations/msteams/test_msteams_voice_backward_compat.py`** (CREATE):
- `test_msteams_imports_still_work` — existing import paths still resolve
- `test_audio_attachment_stays_in_msteams` — AudioAttachment importable from msteams.voice

### Integration Tests

**`tests/integrations/telegram/test_telegram_voice_integration.py`** (CREATE):
- `test_voice_message_full_flow` — voice note → transcription → agent response
- `test_audio_message_full_flow` — audio file → transcription → agent response
- `test_voice_with_no_config_ignored` — no voice_config, voice message silently ignored

---

## 5. YAML Configuration Example

```yaml
agents:
  HRBot:
    chatbot_id: hr_agent
    bot_token: "${HRBOT_TELEGRAM_TOKEN}"
    voice_config:
      enabled: true
      backend: faster_whisper     # or "openai_whisper"
      model_size: small           # tiny, base, small, medium, large-v3
      language: null              # null = auto-detect
      show_transcription: true    # show "I heard: ..." before processing
      max_audio_duration_seconds: 60
      # openai_api_key: "sk-..."  # required only for openai_whisper backend
```

---

## 6. Risk & Mitigation

| Risk | Impact | Mitigation |
|------|--------|------------|
| Moving shared module breaks MS Teams imports | High | Re-export everything from `msteams/voice/__init__.py`; run existing MS Teams tests |
| Large audio files cause memory/timeout issues | Medium | Enforce `max_audio_duration_seconds`; stream download to temp file |
| Telegram .ogg format not supported by Whisper | Low | Whisper natively supports OGG/Opus; no conversion needed |
| GPU not available for FasterWhisper | Low | Falls back to CPU; OpenAI Whisper backend as cloud alternative |
| Temp file cleanup missed on crash | Low | Use `try/finally` and `tempfile.NamedTemporaryFile` with delete-on-close |

---

## 7. Open Questions

1. **Should voice messages be supported in group chats?** Currently scoped to private chats only. Group support adds complexity (which messages to transcribe, @mention requirement). → Suggest: private only for v1, group support as follow-up: only private chats.
2. **Should the transcription be stored in conversation memory?** Should the memory show the original voice note or the transcribed text? → Suggest: store transcribed text, same as typed text: store transcribed text.
3. **Rate limiting**: Should there be a per-user cooldown for voice messages to prevent abuse? → Suggest: rely on `max_audio_duration_seconds` for now; rate limiting as follow-up: Rate-limiting need to be a MUST, avoid several messages per minute.

---

## 8. Acceptance Criteria

- [ ] Voice transcription module lives in `parrot/voice/transcriber/` (shared)
- [ ] MS Teams voice integration still works (backward-compatible imports)
- [ ] `TelegramAgentConfig` has `voice_config` field with `VoiceTranscriberConfig`
- [ ] `handle_voice()` processes `ContentType.VOICE` messages in private chats
- [ ] `handle_voice()` processes `ContentType.AUDIO` messages in private chats
- [ ] Audio is downloaded via aiogram `bot.get_file()` API
- [ ] Transcription uses `VoiceTranscriber` (FasterWhisper or OpenAI backend)
- [ ] Transcription text shown to user when `show_transcription=True`
- [ ] Transcribed text is processed through existing agent message flow
- [ ] Duration limit enforced (`max_audio_duration_seconds`)
- [ ] Temp files always cleaned up (even on errors)
- [ ] Voice disabled by default (`voice_config=None`)
- [ ] All existing MS Teams voice tests pass unchanged
- [ ] All new unit and integration tests pass
