---
type: Wiki Overview
title: 'TASK-1407: TTS abstraction layer (AbstractTTSBackend) + Pydantic models'
id: doc:sdd-tasks-completed-task-1407-tts-abstraction-and-models-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Mirror of `voice/transcriber/`, but for output. The transcriber package already
relates_to:
- concept: mod:parrot.voice.tts
  rel: mentions
- concept: mod:parrot.voice.tts.backend
  rel: mentions
- concept: mod:parrot.voice.tts.models
  rel: mentions
---

# TASK-1407: TTS abstraction layer (AbstractTTSBackend) + Pydantic models

**Feature**: FEAT-213 — Telegram Voice Reply (TTS Output)
**Spec**: `sdd/specs/FEAT-213-telegram-voice-reply-tts.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Mirror of `voice/transcriber/`, but for output. The transcriber package already
ships an `AbstractTranscriberBackend` ABC + `TranscriptionResult`/`VoiceTranscriberConfig`
Pydantic models. This task creates the symmetric **output** foundation for TTS:
the `AbstractTTSBackend` ABC and the `TTSConfig` / `SynthesisResult` Pydantic
models. No concrete backend yet (that is TASK-1408).

Implements spec **Module 1** (§3) and the public interfaces in §2 ("New Public
Interfaces", `backend.py` + `models.py`).

---

## Scope

- Create the new package directory `voice/tts/` with an empty-ish `__init__.py`
  (real exports land in TASK-1410 — a minimal placeholder docstring is fine here,
  or leave the `__init__.py` creation to TASK-1410 if you prefer; if you create it,
  keep it import-safe).
- Implement `AbstractTTSBackend(ABC)` in `voice/tts/backend.py` with one abstract
  async method `synthesize(text, *, voice=None, mime_format="audio/ogg") -> SynthesisResult`
  and a default no-op `async def close(self) -> None`.
- Implement `TTSConfig` and `SynthesisResult` Pydantic models in `voice/tts/models.py`
  per the spec's Data Models (§2).
- Write unit tests for the models (`test_tts_config_defaults`) and a tiny concrete
  subclass to prove the ABC contract is implementable.

**NOT in scope**:
- `GoogleTTSBackend` or any concrete backend (TASK-1408).
- `VoiceSynthesizer` (TASK-1408).
- Telegram wiring or config fields (TASK-1409).
- Package `__init__.py` public-export wiring (TASK-1410).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/voice/tts/__init__.py` | CREATE | Import-safe package marker (full exports deferred to TASK-1410) |
| `packages/ai-parrot-integrations/src/parrot/voice/tts/backend.py` | CREATE | `AbstractTTSBackend` ABC |
| `packages/ai-parrot-integrations/src/parrot/voice/tts/models.py` | CREATE | `TTSConfig`, `SynthesisResult` |
| `packages/ai-parrot-integrations/tests/voice/tts/__init__.py` | CREATE | Test package marker |
| `packages/ai-parrot-integrations/tests/voice/tts/test_tts_models.py` | CREATE | Model + ABC contract tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references from the actual codebase. Use these VERBATIM.
> If you need something not listed, VERIFY it exists first with `grep`/`read`.

### Verified Imports
```python
from abc import ABC, abstractmethod                 # stdlib
from typing import Literal, Optional                 # stdlib
from pydantic import BaseModel, Field                # pydantic (used across parrot)
```

### Existing Signatures to Mirror (DO NOT import — copy the *shape*)
```python
# packages/ai-parrot-integrations/src/parrot/voice/transcriber/backend.py:18
class AbstractTranscriberBackend(ABC):
    @abstractmethod
    async def transcribe(self, audio_path: Path,
                         language: Optional[str] = None) -> TranscriptionResult: ...  # :39
    async def close(self) -> None:   # default no-op, :77
        pass

# packages/ai-parrot-integrations/src/parrot/voice/transcriber/models.py:28
class VoiceTranscriberConfig(BaseModel):   # Pydantic config model, Field(...) defaults
    enabled: bool = Field(default=...)
    backend: TranscriberBackend = Field(default=...)
    ...
# packages/ai-parrot-integrations/src/parrot/voice/transcriber/models.py:87
class TranscriptionResult(BaseModel):
    text: str; language: str; duration_seconds: float; ...
```

