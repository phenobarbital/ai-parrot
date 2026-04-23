# TASK-839: `FormAPIHandler.submit_data` pipeline rewrite + `_run_submission_pipeline`

**Feature**: FEAT-121 — Parrot FormDesigner POST Submission Pipeline
**Spec**: `sdd/specs/parrot-formdesigner-post-method.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: XL (> 8h)
**Depends-on**: TASK-834, TASK-835, TASK-836, TASK-837
**Assigned-to**: unassigned

---

## Context

This task is the heart of FEAT-121. `FormAPIHandler.submit_data` (`api.py:446-535`) is rewritten
to branch between the legacy `FormValidator` path and the new operator pipeline path. The new
path is implemented in a helper `_run_submission_pipeline(request, form, data, conn)` that
acquires a connection + transaction, runs operator hooks around typed Pydantic validation,
persists via `FormResultStorage.store(..., conn=conn)`, and writes to the DLQ on any failure.

Legacy callers — those that do not pass `operators=` or `pydantic_resolver=` at handler init —
MUST see byte-for-byte identical behavior. Spec §2 Overview, §2 Component Diagram, §3 Module 6,
§5 Acceptance Criteria.

---

## Scope

- Extend `FormAPIHandler.__init__` to accept two new keyword-only kwargs (after `*`):
  `operators: list[FormOperator] | None = None`,
  `pydantic_resolver: PydanticModelResolver | None = None`.
- Store them as `self._operators = list(operators or [])` and `self._pydantic_resolver = pydantic_resolver`.
- Rewrite `submit_data` body so it:
  - Returns early with 404/400 exactly as today (unchanged).
  - Branches to `_run_submission_pipeline(...)` when `self._operators or self._pydantic_resolver`.
  - Otherwise runs the current `FormValidator` path unchanged (byte-compatible — covered by a
    golden-fixture test).
- Implement `_run_submission_pipeline(self, request, form, data)` as an async method that:
  1. Resolves a Pydantic model via `self._pydantic_resolver.resolve(form.form_id, form.version, form)`
     if a resolver is configured; falls back to the legacy `FormValidator` path when resolver
     returns `None` or is not configured but operators are.
  2. Builds an `OperatorContext(request=request, form_schema=form)`.
  3. Acquires a connection from `self._submission_storage._pool` and opens a transaction.
  4. Iterates operators in order: `pre_validate → validate → post_validate → build FormSubmission
     → pre_save → storage.store(..., conn=conn) → post_save(conn=conn)`.
  5. On success, commits (implicit `async with conn.transaction():`); returns an extended
     200 JSON response (fields defined in spec §2 Response Contract).
  6. On any exception after step 3, lets the transaction roll back, then calls
     `self._submission_storage.store_dlq(...)` in a separate `acquire()` + `transaction()`;
     returns 422 for validation errors (with `dlq_id`), 500 for operator/storage errors
     (with `dlq_id`), or 503 if the DLQ write itself fails.
- Preserve the forwarder path (`self._forwarder`) as a post-commit step — unchanged.
- Extensive logging at each stage using `self.logger`.

**NOT in scope**:
- Route registration changes (TASK-840 handles `setup_form_routes`).
- New tests at integration level (TASK-841).
- Implementing a decorator-based operator registry.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot/formdesigner/handlers/api.py` | MODIFY | Extend `__init__`; rewrite `submit_data`; add `_run_submission_pipeline` |
| `packages/parrot-formdesigner/tests/unit/test_submit_data_pipeline.py` | CREATE | Unit tests incl. legacy-byte-compat golden fixture |
| `packages/parrot-formdesigner/tests/fixtures/submit_data_legacy_response.json` | CREATE | Golden fixture for legacy-path assertion |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Additions inside handlers/api.py
from typing import TYPE_CHECKING
import traceback
import uuid

if TYPE_CHECKING:
    from parrot.formdesigner.operators import FormOperator, OperatorContext
    from parrot.formdesigner.services.pydantic_resolver import PydanticModelResolver
