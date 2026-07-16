---
type: Wiki Overview
title: 'Feature Specification: LiveKit Native Voice Adapters (AI-Parrot own STT/TTS
  for Phase C)'
id: doc:sdd-specs-livekit-native-voice-adapters-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: LiveAvatar Phase C (FEAT-243, "Option C" — voice-native hybrid with ai-parrot
relates_to:
- concept: mod:parrot.integrations.liveavatar
  rel: mentions
- concept: mod:parrot.voice.transcriber
  rel: mentions
- concept: mod:parrot.voice.transcriber.moonshine_backend
  rel: mentions
- concept: mod:parrot.voice.tts.supertonic_inference
  rel: mentions
---

---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: LiveKit Native Voice Adapters (AI-Parrot own STT/TTS for Phase C)

**Feature ID**: FEAT-246
**Date**: 2026-06-18
**Author**: Jesús Lara (design w/ Claude)
**Status**: approved
**Target version**: (next minor)

---

## 1. Motivation & Business Requirements

### Problem Statement

LiveAvatar Phase C (FEAT-243, "Option C" — voice-native hybrid with ai-parrot
as the brain) was built on top of the LiveKit Agents starter voice pipeline,
whose **default STT/TTS components are third-party plugins**: Deepgram
(`nova-3`) for STT and Cartesia for TTS (`pipeline.py:_default_stt` / `_default_tts`).
This contradicts two project goals and a practical constraint:

1. **Pluggable voice, no vendor lock-in** — the explicit project goal stated in
   the LiveAvatar brainstorm ("opposite of our pluggable goal" was listed as a
   con of vendor-locked options).
2. **Reuse the Phase A investment** — FEAT-242 already ships a working TTS
   (`SupertonicPipeline`) and the project already ships a working STT stack
   (`VoiceTranscriber` with faster-whisper / moonshine / OpenAI backends). Phase C
   ignores all of it.
3. **Cost & operability** — Deepgram + Cartesia require separate accounts and
   per-minute billing. The deployment currently has **no** `DEEPGRAM_API_KEY` /
   `CARTESIA_API_KEY`, so a Phase C turn crashes at `build_session()` even though
   the worker registers with LiveKit.

The fix is to expose AI-Parrot's own voice infra **as LiveKit Agents
components** so Phase C can run entirely on our stack (local faster-whisper /
moonshine STT + Supertonic TTS), with the third-party plugins demoted to
opt-in alternatives.

### Goals
- Provide a `SupertonicTTS` class implementing `livekit.agents.tts.TTS` that
  voices ai-parrot replies through the existing `SupertonicPipeline`.
- Provide `WhisperSTT` and `MoonshineSTT` classes implementing
  `livekit.agents.stt.STT` (non-streaming) that transcribe user speech through
  the existing `VoiceTranscriber` backends, segmented by VAD via
  `stt.StreamAdapter`.
- Make the Phase C pipeline **provider-selectable by env**, defaulting to our
  own stack (Supertonic + faster-whisper), with Deepgram / Cartesia /
  LiveKit-inference kept as alternative options (no regression for anyone who
  prefers them).
- Zero third-party per-minute STT/TTS cost in the default configuration.

### Non-Goals (explicitly out of scope)
- Re-architecting Phase C's turn-taking, OutputBridge, or worker process model
  (FEAT-243 owns those; this feature only swaps the STT/TTS components).
- LiveAvatar FULL Mode / "their end-to-end STT→TTS" — that is a separate,
  parallel effort (FEAT-247, ex-"Option B" of the brainstorm). This spec stays
  inside Option C.
- A true *streaming* STT. Our transcriber backends are file/segment based; we
  wrap them as **non-streaming** `STT` and rely on VAD segmentation. Native
  streaming STT (incremental partials) is a possible later enhancement.
- Replacing the Phase A "mouth" (`AvatarVoiceProvider` / `AvatarTurnSpeaker`).
  Those stay; this feature may *reuse* their Supertonic synth+resample helper.

---

## 2. Architectural Design

### Overview

LiveKit's `AgentSession` accepts any `stt.STT` / `tts.TTS` implementation —
`build_session(vad, *, stt=, tts=, ...)` already takes injectable components.
Deepgram/Cartesia are defaults only because they ship as ready-made plugins.
This feature adds three adapter classes that wrap our existing infra behind the
LiveKit interfaces, plus an env-driven factory that selects the provider.

- **TTS path**: `llm_node` yields speakable sentences → `SupertonicTTS.synthesize(text)`
  returns a `ChunkedStream` of audio frames produced by `SupertonicPipeline.synthesize_pcm`
  (native 44.1 kHz; LiveKit handles resampling to the room/avatar rate, so the
  adapter declares its native `sample_rate` honestly).
- **STT path**: the user's mic audio is buffered by `stt.StreamAdapter` using the
  prewarmed Silero VAD; on each detected utterance the adapter hands a complete
  PCM segment to `WhisperSTT`/`MoonshineSTT`, which writes it to a temp WAV and
  calls the existing `AbstractTranscriberBackend.transcribe(path)` →
  `TranscriptionResult` → emitted as a final `stt.SpeechEvent`.

Provider selection is env-driven (`LIVEAVATAR_STT_PROVIDER`,
`LIVEAVATAR_TTS_PROVIDER`), defaulting to `whisper` + `supertonic`.

### Component Diagram
```
                      build_session(vad)   [worker.entrypoint]
                              │
         ┌────────────────────┼─────────────────────┐
         ▼                    ▼                     ▼
  resolve_stt(env)      resolve_tts(env)      turn_detection (unchanged)
         │                    │
   whisper|moonshine    supertonic|cartesia|inference
         │                    │
  stt.StreamAdapter(     SupertonicTTS(tts.TTS)
    stt=WhisperSTT,           │
    vad=vad)            SupertonicPipeline.synthesize_pcm()
         │
  WhisperSTT(stt.STT, streaming=False)
         │
  VoiceTranscriber / FasterWhisperBackend.transcribe(Path) → TranscriptionResult
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `livekit.agents.stt.STT` / `stt.StreamAdapter` | implements / wraps | New `WhisperSTT`, `MoonshineSTT` are non-streaming `STT`; `StreamAdapter` adds VAD segmentation |
| `livekit.agents.tts.TTS` / `tts.ChunkedStream` | implements | New `SupertonicTTS` |
| `SupertonicPipeline` (`voice/tts/supertonic_inference.py`) | uses | `synthesize_pcm()` for TTS audio (reuse FEAT-242) |
| `AbstractTranscriberBackend` (`voice/transcriber/backend.py`) | uses | `transcribe(Path)` for STT |
| `pipeline.build_session()` / `worker.entrypoint` (FEAT-243) | modifies | `_default_stt`/`_default_tts` become env-driven `resolve_stt`/`resolve_tts` |
| `AvatarVoiceProvider` (`liveavatar/voice_provider.py`) | reuses (optional) | Its off-thread synth + 44.1→target resample helper can back `SupertonicTTS` |

### Data Models
```python
# Provider selection (string enums kept simple; read from env)
# LIVEAVATAR_STT_PROVIDER ∈ {"whisper", "moonshine", "deepgram", "openai"}   default "whisper"
# LIVEAVATAR_TTS_PROVIDER ∈ {"supertonic", "cartesia", "inference"}          default "supertonic"
```

### New Public Interfaces
```python
# parrot/integrations/liveavatar/livekit_agent/voice_adapters.py
class SupertonicTTS(tts.TTS):
    def __init__(self, *, pipeline: SupertonicPipeline | None = None,
                 voice: str | None = None, language: str | None = None) -> None: ...
    def synthesize(self, text: str, *, conn_options=...) -> tts.ChunkedStream: ...

class _TranscriberSTT(stt.STT):   # shared base: buffer PCM → WAV → backend.transcribe
    def __init__(self, backend: AbstractTranscriberBackend, *, language: str | None = None) -> None: ...
    async def _recognize_impl(self, buffer, *, language=None, conn_options=...) -> stt.SpeechEvent: ...

class WhisperSTT(_TranscriberSTT): ...    # FasterWhisperBackend
class MoonshineSTT(_TranscriberSTT): ...   # MoonshineSTTBackend

# Factory wired into the pipeline:
def resolve_stt(vad) -> stt.STT: ...       # returns StreamAdapter(stt=..., vad=vad) for non-streaming
def resolve_tts() -> tts.TTS: ...
```

---

## 3. Module Breakdown

### Module 1: SupertonicTTS adapter
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/livekit_agent/voice_adapters.py`
- **Responsibility**: Implement `tts.TTS` over `SupertonicPipeline.synthesize_pcm`.
  Declare correct `TTSCapabilities` (streaming=False, non-aligned) and the native
  `sample_rate`. Emit audio frames via a `ChunkedStream`. Synthesis runs in a
  worker thread (`asyncio.to_thread`) — never block the event loop. Optionally
  delegate to the existing `AvatarVoiceProvider` synth helper to avoid duplicating
  the Supertonic load + resample logic.
- **Depends on**: `SupertonicPipeline` (existing), livekit `tts` (extra).

### Module 2: Transcriber STT adapters (Whisper + Moonshine)
- **Path**: same module (`voice_adapters.py`).
- **Responsibility**: A shared `_TranscriberSTT(stt.STT)` base with
  `capabilities.streaming = False` that, in `_recognize_impl`, materialises the
  buffered `AudioBuffer` to a temp WAV (16-bit mono) and calls
  `AbstractTranscriberBackend.transcribe(path, language)`, mapping
  `TranscriptionResult.text`/`.language` into a final `stt.SpeechEvent`. Concrete
  `WhisperSTT` (FasterWhisperBackend) and `MoonshineSTT` (MoonshineSTTBackend)
  subclasses wire the backend. Temp files are always unlinked. Errors degrade to
  an empty transcript (logged), never crash the session.
- **Depends on**: `AbstractTranscriberBackend` + concrete backends (existing),
  livekit `stt` (extra).

### Module 3: Env-driven provider factory + pipeline/worker wiring
- **Path**: `.../liveavatar/livekit_agent/pipeline.py` (modify), and the same
  `voice_adapters.py` for `resolve_stt` / `resolve_tts`.
- **Responsibility**: Replace `_default_stt`/`_default_tts` with `resolve_stt(vad)`
  / `resolve_tts()` that dispatch on `LIVEAVATAR_STT_PROVIDER` /
  `LIVEAVATAR_TTS_PROVIDER` (defaults `whisper` + `supertonic`). Non-streaming STT
  is wrapped in `stt.StreamAdapter(stt=..., vad=vad)`. Keep Deepgram/Cartesia/
  inference branches intact as alternatives. `build_session` signature stays
  backward-compatible (explicit `stt=`/`tts=` overrides still win). `worker.entrypoint`
  passes the prewarmed VAD into STT resolution.
- **Depends on**: Modules 1 & 2.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_supertonic_tts_emits_frames` | M1 | `synthesize()` yields audio frames; sample_rate matches pipeline; synth runs off-thread (fake pipeline) |
| `test_supertonic_tts_blank_text` | M1 | Empty/whitespace text → no frames, no error |
| `test_transcriber_stt_recognize` | M2 | `_recognize_impl` writes WAV, calls fake backend, returns final `SpeechEvent` with transcript text |
| `test_transcriber_stt_tempfile_cleanup` | M2 | Temp WAV is unlinked even when backend raises |
| `test_transcriber_stt_error_degrades` | M2 | Backend error → empty transcript event, logged, no exception |
| `test_whisper_and_moonshine_select_backend` | M2 | Each subclass instantiates its expected backend |
| `test_resolve_stt_default_whisper` | M3 | No env → `StreamAdapter` wrapping `WhisperSTT` |
| `test_resolve_tts_default_supertonic` | M3 | No env → `SupertonicTTS` |
| `test_resolve_providers_env_override` | M3 | `LIVEAVATAR_*_PROVIDER` selects deepgram/cartesia/moonshine/inference branches |
| `test_build_session_uses_resolved_components` | M3 | `build_session(vad)` wires resolved stt/tts; explicit overrides still win |

### Integration Tests
| Test | Description |
|---|---|
| `test_phase_c_roundtrip_own_stack_sandbox` | mic PCM → VAD → WhisperSTT → `llm_node`→ai-parrot → SupertonicTTS → avatar; `is_sandbox=true`. Requires the `liveavatar-voice` + `voice-supertonic` extras and a live room (mark as integration, not unit). |

### Test Data / Fixtures
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

---

## 5. Acceptance Criteria

- [ ] `SupertonicTTS`, `WhisperSTT`, `MoonshineSTT` implement the respective
      LiveKit interfaces and are importable from
      `parrot.integrations.liveavatar.livekit_agent.voice_adapters`.
- [ ] With no `LIVEAVATAR_*_PROVIDER` env set, `build_session(vad)` uses
      faster-whisper STT + Supertonic TTS — **no Deepgram/Cartesia keys required**.
- [ ] `LIVEAVATAR_STT_PROVIDER` / `LIVEAVATAR_TTS_PROVIDER` select alternatives
      (whisper|moonshine|deepgram|openai / supertonic|cartesia|inference) without
      code changes.
- [ ] STT adapters run **non-streaming** under `stt.StreamAdapter` + the
      prewarmed Silero VAD; temp audio files are always cleaned up.
- [ ] All synthesis/transcription runs off the event loop (`asyncio.to_thread`
      or equivalent); no blocking I/O in async contexts.
- [ ] Backend/synth failures degrade gracefully (logged, empty result) and never
      crash the AgentSession.
- [ ] All new unit tests pass; existing FEAT-243 tests stay green (no signature
      break in `build_session`).
- [ ] Frontend/operator docs updated: which env vars select providers, and that
      our stack is the default.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** Re-verify before use.

### Verified Imports
```python
# verified at livekit-agents 1.6.1 (installed):
from livekit.agents import stt, tts            # stt.STT, stt.StreamAdapter, stt.SpeechEvent,
                                               # stt.STTCapabilities, tts.TTS, tts.ChunkedStream,
                                               # tts.TTSCapabilities — all present (verified)
# verified: packages/ai-parrot-integrations/src/parrot/voice/transcriber/__init__.py:14-22
from parrot.voice.transcriber import (
    AbstractTranscriberBackend,                # backend.py:18
    FasterWhisperBackend,                      # faster_whisper_backend.py:21
    VoiceTranscriber,                          # transcriber.py:30
)
# NOTE: MoonshineSTTBackend is NOT exported by the package __init__; import directly:
from parrot.voice.transcriber.moonshine_backend import MoonshineSTTBackend  # moonshine_backend.py:38
# verified: packages/ai-parrot-integrations/src/parrot/voice/tts/supertonic_inference.py:335
from parrot.voice.tts.supertonic_inference import SupertonicPipeline
# reuse candidate (FEAT-242): voice_provider.py
from parrot.integrations.liveavatar import AvatarVoiceProvider  # liveavatar/__init__.py
```

### Existing Class Signatures
```python
# voice/transcriber/backend.py
class AbstractTranscriberBackend(ABC):
    @abstractmethod
    async def transcribe(self, audio_path: Path, language: Optional[str] = None) -> TranscriptionResult:  # :38
    async def close(self) -> None: ...  # :77 (default no-op)

# voice/transcriber/faster_whisper_backend.py
class FasterWhisperBackend(AbstractTranscriberBackend):  # :21
    def __init__(self, ...):  # :47

# voice/transcriber/moonshine_backend.py
class MoonshineSTTBackend(AbstractTranscriberBackend):  # :38
    def __init__(self, model_name: str = _DEFAULT_MODEL, **kwargs) -> None:  # :63

# voice/tts/supertonic_inference.py
class SupertonicPipeline:  # :335
    def __init__(self, ...):  # :363  (loads ONNX graphs; resolve model dir)
    sample_rate: int  # :391  (read from cfg["ae"]["sample_rate"], ~44100)
    def synthesize_pcm(self, text, *, voice=None, language=None, sample_rate=None) -> bytes  # docstring :341

# liveavatar/livekit_agent/pipeline.py  (FEAT-243 — to modify)
def _default_stt() -> Any: ...   # :32  (deepgram.STT) → becomes resolve_stt(vad)
def _default_tts() -> Any: ...   # :44  (cartesia.TTS) → becomes resolve_tts()
def build_session(vad, *, stt=None, tts=None, turn_detection=None, session_factory=None) -> Any:  # :80

# liveavatar/livekit_agent/worker.py  (FEAT-243 — to modify)
async def entrypoint(ctx):  # :247  calls build_session(_vad_from_proc(ctx))  # :279
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `SupertonicTTS` | `SupertonicPipeline.synthesize_pcm()` | call (off-thread) | `supertonic_inference.py:341` |
| `WhisperSTT` | `FasterWhisperBackend.transcribe()` | call on temp WAV | `backend.py:38` |
| `MoonshineSTT` | `MoonshineSTTBackend.transcribe()` | call on temp WAV | `moonshine_backend.py:38` |
| `resolve_stt/tts` | `build_session()` | replaces `_default_*` | `pipeline.py:32,44,80` |
| `entrypoint` | `resolve_stt(vad)` | pass prewarmed VAD | `worker.py:279` |

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.voice.transcriber.MoonshineSTTBackend`~~ — class exists but is **not**
  exported by the package `__init__`; import from `...moonshine_backend`.
- ~~A streaming STT backend in `parrot.voice.transcriber`~~ — all backends are
  file/segment based (`transcribe(Path)`); there is no incremental/streaming API.
- ~~`SupertonicPipeline.stream()` / async synth~~ — synthesis is sync (`synthesize_pcm`);
  wrap with `asyncio.to_thread`.
- ~~Env switch for STT/TTS provider in Phase C today~~ — `pipeline.py` hardcodes
  Deepgram/Cartesia; this feature introduces `LIVEAVATAR_STT_PROVIDER` /
  `LIVEAVATAR_TTS_PROVIDER`.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Async-first: all model inference via `asyncio.to_thread`; no blocking calls in
  coroutines (CLAUDE.md non-negotiable).
- Lazy imports of the `liveavatar-voice` extra inside factory branches so the
  module imports without livekit installed (mirror existing `pipeline.py`).
- Google-style docstrings + strict type hints; `self.logger` not `print`.
- Graceful degradation mirrors FEAT-242/243: voice errors are logged and
  skipped, never fatal to the turn.

### Known Risks / Gotchas
- **Latency**: non-streaming STT waits for utterance end (VAD) before
  transcribing — higher TTFB than Deepgram streaming. Acceptable for v1; document
  it. faster-whisper model size (`tiny`/`base`/`small`) trades latency vs accuracy.
- **Sample-rate**: Supertonic is 44.1 kHz native; declare it honestly in
  `TTSCapabilities` and let LiveKit resample. Do NOT hardcode 24 kHz here (that
  24 kHz constant is the Phase A *avatar_ws* contract, not the LiveKit room).
- **Per-process model load**: faster-whisper / Supertonic load is heavy; load
  once per worker process (consider prewarm into `ctx.proc.userdata`, like the VAD).
- **AudioBuffer→WAV**: confirm the exact `stt._recognize_impl` buffer type and the
  WAV encoding helper in livekit-agents 1.6.1 at implementation time.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `livekit-agents` | `~=1.6` (installed 1.6.1) | `stt.STT`/`tts.TTS` base classes + `StreamAdapter` |
| `faster-whisper` | existing extra | default STT backend |
| `useful-moonshine` (or current moonshine dep) | existing | alt STT backend |
| Supertonic (`voice-supertonic` extra) | existing | default TTS |

---

## 8. Open Questions

- [x] Should faster-whisper / Supertonic be **prewarmed per worker process**
      (into `ctx.proc.userdata`, like the Silero VAD) to avoid first-turn load
      latency? — *Owner: Jesús* (recommend yes; can defer to a follow-up): yes
- [x] Default faster-whisper model size for the avatar use case
      (`base` vs `small`)? — *Owner: Jesús* (latency/accuracy tradeoff): start with small by default
- [x] Do we also expose `OpenAIWhisperBackend` as an STT option here, or keep it
      out until needed? — *Owner: Jesús*: exponse as option

---

## Worktree Strategy

- **Isolation unit**: `per-spec` (sequential tasks in one worktree). Modules are
  small and share `voice_adapters.py`; M3 depends on M1+M2, so parallelism buys
  little.
- **Cross-feature dependencies**: builds on FEAT-243 (already merged in `dev`).
  Independent of FEAT-247 (ex-Option B). The uncommitted FEAT-242 "mouth" WIP in
  the working tree is unrelated; do not depend on it.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-06-18 | Jesús Lara (w/ Claude) | Initial draft — own STT/TTS LiveKit adapters for Phase C |
