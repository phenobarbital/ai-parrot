# TASK-2018: Fix stale audio-frame test fixture + remove skip markers

**Feature**: FEAT-395 — Fix deadlock in AudioFormWSHandler confirm_answer flow
**Spec**: `sdd/specs/audio-ws-confirm-answer-deadlock.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2017
**Assigned-to**: unassigned

---

## Context

TASK-2017 confirmed the root cause: three tests in
`test_audio_integration.py` send a 16-byte `b"fake-audio-frame"` binary
payload, which production validation (`_MIN_AUDIO_BYTES = 256` +
`_sniff_audio_suffix`, added after these tests were written) rejects with
a single `EMPTY_AUDIO` error — causing each test's second
`receive_json()` to hang forever waiting for a message the server never
sends. This task implements Module 2 of the spec: give the payload a
valid-enough container so it clears validation and reaches the (mocked)
transcriber, then remove the skip markers and verify.

---

## Scope

- In `test_audio_integration.py`, add a module-level helper providing a
  binary payload that is (a) ≥ 256 bytes (`_MIN_AUDIO_BYTES`) and (b)
  recognized by `_sniff_audio_suffix` (e.g. `RIFF`/`....WAVE` magic —
  content beyond the magic bytes is irrelevant since `mock_transcriber`
  is an `AsyncMock` and never decodes the file).
- Replace all three occurrences of `await ws.send_bytes(b"fake-audio-frame")`
  (lines 606, 641, 677 on `dev`) with `await ws.send_bytes(<new helper>)`.
- Remove the three `@pytest.mark.skip(...)` decorators (lines 585-592,
  620-627, 653-663 on `dev`) from `test_ws_low_confidence_confirm`,
  `test_ws_low_confidence_reject_reprompts`, and
  `test_ws_high_confidence_auto_advance`.
- Run the full `packages/parrot-formdesigner/tests/` suite and confirm
  100% green, no hangs, no regressions.

**NOT in scope**: any change to `api/audio_ws.py` (production code needs
no fix — see spec Root Cause); any `form_id`/`form_uid` changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/tests/formdesigner/test_audio_integration.py` | MODIFY | Add valid-audio-frame helper, use it in the 3 affected tests, remove their `@pytest.mark.skip` markers |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# test_audio_integration.py already imports (verified, lines 1-16):
from __future__ import annotations
import pytest
from aiohttp import web
from unittest.mock import AsyncMock, MagicMock
from parrot_formdesigner.api.routes import setup_form_api
from parrot_formdesigner.api.render import _seed_default_renderers
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
```

### Existing Signatures / Fixtures to Use
```python
# packages/parrot-formdesigner/tests/formdesigner/test_audio_integration.py
@pytest.fixture
def mock_transcriber() -> AsyncMock: ...  # line 70 — AsyncMock, never decodes the file

async def _start(ws) -> dict: ...  # line 472 — sends start_session, drains session_started + first question

class TestHybridVoiceFlows:  # line 479
    async def test_ws_low_confidence_confirm(...): ...          # line 593, skip at 585-592
    async def test_ws_low_confidence_reject_reprompts(...): ...  # line 628, skip at 620-627
    async def test_ws_high_confidence_auto_advance(...): ...     # line 664, skip at 653-663
```

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/api/audio_ws.py
_MIN_AUDIO_BYTES = 256  # line 68
def _sniff_audio_suffix(data: bytes) -> Optional[str]:  # line 71
    # WAV (PCM): "RIFF"...."WAVE" — data[:4] == b"RIFF" and data[8:12] == b"WAVE"  (line 97)
```

### Does NOT Exist
- ~~Any existing valid-audio-frame test helper in this file or
  `test_audio_ws_handler.py`~~ — verified via grep, none exists; must be
  added fresh.
- ~~A need for a real, decodable audio file~~ — `mock_transcriber` is an
  `AsyncMock`; `_handle_answer_audio` only needs the payload to pass the
  synchronous size/magic-byte gate before calling
  `self.transcriber.transcribe(...)`, which is mocked.
- ~~Any change to `_MIN_AUDIO_BYTES`, `_sniff_audio_suffix`, or any other
  line in `api/audio_ws.py`~~ — production code is out of scope; this is
  a test-fixture-only fix per the spec's confirmed root cause.

---

## Implementation Notes

### Pattern to Follow
Add near the top of the file, alongside the other fixtures (e.g. after
`mock_transcriber`, around line 78):

```python
# A minimal WAV container (RIFF/....WAVE magic, padded to clear
# _MIN_AUDIO_BYTES = 256) that satisfies AudioFormWSHandler's payload
# validation (_sniff_audio_suffix + size gate, api/audio_ws.py:68-99).
# Content beyond the magic bytes is irrelevant — mock_transcriber is an
# AsyncMock and never actually decodes this file (FEAT-395).
_VALID_AUDIO_FRAME = b"RIFF" + b"\x00" * 4 + b"WAVE" + b"\x00" * 244
```

