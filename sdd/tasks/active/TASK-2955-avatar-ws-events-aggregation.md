# TASK-2955: AvatarWebSocket observable events, close notification and cross-call frame aggregation

**Feature**: FEAT-537 — Nova VoiceBot avatar broadcast for multiple browsers
**Spec**: `sdd/specs/voicebot-multiroom-heygen-avatar.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Parallel**: true
**Parallelism notes**: Touches only `avatar_ws.py` and `test_avatar_ws.py`. Vendor event semantics are pending TASK-2950; expose them as data (callbacks + names) so no assumption is baked in.

---

## Context

Spec §3 Module 3: "`avatar_ws.py` for observable events/close and cross-call chunk aggregation". Spec §2 Integration Points: "Add events/deadline handling to `AvatarWebSocket`; current handler observes connected state but does not implement broadcast failure routing." Today the reader loop silently reconnects on CLOSE/ERROR (`avatar_ws.py:262-281`) and `send_audio_frame` slices **per call** (`:168-205`), so small Nova chunks become many tiny `agent.speak` frames.

## Scope

- Add constructor kwargs (all optional; defaults preserve current behaviour): `on_event: Callable[[dict], Awaitable[None] | None] | None`, `on_close: Callable[[str], Awaitable[None] | None] | None` (reason string), `auto_reconnect: bool = True`, `send_timeout_s: float | None = None` (spec default for broadcast: 2 s, passed by caller), `aggregate: bool = False`.
- Events: `_handle_server_message` (`:283`) must, after existing `session.state_updated` handling, forward **every** parsed message to `on_event`. Add `speaking_state: str | None` attribute updated from any event whose type contains `speak`/`speaking` (name recorded verbatim — TASK-2950 confirms actual names). Expose `closed: asyncio.Event`.
- Close: when `auto_reconnect=False`, a CLOSE/ERROR frame or reader exception sets `closed`, calls `on_close(reason)`, and makes subsequent sends raise `RuntimeError("AvatarWebSocket: closed (<reason>)")` immediately (no 5 s gate wait).
- Aggregation (`aggregate=True`): buffer incoming PCM across `send_audio_frame` calls into frames of `_NORMAL_CHUNK_BYTES` (48 000 B ≈ 1 s), first frame `_FIRST_CHUNK_BYTES`, hard cap `_MAX_PACKET_BYTES`; `finish_speaking()` flushes the partial tail **before** `agent.speak_end`; `interrupt()` drops the buffer **before** sending `agent.interrupt`. Order preserved; never reorder or duplicate bytes. Add `pending_bytes` property.
- Send deadline: wrap `_send_json` in `asyncio.wait_for(..., send_timeout_s)` when set; on timeout raise `AvatarSendTimeout(RuntimeError)`.
- Tests added to `tests/integrations/liveavatar/test_avatar_ws.py` (existing fake-WS pattern in that file, e.g. `test_avatar_ws_chunking:85`, `test_avatar_ws_reconnect_no_handshake:179`).

**NOT in scope**: `VoiceAvatarSession`, publisher, broadcast package.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/avatar_ws.py` | MODIFY | Callbacks, close semantics, aggregation, send deadline |
| `packages/ai-parrot-integrations/tests/integrations/liveavatar/test_avatar_ws.py` | MODIFY | New tests; existing ones must stay green |

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.integrations.liveavatar.avatar_ws import AvatarWebSocket   # avatar_ws.py:76
from parrot.integrations.liveavatar.models import AvatarSessionHandle   # avatar_ws.py:43
import aiohttp  # avatar_ws.py:41
```

### Existing Signatures to Use
```python
# packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/avatar_ws.py
_SAMPLE_RATE = 24_000; _BYTES_PER_SAMPLE = 2; _BYTES_PER_SECOND = 48_000        # :44-46
_FIRST_CHUNK_BYTES = 19_200; _NORMAL_CHUNK_BYTES = 48_000; _MAX_PACKET_BYTES = 1_048_576  # :49-51
_CONNECT_TIMEOUT = _connect_timeout_default()  # env LIVEAVATAR_WS_CONNECT_TIMEOUT, default 5.0   # :63-73
class AvatarWebSocket:
    def __init__(self, handle: AvatarSessionHandle, *, session: Optional[aiohttp.ClientSession] = None, assume_connected: bool = False)  # :109
        self._ws; self._connected: asyncio.Event; self._connect_failed: bool; self._reader_task   # :120-132
    async def __aenter__/__aexit__                                  # :134/:140
    async def start_speaking(self) -> None                         # :153 (await _await_connected)
    async def send_audio_frame(self, pcm: bytes) -> None           # :168 (per-call slicing loop → _send_json({"type":"agent.speak","audio":b64}))
    async def finish_speaking(self) -> None                        # :207 ({"type":"agent.speak_end","event_id":uuid4hex})
    async def interrupt(self) -> None                              # :221 ({"type":"agent.interrupt"})
    async def _connect(self) -> None                               # :233
    async def _reader_loop(self) -> None                           # :262 (CLOSE/ERROR → await self._reconnect(); return)
    async def _handle_server_message(self, raw: str) -> None       # :283 (json.loads; sets _connected on session.state_updated=="connected")
    async def _reconnect(self) -> None                             # :308
    async def _close(self) -> None                                 # :339
    async def _await_connected(self) -> None                       # :356 (wait_for(_connected.wait(), _CONNECT_TIMEOUT) → RuntimeError)
    async def _send_json(self, payload: Dict[str, Any]) -> None    # :384 (raises RuntimeError if ws None/closed)
