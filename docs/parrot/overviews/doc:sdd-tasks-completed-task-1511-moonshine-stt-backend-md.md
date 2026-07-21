---
type: Wiki Overview
title: 'TASK-1511: Moonshine STT backend'
id: doc:sdd-tasks-completed-task-1511-moonshine-stt-backend-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 2** of the spec (§3). Adds an opt-in sub-second STT backend
relates_to:
- concept: mod:parrot.voice.transcriber.backend
  rel: mentions
- concept: mod:parrot.voice.transcriber.models
  rel: mentions
- concept: mod:parrot.voice.transcriber.moonshine_backend
  rel: mentions
- concept: mod:parrot.voice.transcriber.transcriber
  rel: mentions
---

# TASK-1511: Moonshine STT backend

**Feature**: FEAT-231 — AgentTalk Voice Support
**Spec**: `sdd/specs/agentalk-voice-support.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements **Module 2** of the spec (§3). Adds an opt-in sub-second STT backend
`MoonshineSTTBackend` behind the **existing** `AbstractTranscriberBackend` seam,
registers it in the `VoiceTranscriber._get_backend` dispatch, extends the
`TranscriberBackend` enum, and adds the `voice-moonshine` extra. **FasterWhisper
stays the default** — Moonshine is opt-in. No new abstraction — this mirrors the
existing `FasterWhisperBackend` exactly.

Independent of the Supertonic TTS task (TASK-1510): different subpackage
(`transcriber/` vs `tts/`). Both touch `pyproject.toml` (different blocks).

---

## Scope

- **Implement** `MoonshineSTTBackend(AbstractTranscriberBackend)` in a new file
  `parrot/voice/transcriber/moonshine_backend.py`, honouring the **exact** abstract
  signature `async def transcribe(self, audio_path: Path, language=None) -> TranscriptionResult`.
- Input is a **`Path`**, not bytes. Run inference off the event loop via
  `asyncio.to_thread` (mirror `FasterWhisperBackend._transcribe_sync`).
- Lazy-import the Moonshine runtime inside the backend; raise
  `ImportError`/`RuntimeError` when the extra is not installed.
- **Add** `MOONSHINE = "moonshine"` to the `TranscriberBackend` enum in
  `transcriber/models.py`.
- **Add** a `TranscriberBackend.MOONSHINE` branch to `VoiceTranscriber._get_backend`
  in `transcriber/transcriber.py` (mirroring the FASTER_WHISPER branch).
- **Add** a `voice-moonshine` extra in `ai-parrot-integrations/pyproject.toml`
  and reference it from the `voice` aggregate extra.
- **Write** unit tests.

**NOT in scope**: the handler (TASK-1512), Supertonic TTS (TASK-1510), route
registration (TASK-1513), any change to `FasterWhisperBackend`,
`OpenAIWhisperBackend`, or `AbstractTranscriberBackend`. Do NOT change the
default backend (`VoiceTranscriberConfig.backend` stays `FASTER_WHISPER`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/voice/transcriber/moonshine_backend.py` | CREATE | `MoonshineSTTBackend(AbstractTranscriberBackend)` |
| `packages/ai-parrot-integrations/src/parrot/voice/transcriber/models.py` | MODIFY | Add `MOONSHINE = "moonshine"` to `TranscriberBackend` (line 16) |
| `packages/ai-parrot-integrations/src/parrot/voice/transcriber/transcriber.py` | MODIFY | Add `MOONSHINE` dispatch branch in `_get_backend` (line 70-104) |
| `packages/ai-parrot-integrations/pyproject.toml` | MODIFY | Add `voice-moonshine` extra; add it to `voice` aggregate |
| `packages/ai-parrot-integrations/tests/voice/transcriber/test_moonshine_backend.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pathlib import Path
from parrot.voice.transcriber.backend import AbstractTranscriberBackend  # verified: voice/transcriber/backend.py:18
from parrot.voice.transcriber.models import (                            # verified: voice/transcriber/models.py:16,28,87
    TranscriberBackend, TranscriptionResult, VoiceTranscriberConfig,
)
```

