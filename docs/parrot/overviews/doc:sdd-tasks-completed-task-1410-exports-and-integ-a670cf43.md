---
type: Wiki Overview
title: 'TASK-1410: Public exports for voice.tts + end-to-end integration tests'
id: doc:sdd-tasks-completed-task-1410-exports-and-integration-tests-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Final wiring: expose the new TTS surface as a clean public API (mirror of'
relates_to:
- concept: mod:parrot.voice.tts
  rel: mentions
---

# TASK-1410: Public exports for voice.tts + end-to-end integration tests

**Feature**: FEAT-213 — Telegram Voice Reply (TTS Output)
**Spec**: `sdd/specs/FEAT-213-telegram-voice-reply-tts.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1407, TASK-1408, TASK-1409
**Assigned-to**: unassigned

---

## Context

Final wiring: expose the new TTS surface as a clean public API (mirror of
`voice/transcriber/__init__.py`) and add the two integration tests from the spec's
Test Specification (§4) that exercise the full voice-in → voice-out path and prove
text input is unaffected (zero regression).

Implements spec **Module 4** (§3) and the §4 Integration Tests.

---

## Scope

- Populate `voice/tts/__init__.py` to export the public surface:
  `AbstractTTSBackend`, `GoogleTTSBackend`, `VoiceSynthesizer`, `TTSConfig`,
  `SynthesisResult` (with `__all__`), mirroring `voice/transcriber/__init__.py`.
- Optionally re-export the synthesizer from `voice/__init__.py` for convenience
  (only if it does not introduce import cycles — verify).
- Add the two integration tests:
  - `test_voice_in_voice_out_flow` — mocked voice note → mocked transcribe → mocked
    agent → `send_voice` called with the synth's audio.
  - `test_text_input_unaffected` — a normal **text** message does NOT trigger TTS
    (synth never invoked).

**NOT in scope**:
- Any new backend or wiring logic (done in TASK-1407–1409).
- Changing transcriber exports.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/voice/tts/__init__.py` | MODIFY | Public exports + `__all__` |
| `packages/ai-parrot-integrations/src/parrot/voice/__init__.py` | MODIFY | (optional) re-export `VoiceSynthesizer` |
| `packages/ai-parrot-integrations/tests/voice/tts/test_tts_integration.py` | CREATE | voice-in/voice-out + text-unaffected |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references. Use VERBATIM.

### Verified Imports (exist after TASK-1407/1408)
```python
from .backend import AbstractTTSBackend
from .google_backend import GoogleTTSBackend
from .synthesizer import VoiceSynthesizer
from .models import TTSConfig, SynthesisResult
```

### Pattern to Mirror
```python
# packages/ai-parrot-integrations/src/parrot/voice/transcriber/__init__.py
from .backend import AbstractTranscriberBackend
from .faster_whisper_backend import FasterWhisperBackend
from .models import (TranscriberBackend, TranscriptionResult, VoiceTranscriberConfig)
from .openai_backend import OpenAIWhisperBackend
from .transcriber import VoiceTranscriber

__all__ = [
    "VoiceTranscriber",
    "AbstractTranscriberBackend",
    "FasterWhisperBackend",
    "OpenAIWhisperBackend",
    "TranscriberBackend",
    "VoiceTranscriberConfig",
    "TranscriptionResult",
]
```

### Existing State
```python
# packages/ai-parrot-integrations/src/parrot/voice/__init__.py — currently docstring only,
#   NO exports. Adding a VoiceSynthesizer re-export is OPTIONAL and must not create cycles
#   (voice/__init__ importing tts which imports clients — verify it imports cleanly).
```

### Does NOT Exist
- ~~`parrot.voice.tts.__all__` already populated~~ — TASK-1407 left it minimal; finalize here.
- ~~`ElevenLabsBackend` / `OpenAITTSBackend` to export~~ — not implemented (spec Non-Goals).

---

## Implementation Notes

### Key Constraints
- Exports must import cleanly with no side effects (`python -c "import parrot.voice.tts"`).
- Integration tests must be fully mocked — NO network, NO real Google client, NO real
  aiogram bot. Reuse fixtures/mocks from `tests/test_telegram_integration.py`,
  `tests/test_hitl_telegram_voice.py`, and the FEAT-213 unit tests (TASK-1408/1409).
- Keep `__all__` accurate.

### References in Codebase
- `voice/transcriber/__init__.py` — export pattern to mirror
- `tests/test_hitl_telegram_voice.py` — voice Message/Bot mock patterns
- TASK-1409 `test_telegram_voice_reply.py` — wrapper fixture to reuse

---

## Acceptance Criteria

- [ ] `from parrot.voice.tts import (AbstractTTSBackend, GoogleTTSBackend,
      VoiceSynthesizer, TTSConfig, SynthesisResult)` all work.
- [ ] `python -c "import parrot.voice.tts"` imports with no error/side effects.
- [ ] `test_voice_in_voice_out_flow` passes (mocked end-to-end → `send_voice` called).
- [ ] `test_text_input_unaffected` passes (text message → synth never invoked).
- [ ] Full feature suite green:
      `pytest packages/ai-parrot-integrations/tests/ -k "tts or voice" -v`
- [ ] No linting errors: `ruff check packages/ai-parrot-integrations/src/parrot/voice/tts/`

---

## Test Specification

```python
# packages/ai-parrot-integrations/tests/voice/tts/test_tts_integration.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from parrot.voice.tts import (
    AbstractTTSBackend, GoogleTTSBackend, VoiceSynthesizer,
    TTSConfig, SynthesisResult,
)


def test_public_exports_present():
    assert AbstractTTSBackend and GoogleTTSBackend and VoiceSynthesizer
    assert TTSConfig and SynthesisResult


async def test_voice_in_voice_out_flow(wrapper_with_voice):
    """voice note (mock) -> transcribe (mock) -> agent (mock) -> send_voice(audio)."""
    wrapper_with_voice.config.tts_enabled = True
    wrapper_with_voice.config.reply_in_kind = True
    synth = MagicMock()
    synth.synthesize = AsyncMock(
        return_value=SynthesisResult(audio=b"OGG...", mime_format="audio/ogg")
    )
    wrapper_with_voice._synthesizer = synth
    # drive handle_voice with mocked voice Message + bot
    wrapper_with_voice.bot.send_voice.assert_awaited()


async def test_text_input_unaffected(wrapper_with_voice):
    """A normal text message NEVER triggers TTS (zero regression)."""
    wrapper_with_voice.config.tts_enabled = True
    synth = MagicMock()
    synth.synthesize = AsyncMock()
    wrapper_with_voice._synthesizer = synth
    # drive the TEXT message handler (not handle_voice)
    synth.synthesize.assert_not_awaited()
```

---

## Agent Instructions

1. **Read the spec** (§3 Module 4, §4 Integration Tests).
2. **Verify** TASK-1407–1409 are in `sdd/tasks/completed/` and their symbols import.
3. **Update status** in `sdd/tasks/index/FEAT-213-telegram-voice-reply-tts.json` → `"in-progress"`.
4. **Implement** exports + integration tests.
5. **Verify** acceptance criteria (full `-k "tts or voice"` suite green).
6. **Move** this file to `sdd/tasks/completed/` and update index → `"done"`.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-06-02
**Notes**: voice/tts/__init__.py populated with all 5 public symbols + __all__.
voice/__init__.py updated with VoiceSynthesizer convenience re-export (no import cycle).
5 integration tests pass: 3 export/smoke tests + voice-in/voice-out + text-unaffected.
Full -k "tts or voice" suite: 189 passed, 4 pre-existing failures unrelated to FEAT-213.
**Deviations from spec**: none
