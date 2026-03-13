# TASK-330: VoiceBot Prompt Migration

**Feature**: Composable Prompt Layer System
**Spec**: `sdd/specs/composable-prompt-layer.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (1-2h)
**Depends-on**: TASK-329
**Assigned-to**: —

---

## Context

> Migrates VoiceBot from the monolithic `BASIC_VOICE_PROMPT_TEMPLATE` to the composable `voice` preset. This removes the dedicated voice template string and uses the PromptBuilder's voice factory instead.
> Implements spec Section 5.2.

---

## Scope

- Modify `parrot/bots/voice.py`:
  - Set `_prompt_builder = PromptBuilder.voice()` at class level
  - Remove dependency on `BASIC_VOICE_PROMPT_TEMPLATE` (keep the template in legacy.py for backward compat but VoiceBot no longer uses it)
  - Ensure VoiceBot's `configure()` and `create_system_prompt()` flow through the PromptBuilder path via AbstractBot integration (TASK-329)
- Verify voice-specific behavior layer is present (concise, conversational, no long lists)

**NOT in scope**: Modifying other bot types, changing the voice behavior layer content.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/bots/voice.py` | MODIFY | Set class-level `_prompt_builder` to voice preset |

---

## Implementation Notes

- The `voice` preset is already defined in `PromptBuilder.voice()` (TASK-326). VoiceBot just needs to use it.
- `BASIC_VOICE_PROMPT_TEMPLATE` should NOT be deleted yet — it may be referenced by other code. Just stop using it in VoiceBot.
- Test by comparing output structure: should have `<agent_identity>`, `<security_policy>`, `<response_style>` with voice instructions.

---

## Acceptance Criteria

- [ ] VoiceBot uses `PromptBuilder.voice()` at class level.
- [ ] VoiceBot's `create_system_prompt()` produces output with XML layer structure.
- [ ] Voice behavior layer includes concise/conversational instructions.
- [ ] No reference to `BASIC_VOICE_PROMPT_TEMPLATE` in VoiceBot class.
- [ ] Existing VoiceBot tests still pass (if any).

---

## Test Specification

```python
# tests/bots/prompts/test_voicebot_prompt.py
import pytest


@pytest.mark.asyncio
async def test_voicebot_uses_voice_preset():
    """VoiceBot should use voice PromptBuilder preset."""
    from parrot.bots.voice import VoiceBot
    assert VoiceBot._prompt_builder is not None
    assert VoiceBot._prompt_builder.get("behavior") is not None


@pytest.mark.asyncio
async def test_voicebot_prompt_has_voice_behavior():
    """VoiceBot prompt should include voice-specific behavior."""
    from parrot.bots.voice import VoiceBot
    behavior = VoiceBot._prompt_builder.get("behavior")
    assert "concise" in behavior.template.lower() or "conversational" in behavior.template.lower()
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** (`sdd/specs/composable-prompt-layer.spec.md`) Section 5.2.
2. **Read `parrot/bots/voice.py`** to understand current VoiceBot structure.
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`.
4. **Implement** following the scope above.
5. **Run tests**: `pytest tests/bots/ -v -k voice`
6. **Verify** all acceptance criteria are met.
7. **Move this file** to `sdd/tasks/completed/TASK-330-voicebot-migration.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**:
