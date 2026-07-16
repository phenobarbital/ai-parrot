---
type: Wiki Overview
title: 'TASK-246-003: Unit tests for voice adapters and provider factories'
id: doc:sdd-tasks-completed-task-246-003-unit-tests-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: FEAT-246 test coverage. All tests from the spec section 4 (unit tests table),
relates_to:
- concept: mod:parrot.integrations.liveavatar
  rel: mentions
- concept: mod:parrot.voice.transcriber.backend
  rel: mentions
- concept: mod:parrot.voice.transcriber.models
  rel: mentions
---

# TASK-246-003: Unit tests for voice adapters and provider factories

**Feature**: livekit-native-voice-adapters
**Spec**: sdd/specs/livekit-native-voice-adapters.spec.md
**Status**: [ ] pending | [ ] in-progress | [ ] done
**Priority**: high
**Depends-on**: TASK-246-001, TASK-246-002
**Assigned-to**: unassigned

## Context

FEAT-246 test coverage. All tests from the spec section 4 (unit tests table),
exercised with fakes so livekit-plugins-deepgram/cartesia are not required.

## Scope

Create `packages/ai-parrot-integrations/tests/integrations/liveavatar/test_voice_adapters.py`
covering all 10 unit tests from spec section 4:

1. `test_supertonic_tts_emits_frames` — `synthesize("hello")` yields audio frames;
   sample_rate matches fake pipeline's 44100; synth runs off-thread (check thread usage).
2. `test_supertonic_tts_blank_text` — `synthesize("")` → no frames, no error.
3. `test_transcriber_stt_recognize` — `_recognize_impl` writes WAV, calls fake backend,
   returns final `SpeechEvent` with `text="hello world"`.
4. `test_transcriber_stt_tempfile_cleanup` — temp WAV is unlinked even when backend raises.
5. `test_transcriber_stt_error_degrades` — backend error → empty transcript event, logged.
6. `test_whisper_and_moonshine_select_backend` — each subclass instantiates its expected backend.
7. `test_resolve_stt_default_whisper` — no env → `StreamAdapter` wrapping `WhisperSTT`.
8. `test_resolve_tts_default_supertonic` — with `SUPERTONIC_MODEL_DIR` set (fake), returns `SupertonicTTS`.
9. `test_resolve_providers_env_override` — env vars select moonshine/deepgram/openai/cartesia/inference.
10. `test_build_session_uses_resolved_components` — `build_session(vad)` wires resolved stt/tts;
    explicit overrides still win.

## Files to Create

- `packages/ai-parrot-integrations/tests/integrations/liveavatar/test_voice_adapters.py`

## Files to Modify

None.

## Implementation Notes

- Use fakes for `SupertonicPipeline` and `AbstractTranscriberBackend` per spec fixtures.
- Fake `stt.StreamAdapter` by patching or using real livekit-agents (already installed).
- Use `pytest.mark.asyncio` for async tests.
- For `test_resolve_providers_env_override`: mock the lazy plugin imports with `unittest.mock.patch`.
  Deepgram/cartesia/inference plugins are not installed; the test verifies the branch is
  reached by mocking the import, not by actually importing the plugin.
- For temp WAV cleanup tests: check `Path(temp_path).exists()` is False after call.
- Use `AudioFrame` from `livekit.rtc` to construct test buffers.

## Codebase Contract

### Verified Test Imports
```python
import pytest
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from livekit.rtc import AudioFrame
from livekit.agents import stt as lk_stt
from parrot.voice.transcriber.backend import AbstractTranscriberBackend
from parrot.voice.transcriber.models import TranscriptionResult
from parrot.integrations.liveavatar.livekit_agent.voice_adapters import (
    SupertonicTTS, WhisperSTT, MoonshineSTT, resolve_stt, resolve_tts,
)
from parrot.integrations.liveavatar.livekit_agent.pipeline import build_session
```

### Test Fixtures from Spec
```python
@pytest.fixture
def fake_pipeline():
    class _P:
        sample_rate = 44100
        def synthesize_pcm(self, text, *, voice=None, language=None, sample_rate=None):
            return b"\x00\x00" * 1000  # 1000 silent samples
    return _P()

@pytest.fixture
def fake_backend():
    class _B(AbstractTranscriberBackend):
        async def transcribe(self, audio_path, language=None):
            return TranscriptionResult(text="hello world", language="en",
                                       duration_seconds=1.0, confidence=0.9,
                                       processing_time_ms=10)
    return _B()
```

## Acceptance Criteria

- [ ] All 10 unit tests pass with `pytest -x`
- [ ] Existing FEAT-243 liveavatar tests still pass (no regressions)
- [ ] No test requires deepgram/cartesia API keys or live network access
- [ ] Tests run without `SUPERTONIC_MODEL_DIR` for most cases (factory mocked)

## Completion Note
(Agent fills this in when done)

## Completion Note

Created `test_voice_adapters.py` with 11 unit tests (10 from the spec + 1 extra
for the ValueError case when SUPERTONIC_MODEL_DIR is missing).

Key implementation notes:
- `StreamAdapter` must be imported from `livekit.agents.stt` (not `.stt.stt`).
- `SupertonicPipeline` is a local import in `_build_supertonic_tts`; the test
  patches `_build_supertonic_tts` directly rather than the class.
- `resolve_stt`/`resolve_tts` are local imports in `build_session`; tests patch
  them at their source module (`voice_adapters`), not at `pipeline`.
- All 11 new tests pass; 124 total liveavatar tests pass (no regressions).
- ruff clean.
