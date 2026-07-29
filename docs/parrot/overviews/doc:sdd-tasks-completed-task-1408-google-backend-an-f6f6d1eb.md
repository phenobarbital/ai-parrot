---
type: Wiki Overview
title: 'TASK-1408: GoogleTTSBackend (wraps generate_speech) + VoiceSynthesizer (lazy
  backend)'
id: doc:sdd-tasks-completed-task-1408-google-backend-and-synthesizer-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: With the ABC + models in place (TASK-1407), this task implements the default
relates_to:
- concept: mod:parrot.clients.google.generation
  rel: mentions
- concept: mod:parrot.models.google
  rel: mentions
- concept: mod:parrot.models.outputs
  rel: mentions
- concept: mod:parrot.voice.tts.backend
  rel: mentions
- concept: mod:parrot.voice.tts.google_backend
  rel: mentions
- concept: mod:parrot.voice.tts.models
  rel: mentions
- concept: mod:parrot.voice.tts.synthesizer
  rel: mentions
---

# TASK-1408: GoogleTTSBackend (wraps generate_speech) + VoiceSynthesizer (lazy backend)

**Feature**: FEAT-213 — Telegram Voice Reply (TTS Output)
**Spec**: `sdd/specs/FEAT-213-telegram-voice-reply-tts.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1407
**Assigned-to**: unassigned

---

## Context

With the ABC + models in place (TASK-1407), this task implements the default
backend and the service that selects a backend lazily — the output mirror of
`VoiceTranscriber` / `_get_backend`. `GoogleTTSBackend` wraps the **already-existing**
`GoogleGenAIClient.generate_speech(...)`; `VoiceSynthesizer` chooses the backend on
first use and returns audio bytes.

Implements spec **Module 2** (§3) and resolves the §8 open question *"¿Dónde extraer
los bytes de audio del `AIMessage` que devuelve `generate_speech`?"*.

---

## Scope

- Implement `GoogleTTSBackend(AbstractTTSBackend)` in `voice/tts/google_backend.py`:
  - `__init__(self, client: GoogleGenAIClient | None = None, *, voice: str | None = None, **kwargs)`
    — accept an optional injected client (for tests); lazily create one if `None`.
  - `synthesize(...)` builds a `SpeechGenerationPrompt` (single `SpeakerConfig`),
    calls `await self.client.generate_speech(prompt)`, and **extracts the audio bytes
    from the returned `AIMessage.output`** (see Known Gotcha) into a `SynthesisResult`.
- Implement `VoiceSynthesizer` in `voice/tts/synthesizer.py`:
  - `__init__(self, config: TTSConfig | None = None)` (default `TTSConfig()`).
  - `_get_backend()` — lazy, mirrors `VoiceTranscriber._get_backend`; for
    `config.backend == "google"` create `GoogleTTSBackend`; raise `ValueError` for
    `"elevenlabs"`/`"openai"` (not implemented) and unknown backends.
  - `async def synthesize(self, text: str) -> SynthesisResult` — delegate to backend.
  - `async def close(self)` — close the backend if created.
- Unit tests with a **mocked** `GoogleGenAIClient` (no network).

**NOT in scope**:
- ElevenLabs / OpenAI backends (leave `ValueError` stubs only — spec §1 Non-Goals).
- Telegram wiring (TASK-1409).
- OGG/Opus container conversion for Telegram (that concern lives in TASK-1409 / M3).
  Here, return whatever `mime_format` was produced; document it.
- Package `__init__.py` exports (TASK-1410).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/voice/tts/google_backend.py` | CREATE | `GoogleTTSBackend` wrapping `generate_speech` |
| `packages/ai-parrot-integrations/src/parrot/voice/tts/synthesizer.py` | CREATE | `VoiceSynthesizer` lazy backend selection |
| `packages/ai-parrot-integrations/tests/voice/tts/test_google_backend.py` | CREATE | Backend wraps `generate_speech` (client mock) |
| `packages/ai-parrot-integrations/tests/voice/tts/test_synthesizer.py` | CREATE | Lazy backend creation |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references. Use VERBATIM. Verify before adding anything new.

