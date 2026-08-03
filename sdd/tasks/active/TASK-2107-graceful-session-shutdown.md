# TASK-2107: Send promptEnd + sessionEnd before closing the stream

**Feature**: FEAT-408 — Nova Sonic Protocol Fidelity
**Spec**: `sdd/specs/nova-sonic-protocol-fidelity.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec Module 8 (gap 9). The AWS sample ends a session with two frames
before closing the transport (`nova_sonic_simple.py:210-235`):

```python
await self.send_event(prompt_end)     # {"event": {"promptEnd": {"promptName": …}}}
await self.send_event(session_end)    # {"event": {"sessionEnd": {}}}
await self.stream.input_stream.close()
```

`stream_voice()` sends neither — the transport fix added `_close_stream()`, which
closes the connection without telling Nova the session is over. That leaves the
service tearing down on its side and may cost usage/settlement frames that arrive
after the last content.

---

## Scope

- Add `_end_session(stream, prompt_name)` sending `promptEnd` then `sessionEnd`.
- Call it from `stream_voice()`'s `finally`, **before** `_close_stream(stream)`.
- Make it best-effort: a stream already torn down by the service must not raise
  out of `finally`, and must never mask the turn's original exception.
- Tests for order, for the "does not mask" property, and for the call sequence
  relative to `_close_stream`.

**NOT in scope**: `_close_stream()` itself (added by the transport fix, already
suppresses exceptions); reconnection across the 8-minute limit; whether Nova
requires `contentEnd` for the audio block first (`_audio_sender` already sends
that on the `None` sentinel — verify, don't duplicate).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/nova/audio.py` | MODIFY | `_end_session()` + `finally` wiring |
| `packages/ai-parrot/tests/clients/test_nova_session_shutdown.py` | CREATE | Order + resilience tests |

---

## Codebase Contract (Anti-Hallucination)

> Line numbers verified on branch `fix/nova-sonic-bidirectional-sdk` @ `89204b9f0`.

### Verified Imports

```python
from parrot.clients.nova import NovaClient   # verified: clients/nova/__init__.py:10
# already imported at the top of nova/audio.py — do not re-add:
#   asyncio, contextlib
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/clients/nova/audio.py
class NovaAudio:                                                      # line 125
    async def _send_event(self, stream, event: Dict[str, Any]) -> None: ...   # line 234
    async def _close_stream(self, stream: Any) -> None: ...                   # line 313
    async def _audio_sender(self, stream, audio_iterator,
                            prompt_name, content_name) -> None: ...           # line 599

# The finally block to extend (added by the transport fix):
        finally:
            sender_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await sender_task
            # One stream_voice() call == one turn, so the stream opened above
            # must be released here or every turn leaks its connection.
            await self._close_stream(stream)          # ← _end_session() goes BEFORE this
```

`_close_stream()`'s existing body, for reference — it already swallows everything:

```python
    async def _close_stream(self, stream: Any) -> None:
        with contextlib.suppress(Exception):
            await stream.close()
```

### Does NOT Exist

- ~~`NovaAudio._end_session()`~~ — **this task creates it**.
- ~~`sessionEnd` taking a `promptName`~~ — the sample sends `{"sessionEnd": {}}`,
  an empty object. Only `promptEnd` carries `promptName`.
- ~~`stream.input_stream.close()` as the parrot close path~~ — parrot closes via
  `_close_stream()` → `stream.close()`, which the SDK's `DuplexEventStream.close()`
  implements as closing **both** input and output. Do not add a second close.
- ~~`self._prompt_name`~~ — `prompt_name` is a local in `stream_voice()`; pass it
  in as an argument.

---

## Implementation Notes

### Pattern to Follow

```python
    async def _end_session(self, stream: Any, prompt_name: str) -> None:
        """Tell Nova Sonic the prompt and session are finished.

        Sends ``promptEnd`` then ``sessionEnd`` so the service can settle the
        turn before the transport closes. Best-effort: called from
        ``stream_voice()``'s ``finally``, where the stream may already be
        half-closed by the service, and where raising would mask the real error.
        """
        try:
            await self._send_event(
                stream, {"event": {"promptEnd": {"promptName": prompt_name}}}
            )
            await self._send_event(stream, {"event": {"sessionEnd": {}}})
        except Exception as exc:      # noqa: BLE001 — must never escape finally
            self.logger.debug(
                "Nova Sonic session shutdown frames not delivered: %s", exc
            )
```

Wiring:

```python
        finally:
            sender_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await sender_task
            await self._end_session(stream, prompt_name)
            await self._close_stream(stream)
```

### Key Constraints

- **Order matters**: cancel sender → `_end_session` → `_close_stream`. Sending
  frames after the transport is closed cannot work.
- **Never raise.** Catch broadly and log at `debug`. This runs in a `finally`
  reached on the error path too, including after the `_iter_events` timeout the
  transport fix added, where the stream is by definition unhealthy.
- Do not `await` the shutdown frames with a long timeout — if the stream is dead,
  `_send_event` should fail fast. If it turns out to hang in practice, wrap in
  `asyncio.wait_for` with a small bound and note it.
