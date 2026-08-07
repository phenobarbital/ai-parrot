# TASK-2171: VoiceSession: thread VoiceStreamOptions + add build_frames relay hook

**Feature**: FEAT-418 — Google Gemini Live ↔ Nova 2 Sonic Homologation
**Spec**: `sdd/specs/googlelive-nova2-audiobot-homologation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L
**Depends-on**: TASK-2164, TASK-2165
**Assigned-to**: unassigned
**Parallel-safe**: no — Shared session layer — both provider lanes and the handler converge here.

---

## Context

`VoiceSession._run_turn()` calls `stream_voice()` with only `system_prompt` and
`session_id` (`voice/session.py:182-186`). Every `VoiceConfig` knob FEAT-416
added is dropped for any consumer that drives the session directly — which is
exactly what the new example (TASK-2178) will do.

The integrations handler works around this by re-implementing the entire turn
loop on top of `bot.ask_stream()` (`handler.py:305-360`), duplicating ~60 lines
of reconnection logic purely so it can emit a richer frame protocol from its own
`_relay()` override. A relay extension hook removes that reason to duplicate.

Implements: **Spec §3 Module 6 (threading + hook)**.

---

## Scope

- Thread options into `stream_voice()`: accept a `VoiceStreamOptions` (or derive
  it from `self.voice_config.to_stream_options()`) and pass it on every turn
  **and on every reconnect iteration** of the loop at `voice/session.py:180`.
- Add a `build_frames(resp, turn_no) -> list[dict]` hook containing today's
  frame construction from `_relay()` (`voice/session.py:253-316`), and have
  `_relay()` call it and send whatever it returns.
- Keep `_relay()`'s current output byte-for-byte identical for the default
  implementation, so existing tests and frontends are unaffected.
- Tests per spec §4, including that options survive a reconnect.

**NOT in scope**: capability preflight / `capability_notice` (TASK-2172);
deleting the handler's `_run_turn()` (TASK-2174).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/voice/session.py` | MODIFY | Options threading + `build_frames()` hook |
| `packages/ai-parrot/tests/voice/test_voice_session_options.py` | CREATE | Threading + hook tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (line numbers verified 2026-08-07). The implementing agent MUST use these exact
> imports, class names, and method signatures. **DO NOT** invent, guess, or assume any
> import, attribute, or method not listed here. If you need something not listed,
> VERIFY it exists first with `grep` or `read`.

### Verified Imports

```python
from parrot.voice.session import VoiceSession                 # voice/session.py:36
from parrot.clients.live import LiveVoiceResponse             # voice/session.py:29
from parrot.clients.protocols import VoiceCapable             # voice/session.py:30
from parrot.models.voice import VoiceConfig, VoiceStreamOptions   # voice/session.py:31 (+ TASK-2164)
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/voice/session.py
class VoiceSession:                                           # line 36
    def __init__(self, client: VoiceCapable,                  # line 53
                 send_fn: Callable[[dict], Awaitable[None]],
                 system_prompt: str,
                 voice_config: Optional[VoiceConfig] = None,
                 session_id: Optional[str] = None) -> None:
        self._reconnect_count = 0                             # line 73 — lifetime, not per-turn

    async def start_turn(self) -> None:                       # line 77
    async def push_audio(self, pcm: bytes) -> None:           # line 91
    async def end_turn(self) -> None:                         # line 99 — paced silence, do not touch
    async def close(self) -> None:                            # line 136

    async def _run_turn(self, turn_no: int) -> None:          # line 165
        while True:                                           # line 180 — reconnect loop
            stream = self.client.stream_voice(                # line 182 — NO options today
                self._audio_iterator(queue),
                system_prompt=self.system_prompt,
                session_id=self.session_id,
            )
            async for resp in stream:
                await self._relay(resp, turn_no)              # line 194 — BEFORE reconnect check
                if not (resp.metadata.get("reconnect_required")   # line 196
                        and self.voice_config.reconnect_on_limit):
                    continue

    async def _relay(self, resp: LiveVoiceResponse, turn_no: int) -> None:   # line 253
        if "error" in resp.metadata: ...                      # line 258 — membership, not truthiness
        if resp.text: ... "role": resp.role                   # lines 266-272
        if resp.audio_data: ...                               # line 274
        for call in resp.tool_calls: ...                      # line 283
        if resp.is_interrupted: ...                           # line 293
        if resp.is_complete: ...                              # line 296

    async def _send(self, payload: dict) -> None:             # line 318 — suppresses ConnectionResetError
```

### Does NOT Exist

- ~~`VoiceSession.build_frames()`~~ — created by THIS task.
- ~~`VoiceSession` passing any VoiceConfig-derived kwarg~~ — it passes none today (`voice/session.py:182-186`).
- ~~A `stt_only` attribute on `VoiceSession`~~ — none; it arrives via the options object.
- ~~`VoiceSession` reacting to `metadata["go_away"]`~~ — it does not, and must not; Gemini maps that to `reconnect_required` in TASK-2168.
- ~~An `__init__.py` in `packages/ai-parrot/src/parrot/voice/`~~ — deliberately absent (PEP 420 + `pkgutil.extend_path` on the integrations side). Adding one breaks `parrot.voice.session` resolution.

---

## Implementation Notes

