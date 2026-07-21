---
type: Wiki Overview
title: 'TASK-1463: AudioFormWSHandler — WebSocket Handler'
id: doc:sdd-tasks-completed-task-1463-audio-ws-handler-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The stateful WebSocket handler that manages the interactive audio form session.
relates_to:
- concept: mod:parrot.voice.handler
  rel: mentions
- concept: mod:parrot.voice.transcriber.faster_whisper_backend
  rel: mentions
- concept: mod:parrot.voice.tts.models
  rel: mentions
- concept: mod:parrot.voice.tts.synthesizer
  rel: mentions
---

# TASK-1463: AudioFormWSHandler — WebSocket Handler

**Feature**: FEAT-224 — FormDesigner Audio Renderer
**Spec**: `sdd/specs/formdesigner-audio-renderer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: XL (> 8h)
**Depends-on**: TASK-1460, TASK-1462
**Assigned-to**: unassigned

---

## Context

The stateful WebSocket handler that manages the interactive audio form session.
This is the largest and most complex task — it handles JWT auth, question
delivery with TTS audio, answer collection (text + audio binary), STT
transcription, validation, navigation (back/skip/repeat), and final form
submission. Implements Spec §3 Module 5.

---

## Scope

- Create `AudioFormWSHandler` class in `api/audio_ws.py`.
- Implement `handle_websocket(request) -> web.WebSocketResponse`:
  - JWT authentication via `TokenValidator` on connection.
  - `start_session` → load `FormSchema`, build `AudioFormManifest`, send first question.
  - `answer_text` → validate, store, advance to next question.
  - `answer_audio` (binary frame) → write to temp file, transcribe via
    `FasterWhisperBackend`, send `transcription` message, validate, store.
  - `skip_question` → skip if optional, reject if required.
  - `go_back` → navigate to previous question.
  - `repeat_question` → re-send TTS audio for current question.
  - `end_session` → abort and cleanup.
  - `ping` / `pong` → keep-alive.
  - After last question answered → submit form data and send `form_complete`.
- Manage `AudioSessionState` per connection.
- Proper cleanup on disconnect (temp files, session state).
- Write unit tests with mocked TTS/STT and WebSocket.

**NOT in scope**: Route registration (TASK-1464), frontend client code.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/audio_ws.py` | CREATE | WebSocket handler |
| `tests/formdesigner/test_audio_ws_handler.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# aiohttp WebSocket
from aiohttp import web, WSMsgType  # verified: voice/handler.py:31

# Auth
from parrot.voice.handler import TokenValidator, AuthenticatedUser  # verified: voice/handler.py:59,49

# Voice services
from parrot.voice.tts.synthesizer import VoiceSynthesizer  # verified: voice/tts/synthesizer.py:21
from parrot.voice.tts.models import TTSConfig, SynthesisResult  # verified: voice/tts/synthesizer.py:18
from parrot.voice.transcriber.faster_whisper_backend import FasterWhisperBackend  # verified: voice/transcriber/faster_whisper_backend.py:21
# TranscriptionResult has .text, .language, .confidence, .processing_time_ms

# Form services
from parrot_formdesigner.services.registry import FormRegistry  # verified: api/handlers.py:25
from parrot_formdesigner.services.validators import FormValidator  # verified: api/handlers.py:26

# Audio models (TASK-1460)
from parrot_formdesigner.audio.models import (
    AudioFormManifest, AudioQuestion, AudioAnswer,
    AudioSessionConfig, AudioSessionState,
)

# Audio renderer (TASK-1462)
from parrot_formdesigner.renderers.audio import AudioFormRenderer
```