### Verified Imports
```python
from parrot.voice.tts.backend import AbstractTTSBackend          # created in TASK-1407
from parrot.voice.tts.models import TTSConfig, SynthesisResult   # created in TASK-1407
from parrot.clients.google.generation import GoogleGenAIClient   # verified: clients/google/generation.py
from parrot.models.outputs import SpeechGenerationPrompt, SpeakerConfig  # verified: models/outputs.py:237,229
# Optional (only if you validate/normalize the voice id):
from parrot.models.google import TTSVoice                        # verified: models/google.py:60
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/clients/google/generation.py:411
class GoogleGenAIClient:
    async def generate_speech(
        self, prompt_data: SpeechGenerationPrompt,
        model: Union[str, GoogleModel] = GoogleModel.GEMINI_2_5_FLASH_TTS,
        output_directory: Optional[Path] = None, system_prompt: Optional[str] = None,
        temperature: float = 0.7, mime_format: str = "audio/wav",
        user_id=None, session_id=None, max_retries: int = 3,
        retry_delay: float = 1.0,
    ) -> AIMessage:
        # Returns AIMessage built via AIMessageFactory.from_speech(
        #     output=audio_data,  # <-- RAW PCM audio BYTES live in .output
        #     files=saved_file_paths,  # only populated when output_directory is given
        #     input=..., model=..., provider="google_genai", usage=..., ...)

# packages/ai-parrot/src/parrot/models/outputs.py:229
class SpeakerConfig(BaseModel):
    name: str            # e.g. "Narrator"
    voice: str           # prebuilt voice name, e.g. "Kore", "Puck", "Charon", "Zephyr"
    gender: Optional[str] = None

# packages/ai-parrot/src/parrot/models/outputs.py:237
class SpeechGenerationPrompt(BaseModel):
    prompt: str                       # the text to speak (REQUIRED)
    speakers: List[SpeakerConfig]     # REQUIRED — one entry for single voice
    model: Optional[str] = None
    language: Optional[str] = "en-US"

# Backend lazy-create pattern to MIRROR:
# packages/ai-parrot-integrations/src/parrot/voice/transcriber/transcriber.py:64 (__init__)
# packages/ai-parrot-integrations/src/parrot/voice/transcriber/transcriber.py:70 (_get_backend)
```

### Known Gotcha — extracting bytes (resolves spec §8 open question)
`generate_speech` returns an **`AIMessage`**, NOT raw bytes. The audio is packed as
`AIMessageFactory.from_speech(output=audio_data, ...)` at `generation.py:559`, where
`audio_data = self._extract_audio_data(response)` — i.e. **`ai_message.output` holds
the raw PCM audio bytes**. `ai_message.files` is only populated when an
`output_directory` was passed (we do NOT pass one). So:

```python
ai_message = await self.client.generate_speech(prompt)
audio_bytes = ai_message.output          # raw PCM bytes (NOT a WAV/OGG container)
```

Note: it is raw PCM (Gemini TTS → 24kHz mono 16-bit), not a WAV/OGG file. Set
`SynthesisResult.mime_format` to reflect what you actually return (e.g. the
`generate_speech` `mime_format` arg, default `"audio/wav"`). Container wrapping /
OGG conversion for Telegram is M3's responsibility (TASK-1409) — do NOT do it here.
If `ai_message.output` is falsy, raise a clear error (do not return empty bytes).

### Does NOT Exist
- ~~`generate_speech` returns `bytes`~~ — returns `AIMessage`; bytes are in `.output`.
- ~~`AIMessage.audio` / `AIMessage.audio_content`~~ — the bytes live in `.output`.
- ~~`ElevenLabsBackend` / `OpenAITTSBackend`~~ — not implemented; `VoiceSynthesizer`
  raises `ValueError` for those backend values.
- ~~`VoiceBot` (Gemini Live)~~ — NOT used here (spec Non-Goals); use `generate_speech`.

---

## Implementation Notes

### Pattern to Follow
```python
# Mirror VoiceTranscriber._get_backend (transcriber.py:70)
class VoiceSynthesizer:
    def __init__(self, config: TTSConfig | None = None) -> None:
        self.config = config or TTSConfig()
        self.logger = logging.getLogger(__name__)
        self._backend: AbstractTTSBackend | None = None

    def _get_backend(self) -> AbstractTTSBackend:
        if self._backend is None:
            if self.config.backend == "google":
                self._backend = GoogleTTSBackend(voice=self.config.voice)
            elif self.config.backend in ("elevenlabs", "openai"):
                raise ValueError(f"TTS backend not implemented: {self.config.backend}")
            else:
                raise ValueError(f"Unknown TTS backend: {self.config.backend}")
        return self._backend

    async def synthesize(self, text: str) -> SynthesisResult:
        return await self._get_backend().synthesize(
            text, voice=self.config.voice, mime_format=self.config.mime_format
        )
```