### Target Shapes (from spec §2, build these)
```python
# voice/tts/models.py
class TTSConfig(BaseModel):
    backend: Literal["google", "elevenlabs", "openai"] = "google"
    voice: Optional[str] = None          # backend-specific voice id
    language: Optional[str] = None
    mime_format: str = "audio/ogg"       # Telegram voice notes prefer OGG/Opus

class SynthesisResult(BaseModel):
    audio: bytes
    mime_format: str
    duration_s: Optional[float] = None

# voice/tts/backend.py
class AbstractTTSBackend(ABC):
    @abstractmethod
    async def synthesize(self, text: str, *, voice: str | None = None,
                         mime_format: str = "audio/ogg") -> SynthesisResult: ...
    async def close(self) -> None: ...   # default no-op
```

### Does NOT Exist
- ~~`parrot.voice.tts`~~ — created by THIS task.
- ~~`AbstractTTSBackend`, `TTSConfig`, `SynthesisResult`~~ — do not exist; create them.
- ~~`SynthesisResult` is NOT `TranscriptionResult`~~ — different package, different fields
  (`audio: bytes`, not `text: str`).
- Pydantic `bytes` field is valid — do NOT base64-encode it in the model.

---

## Implementation Notes

### Pattern to Follow
Read `voice/transcriber/backend.py` and `voice/transcriber/models.py` and mirror
their style exactly: module docstring referencing FEAT-213, Google-style docstrings
on the abstract method (document `Args`, `Returns`, `Raises`), `Field(..., description=...)`
on every model field, and a default no-op `close()`.

### Key Constraints
- `synthesize` is `async` and abstract.
- Use Pydantic `BaseModel` for both models. `audio: bytes` is fine as a raw bytes field.
- Keyword-only args after `text` (note the `*,` in the signature).
- No I/O, no provider SDKs in this task — pure abstraction + models.
- PEP 8, strict type hints, Google-style docstrings (CLAUDE.md rules).

### References in Codebase
- `packages/ai-parrot-integrations/src/parrot/voice/transcriber/backend.py` — ABC pattern to mirror
- `packages/ai-parrot-integrations/src/parrot/voice/transcriber/models.py` — Pydantic model style

---

## Acceptance Criteria

- [ ] `AbstractTTSBackend` is an ABC with abstract async `synthesize(...)` and default `close()`.
- [ ] `TTSConfig` defaults: `backend="google"`, `mime_format="audio/ogg"`; `voice`/`language` optional.
- [ ] `SynthesisResult` carries `audio: bytes`, `mime_format: str`, optional `duration_s`.
- [ ] Imports work: `from parrot.voice.tts.backend import AbstractTTSBackend` and
      `from parrot.voice.tts.models import TTSConfig, SynthesisResult`.
- [ ] All tests pass: `pytest packages/ai-parrot-integrations/tests/voice/tts/test_tts_models.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot-integrations/src/parrot/voice/tts/`

---

## Test Specification

```python
# packages/ai-parrot-integrations/tests/voice/tts/test_tts_models.py
import pytest
from parrot.voice.tts.backend import AbstractTTSBackend
from parrot.voice.tts.models import TTSConfig, SynthesisResult


def test_tts_config_defaults():
    cfg = TTSConfig()
    assert cfg.backend == "google"
    assert cfg.mime_format == "audio/ogg"
    assert cfg.voice is None
    assert cfg.language is None


def test_synthesis_result_holds_bytes():
    r = SynthesisResult(audio=b"OGG...", mime_format="audio/ogg")
    assert r.audio == b"OGG..."
    assert r.duration_s is None


def test_abstract_backend_cannot_instantiate():
    with pytest.raises(TypeError):
        AbstractTTSBackend()  # abstract method not implemented


async def test_concrete_backend_contract():
    class _Stub(AbstractTTSBackend):
        async def synthesize(self, text, *, voice=None, mime_format="audio/ogg"):
            return SynthesisResult(audio=b"x", mime_format=mime_format)

    b = _Stub()
    res = await b.synthesize("hola")
    assert res.audio == b"x"
    await b.close()  # default no-op must not raise
```

---

## Agent Instructions

When you pick up this task:
1. **Read the spec** for full context (§2 Data Models / New Public Interfaces, §3 Module 1).
2. **Verify the Codebase Contract** — confirm the transcriber mirror files still match.
3. **Update status** in `sdd/tasks/index/FEAT-213-telegram-voice-reply-tts.json` → `"in-progress"`.
4. **Implement** per scope.
5. **Verify** acceptance criteria.
6. **Move** this file to `sdd/tasks/completed/`.
7. **Update index** → `"done"` and fill the Completion Note.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-06-02
**Notes**: Created all 5 files as specified. AbstractTTSBackend mirrors
AbstractTranscriberBackend exactly. TTSConfig and SynthesisResult use
Pydantic v2 BaseModel with Field descriptions. All 9 tests pass, ruff clean.
**Deviations from spec**: none