### Existing Signatures to Use
```python
# packages/ai-parrot-integrations/src/parrot/voice/transcriber/backend.py
class AbstractTranscriberBackend(ABC):                                  # line 18
    @abstractmethod
    async def transcribe(self, audio_path: Path,
                         language: Optional[str] = None) -> TranscriptionResult:  # lines 38-43
    async def close(self) -> None: ...                                  # line 77 (default no-op)

# packages/ai-parrot-integrations/src/parrot/voice/transcriber/models.py
class TranscriberBackend(str, Enum):                                    # line 16
    FASTER_WHISPER = "faster_whisper"                                   # line 24
    OPENAI_WHISPER = "openai_whisper"                                   # line 25  → ADD MOONSHINE = "moonshine"
class VoiceTranscriberConfig(BaseModel):                               # line 28
    backend: TranscriberBackend = TranscriberBackend.FASTER_WHISPER    # line 39 (DEFAULT — do not change)
    model_size: str = "small"; language: Optional[str] = None
    max_audio_duration_seconds: int = 60
class TranscriptionResult(BaseModel):                                  # line 87
    text: str; language: str; duration_seconds: float                  # lines 95,99,103
    confidence: Optional[float] = None; processing_time_ms: int        # lines 108,114

# packages/ai-parrot-integrations/src/parrot/voice/transcriber/transcriber.py
class VoiceTranscriber:                                                # line 30
    def _get_backend(self) -> AbstractTranscriberBackend:              # line 70
        if self.config.backend == TranscriberBackend.FASTER_WHISPER:  # line 84  ← mirror this branch
            self._backend = FasterWhisperBackend(model_size=self.config.model_size)
        elif self.config.backend == TranscriberBackend.OPENAI_WHISPER: ...  # line 92
        else: raise ValueError(f"Unknown backend: {self.config.backend}")   # line 102

# Reference impl to mirror (asyncio.to_thread offloading):
# packages/ai-parrot-integrations/src/parrot/voice/transcriber/faster_whisper_backend.py
class FasterWhisperBackend(AbstractTranscriberBackend):               # line 21
    async def transcribe(self, audio_path: Path, language=None):     # line 83
        if not audio_path.exists(): raise FileNotFoundError(...)
        result = await asyncio.to_thread(self._transcribe_sync, audio_path, language)  # line 111
```

### Existing pyproject extras (mirror this convention)
```toml
# packages/ai-parrot-integrations/pyproject.toml
voice-local  = ["faster-whisper"]
voice = [ ... "ai-parrot-integrations[voice-local]" ...,
          # ADD: "ai-parrot-integrations[voice-moonshine]",
]
# ADD a new block:  voice-moonshine = ["<moonshine-stt-runtime-pkg>"]
```

### Does NOT Exist
- ~~`MoonshineSTTBackend`~~ — this task creates it.
- ~~`TranscriberBackend.MOONSHINE`~~ — enum currently only `FASTER_WHISPER`, `OPENAI_WHISPER`.
- ~~`AbstractTranscriberBackend.transcribe(bytes)`~~ — input is a **`Path`**, not bytes.
- ~~`VoiceTranscriber.transcribe(...)`~~ — the service method is `transcribe_file(file_path: Path)` / `transcribe_url(url)`; the **backend** method is `transcribe(audio_path)`.

---

## Implementation Notes

### Pattern to Follow
```python
# Mirror FasterWhisperBackend: lazy model load + asyncio.to_thread
import asyncio, time
class MoonshineSTTBackend(AbstractTranscriberBackend):
    def __init__(self, model_name: str = "...") -> None:
        self.model_name = model_name
        self.logger = logging.getLogger(__name__)
        self._model = None  # lazy

    async def transcribe(self, audio_path: Path, language=None) -> TranscriptionResult:
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")
        start = time.perf_counter()
        text, lang, dur = await asyncio.to_thread(self._transcribe_sync, audio_path, language)
        return TranscriptionResult(
            text=text, language=lang or "en", duration_seconds=dur,
            processing_time_ms=int((time.perf_counter() - start) * 1000),
        )
```

### Key Constraints
- async throughout; inference under `asyncio.to_thread`.
- Pydantic `TranscriptionResult` for the return.
- `self.logger` at model load and transcription completion.
- Do NOT change the default backend; Moonshine is opt-in only.

### References in Codebase
- `voice/transcriber/faster_whisper_backend.py` — backend pattern to mirror.
- `voice/transcriber/openai_backend.py` — second existing impl for reference.