- `_audio_sender` already emits `contentEnd` for the audio content block on the
  `None` sentinel (line ~599). Verify that and do **not** send a duplicate.

### References in Codebase

- `nova_sonic_simple.py:210-235` (AWS sample) — `end_session()`.
- `nova/audio.py:313` — `_close_stream()`, the existing best-effort pattern to
  mirror.

---

## Acceptance Criteria

- [ ] `promptEnd` is sent, carrying the turn's `promptName`.
- [ ] `sessionEnd` is sent immediately after, as an empty object.
- [ ] Both are sent **before** `_close_stream()`.
- [ ] A raising `_send_event` inside `_end_session` does not propagate.
- [ ] When the turn itself raised, that original exception still surfaces to the
      caller — `_end_session` never replaces it.
- [ ] `_close_stream()` is still always called.
- [ ] No duplicate `contentEnd` for the audio block.
- [ ] All existing tests pass: `pytest packages/ai-parrot/tests/clients/ -k "nova or bedrock" -q`
      — note `test_nova_audio_sdk.py::test_turn_completes_and_stream_is_closed`
      asserts `stream.closed`, which must keep holding.
- [ ] No AWS access required.

---

## Test Specification

```python
# packages/ai-parrot/tests/clients/test_nova_session_shutdown.py
import pytest
from unittest.mock import AsyncMock, patch

from parrot.clients.nova import NovaClient

END = {"completionEnd": {}}


async def _run(frames, send_event=None):
    client = NovaClient(model="nova-2-sonic", region="us-east-1")
    calls = []

    async def capture(_stream, event):
        calls.append(("send", next(iter(event.get("event", {})), None)))
        if send_event is not None:
            await send_event(_stream, event)

    async def close(_stream):
        calls.append(("close", None))

    async def iter_events(_stream):
        for f in frames:
            yield f

    async def audio():
        yield b"\x00\x01" * 8
        yield None

    with patch.object(client, "_open_stream", return_value=AsyncMock()), \
         patch.object(client, "_send_event", new=capture), \
         patch.object(client, "_iter_events", new=iter_events), \
         patch.object(client, "_close_stream", new=close):
        out = [r async for r in client.stream_voice(audio())]
    return out, calls


class TestGracefulShutdown:
    @pytest.mark.asyncio
    async def test_prompt_end_then_session_end_then_close(self):
        _, calls = await _run([END])
        names = [name for kind, name in calls if kind == "send"]
        assert names[-2:] == ["promptEnd", "sessionEnd"]
        assert calls[-1] == ("close", None)

    @pytest.mark.asyncio
    async def test_prompt_end_carries_prompt_name(self):
        client = NovaClient(model="nova-2-sonic", region="us-east-1")
        sent = []

        async def capture(_stream, event):
            sent.append(event)

        async def iter_events(_stream):
            yield END

        async def audio():
            yield None

        with patch.object(client, "_open_stream", return_value=AsyncMock()), \
             patch.object(client, "_send_event", new=capture), \
             patch.object(client, "_iter_events", new=iter_events), \
             patch.object(client, "_close_stream", new=AsyncMock()):
            async for _ in client.stream_voice(audio()):
                pass

        prompt_start = next(e["event"]["promptStart"] for e in sent
                            if "promptStart" in e.get("event", {}))
        prompt_end = next(e["event"]["promptEnd"] for e in sent
                          if "promptEnd" in e.get("event", {}))
        assert prompt_end["promptName"] == prompt_start["promptName"]
        session_end = next(e["event"]["sessionEnd"] for e in sent
                           if "sessionEnd" in e.get("event", {}))
        assert session_end == {}

    @pytest.mark.asyncio
    async def test_shutdown_failure_does_not_raise(self):
        async def boom(_stream, event):
            if "promptEnd" in event.get("event", {}):
                raise RuntimeError("stream already closed")

        out, calls = await _run([END], send_event=boom)
        assert out[-1].is_complete is True
        assert calls[-1] == ("close", None)

    @pytest.mark.asyncio
    async def test_shutdown_does_not_mask_turn_error(self):
        """The turn's own failure must still reach the caller."""
        client = NovaClient(model="nova-2-sonic", region="us-east-1")

        async def failing_events(_stream):
            raise RuntimeError("original turn failure")
            yield  # pragma: no cover

        async def boom(_stream, event):
            if "promptEnd" in event.get("event", {}):
                raise RuntimeError("shutdown also failed")

        async def audio():
            yield None

        with patch.object(client, "_open_stream", return_value=AsyncMock()), \
             patch.object(client, "_send_event", new=boom), \
             patch.object(client, "_iter_events", new=failing_events), \
             patch.object(client, "_close_stream", new=AsyncMock()):
            out = [r async for r in client.stream_voice(audio())]

        assert "original turn failure" in out[-1].metadata["error"]
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none for this task
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm `_close_stream()` exists at the listed location and the `finally`
     block matches what is quoted
   - Confirm `_audio_sender` already sends the audio `contentEnd`
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/nova-sonic-protocol-fidelity.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2107-graceful-session-shutdown.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
