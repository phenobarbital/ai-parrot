---
type: Wiki Overview
title: 'TASK-1510: Supertonic TTS backend'
id: doc:sdd-tasks-completed-task-1510-supertonic-tts-backend-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 1** of the spec (§3). The voice round-trip needs a
relates_to:
- concept: mod:parrot.voice.tts.backend
  rel: mentions
- concept: mod:parrot.voice.tts.models
  rel: mentions
- concept: mod:parrot.voice.tts.supertonic_backend
  rel: mentions
- concept: mod:parrot.voice.tts.synthesizer
  rel: mentions
---

# TASK-1510: Supertonic TTS backend

**Feature**: FEAT-231 — AgentTalk Voice Support
**Spec**: `sdd/specs/agentalk-voice-support.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements **Module 1** of the spec (§3). The voice round-trip needs a
sub-second TTS backend. This task adds `SupertonicTTSBackend` behind the
**existing** `AbstractTTSBackend` seam, registers it in the lazy
`VoiceSynthesizer._get_backend` dispatch, extends `TTSConfig.backend`, and adds
the `voice-supertonic` extra. No new abstraction is introduced — this mirrors
the existing `GoogleTTSBackend` exactly.

This task is independent of the Moonshine STT task (TASK-1511) — different
subpackage (`tts/` vs `transcriber/`). Both touch `pyproject.toml` (different
blocks); see parallelism note.

---

## Scope

- **Implement** `SupertonicTTSBackend(AbstractTTSBackend)` in a new file
  `parrot/voice/tts/supertonic_backend.py`, honouring the **exact** abstract
  signature `async def synthesize(self, text, *, voice=None, mime_format="audio/ogg", language=None) -> SynthesisResult`.
- The backend MUST return a **browser-playable container** (default target
  `audio/wav`) and set `SynthesisResult.mime_format` **truthfully** — `mime_format`
  is a label, not a converter. If Supertonic emits raw PCM, wrap to WAV before returning.
- Run inference (ONNX) off the event loop via `asyncio.to_thread`.
- Lazy-import the ONNX runtime / model weights inside the backend; raise
  `ImportError`/`ValueError` when the extra is not installed (do NOT silently
  degrade — degradation is the handler's job, TASK-1512).
- **Add** `"supertonic"` to the `TTSConfig.backend` `Literal` in `tts/models.py`.
- **Add** a `"supertonic"` branch to `VoiceSynthesizer._get_backend` in
  `tts/synthesizer.py` (lazy import inside the branch, mirroring the `"google"` branch).
- **Add** a `voice-supertonic` extra in `ai-parrot-integrations/pyproject.toml`
  and reference it from the `voice` aggregate extra.
- **Write** unit tests.

**NOT in scope**: the handler (`AgentVoiceTalk` — TASK-1512), Moonshine STT
(TASK-1511), route registration (TASK-1513), any change to `GoogleTTSBackend` or
`AbstractTTSBackend`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/voice/tts/supertonic_backend.py` | CREATE | `SupertonicTTSBackend(AbstractTTSBackend)` |
| `packages/ai-parrot-integrations/src/parrot/voice/tts/models.py` | MODIFY | Add `"supertonic"` to `TTSConfig.backend` Literal (line 41) |
| `packages/ai-parrot-integrations/src/parrot/voice/tts/synthesizer.py` | MODIFY | Add `"supertonic"` dispatch branch in `_get_backend` (line 52-91) |
| `packages/ai-parrot-integrations/pyproject.toml` | MODIFY | Add `voice-supertonic` extra; add it to `voice` aggregate |
| `packages/ai-parrot-integrations/tests/voice/tts/test_supertonic_backend.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.voice.tts.backend import AbstractTTSBackend       # verified: voice/tts/backend.py:17
from parrot.voice.tts.models import SynthesisResult, TTSConfig # verified: voice/tts/models.py:76,16
```

