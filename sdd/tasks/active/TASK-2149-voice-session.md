# TASK-2149: VoiceSession

**Feature**: FEAT-416 — Voice Agent Framework
**Spec**: `sdd/specs/voice-agent-framework.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2145, TASK-2146
**Assigned-to**: unassigned

---

## Context

The `examples/clients/nova/audio.py` contains `NovaVoiceSession` (~220
LOC, lines 116-338) — a turn lifecycle manager that bridges a browser
WebSocket to `NovaClient.stream_voice()`. It handles audio queuing, turn
tasks, WebSocket relay, and VAD silence injection. However, it lives in an
example file and is tightly coupled to `NovaClient` and `aiohttp.ws`.

The integrations `VoiceChatHandler` (line 1320, `_run_voice_session()`)
duplicates most of this logic.

This task promotes `NovaVoiceSession` into a provider-agnostic
`VoiceSession` in the core framework.

Implements spec §3 Module 5.

---

## Scope

- Create `parrot/voice/session.py` (in the core `ai-parrot` package) with
  a `VoiceSession` class.
- Port the turn lifecycle from `NovaVoiceSession`:
  - `start_turn()`, `push_audio()`, `end_turn()`, `close()`
  - `_run_turn()`, `_audio_iterator()`, `_relay()`
- Replace `NovaClient`-specific references with `VoiceCapable` Protocol.
- Replace `self.ws.send_json()` with an injected `send_fn: Callable`.
- Preserve the 20ms-paced silence injection in `end_turn()`.
- VoiceSession is **stateless w.r.t. conversation history** (resolved Q2).
- Write comprehensive unit tests.

**NOT in scope**: automatic reconnection (TASK-2150), modifying
VoiceChatHandler (TASK-2152), modifying the example.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/voice/session.py` | CREATE | VoiceSession class |
| `parrot/voice/__init__.py` | MODIFY | Export VoiceSession |
| `tests/voice/test_voice_session.py` | CREATE | Unit tests |

Note: `parrot/voice/` in core is at `packages/ai-parrot/src/parrot/voice/`.
Check if this directory exists; if not, create it with `__init__.py`.

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.clients.protocols import VoiceCapable     # TASK-2145 creates this
from parrot.clients.live import LiveVoiceResponse      # verified: live.py:156
from parrot.models.voice import VoiceConfig            # TASK-2146 unifies this
```

### Existing Signatures to Use

```python
# examples/clients/nova/audio.py:116-338 — SOURCE to promote
class NovaVoiceSession:
    def __init__(self, client: NovaClient, ws, system_prompt, session_id=None):
        self.client = client
        self.ws = ws
        self.system_prompt = system_prompt
        self.session_id = session_id or str(uuid.uuid4())
        self._queue: Optional[asyncio.Queue[Optional[bytes]]] = None
        self._task: Optional[asyncio.Task] = None
        self._turn_no = 0

    async def start_turn(self) -> None: ...       # line 151
    async def push_audio(self, pcm: bytes): ...   # line 165
    async def end_turn(self) -> None: ...          # line 172 — 20ms-paced silence
    async def close(self) -> None: ...             # line 211
    async def _cancel_turn(self) -> None: ...      # line 215
    async def _audio_iterator(self, queue): ...    # line 225
    async def _run_turn(self, turn_no): ...        # line 239
    async def _relay(self, resp, turn_no): ...     # line 269

# VoiceCapable Protocol (from TASK-2145)
class VoiceCapable(Protocol):
    async def stream_voice(
        self, audio_iterator, system_prompt=None,
        session_id=None, user_id=None, **kwargs,
    ) -> AsyncIterator[LiveVoiceResponse]: ...

# NovaClient.INPUT_SAMPLE_RATE_HZ — used for silence frame sizing
# parrot/clients/nova/audio.py:274
INPUT_SAMPLE_RATE_HZ: int = 16000
```

### Does NOT Exist

- ~~`parrot.voice.session`~~ — does not exist; must be created
- ~~`VoiceSession`~~ — does not exist anywhere in the codebase
- ~~`parrot/voice/__init__.py` in core~~ — verify; may need creation

---

## Implementation Notes

### Pattern to Follow

```python
# parrot/voice/session.py
import asyncio
import base64
import contextlib
import logging
import uuid
from typing import AsyncIterator, Awaitable, Callable, Optional

from parrot.clients.protocols import VoiceCapable
from parrot.clients.live import LiveVoiceResponse
from parrot.models.voice import VoiceConfig

logger = logging.getLogger(__name__)