```

At **call sites** inside `_run_submission_pipeline`, import lazily:

```python
from parrot.formdesigner.operators import OperatorContext  # avoid circular imports
```

### Existing Signatures to Use

```python
# packages/parrot-formdesigner/src/parrot/formdesigner/handlers/api.py:85-116
class FormAPIHandler:
    def __init__(
        self,
        registry: FormRegistry,
        client: "AbstractClient | None" = None,
        submission_storage: "FormSubmissionStorage | None" = None,
        forwarder: "SubmissionForwarder | None" = None,
    ) -> None: ...
```

```python
# packages/parrot-formdesigner/src/parrot/formdesigner/handlers/api.py:446-535 (current submit_data — to rewrite)
async def submit_data(self, request: web.Request) -> web.Response:
    form_id = request.match_info["form_id"]
    form = await self.registry.get(form_id)
    if form is None:
        return web.json_response({"error": f"Form '{form_id}' not found"}, status=404)
    try:
        data = await request.json()
    except (json.JSONDecodeError, ValueError):
        return web.json_response({"error": "Invalid JSON body"}, status=400)
    result = await self.validator.validate(form, data)
    if not result.is_valid:
        return web.json_response({"is_valid": False, "errors": result.errors}, status=422)
    submission = FormSubmission(
        submission_id=str(uuid.uuid4()),
        form_id=form_id,
        form_version=form.version,
        data=result.sanitized_data,
        is_valid=True,
        created_at=datetime.now(timezone.utc),
    )
    if self._submission_storage is not None:
        await self._submission_storage.store(submission)
    # forwarder branch...
    return web.json_response({...})  # 200 OK
```

Post-TASK-835 / TASK-836 / TASK-837 additions you can rely on:

```python
# FormSubmission (extended — TASK-835)
class FormSubmission(BaseModel):
    ...  # now includes user_id, org_id, program, client, status, enrichment

# FormSubmissionStorage (extended — TASK-835)
class FormSubmissionStorage(FormResultStorage):
    async def store(self, submission, *, conn=None) -> str: ...
    async def store_dlq(self, form_id, form_version, raw_payload, stage, error,
                        traceback, correlation_id) -> str: ...

# FormOperator (TASK-836)
class FormOperator(ABC):
    async def pre_validate(self, payload, ctx) -> dict: ...
    async def post_validate(self, validated, ctx): ...
    async def pre_save(self, submission, ctx) -> FormSubmission: ...
    async def post_save(self, submission, ctx, *, conn) -> None: ...

# OperatorContext (TASK-836)
class OperatorContext(BaseModel):
    request: Any
    form_schema: FormSchema
    user_id: int | None = None
    org_id: int | None = None
    programs: list[str] = []
    scratchpad: dict[str, Any] = {}

# PydanticModelResolver (TASK-837)
class PydanticModelResolver:
    async def resolve(self, form_id, version, schema) -> type[BaseModel] | None: ...
```

### Does NOT Exist (before this task)
- ~~`FormAPIHandler._run_submission_pipeline`~~ — created here.
- ~~`FormAPIHandler._operators` / `._pydantic_resolver` attributes~~ — added here.
- ~~A `PipelineRunner` utility class~~ — the pipeline is a helper method on the handler, not a
  separate class.
- ~~New route `POST /api/v1/forms/{form_id}`~~ — do not add. Spec §1 Non-Goals.

---

## Implementation Notes

### Routing inside `submit_data`

```python
async def submit_data(self, request):
    form_id = request.match_info["form_id"]
    form = await self.registry.get(form_id)
    if form is None:
        return web.json_response({"error": f"Form '{form_id}' not found"}, status=404)
    try:
        data = await request.json()
    except (json.JSONDecodeError, ValueError):
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    use_pipeline = bool(self._operators) or self._pydantic_resolver is not None
    if use_pipeline:
        return await self._run_submission_pipeline(request, form, data)

    # ---- LEGACY PATH (unchanged byte-for-byte) ----
    # keep the current implementation verbatim
    ...