### Existing Signatures to Use
```python
# packages/ai-parrot-integrations/src/parrot/voice/tts/backend.py
class AbstractTTSBackend(ABC):                                          # line 17
    @abstractmethod
    async def synthesize(self, text: str, *, voice: Optional[str] = None,
                         mime_format: str = "audio/ogg",
                         language: Optional[str] = None) -> SynthesisResult:  # lines 37-45
    async def close(self) -> None: ...                                  # line 80 (default no-op)

# packages/ai-parrot-integrations/src/parrot/voice/tts/models.py
class TTSConfig(BaseModel):                                            # line 16
    backend: Literal["google", "elevenlabs", "openai"] = "google"     # line 41  → ADD "supertonic"
    voice: Optional[str] = None                                       # line 45
    language: Optional[str] = None                                    # line 49
    mime_format: str = "audio/ogg"                                    # line 53
class SynthesisResult(BaseModel):                                     # line 76
    audio: bytes                                                      # line 97
    mime_format: str                                                  # line 105
    duration_s: Optional[float] = None                               # line 109

# packages/ai-parrot-integrations/src/parrot/voice/tts/synthesizer.py
class VoiceSynthesizer:                                               # line 21
    def __init__(self, config: Optional[TTSConfig] = None) -> None:   # line 46
    def _get_backend(self) -> AbstractTTSBackend:                     # line 52
        if backend_name == "google":                                 # line 73  ← mirror this branch
            from .google_backend import GoogleTTSBackend
            self._backend = GoogleTTSBackend(voice=self.config.voice)
        elif backend_name in ("elevenlabs", "openai"): raise ValueError(...)  # line 81
        else: raise ValueError(...)                                   # line 86

# Reference impl to mirror (PCM/label behaviour, asyncio offloading):
# packages/ai-parrot-integrations/src/parrot/voice/tts/google_backend.py — GoogleTTSBackend
```

### Existing pyproject extras (mirror this convention)
```toml
# packages/ai-parrot-integrations/pyproject.toml
voice-local  = ["faster-whisper"]
voice-openai = ["openai>=1.0"]
voice-tts    = ["pydub>=0.25"]
voice = [
    "ai-parrot-integrations[voice-local]",
    "ai-parrot-integrations[voice-openai]",
    "ai-parrot-integrations[voice-tts]",
    # ADD: "ai-parrot-integrations[voice-supertonic]",
]
# ADD a new block:  voice-supertonic = ["onnxruntime...", "<supertonic-weights-pkg>"]
```

### Does NOT Exist
- ~~`SupertonicTTSBackend`~~ — this task creates it.
- ~~`TTSConfig.backend == "supertonic"`~~ — Literal currently only `["google","elevenlabs","openai"]`.
- ~~`VoiceSynthesizer` graceful degradation~~ — `_get_backend` **raises** `ValueError`; it does not degrade.
- ~~`AbstractTTSBackend.synthesize(text) -> bytes`~~ — it returns `SynthesisResult`, not raw bytes.

---

## Implementation Notes

### Pattern to Follow
```python
# Mirror GoogleTTSBackend structure. CPU/inference off the loop:
class SupertonicTTSBackend(AbstractTTSBackend):
    def __init__(self, voice: Optional[str] = None) -> None:
        self.voice = voice
        self.logger = logging.getLogger(__name__)
        self._session = None  # lazy ONNX session

    async def synthesize(self, text, *, voice=None, mime_format="audio/ogg", language=None):
        if not text:
            raise ValueError("text must be non-empty")
        audio_bytes = await asyncio.to_thread(self._synthesize_sync, text, voice or self.voice)
        # ensure browser-playable container; label truthfully
        return SynthesisResult(audio=audio_bytes, mime_format="audio/wav")
```

### Key Constraints
- async throughout; inference under `asyncio.to_thread`.
- Pydantic `SynthesisResult` for the return; never return raw bytes.
- `self.logger` at backend creation and synth completion.
- `mime_format` returned MUST match the actual bytes (default `audio/wav`).
- Extras pinning (`onnxruntime` version + Supertonic weights source) is the
  implementer's call — see spec §8 R-deps.

