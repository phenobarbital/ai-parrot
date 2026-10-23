# TASK-4632: Pipeline enforcement (closed check, guarded store, tenant flag)

**Feature**: FEAT-730 — FormDesigner public response controls
**Spec**: `sdd/specs/formdesigner-public-form-controls.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4630, TASK-4631
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 (+ the `SubmitOutcome.created_at` field Module 5 needs, which
lives in the same file). `SubmissionPipeline.submit` is the single commit path
for REST `/data` and the audio WS (FEAT-649). It must:
1. reject a CLOSED form before `onBeforeSubmit`, validation or any LLM call;
2. use `store_guarded` when the policy sets a cap or a key question;
3. stamp the URL tenant on the generic store ONLY when the new
   `tenant_scoped_submissions` flag is on (Juan, 2026-10-22: G8 behind a flag,
   default OFF; FieldSync passes True).

---

## Scope

- Add `SubmissionRejected(reason, message, *, field_id=None)` and export it.
- Add ctor kwarg `tenant_scoped_submissions: bool = False` to `SubmissionPipeline`.
- Add `created_at: datetime | None = None` to `SubmitOutcome`, filled with the stored submission's `created_at`.
- In `submit()`: fail-fast closed check; guarded store; tenant stamping behind the flag; map storage refusals.
- Re-raise `SubmissionRejected` untouched in the outer `except` (never routed to `onError`).
- Unit tests.

**NOT in scope**: HTTP 409 mapping and handler plumbing of the flag (TASK-4634),
audio WS mapping (TASK-4636), `on_submitted` (TASK-4635).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/submission_pipeline.py` | MODIFY | enforcement + flag + `created_at` |
| `packages/parrot-formdesigner/tests/unit/services/test_submission_pipeline_public_access.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

> Relative to `packages/parrot-formdesigner/src/parrot_formdesigner/`. Verified @ `685e6176c`
> (AFTER FEAT-728 merged — the spec's `:38/:137/:206/:259` lines moved; use these).

### Verified Imports
```python
from .submissions import FormSubmission, FormSubmissionStorage    # services/submission_pipeline.py (existing import)
# added by TASK-4631:
from .submissions import DuplicateResponse, ResponseLimitReached
# added by TASK-4630:
from ..core.public_access import RejectionReason, evaluate_open, normalize_key_value
```

### Existing Signatures to Use
```python
# services/submission_pipeline.py
__all__ = [                                       # line 44 (multi-line list; ends with "PlausibilityRateLimited",)
class SubmitOutcome(BaseModel):                   # line 55 — submission_id, stored_in, forwarded, ..., validation
class SubmitSinkError(Exception):                 # line 77 — (message, *, status, headers=None)
class PlausibilityRateLimited(Exception):         # line 115
class SubmissionPipeline:                         # line 126
    def __init__(self, *, validator, submission_storage, forwarder, partial_store, plausibility,
                 sink_factory=None, logger=None, dispatch_fn=None)            # line 129-138
    async def submit(self, form, data, *, tenant, user_id, locale, context, extra_data, auth_context,
                     merge_session_id, plausibility=None, plausibility_ack=False, request=None,
                     visit_context=None, submission_id=None, quota_check=None) -> SubmitOutcome  # line 230
    # auth = auth_context or AuthContext(scheme="none")              line 250
    # try: onBeforeSubmit dispatch                                   line 258-262
    # submission = FormSubmission(... created_at=datetime.now(timezone.utc), ...)   line 331-343 (no tenant=)
    # elif self.submission_storage is not None:
    #     await self.submission_storage.store(submission)             line 391
    #     stored_in = "generic"
    # return SubmitOutcome(...)                                       line 431
    # except (FormEventAbort, ValidationFailed, SubmitSinkError, PlausibilityBlocked,
    #         ImplausibleSubmission, PlausibilityRateLimited): raise  line 440-448
```

### Does NOT Exist
- ~~`SubmissionRejected`, `tenant_scoped_submissions`, `SubmitOutcome.created_at`~~ — added here.
- ~~A tenant on the pipeline-built `FormSubmission`~~ — today it is built WITHOUT `tenant=`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/services/submission_pipeline.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/unit/services/test_submission_pipeline_public_access.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/submission_pipeline.py#SubmissionPipeline",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/submission_pipeline.py#SubmissionPipeline.submit",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/submission_pipeline.py#SubmitOutcome"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Closed check goes BEFORE the `try:` that dispatches `onBeforeSubmit` (right after `auth = …`),
  so a lifecycle handler cannot reopen a closed form, no validator/LLM runs, and `onError` is never dispatched.
- Policy "needs counting" = `public_access` set AND (`max_responses` or `unique_key_field`).
  Needs counting and `submission_storage is None` → `SubmitSinkError(..., status=501)`.
- Flag OFF → byte-for-byte today's behaviour (`store(submission)`, no tenant); `store_guarded(..., tenant=None)`.
- `submit()` is long already (Rule 4): put the persist decision in a private helper
  `_store_generic(form, submission, data, tenant) -> None`, not inline branches.

---

## Implementation Blueprint

### Steps (in order)
1. Add the import lines and `SubmissionRejected`; extend `__all__` — *why*: hosts and handlers import it from here.
2. Add `created_at` to `SubmitOutcome` — *why*: TASK-4635 reports the stored timestamp without re-reading storage.
3. Add the ctor kwarg — *why*: the handler (TASK-4634) passes the host's flag through `_build_submission_pipeline`.
4. Insert the closed check after `auth = …` — *why*: AC2 (no LLM call, nothing stored).
5. Replace the generic-store line by `await self._store_generic(...)` — *why*: keeps `submit()` inside the complexity budget.
6. Add `SubmissionRejected` to the re-raise tuple; set `created_at=submission.created_at` on the outcome.

### `packages/parrot-formdesigner/src/parrot_formdesigner/services/submission_pipeline.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from .submissions import FormSubmission, FormSubmissionStorage' services/submission_pipeline.py)
# AFTER — insert below `from .submissions import FormSubmission, FormSubmissionStorage`
from .submissions import DuplicateResponse, ResponseLimitReached
from ..core.public_access import RejectionReason, evaluate_open, normalize_key_value
```
```python
# occurrences: 1 (verified: grep -c '    "PlausibilityRateLimited",' services/submission_pipeline.py — inside __all__ at :44-52)
# AFTER — insert below `    "PlausibilityRateLimited",` in __all__
    "SubmissionRejected",
```
```python
# occurrences: 1 (verified: grep -c 'class PlausibilityRateLimited(Exception):' services/submission_pipeline.py)
# BEFORE — insert above `class PlausibilityRateLimited(Exception):` (verified: :115)
class SubmissionRejected(Exception):
    """Response-policy refusal (HTTP 409, FEAT-730). Controlled flow — never dispatched to onError."""

    def __init__(self, reason: RejectionReason, message: str, *, field_id: str | None = None) -> None:
        super().__init__(message)
        self.reason: RejectionReason = reason
        self.field_id = field_id
```
```python
# occurrences: 1 (verified: grep -c '    validation: ValidationResult' services/submission_pipeline.py)
# AFTER — insert below `    validation: ValidationResult` (SubmitOutcome, :66)
    created_at: datetime | None = None  # FEAT-730: the stored submission's created_at (UTC)
```
```python
# occurrences: 1 (verified: grep -c '        sink_factory: "SinkFactory | None" = None,' services/submission_pipeline.py)
# AFTER — insert below `        sink_factory: "SinkFactory | None" = None,` (verified: :137)
        tenant_scoped_submissions: bool = False,
# and in the body, after `        self.sink_factory = sink_factory`:
        # FEAT-730 G8: stamp the URL tenant on the generic store only when the host opts in.
        self.tenant_scoped_submissions = tenant_scoped_submissions
```
```python
# occurrences: 1 (verified: grep -c '        auth = auth_context or AuthContext(scheme="none")' services/submission_pipeline.py)
# AFTER — insert below `        auth = auth_context or AuthContext(scheme="none")` (verified: :250)
        # FEAT-730: a closed form is refused before onBeforeSubmit / validation / any LLM call.
        if evaluate_open(form.public_access, now=datetime.now(timezone.utc)) == "form_closed":
            raise SubmissionRejected("form_closed", "This form is no longer accepting responses.")
```
```python
# occurrences: 1 (verified: grep -c '                await self.submission_storage.store(submission)' services/submission_pipeline.py)
# REPLACE — `                await self.submission_storage.store(submission)` (verified: :391) with:
                await self._store_generic(form, submission, data, tenant)
```
```python
# occurrences: 1 (verified: grep -c '            PlausibilityRateLimited,' services/submission_pipeline.py — the re-raise tuple, :446)
# AFTER — insert below `            PlausibilityRateLimited,` inside `except (` (verified: :446)
            SubmissionRejected,
```
```python
# occurrences: 1 (verified: grep -c '            return SubmitOutcome(' services/submission_pipeline.py)
# inside `return SubmitOutcome(...)` (:431) add the keyword:
                created_at=submission.created_at,
```
```python
# new private method — insert right after `async def submit(...)` ends (before `def attach_verdicts`, :463)
    async def _store_generic(self, form: FormSchema, submission: FormSubmission, data: dict[str, Any],
                             tenant: str | None) -> None:
        """Generic-store branch (FEAT-730): tenant stamping behind the flag; guarded store when the
        form's public_access needs counting. Maps storage refusals to SubmissionRejected."""
        storage = self.submission_storage
        assert storage is not None  # caller checked
        store_tenant = tenant if self.tenant_scoped_submissions else None
        if store_tenant is not None:
            submission.tenant = store_tenant
        cfg = form.public_access
        if cfg is None or (cfg.max_responses is None and cfg.unique_key_field is None):
            if store_tenant is None:
                await storage.store(submission)  # today's exact call (AC1 / AC8 flag off)
            else:
                await storage.store(submission, tenant=store_tenant)
            return
        # FILL IN: unique_value = normalize_key_value(data.get(cfg.unique_key_field)) when the key is set;
        # await storage.store_guarded(submission, tenant=store_tenant, max_responses=cfg.max_responses,
        # unique_key_field=cfg.unique_key_field, unique_value=unique_value);
        # ResponseLimitReached -> SubmissionRejected("response_limit_reached", ...);
        # DuplicateResponse as exc -> SubmissionRejected("duplicate_response", ..., field_id=exc.field_id).
```
**Why**: the policy check is centralised here so the REST and audio channels get it
for free; the flag-off branch keeps the old call literally unchanged.

### FILL IN checklist
- [ ] `SubmissionRejected` entry in the re-raise tuple
- [ ] Guarded-store branch + exception mapping — AC3/AC4
- [ ] `needs counting` with `submission_storage is None` → `SubmitSinkError(status=501)` (place it where the
      `elif self.submission_storage is not None` branch is decided — bounded by spec §3 M3)
- [ ] Test bodies

### `packages/parrot-formdesigner/tests/unit/services/test_submission_pipeline_public_access.py` (CREATE)
```python
"""FEAT-730 — pipeline enforcement of public_access."""
import pytest

from parrot_formdesigner.services.submission_pipeline import SubmissionPipeline, SubmissionRejected


# FILL IN: fixture building a SubmissionPipeline with a fake storage recording store/store_guarded calls,
# a spy validator, plausibility=None and a dispatch_fn spy (copy the construction used in
# tests/formdesigner/test_submission_pipeline_parity.py).

async def test_submit_closed_before_validation(): ...      # validator + plausibility never called, onError not dispatched
async def test_generic_store_receives_tenant(): ...       # flag True -> store/store_guarded get the URL tenant (mutation: drop kwarg -> RED)
async def test_generic_store_flag_off_unchanged(): ...    # default -> store(submission) exactly, no tenant kwarg
async def test_limit_maps_to_rejection(): ...             # ResponseLimitReached -> reason "response_limit_reached"
async def test_duplicate_maps_to_rejection(): ...         # DuplicateResponse("email") -> reason + field_id "email"
async def test_outcome_carries_created_at(): ...
```

---

## Acceptance Criteria

- [ ] Closed form → `SubmissionRejected("form_closed")`, nothing validated/stored, no `onError` (AC2).
- [ ] Flag OFF → `store(submission)` exactly as today (AC1, AC8).
- [ ] Flag ON → URL tenant on `store`/`store_guarded` (AC8).
- [ ] Refusals map to the three reason codes (AC3, AC4).

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/unit/services/test_submission_pipeline_public_access.py -q`
- `pytest packages/parrot-formdesigner/tests/formdesigner/test_submission_pipeline_parity.py -q`

---

## Test Specification

See the CREATE block (spec §4 Module 3 rows). Mutation-check `test_generic_store_receives_tenant`.

---

## Agent Instructions

1. Feature worktree; confirm TASK-4630 and TASK-4631 are `done`.
2. Re-run every `grep -c` (FEAT-728 moved this file once already).
3. Implement; run Validation Commands; commit only the listed files.
4. `scripts/sdd/close_task.sh TASK-4632 formdesigner-public-form-controls verified`.

---

## Completion Note

Implemented per blueprint. Tests: test_submission_pipeline_public_access.py 8 passed; test_submission_pipeline_parity.py 21 passed (baseline 21 passed). Mutation checks (6: tenant kwarg dropped, guarded tenant dropped, SubmissionRejected not re-raised, flag ignored, created_at dropped, closed check removed) all RED.
Deviations (minor): the guarded-store key value is read from `unwrap_voice(submission.data)` (sanitized/stored view) rather than the raw `data` payload, so voice envelopes and coerced values are compared as stored. Added an extra test for the 501 (counting policy without storage) and key normalization. ruff not installed in the venv; not run.
