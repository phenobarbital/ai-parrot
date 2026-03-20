# TASK-262: Shared Voice Transcription Module

**Feature**: Telegram Voice Note Support (FEAT-039)
**Spec**: `sdd/specs/telegram-voice-notes.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: claude-session

---

## Context

> Move the voice transcription system from `parrot/integrations/msteams/voice/` to a shared location at `parrot/voice/transcriber/` so both MS Teams and Telegram (and future integrations) can reuse it without cross-importing.
> Implements spec Section 3 — Module 1.

---

## Scope

### Files to Create

**`parrot/voice/transcriber/__init__.py`** (CREATE):
- Public exports: `VoiceTranscriber`, `VoiceTranscriberConfig`, `TranscriptionResult`, `TranscriberBackend`, `AbstractTranscriberBackend`, `FasterWhisperBackend`, `OpenAIWhisperBackend`

**`parrot/voice/transcriber/models.py`** (CREATE):
- Move `VoiceTranscriberConfig`, `TranscriptionResult`, `TranscriberBackend` from `parrot/integrations/msteams/voice/models.py`
- Do NOT move `AudioAttachment` (MS Teams-specific, stays in msteams)

**`parrot/voice/transcriber/backend.py`** (CREATE):
- Move `AbstractTranscriberBackend` from `parrot/integrations/msteams/voice/backend.py`

**`parrot/voice/transcriber/transcriber.py`** (CREATE):
- Move `VoiceTranscriber` orchestrator from `parrot/integrations/msteams/voice/transcriber.py`

**`parrot/voice/transcriber/faster_whisper_backend.py`** (CREATE):
- Move `FasterWhisperBackend` from `parrot/integrations/msteams/voice/faster_whisper_backend.py`

**`parrot/voice/transcriber/openai_backend.py`** (CREATE):
- Move `OpenAIWhisperBackend` from `parrot/integrations/msteams/voice/openai_backend.py`

**`parrot/voice/__init__.py`** (CREATE):
- Package init file

### Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/voice/__init__.py` | CREATE | Package init |
| `parrot/voice/transcriber/__init__.py` | CREATE | Public exports |
| `parrot/voice/transcriber/models.py` | CREATE | Move models (except AudioAttachment) |
| `parrot/voice/transcriber/backend.py` | CREATE | Move abstract backend |
| `parrot/voice/transcriber/transcriber.py` | CREATE | Move VoiceTranscriber |
| `parrot/voice/transcriber/faster_whisper_backend.py` | CREATE | Move FasterWhisper backend |
| `parrot/voice/transcriber/openai_backend.py` | CREATE | Move OpenAI Whisper backend |

---

## Implementation Notes

- Copy files from `parrot/integrations/msteams/voice/` to `parrot/voice/transcriber/`
- Update all internal imports within the moved files to reference new paths
- Keep `AudioAttachment` in `parrot/integrations/msteams/voice/models.py` — it's MS Teams-specific
- Do NOT modify `parrot/integrations/msteams/voice/` in this task (that's TASK-263)
- Ensure all moved classes/functions maintain identical signatures and behavior

---

## Acceptance Criteria

- [ ] Voice transcription module lives in `parrot/voice/transcriber/` (shared)
- [ ] All classes importable from `parrot.voice.transcriber`
- [ ] Internal imports within moved files reference `parrot.voice.transcriber`
- [ ] `AudioAttachment` NOT present in shared module
- [ ] No circular imports

---

## Agent Instructions

When you pick up this task:

1. **Read** the existing `parrot/integrations/msteams/voice/` files to understand current structure
2. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
3. **Create** `parrot/voice/__init__.py` and `parrot/voice/transcriber/` package
4. **Copy** each file, updating imports to new paths
5. **Run** `python -c "from parrot.voice.transcriber import VoiceTranscriber, VoiceTranscriberConfig, TranscriptionResult"` to verify imports
6. **Run** `ruff check parrot/voice/`
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`

---

## Completion Note

Completed 2026-03-09. All voice transcription files moved to `parrot/voice/transcriber/`:

- `models.py` — `VoiceTranscriberConfig`, `TranscriptionResult`, `TranscriberBackend` (AudioAttachment excluded)
- `backend.py` — `AbstractTranscriberBackend`
- `transcriber.py` — `VoiceTranscriber` orchestrator
- `faster_whisper_backend.py` — `FasterWhisperBackend`
- `openai_backend.py` — `OpenAIWhisperBackend`
- `__init__.py` — Public exports (7 symbols)

All imports verified working. No circular imports. `ruff check` passes clean. AudioAttachment correctly excluded from shared module.