### References in Codebase
- `voice/tts/google_backend.py` — backend pattern to mirror.
- `voice/transcriber/faster_whisper_backend.py:111` — `asyncio.to_thread` offloading.

---

## Acceptance Criteria

- [ ] `SupertonicTTSBackend(AbstractTTSBackend)` implemented with the exact abstract signature.
- [ ] Returns a browser-playable container (default `audio/wav`) with truthful `mime_format`.
- [ ] `TTSConfig(backend="supertonic")` validates; `VoiceSynthesizer._get_backend()` builds `SupertonicTTSBackend`.
- [ ] Missing extra raises `ImportError`/`ValueError` (no silent degradation).
- [ ] `voice-supertonic` extra added and referenced from `voice` aggregate.
- [ ] Tests pass: `pytest packages/ai-parrot-integrations/tests/voice/tts/test_supertonic_backend.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot-integrations/src/parrot/voice/tts/`
- [ ] Import works: `from parrot.voice.tts.supertonic_backend import SupertonicTTSBackend`

---

## Test Specification

```python
# packages/ai-parrot-integrations/tests/voice/tts/test_supertonic_backend.py
import pytest
from parrot.voice.tts.models import TTSConfig, SynthesisResult
from parrot.voice.tts.synthesizer import VoiceSynthesizer


def test_ttsconfig_accepts_supertonic():
    cfg = TTSConfig(backend="supertonic")
    assert cfg.backend == "supertonic"


def test_synthesizer_dispatches_supertonic(monkeypatch):
    synth = VoiceSynthesizer(TTSConfig(backend="supertonic"))
    backend = synth._get_backend()  # may need monkeypatched ONNX session
    assert backend.__class__.__name__ == "SupertonicTTSBackend"


async def test_synthesize_returns_playable_container(supertonic_stub):
    backend = supertonic_stub
    result = await backend.synthesize("Hola", mime_format="audio/wav", language="es-ES")
    assert isinstance(result, SynthesisResult)
    assert result.mime_format == "audio/wav"
    assert result.audio  # non-empty


async def test_empty_text_raises(supertonic_stub):
    with pytest.raises(ValueError):
        await supertonic_stub.synthesize("")
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above (§2, §3 Module 1, §6, §7).
2. **Check dependencies** — none.
3. **Verify the Codebase Contract** — confirm the `Literal` at `tts/models.py:41`
   and the `_get_backend` dispatch at `tts/synthesizer.py:73` are unchanged before editing.
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
- Created `SupertonicTTSBackend(AbstractTTSBackend)` with the exact abstract
  signature `synthesize(text, *, voice, mime_format, language)`. ONNX session
  is created lazily (`_ensure_session`); inference runs off the event loop via
  `asyncio.to_thread(self._synthesize_sync, ...)`.
- Returns a browser-playable **WAV** container built with the stdlib `wave`
  module (no extra dependency for container wrapping); `SynthesisResult.mime_format`
  is always reported as `audio/wav` so the label matches the bytes. A requested
  `audio/ogg` is normalised to `audio/wav` (truthful labelling).
- Missing deps/weights surface as `ImportError` (onnxruntime absent) or
  `ValueError` (weights unconfigured/not found) — no silent degradation.
- Added `"supertonic"` to `TTSConfig.backend` Literal and a lazy `"supertonic"`
  dispatch branch in `VoiceSynthesizer._get_backend` (mirrors the `google` branch).
- Added `voice-supertonic = ["onnxruntime>=1.17"]` extra and referenced it from
  the `voice` aggregate in `ai-parrot-integrations/pyproject.toml`.
- Tests: 6 new pass; full tts suite (38) green; `ruff check` clean.

**Deviations from spec**: none. R-deps (exact Supertonic weights package) left as
the deployment's responsibility per spec §8 R-deps — the backend loads weights
from `model_path`/`SUPERTONIC_MODEL_PATH` and the `_synthesize_sync` inference
seam is stubbable for tests. `onnxruntime>=1.17` pinned for the extra.