class VoiceSession:
    """Provider-agnostic voice turn lifecycle manager."""

    def __init__(
        self,
        client: VoiceCapable,
        send_fn: Callable[[dict], Awaitable[None]],
        system_prompt: str,
        voice_config: Optional[VoiceConfig] = None,
        session_id: Optional[str] = None,
    ) -> None:
        self.client = client
        self.send_fn = send_fn
        self.system_prompt = system_prompt
        self.voice_config = voice_config or VoiceConfig()
        self.session_id = session_id or str(uuid.uuid4())
        self.logger = logger.getChild("session")

        self._queue: Optional[asyncio.Queue[Optional[bytes]]] = None
        self._task: Optional[asyncio.Task] = None
        self._turn_no = 0
```

### Key Constraints

- **Silence injection MUST use 20ms pacing** (not burst). This is critical
  for Nova Sonic VAD. See `NovaVoiceSession.end_turn()` lines 196-201.
- `send_fn` replaces direct `ws.send_json()` — makes VoiceSession
  transport-agnostic.
- `_relay()` must handle: text, audio, tool_call, interrupted, error,
  turn_complete frames (same protocol as `NovaVoiceSession._relay()`).
- Use `input_sample_rate` from VoiceConfig (default 16000) for silence
  frame sizing instead of hardcoded `NovaClient.INPUT_SAMPLE_RATE_HZ`.

---

## Acceptance Criteria

- [ ] `VoiceSession` importable from `parrot.voice.session`
- [ ] `start_turn → push_audio → end_turn` produces correct relay frames
- [ ] `end_turn()` injects ~1.5s of 20ms-paced silence frames
- [ ] Cancelling a running turn cleans up correctly
- [ ] `send_fn` is called (not `ws.send_json`)
- [ ] VoiceSession is transport-agnostic (no aiohttp import)
- [ ] All tests pass: `pytest tests/voice/test_voice_session.py -v`

---

## Test Specification

```python
# tests/voice/test_voice_session.py
import pytest
import asyncio
from parrot.voice.session import VoiceSession
from parrot.clients.live import LiveVoiceResponse


class MockVoiceClient:
    """Minimal VoiceCapable for testing."""
    async def stream_voice(self, audio_iterator, system_prompt=None,
                          session_id=None, user_id=None, **kwargs):
        async for chunk in audio_iterator:
            if chunk is None:
                break
        yield LiveVoiceResponse(text="Hello", role="ASSISTANT")
        yield LiveVoiceResponse(text="", is_complete=True)


@pytest.fixture
def mock_send_fn():
    frames = []
    async def send(payload):
        frames.append(payload)
    send.frames = frames
    return send


class TestVoiceSession:
    @pytest.mark.asyncio
    async def test_turn_lifecycle(self, mock_send_fn):
        session = VoiceSession(
            client=MockVoiceClient(),
            send_fn=mock_send_fn,
            system_prompt="You are a test bot.",
        )
        await session.start_turn()
        await session.push_audio(b"\x00" * 2048)
        await session.end_turn()
        # Wait for turn task to complete
        await asyncio.sleep(0.5)
        types = [f["type"] for f in mock_send_fn.frames]
        assert "turn_started" in types
        assert "text" in types or "turn_complete" in types

    @pytest.mark.asyncio
    async def test_cancel_turn(self, mock_send_fn):
        session = VoiceSession(
            client=MockVoiceClient(),
            send_fn=mock_send_fn,
            system_prompt="Test",
        )
        await session.start_turn()
        await session.close()
        assert session._task is None
        assert session._queue is None

    @pytest.mark.asyncio
    async def test_silence_injection_pacing(self, mock_send_fn):
        """end_turn() injects paced silence frames."""
        session = VoiceSession(
            client=MockVoiceClient(),
            send_fn=mock_send_fn,
            system_prompt="Test",
        )
        await session.start_turn()
        await session.push_audio(b"\x00" * 1024)
        start = asyncio.get_event_loop().time()
        await session.end_turn()
        elapsed = asyncio.get_event_loop().time() - start
        # ~23 frames × 20ms = ~460ms minimum
        assert elapsed >= 0.3  # some margin for test environments
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/voice-agent-framework.spec.md` §3 Module 5
2. **Check dependencies** — TASK-2145 and TASK-2146 must be done
3. **Read** `examples/clients/nova/audio.py` lines 116-338 (the source)
4. **Create** `parrot/voice/session.py` with the promoted VoiceSession
5. **Ensure** `parrot/voice/__init__.py` exists and exports VoiceSession
6. **Write tests** and verify all pass

---

## Completion Note

*(Agent fills this in when done)*