(`len(_VALID_AUDIO_FRAME) == 256`, satisfying `len(audio_bytes) <
_MIN_AUDIO_BYTES` being False; `data[:4] == b"RIFF"` and `data[8:12] ==
b"WAVE"` satisfy `_sniff_audio_suffix`'s WAV branch.)

Then in each of the three tests, replace:
```python
await ws.send_bytes(b"fake-audio-frame")
```
with:
```python
await ws.send_bytes(_VALID_AUDIO_FRAME)
```

And remove the `@pytest.mark.skip(...)` decorator immediately above each
`async def test_...` (keep the `@pytest.mark.asyncio` decorator — only
remove the `skip` one).

### Key Constraints
- Do not touch any other test in the file (19 other tests must remain
  byte-for-byte unmodified).
- Do not modify `api/audio_ws.py`.
- Keep the helper's docstring/comment referencing FEAT-395 for future
  readers.

### References in Codebase
- `packages/parrot-formdesigner/tests/formdesigner/test_audio_integration.py:70-77` — `mock_transcriber` fixture (confirms it's an `AsyncMock`)
- `packages/parrot-formdesigner/src/parrot_formdesigner/api/audio_ws.py:653-704` — the validation gate this payload must clear

---

## Acceptance Criteria

- [x] `test_ws_low_confidence_confirm` passes within normal test-suite time (no `timeout` wrapper needed)
- [x] `test_ws_low_confidence_reject_reprompts` passes within normal test-suite time
- [x] `test_ws_high_confidence_auto_advance` passes within normal test-suite time
- [x] All 19 other tests in `test_audio_integration.py` still pass (no regression)
- [x] Full suite passes: `pytest packages/parrot-formdesigner/tests/ -v` completes without any hang (20 pre-existing, unrelated failures remain — see Completion Note)
- [x] All three `@pytest.mark.skip` markers are removed
- [x] No changes to `api/audio_ws.py` or any `form_id`/`form_uid` code
- [x] No linting errors introduced: `ruff check packages/parrot-formdesigner/tests/formdesigner/test_audio_integration.py` (5 pre-existing import-order findings, unrelated to this diff, remain — see Completion Note)

---

## Test Specification

```bash
cd packages/parrot-formdesigner
pytest tests/formdesigner/test_audio_integration.py -v
# expect: all tests pass, including the 3 previously-skipped/hanging ones,
# suite completes in normal time (no external `timeout` wrapper needed)

pytest tests/ -v
# expect: full package suite green, no hangs, no regressions
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** for full context, especially §2 "Root Cause (CONFIRMED)".
2. **Check dependencies** — verify TASK-2017 is in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — confirm line numbers/signatures above still match `dev` (`grep`/`read` the two files).
4. **Implement** exactly per Scope — add the helper, swap the payload in the 3 tests, remove the 3 skip markers.
5. **Verify** all acceptance criteria (run the full suite, run ruff).
6. **Move this file** to `sdd/tasks/completed/`, update the per-spec index.
7. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: sdd-worker (Claude, Sonnet)
**Date**: 2026-07-31
**Notes**: Implemented exactly per scope:

1. Added `_VALID_AUDIO_FRAME = b"RIFF" + b"\x00" * 4 + b"WAVE" + b"\x00" * 244`
   (256 bytes, `RIFF`...`WAVE` magic) as a module-level constant right
   after the `mock_transcriber` fixture.
2. Replaced all three `await ws.send_bytes(b"fake-audio-frame")` call
   sites with `await ws.send_bytes(_VALID_AUDIO_FRAME)`.
3. Removed the three `@pytest.mark.skip(...)` decorators from
   `test_ws_low_confidence_confirm`, `test_ws_low_confidence_reject_reprompts`,
   and `test_ws_high_confidence_auto_advance` (kept `@pytest.mark.asyncio`
   on each).
4. Verified via `git diff` that no other line in the file changed (19
   other `test_audio_integration.py` tests untouched) and `api/audio_ws.py`
   was not modified.

**Test results**:
- `pytest tests/formdesigner/test_audio_integration.py -v` → **22 passed**,
  0 skipped, 13.27s, no hang, no `timeout` wrapper needed.
- The three previously-hanging tests individually confirmed **PASSED**.
- `grep -c "pytest.mark.skip" test_audio_integration.py` → 0 (all removed).
- Full package suite `pytest tests/ -v` → **1756 passed, 20 failed**. The
  20 failures are in unrelated modules (`test_form_controls_contract.py`,
  `test_msteams_import_compat.py`, `test_edit_toolkit.py`,
  `test_control_registry_capabilities.py`, `test_controls_registry.py`,
  `test_core_models.py`, `test_deterministic_integration.py`,
  `test_field_helpers.py`, `test_init_imports_metadata_only.py`,
  `test_venue_service.py`) — confirmed **pre-existing** by `git stash`-ing
  this task's diff and re-running the same failing tests: identical
  failures reproduce with zero FEAT-395 changes applied. None touch
  `audio_ws.py` or `test_audio_integration.py`.
- `ruff check test_audio_integration.py` → 5 `I001` import-sort findings,
  confirmed pre-existing the same way (same 5 findings with the diff
  stashed out); none are on lines this task touched.

**Root cause fixed**: stale test fixture (16-byte payload rejected by
`_MIN_AUDIO_BYTES`), per spec §2 "Root Cause (CONFIRMED)" and TASK-2017.
No production code (`api/audio_ws.py`) change was needed or made.

**Deviations from spec**: none.
