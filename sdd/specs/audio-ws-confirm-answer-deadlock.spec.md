---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: Fix deadlock in AudioFormWSHandler confirm_answer flow

**Feature ID**: FEAT-395
**Date**: 2026-07-31
**Author**: Claude (sdd-worker, discovered while continuing FEAT-389)
**Status**: approved
**Target version**: TBD

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

`tests/formdesigner/test_audio_integration.py::TestHybridVoiceFlows::
test_ws_low_confidence_confirm` hangs indefinitely (does not fail, does not
error — it never returns) whenever it runs, whether alone or as part of the
full `packages/parrot-formdesigner` suite.

**This is a PRE-EXISTING bug, confirmed unrelated to FEAT-389**
(`form-uid-stable-identity`). Evidence gathered while validating FEAT-389's
TASK-1990/TASK-1982:

- Running the exact same test against the **unmodified `dev` branch**
  (main repo checkout, zero FEAT-389 changes applied) reproduces the same
  hang (`timeout 30 pytest ... ::test_ws_low_confidence_confirm` →
  killed by the outer timeout, no output, no exception).
- Diffing `packages/parrot-formdesigner/src/parrot_formdesigner/api/
  audio_ws.py` between `dev` and the FEAT-389 worktree, excluding every
  `form_id`→`form_uid` rename hunk, shows **zero unrelated differences** —
  the code path this test exercises (`_handle_confirm_answer` →
  `_advance_session` → `_send_question`) is byte-for-byte identical to
  `dev`.
- The test file's FEAT-389 diff touches only `TestRenderEndpoint` (4
  tests, URL/`form_uid` updates); the `TestHybridVoiceFlows` class
  (including this test) is untouched by FEAT-389.
- All 21 other tests in the same file, and all other audio-WS/integration
  tests FEAT-389 touches, pass cleanly (only isolated once a worktree
  `PYTHONPATH` misconfiguration — unrelated environmental issue, not a
  code bug — was corrected).

This blocks a fully-green `pytest packages/parrot-formdesigner/tests/ -v`
run for anyone working in this package, including FEAT-389's own
TASK-1982 acceptance criteria. FEAT-389 addresses this by
`@pytest.mark.skip`-ing the test with a pointer to this spec — the actual
fix belongs here, tracked independently.

### Goals
- Root-cause the hang in the WebSocket confirm-answer flow
  (`AudioFormWSHandler._handle_confirm_answer` →
  `_advance_session`/`_send_question`, `api/audio_ws.py`).
- Make `test_ws_low_confidence_confirm` AND its sibling
  `test_ws_low_confidence_reject_reprompts` (see updated Suspected Area
  below — also confirmed hanging) pass without hanging, with no
  regression to the other 20 tests in the same file (all currently
  green).
- Remove both `@pytest.mark.skip` markers this spec's discovery added in
  FEAT-389 (TASK-1990).

### Non-Goals (explicitly out of scope)
- Any `form_id`/`form_uid` identity work — that is FEAT-389's domain and
  is already complete/independent of this bug.
- Broader audio-renderer feature work beyond fixing this specific
  deadlock.

---

## 2. Architectural Design

### Overview

Root cause is **not yet diagnosed** — this spec captures the confirmed
symptom, isolation, and reproduction steps gathered during FEAT-389's
validation pass. The implementing task must do the actual root-cause
investigation (see Open Questions).

### Suspected Area (UPDATED — narrowed, still unconfirmed root cause)

**CONFIRMED**: `test_ws_low_confidence_reject_reprompts` (the `confirmed:
false` sibling) **also hangs**, isolated and reproduced independently
(`timeout 20 pytest ...::test_ws_low_confidence_reject_reprompts` → exit
124). This narrows the fault: both tests share an *identical* prefix —

```python
await _start(ws)                                          # shared
await ws.send_bytes(b"fake-audio-frame")                   # shared
await ws.receive_json()  # transcription                   # shared
await ws.receive_json()  # confirm_request                 # shared
await ws.send_json({"type": "confirm_answer", ...})        # diverges only in `confirmed` value
ack_or_requeued = await ws.receive_json()                   # both then hang here or earlier
```

