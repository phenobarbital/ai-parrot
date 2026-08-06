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

This was the largest and most consequential task in the feature — two
genuine, feature-blocking discoveries had to be resolved, both flagged in
advance and fixed in-scope for this task specifically because this is the
one whose acceptance criteria concretely require them.

### 1. Frame-protocol conflict (discovered here)

The task's Codebase Contract frame list — "text, audio, turn_complete,
error, tool_call, interrupted, reconnect" — is actually
**`VoiceSession._relay()`'s own vocabulary** (TASK-2149), not
`VoiceChatHandler`'s real, already-shipped protocol. Reading
`_send_voice_response()` in full revealed a much richer, different
vocabulary real browser clients depend on: `response_chunk` (combined
text+audio), `transcription` (user/assistant, separately),
`response_complete`, `ready_to_speak`, `display_data`, `session_warning`,
plus STT-only gating, "thought" text filtering, and a LiveAvatar audio
tee — none of which `VoiceSession._relay()` can reproduce (its frames
don't carry `user_transcription`/`assistant_transcription`/
`display_data`/`go_away` at all). Naively wiring
`VoiceSession.start_turn()` end-to-end would have silently replaced this
whole protocol — a real breaking change to existing browser clients,
which is explicitly the constraint the task itself warns against.

**Resolution**: `_HandlerVoiceSession(VoiceSession)` — a local subclass —
overrides `_relay()` to delegate to the handler's own, unchanged
`_send_voice_response()` (100% of the existing frame logic preserved
byte-for-byte, including the avatar tee, STT-only gating, and thought
filtering, since `_send_voice_response()` itself is untouched), while
`start_turn`/`push_audio`/`end_turn`/`close`/`_cancel_turn`/
`_audio_iterator` are all inherited unchanged — genuine delegation of the
audio-queue/task lifecycle (including TASK-2149's 20ms-paced silence
injection, which the original inlined `audio_from_queue()` generator
never did).

A second override, `_run_turn()`, was also necessary (not just
`_relay()`): `VoiceSession._run_turn()` calls
`self.client.stream_voice()` directly, bypassing `VoiceBot.ask_stream()`
entirely — which would have silently dropped conversation-memory
persistence, `stt_only`, and TASK-2151's VoiceConfig inference-parameter
threading (all `VoiceBot`-level value-adds, not client-level). The
override mirrors TASK-2150's reconnection loop exactly, but calls
`self._connection.bot.ask_stream(...)` instead of
`self.client.stream_voice(...)` — `ask_stream()` yields the same
`LiveVoiceResponse` objects unchanged (metadata intact), so
`reconnect_required` detection works identically either way.