```

### Does NOT Exist
- ~~`AvatarWebSocket.on_event` / `on_close` / `aggregate` / `send_timeout_s`~~ — you add them.
- ~~Confirmed vendor event names for speaking start/stop~~ — unknown until TASK-2950; store names verbatim, do not hard-code `agent.speaking_started`.
- ~~A binary WS audio path~~ — LITE carries audio in JSON base64 (docstring `:168`).

## Implementation Notes

- Preserve every existing test: defaults (`auto_reconnect=True`, `aggregate=False`) must reproduce current slicing exactly (`test_avatar_ws_chunking`).
- Aggregation buffer is a `bytearray`; emit while `len(buf) >= target` where target is `_FIRST_CHUNK_BYTES` until the first emit of the utterance, then `_NORMAL_CHUNK_BYTES`; reset "first" state on `finish_speaking`/`interrupt`.
- Callbacks may be sync or async: `res = cb(x); if inspect.isawaitable(res): await res`. Exceptions from callbacks are logged, never propagate into the reader loop.
- `on_close` must fire at most once.

## Acceptance Criteria

- [ ] Existing `test_avatar_ws.py` tests unchanged and green.
- [ ] `aggregate=True`: 30 calls of 1 600 B → frames of 19 200 then 48 000 B, tail flushed on `finish_speaking`, bytes concatenated equal input; `interrupt()` drops pending bytes and sends `agent.interrupt`.
- [ ] `auto_reconnect=False` + server CLOSE → `on_close("close")` once, `closed.is_set()`, next `send_audio_frame` raises immediately (< 100 ms).
- [ ] Every server JSON message reaches `on_event`; `speaking_state` updates for `*speak*` types.
- [ ] `send_timeout_s=0.05` with a stalled fake `send_json` → `AvatarSendTimeout`.
- [ ] `ruff check packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/avatar_ws.py` clean.

## Test Specification

```python
async def test_aggregate_emits_one_second_frames_and_flushes_tail(fake_ws_factory): ...
async def test_interrupt_drops_pending_buffer(fake_ws_factory): ...
async def test_close_without_reconnect_notifies_once_and_fails_fast(fake_ws_factory): ...
async def test_every_event_forwarded_to_on_event(fake_ws_factory): ...
async def test_send_timeout_raises(fake_ws_factory): ...
```

## Agent Instructions
1. Read spec §2 "Audio routing, failure and interruption" + "Vendor contract". 2. Verify anchors above (lines may shift). 3. Index → `in-progress`. 4. Implement + tests, run the whole `test_avatar_ws.py`. 5. Move to `completed/`, index → `done`.

## Completion Note

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**:
