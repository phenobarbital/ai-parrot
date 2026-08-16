# TASK-2017: Root-cause the confirm-answer WebSocket hang

**Feature**: FEAT-395 — Fix deadlock in AudioFormWSHandler confirm_answer flow
**Spec**: `sdd/specs/audio-ws-confirm-answer-deadlock.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

`test_ws_low_confidence_confirm`, `test_ws_low_confidence_reject_reprompts`,
and `test_ws_high_confidence_auto_advance` in
`packages/parrot-formdesigner/tests/formdesigner/test_audio_integration.py`
hang indefinitely (FEAT-389 skip-marked them pending this investigation).
This task implements Module 1 of the spec: confirm and document the root
cause before Module 2 (TASK-2018) applies the fix.

---

## Scope

- Verify the root cause already identified and written into the spec's
  "Root Cause (CONFIRMED)" section (§2) is accurate against the current
  `dev` code: re-read `api/audio_ws.py:653-696` (`_handle_answer_audio`)
  and confirm `_MIN_AUDIO_BYTES = 256` / `_sniff_audio_suffix`
  (`api/audio_ws.py:68-99`) reject the tests' 16-byte
  `b"fake-audio-frame"` payload with a single `EMPTY_AUDIO` error before
  reaching the transcriber — explaining why each test's second
  `receive_json()` blocks forever.
- Confirm this is **not** a lock/`await`-never-resolves bug in
  `_handle_confirm_answer`/`_advance_session`/`_send_question` — those
  code paths are never reached because the message loop stalls one step
  earlier, in `_handle_answer_audio`.
- Confirm no production code path is affected (test-fixture-only issue).
- No code changes in this task — this is a verification/documentation
  task. The spec (already updated) is the artifact; this task's
  Completion Note records that the verification re-ran successfully.

**NOT in scope**: any change to `api/audio_ws.py` or the test file (that's
TASK-2018).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| (none — verification only) | — | Confirms spec §2 "Root Cause (CONFIRMED)" against current `dev` code |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.api.audio_ws import AudioFormWSHandler  # verified: packages/parrot-formdesigner/src/parrot_formdesigner/api/audio_ws.py
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/api/audio_ws.py
_MIN_AUDIO_BYTES = 256  # line 68
def _sniff_audio_suffix(data: bytes) -> Optional[str]: ...  # line 71

class AudioFormWSHandler:
    async def _handle_answer_audio(
        self, ws: web.WebSocketResponse, audio_bytes: bytes,
        session: AudioSessionState, audio_cache: dict[int, str],
    ) -> None: ...  # line 653
    # line 689: if len(audio_bytes) < _MIN_AUDIO_BYTES:
    #               await self._send_error(ws, "EMPTY_AUDIO", ...); return
```

### Does NOT Exist
- ~~A lock, semaphore, or unresolved `await` inside
  `_handle_confirm_answer`/`_advance_session`/`_send_question`~~ — these
  are never reached by the hanging tests; the message loop stalls
  earlier, in `_handle_answer_audio`'s payload-size gate.
- ~~Any `form_id`/`form_uid` involvement~~ — confirmed unrelated (FEAT-389
  is orthogonal).

---

## Implementation Notes

Re-run the reproduction from the spec to reconfirm the hang and its
location before signing off:

```bash
cd packages/parrot-formdesigner
timeout 20 pytest "tests/formdesigner/test_audio_integration.py::TestHybridVoiceFlows::test_ws_low_confidence_confirm" -v
# expect: exit 124 (timeout), confirming the pre-existing hang on dev
```

Add a `self.logger.debug(...)` read-through (already present at
`api/audio_ws.py:683-688`) confirms the frame size/magic-byte logging
already exists — no new instrumentation is needed, the existing debug log
is sufficient evidence once enabled.

### References in Codebase
- `packages/parrot-formdesigner/src/parrot_formdesigner/api/audio_ws.py:653-696` — `_handle_answer_audio`, the actual stall point
- `packages/parrot-formdesigner/tests/formdesigner/test_audio_integration.py:585-683` — the three affected tests

---

## Acceptance Criteria

- [x] Re-verified: `_handle_answer_audio` rejects `b"fake-audio-frame"` (16 bytes) via `_MIN_AUDIO_BYTES` and returns after one `EMPTY_AUDIO` message
- [x] Re-verified: `_handle_confirm_answer`/`_advance_session`/`_send_question` are not implicated — no lock/deadlock exists there
- [x] Reproduction command confirms the hang (`timeout 20 pytest ... test_ws_low_confidence_confirm` → exit 124) on the current `dev` HEAD
- [x] Root cause documented in the Completion Note below

---

## Test Specification

No new tests — this is a verification task. The reproduction command
above (run under `timeout`) is the test.

---

## Agent Instructions

When you pick up this task:

1. Read the spec at the path above, specifically §2 "Root Cause (CONFIRMED)".
2. Re-verify the contract above against current `dev` code (`grep`/`read` `api/audio_ws.py`).
3. Re-run the reproduction command to reconfirm the hang.
4. Fill in the Completion Note, move this file to `sdd/tasks/completed/`, update the per-spec index.

---

## Completion Note

**Completed by**: sdd-worker (Claude, Sonnet)
**Date**: 2026-07-31
**Notes**: Re-verified the spec's confirmed root cause against current `dev`
code in the worktree:

1. Read `api/audio_ws.py:68-99` — `_MIN_AUDIO_BYTES = 256` and
   `_sniff_audio_suffix` unchanged from what the spec documents.
2. Read `api/audio_ws.py:653-704` (`_handle_answer_audio`) — confirmed the
   `len(audio_bytes) < _MIN_AUDIO_BYTES` check (line 689) fires and
   returns after sending one `EMPTY_AUDIO` error, *before* the suffix
   check and before ever reaching the transcriber/confirm logic.
3. Reproduced the hang live: temporarily stripped the three
   `@pytest.mark.skip` decorators from a working-tree copy of
   `test_audio_integration.py` (never committed — reverted via
   `git checkout --` immediately after), then ran
   `timeout 20 pytest ...::test_ws_low_confidence_confirm` → **exit 124**,
   confirming the hang reproduces on current `dev` HEAD.
4. Ran the same reproduction with `--log-cli-level=DEBUG`, capturing the
   handler's own debug line:
   `Received audio frame: 16 bytes, magic=66 61 6b 65 2d 61 75 64,
   detected=unknown` — proving the 16-byte `b"fake-audio-frame"` payload
   is what's rejected, and that only one message (`EMPTY_AUDIO`) is ever
   sent back, explaining why the test's second `receive_json()` blocks
   forever.
5. Confirmed `_handle_confirm_answer`, `_advance_session`, and
   `_send_question` are never reached by any of the three hanging tests
   — the stall is entirely upstream, in `_handle_answer_audio`'s payload
   gate. No lock, semaphore, or unresolved `await` exists in those
   methods.

**Root cause (confirmed)**: stale test fixture, not a production deadlock.
See spec §2 "Root Cause (CONFIRMED)" for the full writeup — this task
independently re-verified it against the current worktree's code and a
live reproduction, and found no discrepancy.

**Deviations from spec**: none. The working tree was left clean (no
diff) after the temporary skip-removal used for reproduction — that
change was never committed and was reverted before finishing this task.