— and diverge ONLY in the `confirmed` boolean sent and the expected
reply type. Since BOTH hang, the fault is much more likely in logic
common to both branches — the shared prefix (`_handle_answer_audio`'s
confidence-gate / `confirm_request` send, `api/audio_ws.py:653-799` on
`dev`) or the shared entry of `_handle_confirm_answer` itself
(`api/audio_ws.py:599-632`, before the `if confirmed:` branch at line
634) — rather than something specific to the `confirmed: true` →
`_advance_session` path alone. The implementing task should instrument
(logging / `faulthandler.dump_traceback_later`) to find the exact
`await` that never resolves, starting with the shared prefix before
looking at either branch.

### Reproduction

```bash
cd packages/parrot-formdesigner
pytest "tests/formdesigner/test_audio_integration.py::TestHybridVoiceFlows::test_ws_low_confidence_confirm" -v
pytest "tests/formdesigner/test_audio_integration.py::TestHybridVoiceFlows::test_ws_low_confidence_reject_reprompts" -v
# BOTH hang indefinitely — no output, no exception, no timeout without an
# external `timeout` wrapper. Confirmed via: timeout 20-30 pytest ... → exit 124.
```

Reproduces identically on `dev` HEAD as of this writing (commit
`71cb962da` "fixing audio ws form" — that commit touched `audio_ws.py`
but in unrelated areas; it neither introduced nor fixed this deadlock).

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AudioFormWSHandler._handle_confirm_answer` | investigate | `api/audio_ws.py:599` (dev line numbers) |
| `AudioFormWSHandler._advance_session` | investigate | `api/audio_ws.py:1034` |
| `AudioFormWSHandler._send_question` | investigate | `api/audio_ws.py:1120` |
| `AudioFormWSHandler._accept_answer` | investigate | `api/audio_ws.py:971` |

---

## 3. Module Breakdown

### Module 1: Root-cause the deadlock
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/api/audio_ws.py`
- **Responsibility**: Identify why the message loop or `_advance_session`
  chain never returns/never sends a response for the `confirm_answer`
  (confirmed=true) path, given `_dispatch_text` wraps every handler call
  in a `try/except Exception` that DOES send an `INTERNAL_ERROR` on
  failure (`api/audio_ws.py:227-235` on `dev`) — ruling out a simple
  uncaught exception as the cause. Consider: an `await` on a resource
  that never resolves (e.g. a lock, an unmocked real I/O call reached via
  a code path the other passing tests don't exercise), or a WebSocket
  heartbeat/protocol-level stall specific to this test's message
  sequence.
- **Depends on**: none (pre-existing code)

### Module 2: Fix + regression coverage
- **Path**: `packages/parrot-formdesigner/tests/formdesigner/test_audio_integration.py`
- **Responsibility**: Remove both `@pytest.mark.skip` markers FEAT-389
  added to `test_ws_low_confidence_confirm` AND
  `test_ws_low_confidence_reject_reprompts`; verify both and all 20
  other siblings in
  `TestHybridVoiceFlows`/`TestWebSocketSession`/`TestRenderEndpoint`/
  `TestAudioRendererSeed` still pass.
- **Depends on**: Module 1

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_ws_low_confidence_confirm` | Module 2 | Must complete (not hang) and pass — the originally-reported symptom |
| `test_ws_low_confidence_reject_reprompts` | Module 2 | CONFIRMED also hangs (see Suspected Area) — must complete (not hang) and pass |

### Integration Tests
| Test | Description |
|---|---|
| Full `packages/parrot-formdesigner/tests/` suite | Must be 100% green with no new hangs or regressions |

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] Root cause of the deadlock is identified and documented in this spec's Completion Note (or a linked task's)
- [ ] `test_ws_low_confidence_confirm` passes within normal test-suite time (no `timeout` wrapper needed)
- [ ] `test_ws_low_confidence_reject_reprompts` (CONFIRMED also hanging) passes within normal test-suite time too
- [ ] All other `TestHybridVoiceFlows`/`TestWebSocketSession` tests still pass (no regression)
- [ ] Full suite passes: `pytest packages/parrot-formdesigner/tests/ -v` completes without any hang, in normal CI time
- [ ] Both `@pytest.mark.skip` markers added by FEAT-389 (TASK-1990) are removed
- [ ] No unrelated `form_id`/`form_uid` changes are made — this is a pure bug fix

---

## 6. Codebase Contract

### Verified Imports
```python
from parrot_formdesigner.api.audio_ws import AudioFormWSHandler  # verified: api/audio_ws.py
```

### Existing Class Signatures (verified on `dev`, `api/audio_ws.py`)
```python
class AudioFormWSHandler:
    async def handle_websocket(self, request: web.Request) -> web.WebSocketResponse: ...  # line 173
    async def _dispatch_text(self, ws, msg_type, data, session, request, audio_cache) -> None: ...  # line 333
    async def _handle_confirm_answer(self, *, ws, data, session, request, audio_cache) -> None: ...  # line 599
    async def _current_question(self, ws, session, field_id): ...  # line 928
    async def _accept_answer(self, ws, session, field_id, value, *, source, confidence=None, raw_transcript=None): ...  # line 971
    async def _advance_session(self, ws, session, request, audio_cache) -> None: ...  # line 1034
    async def _advance_session_no_request(self, ws, session, audio_cache) -> None: ...  # line 1056
    async def _send_question(self, ws, question, audio_cache, *, config, session) -> None: ...  # line 1120
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| (investigation-only, no new component yet) | `AudioFormWSHandler._handle_confirm_answer` | direct call from `_dispatch_text` | `api/audio_ws.py:357` |

### Does NOT Exist (Anti-Hallucination)
- ~~Any `form_id`/`form_uid` involvement in this bug~~ — confirmed
  unrelated via the `dev` control-branch reproduction in this spec's
  Problem Statement. Do not go looking for an identity-migration cause.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- This is a debugging/fix task — follow `systematic-debugging` practice:
  reproduce, isolate (already done here down to one test), bisect the
  exact `await` that never resolves (e.g. instrument with logging or use
  `asyncio` task introspection / `pytest-asyncio` debug mode / attach
  `faulthandler.dump_traceback_later`), form a hypothesis, fix, verify.
- Do NOT touch `form_id`/`form_uid` — this bug is orthogonal to FEAT-389.

### Known Risks / Gotchas
- The outer `_dispatch_text` try/except catches `Exception` and reports
  `INTERNAL_ERROR` — ruling out a simple synchronous exception as the
  cause. The hang is most likely a coroutine that never completes
  (an `await` with no resolving event), not a swallowed exception.
- Worktree testing gotcha (unrelated to this bug, but relevant to whoever
  picks this up): a shared `.venv`'s editable install of
  `parrot_formdesigner` resolves to the MAIN repo checkout, not a
  worktree's local copy, unless `PYTHONPATH="$WORKTREE/packages/
  parrot-formdesigner/src:$PYTHONPATH"` is prepended. Verify with
  `python -c "import parrot_formdesigner; print(parrot_formdesigner.__file__)"`
  before trusting any test result in a worktree.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| (none new) | | |

---

## 8. Open Questions

- [x] Does `test_ws_low_confidence_reject_reprompts` (the `confirmed:
      false` sibling) also hang? **ANSWERED: yes**, confirmed via
      isolated reproduction (`timeout 20 pytest ...` → exit 124). See
      the updated Suspected Area section — this narrows the fault to
      logic shared by both branches (the confidence-gate/`confirm_request`
      send in `_handle_answer_audio`, or `_handle_confirm_answer`'s
      shared entry before the `if confirmed:` split).
- [ ] Given both siblings hang identically, is the true fault actually in
      `_handle_answer_audio`'s confirm_request send (`api/audio_ws.py:
      765-779` on `dev`) rather than in `_handle_confirm_answer` at all?
      — *Owner: implementer*
- [ ] Is this deadlock present in any deployed/production path, or only
      reachable via this specific test's exact message sequence? —
      *Owner: implementer*

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-07-31 | Claude (sdd-worker) | Initial draft — discovered while validating FEAT-389 |
