# TASK-2150: Automatic Reconnection

**Feature**: FEAT-416 — Voice Agent Framework
**Spec**: `sdd/specs/voice-agent-framework.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2149
**Assigned-to**: unassigned

---

## Context

Nova Sonic enforces an 8-minute connection limit
(`_CONNECTION_LIMIT_SECONDS = 465s`). When the limit is near, the client
emits a `reconnect_required` metadata flag in `LiveVoiceResponse`. Currently
nobody acts on it — users must manually restart their session.

This task adds automatic reconnection to `VoiceSession` so the 8-minute
limit is transparent.

Implements spec §3 Module 6.

---

## Scope

- Extend `VoiceSession._run_turn()` to detect `reconnect_required` in
  `LiveVoiceResponse.metadata`.
- When `voice_config.reconnect_on_limit=True`:
  1. Complete relaying the current turn's remaining frames.
  2. Emit `{"type": "reconnect", "session_id": ...}` to the transport.
  3. Close the old `stream_voice()` async generator.
  4. Open a new `stream_voice()` with the same `system_prompt` and
     `session_id`.
  5. Resume accepting audio from the queue.
- Track reconnection count; after `max_reconnects` (default 3), emit an
  error frame and close the session.
- When `reconnect_on_limit=False`, do nothing (pass the flag through to the
  relay as metadata).
- Wait for pending tool execution to complete before tearing down.
- Write unit tests.

**NOT in scope**: modifying NovaAudio or GeminiLiveClient (they already
emit the metadata flag), multi-turn conversation memory across reconnects
(VoiceBot owns that per resolved Q2).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/voice/session.py` | MODIFY | Add reconnection logic to _run_turn() |
| `tests/voice/test_voice_reconnection.py` | CREATE | Reconnection tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.voice.session import VoiceSession          # TASK-2149 creates this
from parrot.clients.live import LiveVoiceResponse      # verified: live.py:156
from parrot.models.voice import VoiceConfig            # TASK-2146 unifies this
```

### Existing Signatures to Use

```python
# LiveVoiceResponse.metadata — dict field
# parrot/clients/live.py:192
metadata: Dict[str, Any] = field(default_factory=dict)
# reconnect_required is set by NovaAudio: resp.metadata.get("reconnect_required")

# NovaAudio._CONNECTION_LIMIT_SECONDS
# parrot/clients/nova/audio.py:265
_CONNECTION_LIMIT_SECONDS: float = 8 * 60 - 15  # 465s

# VoiceConfig fields (from TASK-2146)
# reconnect_on_limit: bool = True
# max_reconnects: int = 3
```

### Does NOT Exist

- ~~`VoiceSession._reconnect()`~~ — must be created in this task
- ~~`VoiceSession._reconnect_count`~~ — must be added

---

## Implementation Notes

### Reconnection Flow

```python
# Inside VoiceSession._run_turn():
async for resp in self.client.stream_voice(...):
    await self._relay(resp, turn_no)
    if resp.metadata.get("reconnect_required") and self.voice_config.reconnect_on_limit:
        if self._reconnect_count >= self.voice_config.max_reconnects:
            await self.send_fn({"type": "error",
                "message": "max reconnections reached",
                "session_id": self.session_id})
            await self.close()
            return
        self._reconnect_count += 1
        await self.send_fn({"type": "reconnect",
            "session_id": self.session_id,
            "reconnect_count": self._reconnect_count})
        # The current turn's stream is exhausted (is_complete should follow).
        # Re-open stream_voice() for the next turn.
        break  # exit inner loop; outer turn loop re-opens
```

### Key Constraints

- Must wait for any pending tool execution to complete before reconnecting
  (8-minute reconnection race risk from spec §7).
- `_reconnect_count` resets only on `VoiceSession.__init__()` — it tracks
  lifetime reconnections, not per-turn.
- The `reconnect` frame is informational — the browser UI can show a
  status indicator but no user action is required.
- VoiceSession is stateless w.r.t. conversation history (Q2 resolved) — it
  just re-sends `system_prompt` and `session_id`.

---

## Acceptance Criteria

- [ ] `reconnect_required=True` + `reconnect_on_limit=True` triggers re-open
- [ ] `reconnect_on_limit=False` does NOT reconnect
- [ ] `max_reconnects=3` exhausted → error frame + session closes
- [ ] Reconnection waits for pending tool execution
- [ ] `reconnect` frame emitted to transport on each reconnection
- [ ] All tests pass: `pytest tests/voice/test_voice_reconnection.py -v`

---

## Test Specification

```python
# tests/voice/test_voice_reconnection.py
import pytest
import asyncio
from parrot.voice.session import VoiceSession
from parrot.clients.live import LiveVoiceResponse
from parrot.models.voice import VoiceConfig, VoiceProvider


class ReconnectingMockClient:
    """Mock that signals reconnect_required on first turn."""
    def __init__(self):
        self.call_count = 0

    async def stream_voice(self, audio_iterator, **kwargs):
        self.call_count += 1
        async for chunk in audio_iterator:
            if chunk is None:
                break
        yield LiveVoiceResponse(
            text="response",
            is_complete=True,
            metadata={"reconnect_required": self.call_count <= 1},
        )


