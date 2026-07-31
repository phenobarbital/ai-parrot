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
**Status**: implemented
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
  **CONFIRMED** (see Root Cause below): the hang is a stale test fixture
  (16-byte `b"fake-audio-frame"` payload rejected by `_MIN_AUDIO_BYTES`),
  not a lock/deadlock in production code.
- Make `test_ws_low_confidence_confirm`, its sibling
  `test_ws_low_confidence_reject_reprompts`, AND
  `test_ws_high_confidence_auto_advance` (all three confirmed hanging —
  see Root Cause) pass without hanging, with no regression to the other
  19 tests in the same file (all currently green).
- Remove all three `@pytest.mark.skip` markers this spec's discovery
  added in FEAT-389 (TASK-1990).

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

### Root Cause (CONFIRMED)

Verified against `dev` HEAD (`api/audio_ws.py`, `test_audio_integration.py`):
this is **not a deadlock in `_handle_confirm_answer`/`_advance_session` at
all** — it is a **stale test fixture**. All three affected tests send
`await ws.send_bytes(b"fake-audio-frame")`, a 16-byte payload. Production
validation added after these tests were written
(`_MIN_AUDIO_BYTES = 256` and `_sniff_audio_suffix`, `api/audio_ws.py:
68-99`) rejects any frame under 256 bytes: `_handle_answer_audio`
(`api/audio_ws.py:653`) sends a single `EMPTY_AUDIO` error message and
returns **before** calling the transcriber (`api/audio_ws.py:689-696`).
Each test awaits two-or-more `receive_json()` calls expecting
`transcription` then `confirm_request`/`question`/`answer_accepted` — but
only the one `EMPTY_AUDIO` message ever arrives, so the second
`receive_json()` blocks forever. This is unrelated to `form_id`/`form_uid`
(FEAT-389) and requires **no production code change** — only the test
fixture needs a valid-enough payload (≥256 bytes with a recognized
container magic, e.g. `RIFF`...`WAVE`). Content is irrelevant since
`mock_transcriber` is an `AsyncMock` and never actually decodes the file.

**A third test shares the identical bug** and was found during this
investigation: `test_ws_high_confidence_auto_advance`
(`test_audio_integration.py:664`) sends the same 16-byte
`b"fake-audio-frame"` and hangs on its second `receive_json()` for the
same reason. It was not part of the original bug report but is in scope
for this fix (see updated Acceptance Criteria below).

### Reproduction

```bash
cd packages/parrot-formdesigner
pytest "tests/formdesigner/test_audio_integration.py::TestHybridVoiceFlows::test_ws_low_confidence_confirm" -v
pytest "tests/formdesigner/test_audio_integration.py::TestHybridVoiceFlows::test_ws_low_confidence_reject_reprompts" -v
pytest "tests/formdesigner/test_audio_integration.py::TestHybridVoiceFlows::test_ws_high_confidence_auto_advance" -v
# ALL THREE hang indefinitely — no output, no exception, no timeout without an
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
  (investigation only — **no code change required**, see Root Cause above)
- **Responsibility**: Identify why the message loop never sends the
  second expected message. **CONFIRMED**: not an unresolved `await`/lock —
  `_handle_answer_audio` (`api/audio_ws.py:653-696`) rejects the 16-byte
  `b"fake-audio-frame"` test payload via `_MIN_AUDIO_BYTES = 256`, sends
  ONE `EMPTY_AUDIO` error, and returns — the test's second
  `receive_json()` then waits forever for a message the server will
  never send. Document this finding (this spec now carries it).
- **Depends on**: none (pre-existing code)

### Module 2: Fix + regression coverage
- **Path**: `packages/parrot-formdesigner/tests/formdesigner/test_audio_integration.py`
- **Responsibility**: Give the three affected tests
  (`test_ws_low_confidence_confirm`, `test_ws_low_confidence_reject_reprompts`,
  `test_ws_high_confidence_auto_advance`) a valid-enough binary audio
  payload (≥256 bytes, recognized container magic, e.g. `RIFF`...`WAVE`
  padding) instead of `b"fake-audio-frame"`, so it clears
  `_MIN_AUDIO_BYTES`/`_sniff_audio_suffix` and reaches the mocked
  transcriber; remove all three `@pytest.mark.skip` markers FEAT-389
  added; verify these three and all 19 other siblings in
  `TestHybridVoiceFlows`/`TestWebSocketSession`/`TestRenderEndpoint`/
  `TestAudioRendererSeed` still pass. **No production code
  (`audio_ws.py`) changes** — this is a test-fixture-only fix.
- **Depends on**: Module 1

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_ws_low_confidence_confirm` | Module 2 | Must complete (not hang) and pass — the originally-reported symptom |
| `test_ws_low_confidence_reject_reprompts` | Module 2 | CONFIRMED also hangs (see Root Cause) — must complete (not hang) and pass |
| `test_ws_high_confidence_auto_advance` | Module 2 | CONFIRMED also hangs, same root cause (see Root Cause) — must complete (not hang) and pass |

