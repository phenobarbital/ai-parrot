---
type: Wiki Overview
title: 'TASK-1749: Voice Integration Provider Registration'
id: doc:sdd-tasks-completed-task-1749-voice-integration-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Register Nova Sonic as a voice provider in the `VoiceProvider` enum and ensure
  `VoiceChatHandler` can route to `NovaSonicClient` for bidirectional voice sessions.
relates_to:
- concept: mod:parrot.voice.models
  rel: mentions
---

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

Added `NOVA_SONIC = "nova_sonic"` to `VoiceProvider`
(`packages/ai-parrot-integrations/src/parrot/voice/models.py`). Noted (and
did not need to act on) that `AudioFormat.PCM_16K` /
`AudioFormat.PCM_24K` already match Nova Sonic's 16kHz-in/24kHz-out
exactly — no new `AudioFormat` entries were needed for the "audio format
compatibility" acceptance criterion.

**Codebase reality check before implementing**: `VoiceChatHandler`
(`voice/handler.py`) is transport-only (WebSocket) and has never had any
`VoiceProvider`-based branching — voice-client construction is hardcoded
to `GeminiLiveClient` inside `VoiceBot._resolve_llm_config()` in CORE
`parrot/bots/voice.py` (not ai-parrot-integrations, and not in this task's
Files-to-Modify list). Since the task explicitly restricts scope to
`voice/models.py` + `voice/handler.py` + tests (excluding `VoiceBot`'s core
resolution path and "full end-to-end voice pipeline testing"), I added a
new, purely additive module-level function `resolve_voice_client_class(provider)`
in `handler.py` plus a `VoiceChatHandler.resolve_provider_client()`
staticmethod wrapping it — this satisfies the literal acceptance criterion
("Provider resolution in VoiceChatHandler recognizes NOVA_SONIC") without
touching any existing method, `VoiceBot`, or the WebSocket session
pipeline. `NOVA_SONIC` resolves to `NovaSonicClient` (lazily imported);
every other currently-declared provider resolves to the existing
`GeminiLiveClient` default. Wiring this into `VoiceBot`'s actual runtime
selection (so a real end-to-end Nova Sonic voice session can be started)
is a natural follow-up but is out of this task's scope as written.

Fixed a stale detail in the task's own Codebase Contract: `VoiceProvider`
is declared as `class VoiceProvider(Enum):`, not `class VoiceProvider(str, Enum):`
as the contract stated — corrected in this note rather than the task file
since it's a one-line inconsistency that doesn't affect any implementation
choice (`.value` access works identically either way).

Created `packages/ai-parrot-integrations/tests/voice/test_nova_sonic_provider.py`
(7 tests): the task's 2 scaffolded enum tests, plus 5 more covering
`resolve_voice_client_class()` for both providers, the `ImportError` when
`aws_sdk_bedrock_runtime` is missing (deferred to `NovaSonicClient()`
construction, not class resolution), and `VoiceChatHandler.resolve_provider_client()`
recognizing `NOVA_SONIC` while leaving `GOOGLE_LIVE` unchanged. All 7 pass;
`ruff check` clean (required adding a `TYPE_CHECKING`-guarded import for the
`VoiceProvider` forward-reference type hint to satisfy F821). Full
`tests/voice/` suite re-run: 107 passed, 1 skipped (pre-existing skip,
unrelated) — no regressions.
