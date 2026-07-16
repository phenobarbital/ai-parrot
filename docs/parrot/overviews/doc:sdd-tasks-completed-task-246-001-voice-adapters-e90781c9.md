---
type: Wiki Overview
title: 'TASK-246-001: Implement voice_adapters.py — SupertonicTTS, _TranscriberSTT,
  WhisperSTT, MoonshineSTT'
id: doc:sdd-tasks-completed-task-246-001-voice-adapters-module-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: FEAT-246 — expose AI-Parrot's own voice infra (SupertonicPipeline TTS and
relates_to:
- concept: mod:parrot.voice.transcriber
  rel: mentions
- concept: mod:parrot.voice.transcriber.moonshine_backend
  rel: mentions
- concept: mod:parrot.voice.tts.supertonic_inference
  rel: mentions
---

# TASK-246-001: Implement voice_adapters.py — SupertonicTTS, _TranscriberSTT, WhisperSTT, MoonshineSTT

**Feature**: livekit-native-voice-adapters
**Spec**: sdd/specs/livekit-native-voice-adapters.spec.md
**Status**: [ ] pending | [ ] in-progress | [ ] done
**Priority**: high
**Depends-on**: none
**Assigned-to**: unassigned

## Context

FEAT-246 — expose AI-Parrot's own voice infra (SupertonicPipeline TTS and
AbstractTranscriberBackend STT) as LiveKit Agents components. This task
creates the `voice_adapters.py` module with the adapter classes. Module 3
(factory + pipeline wiring) is TASK-246-002 and depends on this task.

## Scope

Create `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/livekit_agent/voice_adapters.py`
with the following classes:

1. `SupertonicTTS(tts.TTS)` — wraps `SupertonicPipeline.synthesize_pcm` behind
   the `tts.TTS` interface. `TTSCapabilities(streaming=False)`. Native sample_rate
   from the pipeline (declared honestly — 44100 Hz; LiveKit handles resampling).
   `synthesize(text)` returns a `ChunkedStream` subclass. Synthesis runs in
   `asyncio.to_thread` — never block the event loop. Lazy pipeline init (build
   on first call). Handles blank text gracefully (yields no frames, no error).

2. `_TranscriberSTT(stt.STT)` — shared base with `STTCapabilities(streaming=False,
   interim_results=False)`. `_recognize_impl(buffer, *, language, conn_options)`
   materialises the `AudioBuffer` to a temp WAV (16-bit mono, using `combine_frames`
   to merge frames if needed), calls `AbstractTranscriberBackend.transcribe(path,
   language)`, maps `TranscriptionResult` → `SpeechEvent(type=FINAL_TRANSCRIPT,
   alternatives=[SpeechData(language=..., text=...)])`. Temp files ALWAYS unlinked
   even when backend raises. Errors degrade gracefully (empty SpeechEvent, logged).

3. `WhisperSTT(_TranscriberSTT)` — concrete subclass using `FasterWhisperBackend`.
   Default model_size `"small"` (per spec open question resolved: start with small).

4. `MoonshineSTT(_TranscriberSTT)` — concrete subclass using `MoonshineSTTBackend`.

## Files to Create

- `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/livekit_agent/voice_adapters.py`

## Files to Modify

None.

## Implementation Notes

- Use `from livekit.agents import stt, tts` (verified in spec).
- AudioBuffer is `list[AudioFrame] | AudioFrame` — use `livekit.agents.utils.combine_frames`
  to merge to a single frame, then write WAV via `wave` module (16-bit signed int,
  mono, sample_rate from frame).
- SupertonicTTS: the `ChunkedStream` subclass must override `_run(output_emitter)`.
  Call `output_emitter.initialize(request_id=..., sample_rate=..., num_channels=1,
  mime_type="audio/pcm")` then `output_emitter.push(pcm_bytes)` then
  `output_emitter.flush()`.
- SupertonicTTS: lazy pipeline — accept `pipeline: SupertonicPipeline | None = None`
  in `__init__`; if None, it MUST be provided by caller (no auto-build here, to
  avoid triggering ONNX load at import time). Caller (factory in TASK-246-002) is
  responsible for building/passing the pipeline.
