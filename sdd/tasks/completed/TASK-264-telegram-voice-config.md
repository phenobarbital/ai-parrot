# TASK-264: Telegram Voice Config

**Feature**: Telegram Voice Note Support (FEAT-039)
**Spec**: `sdd/specs/telegram-voice-notes.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (1-2h)
**Depends-on**: TASK-262
**Assigned-to**: claude-session

---

## Context

> Add `voice_config` field to `TelegramAgentConfig` so per-bot voice transcription can be configured via YAML.
> Implements spec Section 3 — Module 3.

---

## Scope

### Files to Modify

**`parrot/integrations/telegram/models.py`** (MODIFY):
- Import `VoiceTranscriberConfig` from `parrot.voice.transcriber`
- Add `voice_config: Optional[VoiceTranscriberConfig] = None` to `TelegramAgentConfig`
- Update `from_dict()` to parse `voice_config` from dict/YAML (same pattern as MS Teams)
- Add `voice_enabled` property: `return self.voice_config is not None and self.voice_config.enabled`

### Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/integrations/telegram/models.py` | MODIFY | Add voice_config field and voice_enabled property |

---

## Implementation Notes

- Follow the same config pattern used in `MSTeamsAgentConfig` for voice config
- `voice_config` defaults to `None` (voice disabled by default)
- The `voice_enabled` property is a convenience check used by the handler
- YAML config example from spec Section 5:
  ```yaml
  voice_config:
    enabled: true
    backend: faster_whisper
    model_size: small
    language: null
    show_transcription: true
    max_audio_duration_seconds: 60
  ```

---

## Acceptance Criteria

- [ ] `TelegramAgentConfig` has `voice_config: Optional[VoiceTranscriberConfig]` field
- [ ] `voice_config` defaults to `None`
- [ ] `from_dict()` correctly parses `voice_config` from dict
- [ ] `voice_enabled` property returns `True` only when config is set and enabled
- [ ] Voice disabled by default (`voice_config=None`)
- [ ] Existing Telegram config tests still pass

---

## Agent Instructions

When you pick up this task:

1. **Verify** TASK-262 is complete
2. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
3. **Read** `parrot/integrations/telegram/models.py` and `parrot/integrations/msteams/models.py` (for voice config pattern)
4. **Modify** `TelegramAgentConfig` to add `voice_config` field
5. **Run** `pytest tests/integrations/telegram/ -v -k config`
6. **Run** `ruff check parrot/integrations/telegram/models.py`
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`