---

## Acceptance Criteria

- [ ] `MoonshineSTTBackend(AbstractTranscriberBackend)` implemented with the exact abstract signature.
- [ ] `TranscriberBackend.MOONSHINE == "moonshine"`; `VoiceTranscriber._get_backend()` builds `MoonshineSTTBackend`.
- [ ] Default `VoiceTranscriberConfig().backend == TranscriberBackend.FASTER_WHISPER` (unchanged).
- [ ] Missing extra raises `ImportError`/`RuntimeError`.
- [ ] `voice-moonshine` extra added and referenced from `voice` aggregate.
- [ ] Tests pass: `pytest packages/ai-parrot-integrations/tests/voice/transcriber/test_moonshine_backend.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot-integrations/src/parrot/voice/transcriber/`
- [ ] Import works: `from parrot.voice.transcriber.moonshine_backend import MoonshineSTTBackend`

---

## Test Specification

```python
# packages/ai-parrot-integrations/tests/voice/transcriber/test_moonshine_backend.py
import pytest
from parrot.voice.transcriber.models import TranscriberBackend, VoiceTranscriberConfig, TranscriptionResult
from parrot.voice.transcriber.transcriber import VoiceTranscriber


def test_enum_has_moonshine():
    assert TranscriberBackend.MOONSHINE == "moonshine"


def test_default_backend_unchanged():
    assert VoiceTranscriberConfig().backend == TranscriberBackend.FASTER_WHISPER


def test_transcriber_dispatches_moonshine(monkeypatch):
    t = VoiceTranscriber(VoiceTranscriberConfig(backend=TranscriberBackend.MOONSHINE))
    backend = t._get_backend()  # may need monkeypatched model
    assert backend.__class__.__name__ == "MoonshineSTTBackend"


async def test_transcribe_returns_result(moonshine_stub, tmp_path):
    wav = tmp_path / "a.wav"; wav.write_bytes(b"RIFF....")
    result = await moonshine_stub.transcribe(wav)
    assert isinstance(result, TranscriptionResult)
    assert result.text is not None


async def test_missing_file_raises(moonshine_stub, tmp_path):
    with pytest.raises(FileNotFoundError):
        await moonshine_stub.transcribe(tmp_path / "nope.wav")
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above (§2, §3 Module 2, §6, §7).
2. **Check dependencies** — none.
3. **Verify the Codebase Contract** — confirm the enum at `transcriber/models.py:16`
   and the `_get_backend` dispatch at `transcriber/transcriber.py:84` are unchanged before editing.
4. **Update status** in the per-spec index → `"in-progress"`.
5. **Implement** per scope.
6. **Verify** all acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: sdd-worker (Claude Opus 4.8)
**Date**: 2026-06-09
**Notes**:
- Created `MoonshineSTTBackend(AbstractTranscriberBackend)` with the exact
  abstract signature `transcribe(audio_path: Path, language=None)`. Runtime
  imported lazily (`_ensure_model`); inference runs off the event loop via
  `asyncio.to_thread(self._transcribe_sync, ...)` (mirrors FasterWhisper).
- Added `MOONSHINE = "moonshine"` to `TranscriberBackend` and a
  `TranscriberBackend.MOONSHINE` dispatch branch in `VoiceTranscriber._get_backend`.
  FasterWhisper remains the default — verified by `test_default_backend_unchanged`.
- Missing runtime raises `ImportError`; missing audio file raises
  `FileNotFoundError`. No silent degradation.
- Lazy import is robust to both Moonshine distribution names
  (`moonshine_onnx` from `useful-moonshine-onnx`, or `moonshine`).
- `duration_seconds` is best-effort probed from WAV headers via stdlib `wave`
  (Moonshine does not report duration); falls back to 0.0.
- Added `voice-moonshine = ["useful-moonshine-onnx"]` extra and referenced it
  from the `voice` aggregate.
- Tests: 6 new pass; full transcriber suite (20) green; `ruff check` clean.

**Deviations from spec**: none. R-deps (Moonshine runtime package) resolved to
`useful-moonshine-onnx` per spec §8 R-deps (implementer's call); the
`_transcribe_sync` inference seam is stubbable for tests.
