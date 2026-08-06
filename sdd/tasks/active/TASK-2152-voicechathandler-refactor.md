# TASK-2152: VoiceChatHandler Refactor

**Feature**: FEAT-416 — Voice Agent Framework
**Spec**: `sdd/specs/voice-agent-framework.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2149, TASK-2146
**Assigned-to**: unassigned

---

## Context

`VoiceChatHandler._run_voice_session()` (line 1320, integrations) contains
inlined turn lifecycle logic — audio queue management, stream consumption,
response relay — that duplicates what `VoiceSession` now provides (created
in TASK-2149). This task refactors the handler to delegate to `VoiceSession`.

Additionally, the handler imports the integrations-layer `VoiceConfig`
which is now a deprecation shim (TASK-2146). This task switches it to the
unified core import.

Implements spec §3 Module 8.

---

## Scope

- Refactor `_run_voice_session()` to create a `VoiceSession` instance and
  delegate `start_turn`, `push_audio`, `end_turn`, `close` to it.
- Replace `from parrot.voice.models import VoiceConfig` with
  `from parrot.models.voice import VoiceConfig`.
- Replace `from parrot.voice.models import VoiceProvider` with
  `from parrot.models.voice import VoiceProvider`.
- Ensure the WebSocket frame protocol is unchanged (no breaking changes
  to `handle_websocket()`).
- The `WebSocketConnection` dataclass remains (it holds transport-level
  state: auth, WS object, config). `VoiceSession` owns turn-level state.
- Write integration tests verifying the refactored handler produces the
  same frame types as before.

**NOT in scope**: modifying VoiceSession itself, changing the WebSocket
authentication flow, modifying avatar session handling.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/voice/handler.py` (integrations) | MODIFY | Delegate to VoiceSession |
| `parrot/voice/models.py` (integrations) | VERIFY | VoiceProvider re-export works |
| `tests/voice/test_handler_refactor.py` | CREATE | Frame-protocol compatibility tests |

Note: paths in integrations are under
`packages/ai-parrot-integrations/src/parrot/voice/`.

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Current handler imports (integrations) — TO BE CHANGED
from parrot.voice.models import VoiceConfig     # line 45 — switch to parrot.models.voice
from parrot.voice.models import VoiceProvider   # switch to parrot.models.voice

# New imports
from parrot.voice.session import VoiceSession   # TASK-2149 creates this
from parrot.models.voice import VoiceConfig, VoiceProvider  # TASK-2146

# Existing (keep as-is)
from parrot.bots.voice import VoiceBot          # verified: voice.py:80
from parrot.clients.live import LiveVoiceResponse  # verified: live.py:156
```

### Existing Signatures to Use

```python
# parrot/voice/handler.py:226 (integrations)
class VoiceChatHandler:
    def __init__(self, bot_factory=None, default_config=None,
        *, require_auth=False, ...):                            # line 267

# parrot/voice/handler.py:1320
async def _run_voice_session(self, connection: WebSocketConnection) -> None:
    # Current: inlined audio_from_queue() generator, while loop calling
    # connection.bot.ask_stream(), dispatching via _send_voice_response()

# parrot/voice/handler.py:154
@dataclass
class WebSocketConnection:
    ws: web.WebSocketResponse
    audio_queue: asyncio.Queue
    voice_task: Optional[asyncio.Task]
    shutdown_event: asyncio.Event
    bot: Optional[VoiceBot]
    # ... ~20 fields total

# VoiceSession (from TASK-2149)
class VoiceSession:
    def __init__(self, client: VoiceCapable, send_fn, system_prompt,
        voice_config=None, session_id=None): ...
    async def start_turn(self): ...
    async def push_audio(self, pcm: bytes): ...
    async def end_turn(self): ...
    async def close(self): ...
```

### Does NOT Exist

- ~~`VoiceChatHandler.voice_session`~~ — no attribute yet; the session is
  created per-connection in `_run_voice_session()`
- ~~`WebSocketConnection.voice_session`~~ — not a field; may need to add it

---

## Implementation Notes

### Refactoring Pattern

```python
# In _run_voice_session():
async def _run_voice_session(self, connection: WebSocketConnection) -> None:
    bot = connection.bot
    client = bot.client  # or however the client is accessed

    async def send_fn(payload: dict) -> None:
        if not connection.ws.closed:
            await connection.ws.send_json(payload)

    session = VoiceSession(
        client=client,
        send_fn=send_fn,
        system_prompt=bot.system_prompt,
        voice_config=bot.voice_config,
        session_id=connection.session_id,
    )

    try:
        while not connection.shutdown_event.is_set():
            # VoiceSession handles the turn lifecycle.
            # The handler only routes WebSocket messages to session methods.
            await asyncio.sleep(0.1)
    finally:
        await session.close()
```

### Key Constraints

- The WebSocket frame protocol (text, audio, turn_complete, error,
  tool_call, interrupted, reconnect) must NOT change — existing browser
  clients depend on it.
- `WebSocketConnection` still owns transport-level state (auth, recording
  mode, ping tracking). `VoiceSession` owns turn-level state.
- The handler's message dispatch (`_handle_audio_data`,
  `_handle_start_recording`, `_handle_stop_recording`) should route to
  `session.push_audio()`, `session.start_turn()`, `session.end_turn()`.
- `_handle_start_session()` (line 739) creates `voice_task` via
  `asyncio.create_task(self._run_voice_session(connection))` — this stays,
  but the task now delegates to VoiceSession.

---

## Acceptance Criteria

- [ ] `_run_voice_session()` uses `VoiceSession` (no inlined turn lifecycle)
- [ ] WebSocket frame types unchanged (text, audio, turn_complete, etc.)
- [ ] Imports use `parrot.models.voice` (not integrations models)
- [ ] VoiceProvider re-export from integrations still works
- [ ] No breaking changes to `handle_websocket()` API
- [ ] All tests pass: `pytest tests/voice/test_handler_refactor.py -v`

---

## Test Specification

```python
# tests/voice/test_handler_refactor.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestHandlerRefactor:
    def test_imports_unified_voiceconfig(self):
        """Handler imports VoiceConfig from core, not integrations."""
        import parrot.voice.handler as h
        # The module should import from parrot.models.voice
        import inspect
        source = inspect.getsource(h)
        assert "from parrot.models.voice import" in source

    @pytest.mark.asyncio
    async def test_run_voice_session_uses_voice_session(self):
        """_run_voice_session creates a VoiceSession instance."""
        # Mock VoiceChatHandler with a mock connection
        # Verify VoiceSession is instantiated
        pass

    @pytest.mark.asyncio
    async def test_frame_protocol_unchanged(self):
        """Refactored handler emits the same frame types."""
        # Set up mock connection + mock VoiceSession
        # Verify text/audio/turn_complete frames are emitted
        pass
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/voice-agent-framework.spec.md` §3 Module 8
2. **Check dependencies** — TASK-2149 and TASK-2146 must be done
3. **Read** `parrot/voice/handler.py` (integrations) thoroughly — especially
   `_run_voice_session()`, `_handle_audio_data()`, `_handle_start_recording()`,
   `_handle_stop_recording()`, `_handle_start_session()`
4. **Read** `parrot/voice/session.py` (created by TASK-2149)
5. **Refactor** the handler to delegate to VoiceSession
6. **Verify** no frame protocol changes
7. **Write tests** and verify

---

## Completion Note

*(Agent fills this in when done)*