**Accepted, documented behavior change**: Gemini's `go_away` signal
(distinct from `reconnect_required`) previously triggered an
unconditional restart of the outer `ask_stream()` loop. Since
`_run_turn()` reads `resp.metadata` immediately after awaiting `_relay()`
(this subclass's override), the override mutates `resp.metadata
["reconnect_required"] = True` on `go_away` — piggybacking on the
inherited reconnect path instead of duplicating it. This makes `go_away`
now respect `voice_config.reconnect_on_limit` (default `True`), whereas
before it was unconditional — a minor, arguably-more-consistent gate
change, called out explicitly rather than silently introduced.

**New, additive frames**: `start_turn()`/reconnection now also emit
`turn_started`/`reconnect` frames (VoiceSession's own, from TASK-2149/
2150) alongside the existing ones. This is new functionality (transparent
reconnection finally wired into the handler — the whole point of
G1/G4 in the spec), not a removal or change to any existing frame; clients
that ignore unknown `type` values (standard defensive JSON-protocol
practice) are unaffected.

### 2. Namespace-package collision (flagged in TASK-2149, resolved here)

TASK-2149's Completion Note flagged this in advance:
`packages/ai-parrot-integrations/src/parrot/voice/__init__.py` already
existed as a **real** (non-namespace) package (`from .tts import
VoiceSynthesizer`) before this feature touched it. Once TASK-2149 added
`packages/ai-parrot/src/parrot/voice/__init__.py` (core, also real), a
package name split across two installed distributions where **both**
sides have `__init__.py` does not merge under PEP 420 — whichever the
`PathFinder` resolves first *and* has a real loader wins **exclusively**;
the constructor confirmed empirically (see below) that with core
alphabetically first on `sys.path`, core's `__init__.py` would have won,
making `parrot.voice.handler`/`.models`/`.tts`/`.transcriber` (this whole
package) **unreachable at its own canonical import path** the moment both
distributions are installed together — which they always are in this
task's own scenario (`VoiceChatHandler` importing `VoiceSession`).

**Resolution** (the classic, pre-PEP-420, still-fully-supported fix):
1. Removed `packages/ai-parrot/src/parrot/voice/__init__.py` (core) —
   verified no test relied on its content (`__all__`/re-export); both
   TASK-2149 tests already used direct submodule imports
   (`from parrot.voice.session import VoiceSession`), unaffected.
2. Added `from pkgutil import extend_path; __path__ = extend_path(
   __path__, __name__)` to the top of
   `packages/ai-parrot-integrations/src/parrot/voice/__init__.py`
   (otherwise unchanged — `VoiceSynthesizer` re-export intact), which
   patches this package's `__path__` to also include core's directory.

**Empirically verified** (not just reasoned about) in `.venv` (both
distributions installed together, after fixing an unrelated pre-existing
broken `pydantic-core` pin in that venv — see below):
```
>>> import parrot.voice
>>> parrot.voice.__path__
['.../ai-parrot-integrations/src/parrot/voice', '.../ai-parrot/src/parrot/voice', ...]
>>> import parrot.voice.session   # core — reaches its own import statements
>>> import parrot.voice.models    # integrations
>>> from parrot.voice import VoiceSynthesizer  # convenience re-export — still works
>>> from parrot.voice.models import VoiceProvider  # 4 members, correct
>>> from parrot.voice.models import VoiceConfig  # DeprecationWarning raised, returns core class
```
All confirmed working. `parrot.voice.session`/`parrot.voice.handler`
imports proceed past their own import statements and hit the SAME
pre-existing, sandbox-wide broken-venv wall as every other task this
session (`datamodel`/`navconfig` missing compiled extensions) — not a
namespace-resolution failure. Even `pytest` itself is broken in this venv
(`hypothesis._native` missing) — the strongest evidence yet that this is
systemic and unrelated to this feature.

### Other changes (as scoped)

- `parrot/voice/handler.py`: both `VoiceProvider` imports (the
  `TYPE_CHECKING` one and the runtime one in
  `resolve_voice_client_class()`) switched to `parrot.models.voice`. The
  `VoiceConfig` import was **already** `from parrot.models.voice` before
  this task (the Codebase Contract's claim that it needed changing was
  stale) — verified, left as-is.
- Added `WebSocketConnection.voice_session` field (per the task's own
  "Does NOT Exist" anticipation).
- Rewired `_handle_start_recording()`/`_handle_audio_data()`/
  `_handle_stop_recording()` to drive `connection.voice_session.
  start_turn()`/`.push_audio()`/`.end_turn()` instead of the
  connection-level `audio_queue`, including the implicit-recording-start
  path in `_handle_audio_data()` and a cheaper `_cancel_turn()` (not full
  `end_turn()`) for the "recording too short" guard. Buffered mode
  (`_handle_voice_binary_complete`) and `_handle_send_text()` (uses
  `bot.ask()`, unrelated) are completely untouched — separate code paths
  that never used `_run_voice_session`/the audio queue.
- `packages/ai-parrot-integrations/tests/voice/test_handler_refactor.py`
  (CREATE) — real functional tests (not AST-based; this test suite,
  unlike core `ai-parrot/tests/bots/`, doesn't hit the Cython blocker —
  confirmed by the pre-existing `test_voicechat_avatar_integration.py`
  pattern reused here), covering the frame-protocol preservation,
  go_away→reconnect bridging, and the namespace-packaging fix itself.

Lint: `ruff check --select=E,F,W,C,B --ignore=E501,W293,C901` passes on
all touched files (one pre-existing `W292` at handler.py's unrelated
`__main__` block, confirmed via `git diff` outside my changes).

**Tests not executed via `pytest`** — same pre-existing, sandbox-wide
broken-venv limitation as every prior task, now additionally confirmed to
break `pytest` itself (`hypothesis._native`). Verified via
`python -m py_compile` on all touched/created files instead, plus the
namespace-fix verification above (real Python imports, run directly,
after a targeted `pydantic-core` version-pin fix in `.venv`). Recommend
running
`pytest packages/ai-parrot-integrations/tests/voice/test_handler_refactor.py
packages/ai-parrot-integrations/tests/voice/test_voicechat_avatar_integration.py
packages/ai-parrot-integrations/tests/voice/test_nova_provider.py
packages/ai-parrot/tests/voice/ -v`
in a fully-provisioned environment before merge — the existing avatar/
nova-provider suites specifically to confirm zero regression from the
`_run_voice_session`/handler rewiring and the `VoiceProvider` import
switch.

### Code Review Addendum (post-completion, commit `6f0f5bb5d`)

The feature-level adversarial code review found one **CRITICAL** and one
**suggestion**-level finding in this task's own files, both fixed:

1. **CRITICAL**: `handle_websocket()`'s raw-binary-frame path
   (`WSMsgType.BINARY` — a second, separate audio-ingestion route
   alongside the base64-in-JSON `_handle_audio_data()` I did rewire) was
   missed during the original refactor — it still queued into
   `connection.audio_queue`, which nothing has drained since
   `_run_voice_session()` stopped reading it. **Any client sending audio
   as raw binary WS frames had its audio silently dropped in streaming
   mode** — a real breaking change to `handle_websocket()`'s protocol
   the acceptance criteria explicitly guard against, and the one I
   should have caught by reading `handle_websocket()` in full rather
   than only the message-type dispatch table in `_handle_message()`.
   Fixed by routing this path through `connection.voice_session
   .push_audio()` too (plus the same auto-`start_turn()` logic
   `_handle_audio_data()` already had). Added a source-based regression
   test (`test_binary_audio_frames_route_through_voice_session`).
2. **Suggestion**: `_HandlerVoiceSession`'s inherited `_send()` (used by
   `_run_turn()` for `error`/`reconnect` frames) only suppressed
   `ConnectionResetError`, unlike the handler's own `_send_message()`
   (blanket `try/except Exception` + log). Overrode `_send()` to route
   through `_send_message()` for consistency.

The reviewer also confirmed (not a finding): the `pkgutil.extend_path`
namespace fix works as verified, the frame-protocol adapter is correct,
and `resolve_provider_client`/`VoiceProvider` re-export are unaffected.
One `parrot/voice/__init__.py` docstring inaccuracy (claimed
`handler.py`/`models.py` were core-provided; they're integrations-local)
was also fixed per the review.

### Feature-wide follow-up recommendation

All 8 tasks are now implemented. Given the depth of judgment calls in
this task alone (frame-protocol adapter, namespace-packaging fix,
go_away/reconnect bridging) and that **no test in this entire feature
could be executed** due to the sandbox's broken venv, a full `pytest`
run across `packages/ai-parrot/tests/{bots,clients,voice,models}/` and
`packages/ai-parrot-integrations/tests/voice/` in a properly-provisioned
environment is strongly recommended before merging FEAT-416, ahead of
`/sdd-done`'s own verification step.
