# TASK-1749: Voice Integration Provider Registration

**Feature**: FEAT-302 — Native Bedrock Client (Converse API) + Nova 2 Sonic
**Spec**: `sdd/specs/bedrock-client-llm.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1748
**Assigned-to**: unassigned

---

## Context

Register Nova Sonic as a voice provider in the `VoiceProvider` enum and ensure `VoiceChatHandler` can route to `NovaSonicClient` for bidirectional voice sessions.

Implements Spec Module 8.

---

## Scope

- Add `NOVA_SONIC = "nova_sonic"` to `VoiceProvider` enum in `parrot/voice/models.py`
- Update `VoiceChatHandler` (or its provider resolution logic) to recognize `VoiceProvider.NOVA_SONIC` and instantiate `NovaSonicClient`
- Ensure audio format compatibility: `VoiceChatHandler` must handle 16kHz in / 24kHz out PCM
- Write tests

**NOT in scope**: NovaSonicClient implementation (TASK-1748), full end-to-end voice pipeline testing.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/voice/models.py` | MODIFY | Add `NOVA_SONIC` to `VoiceProvider` |
| `packages/ai-parrot-integrations/src/parrot/voice/handler.py` | MODIFY | Add Nova Sonic provider resolution (if handler exists) |
| `tests/voice/test_nova_sonic_provider.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.voice.models import VoiceProvider  # verified: parrot/voice/models.py:24
```

### Existing Signatures to Use
```python
# packages/ai-parrot-integrations/src/parrot/voice/models.py:24
class VoiceProvider(str, Enum):
    GOOGLE_LIVE = "google_live"
    OPENAI_REALTIME = "openai_realtime"
    WHISPER_TTS = "whisper_tts"
```

### Does NOT Exist
- ~~`VoiceProvider.NOVA_SONIC`~~ — not yet; this task adds it
- ~~`VoiceChatHandler.create_nova_sonic()`~~ — does not exist; may need to add provider routing

---

## Implementation Notes

### Key Constraints
- `VoiceProvider` is in the `ai-parrot-integrations` package, not core
- Audio sample rate difference: most voice providers use different rates. The handler may need a resampling step or configuration
- Keep the integration lightweight — Nova Sonic is experimental

---

## Acceptance Criteria

- [ ] `VoiceProvider.NOVA_SONIC` exists with value `"nova_sonic"`
- [ ] Provider resolution in `VoiceChatHandler` recognizes `NOVA_SONIC`
- [ ] All tests pass: `pytest tests/voice/test_nova_sonic_provider.py -v`

---

## Test Specification

```python
# tests/voice/test_nova_sonic_provider.py
import pytest
from parrot.voice.models import VoiceProvider


class TestNovaSonicProvider:
    def test_enum_exists(self):
        assert VoiceProvider.NOVA_SONIC.value == "nova_sonic"

    def test_all_providers_present(self):
        providers = [p.value for p in VoiceProvider]
        assert "nova_sonic" in providers
        assert "google_live" in providers
        assert "openai_realtime" in providers
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** for full context on Module 8
2. **Verify** TASK-1748 is completed — `NovaSonicClient` must exist
3. **Read** `parrot/voice/models.py` and the voice handler code
4. **Add** the enum value and provider routing
5. **Run tests** and verify all acceptance criteria

---

## Completion Note

*(Agent fills this in when done)*