### GoogleTTSBackend.synthesize sketch
```python
async def synthesize(self, text, *, voice=None, mime_format="audio/ogg"):
    speaker = SpeakerConfig(name="narrator", voice=voice or "Charon")
    prompt = SpeechGenerationPrompt(prompt=text, speakers=[speaker])
    ai_message = await self.client.generate_speech(prompt)   # AIMessage
    audio_bytes = ai_message.output
    if not audio_bytes:
        raise RuntimeError("generate_speech returned no audio")
    return SynthesisResult(audio=audio_bytes, mime_format=mime_format)
```

### Key Constraints
- async throughout; `self.logger` at key points.
- Inject the client for tests (`GoogleTTSBackend(client=mock_client)`).
- NEVER use `requests`/`httpx`. (Google client uses its own SDK; future backends use aiohttp.)
- Strict type hints, Google-style docstrings.

### References in Codebase
- `voice/transcriber/transcriber.py` — `__init__` + `_get_backend` + `close` to mirror
- `clients/google/generation.py:411` — `generate_speech` (the wrapped call)
- `bots/agent.py:549` — existing `generate_speech` consumer (reads `.output` downstream)

---

## Acceptance Criteria

- [ ] `GoogleTTSBackend.synthesize` calls `generate_speech` and returns a
      `SynthesisResult` whose `.audio` are the bytes from `AIMessage.output` (client mock).
- [ ] `VoiceSynthesizer` creates its backend lazily (no backend until first `synthesize`).
- [ ] `VoiceSynthesizer` raises `ValueError` for `"elevenlabs"`/`"openai"`/unknown backends.
- [ ] Imports work: `from parrot.voice.tts.google_backend import GoogleTTSBackend`,
      `from parrot.voice.tts.synthesizer import VoiceSynthesizer`.
- [ ] Tests pass: `pytest packages/ai-parrot-integrations/tests/voice/tts/ -v`
- [ ] No linting errors: `ruff check packages/ai-parrot-integrations/src/parrot/voice/tts/`

---

## Test Specification

```python
# test_google_backend.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from parrot.voice.tts.google_backend import GoogleTTSBackend


async def test_google_backend_wraps_generate_speech():
    fake_msg = MagicMock()
    fake_msg.output = b"PCM-AUDIO-BYTES"
    client = MagicMock()
    client.generate_speech = AsyncMock(return_value=fake_msg)

    backend = GoogleTTSBackend(client=client)
    result = await backend.synthesize("hola mundo")

    client.generate_speech.assert_awaited_once()
    assert result.audio == b"PCM-AUDIO-BYTES"


# test_synthesizer.py
import pytest
from parrot.voice.tts.models import TTSConfig
from parrot.voice.tts.synthesizer import VoiceSynthesizer


def test_synthesizer_lazy_backend():
    s = VoiceSynthesizer(TTSConfig(backend="google"))
    assert s._backend is None
    b = s._get_backend()
    assert b is not None
    assert s._get_backend() is b  # cached


def test_synthesizer_rejects_unimplemented_backend():
    s = VoiceSynthesizer(TTSConfig(backend="elevenlabs"))
    with pytest.raises(ValueError):
        s._get_backend()
```

---

## Agent Instructions

1. **Read the spec** (§2, §3 Module 2, §8 open question on byte extraction).
2. **Verify the Codebase Contract** — re-confirm `generate_speech` still packs bytes in
   `AIMessage.output` (`grep -n "from_speech" clients/google/generation.py`).
3. **Update status** in `sdd/tasks/index/FEAT-213-telegram-voice-reply-tts.json` → `"in-progress"`.
4. **Implement** per scope; verify TASK-1407 is in `sdd/tasks/completed/` first.
5. **Verify** acceptance criteria.
6. **Move** this file to `sdd/tasks/completed/` and update index → `"done"`.
7. **Fill** the Completion Note.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-06-02
**Notes**: GoogleTTSBackend wraps generate_speech via SpeakerConfig/SpeechGenerationPrompt.
Audio bytes extracted from AIMessage.output as specified. VoiceSynthesizer lazy-creates
the backend on first use and caches it. ValueError raised for unimplemented backends.
27 tests pass total across tts package, ruff clean.
**Deviations from spec**: none
