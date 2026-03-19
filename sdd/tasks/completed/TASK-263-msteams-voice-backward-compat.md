# TASK-263: MS Teams Voice Backward Compatibility

**Feature**: Telegram Voice Note Support (FEAT-039)
**Spec**: `sdd/specs/telegram-voice-notes.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (1-2h)
**Depends-on**: TASK-262
**Assigned-to**: claude-session

---

## Context

> Update `parrot/integrations/msteams/voice/` to re-export from the shared `parrot.voice.transcriber` module, maintaining backward compatibility for all existing MS Teams imports.
> Implements spec Section 3 — Module 2.

---

## Scope

### Files to Modify

**`parrot/integrations/msteams/voice/__init__.py`** (MODIFY):
- Replace direct exports with re-exports from `parrot.voice.transcriber`
- Keep exporting `AudioAttachment` from local `models.py`

**`parrot/integrations/msteams/voice/models.py`** (MODIFY):
- Remove `VoiceTranscriberConfig`, `TranscriptionResult`, `TranscriberBackend` (now in shared module)
- Keep only `AudioAttachment` (MS Teams-specific)
- Optionally add re-imports for backward compatibility

**`parrot/integrations/msteams/voice/backend.py`** (MODIFY or DELETE):
- Replace with re-export from `parrot.voice.transcriber.backend` or delete if `__init__.py` re-exports cover it

**`parrot/integrations/msteams/voice/transcriber.py`** (MODIFY or DELETE):
- Replace with re-export from `parrot.voice.transcriber.transcriber` or delete

**`parrot/integrations/msteams/voice/faster_whisper_backend.py`** (MODIFY or DELETE):
- Replace with re-export or delete

**`parrot/integrations/msteams/voice/openai_backend.py`** (MODIFY or DELETE):
- Replace with re-export or delete

### Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/integrations/msteams/voice/__init__.py` | MODIFY | Re-export from shared module |
| `parrot/integrations/msteams/voice/models.py` | MODIFY | Keep only AudioAttachment |
| `parrot/integrations/msteams/voice/backend.py` | MODIFY/DELETE | Re-export or remove |
| `parrot/integrations/msteams/voice/transcriber.py` | MODIFY/DELETE | Re-export or remove |
| `parrot/integrations/msteams/voice/faster_whisper_backend.py` | MODIFY/DELETE | Re-export or remove |
| `parrot/integrations/msteams/voice/openai_backend.py` | MODIFY/DELETE | Re-export or remove |

---

## Implementation Notes

- The key goal is backward compatibility — existing `from parrot.integrations.msteams.voice import VoiceTranscriber` must still work
- Prefer re-exporting from `__init__.py` rather than keeping individual module files
- Update `parrot/integrations/msteams/wrapper.py` imports if needed (or rely on re-exports)
- Check for any other files that import from `parrot.integrations.msteams.voice`

---

## Acceptance Criteria

- [ ] All existing MS Teams voice imports still resolve
- [ ] `from parrot.integrations.msteams.voice import VoiceTranscriber` works
- [ ] `from parrot.integrations.msteams.voice import AudioAttachment` works
- [ ] `AudioAttachment` stays in `parrot/integrations/msteams/voice/models.py`
- [ ] No duplicate code — shared module is the single source of truth
- [ ] All existing MS Teams tests pass unchanged

---

## Agent Instructions

When you pick up this task:

1. **Verify** TASK-262 is complete
2. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
3. **Find** all imports from `parrot.integrations.msteams.voice` across the codebase
4. **Update** `__init__.py` to re-export from `parrot.voice.transcriber`
5. **Slim down** individual module files (re-export or delete)
6. **Run** existing MS Teams voice tests: `pytest tests/integrations/msteams/ -v -k voice`
7. **Run** `ruff check parrot/integrations/msteams/voice/`
8. **Move this file** to `sdd/tasks/completed/`
9. **Update index** → `"done"`

---

## Completion Note

Completed 2026-03-09. All MS Teams voice module files updated to re-export from `parrot.voice.transcriber`:

- `__init__.py` — Re-exports all shared symbols + `AudioAttachment` from local `models.py`
- `models.py` — Keeps only `AudioAttachment`, re-exports shared models for submodule imports
- `backend.py` — Thin re-export of `AbstractTranscriberBackend`
- `transcriber.py` — Thin re-export of `VoiceTranscriber` (+ `aiohttp` import for test mock paths)
- `faster_whisper_backend.py` — Thin re-export of `FasterWhisperBackend`
- `openai_backend.py` — Thin re-export of `OpenAIWhisperBackend`

All 103 existing MS Teams voice tests pass unchanged. All backward-compatible import paths verified working.