### Existing Signatures to Use
```python
# parrot.voice.handler:59
class TokenValidator:
    def __init__(self, *, secret_key=None, algorithm="HS256",
                 validator_func=None, allow_anonymous=False): ...
    # has async validate(token: str) -> dict or raises

# parrot.voice.tts.synthesizer:21
class VoiceSynthesizer:
    async def synthesize(self, text: str, *, language: Optional[str] = None) -> SynthesisResult: ...
    async def close(self) -> None: ...

# parrot.voice.transcriber.faster_whisper_backend:21
class FasterWhisperBackend:
    def __init__(self, model_size="small", device="cuda", compute_type="float16"): ...
    async def transcribe(self, audio_path: Path, language: Optional[str] = None) -> TranscriptionResult: ...
    async def close(self) -> None: ...
    # CRITICAL: transcribe() takes a Path, NOT bytes

# aiohttp WebSocket pattern (from voice/handler.py):
ws = web.WebSocketResponse(heartbeat=30.0, max_msg_size=10*1024*1024)
await ws.prepare(request)
async for msg in ws:
    if msg.type == WSMsgType.TEXT:
        data = json.loads(msg.data)
    elif msg.type == WSMsgType.BINARY:
        audio_bytes = msg.data
    elif msg.type in (WSMsgType.ERROR, WSMsgType.CLOSE):
        break
await ws.send_json({"type": "...", "data": {...}})
```

### Does NOT Exist
- ~~`parrot_formdesigner.api.audio_ws`~~ — does not exist yet, this task creates it
- ~~`FasterWhisperBackend.transcribe_bytes(bytes)`~~ — does NOT exist; must write bytes to temp file first
- ~~`FasterWhisperBackend.transcribe_stream()`~~ — does NOT exist
- ~~`VoiceSynthesizer.synthesize_to_base64()`~~ — does NOT exist; use `base64.b64encode(result.audio)`
- ~~`TokenValidator.validate_request(request)`~~ — does NOT exist; extract JWT from subprotocol or first message
- ~~`FormRegistry.get(form_id)`~~ — DOES exist but may require `tenant=` kwarg; check signature

---

## Implementation Notes

### Pattern to Follow
```python
# Follow the VoiceChatHandler pattern from voice/handler.py
# Key structure:
class AudioFormWSHandler:
    def __init__(self, registry, synthesizer, transcriber, validator, *,
                 token_validator=None, submission_storage=None):
        self.registry = registry
        self.synthesizer = synthesizer
        self.transcriber = transcriber
        self.validator = validator
        self._token_validator = token_validator
        self._submission_storage = submission_storage
        self.logger = logging.getLogger(__name__)

    async def handle_websocket(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=30.0, max_msg_size=10*1024*1024)
        await ws.prepare(request)
        # Auth: extract JWT from Sec-WebSocket-Protocol or first message
        # Session loop: process messages by type
        # Cleanup on exit
        return ws
```

### Key Constraints
- **Temp files for STT**: `FasterWhisperBackend.transcribe()` requires a `Path`.
  Use `tempfile.NamedTemporaryFile(suffix=".ogg", delete=False)` to write binary
  audio data, transcribe, then delete the temp file in a `finally` block.
- **TTS caching**: Pre-synthesize all questions at `start_session` to avoid
  per-question latency. Cache in `AudioSessionState` or a session-local dict.
- **Error handling**: Wrap each message handler in try/except; send `error`
  message on failure rather than dropping the connection.
- **Concurrent sessions**: Each WebSocket connection gets its own
  `AudioSessionState`. No shared mutable state between connections.
- **Message dispatch**: Use a dict mapping `type` → handler method (pattern from
  `VoiceChatHandler`).
- **JWT extraction**: Check `Sec-WebSocket-Protocol` header first (subprotocol
  pattern), then accept `auth` type message as fallback.
- **Binary frames**: Audio answers arrive as binary WebSocket frames, not JSON.
  Detect via `msg.type == WSMsgType.BINARY`.

### References in Codebase
- `packages/ai-parrot-integrations/src/parrot/voice/handler.py` — WebSocket + JWT auth pattern
- `packages/ai-parrot-integrations/src/parrot/voice/server.py` — message dispatch dict pattern
- Spec §2 WebSocket Protocol — complete message type definitions

---

## Acceptance Criteria