- All imports of `livekit.*` are inside methods or at module level with try/except
  so the module is importable without the liveavatar-voice extra (mirror pipeline.py).
- Google-style docstrings + strict type hints. `self.logger` not `print`.
- Import `MoonshineSTTBackend` directly: `from parrot.voice.transcriber.moonshine_backend import MoonshineSTTBackend`.
- AudioEmitter.flush() — look up the correct method to signal end-of-stream. Based
  on the AudioEmitter API it is `flush()` for non-streaming (no `end_segment`).

## Codebase Contract

### Verified Imports
```python
from livekit.agents import stt, tts              # present at 1.6.1
from livekit.agents.utils import combine_frames  # livekit.agents.utils.combine_frames
from livekit.rtc import AudioFrame               # data is int16 bytes
from parrot.voice.transcriber import AbstractTranscriberBackend, FasterWhisperBackend
from parrot.voice.transcriber.moonshine_backend import MoonshineSTTBackend
from parrot.voice.tts.supertonic_inference import SupertonicPipeline
```

### Existing Signatures
- `tts.TTS.__init__(*, capabilities, sample_rate, num_channels)` — call super().__init__
- `tts.TTSCapabilities(streaming: bool, aligned_transcript: bool = False)`
- `tts.ChunkedStream.__init__(*, tts, input_text, conn_options)` — abstract `_run(output_emitter)`
- `tts.AudioEmitter.initialize(*, request_id, sample_rate, num_channels, mime_type, frame_size_ms=200, stream=False)`
- `tts.AudioEmitter.push(data: bytes)` — pushes PCM bytes
- `tts.AudioEmitter.flush()` — end current segment for non-streaming
- `stt.STT.__init__(*, capabilities: STTCapabilities)` — call super().__init__
- `stt.STTCapabilities(streaming: bool, interim_results: bool)`
- `stt.SpeechEvent(type, request_id, alternatives)`
- `stt.SpeechData(language, text, confidence)`
- `stt.SpeechEventType.FINAL_TRANSCRIPT`
- `SupertonicPipeline.sample_rate: int` — native sample rate (44100)
- `SupertonicPipeline.synthesize_pcm(text, *, voice=None, language=None) -> bytes`
- `AbstractTranscriberBackend.transcribe(audio_path: Path, language: Optional[str]) -> TranscriptionResult`
- `TranscriptionResult.text: str`, `.language: str`
- `combine_frames` is actually `livekit.agents.utils.combine_audio_frames` (the public name exposed as `combine_frames` is an alias — verify the exact name at implementation time)

## Acceptance Criteria

- [ ] `SupertonicTTS`, `WhisperSTT`, `MoonshineSTT` are importable from `voice_adapters.py`
- [ ] `SupertonicTTS.synthesize("hello")` returns a `ChunkedStream` (with fake pipeline)
- [ ] Blank text `synthesize("")` yields no frames and raises no error
- [ ] `WhisperSTT._recognize_impl(buffer)` returns a final `SpeechEvent` (with fake backend)
- [ ] Temp WAV is unlinked even when backend raises
- [ ] Backend error → empty transcript event, logged, no exception

## Completion Note
(Agent fills this in when done)

## Completion Note

Implemented `voice_adapters.py` with all four classes. Key design decisions:

- `SupertonicTTS` and `_TranscriberSTT` use a `__new__`-based lazy class
  construction pattern so `livekit-agents` is imported only when actually
  instantiated (mirror pipeline.py's lazy approach for plugins).
- `_SupertonicChunkedStream._run` calls `asyncio.to_thread(synthesize_pcm)` +
  `output_emitter.initialize / push / flush`.
- `_TranscriberSTT._recognize_impl` uses `lk_utils.combine_frames` (the
  `combine_frames` alias in `livekit.agents.utils`) to merge AudioFrame lists.
- Blank text returns early after `output_emitter.initialize` without pushing.
- Temp WAV always unlinked in `finally` block.
- `resolve_stt` and `resolve_tts` added to same file (TASK-246-002 adds
  pipeline.py wiring).
- ruff passes clean.