```

### Pipeline helper sketch

```python
async def _run_submission_pipeline(self, request, form, data):
    correlation_id = str(uuid.uuid4())
    stage = "resolve_model"
    ctx = None
    try:
        # 1. Resolve model
        model_cls = None
        if self._pydantic_resolver is not None:
            model_cls = await self._pydantic_resolver.resolve(form.form_id, form.version, form)

        from parrot.formdesigner.operators import OperatorContext
        ctx = OperatorContext(request=request, form_schema=form)

        pool = self._submission_storage._pool
        async with pool.acquire() as conn:
            async with conn.transaction():
                # 2. pre_validate hooks
                stage = "pre_validate"
                payload = data
                for op in self._operators:
                    payload = await op.pre_validate(payload, ctx)

                # 3. validate
                stage = "validate"
                if model_cls is not None:
                    validated = model_cls.model_validate(payload)
                    sanitized = validated.model_dump()
                else:
                    # fallback to FormValidator
                    result = await self.validator.validate(form, payload)
                    if not result.is_valid:
                        raise _ValidationError(result.errors)
                    validated = None  # legacy path has no typed model
                    sanitized = result.sanitized_data

                # 4. post_validate
                stage = "post_validate"
                for op in self._operators:
                    validated = await op.post_validate(validated, ctx) if validated else validated

                # 5. build submission
                submission = FormSubmission(
                    submission_id=str(uuid.uuid4()),
                    form_id=form.form_id,
                    form_version=form.version,
                    data=sanitized,
                    is_valid=True,
                    status="submitted",
                    created_at=datetime.now(timezone.utc),
                )

                # 6. pre_save
                stage = "pre_save"
                for op in self._operators:
                    submission = await op.pre_save(submission, ctx)

                # 7. store
                stage = "store"
                await self._submission_storage.store(submission, conn=conn)

                # 8. post_save
                stage = "post_save"
                for op in self._operators:
                    await op.post_save(submission, ctx, conn=conn)

        # 9. forwarder (post-commit, existing behavior)
        forwarded, forward_status, forward_error = await self._run_forwarder(form, sanitized)

        return web.json_response({
            "submission_id": submission.submission_id,
            "form_id": form.form_id,
            "form_version": form.version,
            "is_valid": True,
            "forwarded": forwarded,
            "forward_status": forward_status,
            "forward_error": forward_error,
            "status": submission.status,
            "operators_applied": [type(op).__name__ for op in self._operators],
        })

    except _ValidationError as ve:
        await self._dlq(form, data, stage, repr(ve), traceback.format_exc(), correlation_id)
        return web.json_response(
            {"is_valid": False, "errors": ve.errors, "dlq_id": correlation_id}, status=422,
        )
    except Exception as exc:
        dlq_ok = await self._dlq(form, data, stage, repr(exc), traceback.format_exc(), correlation_id)
        status = 500 if dlq_ok else 503
        return web.json_response(
            {"error": f"Submission pipeline failed at stage {stage!r}", "dlq_id": correlation_id},
            status=status,
        )