### Integration Tests
| Test | Description |
|---|---|
| Full `packages/parrot-formdesigner/tests/` suite | Must be 100% green with no new hangs or regressions |

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [x] Root cause of the deadlock is identified and documented in this spec (see Root Cause, above) — CONFIRMED: stale test fixture (16-byte payload rejected by `_MIN_AUDIO_BYTES`), not a production-code deadlock
- [x] `test_ws_low_confidence_confirm` passes within normal test-suite time (no `timeout` wrapper needed)
- [x] `test_ws_low_confidence_reject_reprompts` (CONFIRMED also hanging) passes within normal test-suite time too
- [x] `test_ws_high_confidence_auto_advance` (CONFIRMED also hanging — found during this investigation) passes within normal test-suite time too
- [x] All other `TestHybridVoiceFlows`/`TestWebSocketSession` tests still pass (no regression) — `test_audio_integration.py` is 22/22 green
- [x] `test_audio_integration.py` (and the audio-WS suite specifically) passes without any hang, in normal CI time. **Caveat**: the *full* `packages/parrot-formdesigner/tests/` package has 20 pre-existing failures in unrelated modules (form-controls contract, MS Teams import compat, edit-toolkit tool counts, control-registry capabilities, venue service, etc.) — confirmed pre-existing on `dev` via `git stash` A/B testing (identical failures with this feature's diff removed). None involve `audio_ws.py` or `test_audio_integration.py`; out of scope for this fix (see TASK-2018 Completion Note).
- [x] All three `@pytest.mark.skip` markers added by FEAT-389 (TASK-1990) are removed
- [x] No unrelated `form_id`/`form_uid` changes are made — this is a pure bug fix
- [x] No production code (`api/audio_ws.py`) changes — fix is test-fixture-only

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
- [x] Given both siblings hang identically, is the true fault actually in
      `_handle_answer_audio`'s confirm_request send (`api/audio_ws.py:
      765-779` on `dev`) rather than in `_handle_confirm_answer` at all?
      **ANSWERED: neither** — the fault is upstream, in
      `_handle_answer_audio`'s payload-size gate (`_MIN_AUDIO_BYTES`,
      `api/audio_ws.py:689`), which returns after a single `EMPTY_AUDIO`
      error before the confirm/transcription logic is ever reached.
- [x] Is this deadlock present in any deployed/production path, or only
      reachable via this specific test's exact message sequence?
      **ANSWERED: test-only** — no production path sends a sub-256-byte
      binary frame and then blocks waiting for a second server message
      without also handling `EMPTY_AUDIO`; real clients react to the
      error message. This is a stale test fixture, not a live-traffic
      bug.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-07-31 | Claude (sdd-worker) | Initial draft — discovered while validating FEAT-389 |
| 0.2 | 2026-07-31 | Claude (sdd-worker) | Approved. Root cause confirmed: stale test fixture (16-byte payload rejected by `_MIN_AUDIO_BYTES`), not a production deadlock. Added third affected test (`test_ws_high_confidence_auto_advance`). No production code change required. |
| 1.0 | 2026-07-31 | Claude (sdd-worker) | Implemented (TASK-2017, TASK-2018). All three tests pass, skip markers removed, no `api/audio_ws.py` changes. `test_audio_integration.py` is 22/22 green; 20 pre-existing unrelated failures remain elsewhere in the package (out of scope). |