### Key Constraints
- **Preserve the FEAT-416 invariants**, all of which have tests:
  - relay the frame (with its `tool_calls`) *before* evaluating
    `reconnect_required` (`voice/session.py:188-200`);
  - never `await self._task` from inside the task itself (`:216-219`);
  - `_reconnect_count` is lifetime-scoped, reset only in `__init__` (`:73`).
- **Do not touch `end_turn()`** (`:99-134`). Its 20 ms-paced silence frames exist
  because bursting them makes provider VAD miss end-of-speech; the pacing is
  load-bearing and has a dedicated test.
- Options must be re-passed on each reconnect iteration, not captured once
  outside the loop — a reconnect that drops them is exactly the bug being fixed.
- `build_frames()` is sync and returns a list; `_relay()` stays async and does
  the sending, so subclasses never need to know about `_send()`.

---

## Acceptance Criteria

- [ ] `stream_voice()` receives the projected options on the first turn
- [ ] Options are re-passed on every reconnect iteration
- [ ] `build_frames()` exists; overriding it changes emitted frames without touching `_run_turn()`
- [ ] Default frame output is unchanged (existing tests pass untouched)
- [ ] Relay-before-reconnect ordering preserved
- [ ] `end_turn()` silence pacing untouched
- [ ] Tests pass: `pytest packages/ai-parrot/tests/voice/ -v`
- [ ] `ruff check packages/ai-parrot/src/parrot/voice/session.py`

---

## Test Specification

> Minimal scaffold. The agent must make these pass and add more as needed.

```python
# packages/ai-parrot/tests/voice/test_voice_session_options.py
import pytest
from parrot.models.voice import VoiceConfig
from parrot.voice.session import VoiceSession


class RecordingClient:
    """VoiceCapable double that records the options it was handed."""
    def __init__(self):
        self.calls = []
    async def stream_voice(self, audio_iterator, system_prompt=None,
                           session_id=None, options=None, **kwargs):
        self.calls.append(options)
        yield ...


class TestOptionThreading:
    async def test_options_forwarded(self):
        client = RecordingClient()
        session = VoiceSession(client, send_fn=..., system_prompt="x",
                               voice_config=VoiceConfig(temperature=0.3))
        await session.start_turn(); await session.end_turn()
        assert client.calls[0].temperature == 0.3

    async def test_options_survive_reconnect(self):
        """Regression: a reconnect that drops options is the bug being fixed."""
        client = ReconnectingRecordingClient()
        ...
        assert all(o is not None for o in client.calls)
        assert len(client.calls) >= 2


class TestRelayHook:
    async def test_build_frames_override_used(self):
        class Custom(VoiceSession):
            def build_frames(self, resp, turn_no):
                return [{"type": "custom"}]
        ...
        assert frames[0]["type"] == "custom"

    async def test_default_frames_unchanged(self):
        """Existing frontends must see byte-identical output."""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/googlelive-nova2-audiobot-homologation.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-08-07
**Notes**: Threaded `options=self.voice_config.to_stream_options()` into
the `stream_voice()` call inside `_run_turn()`'s `while True:` reconnect
loop — recomputed on every iteration (not hoisted above the loop), so a
reconnect that would silently drop the caller's options is structurally
impossible, not just untested. Extracted `_relay()`'s entire frame-
construction body (error/text/audio/tool_call/interrupted/turn_complete)
verbatim into a new sync `build_frames(resp, turn_no) -> list[dict]`
method; `_relay()` now just iterates `build_frames()`'s return value and
calls `self._send()` on each. Preserved every FEAT-416 invariant
call-for-call: relay-before-reconnect-check ordering (`build_frames()` is
called from within `_relay()`, which is still awaited before the
`reconnect_required` check), the early-return-on-error short-circuit
(matches `_relay()`'s old `return` after the error frame), and
`end_turn()`'s silence-pacing loop (untouched — confirmed unchanged with
`git diff`). 9 new tests in `tests/voice/test_voice_session_options.py`,
including an explicit `test_build_frames_is_sync` regression guard and a
byte-for-byte frame-shape assertion in `test_default_frames_unchanged`.
All 10 real pre-existing `tests/voice/` tests still pass unmodified
(the file's 11th test, `test_no_aiohttp_import`, is the already-documented
pre-existing unrelated failure).

While running the FULL `tests/clients/` suite to verify no cross-file
regressions from TASK-2170's landed changes, found two pre-existing test
files that were missed when TASK-2170 was committed:
`test_nova_inference_params.py::test_default_inference_params` (asserted
the old `maxTokens == 1024`) and `test_nova_turn_state.py::TestRoleAttribution`
(asserted uppercase `"USER"`/`"ASSISTANT"`). Both are direct, intentional
consequences of TASK-2170's spec-mandated changes (§3 Module 4, §8
resolved decisions), not new bugs — fixed in a separate preceding commit
(`fix(...): update pre-existing Nova tests for TASK-2170's spec-mandated
max_tokens/role changes`) to keep that fix distinctly attributable from
TASK-2171's own scope. Confirmed via a targeted `dev`-branch run that
`test_nova_protocol_frames.py::TestOpeningSequence` (4 tests) and
`test_parallel_tool_execution.py::test_parallel_error_isolation` are
pre-existing failures unrelated to any part of this feature — left
untouched.

**Deviations from spec**: none for this task's own scope. One
process note: TASK-2170 was completed/committed before this task ran the
full-suite regression check that surfaced the two Nova test files above
— worth doing a full-suite pass at the END of each task in future
features, not just the domain-scoped subset the task names.
