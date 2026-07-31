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

- [ ] Re-verified: `_handle_answer_audio` rejects `b"fake-audio-frame"` (16 bytes) via `_MIN_AUDIO_BYTES` and returns after one `EMPTY_AUDIO` message
- [ ] Re-verified: `_handle_confirm_answer`/`_advance_session`/`_send_question` are not implicated — no lock/deadlock exists there
- [ ] Reproduction command confirms the hang (`timeout 20 pytest ... test_ws_low_confidence_confirm` → exit 124) on the current `dev` HEAD
- [ ] Root cause documented in the Completion Note below

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

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
