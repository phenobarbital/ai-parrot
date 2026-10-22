# TASK-4636: Audio WS — map `SubmissionRejected` to `IOFailed`

**Feature**: FEAT-730 — FormDesigner public response controls
**Spec**: `sdd/specs/formdesigner-public-form-controls.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4632
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 (audio part). The audio-form WebSocket (FEAT-649) submits
through the same `SubmissionPipeline`, so response controls apply there too.
Today an unknown exception falls to the broad `except Exception` and the user
sees `SUBMIT_FAILED`. A policy refusal must instead surface as
`IOFailed(code="FORM_CLOSED" | "RESPONSE_LIMIT_REACHED" | "DUPLICATE_RESPONSE")`.

---

## Scope

- Import `SubmissionRejected` in `api/audio_ws.py`.
- Add an `except SubmissionRejected` arm in the server-submit except chain, ABOVE the broad `except Exception`.
- Test.

**NOT in scope**: `on_submitted` for audio (REST only).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/audio_ws.py` | MODIFY | import + except arm |
| `packages/parrot-formdesigner/tests/formdesigner/test_audio_ws_public_access.py` | CREATE | test |

---

## Codebase Contract (Anti-Hallucination)

> Relative to `packages/parrot-formdesigner/src/parrot_formdesigner/`. Verified @ `685e6176c` (after FEAT-728).

### Verified Imports
```python
from ..services.submission_pipeline import ImplausibleSubmission, SubmissionPipeline, ValidationFailed  # api/audio_ws.py:100 (count 1)
# SubmissionRejected — added to submission_pipeline by TASK-4632 (reason: RejectionReason, field_id)
```

### Existing Signatures to Use
```python
# api/audio_ws.py — server submit (~:1192-1222)
#   outcome = await self._pipeline_for().submit(form, data, tenant=ctx.tenant, ...)
#   except ValidationFailed as exc: return SubmitDone(...)
#   except PlausibilityBlocked as exc: return IOFailed(type="_io_failed", request=item.type, code="PLAUSIBILITY_UNAVAILABLE", detail=exc.reason)   # 2nd of 2 occurrences (:1210)
#   except ImplausibleSubmission as exc: return IOFailed(type="_io_failed", request=item.type, code=exc.code, detail="implausible answers")  # :1212 — "MUST stay above the broad except"
#   except Exception as exc:  # noqa: BLE001 — ... -> IOFailed(code="SUBMIT_FAILED")
```
Test harness: `tests/formdesigner/test_audio_plausibility_policy.py` (drives the server submit with a fake pipeline).

### Does NOT Exist
- ~~A `FORM_CLOSED` code constant~~ — use `exc.reason.upper()`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/api/audio_ws.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/formdesigner/test_audio_ws_public_access.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Extend the import — *why*: the arm needs the class.
2. Add the arm right after the `ImplausibleSubmission` arm — *why*: it must precede the broad `except Exception`.
3. Test with a fake pipeline raising each reason.

### `packages/parrot-formdesigner/src/parrot_formdesigner/api/audio_ws.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from ..services.submission_pipeline import ImplausibleSubmission, SubmissionPipeline, ValidationFailed' api/audio_ws.py)
# REPLACE that line (verified: :100) with:
from ..services.submission_pipeline import (
    ImplausibleSubmission,
    SubmissionPipeline,
    SubmissionRejected,
    ValidationFailed,
)
```
```python
# occurrences: 1 (verified: grep -c '            return IOFailed(type="_io_failed", request=item.type, code=exc.code, detail="implausible answers")' api/audio_ws.py)
# AFTER — insert below that line (the ImplausibleSubmission arm, :1215)
        except SubmissionRejected as exc:
            # FEAT-730 — response-policy refusal (closed / limit / duplicate). MUST stay above the broad except.
            return IOFailed(type="_io_failed", request=item.type, code=exc.reason.upper(), detail=str(exc))
```

### `packages/parrot-formdesigner/tests/formdesigner/test_audio_ws_public_access.py` (CREATE)
```python
"""FEAT-730 — audio WS maps SubmissionRejected to IOFailed."""
# FILL IN: reuse the fake-pipeline setup of tests/formdesigner/test_audio_plausibility_policy.py.

async def test_audio_ws_rejection_io_failed(): ...   # form_closed -> IOFailed(code="FORM_CLOSED"); also the other two reasons
```

### FILL IN checklist
- [ ] Test body

---

## Acceptance Criteria

- [ ] Each reason maps to its upper-case `IOFailed` code; never `SUBMIT_FAILED`.

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/formdesigner/test_audio_ws_public_access.py -q`
- `pytest packages/parrot-formdesigner/tests/formdesigner/test_audio_plausibility_policy.py -q`

---

## Test Specification

Spec §4 row `test_audio_ws_rejection_ioFailed`.

---

## Agent Instructions

1. Feature worktree; TASK-4632 must be `done`.
2. Re-grep anchors; implement; run Validation Commands; commit only the listed files.
3. `scripts/sdd/close_task.sh TASK-4636 formdesigner-public-form-controls verified`.

---

## Completion Note

*(Agent fills this in when done)*