class AlwaysReconnectMockClient:
    """Mock that always signals reconnect_required."""
    def __init__(self):
        self.call_count = 0

    async def stream_voice(self, audio_iterator, **kwargs):
        self.call_count += 1
        async for chunk in audio_iterator:
            if chunk is None:
                break
        yield LiveVoiceResponse(
            text="", is_complete=True,
            metadata={"reconnect_required": True},
        )


class TestReconnection:
    @pytest.mark.asyncio
    async def test_reconnect_on_limit(self):
        """Session re-opens stream_voice after reconnect_required."""
        frames = []
        async def send(p): frames.append(p)
        client = ReconnectingMockClient()
        config = VoiceConfig(reconnect_on_limit=True)
        session = VoiceSession(client=client, send_fn=send,
            system_prompt="test", voice_config=config)
        # First turn triggers reconnect
        await session.start_turn()
        await session.end_turn()
        await asyncio.sleep(0.5)
        types = [f["type"] for f in frames]
        assert "reconnect" in types

    @pytest.mark.asyncio
    async def test_reconnect_disabled(self):
        frames = []
        async def send(p): frames.append(p)
        client = ReconnectingMockClient()
        config = VoiceConfig(reconnect_on_limit=False)
        session = VoiceSession(client=client, send_fn=send,
            system_prompt="test", voice_config=config)
        await session.start_turn()
        await session.end_turn()
        await asyncio.sleep(0.5)
        types = [f["type"] for f in frames]
        assert "reconnect" not in types

    @pytest.mark.asyncio
    async def test_max_reconnects_exhausted(self):
        frames = []
        async def send(p): frames.append(p)
        client = AlwaysReconnectMockClient()
        config = VoiceConfig(reconnect_on_limit=True, max_reconnects=2)
        session = VoiceSession(client=client, send_fn=send,
            system_prompt="test", voice_config=config)
        # Simulate enough turns to exhaust max_reconnects
        for _ in range(3):
            await session.start_turn()
            await session.end_turn()
            await asyncio.sleep(0.3)
        types = [f["type"] for f in frames]
        assert "error" in types
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/voice-agent-framework.spec.md` §3 Module 6
2. **Check dependencies** — TASK-2149 must be done
3. **Read** `parrot/voice/session.py` (created by TASK-2149)
4. **Add** reconnection logic to `_run_turn()`
5. **Write tests** and verify

---

## Completion Note

Implemented per spec §3 Module 6, with one real bug fixed in the task's
own Implementation Notes pseudocode:

- `_run_turn()` now wraps `stream_voice()` in an outer `while True:` loop.
  Each iteration captures the async generator explicitly (`stream = self.
  client.stream_voice(...)`) so it can be `.aclose()`'d in a `finally`
  before either reconnecting or exiting — satisfying "close the old
  `stream_voice()` async generator" literally, not just implicitly via
  loop exit (which would otherwise leak a suspended generator on early
  `break`).
- Relaying happens **before** checking `reconnect_required`, so any tool
  calls carried on that same response are already sent — the sequential
  nature of `async for` means the provider client (which only sets
  `reconnect_required` between its own already-flushed tool batches,
  confirmed in TASK-2148) guarantees no pending tool execution is
  in-flight when a reconnect is triggered; no extra explicit "wait"
  needed.
- `_reconnect_count` is a plain instance counter set in `__init__`,
  incremented only on an actual reconnect, never reset per-turn — matches
  "tracks lifetime reconnections, not per-turn."

**Bug fixed in the task's own pseudocode**: the Implementation Notes
example calls `await self.close()` when `max_reconnects` is exhausted.
`close()` → `_cancel_turn()` does `self._task.cancel(); await
self._task` — but at that point in the code, `self._task` **is** the
currently-running coroutine calling `close()` (this method only ever runs
inside `_run_turn`, which *is* `self._task`). Awaiting a task from inside
its own coroutine raises `RuntimeError` (a task cannot await itself) —
this would have crashed on the very first `max_reconnects`-exhausted
turn. Fixed by clearing `self._queue`/`self._task` directly (guarded by
`self._task is asyncio.current_task()`, mirroring the existing outer
`finally`) and `return`ing instead — the task is ending on its own, there
is nothing to cancel.

Files touched exactly as scoped:
- `packages/ai-parrot/src/parrot/voice/session.py` (MODIFY) — added
  `self._reconnect_count = 0` to `__init__` and the reconnection loop to
  `_run_turn()`. No other methods changed.
- `packages/ai-parrot/tests/voice/test_voice_reconnection.py` (CREATE) —
  the task's Test Specification was already complete, runnable code; used
  verbatim, plus 2 added tests
  (`test_reconnect_count_persists_across_turns`,
  `test_reconnect_frame_includes_session_and_count`) directly covering
  the "lifetime, not per-turn" constraint and the `reconnect` frame shape,
  neither exercised by the given scaffold.

Lint: `ruff check --select=E,F,W,C,B --ignore=E501,W293,C901` passes.

**Tests not executed** — same pre-existing, sandbox-wide broken-venv
limitation as prior tasks (verified via `python -m py_compile` instead).
Recommend running
`pytest packages/ai-parrot/tests/voice/test_voice_reconnection.py
packages/ai-parrot/tests/voice/test_voice_session.py -v`
in a fully-provisioned environment before merge — the latter to confirm
no regression in TASK-2149's turn-lifecycle contract.