```

### DLQ helper

`_dlq(...)` acquires its own connection and transaction (because the main txn was rolled back
when the exception bubbled out of the nested `async with`). If it also fails, return `False` so
the caller can respond 503.

### Key Constraints
- **Legacy byte-compat is non-negotiable.** Add a golden-fixture test that compares the full
  JSON body of `submit_data` when `operators` and `pydantic_resolver` are both `None`.
- `_run_submission_pipeline` must NOT acquire more than one main connection. `post_save` gets
  the SAME `conn` that `store()` used (spec §7 "Operators-in-transaction").
- All operator exceptions are caught by the outer `try/except` and routed to DLQ.
- 400 for JSON decode errors must happen **before** entering the pipeline (existing behavior
  preserved).
- 404 for unknown form must happen **before** entering the pipeline (existing behavior preserved).
- `operators_applied` in the response body is the list of operator class names (`type(op).__name__`).
- Use `self.logger` liberally — debug lines on every stage transition.
- Do NOT break the forwarder path.

### References in Codebase
- `packages/parrot-formdesigner/src/parrot/formdesigner/handlers/api.py:446-535` — current code.
- `packages/parrot-formdesigner/src/parrot/formdesigner/services/submissions.py` — post-835 shape.

---

## Acceptance Criteria

- [ ] `FormAPIHandler.__init__` accepts `operators`, `pydantic_resolver` keyword-only kwargs,
      both defaulting to `None`. Positional signature unchanged.
- [ ] `self._operators` is always a list; `self._pydantic_resolver` may be None.
- [ ] With both kwargs None, `submit_data` response body matches the golden fixture byte-for-byte
      (legacy byte-compat).
- [ ] With operators configured, hooks fire in order `pre_validate → validate → post_validate →
      pre_save → store → post_save`; verified by a recording operator in tests.
- [ ] `storage.store()` is called with `conn=conn` (shared transaction); storage NOT called
      twice.
- [ ] On operator exception after the main transaction is open, the transaction rolls back and
      `storage.store_dlq()` is called with `stage` reflecting the failed step.
- [ ] Response is 422 `{is_valid: false, errors: ..., dlq_id}` on Pydantic validation failure.
- [ ] Response is 500 `{error, dlq_id}` on operator/storage failure.
- [ ] Response is 503 when DLQ write also fails.
- [ ] Forwarder path works when a pipeline run succeeds (`forwarded` key populated).
- [ ] All unit tests pass: `pytest packages/parrot-formdesigner/tests/unit/test_submit_data_pipeline.py -v`.
- [ ] Existing `submit_data` tests still pass (regression).
- [ ] `ruff check packages/parrot-formdesigner/src/parrot/formdesigner/handlers/api.py` clean.

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/test_submit_data_pipeline.py
import json
import pytest
from aiohttp.test_utils import make_mocked_request
from unittest.mock import AsyncMock, MagicMock

from parrot.formdesigner.handlers.api import FormAPIHandler
from parrot.formdesigner.operators import FormOperator, OperatorContext
from parrot.formdesigner.services.submissions import FormSubmission


class RecordingOperator(FormOperator):
    def __init__(self, trace):
        self._trace = trace

    async def pre_validate(self, payload, ctx):
        self._trace.append("pre_validate")
        return payload

    async def post_validate(self, validated, ctx):
        self._trace.append("post_validate")
        return validated

    async def pre_save(self, submission, ctx):
        self._trace.append("pre_save")
        return submission

    async def post_save(self, submission, ctx, *, conn):
        self._trace.append("post_save")


class TestLegacyByteCompat:
    async def test_no_operators_no_resolver_matches_golden(self, ...):
        """With both kwargs None, response matches golden fixture."""
        ...


class TestPipelineOrdering:
    async def test_hooks_fire_in_expected_order(self, ...):
        trace = []
        op = RecordingOperator(trace)
        handler = FormAPIHandler(registry=..., submission_storage=..., operators=[op])
        ...
        assert trace == ["pre_validate", "post_validate", "pre_save", "post_save"]


class TestPipelineErrorHandling:
    async def test_operator_raise_returns_500_with_dlq_id(self, ...): ...
    async def test_validation_failure_returns_422_with_dlq_id(self, ...): ...
    async def test_dlq_write_failure_returns_503(self, ...): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path above (§2 Overview, §2 Component Diagram, §3 Module 6, §5 AC).
2. **Check dependencies** — TASK-834, TASK-835, TASK-836, TASK-837 all in `completed/`.
3. **Verify the Codebase Contract** — re-read `handlers/api.py:85-535` to confirm the current
   `submit_data` body matches the contract, and that the extended `FormSubmissionStorage.store`
   signature is as described after TASK-835.
4. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`.
5. **Implement** `__init__` kwargs, the `submit_data` router, `_run_submission_pipeline`, `_dlq`
   helper, and tests.
6. **Capture the golden fixture** FIRST (run today's `submit_data` once and record its exact
   JSON body into `tests/fixtures/submit_data_legacy_response.json`) so your byte-compat test
   is actually valid.
7. **Verify** all acceptance criteria.
8. **Move this file** to `sdd/tasks/completed/TASK-839-submit-data-pipeline-rewrite.md`.
9. **Update index** → `"done"`.
10. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