- [ ] `AudioFormWSHandler` accepts WebSocket connections
- [ ] JWT authentication rejects unauthenticated connections
- [ ] `start_session` loads the form and sends first question with TTS audio
- [ ] `answer_text` validates and stores text answers
- [ ] Binary audio frames are transcribed via `FasterWhisperBackend`
- [ ] `transcription` message is sent back with text and confidence
- [ ] `skip_question` works for optional fields, rejects for required
- [ ] `go_back` navigates to a previous question
- [ ] `repeat_question` re-sends TTS audio for current question
- [ ] After last answer, `form_complete` message is sent
- [ ] Temp files are cleaned up after transcription
- [ ] Error messages are sent for invalid protocol messages
- [ ] Tests pass: `pytest tests/formdesigner/test_audio_ws_handler.py -v`
- [ ] No linting errors

---

## Test Specification

```python
# tests/formdesigner/test_audio_ws_handler.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from parrot_formdesigner.api.audio_ws import AudioFormWSHandler
from parrot_formdesigner.audio.models import AudioSessionState


@pytest.fixture
def mock_registry():
    registry = AsyncMock()
    # return a simple 2-question form
    return registry


@pytest.fixture
def mock_synthesizer():
    synth = AsyncMock()
    synth.synthesize.return_value = MagicMock(audio=b"fake-audio", mime_format="audio/ogg")
    return synth


@pytest.fixture
def mock_transcriber():
    transcriber = AsyncMock()
    transcriber.transcribe.return_value = MagicMock(
        text="hello", confidence=0.95, language="en"
    )
    return transcriber


@pytest.fixture
def handler(mock_registry, mock_synthesizer, mock_transcriber):
    return AudioFormWSHandler(
        registry=mock_registry,
        synthesizer=mock_synthesizer,
        transcriber=mock_transcriber,
        validator=MagicMock(),
    )


class TestSessionLifecycle:
    @pytest.mark.asyncio
    async def test_session_state_initialized(self, handler):
        # Test that start_session creates AudioSessionState
        pass  # implement with aiohttp test client

    @pytest.mark.asyncio
    async def test_text_answer_accepted(self, handler):
        # Test answer_text stores value and advances
        pass

    @pytest.mark.asyncio
    async def test_audio_answer_transcribed(self, handler):
        # Test binary frame → temp file → transcribe → accept
        pass


class TestNavigation:
    @pytest.mark.asyncio
    async def test_skip_optional_field(self, handler):
        pass

    @pytest.mark.asyncio
    async def test_skip_required_field_rejected(self, handler):
        pass

    @pytest.mark.asyncio
    async def test_go_back(self, handler):
        pass

    @pytest.mark.asyncio
    async def test_repeat_question(self, handler):
        pass
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/formdesigner-audio-renderer.spec.md` §2 WebSocket Protocol
2. **Check dependencies** — TASK-1460 (models) and TASK-1462 (renderer) must be complete
3. **Verify the Codebase Contract** — especially `FasterWhisperBackend.transcribe(Path)` signature and `TokenValidator`
4. **Read** `packages/ai-parrot-integrations/src/parrot/voice/handler.py` for the WS+JWT pattern
5. **Update status** in `sdd/tasks/index/formdesigner-audio-renderer.json` → `"in-progress"`
6. **Implement** the WebSocket handler
7. **Verify** all acceptance criteria are met
8. **Move this file** to `sdd/tasks/completed/TASK-1463-audio-ws-handler.md`
9. **Update index** → `"done"`
10. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-06-04
**Notes**: Created `api/audio_ws.py` with `AudioFormWSHandler`. Implements JWT auth via Sec-WebSocket-Protocol header (with auth-message fallback), start_session, answer_text, binary audio (temp file → FasterWhisperBackend), skip_question, go_back, repeat_question, end_session, ping/pong. TTS pre-synthesis at session start with per-question cache. 13 unit tests pass.

**Deviations from spec**: TASK-1465 (builtin.py) had to be implemented first to unblock import of `parrot_formdesigner.api` in tests. Implementation order followed correctly: 1465 was done before 1463 tests ran.
